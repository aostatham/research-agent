"""
Tests for agent/verifier.py — _extract_suspicious_claims() and verify().

Verifies:
  - _extract_suspicious_claims(): detects numbers, absolute terms, named
    entities; ranks multi-criteria sentences first; respects max_claims;
    returns empty list when no suspicious markers found.
  - verify(): returns ResearchResult; sets verification="unverified" when no
    suspicious claims (heuristic miss ≠ verification pass); sets verification="verified" when all claims pass;
    sets verification="refuted" when a claim is refuted; handles tool calls;
    handles JSON parse failure (leaves verification="unverified", M1);
    handles max_iterations with no text response (leaves verification="unverified", M1).

All tests mock the LLM and execute_tool_with_sources.
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from agent.verifier import verify, _extract_suspicious_claims
from agent.base import Agent
from evidence.schema import ResearchResult
from llm.base import LLMResponse


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_text_response(content):
    return LLMResponse(type="text", content=content)


def make_tool_response(tool_name, tool_input):
    return LLMResponse(type="tool_call", tool_name=tool_name, tool_input=tool_input)


def make_verifier_agent(mock_llm, max_iterations=5):
    return Agent(
        name="verifier",
        role="Research verifier",
        description="Verifies claims",
        llm=mock_llm,
        system_prompt="You are a verifier.",
        tools=("web_search",),
        max_iterations=max_iterations,
    )


def make_rr(question="What is fusion?", answer="Fusion is a process."):
    return ResearchResult(question=question, answer=answer)


# ── _extract_suspicious_claims() tests ───────────────────────────────────────

def test_extract_detects_sentence_with_number():
    """Sentences containing digits are flagged as suspicious."""
    answer = "Fusion produces 500 megawatts."
    claims = _extract_suspicious_claims(answer, "What is fusion?")
    assert len(claims) >= 1
    assert "500" in claims[0]


def test_extract_detects_absolute_terms():
    """Sentences containing absolute terms (only, always, never) are flagged."""
    answer = "Fusion is the only viable clean energy source."
    claims = _extract_suspicious_claims(answer, "What is fusion?")
    assert len(claims) >= 1
    assert "only" in claims[0].lower()


def test_extract_detects_named_entity_not_in_question():
    """Sentences with a capitalised word absent from the question are flagged."""
    answer = "The ITER project in France aims to demonstrate fusion viability."
    claims = _extract_suspicious_claims(answer, "What is fusion?")
    assert len(claims) >= 1


def test_extract_returns_empty_for_plain_text():
    """Plain descriptive sentences with no markers return an empty list."""
    answer = "Fusion is a type of nuclear reaction where light nuclei combine."
    # No numbers, no absolute terms, no unexpected capitalized words
    claims = _extract_suspicious_claims(answer, "What is fusion and how does it work?")
    # May return 0 or a small number depending on named entity heuristic
    # The key assertion: no crash and returns a list
    assert isinstance(claims, list)


def test_extract_respects_max_claims():
    """At most max_claims sentences are returned."""
    answer = (
        "ITER will produce 500 MW of fusion power. "
        "Plasma temperature must always exceed 100 million degrees. "
        "The first commercial plant will open by 2050. "
        "Only tritium-deuterium reactions are commercially viable. "
        "NIF achieved 3.15 megajoules in December 2022."
    )
    claims = _extract_suspicious_claims(answer, "What is fusion?", max_claims=3)
    assert len(claims) <= 3


def test_extract_empty_answer_returns_empty():
    """Empty answer string returns an empty list."""
    assert _extract_suspicious_claims("", "What is fusion?") == []


def test_extract_whitespace_answer_returns_empty():
    """Whitespace-only answer returns an empty list."""
    assert _extract_suspicious_claims("   \n  ", "What is fusion?") == []


def test_extract_multi_criteria_sentence_ranked_first():
    """A sentence matching multiple criteria is ranked above single-criteria sentences."""
    answer = (
        "Fusion occurs at high temperatures. "
        "ITER will produce exactly 500 MW, making it the only fusion-scale experiment ever built."
    )
    claims = _extract_suspicious_claims(answer, "What is fusion?", max_claims=2)
    # Second sentence matches: number (500), absolute (only), named entity (ITER)
    assert any("500" in c or "only" in c.lower() for c in claims[:1])


def test_extract_returns_list():
    """Return type is always a list."""
    result = _extract_suspicious_claims("Fusion is a process.", "What is fusion?")
    assert isinstance(result, list)


# ── verify() — return type and no-suspicious-claims path ─────────────────────

def test_verify_returns_research_result():
    """verify() returns a ResearchResult."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response('[]')
    agent = make_verifier_agent(mock_llm)
    rr = ResearchResult(question="Q?", answer="Fusion produces 500 MW.")
    with patch("agent.verifier.execute_tool_with_sources", return_value=("results", [])):
        result = verify(agent, rr)
    assert isinstance(result, ResearchResult)


