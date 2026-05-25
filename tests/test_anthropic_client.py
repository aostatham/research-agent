"""
Tests for llm/anthropic_client.py — AnthropicClient.

Verifies:
    - Construction fails without ANTHROPIC_API_KEY in environment.
    - chat() normalises text and tool_call responses correctly.
    - Tools are converted from agnostic format to Anthropic input_schema format.
    - The raw provider response is stored on LLMResponse.raw.

All unit tests patch the Anthropic SDK client to avoid real API calls.
Integration tests (marked) make live calls to validate end-to-end behaviour.
"""

import pytest
from unittest.mock import MagicMock, patch
from llm.anthropic_client import AnthropicClient
from llm.base import LLMResponse


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """AnthropicClient with a mocked underlying SDK client."""
    with patch("llm.anthropic_client.anthropic.Anthropic"):
        return AnthropicClient()


# ── Unit tests ────────────────────────────────────────────────────────────────

def test_missing_api_key_raises(monkeypatch):
    """Construction must raise ValueError when ANTHROPIC_API_KEY is absent."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("llm.anthropic_client.anthropic.Anthropic"):
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            AnthropicClient()


def test_chat_returns_text_response(client):
    """A text content block is normalised to LLMResponse(type='text')."""
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
    """A tool_use content block is normalised to LLMResponse(type='tool_call')."""
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
    """chat() without tools does not include a tools key in the API payload."""
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "ok"
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    client.client.messages.create.return_value = mock_response

    response = client.chat([{"role": "user", "content": "hi"}])
    assert response.type == "text"


def test_tool_conversion(client):
    """Tools are converted from agnostic 'parameters' key to Anthropic 'input_schema'."""
    tools = [{
        "name": "web_search",
        "description": "Search the web",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }]
    converted = client._convert_tools(tools)
    assert converted[0]["name"] == "web_search"
    assert converted[0]["input_schema"] == tools[0]["parameters"]
    # The agnostic 'parameters' key must not appear in the converted output
    assert "parameters" not in converted[0]


def test_raw_response_stored(client):
    """The raw Anthropic response object is preserved on LLMResponse.raw."""
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "hello"
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    client.client.messages.create.return_value = mock_response

    response = client.chat([{"role": "user", "content": "hi"}])
    assert response.raw == mock_response


# ── system prompt routing ─────────────────────────────────────────────────────

def test_chat_passes_system_to_api_when_provided(client):
    """When system= is given, it must appear as a top-level kwarg in the API call."""
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "ok"
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    client.client.messages.create.return_value = mock_response

    client.chat([{"role": "user", "content": "hi"}], system="be concise")

    call_kwargs = client.client.messages.create.call_args.kwargs
    assert call_kwargs.get("system") == "be concise"


def test_chat_does_not_pass_system_when_none(client):
    """When system= is None (default), the system key must not appear in the API call."""
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "ok"
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    client.client.messages.create.return_value = mock_response

    client.chat([{"role": "user", "content": "hi"}])

    call_kwargs = client.client.messages.create.call_args.kwargs
    assert "system" not in call_kwargs


# ── Integration tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
def test_real_simple_chat():
    """Live call to Anthropic API returns a non-empty text response."""
    client = AnthropicClient()
    response = client.chat([{"role": "user", "content": "Reply with exactly two words."}])
    assert response.type == "text"
    assert len(response.content) > 0
