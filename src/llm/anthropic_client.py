import os
import anthropic
from dotenv import load_dotenv
from .base import LLMClient, LLMResponse
from .retry import with_retry

load_dotenv()


class AnthropicClient(LLMClient):

    DEFAULT_MODEL = "claude-haiku-4-5-20251001"

    def __init__(self, model: str = DEFAULT_MODEL):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set in .env")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    @with_retry(max_attempts=3, base_delay=1.0, max_delay=30.0)
    def chat(self, messages: list, tools: list = None, max_tokens: int = 2048) -> LLMResponse:
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        response = self.client.messages.create(**kwargs)
        return self._normalise(response)

    def _convert_tools(self, tools: list) -> list:
        """Convert agnostic tool format to Anthropic format."""
        converted = []
        for tool in tools:
            converted.append({
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["parameters"]
            })
        return converted

    def _normalise(self, response) -> LLMResponse:
        """Convert Anthropic response to normalised LLMResponse."""
        for block in response.content:
            if block.type == "tool_use":
                return LLMResponse(
                    type="tool_call",
                    tool_name=block.name,
                    tool_input=block.input,
                    raw=response
                )
        text = next((b.text for b in response.content if b.type == "text"), "")
        return LLMResponse(type="text", content=text, raw=response)