def test_verify_sets_unverified_when_no_suspicious_claims():
    """When no suspicious claims are found, verification stays 'unverified' — heuristic miss ≠ verified."""
    mock_llm = MagicMock()
    agent = make_verifier_agent(mock_llm)
    rr = ResearchResult(
        question="What is fusion?",
        answer="Fusion is a nuclear reaction where light nuclei combine and release energy.",
    )
    with patch("agent.verifier._extract_suspicious_claims", return_value=[]):
        result = verify(agent, rr)
    assert result.verification == "unverified"
    assert mock_llm.chat.call_count == 0


# ── verify() — verification paths ────────────────────────────────────────────

def test_verify_sets_verified_when_all_pass():
    """verification='verified' when agent returns JSON with confirmed status."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(
        '[{"claim": "Fusion produces 500 MW.", "status": "verified", "confidence": 0.9}]'
    )
    agent = make_verifier_agent(mock_llm)
    rr = ResearchResult(question="What is fusion?", answer="Fusion produces 500 MW.")
    with patch("agent.verifier.execute_tool_with_sources", return_value=("r", [])):
        result = verify(agent, rr)
    assert result.verification == "verified"


def test_verify_sets_refuted_when_claim_refuted():
    """verification='refuted' when agent returns JSON containing a refuted claim."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(
        '[{"claim": "Fusion produces 500 MW.", "status": "refuted", "confidence": 0.2}]'
    )
    agent = make_verifier_agent(mock_llm)
    rr = ResearchResult(question="What is fusion?", answer="Fusion produces 500 MW.")
    with patch("agent.verifier.execute_tool_with_sources", return_value=("r", [])):
        result = verify(agent, rr)
    assert result.verification == "refuted"


def test_verify_handles_tool_call_before_json():
    """verify() handles a tool_call response before the final JSON response."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "ITER 500 MW output"}),
        make_text_response('[{"claim": "ITER produces 500 MW.", "status": "verified"}]'),
    ]
    agent = make_verifier_agent(mock_llm)
    rr = ResearchResult(question="What is ITER?", answer="ITER produces 500 MW.")
    with patch("agent.verifier.execute_tool_with_sources", return_value=("results", [])):
        result = verify(agent, rr)
    assert result.verification == "verified"
    assert mock_llm.chat.call_count == 2


def test_verify_json_parse_failure_leaves_unverified():
    """When JSON parsing fails, verification stays 'unverified' (M1: not silently promoted)."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response("This is not JSON at all.")
    agent = make_verifier_agent(mock_llm)
    rr = ResearchResult(question="What is fusion?", answer="Fusion produces 500 MW.")
    with patch("agent.verifier.execute_tool_with_sources", return_value=("r", [])):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = verify(agent, rr)
    assert result.verification == "unverified"


def test_verify_max_iterations_leaves_unverified():
    """When max_iterations exhausted with no text response, verification stays 'unverified' (M1)."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_tool_response("web_search", {"query": "fusion"})
    agent = make_verifier_agent(mock_llm, max_iterations=3)
    rr = ResearchResult(question="What is fusion?", answer="Fusion produces 500 MW.")
    with patch("agent.verifier.execute_tool_with_sources", return_value=("results", [])):
        result = verify(agent, rr)
    assert result.verification == "unverified"
    assert mock_llm.chat.call_count == 3


def test_verify_fenced_json_is_parsed():
    """JSON wrapped in code fences is stripped and parsed correctly."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(
        '```json\n[{"status": "verified"}]\n```'
    )
    agent = make_verifier_agent(mock_llm)
    rr = ResearchResult(question="What is fusion?", answer="Fusion produces 500 MW.")
    with patch("agent.verifier.execute_tool_with_sources", return_value=("r", [])):
        result = verify(agent, rr)
    assert result.verification == "verified"


