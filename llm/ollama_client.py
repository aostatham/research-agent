import requests
from .base import LLMClient, LLMResponse
from .retry import with_retry


class OllamaClient(LLMClient):

    DEFAULT_MODEL = "llama3.1"
    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL):
        self.model = model
        self.base_url = base_url.rstrip("/")

    @with_retry(max_attempts=3, base_delay=1.0, max_delay=30.0)
    def chat(self, messages: list, tools: list = None, max_tokens: int = 2048) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": max_tokens}
        }
        if tools:
            payload["tools"] = self._convert_tools(tools)

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=60
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise ConnectionError(
                f"Could not connect to Ollama at {self.base_url}. "
                "Is Ollama running? Try: ollama serve"
            )

        return self._normalise(response.json())

    def _convert_tools(self, tools: list) -> list:
        """Convert agnostic tool format to OpenAI-compatible format."""
        converted = []
        for tool in tools:
            converted.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"]
                }
            })
        return converted

    def _normalise(self, response: dict) -> LLMResponse:
        """Convert Ollama response to normalised LLMResponse."""
        message = response.get("message", {})
        tool_calls = message.get("tool_calls", [])
        if tool_calls:
            call = tool_calls[0]["function"]
            return LLMResponse(
                type="tool_call",
                tool_name=call["name"],
                tool_input=call["arguments"],
                raw=response
            )
        return LLMResponse(
            type="text",
            content=message.get("content", ""),
            raw=response
        )