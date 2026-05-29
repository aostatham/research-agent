"""
Verification loop for the Verifier Agent and Graph Verifier Agent.

Public API:
  verify()                    — web Verifier Agent on a ResearchResult (D010)
  graph_verify()              — Graph Verifier Agent: checks claims against
                                knowledge graph before web verification (D041)
  _extract_suspicious_claims() — heuristic claim selector (testable)
"""

import json
import logging
import re
import time
import warnings
from typing import Optional

from agent.base import Agent
from agent.tool_utils import _validate_tool_input
from agent.tools import build_tool_list, execute_tool_with_sources
from evidence.schema import ResearchResult
from observability.events import log_event


# Exact status strings that represent a refuted claim.
# The prompt (prompts/verifier.md) instructs the model to emit only "verified",
# "unverified", or "refuted". The additional synonyms below are defensive
# coverage in case the model goes off-script — they do not widen the happy path.
# "disputed" maps correctly by coincidence: provenance.py maps "refuted" ->
# verification_status="disputed", so accepting "disputed" here is consistent.
_REFUTED_STATUSES = frozenset({
    "refuted", "false", "incorrect", "disputed",
    "contradicted", "wrong", "inaccurate",
})

# Absolute terms that suggest a claim is worth verifying (D010).
_ABSOLUTE_TERMS = frozenset({
    "first", "only", "always", "never", "largest", "smallest",
    "biggest", "all", "none", "every", "exclusively", "unique",
    "impossible", "guaranteed", "certain",
})


def _extract_suspicious_claims(
    answer: str,
    question: str,
    max_claims: int = 3,
) -> list[str]:
    """
    Extract up to max_claims suspicious sentences from an answer.

    Heuristics (D010):
      +1  Contains a digit (number or statistic)
      +1  Uses an absolute term (first, only, always, never, etc.)
      +1  Contains a capitalised word not present in the question
          (named-entity proxy)

    Sentences are ranked by total score; only sentences scoring > 0 are
    returned.  Sentences are split on terminal punctuation followed by
    whitespace.

    Args:
        answer:     The researcher's answer text.
        question:   The original research question (used for entity filtering).
        max_claims: Maximum number of sentences to return.

    Returns:
        List of suspicious sentence strings, highest-scored first.
    """
    if not answer.strip():
        return []

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", answer) if s.strip()]
    question_words = set(question.lower().split())

    def _score(sentence: str) -> int:
        score = 0
        if re.search(r"\d", sentence):
            score += 1
        lower_words = set(sentence.lower().split())
        if lower_words & _ABSOLUTE_TERMS:
            score += 1
        # Named-entity proxy: capitalised word (len > 1) not in question
        if any(
            w[0].isupper() and w.lower() not in question_words
            for w in sentence.split()
            if len(w) > 1
        ):
            score += 1
        return score

    scored = sorted(sentences, key=_score, reverse=True)
    return [s for s in scored[:max_claims] if _score(s) > 0]


# Matching strategy for _is_refuted and _is_confirmed (L1):
# Both functions resolve the status field by checking keys in priority order:
#   status, verification_status, verdict, summary
# Both use exact frozenset membership against their respective frozensets.
# Neither uses substring matching.


def _is_refuted(result_item) -> bool:
    """Return True if the verification result indicates a refuted claim.

    Uses exact frozenset lookup against _REFUTED_STATUSES (H4) to avoid
    false positives from substring matching. Checks status/summary fields
    in priority order. If none of the recognised field names are present,
    returns False (no guessing from unrecognised fields — M6).
    """
    if not isinstance(result_item, dict):
        return False
    for field in ("status", "verification_status", "verdict", "summary"):
        val = result_item.get(field)
        if val is not None:
            return isinstance(val, str) and val.lower().strip() in _REFUTED_STATUSES
    logging.debug(
        "Verifier result missing recognised status field — treating as unverified"
    )
    return False


# Exact status strings that represent an explicit confirmation.
# Uses a frozenset to avoid "verified" in "unverified" false-positive.
_CONFIRMED_STATUSES = frozenset({
    "verified", "confirmed", "true", "yes", "supported", "correct",
})


def _is_confirmed(result_item) -> bool:
    """Return True if the verification result explicitly confirms a claim (M4).

    Uses exact-match against _CONFIRMED_STATUSES to avoid the false-positive
    where 'verified' appears as a substring of 'unverified'.
    """
    if not isinstance(result_item, dict):
        return False
    for field in ("status", "verification_status", "verdict", "summary"):
        val = result_item.get(field)
        if val is not None:
            return isinstance(val, str) and val.lower().strip() in _CONFIRMED_STATUSES
    return False