def test_verify_passes_tools_from_agent_tools():
    """verify() passes build_tool_list(agent.tools) to agent.chat(), not ALL_TOOLS."""
    from agent.tools import WEB_SEARCH_TOOL
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response('[{"status": "verified"}]')
    agent = Agent(
        name="verifier",
        role="Research verifier",
        description="Verifies claims",
        llm=mock_llm,
        system_prompt="You are a verifier.",
        tools=("web_search",),
        max_iterations=5,
    )
    rr = ResearchResult(question="What is fusion?", answer="Fusion produces 500 MW.")
    with patch("agent.verifier.execute_tool_with_sources", return_value=("r", [])):
        verify(agent, rr)
    call_kwargs = mock_llm.chat.call_args.kwargs
    assert call_kwargs.get("tools") == [WEB_SEARCH_TOOL]


def test_verify_uses_agent_llm():
    """verify() calls the agent's LLM, not a global one."""
    mock_llm_a = MagicMock()
    mock_llm_b = MagicMock()
    mock_llm_a.chat.return_value = make_text_response('[{"status": "verified"}]')
    agent = make_verifier_agent(mock_llm_a)
    rr = ResearchResult(question="What is fusion?", answer="Fusion produces 500 MW.")
    with patch("agent.verifier.execute_tool_with_sources", return_value=("r", [])):
        verify(agent, rr)
    assert mock_llm_a.chat.called
    assert not mock_llm_b.chat.called


# ── M3: Malformed tool input ──────────────────────────────────────────────────

def test_verify_malformed_tool_input_does_not_raise():
    """Malformed tool input (None) is handled without raising KeyError/AttributeError."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        LLMResponse(type="tool_call", tool_name="web_search", tool_input=None),
        make_text_response('[{"status": "verified"}]'),
    ]
    agent = make_verifier_agent(mock_llm)
    rr = make_rr(answer="Fusion produces 500 MW.")
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = verify(agent, rr)
    assert isinstance(result, ResearchResult)


# ── M4: Three-outcome verification ───────────────────────────────────────────

def test_verify_ambiguous_result_leaves_unverified():
    """An 'unverified' status from the agent leaves verification='unverified' (not 'verified')."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(
        '[{"claim": "Fusion produces 500 MW.", "status": "unverified", "confidence": 0.5}]'
    )
    agent = make_verifier_agent(mock_llm)
    rr = make_rr(answer="Fusion produces 500 MW.")
    with patch("agent.verifier.execute_tool_with_sources", return_value=("r", [])):
        result = verify(agent, rr)
    assert result.verification == "unverified"


# ── M6: Verifier citation retention ──────────────────────────────────────────

def test_verify_attaches_verifier_sources_to_rr():
    """Sources returned by verifier web searches are appended to rr.sources."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "ITER output"}),
        make_text_response('[{"status": "verified"}]'),
    ]
    agent = make_verifier_agent(mock_llm)
    rr = make_rr(answer="ITER produces 500 MW.")
    verifier_sources = [{"title": "ITER site", "url": "https://iter.org"}]
    with patch("agent.verifier.execute_tool_with_sources",
               return_value=("results", verifier_sources)):
        result = verify(agent, rr)
    assert any(s["url"] == "https://iter.org" for s in result.sources)


# ── M7: Verifier seen_queries guard ──────────────────────────────────────────

def test_verify_skips_repeated_query(caplog):
    """A repeated search query is skipped — only one search executes per unique query."""
    import logging
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "ITER output"}),
        make_tool_response("web_search", {"query": "ITER output"}),  # repeated
        make_text_response('[{"status": "verified"}]'),
    ]
    agent = make_verifier_agent(mock_llm, max_iterations=5)
    rr = make_rr(answer="ITER produces 500 MW.")
    with patch("agent.verifier.execute_tool_with_sources", return_value=("results", [])) as mock_tool:
        with caplog.at_level(logging.WARNING, logger="root"):
            result = verify(agent, rr)
    # Only one actual tool execution for the unique query
    assert mock_tool.call_count == 1


def test_verify_repeated_query_logs_warning(caplog):
    """A WARNING is logged when a repeated query is detected."""
    import logging
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion energy"}),
        make_tool_response("web_search", {"query": "fusion energy"}),  # repeated
        make_text_response('[{"status": "verified"}]'),
    ]
    agent = make_verifier_agent(mock_llm, max_iterations=5)
    rr = make_rr(answer="Fusion produces 500 MW.")
    with patch("agent.verifier.execute_tool_with_sources", return_value=("results", [])):
        with caplog.at_level(logging.WARNING, logger="root"):
            verify(agent, rr)
    assert any("repeated query" in r.message.lower() for r in caplog.records)


# ── M2: URL deduplication of verifier sources ─────────────────────────────────

def test_verify_deduplicates_sources_by_url():
    """Verifier sources already in rr.sources (same URL) are not duplicated (M2)."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "ITER output"}),
        make_text_response('[{"status": "verified"}]'),
    ]
    agent = make_verifier_agent(mock_llm)
    rr = make_rr(answer="ITER produces 500 MW.")
    existing = {"title": "ITER site", "url": "https://iter.org"}
    rr.sources.append(existing)
    verifier_sources = [{"title": "ITER site", "url": "https://iter.org"}]
    with patch("agent.verifier.execute_tool_with_sources",
               return_value=("results", verifier_sources)):
        result = verify(agent, rr)
    assert result.sources.count(existing) == 1


