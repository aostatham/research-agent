"""
Anthropic API client implementation.

Wraps the Anthropic Python SDK behind the LLMClient interface.  Handles
tool-format conversion (agnostic → Anthropic input_schema format) and
response normalisation (Anthropic SDK objects → LLMResponse).

Retries are applied automatically via the @with_retry decorator for
transient API errors (rate limits, server errors).
"""

import os
from typing import Optional
import anthropic
from dotenv import load_dotenv
from .base import LLMClient, LLMResponse
from .retry import with_retry

load_dotenv()


class AnthropicClient(LLMClient):
    """
    LLMClient implementation for the Anthropic Messages API.

    Uses model tiering by default: orchestration callers pass
    claude-haiku-4-5-20251001 (fast, cheap) while synthesis callers pass
    claude-sonnet-4-6 (higher quality).  The model is set at construction
    time and applied to every call.
    """

    DEFAULT_MODEL = "claude-haiku-4-5-20251001"

    def __init__(self, model: str = DEFAULT_MODEL):
        """
        Initialise the Anthropic client.

        Args:
            model: Anthropic model ID to use for all requests from this
                   client instance.

        Raises:
            ValueError: If ANTHROPIC_API_KEY is not set in the environment.
        """
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set in .env")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    @with_retry(max_attempts=3, base_delay=1.0, max_delay=30.0)
    def chat(self, messages: list, tools: list = None, max_tokens: int = 2048,
             system: Optional[str] = None) -> LLMResponse:
        """
        Send a conversation to the Anthropic Messages API.

        Converts the provider-agnostic tool format to Anthropic's
        input_schema format before sending, then normalises the response.

        Args:
            messages:   List of {"role": "user"|"assistant", "content": str} dicts.
            tools:      Optional list of provider-agnostic tool definitions.
                        Converted to Anthropic format via _convert_tools().
            max_tokens: Maximum tokens to generate.
            system:     Optional system prompt passed as the top-level system=
                        parameter to the Anthropic API (not in the messages list —
                        Anthropic ignores role:system inside messages).

        Returns:
            LLMResponse with type "tool_call" if the model chose a tool,
            or "text" for a plain reply.
        """
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = self._convert_tools(tools)
        if system is not None:
            kwargs["system"] = system

        response = self.client.messages.create(**kwargs)
        return self._normalise(response)

    def _convert_tools(self, tools: list) -> list:
        """
        Convert agnostic tool definitions to Anthropic API format.

        The agnostic format uses "parameters" as the JSON schema key.
        Anthropic expects the same schema under "input_schema" instead.

        Args:
            tools: List of tool dicts in provider-agnostic format
                   (name, description, parameters).

        Returns:
            List of tool dicts in Anthropic format
            (name, description, input_schema).
        """
        converted = []
        for tool in tools:
            converted.append({
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["parameters"],  # Anthropic uses input_schema, not parameters
            })
        return converted

    def _normalise(self, response) -> LLMResponse:
        """
        Convert an Anthropic SDK response object to a normalised LLMResponse.

        Anthropic can return multiple content blocks; a tool_use block takes
        priority over any text blocks, matching the model's intended action.

        Args:
            response: Raw anthropic.types.Message object from the SDK.

        Returns:
            LLMResponse with type "tool_call" if a tool_use block is present,
            otherwise type "text" using the first text block's content.
        """
        # A tool_use block means the model wants to call a tool — return that first.
        for block in response.content:
            if block.type == "tool_use":
                return LLMResponse(
                    type="tool_call",
                    tool_name=block.name,
                    tool_input=block.input,
                    raw=response
                )
        # No tool call — extract the first text block's content.
        text = next((b.text for b in response.content if b.type == "text"), "")
        return LLMResponse(type="text", content=text, raw=response)
