import pytest
from dotenv import load_dotenv

load_dotenv()


# ── Anthropic smoke tests ─────────────────────────────────────────────────────

@pytest.mark.integration
def test_anthropic_basic_chat():
    from llm import AnthropicClient
    client = AnthropicClient()
    response = client.chat([{"role": "user", "content": "Reply with exactly two words."}])
    assert response.type == "text"
    assert len(response.content) > 0


@pytest.mark.integration
def test_anthropic_tool_call():
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
    from agent.tools import execute_tool
    result = execute_tool("web_search", {"query": "nuclear fusion 2026"})
    assert isinstance(result, str)
    assert len(result) > 100


# ── Ollama smoke tests ────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.ollama
def test_ollama_basic_chat():
    from llm import OllamaClient
    client = OllamaClient(model="llama3.2")
    response = client.chat([{"role": "user", "content": "Reply with exactly two words."}])
    assert response.type == "text"
    assert len(response.content) > 0


@pytest.mark.integration
@pytest.mark.ollama
def test_ollama_tool_call():
    from llm import OllamaClient
    from agent.tools import ALL_TOOLS
    client = OllamaClient(model="llama3.2")
    response = client.chat(
        messages=[{"role": "user", "content": "Search for the latest news on nuclear fusion."}],
        tools=ALL_TOOLS
    )
    assert response.type == "tool_call"
    assert response.tool_name == "web_search"
    assert "query" in response.tool_input


# ── Provider parity smoke test ────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.ollama
def test_both_providers_respond_to_same_prompt():
    from llm import AnthropicClient, OllamaClient
    prompt = [{"role": "user", "content": "In one sentence, what is nuclear fusion?"}]

    anthropic_response = AnthropicClient().chat(prompt)
    ollama_response = OllamaClient(model="llama3.2").chat(prompt)

    assert anthropic_response.type == "text"
    assert ollama_response.type == "text"
    assert len(anthropic_response.content) > 0
    assert len(ollama_response.content) > 0
    