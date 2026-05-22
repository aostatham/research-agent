"""
Abstract base classes for the LLM layer.

Defines the provider-agnostic interface that all LLM clients must implement.
Every concrete client (AnthropicClient, OllamaClient) returns an LLMResponse,
allowing the rest of the pipeline to treat providers interchangeably.
"""

from abc import ABC, abstractmethod
from typing import Optional


class LLMResponse:
    """
    Normalised response from any LLM provider.

    Wraps either a plain-text reply or a tool-call request in a single
    consistent shape, so orchestrator and synthesiser code never needs to
    branch on provider-specific response formats.

    Attributes:
        type:       "text" for a plain response, "tool_call" when the model
                    wants to invoke a tool.
        content:    The text content; populated when type == "text".
        tool_name:  Name of the tool the model wants to call; populated when
                    type == "tool_call".
        tool_input: Dict of arguments for the tool call; populated when
                    type == "tool_call".
        raw:        The original provider response object, preserved for
                    debugging and logging.
    """

    def __init__(self, type: str, content: Optional[str] = None,
                 tool_name: Optional[str] = None, tool_input: Optional[dict] = None,
                 raw: Optional[dict] = None):
        self.type = type
        self.content = content
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.raw = raw

    def __repr__(self):
        if self.type == "text":
            return f"LLMResponse(type=text, content={self.content[:80]}...)"
        return f"LLMResponse(type=tool_call, tool={self.tool_name}, input={self.tool_input})"


class LLMClient(ABC):
    """
    Abstract base class for all LLM provider clients.

    Subclasses must implement chat() and return an LLMResponse.  The rest of
    the codebase depends only on this interface, enabling provider swaps with
    no changes upstream.
    """

    @abstractmethod
    def chat(self, messages: list, tools: Optional[list] = None, max_tokens: int = 2048) -> LLMResponse:
        """
        Send a conversation to the LLM and return a normalised response.

        Args:
            messages:   List of message dicts, each with "role" ("user" or
                        "assistant") and "content" (string).
            tools:      Optional list of tool definitions in the provider-agnostic
                        format defined in agent/tools.py.  If provided, the model
                        may respond with a tool_call instead of text.
            max_tokens: Maximum number of tokens to generate.

        Returns:
            LLMResponse with type "text" or "tool_call".
        """
        pass
