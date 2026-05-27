"""
Tests for agent/editor.py — edit() function.

Verifies:
  - Returns a string
  - Returns the edited report when the agent provides a valid response
  - Returns the original report when the response is too short (< 50% of original)
  - Returns the original report when the response is not a text response
  - Calls agent.chat with the report as the user message content
  - Passes max_tokens through to the agent chat call
  - Uses the agent's system prompt (via agent.chat)
  - Acceptance requires both length >= 50% AND similarity ratio >= 0.5 (M3+M5)
  - Preamble-only responses are rejected by the length check
  - Refusal messages are rejected by both checks
  - Valid minor edits pass both checks
  - Original is returned unchanged when either check fails

All tests mock the agent's LLM.
"""

import logging
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
    """Response >= 50% of original AND similar content is accepted."""
    # Minor edit: one sentence changed — passes both length and similarity checks
    original = SAMPLE_REPORT
    edited = SAMPLE_REPORT.replace(
        "Nuclear fusion is a process where light atomic nuclei combine to release energy.",
        "Nuclear fusion combines light atomic nuclei to release enormous energy.",
    )
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(edited)
    agent = make_editor_agent(mock_llm)
    result = edit(agent, original)
    assert result == edited


def test_edit_rejects_276_char_response_against_5000_char_report():
    """A 276-char response against a 5000-char report fails the proportional check."""
    original = "A" * 5000
    short_response = "B" * 276  # 276 < 2500 = 50% of 5000
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(short_response)
    agent = make_editor_agent(mock_llm)
    result = edit(agent, original)
    assert result == original


def test_edit_rejects_preamble_only_response_by_length():
    """A preamble-only response (no report body) is rejected by the length check."""
    original = "A" * 3000
    preamble = "Here is the edited report, no changes needed."  # ~46 chars < 1500 = 50% of 3000
    assert len(preamble) < 0.5 * len(original)
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(preamble)
    agent = make_editor_agent(mock_llm)
    result = edit(agent, original)
    assert result == original


def test_edit_rejects_refusal_message_by_length_and_similarity():
    """A 200-char refusal against a 3000-char original fails both checks."""
    original = "A" * 3000
    refusal = "Sorry, I cannot edit this report as it falls outside my scope. " * 3  # ~192 chars
    assert len(refusal) < 0.5 * len(original)  # length check fails
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(refusal)
    agent = make_editor_agent(mock_llm)
    result = edit(agent, original)
    assert result == original


def test_edit_accepts_valid_minor_edit():
    """A valid minor edit (one sentence changed) passes both length and similarity checks."""
    original = SAMPLE_REPORT
    edited = original.replace(
        "The primary challenges include plasma confinement and materials science.",
        "The primary challenges include plasma confinement, materials science, and tritium supply.",
    )
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(edited)
    agent = make_editor_agent(mock_llm)
    result = edit(agent, original)
    assert result == edited


def test_edit_accepts_valid_short_original():
    """A 150-char edited report from a 200-char original passes both checks."""
    original = (
        "Nuclear fusion is a process where light atomic nuclei combine to release energy. "
        "This reaction powers the Sun and has been studied since the 1950s for energy."
    )
    # Trim 20 chars — still >= 50% length and high similarity
    edited = original[:-20]
    assert len(edited) >= 0.5 * len(original)
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(edited)
    agent = make_editor_agent(mock_llm)
    result = edit(agent, original)
    assert result == edited


def test_edit_uses_agent_system_prompt():
    """agent.chat is called, which routes through the agent's system_prompt."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(SAMPLE_REPORT)
    agent = make_editor_agent(mock_llm)
    edit(agent, SAMPLE_REPORT)
    # agent.chat passes system= to llm.chat; verify system= is the agent's prompt
    assert mock_llm.chat.call_args[1]["system"] == "You are a coherence editor."


# ── FIX 3 — autojunk=False and length cap ────────────────────────────────────

def test_edit_autojunk_false_handles_repetitive_content():
    """Repetitive content compared to itself returns ratio >= 0.5 with autojunk=False."""
    # Highly repetitive report: SequenceMatcher with autojunk=True would mark
    # most elements as junk and return a near-zero ratio.
    repetitive = ("nuclear fusion " * 200).strip()
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(repetitive)
    agent = make_editor_agent(mock_llm)
    result = edit(agent, repetitive)
    # Should be accepted — identical content has ratio 1.0 regardless of autojunk
    assert result == repetitive


# ── FIX 4 — preamble stripping and exact-50% floor ───────────────────────────

def test_edit_strips_preamble_when_original_follows():
    """'Here is the edited report:\\n\\n' + original is stripped to original and returned."""
    preamble = "Here is the edited report:\n\n"
    response_text = preamble + SAMPLE_REPORT
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(response_text)
    agent = make_editor_agent(mock_llm)
    result = edit(agent, SAMPLE_REPORT)
    assert result == SAMPLE_REPORT


def test_edit_rejects_exactly_half_length_response():
    """A response of exactly len(original) * 0.5 characters is rejected."""
    original = "A" * 200
    exactly_half = "B" * 100  # exactly 50% — must be rejected (M6: <= not <)
    assert len(exactly_half) == 0.5 * len(original)
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(exactly_half)
    agent = make_editor_agent(mock_llm)
    result = edit(agent, original)
    assert result == original


def test_edit_accepts_just_over_half_length_response():
    """A response of len(original) * 0.5 + 1 characters passes the length floor."""
    original = "A" * 200
    just_over = ("A" * 101) + ("B" * 20)  # 101 chars same prefix — passes length AND similarity
    assert len(just_over) > 0.5 * len(original)
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(just_over)
    agent = make_editor_agent(mock_llm)
    result = edit(agent, original)
    assert result == just_over


def test_edit_length_cap_skips_similarity_check():
    """Strings over 100000 chars skip the similarity check and accept the response."""
    # Response is very different but exceeds the length cap — similarity skipped.
    long_original = ("A sentence about nuclear fusion. " * 4000).strip()   # ~131999 chars
    long_edited = ("B sentence about nuclear fusion. " * 4000).strip()     # different content
    assert len(long_original) > 100000
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response(long_edited)
    agent = make_editor_agent(mock_llm)
    result = edit(agent, long_original)
    # Accepted because length cap bypasses similarity check
    assert result == long_edited


# ── Exception handling ────────────────────────────────────────────────────────

def test_edit_catches_read_timeout_and_returns_original(caplog):
    """ReadTimeout raised by the LLM is caught; original report is returned."""
    import requests.exceptions
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = requests.exceptions.ReadTimeout("timed out")
    agent = make_editor_agent(mock_llm)
    with caplog.at_level(logging.WARNING):
        result = edit(agent, SAMPLE_REPORT)
    assert result == SAMPLE_REPORT
    assert any("Editor pass failed" in r.message for r in caplog.records)


def test_edit_catches_generic_exception_and_returns_original(caplog):
    """Any Exception raised by the LLM is caught; original report is returned."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = RuntimeError("unexpected LLM error")
    agent = make_editor_agent(mock_llm)
    with caplog.at_level(logging.WARNING):
        result = edit(agent, SAMPLE_REPORT)
    assert result == SAMPLE_REPORT
    assert any("Editor pass failed" in r.message for r in caplog.records)


def test_edit_exception_warning_includes_exception_type(caplog):
    """The WARNING message includes the exception class name."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = ValueError("bad value")
    agent = make_editor_agent(mock_llm)
    with caplog.at_level(logging.WARNING):
        edit(agent, SAMPLE_REPORT)
    assert any("ValueError" in r.message for r in caplog.records)
