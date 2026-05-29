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

def test_analyse_passes_tools_from_agent_tools():
    """analyse() passes build_tool_list(agent.tools) to agent.chat(), not ALL_TOOLS."""
    from agent.tools import WEB_SEARCH_TOOL
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response("[]")
    agent = Agent(
        name="analyst",
        role="Analyst",
        description="Evidence analyst",
        llm=mock_llm,
        system_prompt="You are an analyst.",
        tools=("web_search",),
    )
    analyse(agent, SAMPLE_REPORT, SAMPLE_CLAIMS, make_config())
    call_kwargs = mock_llm.chat.call_args.kwargs
    assert call_kwargs.get("tools") == [WEB_SEARCH_TOOL]


# ── Non-text response ─────────────────────────────────────────────────────────

def test_analyse_returns_original_on_non_text_response():
    """When agent returns a tool_call response, original report and claims are returned."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_tool_response()
    agent = make_analyst_agent(mock_llm)
    result_report, result_claims = analyse(agent, SAMPLE_REPORT, SAMPLE_CLAIMS, make_config())
    assert result_report == SAMPLE_REPORT
    assert result_claims is SAMPLE_CLAIMS


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
