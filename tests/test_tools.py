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


# ── Global state isolation ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_search_globals():
    """Snapshot and restore tools module globals after each test."""
    from agent import tools
    orig_provider = tools._search_provider
    orig_key = tools._tavily_api_key
    orig_max = tools._tavily_max_results
    orig_client = tools._anthropic_client
    orig_model = tools._search_model
    orig_staleness = tools._staleness_days
    yield
    tools._search_provider = orig_provider
    tools._tavily_api_key = orig_key
    tools._tavily_max_results = orig_max
    tools._anthropic_client = orig_client
    tools._search_model = orig_model
    tools._staleness_days = orig_staleness


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


def test_configure_search_stores_search_model():
    """configure_search() stores the search_model global correctly."""
    from agent.tools import configure_search
    from agent import tools
    configure_search("anthropic", search_model="claude-sonnet-4-6")
    assert tools._search_model == "claude-sonnet-4-6"


def test_configure_search_search_model_default():
    """configure_search() defaults search_model to Haiku when not specified."""
    from agent.tools import configure_search
    from agent import tools
    configure_search("anthropic")
    assert tools._search_model == "claude-haiku-4-5-20251001"


def test_anthropic_search_uses_configured_model():
    """_anthropic_search_with_sources() passes _search_model to the API, not a hardcoded string."""
    from agent.tools import configure_search, _anthropic_search_with_sources
    configure_search("anthropic", search_model="claude-sonnet-4-6")

    mock_response = MagicMock()
    mock_response.content = []
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("agent.tools._get_anthropic_client", return_value=mock_client):
        _anthropic_search_with_sources("test query")

    call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs["model"] == "claude-sonnet-4-6"


def test_anthropic_search_does_not_hardcode_model():
    """Changing the configured model changes what the API receives."""
    from agent.tools import configure_search, _anthropic_search_with_sources
    configure_search("anthropic", search_model="claude-haiku-4-5-20251001")

    mock_response = MagicMock()
    mock_response.content = []
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("agent.tools._get_anthropic_client", return_value=mock_client):
        _anthropic_search_with_sources("test query")

    call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs["model"] == "claude-haiku-4-5-20251001"


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
# Verify the (result, sources) tuple return shape and search counter.

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


def test_execute_tool_with_sources_increments_counter():
    """execute_tool_with_sources() increments _search_call_count on each call."""
    import agent.tools as tools_module
    tools_module.get_and_reset_search_count()  # clear any prior state
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(content=[])
    with patch("agent.tools._get_anthropic_client", return_value=mock_client):
        tools_module.execute_tool_with_sources("web_search", {"query": "test"})
    assert tools_module._search_call_count == 1


def test_get_and_reset_search_count_returns_accumulated_count():
    """get_and_reset_search_count() returns the number of calls since last reset."""
    import agent.tools as tools_module
    tools_module.get_and_reset_search_count()  # clear any prior state
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(content=[])
    with patch("agent.tools._get_anthropic_client", return_value=mock_client):
        tools_module.execute_tool_with_sources("web_search", {"query": "q1"})
        tools_module.execute_tool_with_sources("web_search", {"query": "q2"})
    count = tools_module.get_and_reset_search_count()
    assert count == 2


def test_get_and_reset_search_count_resets_to_zero():
    """A second call to get_and_reset_search_count() returns zero."""
    import agent.tools as tools_module
    tools_module.get_and_reset_search_count()  # clear
    second = tools_module.get_and_reset_search_count()
    assert second == 0


def test_unknown_tool_name_does_not_increment_counter():
    """An unknown tool name raises ValueError and does not increment the counter."""
    import agent.tools as tools_module
    tools_module.get_and_reset_search_count()  # clear
    with pytest.raises(ValueError):
        tools_module.execute_tool_with_sources("unknown_tool", {"query": "test"})
    assert tools_module._search_call_count == 0


def test_successful_web_search_increments_counter():
    """A successful web_search dispatch increments the counter exactly once."""
    import agent.tools as tools_module
    tools_module.get_and_reset_search_count()  # clear
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(content=[])
    with patch("agent.tools._get_anthropic_client", return_value=mock_client):
        tools_module.execute_tool_with_sources("web_search", {"query": "test"})
    assert tools_module._search_call_count == 1


