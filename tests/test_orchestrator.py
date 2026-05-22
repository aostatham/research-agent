import pytest
from unittest.mock import MagicMock, patch
from agent.orchestrator import Orchestrator
from llm.base import LLMResponse
from config import Config


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def config():
    return Config(
        min_questions=4,
        max_questions=5,
        max_iterations=5,
        max_tokens_research=2048,
        max_tokens_synthesis=8192
    )


@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.fixture
def orchestrator(mock_llm, config):
    return Orchestrator(llm=mock_llm, config=config)


def make_text_response(content):
    return LLMResponse(type="text", content=content)


def make_tool_response(tool_name, tool_input):
    return LLMResponse(type="tool_call", tool_name=tool_name, tool_input=tool_input)


# ── decompose() tests ─────────────────────────────────────────────────────────

def test_decompose_returns_list_of_questions(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response(
        '["What is fusion?", "How does fusion work?", "What are fusion challenges?", "Who leads fusion research?"]'
    )
    questions = orchestrator.decompose("nuclear fusion")
    assert isinstance(questions, list)
    assert len(questions) >= 1
    assert all(isinstance(q, str) for q in questions)


def test_decompose_invalid_json_returns_fallback(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response("not valid json at all")
    questions = orchestrator.decompose("nuclear fusion")
    assert isinstance(questions, list)
    assert len(questions) >= 4


def test_decompose_calls_llm_once(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]')
    orchestrator.decompose("nuclear fusion")
    assert mock_llm.chat.call_count == 1


def test_decompose_respects_max_questions(orchestrator, mock_llm, config):
    config.max_questions = 3
    mock_llm.chat.return_value = make_text_response(
        '["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"]'
    )
    questions = orchestrator.decompose("nuclear fusion")
    assert len(questions) <= 3


def test_decompose_includes_min_max_in_prompt(orchestrator, mock_llm, config):
    config.min_questions = 3
    config.max_questions = 6
    mock_llm.chat.return_value = make_text_response('["Q1?", "Q2?", "Q3?"]')
    orchestrator.decompose("nuclear fusion")
    call_content = mock_llm.chat.call_args[1]["messages"][0]["content"]
    assert "3" in call_content
    assert "6" in call_content


def test_decompose_fallback_meets_min_questions(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response("not valid json")
    questions = orchestrator.decompose("nuclear fusion")
    assert len(questions) >= 4


def test_decompose_uses_config_max_tokens(orchestrator, mock_llm, config):
    config.max_tokens_research = 512
    mock_llm.chat.return_value = make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]')
    orchestrator.decompose("nuclear fusion")
    assert mock_llm.chat.call_args[1]["max_tokens"] == 512


# ── research_question() tests ─────────────────────────────────────────────────

def test_research_question_returns_text_directly(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response("Fusion is the process of combining atoms.")
    with patch("agent.orchestrator.execute_tool_with_sources", return_value=("results", [])):
        result, sources = orchestrator.research_question("What is fusion?")
    assert result == "Fusion is the process of combining atoms."
    assert isinstance(sources, list)


def test_research_question_returns_sources(orchestrator, mock_llm):
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "nuclear fusion"}),
        make_text_response("Fusion combines nuclei.")
    ]
    mock_sources = [{"title": "Fusion News", "url": "https://example.com/fusion"}]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("results", mock_sources)):
        result, sources = orchestrator.research_question("What is fusion?")
    assert sources == mock_sources


