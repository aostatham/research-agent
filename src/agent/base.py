"""
Agent and AgentPool abstractions for the multi-agent pipeline.

Agent wraps an LLMClient with identity, persona, system prompt, and tool set.
AgentPool is a typed container of the three pipeline agents (researcher,
verifier, editor).  Both dataclasses are frozen — agents are immutable once built.

See DECISIONS.md D003–D006 for design rationale.
"""

from dataclasses import dataclass
from typing import Optional
from llm.base import LLMClient, LLMResponse


@dataclass(frozen=True)
class Agent:
    """
    Immutable agent unit combining an LLM client with its persona and constraints.

    Attributes:
        name:          Identifier, e.g. "planner", "researcher".
        role:          Human-readable description of what this agent does.
        description:   Used for future dynamic handoff routing.
        llm:           Underlying LLM provider client.
        system_prompt: Passed as the native system parameter on every chat() call.
        tools:         Immutable tuple of tool names available to this agent.
        temperature:   Optional sampling temperature override.
        max_iterations: Per-agent agentic loop budget (not a global limit).
        output_schema: Optional type for validating structured output.
    """

    name: str
    role: str
    description: str
    llm: LLMClient
    system_prompt: str
    # Populated by builder. Read by build_tool_list() in tools.py
    # to construct the tools= argument for LLM calls. Each agent's
    # research/verify/analyse function must call
    # build_tool_list(agent.tools) rather than using ALL_TOOLS or
    # hardcoded tool lists.
    tools: tuple = ()
    temperature: Optional[float] = None
    max_iterations: int = 5
    output_schema: Optional[type] = None

    def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        """
        Delegate to the underlying LLM client, injecting the agent system prompt.

        Args:
            messages: Conversation history as role/content dicts.
            **kwargs: Forwarded to llm.chat() (e.g. max_tokens, tools).

        Returns:
            LLMResponse from the underlying provider.
        """
        kwargs.pop('system', None)
        return self.llm.chat(messages, system=self.system_prompt, **kwargs)


@dataclass(frozen=True)
class AgentPool:
    """
    Typed container for the three pipeline agents.

    Frozen to prevent accidental reassignment after construction.
    Grows by field rather than expanding argument lists — see D005.
    Planner deferred to Phase E — see DECISIONS.md D015.

    Five fields (three required, two optional) is the comfortable
    ceiling for this dataclass. The next optional agent triggers a
    registry review — see DECISIONS.md D005.
    """

    researcher: Agent
    verifier: Agent
    editor: Agent
    graph_verifier: object = None   # Agent | None — populated when knowledge_store != "none"
    analyst: object = None          # Agent | None — Phase E Phase 5