def test_failed_anthropic_search_still_increments_counter():
    """Counter increments before API call so a failed search is still counted."""
    import agent.tools as tools_module
    tools_module.get_and_reset_search_count()  # clear
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = ValueError("bad request")
    with patch("agent.tools._get_anthropic_client", return_value=mock_client):
        with pytest.raises(ValueError):
            tools_module.execute_tool_with_sources("web_search", {"query": "test"})
    assert tools_module._search_call_count >= 1


def test_tavily_search_increments_counter():
    """_tavily_search_with_sources() increments counter before the Tavily API call."""
    import agent.tools as tools_module
    tools_module.configure_search("tavily", tavily_api_key="test-key")
    tools_module.get_and_reset_search_count()  # clear
    mock_tavily = MagicMock()
    mock_tavily.search.return_value = {"answer": "", "results": []}
    with patch("agent.tools.TavilyClient", return_value=mock_tavily):
        tools_module.execute_tool_with_sources("web_search", {"query": "test"})
    assert tools_module._search_call_count == 1


def test_malformed_tool_input_does_not_increment_counter():
    """A KeyError from missing query field does not increment the counter."""
    import agent.tools as tools_module
    tools_module.get_and_reset_search_count()  # clear
    with pytest.raises(KeyError):
        tools_module.execute_tool_with_sources("web_search", {})  # missing "query"
    assert tools_module._search_call_count == 0


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

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    with patch("agent.tools._get_anthropic_client", return_value=mock_client):
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

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    with patch("agent.tools._get_anthropic_client", return_value=mock_client):
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

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    with patch("agent.tools._get_anthropic_client", return_value=mock_client):
        result, sources = _anthropic_search_with_sources("nuclear fusion")

    assert len(sources) == 1


def test_anthropic_search_returns_no_results_fallback():
    """An empty content list returns 'No results found.' and an empty sources list."""
    from agent.tools import _anthropic_search_with_sources

    mock_response = MagicMock()
    mock_response.content = []

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    with patch("agent.tools._get_anthropic_client", return_value=mock_client):
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
    with patch("agent.tools.TavilyClient", new=None):
        with pytest.raises(ImportError, match="tavily-python not installed"):
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


# ── build_tool_list() tests ──────────────────────────────────────────────────

def test_build_tool_list_web_search_returns_web_search_descriptor():
    """build_tool_list(('web_search',)) returns [WEB_SEARCH_TOOL]."""
    from agent.tools import build_tool_list, WEB_SEARCH_TOOL
    result = build_tool_list(("web_search",))
    assert result == [WEB_SEARCH_TOOL]


def test_build_tool_list_kg_tool_returns_kg_descriptor():
    """build_tool_list(('kg_check_contradiction',)) returns the kg_ descriptor."""
    from agent.tools import build_tool_list, KG_TOOL_DESCRIPTORS
    result = build_tool_list(("kg_check_contradiction",))
    assert len(result) == 1
    assert result[0]["name"] == "kg_check_contradiction"
    assert result[0] is KG_TOOL_DESCRIPTORS["kg_check_contradiction"]


def test_build_tool_list_unknown_name_raises_value_error():
    """build_tool_list() raises ValueError for unknown tool names."""
    import pytest
    from agent.tools import build_tool_list
    with pytest.raises(ValueError, match="Unknown tool names"):
        build_tool_list(("web_search", "unknown_tool_xyz"))


# ── kg_ tool routing tests ───────────────────────────────────────────────────

def test_kg_query_claims_returns_unavailable_when_no_store():
    """kg_query_claims_for_topic returns error JSON when store is not configured."""
    from agent.tools import kg_query_claims_for_topic
    import knowledge.store as ks
    orig = ks._store
    ks._store = None
    try:
        result = kg_query_claims_for_topic("topic")
        assert "error" in result
    finally:
        ks._store = orig


def test_kg_check_contradiction_returns_unresolved_when_no_store():
    """kg_check_contradiction returns unresolved JSON when store is not configured."""
    import json
    from agent.tools import kg_check_contradiction
    import knowledge.store as ks
    orig = ks._store
    ks._store = None
    try:
        result = json.loads(kg_check_contradiction("claim text", "topic"))
        assert result["status"] == "unresolved"
    finally:
        ks._store = orig


