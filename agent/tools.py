import os
import anthropic
from dotenv import load_dotenv

load_dotenv()


# ── Tool definitions (provider-agnostic format) ───────────────────────────────

WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": "Search the web for current information on a topic or question.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to look up"
            }
        },
        "required": ["query"]
    }
}

ALL_TOOLS = [WEB_SEARCH_TOOL]


# ── Tool executor ─────────────────────────────────────────────────────────────

def execute_tool(tool_name: str, tool_input: dict) -> str:
    """
    Dispatch a tool call and return the result as a string.
    Add new tools here as the project grows.
    """
    if tool_name == "web_search":
        return _web_search(tool_input["query"])

    raise ValueError(f"Unknown tool: {tool_name}")


def _web_search(query: str) -> str:
    """
    Execute a web search using Anthropic's built-in web search tool.
    Returns the search results as a formatted string.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": f"Search for: {query}"}]
    )

    # Extract text content from response
    results = []
    for block in response.content:
        if hasattr(block, "text"):
            results.append(block.text)

    return "\n".join(results) if results else "No results found."