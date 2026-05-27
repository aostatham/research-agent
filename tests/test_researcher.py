"""
Tests for agent/researcher.py — research() function.

Verifies:
  - Returns ResearchResult on text response
  - ResearchResult has correct question, answer, sources, message_history fields
  - Tool call routing: executes search and continues loop
  - Source deduplication via _dedup_sources
  - Repeated query detection injects synthesis prompt
  - Tool-call-string detection redirects to summary
  - Fallback synthesis when max_iterations reached with accumulated results
  - Failure path when max_iterations reached with no results

All tests mock the LLM client and execute_tool_with_sources.
"""

import pytest
from unittest.mock import MagicMock, patch
from agent.researcher import research, _dedup_sources
from agent.base import Agent
from evidence.schema import ResearchResult
from llm.base import LLMResponse


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_text_response(content):
    return LLMResponse(type="text", content=content)


def make_tool_response(tool_name, tool_input):
    return LLMResponse(type="tool_call", tool_name=tool_name, tool_input=tool_input)


def make_agent(mock_llm, max_iterations=5):
    return Agent(
        name="researcher",
        role="researcher",
        description="Researcher agent",
        llm=mock_llm,
        system_prompt="You are a researcher.",
        max_iterations=max_iterations,
    )


# ── Return type and fields ────────────────────────────────────────────────────

def test_research_returns_research_result():
    """research() returns a ResearchResult object."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response("Fusion combines nuclei.")
    agent = make_agent(mock_llm)
    with patch("agent.researcher.execute_tool_with_sources", return_value=("results", [])):
        result = research(agent, "What is fusion?")
    assert isinstance(result, ResearchResult)


def test_research_result_has_question():
    """ResearchResult.question matches the input question."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response("Answer.")
    agent = make_agent(mock_llm)
    with patch("agent.researcher.execute_tool_with_sources", return_value=("results", [])):
        rr = research(agent, "What is fusion?")
    assert rr.question == "What is fusion?"


def test_research_result_has_answer():
    """ResearchResult.answer contains the LLM text response."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response("Fusion is powerful.")
    agent = make_agent(mock_llm)
    with patch("agent.researcher.execute_tool_with_sources", return_value=("results", [])):
        rr = research(agent, "What is fusion?")
    assert rr.answer == "Fusion is powerful."


def test_research_result_has_sources():
    """ResearchResult.sources contains sources from tool execution."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion"}),
        make_text_response("Answer."),
    ]
    mock_sources = [{"title": "Fusion Page", "url": "https://example.com/fusion"}]
    agent = make_agent(mock_llm)
    with patch("agent.researcher.execute_tool_with_sources",
               return_value=("results", mock_sources)):
        rr = research(agent, "What is fusion?")
    assert rr.sources == mock_sources


def test_research_result_has_message_history():
    """ResearchResult.message_history is a non-empty list."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response("Answer.")
    agent = make_agent(mock_llm)
    with patch("agent.researcher.execute_tool_with_sources", return_value=("results", [])):
        rr = research(agent, "What is fusion?")
    assert isinstance(rr.message_history, list)
    assert len(rr.message_history) > 0


# ── Loop guards ───────────────────────────────────────────────────────────────

def test_research_tool_call_then_text_returns_answer():
    """Tool call on turn 1 followed by text on turn 2 returns the text answer."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "nuclear fusion"}),
        make_text_response("Fusion combines light nuclei."),
    ]
    agent = make_agent(mock_llm)
    with patch("agent.researcher.execute_tool_with_sources",
               return_value=("search results", [])):
        rr = research(agent, "What is nuclear fusion?")
    assert rr.answer == "Fusion combines light nuclei."
    assert mock_llm.chat.call_count == 2