def test_kg_check_contradiction_uses_configured_staleness():
    """configure_knowledge() caches staleness_threshold_days into _staleness_days."""
    from unittest.mock import MagicMock, patch
    from agent import tools

    mock_config = MagicMock()
    mock_config.knowledge_staleness_threshold_days = 7

    with patch("knowledge.store.configure_knowledge"):
        tools.configure_knowledge(mock_config)

    assert tools._staleness_days == 7


def test_kg_write_claim_returns_error_when_no_store():
    """kg_write_claim returns error JSON when store is not configured."""
    import json
    from agent.tools import kg_write_claim
    import knowledge.store as ks
    orig = ks._store
    ks._store = None
    try:
        result = json.loads(kg_write_claim({"claim": "test", "sources": []}))
        assert result["status"] == "error"
    finally:
        ks._store = orig


def test_execute_tool_with_sources_routes_kg_query(tmp_path):
    """execute_tool_with_sources routes kg_query_claims_for_topic to knowledge store."""
    from agent.tools import execute_tool_with_sources
    from knowledge.store import KuzuStore
    import knowledge.store as ks
    store = KuzuStore(str(tmp_path / "test.db"))
    orig = ks._store
    ks._store = store
    try:
        result, sources = execute_tool_with_sources(
            "kg_query_claims_for_topic", {"topic": "unknown topic xyz"}
        )
        assert result == "[]"
        assert sources == []
    finally:
        ks._store = orig
        store.close()


def test_execute_tool_with_sources_kg_write_claim_routes_to_claim_dict(tmp_path):
    """execute_tool_with_sources("kg_write_claim", {"claim_dict": {...}}) routes correctly."""
    import json
    from agent.tools import execute_tool_with_sources
    from knowledge.store import KuzuStore
    import knowledge.store as ks
    store = KuzuStore(str(tmp_path / "test.db"))
    orig = ks._store
    ks._store = store
    try:
        valid_claim = {
            "claim": "The speed of light is approximately 3×10⁸ m/s.",
            "confidence": 0.9,
            "verification_status": "verified",
            "sources": [{"url": "https://example.com", "title": "Physics ref"}],
        }
        result, sources = execute_tool_with_sources(
            "kg_write_claim", {"claim_dict": valid_claim}
        )
        parsed = json.loads(result)
        assert parsed["status"] == "written"
        assert sources == []
    finally:
        ks._store = orig
        store.close()


def test_execute_tool_with_sources_kg_write_claim_old_claim_json_returns_rejected(tmp_path):
    """Calling kg_write_claim with old 'claim_json' key (string) returns rejected, not an exception."""
    import json
    from agent.tools import execute_tool_with_sources
    from knowledge.store import KuzuStore
    import knowledge.store as ks
    store = KuzuStore(str(tmp_path / "test.db"))
    orig = ks._store
    ks._store = store
    try:
        # Old broken path: claim_dict key absent, would have been claim_json string
        result, sources = execute_tool_with_sources(
            "kg_write_claim", {"claim_json": '{"claim": "test"}'}
        )
        parsed = json.loads(result)
        # claim_dict defaults to {} → rejected (empty claim text)
        assert parsed["status"] == "rejected"
        assert sources == []
    finally:
        ks._store = orig
        store.close()


def test_execute_tool_with_sources_kg_write_claim_json_string_parses_correctly(tmp_path):
    """Dispatcher with claim_dict as a JSON string parses and routes to write_claim."""
    import json
    from agent.tools import execute_tool_with_sources
    from knowledge.store import KuzuStore
    import knowledge.store as ks
    store = KuzuStore(str(tmp_path / "test.db"))
    orig = ks._store
    ks._store = store
    try:
        valid_claim_json = json.dumps({
            "claim": "The speed of light is approximately 3×10⁸ m/s.",
            "confidence": 0.9,
            "verification_status": "verified",
            "sources": [{"url": "https://example.com", "title": "Physics ref"}],
        })
        result, sources = execute_tool_with_sources(
            "kg_write_claim", {"claim_dict": valid_claim_json}
        )
        parsed = json.loads(result)
        assert parsed["status"] == "written"
        assert sources == []
    finally:
        ks._store = orig
        store.close()


