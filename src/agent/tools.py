"""
Tool definitions and execution layer for the research agent.

Provides a provider-agnostic web_search tool that the orchestrator's agentic
loop can call, and routes actual search execution to the configured backend:

    - "anthropic": Anthropic's built-in web_search_20250305 tool ($0.01/search,
                   always hits the Anthropic API even during Ollama runs).
    - "tavily":    Tavily Search API (1,000 free searches/month, richer content).

The active backend is set once at startup via configure_search(), which stores
it in module-level state.  All subsequent calls to execute_tool* use that state.

Tool definitions use a provider-agnostic format so each LLM client can
translate them to its own schema (Anthropic input_schema vs OpenAI function).
"""

import os
import anthropic
from dotenv import load_dotenv
from llm.retry import with_retry

load_dotenv()

# Optional Tavily import — None if not installed.
# Using try/except avoids a hard dependency: Anthropic-only users don't need
# tavily-python installed.
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

# Passed to LLMClient.chat() to advertise available tools to the model.
ALL_TOOLS = [WEB_SEARCH_TOOL]


# ── Search provider state ─────────────────────────────────────────────────────

# Module-level state set once at startup by configure_search().
# Using module globals rather than a singleton class keeps call sites simple:
# execute_tool_with_sources() needs no context object.
_search_provider = "anthropic"
_tavily_api_key = None
_tavily_max_results = 5
_search_model = "claude-haiku-4-5-20251001"

# Counts every successful call to execute_tool_with_sources() across all agents
# (Researcher and Verifier). Reset and read via get_and_reset_search_count().
# Not thread-safe by language guarantee — relies on CPython GIL for
# single-process CLI use. Move to a threading.Lock before Phase I
# (concurrent request handlers).
_search_call_count: int = 0

# Lazy singleton — created on first Anthropic search call, reused across
# all subsequent calls within the same process to avoid repeated auth overhead.
_anthropic_client = None


def _get_anthropic_client() -> anthropic.Anthropic:
    """Return the module-level Anthropic client, creating it on first call."""
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _anthropic_client


def configure_search(provider: str, tavily_api_key: str = None,
                     tavily_max_results: int = 5,
                     search_model: str = "claude-haiku-4-5-20251001"):
    """
    Configure the search backend used by all execute_tool* calls.

    Called once at startup from main.py before any research begins.
    Writes into module-level globals so all downstream calls automatically
    use the configured provider.

    Args:
        provider:           "anthropic" or "tavily".
        tavily_api_key:     Required when provider is "tavily".  Can also be
                            set via TAVILY_API_KEY environment variable
                            (load_config handles the env fallback).
        tavily_max_results: Number of results to return per Tavily search.
        search_model:       Model used for Anthropic web search calls.
                            Defaults to Haiku; configurable so model
                            deprecations can be handled without code changes.

    Raises:
        ValueError: If provider is "tavily" but no API key is provided.
    """
    if provider == "tavily" and not tavily_api_key:
        raise ValueError(
            "Tavily API key required. Set TAVILY_API_KEY in .env or "
            "tavily_api_key in config.yaml"
        )

    global _search_provider, _tavily_api_key, _tavily_max_results, _search_model
    _search_provider = provider
    _tavily_api_key = tavily_api_key
    _tavily_max_results = tavily_max_results
    _search_model = search_model


# ── Tool executor ─────────────────────────────────────────────────────────────

def execute_tool(tool_name: str, tool_input: dict) -> str:
    """
    Dispatch a tool call and return the result as a plain string.

    Uses the search provider configured via configure_search().
    Sources (citations) are discarded; use execute_tool_with_sources()
    when citation tracking is needed.

    Args:
        tool_name:  Name of the tool to execute (currently only "web_search").
        tool_input: Dict of tool arguments ({"query": "..."}).

    Returns:
        Search result as a plain string.

    Raises:
        ValueError: If tool_name is not recognised.
    """
    if tool_name == "web_search":
        return _web_search(tool_input["query"])
    raise ValueError(f"Unknown tool: {tool_name}")


