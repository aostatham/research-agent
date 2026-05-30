"""
Tests for agent/analyst.py — analyse() function.

Verifies:
  - Returns (original_report, claims) when agent returns a non-text response
  - Returns (original_report, claims) when the response contains no JSON array
  - Returns (original_report, claims) on JSON parse error
  - qualify recommendation inserts qualifier before matched claim text
  - qualify recommendation prepends to the full line when claim text not found
  - strengthen recommendation appends community source note to the line
  - surface_contradiction recommendation inserts warning marker before claim text
  - Claims without report_line are excluded from filtered_claims

All tests mock the agent's LLM.
"""

import json
import pytest
from unittest.mock import MagicMock
from agent.analyst import analyse
from agent.base import Agent
from llm.base import LLMResponse


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_analyst_agent(mock_llm):
    return Agent(
        name="analyst",
        role="Analyst",
        description="Evidence analyst",
        llm=mock_llm,
        system_prompt="You are an analyst.",
    )


def make_config(qualify_threshold=0.5, strengthen_source_types=None):
    cfg = MagicMock()
    cfg.analyst_qualify_threshold = qualify_threshold
    cfg.analyst_strengthen_source_types = strengthen_source_types or ["forum"]
    return cfg


def make_text_response(content):
    return LLMResponse(type="text", content=content)


def make_tool_response():
    return LLMResponse(type="tool_call", tool_name="web_search", tool_input={"query": "test"})


SAMPLE_REPORT = "Line one content.\nLine two content.\nLine three content."

SAMPLE_CLAIMS = [
    {"id": 1, "claim": "Line one content.", "confidence": 0.3,
     "sources": [{"type": "forum"}], "verification_status": "unverified", "report_line": 1},
    {"id": 2, "claim": "Line two content.", "confidence": 0.9,
     "sources": [{"type": "academic"}], "verification_status": "verified", "report_line": 2},
]


# ── Tools kwarg ──────────────────────────────────────────────────────────────

def test_analyse_passes_empty_tools_list_to_chat():
    """analyse() passes [] to agent.chat() — Analyst has no tools."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response("[]")
    agent = Agent(
        name="analyst",
        role="Analyst",
        description="Evidence analyst",
        llm=mock_llm,
        system_prompt="You are an analyst.",
    )
    analyse(agent, SAMPLE_REPORT, SAMPLE_CLAIMS, make_config())
    call_kwargs = mock_llm.chat.call_args.kwargs
    assert call_kwargs.get("tools") == []


# ── Non-text response ─────────────────────────────────────────────────────────

def test_analyse_returns_original_on_non_text_response():
    """When agent returns a tool_call response, original report and claims are returned."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_tool_response()
    agent = make_analyst_agent(mock_llm)
    result_report, result_claims = analyse(agent, SAMPLE_REPORT, SAMPLE_CLAIMS, make_config())
    assert result_report == SAMPLE_REPORT
    assert result_claims is SAMPLE_CLAIMS


def test_analyse_non_text_response_logs_warning(caplog):
    """Non-text response logs a WARNING with the response type."""
    import logging
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_tool_response()
    agent = make_analyst_agent(mock_llm)
    with caplog.at_level(logging.WARNING, logger="agent.analyst"):
        analyse(agent, SAMPLE_REPORT, SAMPLE_CLAIMS, make_config())
    assert any("non-text response" in r.message for r in caplog.records)


# ── No JSON array in response ─────────────────────────────────────────────────