def test_execute_tool_with_sources_kg_write_claim_invalid_json_string_returns_rejected(tmp_path):
    """Dispatcher with claim_dict as an unparseable JSON string returns rejected."""
    import json
    from agent.tools import execute_tool_with_sources
    from knowledge.store import KuzuStore
    import knowledge.store as ks
    store = KuzuStore(str(tmp_path / "test.db"))
    orig = ks._store
    ks._store = store
    try:
        result, sources = execute_tool_with_sources(
            "kg_write_claim", {"claim_dict": "not valid json {{{"}
        )
        parsed = json.loads(result)
        assert parsed["status"] == "rejected"
        assert "parsed" in parsed["reason"]
        assert sources == []
    finally:
        ks._store = orig
        store.close()


def test_kg_calls_do_not_increment_search_count():
    """kg_ tool calls do not increment _search_call_count."""
    from agent import tools
    from agent.tools import kg_query_claims_for_topic
    import knowledge.store as ks
    orig_store = ks._store
    orig_count = tools._search_call_count
    ks._store = None
    tools._search_call_count = 0
    try:
        kg_query_claims_for_topic("some topic")
        assert tools._search_call_count == 0
    finally:
        ks._store = orig_store
        tools._search_call_count = orig_count


# ── read_url / _fetch_url tests ───────────────────────────────────────────────

def test_fetch_url_rejects_non_http_scheme():
    """_fetch_url returns an error dict for non-http/https URL schemes."""
    import agent.tools as tools
    result = tools._fetch_url("ftp://example.com/file.txt", 8000, 10)
    assert "error" in result
    assert "http" in result["error"]


def test_fetch_url_rejects_file_scheme():
    """_fetch_url returns an error dict for file:// URLs."""
    import agent.tools as tools
    result = tools._fetch_url("file:///etc/passwd", 8000, 10)
    assert "error" in result


def test_fetch_url_returns_error_on_timeout(monkeypatch):
    """_fetch_url returns an error dict when requests.get raises Timeout."""
    import agent.tools as tools
    import requests as _requests

    def _raise_timeout(*a, **kw):
        raise _requests.exceptions.Timeout()

    monkeypatch.setattr("agent.tools.requests.get", _raise_timeout)
    # Pre-populate robots cache to skip robots.txt fetch
    tools._robots_cache["https://example.com"] = None
    result = tools._fetch_url("https://example.com/page", 8000, 10)
    assert "error" in result
    assert "timed out" in result["error"]


def test_fetch_url_returns_error_on_http_4xx(monkeypatch):
    """_fetch_url returns an error dict when the response status is 4xx."""
    import agent.tools as tools
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    monkeypatch.setattr("agent.tools.requests.get", lambda *a, **kw: mock_resp)
    tools._robots_cache["https://example.com"] = None
    result = tools._fetch_url("https://example.com/missing", 8000, 10)
    assert "error" in result
    assert "404" in result["error"]


def test_fetch_url_returns_structured_dict_on_success(monkeypatch):
    """_fetch_url returns url, title, text, truncated on a successful trafilatura extract."""
    import agent.tools as tools
    import json
    from unittest.mock import MagicMock, patch

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
    mock_resp.text = "<html><body><p>Article text here.</p></body></html>"
    monkeypatch.setattr("agent.tools.requests.get", lambda *a, **kw: mock_resp)
    tools._robots_cache["https://example.com"] = None

    trafilatura_result = json.dumps({
        "title": "Test Title",
        "author": "Test Author",
        "date": "2026-01-01",
        "text": "Article text here.",
    })
    with patch("agent.tools._trafilatura") as mock_traf:
        mock_traf.extract.return_value = trafilatura_result
        with patch.object(tools, "TRAFILATURA_AVAILABLE", True):
            result = tools._fetch_url("https://example.com/article", 8000, 10)

    assert result["url"] == "https://example.com/article"
    assert result["title"] == "Test Title"
    assert result["text"] == "Article text here."
    assert result["truncated"] is False


def test_fetch_url_falls_back_to_bleach_when_trafilatura_returns_none(monkeypatch):
    """_fetch_url uses bleach fallback when trafilatura.extract() returns None."""
    import agent.tools as tools
    from unittest.mock import MagicMock, patch

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "text/html"}
    mock_resp.raw.read.return_value = b"<p>Prose content.</p><script>evil()</script>"
    monkeypatch.setattr("agent.tools.requests.get", lambda *a, **kw: mock_resp)
    tools._robots_cache["https://example.com"] = None

    with patch("agent.tools._trafilatura") as mock_traf:
        mock_traf.extract.return_value = None
        with patch.object(tools, "TRAFILATURA_AVAILABLE", True):
            result = tools._fetch_url("https://example.com/page", 8000, 10)

    assert "error" not in result
    assert "Prose content." in result["text"]
    assert result["title"] is None


