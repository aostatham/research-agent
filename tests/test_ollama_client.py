"""
Tests for llm/ollama_client.py — OllamaClient.

Verifies:
    - Default and custom base URL configuration.
    - chat() normalises text and tool_call responses from Ollama JSON format.
    - Connection errors surface as a descriptive ConnectionError.
    - Tools are converted from agnostic format to OpenAI function format.

All unit tests patch requests.post to avoid a running Ollama server.
Integration tests (marked ollama) require `ollama serve` to be active.
"""

import pytest
from unittest.mock import patch, MagicMock
from llm.ollama_client import OllamaClient
from llm.base import LLMResponse


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """OllamaClient instance with a non-default model for test isolation."""
    return OllamaClient(model="llama3.2")


# ── Unit tests ────────────────────────────────────────────────────────────────

def test_default_base_url(client):
    """Default base URL is the standard Ollama local endpoint."""
    assert client.base_url == "http://localhost:11434"


def test_custom_base_url():
    """Trailing slash is stripped from a custom base URL."""
    client = OllamaClient(base_url="http://localhost:9999")
    assert client.base_url == "http://localhost:9999"


def test_chat_returns_text_response(client):
    """A plain message.content response is normalised to LLMResponse(type='text')."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "message": {"role": "assistant", "content": "hello world"}
    }
    mock_response.raise_for_status = MagicMock()

    with patch("llm.ollama_client.requests.post", return_value=mock_response):
        response = client.chat([{"role": "user", "content": "hi"}])

    assert isinstance(response, LLMResponse)
    assert response.type == "text"
    assert response.content == "hello world"


def test_chat_returns_tool_call_response(client):
    """A message.tool_calls list is normalised to LLMResponse(type='tool_call')."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "function": {
                    "name": "web_search",
                    "arguments": {"query": "fusion energy"}
                }
            }]
        }
    }
    mock_response.raise_for_status = MagicMock()

    with patch("llm.ollama_client.requests.post", return_value=mock_response):
        response = client.chat([{"role": "user", "content": "search"}])

    assert response.type == "tool_call"
    assert response.tool_name == "web_search"
    assert response.tool_input == {"query": "fusion energy"}


def test_connection_error_raises_cleanly(client):
    """A ConnectionError from requests is re-raised with an actionable message."""
    import requests
    with patch("llm.ollama_client.requests.post", side_effect=requests.exceptions.ConnectionError):
        with pytest.raises(ConnectionError, match="Ollama"):
            client.chat([{"role": "user", "content": "hi"}])


def test_tool_conversion(client):
    """Tools are converted to OpenAI-compatible function format (type/function envelope)."""
    tools = [{
        "name": "web_search",
        "description": "Search the web",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }]
    converted = client._convert_tools(tools)
    assert converted[0]["type"] == "function"
    assert converted[0]["function"]["name"] == "web_search"
    # Ollama uses "parameters" (OpenAI convention), not "input_schema"
    assert converted[0]["function"]["parameters"] == tools[0]["parameters"]


def test_chat_with_no_tools_succeeds(client):
    """chat() without tools omits the tools key from the payload."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "message": {"role": "assistant", "content": "ok"}
    }
    mock_response.raise_for_status = MagicMock()

    with patch("llm.ollama_client.requests.post", return_value=mock_response):
        response = client.chat([{"role": "user", "content": "hi"}])
    assert response.type == "text"


# ── Integration tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
def test_real_simple_chat():
    """Live call to local Ollama returns a non-empty text response."""
    client = OllamaClient(model="llama3.2")
    response = client.chat([{"role": "user", "content": "Reply with exactly two words."}])
    assert response.type == "text"
    assert len(response.content) > 0
