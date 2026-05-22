"""
Ollama local inference client implementation.

Wraps the Ollama REST API behind the LLMClient interface.  Handles
tool-format conversion (agnostic → OpenAI-compatible function format, which
Ollama uses) and response normalisation (Ollama JSON → LLMResponse).

Ollama must be running locally (`ollama serve`) for this client to work.
Connection failures surface as a descriptive ConnectionError rather than a
raw requests exception.

Retries are applied automatically via the @with_retry decorator for
transient HTTP errors.
"""

import requests
from .base import LLMClient, LLMResponse
from .retry import with_retry


class OllamaClient(LLMClient):
    """
    LLMClient implementation for the Ollama local inference server.

    Sends requests to Ollama's /api/chat endpoint with streaming disabled.
    Tool calls use OpenAI-compatible function format, which Ollama supports
    natively for models like llama3.1 and llama3.2.

    Note: web searches always hit the Anthropic API regardless of which LLM
    client is used for orchestration (see agent/tools.py).  Using OllamaClient
    does not mean fully local operation when web search is enabled.
    """

    DEFAULT_MODEL = "llama3.1"
    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL):
        """
        Initialise the Ollama client.

        Args:
            model:    Ollama model name (e.g. "llama3.1", "llama3.2").
                      The model must already be pulled locally.
            base_url: Base URL of the Ollama server.  Trailing slashes are
                      stripped to avoid double-slash in request URLs.
        """
        self.model = model
        self.base_url = base_url.rstrip("/")

    @with_retry(max_attempts=3, base_delay=1.0, max_delay=30.0)
    def chat(self, messages: list, tools: list = None, max_tokens: int = 2048) -> LLMResponse:
        """
        Send a conversation to the Ollama /api/chat endpoint.

        Args:
            messages:   List of {"role": "user"|"assistant", "content": str} dicts.
            tools:      Optional list of provider-agnostic tool definitions.
                        Converted to OpenAI function format via _convert_tools().
            max_tokens: Maximum tokens to generate, passed as num_predict in
                        the Ollama options block.

        Returns:
            LLMResponse with type "tool_call" if the model chose a tool,
            or "text" for a plain reply.

        Raises:
            ConnectionError: If the Ollama server is not reachable.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,             # disable streaming; we want a single JSON response
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
            # Convert the low-level requests error into a more actionable message.
            raise ConnectionError(
                f"Could not connect to Ollama at {self.base_url}. "
                "Is Ollama running? Try: ollama serve"
            )

        return self._normalise(response.json())

    def _convert_tools(self, tools: list) -> list:
        """
        Convert agnostic tool definitions to OpenAI-compatible function format.

        Ollama uses the same tool schema as OpenAI: each tool is wrapped in a
        {"type": "function", "function": {...}} envelope, with "parameters"
        (not "input_schema") as the JSON schema key.

        Args:
            tools: List of tool dicts in provider-agnostic format
                   (name, description, parameters).

        Returns:
            List of tool dicts in OpenAI/Ollama function-call format.
        """
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
        """
        Convert an Ollama JSON response dict to a normalised LLMResponse.

        Ollama returns tool calls in message.tool_calls as a list of
        {"function": {"name": ..., "arguments": ...}} objects.  Only the
        first tool call is processed (the agent loop will handle subsequent
        calls in future iterations).

        Args:
            response: Parsed JSON dict from the Ollama /api/chat response.

        Returns:
            LLMResponse with type "tool_call" if tool_calls is non-empty,
            otherwise type "text" using message.content.
        """
        message = response.get("message", {})
        tool_calls = message.get("tool_calls", [])
        if tool_calls:
            # Take only the first tool call; the loop handles multiple rounds.
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