def test_fetch_url_falls_back_to_bleach_when_trafilatura_raises(monkeypatch):
    """_fetch_url uses bleach fallback when trafilatura.extract() raises an exception."""
    import agent.tools as tools
    from unittest.mock import MagicMock, patch

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "text/html"}
    mock_resp.raw.read.return_value = b"<p>Fallback prose.</p>"
    monkeypatch.setattr("agent.tools.requests.get", lambda *a, **kw: mock_resp)
    tools._robots_cache["https://example.com"] = None

    with patch("agent.tools._trafilatura") as mock_traf:
        mock_traf.extract.side_effect = RuntimeError("parse error")
        with patch.object(tools, "TRAFILATURA_AVAILABLE", True):
            result = tools._fetch_url("https://example.com/page", 8000, 10)

    assert "error" not in result
    assert "Fallback prose." in result["text"]


def test_fetch_url_reads_only_up_to_max_bytes(monkeypatch):
    """_fetch_url calls response.raw.read with max_chars * 4 as the byte limit."""
    import agent.tools as tools
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "text/html"}
    mock_resp.raw.read.return_value = b"<p>Short page.</p>"
    monkeypatch.setattr("agent.tools.requests.get", lambda *a, **kw: mock_resp)
    monkeypatch.setattr("agent.tools.TRAFILATURA_AVAILABLE", False)
    tools._robots_cache["https://example.com"] = None

    tools._fetch_url("https://example.com/page", 500, 10)

    mock_resp.raw.read.assert_called_once_with(2000, decode_content=True)


def test_fetch_url_rejects_pdf_content_type(monkeypatch):
    """_fetch_url returns error dict when Content-Type is application/pdf."""
    import agent.tools as tools
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "application/pdf"}
    monkeypatch.setattr("agent.tools.requests.get", lambda *a, **kw: mock_resp)
    tools._robots_cache["https://example.com"] = None
    result = tools._fetch_url("https://example.com/paper.pdf", 8000, 10)
    assert "error" in result
    assert "application/pdf" in result["error"]


def test_fetch_url_rejects_image_content_type(monkeypatch):
    """_fetch_url returns error dict when Content-Type is image/jpeg."""
    import agent.tools as tools
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "image/jpeg"}
    monkeypatch.setattr("agent.tools.requests.get", lambda *a, **kw: mock_resp)
    tools._robots_cache["https://example.com"] = None
    result = tools._fetch_url("https://example.com/photo.jpg", 8000, 10)
    assert "error" in result
    assert "image/jpeg" in result["error"]


def test_fetch_url_proceeds_for_text_html_content_type(monkeypatch):
    """_fetch_url proceeds normally when Content-Type is text/html."""
    import agent.tools as tools
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
    mock_resp.text = "<p>Hello world.</p>"
    monkeypatch.setattr("agent.tools.requests.get", lambda *a, **kw: mock_resp)
    monkeypatch.setattr("agent.tools.TRAFILATURA_AVAILABLE", False)
    tools._robots_cache["https://example.com"] = None
    result = tools._fetch_url("https://example.com/page", 8000, 10)
    assert "error" not in result


def test_read_url_returns_json_string():
    """read_url() returns a JSON-serialisable string."""
    import json, agent.tools as tools
    from unittest.mock import patch

    with patch.object(tools, "_fetch_url", return_value={"url": "https://x.com", "text": "ok"}):
        result = tools.read_url("https://x.com")
    parsed = json.loads(result)
    assert parsed["text"] == "ok"


def test_read_url_does_not_increment_search_count():
    """read_url calls do not increment the search counter."""
    import agent.tools as tools
    from unittest.mock import patch

    tools._search_call_count = 0
    with patch.object(tools, "_fetch_url", return_value={"text": "ok"}):
        tools.execute_tool_with_sources("read_url", {"url": "https://x.com"})
    assert tools._search_call_count == 0


def test_execute_tool_with_sources_routes_read_url():
    """execute_tool_with_sources dispatches read_url and returns empty sources list."""
    import agent.tools as tools
    from unittest.mock import patch

    with patch.object(tools, "read_url", return_value='{"text":"content"}') as mock_ru:
        result, sources = tools.execute_tool_with_sources(
            "read_url", {"url": "https://example.com"}
        )
    mock_ru.assert_called_once_with("https://example.com")
    assert sources == []
    assert result == '{"text":"content"}'