def test_research_executes_tool_with_correct_args():
    """execute_tool_with_sources is called with the exact tool name and input."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion energy 2026"}),
        make_text_response("Answer."),
    ]
    agent = make_agent(mock_llm)
    with patch("agent.researcher.execute_tool_with_sources",
               return_value=("results", [])) as mock_exec:
        research(agent, "State of fusion in 2026?")
    mock_exec.assert_called_once_with("web_search", {"query": "fusion energy 2026"})


def test_research_deduplicates_sources():
    """Duplicate URLs from multiple searches appear only once in returned sources."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion"}),
        make_tool_response("web_search", {"query": "fusion energy"}),
        make_text_response("Answer."),
    ]
    dup_sources = [{"title": "Same", "url": "https://example.com"}]
    agent = make_agent(mock_llm)
    with patch("agent.researcher.execute_tool_with_sources",
               return_value=("results", dup_sources)):
        rr = research(agent, "What is fusion?")
    urls = [s["url"] for s in rr.sources]
    assert urls.count("https://example.com") == 1


def test_research_detects_repeated_query():
    """Repeated identical queries trigger synthesis instead of another search."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion energy"}),
        make_tool_response("web_search", {"query": "fusion energy"}),  # repeat
        make_text_response("Fusion combines nuclei."),
    ]
    agent = make_agent(mock_llm)
    with patch("agent.researcher.execute_tool_with_sources",
               return_value=("search results", [])) as mock_exec:
        rr = research(agent, "What is fusion?")
    assert mock_exec.call_count == 1
    assert rr.answer == "Fusion combines nuclei."


def test_research_detects_oscillating_queries():
    """A→B→A oscillation triggers synthesis on the second A."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "query A"}),
        make_tool_response("web_search", {"query": "query B"}),
        make_tool_response("web_search", {"query": "query A"}),  # repeat
        make_text_response("Final answer."),
    ]
    agent = make_agent(mock_llm)
    with patch("agent.researcher.execute_tool_with_sources",
               return_value=("results", [])) as mock_exec:
        rr = research(agent, "test question")
    assert mock_exec.call_count == 2
    assert rr.answer == "Final answer."


def test_research_detects_tool_call_string():
    """Literal '[Calling ...]' text response is detected and redirected."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        LLMResponse(type="text", content="[Calling web_search with {'query': 'fusion'}]"),
        LLMResponse(type="text", content="Fusion is the process of combining atomic nuclei."),
    ]
    agent = make_agent(mock_llm)
    with patch("agent.researcher.execute_tool_with_sources", return_value=("results", [])):
        rr = research(agent, "What is fusion?")
    assert rr.answer == "Fusion is the process of combining atomic nuclei."


def test_research_fallback_synthesis_on_max_iterations():
    """Fallback synthesis returns an answer when max_iterations exhausted."""
    fallback_text = "This is a comprehensive fallback answer with more than fifty characters total."
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": f"query {i}"}) for i in range(5)
    ] + [make_text_response(fallback_text)]
    agent = make_agent(mock_llm, max_iterations=5)
    with patch("agent.researcher.execute_tool_with_sources",
               return_value=("search results", [])):
        rr = research(agent, "What is fusion?")
    assert rr.answer == fallback_text


def test_research_failure_path_returns_unable_message():
    """When max_iterations reached with no results, returns 'unable to retrieve'."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_tool_response("web_search", {"query": "fusion"})
    agent = make_agent(mock_llm, max_iterations=5)
    with patch("agent.researcher.execute_tool_with_sources", return_value=("results", [])):
        rr = research(agent, "What is fusion?")
    assert "unable to retrieve" in rr.answer.lower()


def test_research_uses_agent_max_iterations():
    """Loop respects agent.max_iterations, not a hardcoded value."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_tool_response("web_search", {"query": "fusion"})
    agent = make_agent(mock_llm, max_iterations=3)
    with patch("agent.researcher.execute_tool_with_sources", return_value=("results", [])):
        research(agent, "What is fusion?")
    # 3 iterations + 1 fallback attempt = 4 LLM calls
    assert mock_llm.chat.call_count == 4


def test_research_main_loop_uses_agent_system_prompt():
    """research() main loop calls agent.chat, injecting system=agent.system_prompt."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = make_text_response("Answer.")
    agent = make_agent(mock_llm)
    with patch("agent.researcher.execute_tool_with_sources", return_value=("results", [])):
        research(agent, "What is fusion?")
    call_kwargs = mock_llm.chat.call_args.kwargs
    assert call_kwargs["system"] == agent.system_prompt


