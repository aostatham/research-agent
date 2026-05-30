"""
Tests for agent/base.py — Agent and AgentPool dataclasses.

Verifies:
  - Agent is frozen (FrozenInstanceError on field assignment)
  - Agent.chat() calls llm.chat() with system=self.system_prompt
  - Agent.chat() passes additional kwargs through to llm.chat()
  - Agent.chat() returns the LLMResponse from llm.chat()
  - AgentPool is frozen (FrozenInstanceError on field assignment)
  - AgentPool has exactly three fields: researcher, verifier, editor
  - AgentPool fields return the correct agent instances

All tests use a mock LLMClient — no real API calls.
"""

import dataclasses
import pytest
from unittest.mock import MagicMock
from agent.base import Agent, AgentPool
from llm.base import LLMResponse


def make_mock_llm(content="response text"):
    """Return a mock LLMClient whose chat() returns a text LLMResponse."""
    mock = MagicMock()
    mock.chat.return_value = LLMResponse(type="text", content=content)
    return mock


def make_agent(llm=None, system_prompt="system prompt"):
    """Construct an Agent with default field values for testing."""
    return Agent(
        name="test",
        role="test role",
        description="test description",
        llm=llm or make_mock_llm(),
        system_prompt=system_prompt,
    )


# ── Agent frozen behaviour ────────────────────────────────────────────────────

def test_agent_is_frozen():
    """Assigning to any Agent field raises FrozenInstanceError."""
    agent = make_agent()
    with pytest.raises(dataclasses.FrozenInstanceError):
        agent.name = "changed"


def test_agent_tools_defaults_to_empty_tuple():
    agent = make_agent()
    assert agent.tools == ()


def test_agent_temperature_defaults_to_none():
    agent = make_agent()
    assert agent.temperature is None


def test_agent_max_iterations_defaults_to_five():
    agent = make_agent()
    assert agent.max_iterations == 5


def test_agent_output_schema_defaults_to_none():
    agent = make_agent()
    assert agent.output_schema is None


def test_agent_tool_descriptors_defaults_to_empty_tuple():
    """tool_descriptors defaults to () when not provided."""
    agent = make_agent()
    assert agent.tool_descriptors == ()


def test_agent_can_be_constructed_with_tool_descriptors():
    """Agent accepts a non-empty tool_descriptors tuple at construction."""
    descriptor = {"name": "web_search", "description": "Search the web"}
    agent = Agent(
        name="test",
        role="test role",
        description="test description",
        llm=make_mock_llm(),
        system_prompt="system prompt",
        tool_descriptors=(descriptor,),
    )
    assert agent.tool_descriptors == (descriptor,)


def test_agent_tool_descriptors_is_tuple():
    """tool_descriptors field is a tuple, not a list."""
    descriptor = {"name": "web_search", "description": "Search the web"}
    agent = Agent(
        name="test",
        role="test role",
        description="test description",
        llm=make_mock_llm(),
        system_prompt="system prompt",
        tool_descriptors=(descriptor,),
    )
    assert isinstance(agent.tool_descriptors, tuple)


# ── Agent.chat() delegation ───────────────────────────────────────────────────

def test_agent_chat_calls_llm_with_system_prompt():
    """chat() must forward system=self.system_prompt to llm.chat()."""
    llm = make_mock_llm()
    agent = make_agent(llm=llm, system_prompt="be precise")
    messages = [{"role": "user", "content": "hello"}]
    agent.chat(messages)
    llm.chat.assert_called_once_with(messages, system="be precise")


def test_agent_chat_passes_kwargs_to_llm():
    """Additional kwargs must be forwarded to llm.chat() unchanged."""
    llm = make_mock_llm()
    agent = make_agent(llm=llm)
    messages = [{"role": "user", "content": "hi"}]
    agent.chat(messages, max_tokens=4096, tools=["web_search"])
    llm.chat.assert_called_once_with(
        messages, system="system prompt", max_tokens=4096, tools=["web_search"]
    )


def test_agent_chat_returns_llm_response():
    """chat() must return the LLMResponse produced by llm.chat()."""
    llm = make_mock_llm(content="the answer")
    agent = make_agent(llm=llm)
    result = agent.chat([{"role": "user", "content": "question"}])
    assert isinstance(result, LLMResponse)
    assert result.content == "the answer"


def test_agent_chat_uses_own_system_prompt_not_kwarg():
    """system= from system_prompt field takes precedence — not overridable via kwargs."""
    llm = make_mock_llm()
    agent = make_agent(llm=llm, system_prompt="original prompt")
    agent.chat([{"role": "user", "content": "q"}])
    call_kwargs = llm.chat.call_args.kwargs
    assert call_kwargs["system"] == "original prompt"


def test_agent_chat_caller_system_kwarg_does_not_raise():
    """Passing system= explicitly does not raise TypeError; agent system_prompt is used."""
    llm = make_mock_llm()
    agent = make_agent(llm=llm, system_prompt="original prompt")
    agent.chat([{"role": "user", "content": "q"}], system="override attempt")
    call_kwargs = llm.chat.call_args.kwargs
    assert call_kwargs["system"] == "original prompt"


# ── AgentPool frozen behaviour ────────────────────────────────────────────────

def _make_pool():
    """Build an AgentPool with three distinct mock agents."""
    researcher = Agent("researcher", "researches", "researcher desc", make_mock_llm(), "research prompt")
    verifier = Agent("verifier", "verifies", "verifier desc", make_mock_llm(), "verify prompt")
    editor = Agent("editor", "edits", "editor desc", make_mock_llm(), "edit prompt")
    return AgentPool(researcher=researcher, verifier=verifier, editor=editor)


def test_agentpool_is_frozen():
    """Assigning to any AgentPool field raises FrozenInstanceError."""
    pool = _make_pool()
    with pytest.raises(dataclasses.FrozenInstanceError):
        pool.researcher = pool.researcher


def test_agentpool_does_not_have_planner_field():
    """AgentPool has no planner field — planner deferred to Phase E (D015)."""
    pool = _make_pool()
    assert not hasattr(pool, "planner")


def test_agentpool_three_fields_only():
    """Constructing AgentPool with a planner kwarg raises TypeError."""
    researcher = Agent("researcher", "r", "d", make_mock_llm(), "p")
    verifier = Agent("verifier", "r", "d", make_mock_llm(), "p")
    editor = Agent("editor", "r", "d", make_mock_llm(), "p")
    with pytest.raises(TypeError):
        AgentPool(planner=researcher, researcher=researcher, verifier=verifier, editor=editor)


def test_agentpool_researcher_field():
    pool = _make_pool()
    assert pool.researcher.name == "researcher"


def test_agentpool_verifier_field():
    pool = _make_pool()
    assert pool.verifier.name == "verifier"


def test_agentpool_editor_field():
    pool = _make_pool()
    assert pool.editor.name == "editor"


def test_agentpool_fields_are_same_instances():
    """Field access must return the exact Agent instances passed at construction."""
    researcher = Agent("researcher", "r", "d", make_mock_llm(), "p")
    verifier = Agent("verifier", "r", "d", make_mock_llm(), "p")
    editor = Agent("editor", "r", "d", make_mock_llm(), "p")
    pool = AgentPool(researcher=researcher, verifier=verifier, editor=editor)
    assert pool.researcher is researcher
    assert pool.verifier is verifier
    assert pool.editor is editor