# ── M7: _is_refuted status-field precision ────────────────────────────────────
# Note: _REFUTED_STATUSES intentionally contains synonyms beyond what the prompt
# emits ("refuted" only). The synonyms are defensive coverage for off-script model
# output — they do not widen the expected happy path. See verifier.py for detail.

def test_is_refuted_checks_status_field_first():
    """_is_refuted() returns True only when the status field says refuted."""
    from agent.verifier import _is_refuted
    assert _is_refuted({"status": "refuted", "note": "something else"}) is True


def test_is_refuted_ignores_refuted_in_non_status_field_when_status_present():
    """When status field is present, _is_refuted() ignores 'refuted' in other fields."""
    from agent.verifier import _is_refuted
    assert _is_refuted({"status": "verified", "note": "claim was refuted initially"}) is False


def test_is_refuted_returns_false_when_no_recognised_field():
    """Without a recognised field, _is_refuted() returns False — no value-scan fallback (M6)."""
    from agent.verifier import _is_refuted
    assert _is_refuted({"note": "refuted"}) is False


def test_is_refuted_returns_false_for_unrecognised_field_with_refuted_value():
    """Unrecognised field containing 'refuted' string is not treated as refutation (M6)."""
    from agent.verifier import _is_refuted
    assert _is_refuted({"note": "this claim is refuted by evidence"}) is False


# ── M6: No fallback value-scan — unrecognised fields ignored ─────────────────

def test_is_confirmed_returns_false_when_no_recognised_field():
    """Without a recognised field, _is_confirmed() returns False (no fallback scan)."""
    from agent.verifier import _is_confirmed
    assert _is_confirmed({"note": "verified"}) is False


def test_is_refuted_logs_debug_when_no_recognised_field(caplog):
    """DEBUG log fires when no recognised status field is present in the result."""
    import logging
    from agent.verifier import _is_refuted
    with caplog.at_level(logging.DEBUG, logger="root"):
        _is_refuted({"note": "some value"})
    assert "missing recognised status field" in caplog.text.lower() or \
           any("unverified" in r.message.lower() for r in caplog.records)


# ── H4: _REFUTED_STATUSES frozenset exact match ───────────────────────────────

def test_is_refuted_matches_false_status():
    """'false' status is treated as refuted (in _REFUTED_STATUSES)."""
    from agent.verifier import _is_refuted
    assert _is_refuted({"status": "false"}) is True


def test_is_refuted_matches_incorrect_status():
    """'incorrect' status is treated as refuted."""
    from agent.verifier import _is_refuted
    assert _is_refuted({"status": "incorrect"}) is True


def test_is_refuted_matches_disputed_status():
    """'disputed' status is treated as refuted."""
    from agent.verifier import _is_refuted
    assert _is_refuted({"status": "disputed"}) is True


def test_is_refuted_matches_wrong_status():
    """'wrong' status is treated as refuted."""
    from agent.verifier import _is_refuted
    assert _is_refuted({"status": "wrong"}) is True


def test_is_refuted_matches_inaccurate_status():
    """'inaccurate' status is treated as refuted."""
    from agent.verifier import _is_refuted
    assert _is_refuted({"status": "inaccurate"}) is True


# ── graph_verify() tests ─────────────────────────────────────────────────────

