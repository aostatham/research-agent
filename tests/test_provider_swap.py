import pytest
from unittest.mock import patch, MagicMock
from llm.anthropic_client import AnthropicClient
from llm.ollama_client import OllamaClient
from llm.base import LLMResponse


def make_anthropic_client():
    with patch("llm.anthropic_client.anthropic.Anthropic"):
        return AnthropicClient()


def make_ollama_client():
    return OllamaClient(model="llama3.2")


def mock_anthropic_text(client, text="hello"):
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = text
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    client.client.messages.create.return_value = mock_response


def mock_ollama_text(text="hello"):
    mock_response = MagicMock()
    mock_response.json.return_value = {"message": {"role": "assistant", "content": text}}
    mock_response.raise_for_status = MagicMock()
    return mock_response


# ── Shape tests ───────────────────────────────────────────────────────────────

def test_both_providers_return_same_response_shape():
    anthropic_client = make_anthropic_client()
    mock_anthropic_text(anthropic_client)
    ollama_client = make_ollama_client()

    with patch("llm.ollama_client.requests.post", return_value=mock_ollama_text()):
        ollama_response = ollama_client.chat([{"role": "user", "content": "hi"}])

    anthropic_response = anthropic_client.chat([{"role": "user", "content": "hi"}])

    assert set(vars(anthropic_response).keys()) == set(vars(ollama_response).keys())


def test_both_providers_text_responses_have_same_type():
    anthropic_client = make_anthropic_client()
    mock_anthropic_text(anthropic_client)
    ollama_client = make_ollama_client()

    with patch("llm.ollama_client.requests.post", return_value=mock_ollama_text()):
        ollama_response = ollama_client.chat([{"role": "user", "content": "hi"}])

    anthropic_response = anthropic_client.chat([{"role": "user", "content": "hi"}])

    assert anthropic_response.type == ollama_response.type == "text"


def test_swap_requires_no_agent_code_change():
    """Confirm agent code works identically regardless of provider."""

    def run_agent(llm_client):
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
    