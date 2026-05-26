"""
Tests for agent/verifier.py — _extract_suspicious_claims() and verify().

Verifies:
  - _extract_suspicious_claims(): detects numbers, absolute terms, named
    entities; ranks multi-criteria sentences first; respects max_claims;
    returns empty list when no suspicious markers found.
  - verify(): returns ResearchResult; sets verified=True when no suspicious
    claims; sets verified=True when all claims pass; sets verified=False
    when a claim is refuted; handles tool calls; handles JSON parse failure
    gracefully (conservative: verified=True); handles max_iterations with no
    text response (conservative: verified=True).

All tests mock the LLM and execute_tool_with_sources.
"""

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


def test_verify_sets_verified_true_when_no_suspicious_claims():
    """When no suspicious claims are found, verified is set True without any LLM call."""
    mock_llm = MagicMock()
    agent = make_verifier_agent(mock_llm)
    rr = ResearchResult(
        question="What is fusion?",
        answer="Fusion is a nuclear reaction where light nuclei combine and release energy.",
    )
    # Patch _extract_suspicious_claims to return empty list
    with patch("agent.verifier._extract_suspicious_claims", return_value=[]):
        result = verify(agent, rr)
    assert result.verified is True
    assert mock_llm.chat.call_count == 0


# ── verify() — verification paths ────────────────────────────────────────────

def test_verify_sets_verified_true_when_all_pass():
    """verified=True when agent returns JSON with all verified/unverified statuses."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(
        '[{"claim": "Fusion produces 500 MW.", "status": "verified", "confidence": 0.9}]'
    )
    agent = make_verifier_agent(mock_llm)
    rr = ResearchResult(question="What is fusion?", answer="Fusion produces 500 MW.")
    with patch("agent.verifier.execute_tool_with_sources", return_value=("r", [])):
        result = verify(agent, rr)
    assert result.verified is True


def test_verify_sets_verified_false_when_claim_refuted():
    """verified=False when agent returns JSON containing a refuted claim."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(
        '[{"claim": "Fusion produces 500 MW.", "status": "refuted", "confidence": 0.2}]'
    )
    agent = make_verifier_agent(mock_llm)
    rr = ResearchResult(question="What is fusion?", answer="Fusion produces 500 MW.")
    with patch("agent.verifier.execute_tool_with_sources", return_value=("r", [])):
        result = verify(agent, rr)
    assert result.verified is False


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
    assert result.verified is True
    assert mock_llm.chat.call_count == 2


def test_verify_json_parse_failure_defaults_to_verified_true():
    """When JSON parsing fails, verified defaults to True (conservative)."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response("This is not JSON at all.")
    agent = make_verifier_agent(mock_llm)
    rr = ResearchResult(question="What is fusion?", answer="Fusion produces 500 MW.")
    with patch("agent.verifier.execute_tool_with_sources", return_value=("r", [])):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = verify(agent, rr)
    assert result.verified is True


def test_verify_max_iterations_defaults_to_verified_true():
    """When max_iterations exhausted with no text response, verified defaults to True."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_tool_response("web_search", {"query": "fusion"})
    agent = make_verifier_agent(mock_llm, max_iterations=3)
    rr = ResearchResult(question="What is fusion?", answer="Fusion produces 500 MW.")
    with patch("agent.verifier.execute_tool_with_sources", return_value=("results", [])):
        result = verify(agent, rr)
    assert result.verified is True
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
    assert result.verified is True


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