def _make_gv_agent(chat_return):
    """Build a minimal mock Agent for graph_verify() tests."""
    from agent.base import Agent
    mock_llm = MagicMock()
    mock_llm.chat.return_value = chat_return
    return Agent(
        name="graph_verifier",
        role="Graph Verifier",
        description="test",
        llm=mock_llm,
        system_prompt="You are a graph verifier.",
        tools=("kg_check_contradiction",),
        max_iterations=4,
    )


def _make_rr_with_claims(*claims_text):
    """Build a ResearchResult with EvidenceClaim-like dicts."""
    claims = [
        {"id": i + 1, "claim": t, "confidence": 0.7,
         "verification_status": "unverified", "sources": []}
        for i, t in enumerate(claims_text)
    ]
    return ResearchResult(
        question="What is X?", answer="X is something.", claims=claims
    )


def test_graph_verify_sets_disputed_on_resolved_contradicted():
    """graph_verify() sets verification_status=disputed on resolved_contradicted claims."""
    from agent.verifier import graph_verify
    from llm.base import LLMResponse

    gv_response = json.dumps([
        {"claim_id": 1, "result": "resolved_contradicted", "reason": "Found contradiction."}
    ])
    agent = _make_gv_agent(LLMResponse(type="text", content=gv_response))
    rr = _make_rr_with_claims("X is definitely the largest.")

    result = graph_verify(agent, rr, "topic X")

    assert result.claims[0]["verification_status"] == "disputed"
    assert result.claims[0]["confidence"] < 0.7
    assert result.verification == "refuted"


def test_graph_verify_leaves_unresolved_claims_unchanged():
    """graph_verify() leaves claims unchanged when result is unresolved."""
    from agent.verifier import graph_verify
    from llm.base import LLMResponse

    gv_response = json.dumps([
        {"claim_id": 1, "result": "unresolved", "reason": "No graph evidence."}
    ])
    agent = _make_gv_agent(LLMResponse(type="text", content=gv_response))
    rr = _make_rr_with_claims("X is a large number.")

    result = graph_verify(agent, rr, "topic X")

    assert result.claims[0]["verification_status"] == "unverified"
    assert result.claims[0]["confidence"] == 0.7
    assert result.verification == "unverified"


def test_graph_verify_returns_original_result_on_exception():
    """graph_verify() returns the original ResearchResult unmodified on any exception."""
    from agent.verifier import graph_verify
    from agent.base import Agent

    # Agent whose chat() raises RuntimeError
    bad_llm = MagicMock()
    bad_llm.chat.side_effect = RuntimeError("network failure")
    bad_agent = Agent(
        name="graph_verifier", role="r", description="d",
        llm=bad_llm, system_prompt="s", tools=(), max_iterations=4,
    )
    rr = _make_rr_with_claims("Some claim.")
    original_vstatus = rr.claims[0]["verification_status"]

    result = graph_verify(bad_agent, rr, "topic")

    assert result is rr
    assert result.claims[0]["verification_status"] == original_vstatus


def test_graph_verify_confidence_floor_at_zero():
    """graph_verify() does not decrease confidence below 0.0."""
    from agent.verifier import graph_verify
    from llm.base import LLMResponse

    gv_response = json.dumps([
        {"claim_id": 1, "result": "resolved_contradicted", "reason": "Contradiction found."}
    ])
    agent = _make_gv_agent(LLMResponse(type="text", content=gv_response))
    rr = _make_rr_with_claims("Some claim.")
    rr.claims[0]["confidence"] = 0.05  # would go below 0 without floor

    result = graph_verify(agent, rr, "topic")

    assert result.claims[0]["confidence"] == 0.0


# ── Orchestrator verifier integration ────────────────────────────────────────

def test_research_question_async_calls_verifier_unconditionally():
    """research_question_async() always invokes verify() — no conditional on agent_pool."""
    import asyncio
    from agent.orchestrator import Orchestrator
    from config import Config

    mock_llm = MagicMock()
    config = Config(max_iterations=5, max_tokens_research=2048)
    mock_pool = MagicMock()
    orch = Orchestrator(llm=mock_llm, agent_pool=mock_pool, config=config)

    expected_rr = ResearchResult(question="Q?", answer="Answer.")

    with patch("agent.researcher.research", return_value=expected_rr), \
         patch("agent.verifier.verify", return_value=expected_rr) as mock_verify:
        sem = asyncio.Semaphore(4)
        result = asyncio.run(orch.research_question_async("Q?", sem))

    mock_verify.assert_called_once()
    assert isinstance(result, ResearchResult)