def verify(
    agent: Agent,
    rr: ResearchResult,
    max_tokens: int = 2048,
) -> ResearchResult:
    """
    Run the Verifier Agent on a ResearchResult to check suspicious claims.

    If no suspicious claims are found, leaves rr.verification = "unverified"
    and returns immediately (no LLM calls).  Otherwise runs an agentic loop:

      1. The agent receives the question, answer, and flagged claims.
      2. The agent may call web_search (once per claim at most).
      3. When the agent returns a text response it is parsed as JSON.
      4. If any result has status "refuted", verification is set to "refuted".
      5. On JSON parse failure, verification stays "unverified" (M1).
      6. If max_iterations is exhausted without a text response, verification
         stays "unverified" (M1).

    Args:
        agent:      Verifier Agent with llm and max_iterations configured.
        rr:         ResearchResult from the Researcher (mutated in place).
        max_tokens: Token budget per LLM call.

    Returns:
        The same ResearchResult with verification field updated.
    """
    start = time.time()
    suspicious = _extract_suspicious_claims(rr.answer, rr.question)
    if not suspicious:
        # No claims flagged by heuristic — leave as "unverified" not
        # falsely "verified". A heuristic miss does not equal a
        # verification pass.
        rr.verification = "unverified"
        log_event(
            run_id=getattr(agent, "run_id", "unknown"),
            agent="verifier",
            stage="verify",
            event="complete",
            duration_ms=int((time.time() - start) * 1000),
            metadata={"question": rr.question[:80],
                      "verification": rr.verification,
                      "claims_checked": 0},
        )
        return rr

    claims_list = "\n".join(f"- {c}" for c in suspicious)
    user_msg = (
        f"Question: {rr.question}\n\n"
        f"Answer: {rr.answer}\n\n"
        f"Claims to verify:\n{claims_list}\n\n"
        "Search the web to verify each claim. "
        "Return a JSON array of results as described in your instructions."
    )

    messages = [{"role": "user", "content": user_msg}]
    iteration = 0
    seen_queries: set[str] = set()

    while iteration < agent.max_iterations:
        iteration += 1
        response = agent.chat(messages=messages, tools=build_tool_list(agent.tools), max_tokens=max_tokens)

        if response.type == "tool_call":
            # M3: malformed tool_input must not crash the verifier loop.
            query = _validate_tool_input(response.tool_input)
            if query is None:
                logging.warning("Verifier: malformed tool input %r", response.tool_input)
                messages.append({
                    "role": "assistant",
                    "content": "Tool call had malformed input.",
                })
                messages.append({
                    "role": "user",
                    "content": "Return your verification results as a JSON array.",
                })
                continue

            # M7: skip repeated queries — prevents oscillation over the same claim.
            if query in seen_queries:
                logging.warning("Verifier repeated query: '%s' — skipping", query)
                messages.append({
                    "role": "assistant",
                    "content": f"I already searched for: {query}",
                })
                messages.append({
                    "role": "user",
                    "content": "Return your verification results as a JSON array.",
                })
                continue

            print(f"  🔍 Verifier searching: '{query}'")
            try:
                tool_result, verifier_sources = execute_tool_with_sources(
                    response.tool_name, response.tool_input
                )
                # M6: attach verifier citations; M2: deduplicate by URL.
                existing_urls = {s.get("url") for s in rr.sources}
                rr.sources.extend(
                    s for s in verifier_sources if s.get("url") not in existing_urls
                )
            except (ValueError, KeyError, AttributeError) as e:
                logging.warning("Verifier: tool execution failed: %s", e)
                tool_result = "Search failed."

            seen_queries.add(query)
            messages.append({
                "role": "assistant",
                "content": f"I will search for: {query}",
            })
            messages.append({
                "role": "user",
                "content": (
                    f"Search results for '{query}':\n\n{tool_result}\n\n"
                    "Now return your verification results as a JSON array."
                ),
            })

        elif response.type == "text":
            content = response.content.strip()
            # Strip markdown code fences if the model wrapped the JSON
            if content.startswith("```"):
                lines = content.splitlines()[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines)
            try:
                results = json.loads(content)
                refuted = [r for r in results if _is_refuted(r)]
                confirmed = [r for r in results if _is_confirmed(r)]
                if refuted:
                    print(f"  ⚠️  Verifier: {len(refuted)} refuted claim(s) "
                          f"in '{rr.question}'")
                    rr.verification = "refuted"
                elif confirmed:
                    # M4: only mark verified on explicit confirmation;
                    # ambiguous results (unverified status) leave verification="unverified".
                    rr.verification = "verified"
                # else: no confirmation and no refutation — leave "unverified"
            except (json.JSONDecodeError, TypeError, AttributeError) as e:
                warnings.warn(f"Verifier JSON parse failed: {e}", stacklevel=2)
                # M1: parse failure leaves verification="unverified" — not verified
            log_event(
                run_id=getattr(agent, "run_id", "unknown"),
                agent="verifier",
                stage="verify",
                event="complete",
                duration_ms=int((time.time() - start) * 1000),
                metadata={"question": rr.question[:80],
                          "verification": rr.verification,
                          "claims_checked": len(suspicious)},
            )
            return rr

    # Max iterations reached without a text response — leave "unverified"
    log_event(
        run_id=getattr(agent, "run_id", "unknown"),
        agent="verifier",
        stage="verify",
        event="complete",
        duration_ms=int((time.time() - start) * 1000),
        metadata={"question": rr.question[:80],
                  "verification": rr.verification,
                  "claims_checked": len(suspicious)},
    )
    return rr


