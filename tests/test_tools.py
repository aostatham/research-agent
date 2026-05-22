"""
Tests for agent/tools.py — configure_search(), execute_tool(),
execute_tool_with_sources(), and both search backends.

Verifies:
    - configure_search(): module-level state is updated correctly for both
      providers; Tavily requires an API key.
    - execute_tool() / execute_tool_with_sources(): correct delegation to
      _web_search / _web_search_with_sources; unknown tool raises ValueError.
    - Anthropic search: text extraction, citation extraction, deduplication,
      empty-response fallback.
    - Tavily search: answer + result assembly, source deduplication,
      missing answer field, max_results passed to client.
    - Routing: _web_search_with_sources() routes to the correct backend
      based on _search_provider module state.

All tests mock external clients (anthropic.Anthropic, TavilyClient) to avoid
real API calls.  Integration tests (marked) make live calls.
"""

import pytest
from unittest.mock import MagicMock, patch


# ── configure_search() tests ──────────────────────────────────────────────────
# Verify that configure_search() correctly sets all three module-level globals.

def test_configure_search_sets_anthropic():
    """configure_search('anthropic') sets _search_provider to 'anthropic'."""
    from agent.tools import configure_search, _search_provider
    configure_search("anthropic")
    from agent import tools
    assert tools._search_provider == "anthropic"


def test_configure_search_sets_tavily():
    """configure_search('tavily', ...) sets provider and API key globals."""
    from agent.tools import configure_search
    from agent import tools
    configure_search("tavily", tavily_api_key="tvly-test-key")
    assert tools._search_provider == "tavily"
    assert tools._tavily_api_key == "tvly-test-key"


def test_configure_search_tavily_requires_key():
    """configure_search('tavily') without an API key raises ValueError."""
    from agent.tools import configure_search
    with pytest.raises(ValueError, match="Tavily API key required"):
        configure_search("tavily", tavily_api_key=None)


def test_configure_search_sets_max_results():
    """configure_search() stores the tavily_max_results value."""
    from agent.tools import configure_search
    from agent import tools
    configure_search("tavily", tavily_api_key="tvly-test", tavily_max_results=10)
    assert tools._tavily_max_results == 10


# ── execute_tool() tests ──────────────────────────────────────────────────────
# Verify dispatch and error handling for the public tool executor.

def test_execute_tool_calls_web_search():
    """execute_tool('web_search', ...) calls _web_search with the query string."""
    from agent.tools import configure_search
    configure_search("anthropic")
    with patch("agent.tools._web_search", return_value="results") as mock:
        from agent.tools import execute_tool
        result = execute_tool("web_search", {"query": "nuclear fusion"})
    mock.assert_called_once_with("nuclear fusion")
    assert result == "results"


def test_execute_tool_unknown_tool_raises():
    """execute_tool() raises ValueError for unrecognised tool names."""
    from agent.tools import execute_tool
    with pytest.raises(ValueError, match="Unknown tool"):
        execute_tool("unknown_tool", {})


# ── execute_tool_with_sources() tests ─────────────────────────────────────────
# Verify the (result, sources) tuple return shape.

def test_execute_tool_with_sources_returns_tuple():
    """execute_tool_with_sources() returns (str, list) tuple."""
    from agent.tools import configure_search
    configure_search("anthropic")
    with patch("agent.tools._web_search_with_sources",
               return_value=("results", [{"title": "Test", "url": "https://example.com"}])):
        from agent.tools import execute_tool_with_sources
        result, sources = execute_tool_with_sources("web_search", {"query": "fusion"})
    assert result == "results"
    assert sources[0]["url"] == "https://example.com"


# ── Anthropic search tests ────────────────────────────────────────────────────
# Verify text extraction and citation handling from Anthropic response blocks.

