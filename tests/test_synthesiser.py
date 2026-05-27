"""
Tests for agent/synthesiser.py — Synthesiser.

Verifies:
    - synthesise(): LLM is called once, topic and all findings appear in the
      prompt, max_tokens respected, short mode uses lower limit, References
      section appended for full mode only.
    - _format_findings(): all questions/answers present, numbered sections,
      inline source blocks included when sources provided.
    - _format_master_references(): deduplicated numbered reference list with
      URLs and titles, empty when no sources, proper heading.

All tests use a mock LLM; integration tests (marked) make live API calls.
"""

import pytest
from unittest.mock import MagicMock
from agent.synthesiser import Synthesiser
from llm.base import LLMResponse
from config import Config


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_llm():
    """Mock LLM client for synthesiser tests."""
    return MagicMock()


@pytest.fixture
def config():
    """Standard Config for synthesiser tests."""
    return Config(
        max_tokens_research=2048,
        max_tokens_synthesis=8192
    )


@pytest.fixture
def synthesiser(mock_llm, config):
    """Synthesiser wired to a mock LLM and test config."""
    return Synthesiser(llm=mock_llm, config=config)


@pytest.fixture
def sample_results():
    """Realistic three-question results dict for use across multiple tests."""
    return {
        "What is nuclear fusion?": "Nuclear fusion is the process of combining light atomic nuclei to release energy.",
        "What are the challenges?": "Key challenges include plasma confinement, materials science, and energy economics.",
        "Who is leading development?": "ITER, Commonwealth Fusion Systems, and Helion Energy are leading efforts."
    }


@pytest.fixture
def sample_sources():
    """Corresponding sources for sample_results."""
    return {
        "What is nuclear fusion?": [
            {"title": "Fusion Energy Explained", "url": "https://example.com/fusion"},
            {"title": "Nuclear Physics Today", "url": "https://example.com/nuclear"}
        ],
        "What are the challenges?": [
            {"title": "Fusion Challenges Report", "url": "https://example.com/challenges"}
        ],
        "Who is leading development?": [
            {"title": "ITER Project", "url": "https://iter.org"},
        ]
    }


# ── synthesise() tests ────────────────────────────────────────────────────────
# Verify LLM call count, prompt construction, token limits, and output shape.

def test_synthesise_returns_string(synthesiser, mock_llm, sample_results):
    """synthesise() returns a non-empty string."""
    mock_llm.chat.return_value = LLMResponse(type="text", content="# Report\n\nSome content.")
    result = synthesiser.synthesise("nuclear fusion", sample_results)
    assert isinstance(result, str)
    assert len(result) > 0


def test_synthesise_calls_llm_once(synthesiser, mock_llm, sample_results):
    """Exactly one LLM call is made per synthesise() invocation."""
    mock_llm.chat.return_value = LLMResponse(type="text", content="# Report")
    synthesiser.synthesise("nuclear fusion", sample_results)
    assert mock_llm.chat.call_count == 1


def test_synthesise_includes_topic_in_prompt(synthesiser, mock_llm, sample_results):
    """The topic string appears in the prompt sent to the LLM."""
    mock_llm.chat.return_value = LLMResponse(type="text", content="# Report")
    synthesiser.synthesise("nuclear fusion", sample_results)
    call_messages = mock_llm.chat.call_args[1]["messages"]
    prompt_content = call_messages[0]["content"]
    assert "nuclear fusion" in prompt_content


def test_synthesise_includes_all_findings_in_prompt(synthesiser, mock_llm, sample_results):
    """All question strings from the results dict appear in the prompt."""
    mock_llm.chat.return_value = LLMResponse(type="text", content="# Report")
    synthesiser.synthesise("nuclear fusion", sample_results)
    call_messages = mock_llm.chat.call_args[1]["messages"]
    prompt_content = call_messages[0]["content"]
    for question in sample_results.keys():
        assert question in prompt_content


