import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

# Optional Tavily import — None if not installed
try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None


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


# ── Search provider state ─────────────────────────────────────────────────────

# Configured once at startup via configure_search()
_search_provider = "anthropic"
_tavily_api_key = None
_tavily_max_results = 5


def configure_search(provider: str, tavily_api_key: str = None,
                     tavily_max_results: int = 5):
    """
    Configure the search provider used by execute_tool.
    Called once at startup from main.py.

    Args:
        provider:           "anthropic" or "tavily"
        tavily_api_key:     Required if provider is "tavily"
        tavily_max_results: Number of results to return per Tavily search
    """
    global _search_provider, _tavily_api_key, _tavily_max_results
    _search_provider = provider
    _tavily_api_key = tavily_api_key
    _tavily_max_results = tavily_max_results

    if provider == "tavily" and not tavily_api_key:
        raise ValueError(
            "Tavily API key required. Set TAVILY_API_KEY in .env or "
            "tavily_api_key in config.yaml"
        )


# ── Tool executor ─────────────────────────────────────────────────────────────

def execute_tool(tool_name: str, tool_input: dict) -> str:
    """
    Dispatch a tool call and return the result as a string.
    Uses the search provider configured via configure_search().
    """
    if tool_name == "web_search":
        return _web_search(tool_input["query"])
    raise ValueError(f"Unknown tool: {tool_name}")


def execute_tool_with_sources(tool_name: str, tool_input: dict) -> tuple[str, list[dict]]:
    """
    Dispatch a tool call and return (result_text, sources).
    sources is a list of {"title": str, "url": str} dicts.
    Uses the search provider configured via configure_search().
    """
    if tool_name == "web_search":
        return _web_search_with_sources(tool_input["query"])
    raise ValueError(f"Unknown tool: {tool_name}")


def _web_search(query: str) -> str:
    """Execute a web search using the configured provider, return text only."""
    result, _ = _web_search_with_sources(query)
    return result


def _web_search_with_sources(query: str) -> tuple[str, list[dict]]:
    """
    Execute a web search using the configured provider.
    Routes to Anthropic or Tavily based on _search_provider.
    Returns (result_text, sources) where sources is a list of
    {"title": str, "url": str} dicts.
    """
    if _search_provider == "tavily":
        return _tavily_search_with_sources(query)
    return _anthropic_search_with_sources(query)


# ── Anthropic search ──────────────────────────────────────────────────────────

def _anthropic_search_with_sources(query: str) -> tuple[str, list[dict]]:
    """
    Execute a web search using Anthropic's built-in web search tool.

    Citations are attached to text blocks — each text block may have a
    citations attribute containing CitationsWebSearchResultLocation objects
    with url and title fields. Citations are NOT on tool_result blocks.

    Returns (result_text, sources) where sources is deduplicated by URL.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": f"Search for: {query}"}]
    )

    results = []
    sources = []
    seen_urls = set()

    for block in response.content:
        # Collect text content from text blocks
        if hasattr(block, "text") and block.text:
            results.append(block.text)

        # Extract citations from text blocks (not tool_result blocks)
        if hasattr(block, "citations") and block.citations:
            for citation in block.citations:
                url = getattr(citation, "url", None)
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    sources.append({
                        "title": getattr(citation, "title", url),
                        "url": url
                    })

    result_text = "\n".join(results) if results else "No results found."
    return result_text, sources


# ── Tavily search ─────────────────────────────────────────────────────────────

def _tavily_search_with_sources(query: str) -> tuple[str, list[dict]]:
    """
    Execute a web search using the Tavily API.

    Tavily returns structured results with title, url, and content per result,
    plus an optional synthesised answer. Unlike Anthropic search, citations are
    per-result rather than per-sentence.

    Returns (result_text, sources) in the same normalised format as Anthropic search.
    """
    if TavilyClient is None:
        raise ImportError(
            "tavily-python not installed. Run: pip install tavily-python"
        )

    client = TavilyClient(api_key=_tavily_api_key)

    response = client.search(
        query=query,
        max_results=_tavily_max_results,
        include_answer=True,
        search_depth="advanced"
    )

    sources = []
    seen_urls = set()
    result_parts = []

    # Include Tavily's synthesised answer if available
    if response.get("answer"):
        result_parts.append(response["answer"])

    # Include individual result content and collect sources
    for result in response.get("results", []):
        url = result.get("url", "")
        title = result.get("title", url)
        content = result.get("content", "")

        if content:
            result_parts.append(f"**{title}**\n{content}")

        if url and url not in seen_urls:
            seen_urls.add(url)
            sources.append({"title": title, "url": url})

    result_text = "\n\n".join(result_parts) if result_parts else "No results found."
    return result_text, sources