def test_fetch_url_robots_txt_uses_requests_get_with_timeout(monkeypatch):
    """robots.txt is fetched via requests.get with the configured timeout."""
    import agent.tools as tools
    from unittest.mock import MagicMock

    robots_resp = MagicMock()
    robots_resp.status_code = 200
    robots_resp.text = "User-agent: *\nDisallow:"

    page_resp = MagicMock()
    page_resp.status_code = 200
    page_resp.headers = {"Content-Type": "text/html"}
    page_resp.text = "<html><body>Hello</body></html>"

    call_records = []

    def fake_get(url, **kw):
        call_records.append((url, kw.get("timeout")))
        if "robots.txt" in url:
            return robots_resp
        return page_resp

    tools._robots_cache.pop("https://robots-test.example.com", None)
    monkeypatch.setattr("agent.tools.requests.get", fake_get)
    monkeypatch.setattr("agent.tools.TRAFILATURA_AVAILABLE", False)

    tools._fetch_url("https://robots-test.example.com/page", 8000, 7)

    robots_call = next(c for c in call_records if "robots.txt" in c[0])
    assert robots_call[1] == 7, "robots.txt fetch must use the configured timeout"
    tools._robots_cache.pop("https://robots-test.example.com", None)


def test_fetch_url_robots_timeout_sets_cache_to_none_and_proceeds(monkeypatch):
    """A Timeout on robots.txt sets cache[domain]=None and allows the main fetch."""
    import agent.tools as tools
    import requests as _requests
    from unittest.mock import MagicMock

    domain = "https://slow-robots.example.com"
    page_resp = MagicMock()
    page_resp.status_code = 200
    page_resp.headers = {"Content-Type": "text/html"}
    page_resp.text = "<p>content</p>"

    def fake_get(url, **kw):
        if "robots.txt" in url:
            raise _requests.exceptions.Timeout()
        return page_resp

    tools._robots_cache.pop(domain, None)
    monkeypatch.setattr("agent.tools.requests.get", fake_get)
    monkeypatch.setattr("agent.tools.TRAFILATURA_AVAILABLE", False)

    result = tools._fetch_url(f"{domain}/page", 8000, 5)

    assert tools._robots_cache.get(domain) is None
    assert "error" not in result
    tools._robots_cache.pop(domain, None)


# ── arxiv_search / _arxiv_search tests ───────────────────────────────────────

_ARXIV_ATOM_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2407.04363v1</id>
    <title>Attention Is All You Need</title>
    <author><name>Alice Smith</name></author>
    <author><name>Bob Jones</name></author>
    <summary>A paper about transformers.</summary>
    <published>2024-07-05T00:00:00Z</published>
    <arxiv:primary_category term="cs.LG"/>
    <category term="cs.LG"/>
    <category term="cs.AI"/>
  </entry>