def test_synthesise_returns_llm_content(synthesiser, mock_llm, sample_results):
    """The LLM's content string is present in the returned report."""
    expected = "# Nuclear Fusion Report\n\n## Executive Summary\n\nFusion is promising."
    mock_llm.chat.return_value = LLMResponse(type="text", content=expected)
    result = synthesiser.synthesise("nuclear fusion", sample_results)
    assert expected in result


def test_synthesise_uses_config_max_tokens(synthesiser, mock_llm, sample_results, config):
    """max_tokens passed to LLM matches config.max_tokens_synthesis."""
    config.max_tokens_synthesis = 4096
    mock_llm.chat.return_value = LLMResponse(type="text", content="# Report")
    synthesiser.synthesise("nuclear fusion", sample_results)
    assert mock_llm.chat.call_args[1]["max_tokens"] == 4096


def test_synthesise_max_tokens_override(synthesiser, mock_llm, sample_results):
    """Explicit max_tokens argument overrides config value."""
    mock_llm.chat.return_value = LLMResponse(type="text", content="# Report")
    synthesiser.synthesise("nuclear fusion", sample_results, max_tokens=1024)
    assert mock_llm.chat.call_args[1]["max_tokens"] == 1024


def test_synthesise_without_sources_still_works(synthesiser, mock_llm, sample_results):
    """synthesise() works when sources argument is omitted entirely."""
    mock_llm.chat.return_value = LLMResponse(type="text", content="# Report")
    result = synthesiser.synthesise("nuclear fusion", sample_results)
    assert isinstance(result, str)


def test_synthesise_with_empty_sources_no_references(synthesiser, mock_llm, sample_results):
    """An empty sources dict produces no References section."""
    mock_llm.chat.return_value = LLMResponse(type="text", content="# Report")
    result = synthesiser.synthesise("nuclear fusion", sample_results, sources={})
    assert "References" not in result


def test_synthesise_includes_references_when_sources_provided(synthesiser, mock_llm,
                                                               sample_results, sample_sources):
    """Non-empty sources dict causes a References section to be appended."""
    mock_llm.chat.return_value = LLMResponse(type="text", content="# Report\n\nContent.")
    result = synthesiser.synthesise("nuclear fusion", sample_results, sources=sample_sources)
    assert "References" in result


def test_synthesise_references_contain_urls(synthesiser, mock_llm,
                                            sample_results, sample_sources):
    """Source URLs appear in the appended References section."""
    mock_llm.chat.return_value = LLMResponse(type="text", content="# Report")
    result = synthesiser.synthesise("nuclear fusion", sample_results, sources=sample_sources)
    assert "https://example.com/fusion" in result
    assert "https://iter.org" in result


def test_synthesise_references_are_deduplicated(synthesiser, mock_llm, sample_results):
    """The same URL appearing in multiple questions appears only once in References."""
    mock_llm.chat.return_value = LLMResponse(type="text", content="# Report")
    sources_with_duplicates = {
        "What is nuclear fusion?": [
            {"title": "Same Page", "url": "https://example.com/same"}
        ],
        "What are the challenges?": [
            {"title": "Same Page Again", "url": "https://example.com/same"}
        ]
    }
    result = synthesiser.synthesise("nuclear fusion", sample_results,
                                    sources=sources_with_duplicates)
    assert result.count("https://example.com/same") == 1


def test_synthesise_none_sources_no_references(synthesiser, mock_llm, sample_results):
    """sources=None produces no References section."""
    mock_llm.chat.return_value = LLMResponse(type="text", content="# Report")
    result = synthesiser.synthesise("nuclear fusion", sample_results, sources=None)
    assert "References" not in result


# ── short mode tests ──────────────────────────────────────────────────────────
# Verify executive-summary mode: lower token limit, no References appended.

def test_synthesise_short_mode_returns_string(synthesiser, mock_llm, sample_results):
    """Short mode returns a non-empty string."""
    mock_llm.chat.return_value = LLMResponse(type="text", content="## Summary\n\nBrief overview.")
    result = synthesiser.synthesise("nuclear fusion", sample_results, short=True)
    assert isinstance(result, str)
    assert len(result) > 0