def test_analyse_returns_original_on_no_json_array():
    """When the response contains no JSON array markers, originals are returned."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response("No recommendations needed.")
    agent = make_analyst_agent(mock_llm)
    result_report, result_claims = analyse(agent, SAMPLE_REPORT, SAMPLE_CLAIMS, make_config())
    assert result_report == SAMPLE_REPORT
    assert result_claims is SAMPLE_CLAIMS


# ── JSON parse error ──────────────────────────────────────────────────────────

def test_analyse_returns_original_on_json_parse_error():
    """When JSON inside [...] is malformed, originals are returned."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response("[not valid json {{")
    agent = make_analyst_agent(mock_llm)
    result_report, result_claims = analyse(agent, SAMPLE_REPORT, SAMPLE_CLAIMS, make_config())
    assert result_report == SAMPLE_REPORT
    assert result_claims is SAMPLE_CLAIMS


# ── qualify ───────────────────────────────────────────────────────────────────

def test_analyse_qualify_inserts_qualifier_before_claim_text():
    """qualify recommendation inserts qualifier before the matched claim text on the line."""
    recs = [{"type": "qualify", "report_line": 1, "claim_id": 1,
             "suggested_qualifier": "Some sources suggest that "}]
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(json.dumps(recs))
    agent = make_analyst_agent(mock_llm)
    result_report, _ = analyse(agent, SAMPLE_REPORT, SAMPLE_CLAIMS, make_config())
    first_line = result_report.split("\n")[0]
    assert first_line == "Some sources suggest that Line one content."


def test_analyse_qualify_prepends_to_line_when_claim_text_not_found():
    """qualify falls back to prepending qualifier to the whole line when claim not matched."""
    recs = [{"type": "qualify", "report_line": 1, "claim_id": 1,
             "suggested_qualifier": "According to available sources, "}]
    # Use a claim text that does not appear verbatim in the report
    claims = [
        {"id": 1, "claim": "NONEXISTENT TEXT", "confidence": 0.3,
         "sources": [], "verification_status": "unverified", "report_line": 1},
    ]
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(json.dumps(recs))
    agent = make_analyst_agent(mock_llm)
    result_report, _ = analyse(agent, SAMPLE_REPORT, claims, make_config())
    first_line = result_report.split("\n")[0]
    assert first_line == "According to available sources, Line one content."


# ── strengthen ────────────────────────────────────────────────────────────────

def test_analyse_strengthen_appends_community_source_note():
    """strengthen recommendation appends the community source note to the line."""
    recs = [{"type": "strengthen", "report_line": 2, "claim_id": 2}]
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(json.dumps(recs))
    agent = make_analyst_agent(mock_llm)
    result_report, _ = analyse(agent, SAMPLE_REPORT, SAMPLE_CLAIMS, make_config())
    second_line = result_report.split("\n")[1]
    assert second_line == "Line two content. (Note: based on a single community source)"


# ── surface_contradiction ─────────────────────────────────────────────────────

def test_analyse_surface_contradiction_inserts_marker_before_claim_text():
    """surface_contradiction inserts the warning marker before the matched claim text."""
    recs = [{"type": "surface_contradiction", "report_line": 1, "claim_id": 1}]
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(json.dumps(recs))
    agent = make_analyst_agent(mock_llm)
    result_report, _ = analyse(agent, SAMPLE_REPORT, SAMPLE_CLAIMS, make_config())
    first_line = result_report.split("\n")[0]
    assert first_line.startswith("⚠️ (disputed) ")
    assert "Line one content." in first_line


# ── Claims without report_line ────────────────────────────────────────────────

def test_analyse_skips_claims_without_report_line():
    """Claims where report_line is None are excluded from the filtered set passed to the agent."""
    claims_with_null = [
        {"id": 10, "claim": "orphan claim", "confidence": 0.1,
         "sources": [], "verification_status": "unverified", "report_line": None},
        {"id": 11, "claim": "Line one content.", "confidence": 0.4,
         "sources": [], "verification_status": "unverified", "report_line": 1},
    ]
    recs = [{"type": "qualify", "report_line": 1, "claim_id": 11,
             "suggested_qualifier": "Reportedly, "}]
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(json.dumps(recs))
    agent = make_analyst_agent(mock_llm)
    result_report, _ = analyse(agent, SAMPLE_REPORT, claims_with_null, make_config())
    first_line = result_report.split("\n")[0]
    # claim 11 was included (has report_line=1), so qualifier applied
    assert "Reportedly, " in first_line
    # claim 10 (no report_line) must not appear as a lookup key causing errors


# ── Deterministic multi-recommendation ordering ───────────────────────────────

def test_analyse_surface_contradiction_applied_before_qualify_regardless_of_input_order():
    """surface_contradiction is applied before qualify on the same line regardless of input order."""
    # Input order is wrong (qualify first) — output must still have ⚠️ before qualifier.
    recs = [
        {"type": "qualify", "report_line": 1, "claim_id": 1,
         "suggested_qualifier": "Reportedly, "},
        {"type": "surface_contradiction", "report_line": 1, "claim_id": 1},
    ]
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(json.dumps(recs))
    agent = make_analyst_agent(mock_llm)
    result_report, _ = analyse(agent, SAMPLE_REPORT, SAMPLE_CLAIMS, make_config())
    first_line = result_report.split("\n")[0]
    # surface_contradiction first → ⚠️ marker; qualify second → qualifier inserted
    assert first_line.startswith("⚠️ (disputed) Reportedly, ")
    assert "Line one content." in first_line


def test_analyse_duplicate_same_type_same_line_applies_first_logs_warning(caplog):
    """Two qualify recs on the same line: first by claim_id applied, second skipped with WARNING."""
    import logging
    claims = [
        {"id": 1, "claim": "Line one content.", "confidence": 0.3,
         "sources": [{"type": "forum"}], "verification_status": "unverified", "report_line": 1},
        {"id": 2, "claim": "other claim text", "confidence": 0.9,
         "sources": [{"type": "academic"}], "verification_status": "verified", "report_line": 1},
    ]
    recs = [
        {"type": "qualify", "report_line": 1, "claim_id": 1, "suggested_qualifier": "First: "},
        {"type": "qualify", "report_line": 1, "claim_id": 2, "suggested_qualifier": "Second: "},
    ]
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(json.dumps(recs))
    agent = make_analyst_agent(mock_llm)
    with caplog.at_level(logging.WARNING):
        result_report, _ = analyse(agent, SAMPLE_REPORT, claims, make_config())
    first_line = result_report.split("\n")[0]
    assert first_line.startswith("First: ")
    assert "Second:" not in first_line
    assert any("Multiple qualify" in r.message for r in caplog.records)


def test_analyse_surface_contradiction_plus_qualify_on_same_line_combined():
    """surface_contradiction + qualify on same line produce correct combined output."""
    claims = [
        {"id": 1, "claim": "Line one content.", "confidence": 0.3,
         "sources": [{"type": "forum"}], "verification_status": "unverified", "report_line": 1},
        {"id": 2, "claim": "Line one content.", "confidence": 0.4,
         "sources": [{"type": "forum"}], "verification_status": "unverified", "report_line": 1},
    ]
    recs = [
        {"type": "qualify", "report_line": 1, "claim_id": 1,
         "suggested_qualifier": "Reportedly, "},
        {"type": "surface_contradiction", "report_line": 1, "claim_id": 2},
    ]
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(json.dumps(recs))
    agent = make_analyst_agent(mock_llm)
    result_report, _ = analyse(agent, SAMPLE_REPORT, claims, make_config())
    first_line = result_report.split("\n")[0]
    assert "⚠️ (disputed)" in first_line
    assert "Reportedly," in first_line
    assert "Line one content." in first_line


# ── string.Template prompt substitution ──────────────────────────────────────

def test_analyse_prompt_contains_substituted_threshold():
    """The prompt sent to agent.chat() contains the threshold value, not the placeholder."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response("[]")
    agent = make_analyst_agent(mock_llm)
    cfg = make_config(qualify_threshold=0.42)
    analyse(agent, SAMPLE_REPORT, SAMPLE_CLAIMS, cfg)
    # agent.chat() forwards messages as the first positional arg to llm.chat()
    messages = mock_llm.chat.call_args[0][0]
    user_content = messages[0]["content"]
    assert "0.42" in user_content
    assert "$qualify_threshold" not in user_content


def test_analyse_prompt_substitution_ignores_unrelated_dollar_signs():
    """safe_substitute() leaves unrecognised $ placeholders unchanged — does not raise."""
    from unittest.mock import patch
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response("[]")
    agent = make_analyst_agent(mock_llm)
    # Inject a prompt that contains an unrelated $ sign (e.g. from a JSON example)
    patched_prompt = (
        "Qualify below $qualify_threshold. "
        "Strengthen $strengthen_source_types. "
        "Example: {\"amount\": \"$100\"}"
    )
    with patch("agent.analyst._ANALYST_PROMPT_PATH") as mock_path:
        mock_path.read_text.return_value = patched_prompt
        # Should not raise even though $100 is not a recognised placeholder
        result_report, _ = analyse(agent, SAMPLE_REPORT, SAMPLE_CLAIMS, make_config())
    assert result_report == SAMPLE_REPORT  # [] recs → unchanged