def graph_verify(
    agent: Agent,
    result: ResearchResult,
    topic: str,
) -> ResearchResult:
    """
    Run the Graph Verifier Agent on a ResearchResult.

    Checks all claims in result.claims against the knowledge graph (D041).
    The graph is cheap to query so all claims are checked, not just suspicious
    ones (unlike the web Verifier which uses heuristic selection — D010).

    For each claim returned as resolved_contradicted by the graph verifier:
      - claim.verification_status is set to "disputed"
      - claim.confidence is decreased by 0.10 (floor 0.0)

    Sets result.verification = "refuted" if any claim was resolved_contradicted;
    otherwise leaves result.verification unchanged.

    On any exception the original unmodified ResearchResult is returned and
    a WARNING is logged — the graph verifier must not crash the pipeline.

    Args:
        agent:  Graph Verifier Agent with kg_ tools and max_iterations configured.
        result: ResearchResult from the Researcher + web Verifier pipeline.
        topic:  The research topic (passed to kg_ tools as context).

    Returns:
        Updated ResearchResult (modified in place, also returned for convenience).
    """
    try:
        claims = result.claims
        if not claims:
            return result

        # Build numbered claim list for the agent
        claims_text = "\n".join(
            f"{i + 1}. (claim_id={c.get('id', i + 1)}) {c.get('claim', '')}"
            for i, c in enumerate(claims)
        )
        user_msg = (
            f"Topic: {topic}\n\n"
            f"Research question: {result.question}\n\n"
            f"Claims to verify against the knowledge graph:\n{claims_text}\n\n"
            "Check each claim against the knowledge graph using the available tools. "
            "Return a JSON array with one object per claim as described in your instructions."
        )

        messages = [{"role": "user", "content": user_msg}]

        iteration = 0
        while iteration < agent.max_iterations:
            iteration += 1
            response = agent.chat(messages=messages, tools=build_tool_list(agent.tools),
                                  max_tokens=2048)

            if response.type == "tool_call":
                tool_name = response.tool_name
                tool_input = response.tool_input or {}
                try:
                    tool_result, _ = execute_tool_with_sources(tool_name, tool_input)
                except (ValueError, KeyError, AttributeError) as e:
                    logging.warning("GraphVerifier: tool %r failed: %s", tool_name, e)
                    tool_result = '{"error": "tool call failed"}'
                messages.append({
                    "role": "assistant",
                    "content": f"Called {tool_name}.",
                })
                messages.append({
                    "role": "user",
                    "content": (
                        f"Tool result for {tool_name}:\n{tool_result}\n\n"
                        "Continue checking remaining claims or return your JSON array."
                    ),
                })

            elif response.type == "text":
                content = response.content.strip()
                if content.startswith("```"):
                    lines = content.splitlines()[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    content = "\n".join(lines)
                try:
                    gv_results = json.loads(content)
                    if not isinstance(gv_results, list):
                        return result
                    any_contradicted = False
                    for gv in gv_results:
                        if not isinstance(gv, dict):
                            continue
                        if gv.get("result") != "resolved_contradicted":
                            continue
                        # Find the matching claim by claim_id
                        cid = gv.get("claim_id")
                        for claim in claims:
                            if claim.get("id") == cid:
                                prior = claim.get("verification_status", "unverified")
                                if prior == "verified":
                                    logging.info(
                                        "graph_verify: claim %s was web-verified but "
                                        "graph found contradiction — setting disputed "
                                        "(prior: verified)",
                                        cid,
                                    )
                                claim["verification_status"] = "disputed"
                                claim["confidence"] = max(
                                    0.0,
                                    float(claim.get("confidence", 0.5)) - 0.10
                                )
                                any_contradicted = True
                                break
                    if any_contradicted:
                        result.verification = "refuted"
                except (json.JSONDecodeError, TypeError, ValueError) as e:
                    logging.warning("GraphVerifier: JSON parse failed: %s", e)
                return result

        return result

    except Exception as e:
        logging.warning("GraphVerifier: unexpected error — returning original result: %s", e)
        return result