def test_synthesise_short_mode_no_references(synthesiser, mock_llm,
                                              sample_results, sample_sources):
    """Short mode never appends a References section even when sources are provided."""
    mock_llm.chat.return_value = LLMResponse(type="text", content="## Summary")
    result = synthesiser.synthesise("nuclear fusion", sample_results,
                                    sources=sample_sources, short=True)
    assert "References" not in result


def test_synthesise_short_mode_uses_lower_token_limit(synthesiser, mock_llm,
                                                       sample_results, config):
    """Short mode caps max_tokens at 2048 regardless of config.max_tokens_synthesis."""
    config.max_tokens_synthesis = 8192
    mock_llm.chat.return_value = LLMResponse(type="text", content="## Summary")
    synthesiser.synthesise("nuclear fusion", sample_results, short=True)
    assert mock_llm.chat.call_args[1]["max_tokens"] <= 2048


def test_synthesise_default_is_not_short(synthesiser, mock_llm, sample_results, config):
    """Default (short=False) uses the full config.max_tokens_synthesis."""
    config.max_tokens_synthesis = 8192
    mock_llm.chat.return_value = LLMResponse(type="text", content="# Report")
    synthesiser.synthesise("nuclear fusion", sample_results)
    assert mock_llm.chat.call_args[1]["max_tokens"] == 8192


# ── _format_findings() tests ──────────────────────────────────────────────────
# Verify prompt formatting: all content present, numbered sections, source blocks.

def test_format_findings_includes_all_questions(synthesiser, sample_results):
    """All question strings appear in the formatted output."""
    formatted = synthesiser._format_findings(sample_results, {})
    for question in sample_results.keys():
        assert question in formatted


def test_format_findings_includes_all_answers(synthesiser, sample_results):
    """All answer strings appear in the formatted output."""
    formatted = synthesiser._format_findings(sample_results, {})
    for answer in sample_results.values():
        assert answer in formatted


def test_format_findings_numbers_sections(synthesiser, sample_results):
    """Sections are numbered Finding 1, Finding 2, Finding 3."""
    formatted = synthesiser._format_findings(sample_results, {})
    assert "Finding 1" in formatted
    assert "Finding 2" in formatted
    assert "Finding 3" in formatted


def test_format_findings_empty_results(synthesiser):
    """Empty results dict produces an empty string."""
    formatted = synthesiser._format_findings({}, {})
    assert formatted == ""


def test_format_findings_includes_source_urls(synthesiser, sample_results, sample_sources):
    """Source URLs appear in the inline Sources block for each finding."""
    formatted = synthesiser._format_findings(sample_results, sample_sources)
    assert "https://example.com/fusion" in formatted
    assert "https://example.com/challenges" in formatted


def test_format_findings_includes_source_titles(synthesiser, sample_results, sample_sources):
    """Source titles appear in the inline Sources block."""
    formatted = synthesiser._format_findings(sample_results, sample_sources)
    assert "Fusion Energy Explained" in formatted
    assert "ITER Project" in formatted


def test_format_findings_no_sources_section_when_empty(synthesiser, sample_results):
    """No 'Sources:' heading appears when the sources dict has no entries for a question."""
    formatted = synthesiser._format_findings(sample_results, {})
    assert "Sources:" not in formatted


def test_format_findings_sources_section_present_when_provided(synthesiser,
                                                                sample_results, sample_sources):
    """'Sources:' heading appears when sources are provided for at least one question."""
    formatted = synthesiser._format_findings(sample_results, sample_sources)
    assert "Sources:" in formatted


# ── _format_master_references() tests ────────────────────────────────────────
# Verify the deduplicated numbered References section.

def test_format_master_references_returns_empty_when_no_sources(synthesiser):
    """Empty sources dict returns an empty string."""
    result = synthesiser._format_master_references({})
    assert result == ""


def test_format_master_references_returns_empty_when_all_empty(synthesiser):
    """Sources dict with all-empty lists returns an empty string."""
    result = synthesiser._format_master_references({"Q1": [], "Q2": []})
    assert result == ""


