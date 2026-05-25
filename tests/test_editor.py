"""
Tests for agent/editor.py — edit() function.

Verifies:
  - Returns a string
  - Returns the edited report when the agent provides a valid response
  - Returns the original report when the response is too short (< 100 chars)
  - Returns the original report when the response is not a text response
  - Calls agent.chat with the report as the user message content
  - Passes max_tokens through to the agent chat call
  - Uses the agent's system prompt (via agent.chat)

All tests mock the agent's LLM.
"""

import pytest
from unittest.mock import MagicMock
from agent.editor import edit
from agent.base import Agent
from llm.base import LLMResponse


# ── Helpers ───────────────────────────────────────────────────────────────────

SAMPLE_REPORT = (
    "# Nuclear Fusion\n\n"
    "## Introduction\n\n"
    "Nuclear fusion is a process where light atomic nuclei combine to release energy. "
    "This has been studied extensively since the 1950s.\n\n"
    "## Challenges\n\n"
    "The primary challenges include plasma confinement and materials science."
)


def make_editor_agent(mock_llm):
    return Agent(
        name="editor",
        role="Research editor",
        description="Coherence editor",
        llm=mock_llm,
        system_prompt="You are a coherence editor.",
    )


def make_text_response(content):
    return LLMResponse(type="text", content=content)


def make_tool_response():
    return LLMResponse(type="tool_call", tool_name="web_search", tool_input={"query": "test"})


# ── Return type ───────────────────────────────────────────────────────────────

def test_edit_returns_string():
    """edit() always returns a string."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(SAMPLE_REPORT)
    agent = make_editor_agent(mock_llm)
    result = edit(agent, SAMPLE_REPORT)
    assert isinstance(result, str)


# ── Valid response paths ──────────────────────────────────────────────────────

def test_edit_returns_edited_report_when_valid():
    """When agent returns a valid text response, the edited text is returned."""
    edited = SAMPLE_REPORT + "\n\n*(minor coherence fix applied)*"
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(edited)
    agent = make_editor_agent(mock_llm)
    result = edit(agent, SAMPLE_REPORT)
    assert result == edited.strip()


def test_edit_strips_whitespace_from_response():
    """Leading and trailing whitespace is stripped from the edited report."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(f"  \n{SAMPLE_REPORT}\n  ")
    agent = make_editor_agent(mock_llm)
    result = edit(agent, SAMPLE_REPORT)
    assert result == SAMPLE_REPORT


# ── Fallback paths ────────────────────────────────────────────────────────────

def test_edit_returns_original_when_response_too_short():
    """If the response is shorter than 100 chars, the original report is returned."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response("Looks good.")
    agent = make_editor_agent(mock_llm)
    result = edit(agent, SAMPLE_REPORT)
    assert result == SAMPLE_REPORT


def test_edit_returns_original_when_response_is_tool_call():
    """If the response type is tool_call (unexpected), the original report is returned."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_tool_response()
    agent = make_editor_agent(mock_llm)
    result = edit(agent, SAMPLE_REPORT)
    assert result == SAMPLE_REPORT


def test_edit_returns_original_when_response_empty():
    """Empty response falls back to the original report."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response("")
    agent = make_editor_agent(mock_llm)
    result = edit(agent, SAMPLE_REPORT)
    assert result == SAMPLE_REPORT


# ── Agent interaction ─────────────────────────────────────────────────────────

def test_edit_calls_agent_chat_once():
    """edit() makes exactly one call to agent.chat."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(SAMPLE_REPORT)
    agent = make_editor_agent(mock_llm)
    edit(agent, SAMPLE_REPORT)
    assert mock_llm.chat.call_count == 1


def test_edit_passes_report_as_user_message():
    """The report is passed as the user message content."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(SAMPLE_REPORT)
    agent = make_editor_agent(mock_llm)
    edit(agent, SAMPLE_REPORT)
    # agent.chat() forwards messages as first positional arg to llm.chat()
    call_messages = mock_llm.chat.call_args[0][0]
    assert call_messages[0]["role"] == "user"
    assert call_messages[0]["content"] == SAMPLE_REPORT


def test_edit_passes_max_tokens():
    """max_tokens is forwarded to agent.chat."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(SAMPLE_REPORT)
    agent = make_editor_agent(mock_llm)
    edit(agent, SAMPLE_REPORT, max_tokens=4096)
    assert mock_llm.chat.call_args[1]["max_tokens"] == 4096


def test_edit_default_max_tokens_is_8192():
    """Default max_tokens is 8192 (large enough for a full report)."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(SAMPLE_REPORT)
    agent = make_editor_agent(mock_llm)
    edit(agent, SAMPLE_REPORT)
    assert mock_llm.chat.call_args[1]["max_tokens"] == 8192


def test_edit_rejects_response_shorter_than_half_original():
    """A response shorter than 50% of the original is rejected; original returned."""
    original = "A" * 200
    short = "B" * 99  # 99 < 100 = 50% of 200
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(short)
    agent = make_editor_agent(mock_llm)
    result = edit(agent, original)
    assert result == original


def test_edit_accepts_response_at_least_half_original():
    """Response >= 50% of original length is accepted (90 chars for 150-char original)."""
    original = "A" * 150
    response = "B" * 90  # 90 >= 75 = 50% of 150
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(response)
    agent = make_editor_agent(mock_llm)
    result = edit(agent, original)
    assert result == "B" * 90


def test_edit_rejects_276_char_response_against_5000_char_report():
    """A 276-char response against a 5000-char report fails the proportional check."""
    original = "A" * 5000
    short_response = "B" * 276  # 276 < 2500 = 50% of 5000
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(short_response)
    agent = make_editor_agent(mock_llm)
    result = edit(agent, original)
    assert result == original


def test_edit_rejects_refusal_phrase_in_first_60_chars():
    """Response starting with a refusal phrase is rejected even if proportionally long enough."""
    original = "X" * 100
    # 62 chars starting with "sorry" — passes proportional check (62 >= 50) but is a refusal
    refusal = "Sorry, I cannot edit this report as it falls outside my scope."
    assert len(refusal) >= 50
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(refusal)
    agent = make_editor_agent(mock_llm)
    result = edit(agent, original)
    assert result == original


def test_edit_uses_agent_system_prompt():
    """agent.chat is called, which routes through the agent's system_prompt."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(SAMPLE_REPORT)
    agent = make_editor_agent(mock_llm)
    edit(agent, SAMPLE_REPORT)
    # agent.chat passes system= to llm.chat; verify system= is the agent's prompt
    assert mock_llm.chat.call_args[1]["system"] == "You are a coherence editor."
