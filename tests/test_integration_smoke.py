"""
End-to-end smoke tests for live API calls.

All tests are marked @pytest.mark.integration and require real credentials.
Ollama tests additionally require @pytest.mark.ollama and a running Ollama server.

Run with:
    pytest tests/test_integration_smoke.py -m "integration and not ollama" -v
    pytest tests/test_integration_smoke.py -m "ollama" -v

These tests validate that the pipeline components work against their real
backends and that both LLM providers produce the correct response shape.
They are intentionally excluded from the default test run (pytest -m "not integration").
"""

import pytest
from dotenv import load_dotenv

load_dotenv()


# ── Anthropic smoke tests ─────────────────────────────────────────────────────
# Confirm live Anthropic API connectivity and basic tool-call flow.

@pytest.mark.integration
def test_anthropic_basic_chat():
    """AnthropicClient returns a non-empty text response from the live API."""
    from llm import AnthropicClient
    client = AnthropicClient()
    response = client.chat([{"role": "user", "content": "Reply with exactly two words."}])
    assert response.type == "text"
    assert len(response.content) > 0


@pytest.mark.integration
def test_anthropic_tool_call():
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
def test_anthropic_web_search_execute():
    """execute_tool() with web_search returns a non-empty string from the Anthropic API."""
    from agent.tools import execute_tool
    result = execute_tool("web_search", {"query": "nuclear fusion 2026"})
    assert isinstance(result, str)
    assert len(result) > 100


# ── Ollama smoke tests ────────────────────────────────────────────────────────
# Confirm live Ollama connectivity (requires ollama serve and llama3.1 pulled).

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


# ── Provider parity smoke test ────────────────────────────────────────────────
# Confirm that both providers respond to the same prompt and return
# the same response shape (the LLMClient contract).

@pytest.mark.integration
@pytest.mark.ollama
def test_both_providers_respond_to_same_prompt():
    """Anthropic and Ollama both return non-empty text responses for the same prompt."""
    from llm import AnthropicClient, OllamaClient
    prompt = [{"role": "user", "content": "In one sentence, what is nuclear fusion?"}]

    anthropic_response = AnthropicClient().chat(prompt)
    ollama_response = OllamaClient(model="llama3.1").chat(prompt)

    assert anthropic_response.type == "text"
    assert ollama_response.type == "text"
    assert len(anthropic_response.content) > 0
    assert len(ollama_response.content) > 0