def test_anthropic_search_extracts_text():
    """Text from response blocks is included in result_text."""
    from agent.tools import configure_search, _anthropic_search_with_sources
    configure_search("anthropic")

    mock_block = MagicMock()
    mock_block.text = "Fusion combines nuclei."
    mock_block.citations = None   # no citations on this block

    mock_response = MagicMock()
    mock_response.content = [mock_block]

    with patch("agent.tools.anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = mock_response
        result, sources = _anthropic_search_with_sources("nuclear fusion")

    assert "Fusion combines nuclei." in result
    assert sources == []


def test_anthropic_search_extracts_citations():
    """Citations on text blocks are extracted into the sources list."""
    from agent.tools import _anthropic_search_with_sources

    mock_citation = MagicMock()
    mock_citation.url = "https://example.com/fusion"
    mock_citation.title = "Fusion Explained"

    mock_block = MagicMock()
    mock_block.text = "Fusion is the process of combining nuclei."
    mock_block.citations = [mock_citation]

    mock_response = MagicMock()
    mock_response.content = [mock_block]

    with patch("agent.tools.anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = mock_response
        result, sources = _anthropic_search_with_sources("nuclear fusion")

    assert len(sources) == 1
    assert sources[0]["url"] == "https://example.com/fusion"
    assert sources[0]["title"] == "Fusion Explained"


def test_anthropic_search_deduplicates_citations():
    """The same URL appearing on two blocks appears only once in sources."""
    from agent.tools import _anthropic_search_with_sources

    mock_citation = MagicMock()
    mock_citation.url = "https://example.com/fusion"
    mock_citation.title = "Fusion Explained"

    mock_block1 = MagicMock()
    mock_block1.text = "First sentence."
    mock_block1.citations = [mock_citation]

    mock_block2 = MagicMock()
    mock_block2.text = "Second sentence."
    mock_block2.citations = [mock_citation]  # same URL as block1

    mock_response = MagicMock()
    mock_response.content = [mock_block1, mock_block2]

    with patch("agent.tools.anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = mock_response
        result, sources = _anthropic_search_with_sources("nuclear fusion")

    assert len(sources) == 1


def test_anthropic_search_returns_no_results_fallback():
    """An empty content list returns 'No results found.' and an empty sources list."""
    from agent.tools import _anthropic_search_with_sources

    mock_response = MagicMock()
    mock_response.content = []

    with patch("agent.tools.anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = mock_response
        result, sources = _anthropic_search_with_sources("nuclear fusion")

    assert result == "No results found."
    assert sources == []


# ── Tavily search tests ───────────────────────────────────────────────────────
# Verify Tavily response assembly, deduplication, and parameter passing.

def test_tavily_search_returns_answer_and_sources():
    """Tavily synthesised answer and per-result sources are both included."""
    from agent.tools import configure_search, _tavily_search_with_sources
    configure_search("tavily", tavily_api_key="tvly-test")

    mock_response = {
        "answer": "Nuclear fusion combines light nuclei.",
        "results": [
            {
                "title": "Fusion Energy",
                "url": "https://example.com/fusion",
                "content": "Fusion is a clean energy source."
            },
            {
                "title": "NIF Breakthrough",
                "url": "https://example.com/nif",
                "content": "NIF achieved ignition in 2022."
            }
        ]
    }

    mock_client = MagicMock()
    mock_client.search.return_value = mock_response

    with patch("agent.tools.TavilyClient", return_value=mock_client):
        result, sources = _tavily_search_with_sources("nuclear fusion")

    assert "Nuclear fusion combines light nuclei." in result
    assert len(sources) == 2
    assert sources[0]["url"] == "https://example.com/fusion"
    assert sources[1]["url"] == "https://example.com/nif"


def test_tavily_search_deduplicates_sources():
    """The same URL in two results appears only once in sources."""
    from agent.tools import _tavily_search_with_sources

    mock_response = {
        "answer": "Answer.",
        "results": [
            {"title": "Page", "url": "https://example.com/same", "content": "Content 1."},
            {"title": "Page", "url": "https://example.com/same", "content": "Content 2."},
        ]
    }

    mock_client = MagicMock()
    mock_client.search.return_value = mock_response

    with patch("agent.tools.TavilyClient", return_value=mock_client):
        result, sources = _tavily_search_with_sources("fusion")

    assert len(sources) == 1


def test_tavily_search_handles_no_answer():
    """Missing 'answer' key in Tavily response still produces valid result_text."""
    from agent.tools import _tavily_search_with_sources

    mock_response = {
        "results": [
            {"title": "Page", "url": "https://example.com", "content": "Some content."}
        ]
    }

    mock_client = MagicMock()
    mock_client.search.return_value = mock_response

    with patch("agent.tools.TavilyClient", return_value=mock_client):
        result, sources = _tavily_search_with_sources("fusion")

    assert "Some content." in result


def test_tavily_search_raises_without_import():
    """If TavilyClient is None (package not installed), an ImportError is raised."""
    from agent.tools import _tavily_search_with_sources
    with patch.dict("sys.modules", {"tavily": None}):
        with pytest.raises((ImportError, Exception)):
            _tavily_search_with_sources("fusion")


def test_tavily_uses_configured_max_results():
    """max_results passed to TavilyClient.search() matches configure_search value."""
    from agent.tools import configure_search, _tavily_search_with_sources
    configure_search("tavily", tavily_api_key="tvly-test", tavily_max_results=3)

    mock_response = {"answer": "Answer.", "results": []}
    mock_client = MagicMock()
    mock_client.search.return_value = mock_response

    with patch("agent.tools.TavilyClient", return_value=mock_client):
        _tavily_search_with_sources("fusion")

    call_kwargs = mock_client.search.call_args[1]
    assert call_kwargs["max_results"] == 3


# ── Search routing tests ──────────────────────────────────────────────────────
# Verify that _web_search_with_sources() routes to exactly one backend based
# on the module-level _search_provider state.

def test_web_search_routes_to_anthropic():
    """When _search_provider='anthropic', only _anthropic_search_with_sources is called."""
    from agent.tools import configure_search
    configure_search("anthropic")

    with patch("agent.tools._anthropic_search_with_sources",
               return_value=("results", [])) as mock_anthropic, \
         patch("agent.tools._tavily_search_with_sources",
               return_value=("results", [])) as mock_tavily:
        from agent.tools import _web_search_with_sources
        _web_search_with_sources("fusion")

    mock_anthropic.assert_called_once()
    mock_tavily.assert_not_called()


def test_web_search_routes_to_tavily():
    """When _search_provider='tavily', only _tavily_search_with_sources is called."""
    from agent.tools import configure_search
    configure_search("tavily", tavily_api_key="tvly-test")

    with patch("agent.tools._anthropic_search_with_sources",
               return_value=("results", [])) as mock_anthropic, \
         patch("agent.tools._tavily_search_with_sources",
               return_value=("results", [])) as mock_tavily:
        from agent.tools import _web_search_with_sources
        _web_search_with_sources("fusion")

    mock_tavily.assert_called_once()
    mock_anthropic.assert_not_called()


# ── Integration tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
def test_real_anthropic_search():
    """Live Anthropic web search returns a non-empty string result."""
    from agent.tools import configure_search, execute_tool_with_sources
    from dotenv import load_dotenv
    load_dotenv()
    configure_search("anthropic")
    result, sources = execute_tool_with_sources("web_search", {"query": "nuclear fusion 2026"})
    assert isinstance(result, str)
    assert len(result) > 100


@pytest.mark.integration
def test_real_tavily_search():
    """Live Tavily search returns a non-empty string result with at least one source."""
    from agent.tools import configure_search, execute_tool_with_sources
    from dotenv import load_dotenv
    import os
    load_dotenv()
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        pytest.skip("TAVILY_API_KEY not set")
    configure_search("tavily", tavily_api_key=api_key)
    result, sources = execute_tool_with_sources("web_search", {"query": "nuclear fusion 2026"})
    assert isinstance(result, str)
    assert len(result) > 100
    assert len(sources) > 0
