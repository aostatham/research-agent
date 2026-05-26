"""
Verification loop for the Verifier Agent.

Extracts suspicious claims from a ResearchResult answer using cheap heuristics
(D010) and runs targeted web searches to confirm or refute them.

Public API:
  verify()                    — run the Verifier Agent on a ResearchResult
  _extract_suspicious_claims() — heuristic claim selector (testable)
"""

import json
import logging
import re
import warnings
from typing import Optional

from agent.base import Agent
from agent.tools import ALL_TOOLS, execute_tool_with_sources
from evidence.schema import ResearchResult


# Exact status strings that represent a refuted claim.
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


def _is_refuted(result_item) -> bool:
    """Return True if the verification result indicates a refuted claim.

    Uses exact frozenset lookup against _REFUTED_STATUSES (H4) to avoid
    false positives from substring matching. Checks status/summary fields
    first (M7); falls back to a full-value scan only when no recognised
    field is present, logging at DEBUG level.
    """
    if not isinstance(result_item, dict):
        return False
    for field in ("status", "verification_status", "verdict", "summary"):
        val = result_item.get(field)
        if val is not None:
            return isinstance(val, str) and val.lower().strip() in _REFUTED_STATUSES
    # No recognised status/summary field — fall back to scanning all values
    logging.debug("_is_refuted: no status/summary field found, scanning all values")
    return any(
        isinstance(v, str) and v.lower().strip() in _REFUTED_STATUSES
        for v in result_item.values()
    )


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

    If no suspicious claims are found, sets rr.verification = "verified" and
    returns immediately (no LLM calls).  Otherwise runs an agentic loop:

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
        The same ResearchResult with verified field updated.
    """
    suspicious = _extract_suspicious_claims(rr.answer, rr.question)
    if not suspicious:
        rr.verification = "verified"
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

    while iteration < agent.max_iterations:
        iteration += 1
        response = agent.chat(messages=messages, tools=ALL_TOOLS, max_tokens=max_tokens)

        if response.type == "tool_call":
            # M3: malformed tool_input must not crash the verifier loop.
            try:
                query = response.tool_input.get("query", "")
            except (AttributeError, TypeError) as e:
                logging.warning("Verifier: malformed tool input %r: %s",
                                response.tool_input, e)
                messages.append({
                    "role": "assistant",
                    "content": "Tool call had malformed input.",
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
            except (ValueError, KeyError, Exception) as e:
                logging.warning("Verifier: tool execution failed: %s", e)
                tool_result = "Search failed."

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
            return rr

    # Max iterations reached without a text response — leave "unverified"
    return rr
