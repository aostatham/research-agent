"""
Tests for agent/orchestrator.py — Orchestrator.

Verifies:
    - decompose(): JSON parsing, max_questions enforcement, fallback on bad JSON,
      prompt includes min/max bounds, max_tokens passed from config.
    - _research_question_sync(): text/tool_call routing, message history accumulation,
      repeated query detection, tool-call-string detection, max_iterations guard,
      source deduplication, config.max_tokens_research respected.
    - research_question_async() / research_all_async(): async wrapper, semaphore
      gating, parallel dispatch, result and source aggregation.
    - reflect(): JSON parsing, sufficient/insufficient paths, markdown-fenced JSON
      handling, fallback on parse error, topic and findings included in prompt.
    - run(): full pipeline composition, gap research triggered on insufficient
      reflection, gap research skipped when sufficient.

All tests mock the LLM and patch execute_tool_with_sources to avoid API calls.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch
from agent.orchestrator import Orchestrator
from llm.base import LLMResponse
from config import Config


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def config():
    """Standard Config for orchestrator tests."""
    return Config(
        min_questions=4,
        max_questions=5,
        max_iterations=5,
        max_tokens_research=2048,
        max_tokens_synthesis=8192
    )


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    return MagicMock()


@pytest.fixture
def orchestrator(mock_llm, config):
    """Orchestrator wired to a mock LLM and test config."""
    return Orchestrator(llm=mock_llm, config=config)


def make_text_response(content):
    """Build a text LLMResponse with the given content string."""
    return LLMResponse(type="text", content=content)


def make_tool_response(tool_name, tool_input):
    """Build a tool_call LLMResponse for the given tool and input dict."""
    return LLMResponse(type="tool_call", tool_name=tool_name, tool_input=tool_input)


# ── decompose() tests ─────────────────────────────────────────────────────────
# Verify topic decomposition: JSON parsing, slicing to max_questions, fallback.

def test_decompose_returns_list_of_questions(orchestrator, mock_llm):
    """Valid JSON array response is parsed into a list of question strings."""
    mock_llm.chat.return_value = make_text_response(
        '["What is fusion?", "How does fusion work?", "What are fusion challenges?", "Who leads fusion research?"]'
    )
    questions = orchestrator.decompose("nuclear fusion")
    assert isinstance(questions, list)
    assert len(questions) >= 1
    assert all(isinstance(q, str) for q in questions)


def test_decompose_invalid_json_returns_fallback(orchestrator, mock_llm):
    """Non-JSON response triggers the four-question fallback list."""
    mock_llm.chat.return_value = make_text_response("not valid json at all")
    questions = orchestrator.decompose("nuclear fusion")
    assert isinstance(questions, list)
    assert len(questions) >= 4


def test_decompose_calls_llm_once(orchestrator, mock_llm):
    """decompose() makes exactly one LLM call."""
    mock_llm.chat.return_value = make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]')
    orchestrator.decompose("nuclear fusion")
    assert mock_llm.chat.call_count == 1


def test_decompose_respects_max_questions(orchestrator, mock_llm, config):
    """Returned list is capped at config.max_questions even if LLM returns more."""
    config.max_questions = 3
    mock_llm.chat.return_value = make_text_response(
        '["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"]'
    )
    questions = orchestrator.decompose("nuclear fusion")
    assert len(questions) <= 3


def test_decompose_includes_min_max_in_prompt(orchestrator, mock_llm, config):
    """Prompt sent to LLM includes both min and max question counts."""
    config.min_questions = 3
    config.max_questions = 6
    mock_llm.chat.return_value = make_text_response('["Q1?", "Q2?", "Q3?"]')
    orchestrator.decompose("nuclear fusion")
    call_content = mock_llm.chat.call_args[1]["messages"][0]["content"]
    assert "3" in call_content
    assert "6" in call_content


def test_decompose_fallback_meets_min_questions(orchestrator, mock_llm):
    """Fallback list always has at least 4 questions."""
    mock_llm.chat.return_value = make_text_response("not valid json")
    questions = orchestrator.decompose("nuclear fusion")
    assert len(questions) >= 4


def test_decompose_uses_config_max_tokens(orchestrator, mock_llm, config):
    """max_tokens passed to LLM matches config.max_tokens_research."""
    config.max_tokens_research = 512
    mock_llm.chat.return_value = make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]')
    orchestrator.decompose("nuclear fusion")
    assert mock_llm.chat.call_args[1]["max_tokens"] == 512


# ── _research_question_sync() tests ──────────────────────────────────────────
# Verify the agentic loop: routing, history building, guards, source handling.

def test_research_question_returns_text_directly(orchestrator, mock_llm):
    """If the first response is text, it is returned immediately."""
    mock_llm.chat.return_value = make_text_response("Fusion is the process of combining atoms.")
    with patch("agent.orchestrator.execute_tool_with_sources", return_value=("results", [])):
        result, sources = orchestrator._research_question_sync("What is fusion?")
    assert result == "Fusion is the process of combining atoms."
    assert isinstance(sources, list)


def test_research_question_returns_sources(orchestrator, mock_llm):
    """Sources from tool execution are returned alongside the answer."""
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "nuclear fusion"}),
        make_text_response("Fusion combines nuclei.")
    ]
    mock_sources = [{"title": "Fusion News", "url": "https://example.com/fusion"}]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("results", mock_sources)):
        result, sources = orchestrator._research_question_sync("What is fusion?")
    assert sources == mock_sources


def test_research_question_handles_tool_call_then_text(orchestrator, mock_llm):
    """Tool call on turn 1 followed by text on turn 2 returns the text answer."""
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "what is nuclear fusion"}),
        make_text_response("Fusion combines light atomic nuclei.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("search results here", [])):
        result, sources = orchestrator._research_question_sync("What is nuclear fusion?")
    assert result == "Fusion combines light atomic nuclei."
    assert mock_llm.chat.call_count == 2


def test_research_question_executes_tool_with_correct_args(orchestrator, mock_llm):
    """execute_tool_with_sources is called with the exact tool name and input from the LLM."""
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion energy 2026"}),
        make_text_response("Here are the findings.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("results", [])) as mock_execute:
        orchestrator._research_question_sync("What is the state of fusion in 2026?")
    mock_execute.assert_called_once_with("web_search", {"query": "fusion energy 2026"})


def test_research_question_appends_tool_results_to_history(orchestrator, mock_llm):
    """Search results are present in the message history for the second LLM call."""
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion"}),
        make_text_response("Answer.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("specific tool output here", [])):
        orchestrator._research_question_sync("What is fusion?")
    second_call_messages = mock_llm.chat.call_args_list[1][1]["messages"]
    message_contents = [m["content"] for m in second_call_messages]
    assert any("specific tool output here" in c for c in message_contents)


def test_research_question_message_history_has_original_question(orchestrator, mock_llm):
    """The original question is still visible in the message history after a search."""
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion energy"}),
        make_text_response("Fusion combines nuclei.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("search results", [])):
        orchestrator._research_question_sync("What is nuclear fusion?")
    second_call_messages = mock_llm.chat.call_args_list[1][1]["messages"]
    message_contents = " ".join(m["content"] for m in second_call_messages)
    assert "What is nuclear fusion?" in message_contents


def test_research_question_detects_tool_call_string_and_retries(orchestrator, mock_llm):
    """
    Regression test: some models return a literal '[Calling ...]' string as text
    instead of a proper tool_call response.  This must be detected and redirected.
    """
    mock_llm.chat.side_effect = [
        LLMResponse(type="text", content="[Calling web_search with {'query': 'fusion'}]"),
        LLMResponse(type="text", content="Fusion is the process of combining atomic nuclei.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources", return_value=("results", [])):
        result, sources = orchestrator._research_question_sync("What is fusion?")
    assert result == "Fusion is the process of combining atomic nuclei."
    assert mock_llm.chat.call_count == 2


def test_research_question_tool_result_included_in_history(orchestrator, mock_llm):
    """Tool output is injected into the message history so the LLM can use it."""
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion"}),
        make_text_response("Answer.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("specific tool output here", [])):
        orchestrator._research_question_sync("What is fusion?")
    second_call_messages = mock_llm.chat.call_args_list[1][1]["messages"]
    message_contents = " ".join(m["content"] for m in second_call_messages)
    assert "specific tool output here" in message_contents


def test_research_question_uses_config_max_tokens(orchestrator, mock_llm, config):
    """max_tokens in every LLM call reflects config.max_tokens_research."""
    config.max_tokens_research = 1024
    mock_llm.chat.return_value = make_text_response("Answer.")
    with patch("agent.orchestrator.execute_tool_with_sources", return_value=("results", [])):
        orchestrator._research_question_sync("What is fusion?")
    assert mock_llm.chat.call_args[1]["max_tokens"] == 1024


def test_research_question_deduplicates_sources(orchestrator, mock_llm):
    """Duplicate URLs from multiple searches appear only once in returned sources."""
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion"}),
        make_tool_response("web_search", {"query": "fusion energy"}),
        make_text_response("Answer.")
    ]
    duplicate_sources = [{"title": "Same Page", "url": "https://example.com"}]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("results", duplicate_sources)):
        result, sources = orchestrator._research_question_sync("What is fusion?")
    urls = [s["url"] for s in sources]
    assert urls.count("https://example.com") == 1


def test_research_question_exits_loop_at_max_iterations(orchestrator, mock_llm):
    """Loop exits at max_iterations; fallback synthesis attempted; returns 'unable to retrieve'."""
    mock_llm.chat.return_value = make_tool_response("web_search", {"query": "fusion"})
    with patch("agent.orchestrator.execute_tool_with_sources", return_value=("results", [])):
        result, sources = orchestrator._research_question_sync("What is fusion?")
    assert "unable to retrieve" in result.lower()
    assert mock_llm.chat.call_count == 6


def test_research_question_handles_repeated_query(orchestrator, mock_llm):
    """Repeated identical queries trigger a synthesis-forcing message instead of another search."""
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion energy"}),
        make_tool_response("web_search", {"query": "fusion energy"}),  # repeat
        make_text_response("Fusion combines nuclei releasing energy.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("search results", [])):
        result, sources = orchestrator._research_question_sync("What is fusion?")
    assert result == "Fusion combines nuclei releasing energy."
    assert mock_llm.chat.call_count == 3


def test_research_question_does_not_call_tool_on_repeated_query(orchestrator, mock_llm):
    """execute_tool_with_sources is called only once for a repeated query pair."""
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion energy"}),
        make_tool_response("web_search", {"query": "fusion energy"}),  # repeat
        make_text_response("Answer.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("search results", [])) as mock_execute:
        orchestrator._research_question_sync("What is fusion?")
    assert mock_execute.call_count == 1


def test_research_question_allows_different_queries(orchestrator, mock_llm):
    """Different queries each trigger a real search execution."""
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion basics"}),
        make_tool_response("web_search", {"query": "fusion challenges"}),
        make_text_response("Answer.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("results", [])) as mock_execute:
        orchestrator._research_question_sync("What is fusion?")
    assert mock_execute.call_count == 2


def test_research_question_detects_oscillating_queries(orchestrator, mock_llm):
    """A→B→A oscillation triggers synthesis on the second A; tool called only for A and B."""
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "query A"}),
        make_tool_response("web_search", {"query": "query B"}),
        make_tool_response("web_search", {"query": "query A"}),  # repeat A
        make_text_response("Final answer after synthesis forced."),
    ]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("results", [])) as mock_execute:
        result, sources = orchestrator._research_question_sync("test question")
    assert mock_execute.call_count == 2
    assert result == "Final answer after synthesis forced."


def test_research_question_fallback_synthesis_succeeds(orchestrator, mock_llm):
    """Fallback synthesis returns an answer when max_iterations is reached with accumulated results."""
    fallback_text = "This is a comprehensive fallback answer with more than fifty characters total."
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": f"query {i}"}) for i in range(5)
    ] + [make_text_response(fallback_text)]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("search results", [])):
        result, sources = orchestrator._research_question_sync("What is fusion?")
    assert result == fallback_text
    assert mock_llm.chat.call_count == 6


# ── reflect() tests ───────────────────────────────────────────────────────────
# Verify JSON parsing, sufficient/insufficient paths, prompt content, edge cases.

def test_reflect_returns_sufficient_true(orchestrator, mock_llm):
    """sufficient=true JSON response returns (True, [])."""
    mock_llm.chat.return_value = make_text_response('{"sufficient": true, "missing": []}')
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is True
    assert missing == []


def test_reflect_returns_sufficient_false_with_gaps(orchestrator, mock_llm):
    """sufficient=false JSON response returns the missing list."""
    mock_llm.chat.return_value = make_text_response(
        '{"sufficient": false, "missing": ["commercial viability", "development timeline"]}'
    )
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is False
    assert "commercial viability" in missing
    assert "development timeline" in missing


def test_reflect_invalid_json_defaults_to_sufficient(orchestrator, mock_llm):
    """Parse failure defaults to sufficient=True to avoid spurious extra research."""
    mock_llm.chat.return_value = make_text_response("not valid json")
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is True
    assert missing == []


def test_reflect_uses_config_max_tokens(orchestrator, mock_llm, config):
    """max_tokens for the reflect call matches config.max_tokens_research."""
    config.max_tokens_research = 512
    mock_llm.chat.return_value = make_text_response('{"sufficient": true, "missing": []}')
    orchestrator.reflect("fusion", {"Q1": "A1"})
    assert mock_llm.chat.call_args[1]["max_tokens"] == 512


def test_reflect_includes_topic_in_prompt(orchestrator, mock_llm):
    """The topic string appears in the prompt sent to the LLM."""
    mock_llm.chat.return_value = make_text_response('{"sufficient": true, "missing": []}')
    orchestrator.reflect("nuclear fusion", {"Q1": "A1"})
    call_content = mock_llm.chat.call_args[1]["messages"][0]["content"]
    assert "nuclear fusion" in call_content


def test_reflect_includes_findings_in_prompt(orchestrator, mock_llm):
    """The question strings from the results dict appear in the prompt."""
    mock_llm.chat.return_value = make_text_response('{"sufficient": true, "missing": []}')
    orchestrator.reflect("fusion", {"What is fusion?": "Fusion combines nuclei."})
    call_content = mock_llm.chat.call_args[1]["messages"][0]["content"]
    assert "What is fusion?" in call_content


def test_reflect_handles_markdown_fenced_json(orchestrator, mock_llm):
    """JSON wrapped in ```json code fences is stripped and parsed correctly."""
    mock_llm.chat.return_value = make_text_response(
        '```json\n{"sufficient": true, "missing": []}\n```'
    )
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is True


def test_reflect_prompt_includes_full_findings(orchestrator, mock_llm):
    """Answers up to 300 chars are included in the prompt (truncation check)."""
    mock_llm.chat.return_value = make_text_response('{"sufficient": true, "missing": []}')
    results = {"What is fusion?": "A" * 400}
    orchestrator.reflect("fusion", results)
    call_content = mock_llm.chat.call_args[1]["messages"][0]["content"]
    assert "A" * 300 in call_content


def test_reflect_returns_all_gaps_without_filtering(orchestrator, mock_llm):
    """All gap strings are returned regardless of their length."""
    mock_llm.chat.return_value = make_text_response(
        '{"sufficient": false, "missing": ["timeline", "cost", "commercial viability and investment landscape"]}'
    )
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is False
    assert "timeline" in missing
    assert "cost" in missing
    assert "commercial viability and investment landscape" in missing


# ── run() tests ───────────────────────────────────────────────────────────────
# Verify the full pipeline composition: decompose + research + reflect + gap fill.

def test_run_returns_dict_of_results(orchestrator, mock_llm):
    """run() returns a results dict with one entry per question."""
    mock_llm.chat.side_effect = [
        make_text_response('["What is fusion?", "How does fusion work?", "What are challenges?", "Who leads research?"]'),
        make_text_response("Fusion is combining atoms."),
        make_text_response("Fusion works via plasma confinement."),
        make_text_response("Challenges include plasma instability."),
        make_text_response("ITER and CFS lead research."),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    with patch("agent.orchestrator.execute_tool_with_sources", return_value=("results", [])):
        results, sources = orchestrator.run("nuclear fusion")
    assert isinstance(results, dict)
    assert isinstance(sources, dict)
    assert len(results) == 4


def test_run_returns_sources_dict(orchestrator, mock_llm):
    """run() returns a sources dict keyed by question."""
    mock_llm.chat.side_effect = [
        make_text_response('["What is fusion?", "What are challenges?", "Who leads?", "What is timeline?"]'),
        make_text_response("Fusion is combining atoms."),
        make_text_response("Challenges include instability."),
        make_text_response("ITER leads."),
        make_text_response("Timeline is 2035."),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    mock_sources = [{"title": "Source", "url": "https://example.com"}]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("results", mock_sources)):
        results, sources = orchestrator.run("nuclear fusion")
    assert isinstance(sources, dict)
    for question in results:
        assert question in sources


def test_run_researches_gaps_when_insufficient(orchestrator, mock_llm):
    """Gap questions identified by reflect() are added to results and sources."""
    mock_llm.chat.side_effect = [
        make_text_response('["What is fusion?", "What are challenges?", "Who leads?", "What is the timeline?"]'),
        make_text_response("Fusion is combining atoms."),
        make_text_response("Challenges include plasma instability."),
        make_text_response("ITER leads."),
        make_text_response("Timeline is 2035."),
        make_text_response('{"sufficient": false, "missing": ["commercial timeline"]}'),
        make_text_response("Commercial fusion expected by 2035."),
    ]
    with patch("agent.orchestrator.execute_tool_with_sources", return_value=("results", [])):
        results, sources = orchestrator.run("nuclear fusion")
    assert "commercial timeline" in results
    assert "commercial timeline" in sources


def test_run_does_not_research_gaps_when_sufficient(orchestrator, mock_llm):
    """When reflect returns sufficient=True, no extra LLM calls are made."""
    mock_llm.chat.side_effect = [
        make_text_response('["What is fusion?", "What are challenges?", "Who leads?", "What is the timeline?"]'),
        make_text_response("Fusion is combining atoms."),
        make_text_response("Challenges include plasma instability."),
        make_text_response("ITER leads."),
        make_text_response("Timeline is 2035."),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    with patch("agent.orchestrator.execute_tool_with_sources", return_value=("results", [])):
        results, sources = orchestrator.run("nuclear fusion")
    # 1 decompose + 4 research + 1 reflect = exactly 6 calls
    assert mock_llm.chat.call_count == 6


def test_run_uses_config_question_bounds(orchestrator, mock_llm, config):
    """run() respects config.max_questions by researching exactly that many questions."""
    config.min_questions = 3
    config.max_questions = 3
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?"]'),
        make_text_response("A1."),
        make_text_response("A2."),
        make_text_response("A3."),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    with patch("agent.orchestrator.execute_tool_with_sources", return_value=("results", [])):
        results, sources = orchestrator.run("nuclear fusion")
    assert len(results) == 3


# ── Async / parallel research tests (Phase D Part 1) ─────────────────────────
# Verify research_question_async, research_all_async, and max_workers config.

def test_run_async_returns_correct_tuple_shape(orchestrator, mock_llm):
    """run_async() returns a (dict, dict) tuple from an async context."""
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]'),
        make_text_response("A1."),
        make_text_response("A2."),
        make_text_response("A3."),
        make_text_response("A4."),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    with patch("agent.orchestrator.execute_tool_with_sources", return_value=("results", [])):
        results, sources = asyncio.run(orchestrator.run_async("nuclear fusion"))
    assert isinstance(results, dict)
    assert isinstance(sources, dict)


def test_config_max_workers_default():
    """Config defaults max_workers to 2 (safe ceiling for Ollama)."""
    assert Config().max_workers == 2


def test_research_all_async_results_have_all_questions(orchestrator):
    """research_all_async returns one result entry per input question."""
    with patch.object(orchestrator, '_research_question_sync', return_value=("answer", [])):
        results, _ = asyncio.run(orchestrator.research_all_async(["Q1?", "Q2?", "Q3?"]))
    assert set(results.keys()) == {"Q1?", "Q2?", "Q3?"}


def test_research_all_async_sources_have_all_questions(orchestrator):
    """research_all_async returns one sources entry per input question."""
    with patch.object(orchestrator, '_research_question_sync', return_value=("answer", [])):
        _, sources = asyncio.run(orchestrator.research_all_async(["Q1?", "Q2?"]))
    assert set(sources.keys()) == {"Q1?", "Q2?"}


def test_research_all_async_calls_sync_per_question(orchestrator):
    """_research_question_sync is invoked once per input question."""
    with patch.object(orchestrator, '_research_question_sync', return_value=("a", [])) as m:
        asyncio.run(orchestrator.research_all_async(["Q1?", "Q2?", "Q3?"]))
    assert m.call_count == 3


def test_research_all_async_empty_questions(orchestrator):
    """research_all_async with an empty list returns empty dicts."""
    results, sources = asyncio.run(orchestrator.research_all_async([]))
    assert results == {}
    assert sources == {}


def test_research_all_async_preserves_answers(orchestrator):
    """research_all_async passes through each answer from _research_question_sync."""
    def fake_sync(q):
        return (f"Answer for {q}", [])
    with patch.object(orchestrator, '_research_question_sync', side_effect=fake_sync):
        results, _ = asyncio.run(orchestrator.research_all_async(["Q1?", "Q2?"]))
    assert results["Q1?"] == "Answer for Q1?"
    assert results["Q2?"] == "Answer for Q2?"


def test_research_question_async_calls_sync(orchestrator):
    """research_question_async delegates to _research_question_sync."""
    sem = asyncio.Semaphore(4)
    with patch.object(orchestrator, '_research_question_sync',
                      return_value=("ans", [{"title": "T", "url": "u"}])) as m:
        result, srcs = asyncio.run(orchestrator.research_question_async("Q?", sem))
    m.assert_called_once_with("Q?")
    assert result == "ans"


def test_run_max_workers_respected(orchestrator, mock_llm, config):
    """run() processes all questions even when max_workers is smaller than question count."""
    config.max_workers = 2
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]'),
        make_text_response("A1."),
        make_text_response("A2."),
        make_text_response("A3."),
        make_text_response("A4."),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    with patch("agent.orchestrator.execute_tool_with_sources", return_value=("results", [])):
        results, sources = orchestrator.run("nuclear fusion")
    assert len(results) == 4


def test_run_gap_research_also_parallel(orchestrator, mock_llm):
    """Gap questions identified by reflect() are also researched via research_all_async."""
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]'),
        make_text_response("A1."),
        make_text_response("A2."),
        make_text_response("A3."),
        make_text_response("A4."),
        make_text_response('{"sufficient": false, "missing": ["gap1", "gap2"]}'),
        make_text_response("Gap answer 1."),
        make_text_response("Gap answer 2."),
    ]
    with patch("agent.orchestrator.execute_tool_with_sources", return_value=("results", [])):
        results, sources = orchestrator.run("nuclear fusion")
    assert "gap1" in results
    assert "gap2" in results
    assert "gap1" in sources
    assert "gap2" in sources


# ── AgentPool wiring ─────────────────────────────────────────────────────────

def test_orchestrator_accepts_agent_pool_none(mock_llm, config):
    """Orchestrator constructs without agent_pool (existing behaviour preserved)."""
    orch = Orchestrator(llm=mock_llm, config=config, agent_pool=None)
    assert orch.agent_pool is None


def test_orchestrator_accepts_no_agent_pool_kwarg(mock_llm, config):
    """Orchestrator constructs without passing agent_pool at all."""
    orch = Orchestrator(llm=mock_llm, config=config)
    assert orch.agent_pool is None


def test_orchestrator_stores_agent_pool(mock_llm, config):
    """Provided AgentPool is stored on self.agent_pool."""
    mock_pool = MagicMock()
    orch = Orchestrator(llm=mock_llm, config=config, agent_pool=mock_pool)
    assert orch.agent_pool is mock_pool


# ── Integration tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
def test_real_orchestrator_run():
    """Live end-to-end orchestrator run produces a populated results dict."""
    from llm import AnthropicClient
    from dotenv import load_dotenv
    load_dotenv()

    llm = AnthropicClient()
    orchestrator = Orchestrator(llm=llm)
    results, sources = orchestrator.run("the current state of nuclear fusion energy")

    assert isinstance(results, dict)
    assert isinstance(sources, dict)
    assert len(results) >= 3
    for question, answer in results.items():
        assert isinstance(question, str)
        assert isinstance(answer, str)
        assert len(answer) > 100