def test_research_question_handles_tool_call_then_text(orchestrator, mock_llm):
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "what is nuclear fusion"}),
        make_text_response("Fusion combines light atomic nuclei.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("search results here", [])):
        result, sources = orchestrator.research_question("What is nuclear fusion?")
    assert result == "Fusion combines light atomic nuclei."
    assert mock_llm.chat.call_count == 2


def test_research_question_executes_tool_with_correct_args(orchestrator, mock_llm):
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion energy 2026"}),
        make_text_response("Here are the findings.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("results", [])) as mock_execute:
        orchestrator.research_question("What is the state of fusion in 2026?")
    mock_execute.assert_called_once_with("web_search", {"query": "fusion energy 2026"})


def test_research_question_respects_max_iterations(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_tool_response("web_search", {"query": "fusion"})
    with patch("agent.orchestrator.execute_tool_with_sources", return_value=("results", [])):
        result, sources = orchestrator.research_question("What is fusion?")
    assert "max iterations" in result.lower()
    assert mock_llm.chat.call_count == 5


def test_research_question_appends_tool_results_to_history(orchestrator, mock_llm):
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion"}),
        make_text_response("Answer.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("specific tool output here", [])):
        orchestrator.research_question("What is fusion?")
    second_call_messages = mock_llm.chat.call_args_list[1][1]["messages"]
    message_contents = [m["content"] for m in second_call_messages]
    assert any("specific tool output here" in c for c in message_contents)


def test_research_question_message_history_has_original_question(orchestrator, mock_llm):
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion energy"}),
        make_text_response("Fusion combines nuclei.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("search results", [])):
        orchestrator.research_question("What is nuclear fusion?")
    second_call_messages = mock_llm.chat.call_args_list[1][1]["messages"]
    message_contents = " ".join(m["content"] for m in second_call_messages)
    assert "What is nuclear fusion?" in message_contents


def test_research_question_detects_tool_call_string_and_retries(orchestrator, mock_llm):
    """Regression test for Q3 bug — tool call string returned as text."""
    mock_llm.chat.side_effect = [
        LLMResponse(type="text", content="[Calling web_search with {'query': 'fusion'}]"),
        LLMResponse(type="text", content="Fusion is the process of combining atomic nuclei.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources", return_value=("results", [])):
        result, sources = orchestrator.research_question("What is fusion?")
    assert result == "Fusion is the process of combining atomic nuclei."
    assert mock_llm.chat.call_count == 2


def test_research_question_tool_result_included_in_history(orchestrator, mock_llm):
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion"}),
        make_text_response("Answer.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("specific tool output here", [])):
        orchestrator.research_question("What is fusion?")
    second_call_messages = mock_llm.chat.call_args_list[1][1]["messages"]
    message_contents = " ".join(m["content"] for m in second_call_messages)
    assert "specific tool output here" in message_contents


def test_research_question_uses_config_max_tokens(orchestrator, mock_llm, config):
    config.max_tokens_research = 1024
    mock_llm.chat.return_value = make_text_response("Answer.")
    with patch("agent.orchestrator.execute_tool_with_sources", return_value=("results", [])):
        orchestrator.research_question("What is fusion?")
    assert mock_llm.chat.call_args[1]["max_tokens"] == 1024


def test_research_question_deduplicates_sources(orchestrator, mock_llm):
    """Duplicate URLs should appear only once in returned sources."""
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion"}),
        make_tool_response("web_search", {"query": "fusion energy"}),
        make_text_response("Answer.")
    ]
    duplicate_sources = [{"title": "Same Page", "url": "https://example.com"}]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("results", duplicate_sources)):
        result, sources = orchestrator.research_question("What is fusion?")
    urls = [s["url"] for s in sources]
    assert urls.count("https://example.com") == 1


def test_research_question_respects_max_iterations(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_tool_response("web_search", {"query": "fusion"})
    with patch("agent.orchestrator.execute_tool_with_sources", return_value=("results", [])):
        result, sources = orchestrator.research_question("What is fusion?")
    assert "unable to retrieve" in result.lower()
    assert mock_llm.chat.call_count >= 5

def test_research_question_handles_repeated_query(orchestrator, mock_llm):
    """Repeated identical queries should trigger synthesis prompt not another search."""
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion energy"}),
        make_tool_response("web_search", {"query": "fusion energy"}),  # repeat
        make_text_response("Fusion combines nuclei releasing energy.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("search results", [])):
        result, sources = orchestrator.research_question("What is fusion?")
    assert result == "Fusion combines nuclei releasing energy."
    assert mock_llm.chat.call_count == 3


def test_research_question_does_not_call_tool_on_repeated_query(orchestrator, mock_llm):
    """Tool executor should not be called for a repeated query."""
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion energy"}),
        make_tool_response("web_search", {"query": "fusion energy"}),  # repeat
        make_text_response("Answer.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("search results", [])) as mock_execute:
        orchestrator.research_question("What is fusion?")
    assert mock_execute.call_count == 1


def test_research_question_allows_different_queries(orchestrator, mock_llm):
    """Different queries should each trigger a real search."""
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion basics"}),
        make_tool_response("web_search", {"query": "fusion challenges"}),
        make_text_response("Answer.")
    ]
    with patch("agent.orchestrator.execute_tool_with_sources",
               return_value=("results", [])) as mock_execute:
        orchestrator.research_question("What is fusion?")
    assert mock_execute.call_count == 2


# ── reflect() tests ───────────────────────────────────────────────────────────

def test_reflect_returns_sufficient_true(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response('{"sufficient": true, "missing": []}')
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is True
    assert missing == []


def test_reflect_returns_sufficient_false_with_gaps(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response(
        '{"sufficient": false, "missing": ["commercial viability", "development timeline"]}'
    )
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is False
    assert "commercial viability" in missing
    assert "development timeline" in missing


def test_reflect_invalid_json_defaults_to_sufficient(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response("not valid json")
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is True
    assert missing == []


def test_reflect_uses_config_max_tokens(orchestrator, mock_llm, config):
    config.max_tokens_research = 512
    mock_llm.chat.return_value = make_text_response('{"sufficient": true, "missing": []}')
    orchestrator.reflect("fusion", {"Q1": "A1"})
    assert mock_llm.chat.call_args[1]["max_tokens"] == 512


def test_reflect_includes_topic_in_prompt(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response('{"sufficient": true, "missing": []}')
    orchestrator.reflect("nuclear fusion", {"Q1": "A1"})
    call_content = mock_llm.chat.call_args[1]["messages"][0]["content"]
    assert "nuclear fusion" in call_content


def test_reflect_includes_findings_in_prompt(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response('{"sufficient": true, "missing": []}')
    orchestrator.reflect("fusion", {"What is fusion?": "Fusion combines nuclei."})
    call_content = mock_llm.chat.call_args[1]["messages"][0]["content"]
    assert "What is fusion?" in call_content


def test_reflect_handles_markdown_fenced_json(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response(
        '```json\n{"sufficient": true, "missing": []}\n```'
    )
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is True


def test_reflect_prompt_includes_full_findings(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response('{"sufficient": true, "missing": []}')
    results = {"What is fusion?": "A" * 400}
    orchestrator.reflect("fusion", results)
    call_content = mock_llm.chat.call_args[1]["messages"][0]["content"]
    assert "A" * 300 in call_content


def test_reflect_returns_all_gaps_without_filtering(orchestrator, mock_llm):
    """All gaps returned regardless of length."""
    mock_llm.chat.return_value = make_text_response(
        '{"sufficient": false, "missing": ["timeline", "cost", "commercial viability and investment landscape"]}'
    )
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is False
    assert "timeline" in missing
    assert "cost" in missing
    assert "commercial viability and investment landscape" in missing


# ── run() tests ───────────────────────────────────────────────────────────────

def test_run_returns_dict_of_results(orchestrator, mock_llm):
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
    assert mock_llm.chat.call_count == 6


def test_run_uses_config_question_bounds(orchestrator, mock_llm, config):
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


# ── Integration tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
def test_real_orchestrator_run():
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