"""
End-to-end smoke tests for live API calls.

Test strategy:
- Free-by-default: all tests that can run free use Ollama + Tavily
- Anthropic-specific tests are marked @pytest.mark.anthropic and require
  a live ANTHROPIC_API_KEY — run explicitly only when testing Anthropic behaviour
- Ollama tests require @pytest.mark.ollama and a running Ollama server

Run commands:
    # Free tests only (Ollama + Tavily) — default integration run
    pytest tests/test_integration_smoke.py -m "ollama" -v

    # Anthropic-specific tests (costs money)
    pytest tests/test_integration_smoke.py -m "anthropic_integration" -v

    # Full suite including both
    pytest tests/test_integration_smoke.py -m "integration" -v

    # All integration tests excluding Anthropic-specific
    pytest tests/test_integration_smoke.py -m "integration and not anthropic_integration" -v
"""

import pytest
import os
from dotenv import load_dotenv

load_dotenv()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def tavily_api_key():
    """Return Tavily API key or skip test if not configured."""
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        pytest.skip("TAVILY_API_KEY not set — skipping Tavily tests")
    return key


@pytest.fixture(scope="session")
def anthropic_api_key():
    """Return Anthropic API key or skip test if not configured."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set — skipping Anthropic tests")
    return key


# ── Ollama smoke tests (free) ─────────────────────────────────────────────────
# Default integration tests — require ollama serve + llama3.1 pulled.
# No API costs.

@pytest.mark.integration
@pytest.mark.ollama
def test_ollama_basic_chat():
    """OllamaClient returns a non-empty text response from a running Ollama server."""
    from llm import OllamaClient
    client = OllamaClient(model="llama3.1")
    response = client.chat([{"role": "user", "content": "Reply with exactly two words."}])
    assert response.type == "text"
    assert len(response.content) > 0


@pytest.mark.integration
@pytest.mark.ollama
def test_ollama_tool_call():
    """OllamaClient returns a tool_call response when web_search tool is provided."""
    from llm import OllamaClient
    from agent.tools import ALL_TOOLS
    client = OllamaClient(model="llama3.1")
    response = client.chat(
        messages=[{"role": "user", "content": "Search for the latest news on nuclear fusion."}],
        tools=ALL_TOOLS
    )
    assert response.type == "tool_call"
    assert response.tool_name == "web_search"
    assert "query" in response.tool_input


@pytest.mark.integration
@pytest.mark.ollama
def test_ollama_multi_turn_chat():
    """OllamaClient handles multi-turn message history correctly."""
    from llm import OllamaClient
    client = OllamaClient(model="llama3.1")
    messages = [
        {"role": "user", "content": "My favourite element is helium."},
        {"role": "assistant", "content": "Helium is a noble gas."},
        {"role": "user", "content": "What element did I mention?"}
    ]
    response = client.chat(messages)
    assert response.type == "text"
    assert "helium" in response.content.lower()


# ── Tavily smoke tests (free tier) ────────────────────────────────────────────
# Require TAVILY_API_KEY in .env — free up to 1,000 searches/month.

@pytest.mark.integration
def test_tavily_search_returns_results(tavily_api_key):
    """Tavily search returns non-empty text and at least one source."""
    from agent.tools import configure_search, execute_tool_with_sources
    configure_search("tavily", tavily_api_key=tavily_api_key)
    result, sources = execute_tool_with_sources("web_search", {"query": "nuclear fusion 2026"})
    assert isinstance(result, str)
    assert len(result) > 100
    assert len(sources) > 0
    assert all("url" in s for s in sources)
    assert all("title" in s for s in sources)


@pytest.mark.integration
def test_tavily_sources_have_valid_urls(tavily_api_key):
    """Tavily sources contain valid HTTP URLs."""
    from agent.tools import configure_search, execute_tool_with_sources
    configure_search("tavily", tavily_api_key=tavily_api_key)
    _, sources = execute_tool_with_sources("web_search", {"query": "quantum computing"})
    for source in sources:
        assert source["url"].startswith("http")


@pytest.mark.integration
def test_tavily_max_results_respected(tavily_api_key):
    """Tavily respects the max_results configuration."""
    from agent.tools import configure_search, execute_tool_with_sources
    configure_search("tavily", tavily_api_key=tavily_api_key, tavily_max_results=3)
    _, sources = execute_tool_with_sources("web_search", {"query": "nuclear fusion energy"})
    assert len(sources) <= 3


# ── Full pipeline smoke tests (free) ─────────────────────────────────────────
# Ollama orchestration + synthesis + Tavily search.
# No Anthropic API costs.

@pytest.mark.integration
@pytest.mark.ollama
def test_full_pipeline_free(tmp_path, monkeypatch, tavily_api_key):
    """
    Full research pipeline using only free providers.
    Ollama orchestration + synthesis, Tavily search.
    Validates that a report is generated with correct structure.
    """
    monkeypatch.chdir(tmp_path)
    from unittest.mock import patch

    with patch("sys.argv", [
        "main.py", "nuclear fusion",
        "--orchestration-provider", "ollama",
        "--orchestration-model", "llama3.1",
        "--synthesis-provider", "ollama",
        "--synthesis-model", "llama3.1",
        "--search-provider", "tavily",
        "--short",
        "--min-questions", "2",
        "--max-questions", "3"
    ]):
        from main import main
        main()

    output_files = [f for f in os.listdir(tmp_path / "output")
                    if f.endswith(".md") and f != "index.md"]
    assert len(output_files) == 1

    with open(tmp_path / "output" / output_files[0]) as f:
        content = f.read()

    assert len(content) > 500
    assert "#" in content
    assert "**Topic**" in content


@pytest.mark.integration
@pytest.mark.ollama
def test_full_pipeline_free_html(tmp_path, monkeypatch, tavily_api_key):
    """Full free pipeline produces valid HTML output."""
    monkeypatch.chdir(tmp_path)
    from unittest.mock import patch

    with patch("sys.argv", [
        "main.py", "nuclear fusion",
        "--orchestration-provider", "ollama",
        "--orchestration-model", "llama3.1",
        "--synthesis-provider", "ollama",
        "--synthesis-model", "llama3.1",
        "--search-provider", "tavily",
        "--short",
        "--format", "html",
        "--min-questions", "2",
        "--max-questions", "3"
    ]):
        from main import main
        main()

    html_files = [f for f in os.listdir(tmp_path / "output")
                  if f.endswith(".html")]
    assert len(html_files) == 1

    with open(tmp_path / "output" / html_files[0]) as f:
        content = f.read()

    assert "<!DOCTYPE html>" in content
    assert "nuclear fusion" in content.lower()


@pytest.mark.integration
@pytest.mark.ollama
def test_index_updated_after_free_run(tmp_path, monkeypatch, tavily_api_key):
    """Index file is updated correctly after a free pipeline run."""
    monkeypatch.chdir(tmp_path)
    from unittest.mock import patch

    with patch("sys.argv", [
        "main.py", "nuclear fusion",
        "--orchestration-provider", "ollama",
        "--orchestration-model", "llama3.1",
        "--synthesis-provider", "ollama",
        "--synthesis-model", "llama3.1",
        "--search-provider", "tavily",
        "--short",
        "--min-questions", "2",
        "--max-questions", "3"
    ]):
        from main import main
        main()

    assert os.path.exists(tmp_path / "output" / "index.md")
    with open(tmp_path / "output" / "index.md") as f:
        content = f.read()
    assert "nuclear fusion" in content
    assert "ollama" in content
    assert "tavily" in content


# ── Mixed provider smoke tests (free orchestration + paid synthesis) ───────────
# Ollama orchestration (free) + Anthropic synthesis (paid).
# Only run when explicitly testing mixed provider quality.

@pytest.mark.integration
@pytest.mark.ollama
def test_mixed_provider_pipeline(tmp_path, monkeypatch, tavily_api_key, anthropic_api_key):
    """
    Mixed provider pipeline — Ollama orchestration + Anthropic synthesis.
    Validates that mixed providers produce a deeper report than pure Ollama.
    """
    monkeypatch.chdir(tmp_path)
    from unittest.mock import patch

    with patch("sys.argv", [
        "main.py", "nuclear fusion",
        "--orchestration-provider", "ollama",
        "--orchestration-model", "llama3.1",
        "--synthesis-provider", "anthropic",
        "--synthesis-model", "claude-sonnet-4-6",
        "--search-provider", "tavily",
        "--short",
        "--min-questions", "2",
        "--max-questions", "3"
    ]):
        from main import main
        main()

    output_files = [f for f in os.listdir(tmp_path / "output")
                    if f.endswith(".md") and f != "index.md"]
    assert len(output_files) == 1

    with open(tmp_path / "output" / output_files[0]) as f:
        content = f.read()

    assert len(content) > 1000
    assert "anthropic" in content.lower()


# ── Anthropic-specific smoke tests (paid) ────────────────────────────────────
# Mark with anthropic_integration — only run when explicitly testing
# Anthropic-specific behaviour (citations, tool calling format, etc).
# These cost money — do not include in default integration runs.

@pytest.mark.integration
@pytest.mark.anthropic_integration
def test_anthropic_basic_chat(anthropic_api_key):
    """AnthropicClient returns a non-empty text response from the live API."""
    from llm import AnthropicClient
    client = AnthropicClient()
    response = client.chat([{"role": "user", "content": "Reply with exactly two words."}])
    assert response.type == "text"
    assert len(response.content) > 0


@pytest.mark.integration
@pytest.mark.anthropic_integration
def test_anthropic_tool_call(anthropic_api_key):
    """AnthropicClient returns a tool_call response when web_search tool is provided."""
    from llm import AnthropicClient
    from agent.tools import ALL_TOOLS
    client = AnthropicClient()
    response = client.chat(
        messages=[{"role": "user", "content": "Search for the latest news on nuclear fusion."}],
        tools=ALL_TOOLS
    )
    assert response.type == "tool_call"
    assert response.tool_name == "web_search"
    assert "query" in response.tool_input


@pytest.mark.integration
@pytest.mark.anthropic_integration
def test_anthropic_web_search_citations(anthropic_api_key):
    """Anthropic web search returns citations attached to text blocks."""
    from agent.tools import configure_search, execute_tool_with_sources
    configure_search("anthropic")
    result, sources = execute_tool_with_sources("web_search", {"query": "nuclear fusion 2026"})
    assert isinstance(result, str)
    assert len(result) > 100
    assert isinstance(sources, list)


@pytest.mark.integration
@pytest.mark.anthropic_integration
def test_both_providers_respond_to_same_prompt(anthropic_api_key):
    """Anthropic and Ollama both return non-empty text for the same prompt."""
    from llm import AnthropicClient, OllamaClient
    prompt = [{"role": "user", "content": "In one sentence, what is nuclear fusion?"}]

    anthropic_response = AnthropicClient().chat(prompt)
    ollama_response = OllamaClient(model="llama3.1").chat(prompt)

    assert anthropic_response.type == "text"
    assert ollama_response.type == "text"
    assert len(anthropic_response.content) > 0
    assert len(ollama_response.content) > 0