"""
Tests for llm/base.py — LLMResponse and LLMClient abstract base class.

Verifies:
    - LLMResponse stores and exposes all fields correctly for both response types.
    - LLMClient cannot be instantiated directly (it is abstract).
    - Subclasses without chat() also cannot be instantiated.
    - A valid concrete subclass can be instantiated and called.
"""

import pytest
from llm.base import LLMClient, LLMResponse


# ── LLMResponse tests ─────────────────────────────────────────────────────────
# Verify that the normalised response dataclass stores fields as expected for
# both "text" and "tool_call" response types.

def test_text_response_fields():
    """Text responses populate type and content; tool fields remain None."""
    r = LLMResponse(type="text", content="hello")
    assert r.type == "text"
    assert r.content == "hello"
    assert r.tool_name is None
    assert r.tool_input is None


def test_tool_call_response_fields():
    """Tool-call responses populate type, tool_name, and tool_input; content is None."""
    r = LLMResponse(type="tool_call", tool_name="web_search", tool_input={"query": "test"})
    assert r.type == "tool_call"
    assert r.tool_name == "web_search"
    assert r.tool_input == {"query": "test"}
    assert r.content is None


# ── LLMClient abstract class tests ───────────────────────────────────────────
# Verify the ABC enforcement: direct instantiation and incomplete subclasses
# must fail so the interface contract is guaranteed.

def test_cannot_instantiate_base():
    """LLMClient is abstract and must not be instantiatable directly."""
    with pytest.raises(TypeError):
        LLMClient()


def test_subclass_without_chat_raises():
    """A subclass that omits chat() is still abstract and cannot be instantiated."""
    class IncompleteClient(LLMClient):
        pass
    with pytest.raises(TypeError):
        IncompleteClient()


def test_valid_subclass_instantiates():
    """A subclass that implements chat() can be instantiated."""
    class ValidClient(LLMClient):
        def chat(self, messages, tools=None):
            return LLMResponse(type="text", content="ok")
    client = ValidClient()
    assert client is not None


def test_valid_subclass_chat_returns_response():
    """chat() on a valid subclass returns an LLMResponse instance."""
    class ValidClient(LLMClient):
        def chat(self, messages, tools=None):
            return LLMResponse(type="text", content="ok")
    client = ValidClient()
    response = client.chat([{"role": "user", "content": "hello"}])
    assert isinstance(response, LLMResponse)