def test_format_master_references_includes_all_urls(synthesiser, sample_sources):
    """All source URLs from all questions appear in the References section."""
    result = synthesiser._format_master_references(sample_sources)
    assert "https://example.com/fusion" in result
    assert "https://example.com/nuclear" in result
    assert "https://example.com/challenges" in result
    assert "https://iter.org" in result


def test_format_master_references_deduplicates_urls(synthesiser):
    """The same URL shared across two questions appears only once."""
    sources = {
        "Q1": [{"title": "Page A", "url": "https://example.com/a"}],
        "Q2": [{"title": "Page A Again", "url": "https://example.com/a"}],
    }
    result = synthesiser._format_master_references(sources)
    assert result.count("https://example.com/a") == 1


def test_format_master_references_includes_titles(synthesiser, sample_sources):
    """Source titles appear in the References section."""
    result = synthesiser._format_master_references(sample_sources)
    assert "Fusion Energy Explained" in result
    assert "ITER Project" in result


def test_format_master_references_is_numbered(synthesiser, sample_sources):
    """References are numbered starting from 1."""
    result = synthesiser._format_master_references(sample_sources)
    assert "1." in result
    assert "2." in result


def test_format_master_references_has_heading(synthesiser, sample_sources):
    """The section has a '## References' heading."""
    result = synthesiser._format_master_references(sample_sources)
    assert "## References" in result


# ── _build_synthesis_prompt() tests ──────────────────────────────────────────

def test_build_synthesis_prompt_returns_string(synthesiser):
    """_build_synthesis_prompt() returns a string."""
    result = synthesiser._build_synthesis_prompt("nuclear fusion", "some findings")
    assert isinstance(result, str)


def test_build_synthesis_prompt_contains_topic(synthesiser):
    """_build_synthesis_prompt() includes the topic in the returned prompt."""
    result = synthesiser._build_synthesis_prompt("nuclear fusion", "some findings")
    assert "nuclear fusion" in result


def test_build_synthesis_prompt_full_uses_full_template(synthesiser):
    """short=False uses the full SYNTHESISE_PROMPT template."""
    from agent.synthesiser import SYNTHESISE_PROMPT
    result = synthesiser._build_synthesis_prompt("topic", "findings", short=False)
    assert SYNTHESISE_PROMPT[:40] in result


def test_build_synthesis_prompt_short_uses_short_template(synthesiser):
    """short=True uses the SHORT_SYNTHESISE_PROMPT template."""
    from agent.synthesiser import SHORT_SYNTHESISE_PROMPT
    result = synthesiser._build_synthesis_prompt("topic", "findings", short=True)
    assert SHORT_SYNTHESISE_PROMPT[:40] in result


def test_build_synthesis_prompt_contains_findings(synthesiser):
    """_build_synthesis_prompt() includes the findings text."""
    result = synthesiser._build_synthesis_prompt("topic", "my specific findings text")
    assert "my specific findings text" in result


# ── Integration tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
def test_real_synthesise():
    """Live synthesis call produces a markdown report with References."""
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
    sources = {
        "What is nuclear fusion?": [
            {"title": "Fusion Basics", "url": "https://example.com/fusion"}
        ],
        "What are the challenges?": [],
        "Who is leading development?": [
            {"title": "ITER Official", "url": "https://iter.org"}
        ]
    }

    report = synthesiser.synthesise("nuclear fusion energy", results, sources=sources)

    assert isinstance(report, str)
    assert len(report) > 500
    assert "#" in report
    assert "References" in report


@pytest.mark.integration
def test_real_synthesise_short_mode():
    """Live short-mode synthesis returns a brief report without References."""
    from llm import AnthropicClient
    from dotenv import load_dotenv
    load_dotenv()

    llm = AnthropicClient()
    synthesiser = Synthesiser(llm=llm)

    results = {
        "What is nuclear fusion?": "Nuclear fusion combines light nuclei releasing enormous energy.",
        "What are the challenges?": "Plasma confinement and materials science are key challenges.",
    }

    report = synthesiser.synthesise("nuclear fusion energy", results, short=True)

    assert isinstance(report, str)
    assert len(report) > 100
    assert "References" not in report
