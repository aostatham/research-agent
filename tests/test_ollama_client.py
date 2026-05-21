import pytest
from unittest.mock import patch, MagicMock
from llm.ollama_client import OllamaClient
from llm.base import LLMResponse


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    return OllamaClient(model="llama3.2")


# ── Unit tests ────────────────────────────────────────────────────────────────

def test_default_base_url(client):
    assert client.base_url == "http://localhost:11434"


def test_custom_base_url():
    client = OllamaClient(base_url="http://localhost:9999")
    assert client.base_url == "http://localhost:9999"


def test_chat_returns_text_response(client):
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
    import requests
    with patch("llm.ollama_client.requests.post", side_effect=requests.exceptions.ConnectionError):
        with pytest.raises(ConnectionError, match="Ollama"):
            client.chat([{"role": "user", "content": "hi"}])


def test_tool_conversion(client):
    tools = [{
        "name": "web_search",
        "description": "Search the web",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }]
    converted = client._convert_tools(tools)
    assert converted[0]["type"] == "function"
    assert converted[0]["function"]["name"] == "web_search"
    assert converted[0]["function"]["parameters"] == tools[0]["parameters"]


def test_chat_with_no_tools_succeeds(client):
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
    client = OllamaClient(model="llama3.2")
    response = client.chat([{"role": "user", "content": "Reply with exactly two words."}])
    assert response.type == "text"
    assert len(response.content) > 0
    