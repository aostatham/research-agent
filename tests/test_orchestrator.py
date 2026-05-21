import pytest
from unittest.mock import MagicMock, patch
from agent.orchestrator import Orchestrator
from llm.base import LLMResponse


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.fixture
def orchestrator(mock_llm):
    return Orchestrator(llm=mock_llm)


def make_text_response(content):
    return LLMResponse(type="text", content=content)


def make_tool_response(tool_name, tool_input):
    return LLMResponse(type="tool_call", tool_name=tool_name, tool_input=tool_input)


# ── decompose() tests ─────────────────────────────────────────────────────────

def test_decompose_returns_list_of_questions(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response(
        '["What is fusion?", "How does fusion work?", "What are fusion challenges?"]'
    )
    questions = orchestrator.decompose("nuclear fusion")
    assert isinstance(questions, list)
    assert len(questions) == 3
    assert all(isinstance(q, str) for q in questions)


def test_decompose_invalid_json_returns_fallback(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response("not valid json at all")
    questions = orchestrator.decompose("nuclear fusion")
    assert isinstance(questions, list)
    assert len(questions) > 0


def test_decompose_calls_llm_once(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response('["Q1?", "Q2?", "Q3?"]')
    orchestrator.decompose("nuclear fusion")
    assert mock_llm.chat.call_count == 1


# ── research_question() tests ─────────────────────────────────────────────────

def test_research_question_returns_text_directly(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response("Fusion is the process of combining atoms.")
    result = orchestrator.research_question("What is fusion?")
    assert result == "Fusion is the process of combining atoms."


def test_research_question_handles_tool_call_then_text(orchestrator, mock_llm):
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "what is nuclear fusion"}),
        make_text_response("Fusion combines light atomic nuclei.")
    ]

    with patch("agent.orchestrator.execute_tool", return_value="search results here"):
        result = orchestrator.research_question("What is nuclear fusion?")

    assert result == "Fusion combines light atomic nuclei."
    assert mock_llm.chat.call_count == 2


def test_research_question_executes_tool_with_correct_args(orchestrator, mock_llm):
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion energy 2026"}),
        make_text_response("Here are the findings.")
    ]

    with patch("agent.orchestrator.execute_tool", return_value="results") as mock_execute:
        orchestrator.research_question("What is the state of fusion in 2026?")

    mock_execute.assert_called_once_with("web_search", {"query": "fusion energy 2026"})


def test_research_question_respects_max_iterations(orchestrator, mock_llm):
    """Agent should stop after max iterations even if no text response."""
    mock_llm.chat.return_value = make_tool_response("web_search", {"query": "fusion"})

    with patch("agent.orchestrator.execute_tool", return_value="results"):
        result = orchestrator.research_question("What is fusion?")

    assert "max iterations" in result.lower()
    assert mock_llm.chat.call_count == 5


def test_research_question_appends_tool_results_to_history(orchestrator, mock_llm):
    mock_llm.chat.side_effect = [
        make_tool_response("web_search", {"query": "fusion"}),
        make_text_response("Answer.")
    ]

    with patch("agent.orchestrator.execute_tool", return_value="tool output"):
        orchestrator.research_question("What is fusion?")

    # Second call should include tool result in messages
    second_call_messages = mock_llm.chat.call_args_list[1][1]["messages"]
    message_contents = [m["content"] for m in second_call_messages]
    assert any("tool output" in c for c in message_contents)


# ── reflect() tests ───────────────────────────────────────────────────────────

def test_reflect_returns_sufficient_true(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response('{"sufficient": true, "missing": []}')
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is True
    assert missing == []


def test_reflect_returns_sufficient_false_with_gaps(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response(
        '{"sufficient": false, "missing": ["commercial viability", "timeline"]}'
    )
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is False
    assert "commercial viability" in missing
    assert "timeline" in missing


def test_reflect_invalid_json_defaults_to_sufficient(orchestrator, mock_llm):
    mock_llm.chat.return_value = make_text_response("not valid json")
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is True
    assert missing == []


# ── run() tests ───────────────────────────────────────────────────────────────

def test_run_returns_dict_of_results(orchestrator, mock_llm):
    mock_llm.chat.side_effect = [
        make_text_response('["What is fusion?", "How does fusion work?"]'),
        make_text_response("Fusion is combining atoms."),
        make_text_response("Fusion works via plasma confinement."),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]

    results = orchestrator.run("nuclear fusion")
    assert isinstance(results, dict)
    assert len(results) == 2


def test_run_researches_gaps_when_insufficient(orchestrator, mock_llm):
    mock_llm.chat.side_effect = [
        make_text_response('["What is fusion?"]'),
        make_text_response("Fusion is combining atoms."),
        make_text_response('{"sufficient": false, "missing": ["commercial timeline"]}'),
        make_text_response("Commercial fusion expected by 2035."),
    ]

    results = orchestrator.run("nuclear fusion")
    assert "commercial timeline" in results


def test_run_does_not_research_gaps_when_sufficient(orchestrator, mock_llm):
    mock_llm.chat.side_effect = [
        make_text_response('["What is fusion?"]'),
        make_text_response("Fusion is combining atoms."),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]

    results = orchestrator.run("nuclear fusion")
    assert mock_llm.chat.call_count == 3


# ── Integration tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
def test_real_orchestrator_run():
    from llm import AnthropicClient
    from dotenv import load_dotenv
    load_dotenv()

    llm = AnthropicClient()
    orchestrator = Orchestrator(llm=llm)
    results = orchestrator.run("the current state of nuclear fusion energy")

    assert isinstance(results, dict)
    assert len(results) >= 3
    for question, answer in results.items():
        assert isinstance(question, str)
        assert isinstance(answer, str)
        assert len(answer) > 100
        