</feed>"""


def _make_arxiv_response(text=_ARXIV_ATOM_FIXTURE, status=200):
    from unittest.mock import MagicMock
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.raise_for_status = MagicMock()
    return r


def test_arxiv_search_returns_list_of_dicts(monkeypatch):
    """_arxiv_search() returns a list of result dicts with required fields."""
    import agent.tools as tools

    monkeypatch.setattr("agent.tools.requests.get",
                        lambda *a, **kw: _make_arxiv_response())
    results = tools._arxiv_search("transformers")
    assert isinstance(results, list)
    assert len(results) == 1
    result = results[0]
    for key in ("arxiv_id", "title", "authors", "abstract", "published", "url", "categories"):
        assert key in result, f"missing key: {key}"


def test_arxiv_search_extracts_arxiv_id_and_strips_version(monkeypatch):
    """_arxiv_search() extracts the arXiv ID without version suffix."""
    import agent.tools as tools

    monkeypatch.setattr("agent.tools.requests.get",
                        lambda *a, **kw: _make_arxiv_response())
    results = tools._arxiv_search("transformers")
    assert results[0]["arxiv_id"] == "2407.04363"


def test_arxiv_search_includes_categories(monkeypatch):
    """_arxiv_search() includes categories from primary_category and category elements."""
    import agent.tools as tools

    monkeypatch.setattr("agent.tools.requests.get",
                        lambda *a, **kw: _make_arxiv_response())
    results = tools._arxiv_search("transformers")
    cats = results[0]["categories"]
    assert "cs.LG" in cats
    assert "cs.AI" in cats


def test_arxiv_search_returns_empty_list_on_network_error(monkeypatch):
    """_arxiv_search() returns [] and logs a warning on a network error."""
    import agent.tools as tools
    import requests as _req

    monkeypatch.setattr("agent.tools.requests.get",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            _req.exceptions.ConnectionError("no route")))
    results = tools._arxiv_search("transformers")
    assert results == []


def test_arxiv_search_wrapper_returns_json_string(monkeypatch):
    """arxiv_search() returns a JSON string."""
    import json, agent.tools as tools

    monkeypatch.setattr("agent.tools.requests.get",
                        lambda *a, **kw: _make_arxiv_response())
    result = tools.arxiv_search("transformers")
    parsed = json.loads(result)
    assert isinstance(parsed, list)
    assert len(parsed) == 1


def test_arxiv_search_does_not_increment_search_count(monkeypatch):
    """arxiv_search calls do not increment the search counter."""
    import agent.tools as tools

    tools._search_call_count = 0
    monkeypatch.setattr("agent.tools.requests.get",
                        lambda *a, **kw: _make_arxiv_response())
    tools.execute_tool_with_sources("arxiv_search", {"query": "attention"})
    assert tools._search_call_count == 0


def test_execute_tool_with_sources_routes_arxiv_search():
    """execute_tool_with_sources dispatches arxiv_search and returns empty sources."""
    import agent.tools as tools
    from unittest.mock import patch

    with patch.object(tools, "arxiv_search", return_value="[]") as mock_ax:
        result, sources = tools.execute_tool_with_sources(
            "arxiv_search", {"query": "transformers"}
        )
    mock_ax.assert_called_once_with("transformers")
    assert sources == []
    assert result == "[]"


def test_arxiv_search_not_in_verifier_tools():
    """arxiv_search is not in the Verifier's tool set."""
    from unittest.mock import MagicMock, patch
    from pathlib import Path
    import tempfile, os

    with tempfile.TemporaryDirectory() as tmpdir:
        for name in ("researcher", "verifier", "editor"):
            (Path(tmpdir) / f"{name}.md").write_text(f"# {name}")

        mock_orch = MagicMock()
        mock_synth = MagicMock()
        mock_config = MagicMock()
        mock_config.max_iterations = 5
        mock_config.verifier_max_iterations = 4
        mock_config.editor_provider = None
        mock_config.knowledge_store = "none"

        from agent.builder import build_agents
        pool = build_agents(mock_config, mock_orch, mock_synth, prompt_dir=tmpdir)

    assert "arxiv_search" not in pool.verifier.tools
    assert "arxiv_search" in pool.researcher.tools


def test_read_url_in_verifier_tools():
    """read_url is in both the Researcher and Verifier tool sets."""
    from unittest.mock import MagicMock
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        for name in ("researcher", "verifier", "editor"):
            (Path(tmpdir) / f"{name}.md").write_text(f"# {name}")

        mock_orch = MagicMock()
        mock_synth = MagicMock()
        mock_config = MagicMock()
        mock_config.max_iterations = 5
        mock_config.verifier_max_iterations = 4
        mock_config.editor_provider = None
        mock_config.knowledge_store = "none"

        from agent.builder import build_agents
        pool = build_agents(mock_config, mock_orch, mock_synth, prompt_dir=tmpdir)

    assert "read_url" in pool.researcher.tools
    assert "read_url" in pool.verifier.tools


def test_all_tool_descriptors_have_parameters_key():
    """Every descriptor in all tool dicts uses 'parameters', not 'input_schema'."""
    from agent.tools import (
        WEB_SEARCH_TOOL,
        KG_TOOL_DESCRIPTORS,
        URL_TOOL_DESCRIPTORS,
        ARXIV_TOOL_DESCRIPTORS,
    )
    all_descriptors = [
        WEB_SEARCH_TOOL,
        *KG_TOOL_DESCRIPTORS.values(),
        *URL_TOOL_DESCRIPTORS.values(),
        *ARXIV_TOOL_DESCRIPTORS.values(),
    ]
    for d in all_descriptors:
        assert "parameters" in d, (
            f"{d['name']} missing 'parameters' key"
        )


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