def test_research_fallback_synthesis_uses_agent_system_prompt():
    """research() fallback synthesis calls agent.chat, injecting system=agent.system_prompt."""
    fallback_text = "This is a comprehensive fallback answer with more than fifty characters here."
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": f"query {i}"}) for i in range(5)
    ] + [make_text_response(fallback_text)]
    agent = make_agent(mock_llm, max_iterations=5)
    with patch("agent.researcher.execute_tool_with_sources", return_value=("results", [])):
        research(agent, "What is fusion?")
    fallback_call_kwargs = mock_llm.chat.call_args.kwargs
    assert fallback_call_kwargs["system"] == agent.system_prompt


def test_research_uses_agent_llm():
    """research() calls the agent's LLM, not a global one."""
    mock_llm_a = MagicMock()
    mock_llm_b = MagicMock()
    mock_llm_a.chat.return_value = make_text_response("Answer from A.")
    agent = make_agent(mock_llm_a)
    with patch("agent.researcher.execute_tool_with_sources", return_value=("results", [])):
        research(agent, "Q?")
    assert mock_llm_a.chat.called
    assert not mock_llm_b.chat.called


# ── _dedup_sources() ──────────────────────────────────────────────────────────

def test_dedup_sources_removes_duplicate_urls():
    """_dedup_sources() removes entries with repeated URLs."""
    sources = [
        {"title": "A", "url": "https://example.com"},
        {"title": "B", "url": "https://example.com"},
        {"title": "C", "url": "https://other.com"},
    ]
    result = _dedup_sources(sources)
    assert len(result) == 2


def test_dedup_sources_preserves_order():
    """_dedup_sources() preserves first-seen order."""
    sources = [
        {"title": "First", "url": "https://a.com"},
        {"title": "Second", "url": "https://b.com"},
        {"title": "Duplicate of first", "url": "https://a.com"},
    ]
    result = _dedup_sources(sources)
    assert result[0]["title"] == "First"
    assert result[1]["title"] == "Second"


def test_dedup_sources_empty_list():
    """_dedup_sources() handles empty input."""
    assert _dedup_sources([]) == []


def test_dedup_sources_no_duplicates_unchanged():
    """_dedup_sources() returns all entries when no duplicates exist."""
    sources = [
        {"title": "A", "url": "https://a.com"},
        {"title": "B", "url": "https://b.com"},
    ]
    result = _dedup_sources(sources)
    assert len(result) == 2


# ── H5: malformed tool input guard ───────────────────────────────────────────

def test_research_malformed_tool_input_does_not_raise():
    """Malformed tool_input (None) is skipped without raising AttributeError."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        LLMResponse(type="tool_call", tool_name="web_search", tool_input=None),
        make_text_response("Fusion is a nuclear reaction."),
    ]
    agent = make_agent(mock_llm, max_iterations=5)
    with patch("agent.researcher.execute_tool_with_sources", return_value=("r", [])):
        result = research(agent, "What is fusion?")
    assert isinstance(result, ResearchResult)


def test_research_non_dict_tool_input_does_not_raise():
    """Non-dict tool_input (int) is skipped without raising AttributeError."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        LLMResponse(type="tool_call", tool_name="web_search", tool_input=42),
        make_text_response("Fusion is a nuclear reaction."),
    ]
    agent = make_agent(mock_llm, max_iterations=5)
    with patch("agent.researcher.execute_tool_with_sources", return_value=("r", [])):
        result = research(agent, "What is fusion?")
    assert isinstance(result, ResearchResult)


def test_research_malformed_input_appends_corrective_messages():
    """Corrective messages are appended after malformed tool_input so the model sees new context."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        LLMResponse(type="tool_call", tool_name="web_search", tool_input=None),
        make_text_response("Fusion is a nuclear reaction."),
    ]
    agent = make_agent(mock_llm, max_iterations=5)
    with patch("agent.researcher.execute_tool_with_sources", return_value=("r", [])):
        result = research(agent, "What is fusion?")
    # The second chat call must receive a messages list containing the corrective pair
    second_call_messages = mock_llm.chat.call_args_list[1][0][0]
    roles = [m["role"] for m in second_call_messages]
    assert "assistant" in roles
    assert roles[-1] == "user"
    # The corrective user message must direct the model away from tools
    last_user = next(m for m in reversed(second_call_messages) if m["role"] == "user")
    assert "Do not use any tools" in last_user["content"]


