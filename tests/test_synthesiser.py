import pytest
from unittest.mock import MagicMock
from agent.synthesiser import Synthesiser
from llm.base import LLMResponse


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.fixture
def synthesiser(mock_llm):
    return Synthesiser(llm=mock_llm)


@pytest.fixture
def sample_results():
    return {
        "What is nuclear fusion?": "Nuclear fusion is the process of combining light atomic nuclei to release energy.",
        "What are the challenges?": "Key challenges include plasma confinement, materials science, and energy economics.",
        "Who is leading development?": "ITER, Commonwealth Fusion Systems, and Helion Energy are leading efforts."
    }


# ── synthesise() tests ────────────────────────────────────────────────────────

def test_synthesise_returns_string(synthesiser, mock_llm, sample_results):
    mock_llm.chat.return_value = LLMResponse(type="text", content="# Report\n\nSome content.")
    result = synthesiser.synthesise("nuclear fusion", sample_results)
    assert isinstance(result, str)
    assert len(result) > 0


def test_synthesise_calls_llm_once(synthesiser, mock_llm, sample_results):
    mock_llm.chat.return_value = LLMResponse(type="text", content="# Report")
    synthesiser.synthesise("nuclear fusion", sample_results)
    assert mock_llm.chat.call_count == 1


def test_synthesise_includes_topic_in_prompt(synthesiser, mock_llm, sample_results):
    mock_llm.chat.return_value = LLMResponse(type="text", content="# Report")
    synthesiser.synthesise("nuclear fusion", sample_results)
    call_messages = mock_llm.chat.call_args[1]["messages"]
    prompt_content = call_messages[0]["content"]
    assert "nuclear fusion" in prompt_content


def test_synthesise_includes_all_findings_in_prompt(synthesiser, mock_llm, sample_results):
    mock_llm.chat.return_value = LLMResponse(type="text", content="# Report")
    synthesiser.synthesise("nuclear fusion", sample_results)
    call_messages = mock_llm.chat.call_args[1]["messages"]
    prompt_content = call_messages[0]["content"]
    for question in sample_results.keys():
        assert question in prompt_content


def test_synthesise_returns_llm_content(synthesiser, mock_llm, sample_results):
    expected = "# Nuclear Fusion Report\n\n## Executive Summary\n\nFusion is promising."
    mock_llm.chat.return_value = LLMResponse(type="text", content=expected)
    result = synthesiser.synthesise("nuclear fusion", sample_results)
    assert result == expected


# ── _format_findings() tests ──────────────────────────────────────────────────

def test_format_findings_includes_all_questions(synthesiser, sample_results):
    formatted = synthesiser._format_findings(sample_results)
    for question in sample_results.keys():
        assert question in formatted


def test_format_findings_includes_all_answers(synthesiser, sample_results):
    formatted = synthesiser._format_findings(sample_results)
    for answer in sample_results.values():
        assert answer in formatted


def test_format_findings_numbers_sections(synthesiser, sample_results):
    formatted = synthesiser._format_findings(sample_results)
    assert "Finding 1" in formatted
    assert "Finding 2" in formatted
    assert "Finding 3" in formatted


def test_format_findings_empty_results(synthesiser):
    formatted = synthesiser._format_findings({})
    assert formatted == ""


# ── Integration tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
def test_real_synthesise():
    from llm import AnthropicClient
    from dotenv import load_dotenv
    load_dotenv()

    llm = AnthropicClient()
    synthesiser = Synthesiser(llm=llm)

    results = {
        "What is nuclear fusion?": "Nuclear fusion combines light nuclei releasing enormous energy. The sun runs on fusion.",
        "What are the challenges?": "Plasma must reach 100 million degrees. Confinement via magnetic fields is difficult.",
        "Who is leading development?": "ITER is the main international project. Commonwealth Fusion Systems aims for 2030s."
    }

    report = synthesiser.synthesise("nuclear fusion energy", results)

    assert isinstance(report, str)
    assert len(report) > 500
    assert "#" in report  # confirms markdown structure
    