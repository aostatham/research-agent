"""
Tests for provider interchangeability — verifying the LLMClient abstraction.

The research pipeline must work identically regardless of which LLM provider
is wired up.  These tests confirm that both AnthropicClient and OllamaClient:

    1. Return the same LLMResponse shape (same field names).
    2. Produce the same response.type for equivalent inputs.
    3. Can be used by agent code that only talks to the LLMClient interface.

This is a contract test: if it breaks, the provider abstraction has drifted.
"""

import pytest
from unittest.mock import patch, MagicMock
from llm.anthropic_client import AnthropicClient
from llm.ollama_client import OllamaClient
from llm.base import LLMResponse


# ── Helper factories ──────────────────────────────────────────────────────────

def make_anthropic_client():
    """Return an AnthropicClient with the Anthropic SDK patched out."""
    with patch("llm.anthropic_client.anthropic.Anthropic"):
        return AnthropicClient()


def make_ollama_client():
    """Return an OllamaClient (no mocking needed at construction time)."""
    return OllamaClient(model="llama3.2")


def mock_anthropic_text(client, text="hello"):
    """Configure the mocked Anthropic SDK to return a text response."""
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = text
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    client.client.messages.create.return_value = mock_response


def mock_ollama_text(text="hello"):
    """Build a mock requests.Response that returns a text Ollama payload."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"message": {"role": "assistant", "content": text}}
    mock_response.raise_for_status = MagicMock()
    return mock_response


# ── Shape tests ───────────────────────────────────────────────────────────────
# Both providers must return objects with identical attribute sets so the rest
# of the pipeline can treat them uniformly.

def test_both_providers_return_same_response_shape():
    """LLMResponse from Anthropic and Ollama have identical attribute names."""
    anthropic_client = make_anthropic_client()
    mock_anthropic_text(anthropic_client)
    ollama_client = make_ollama_client()

    with patch("llm.ollama_client.requests.post", return_value=mock_ollama_text()):
        ollama_response = ollama_client.chat([{"role": "user", "content": "hi"}])

    anthropic_response = anthropic_client.chat([{"role": "user", "content": "hi"}])

    assert set(vars(anthropic_response).keys()) == set(vars(ollama_response).keys())


def test_both_providers_text_responses_have_same_type():
    """Both providers produce response.type == 'text' for plain replies."""
    anthropic_client = make_anthropic_client()
    mock_anthropic_text(anthropic_client)
    ollama_client = make_ollama_client()

    with patch("llm.ollama_client.requests.post", return_value=mock_ollama_text()):
        ollama_response = ollama_client.chat([{"role": "user", "content": "hi"}])

    anthropic_response = anthropic_client.chat([{"role": "user", "content": "hi"}])

    assert anthropic_response.type == ollama_response.type == "text"


def test_swap_requires_no_agent_code_change():
    """Agent code using only the LLMClient interface works with either provider."""

    def run_agent(llm_client):
        """Minimal agent that calls chat() and reads content — the full interface."""
        response = llm_client.chat([{"role": "user", "content": "hi"}])
        assert isinstance(response, LLMResponse)
        assert response.type == "text"
        return response.content

    anthropic_client = make_anthropic_client()
    mock_anthropic_text(anthropic_client, "same result")
    ollama_client = make_ollama_client()

    with patch("llm.ollama_client.requests.post", return_value=mock_ollama_text("same result")):
        ollama_result = run_agent(ollama_client)

    anthropic_result = run_agent(anthropic_client)

    assert anthropic_result == ollama_result
