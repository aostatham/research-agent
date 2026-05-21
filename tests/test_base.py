import pytest
from llm.base import LLMClient, LLMResponse


# ── LLMResponse tests ─────────────────────────────────────────────────────────

def test_text_response_fields():
    r = LLMResponse(type="text", content="hello")
    assert r.type == "text"
    assert r.content == "hello"
    assert r.tool_name is None
    assert r.tool_input is None


def test_tool_call_response_fields():
    r = LLMResponse(type="tool_call", tool_name="web_search", tool_input={"query": "test"})
    assert r.type == "tool_call"
    assert r.tool_name == "web_search"
    assert r.tool_input == {"query": "test"}
    assert r.content is None


# ── LLMClient abstract class tests ───────────────────────────────────────────

def test_cannot_instantiate_base():
    with pytest.raises(TypeError):
        LLMClient()


def test_subclass_without_chat_raises():
    class IncompleteClient(LLMClient):
        pass
    with pytest.raises(TypeError):
        IncompleteClient()


def test_valid_subclass_instantiates():
    class ValidClient(LLMClient):
        def chat(self, messages, tools=None):
            return LLMResponse(type="text", content="ok")
    client = ValidClient()
    assert client is not None


def test_valid_subclass_chat_returns_response():
    class ValidClient(LLMClient):
        def chat(self, messages, tools=None):
            return LLMResponse(type="text", content="ok")
    client = ValidClient()
    response = client.chat([{"role": "user", "content": "hello"}])
    assert isinstance(response, LLMResponse)
    