def get_and_reset_search_count() -> int:
    """
    Return the total number of execute_tool_with_sources() calls since the last
    reset, then reset the counter to zero.

    Called once at the end of Orchestrator.run_async() to capture all searches
    executed across Researcher and Verifier agents during that run.
    """
    global _search_call_count
    count = _search_call_count
    _search_call_count = 0
    return count


def execute_tool_with_sources(tool_name: str, tool_input: dict) -> tuple[str, list[dict]]:
    """
    Dispatch a tool call and return both result text and source citations.

    Increments the module-level _search_call_count on successful dispatch
    only — unknown tool names and malformed inputs do not count. The
    Orchestrator reports the total via get_and_reset_search_count().

    Used by the orchestrator so citations are carried through to the synthesiser
    and formatted into the final report's References section.

    Args:
        tool_name:  Name of the tool to execute (currently only "web_search").
        tool_input: Dict of tool arguments ({"query": "..."}).

    Returns:
        Tuple of (result_text, sources) where sources is a list of
        {"title": str, "url": str} dicts, deduplicated by URL.

    Raises:
        ValueError: If tool_name is not recognised.
    """
    if tool_name == "web_search":
        result = _web_search_with_sources(tool_input["query"])
        global _search_call_count
        _search_call_count += 1
        return result
    raise ValueError(f"Unknown tool: {tool_name}")


def _web_search(query: str) -> str:
    """Execute a web search using the configured provider, return text only."""
    result, _ = _web_search_with_sources(query)
    return result


def _web_search_with_sources(query: str) -> tuple[str, list[dict]]:
    """
    Execute a web search using the configured provider.

    Routes to Anthropic or Tavily based on the _search_provider module global
    set by configure_search().

    Args:
        query: The search query string.

    Returns:
        Tuple of (result_text, sources) where sources is a list of
        {"title": str, "url": str} dicts.
    """
    if _search_provider == "tavily":
        return _tavily_search_with_sources(query)
    return _anthropic_search_with_sources(query)


# ── Anthropic search ──────────────────────────────────────────────────────────

@with_retry(max_attempts=3, base_delay=1.0, max_delay=30.0)
def _anthropic_search_with_sources(query: str) -> tuple[str, list[dict]]:
    """
    Execute a web search using Anthropic's built-in web_search_20250305 tool.

    Always calls the Anthropic API regardless of which LLM provider handles
    orchestration.  Each call costs ~$0.01.

    Citations are attached to *text blocks*, not tool_result blocks.  Each
    text block may have a `citations` attribute containing a list of
    CitationsWebSearchResultLocation objects with `url` and `title` fields.

    Args:
        query: The search query string.

    Returns:
        Tuple of (result_text, sources) where sources is deduplicated by URL.
    """
    client = _get_anthropic_client()

    response = client.messages.create(
        model=_search_model,
        max_tokens=2048,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": f"Search for: {query}"}]
    )

    results = []
    sources = []
    seen_urls = set()  # deduplicate citations that appear across multiple blocks

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

    Tavily returns structured results with title, url, and pre-extracted
    content per result, plus an optional synthesised answer.  Unlike Anthropic
    search, citations are per-result rather than per-sentence.

    Uses search_depth="advanced" for richer content and include_answer=True to
    get Tavily's own synthesis as a lead paragraph in the result text.

    Args:
        query: The search query string.

    Returns:
        Tuple of (result_text, sources) in the same normalised format as
        _anthropic_search_with_sources(), so the orchestrator treats both
        backends identically.

    Raises:
        ImportError: If tavily-python is not installed.
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

    # Include Tavily's synthesised answer as the lead paragraph if available
    if response.get("answer"):
        result_parts.append(response["answer"])

    # Append each result's extracted content and record its URL as a source
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
