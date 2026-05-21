import pytest
from unittest.mock import MagicMock, patch
from llm.anthropic_client import AnthropicClient
from llm.base import LLMResponse


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    with patch("llm.anthropic_client.anthropic.Anthropic"):
        return AnthropicClient()


# ── Unit tests ────────────────────────────────────────────────────────────────

def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("llm.anthropic_client.anthropic.Anthropic"):
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            AnthropicClient()


def test_chat_returns_text_response(client):
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "hello world"
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    client.client.messages.create.return_value = mock_response

    response = client.chat([{"role": "user", "content": "hi"}])

    assert isinstance(response, LLMResponse)
    assert response.type == "text"
    assert response.content == "hello world"


def test_chat_returns_tool_call_response(client):
    mock_block = MagicMock()
    mock_block.type = "tool_use"
    mock_block.name = "web_search"
    mock_block.input = {"query": "fusion energy"}
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    client.client.messages.create.return_value = mock_response

    response = client.chat(
        [{"role": "user", "content": "search for fusion"}],
        tools=[{
            "name": "web_search",
            "description": "Search the web",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
        }]
    )

    assert response.type == "tool_call"
    assert response.tool_name == "web_search"
    assert response.tool_input == {"query": "fusion energy"}


def test_chat_with_no_tools_succeeds(client):
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "ok"
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    client.client.messages.create.return_value = mock_response

    response = client.chat([{"role": "user", "content": "hi"}])
    assert response.type == "text"


def test_tool_conversion(client):
    tools = [{
        "name": "web_search",
        "description": "Search the web",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }]
    converted = client._convert_tools(tools)
    assert converted[0]["name"] == "web_search"
    assert converted[0]["input_schema"] == tools[0]["parameters"]
    assert "parameters" not in converted[0]


def test_raw_response_stored(client):
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "hello"
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    client.client.messages.create.return_value = mock_response

    response = client.chat([{"role": "user", "content": "hi"}])
    assert response.raw == mock_response


# ── Integration tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
def test_real_simple_chat():
    client = AnthropicClient()
    response = client.chat([{"role": "user", "content": "Reply with exactly two words."}])
    assert response.type == "text"
    assert len(response.content) > 0
    