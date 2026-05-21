from abc import ABC, abstractmethod
from typing import Optional


class LLMResponse:
    """Normalised response from any LLM provider."""

    def __init__(self, type: str, content: Optional[str] = None,
                 tool_name: Optional[str] = None, tool_input: Optional[dict] = None,
                 raw: Optional[dict] = None):
        self.type = type          # "text" or "tool_call"
        self.content = content    # populated when type == "text"
        self.tool_name = tool_name    # populated when type == "tool_call"
        self.tool_input = tool_input  # populated when type == "tool_call"
        self.raw = raw            # original provider response, for debugging

    def __repr__(self):
        if self.type == "text":
            return f"LLMResponse(type=text, content={self.content[:80]}...)"
        return f"LLMResponse(type=tool_call, tool={self.tool_name}, input={self.tool_input})"


class LLMClient(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    def chat(self, messages: list, tools: Optional[list] = None) -> LLMResponse:
        """
        Send messages to the LLM and return a normalised response.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."}
            tools:    Optional list of tool definitions in provider-agnostic format

        Returns:
            LLMResponse with type "text" or "tool_call"
        """
        pass