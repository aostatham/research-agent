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

import json
import logging
import os
import urllib.parse
import urllib.robotparser
import anthropic
import requests
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

# Optional trafilatura import — falls back to bleach on raw HTML when unavailable.
try:
    import trafilatura as _trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    _trafilatura = None  # type: ignore[assignment]
    TRAFILATURA_AVAILABLE = False


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

# Descriptors for knowledge-graph tools, keyed by tool name.
KG_TOOL_DESCRIPTORS = {
    "kg_query_claims_for_topic": {
        "name": "kg_query_claims_for_topic",
        "description": "Query the knowledge graph for claims related to a topic.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "The research topic to query"},
            },
            "required": ["topic"],
        },
    },
    "kg_check_contradiction": {
        "name": "kg_check_contradiction",
        "description": "Check for contradicting claims in the knowledge graph.",
        "parameters": {
            "type": "object",
            "properties": {
                "claim": {"type": "string", "description": "The claim text to check"},
                "topic": {"type": "string", "description": "The topic context"},
            },
            "required": ["claim", "topic"],
        },
    },
    # Reserved — no agent currently has this tool in its tools tuple.
    # Re-enable on Analyst once string-input handling from Ollama is
    # confirmed (Phase E QA Pass 2 M2).
    "kg_write_claim": {
        "name": "kg_write_claim",
        "description": "Write a verified claim to the knowledge graph.",
        "parameters": {
            "type": "object",
            "properties": {
                "claim_dict": {
                    "type": "object",
                    "description": "Claim dict with keys: claim (str), confidence (float), verification_status (str), sources (list)",
                },
            },
            "required": ["claim_dict"],
        },
    },
}


ARXIV_TOOL_DESCRIPTORS = {
    "arxiv_search": {
        "name": "arxiv_search",
        "description": (
            "Search arXiv for academic papers. "
            "Returns up to 5 results with title, authors, abstract, "
            "arXiv ID, categories, and URL. "
            "Use for finding peer-reviewed research on a topic."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for arXiv papers",
                }
            },
            "required": ["query"],
        },
    },
}

URL_TOOL_DESCRIPTORS = {
    "read_url": {
        "name": "read_url",
        "description": (
            "Fetch and extract the text content of a web page. "
            "Returns structured JSON with title, author, published_date, and cleaned text. "
            "Use to read a specific URL found in search results. "
            "Read at most one URL per research iteration."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The full URL to fetch",
                }
            },
            "required": ["url"],
        },
    },
}

def build_tool_list(tool_names: tuple) -> list:
    """
    Build the list of tool descriptors for an agent LLM call.

    Each agent's research/verify/analyse function must call this with
    agent.tools rather than using the module-level ALL_TOOLS constant,
    so each agent receives exactly the tools assigned to it by the builder.

    Args:
        tool_names: Tuple of tool name strings from Agent.tools.

    Returns:
        List of tool descriptor dicts.

    Raises:
        ValueError: If any tool name is not recognised. This is a startup
                    failure — descriptor skew (e.g. adding a tool to Agent.tools
                    without a matching KG_TOOL_DESCRIPTORS entry) is caught at
                    build time rather than silently omitted at LLM call time.
    """
    _all_descriptors = {
        **KG_TOOL_DESCRIPTORS,
        **URL_TOOL_DESCRIPTORS,
        **ARXIV_TOOL_DESCRIPTORS,
    }
    known = {"web_search"} | set(_all_descriptors)
    unknown = [t for t in tool_names if t not in known]
    if unknown:
        raise ValueError(
            f"Unknown tool names in Agent.tools: {unknown}. "
            f"Add descriptors to KG_TOOL_DESCRIPTORS, URL_TOOL_DESCRIPTORS, "
            f"or ARXIV_TOOL_DESCRIPTORS in tools.py."
        )
    result = []
    for name in tool_names:
        if name == "web_search":
            result.append(WEB_SEARCH_TOOL)
        elif name in _all_descriptors:
            result.append(_all_descriptors[name])
    return result


# ── Search provider state ─────────────────────────────────────────────────────

# Module-level state set once at startup by configure_search().
# Using module globals rather than a singleton class keeps call sites simple:
# execute_tool_with_sources() needs no context object.
_search_provider = "anthropic"
# Staleness threshold for kg_check_contradiction — cached from config at startup
# by configure_knowledge() so the tool never instantiates a fresh Config().
_staleness_days: int = 90
_tavily_api_key = None
_tavily_max_results = 5
_search_model = "claude-haiku-4-5-20251001"
# read_url settings — cached at startup so _fetch_url never reads Config().
_max_url_chars: int = 8000
_url_fetch_timeout: int = 10
# Per-domain robots.txt cache — populated lazily by _fetch_url().
_robots_cache: dict = {}

# Counts every successful call to execute_tool_with_sources() across all agents
# (Researcher and Verifier). Reset and read via get_and_reset_search_count().
# Not thread-safe by language guarantee — relies on CPython GIL for
# single-process CLI use. Two concurrent Orchestrator.run_async calls
# in the same process will actively corrupt each other's counts — the
# second call's reset-at-start discards the first call's accumulated
# count. Fix for Phase I: use contextvars.ContextVar for per-request
# isolation, not threading.Lock (async tasks share a thread and would
# serialise on a Lock). threading.Lock also works if Phase I uses a
# thread-per-worker or process-per-worker model rather than
# async-in-one-thread. See I003 in ISSUES.md.
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
                     search_model: str = "claude-haiku-4-5-20251001",
                     max_url_chars: int = 8000,
                     url_fetch_timeout_seconds: int = 10):
    """
    Configure the search backend used by all execute_tool* calls.

    Called once at startup from main.py before any research begins.
    Writes into module-level globals so all downstream calls automatically
    use the configured provider.

    Args:
        provider:                  "anthropic" or "tavily".
        tavily_api_key:            Required when provider is "tavily".  Can also be
                                   set via TAVILY_API_KEY environment variable.
        tavily_max_results:        Number of results to return per Tavily search.
        search_model:              Model used for Anthropic web search calls.
        max_url_chars:             Max characters returned per read_url call.
        url_fetch_timeout_seconds: HTTP fetch timeout in seconds for read_url.

    Raises:
        ValueError: If provider is "tavily" but no API key is provided.
    """
    if provider == "tavily" and not tavily_api_key:
        raise ValueError(
            "Tavily API key required. Set TAVILY_API_KEY in .env or "
            "tavily_api_key in config.yaml"
        )

    global _search_provider, _tavily_api_key, _tavily_max_results, _search_model
    global _max_url_chars, _url_fetch_timeout
    _search_provider = provider
    _tavily_api_key = tavily_api_key
    _tavily_max_results = tavily_max_results
    _search_model = search_model
    _max_url_chars = max_url_chars
    _url_fetch_timeout = url_fetch_timeout_seconds


def configure_knowledge(config) -> None:
    """
    Configure the knowledge store and cache user settings for kg_ tools.

    Called once at startup from main.py. Caches knowledge_staleness_threshold_days
    from config so kg_check_contradiction() never has to instantiate a fresh Config.
    Delegates to knowledge.store.configure_knowledge() for store initialisation.

    Args:
        config: Config instance with knowledge_store, knowledge_db_path, and
                knowledge_staleness_threshold_days fields.
    """
    global _staleness_days
    _staleness_days = getattr(config, "knowledge_staleness_threshold_days", 90)
    from knowledge.store import configure_knowledge as _ks_configure
    _ks_configure(config)


# ── arXiv search ──────────────────────────────────────────────────────────────

_ARXIV_NS = "http://www.w3.org/2005/Atom"
_ARXIV_API_NS = "http://arxiv.org/schemas/atom"
_ARXIV_QUERY_URL = "http://export.arxiv.org/api/query"


def _arxiv_search(query: str, max_results: int = 5,
                  sort_by_date: bool = False) -> list:
    """
    Search arXiv via the public Atom API and return structured results.

    Uses the standard library xml.etree.ElementTree — no new dependency.
    Up to 5 authors are listed; papers with more show the first 5 followed
    by "et al.".

    Args:
        query:        Search query string.
        max_results:  Maximum number of results (default 5).
        sort_by_date: If True, sort by submittedDate; otherwise by relevance.

    Returns:
        List of dicts with keys: arxiv_id, title, authors, abstract,
        published, url, categories.  Empty list on any error.
    """
    import xml.etree.ElementTree as ET

    sort_by = "submittedDate" if sort_by_date else "relevance"
    params = (
        f"search_query={urllib.parse.quote(query)}"
        f"&max_results={max_results}"
        f"&sortBy={sort_by}"
        f"&sortOrder=descending"
    )
    url = f"{_ARXIV_QUERY_URL}?{params}"

    try:
        response = requests.get(url, timeout=15,
                                headers={"User-Agent": _USER_AGENT})
        response.raise_for_status()
        root = ET.fromstring(response.text)
    except Exception as e:
        logging.warning("arxiv_search failed: %s", e)
        return []

    results = []
    for entry in root.findall(f"{{{_ARXIV_NS}}}entry"):
        # arxiv_id from the <id> element URL, strip version suffix.
        id_elem = entry.find(f"{{{_ARXIV_NS}}}id")
        raw_id = id_elem.text.strip() if id_elem is not None else ""
        # e.g. "http://arxiv.org/abs/2407.04363v1" → "2407.04363"
        arxiv_id = raw_id.split("/abs/")[-1].split("v")[0] if "/abs/" in raw_id else raw_id

        title_elem = entry.find(f"{{{_ARXIV_NS}}}title")
        title = " ".join((title_elem.text or "").split()) if title_elem is not None else ""

        author_elems = entry.findall(f"{{{_ARXIV_NS}}}author")
        author_names = []
        for a in author_elems:
            name_elem = a.find(f"{{{_ARXIV_NS}}}name")
            if name_elem is not None and name_elem.text:
                author_names.append(name_elem.text.strip())
        if len(author_names) > 5:
            authors = author_names[:5] + ["et al."]
        else:
            authors = author_names

        abstract_elem = entry.find(f"{{{_ARXIV_NS}}}summary")
        abstract = " ".join((abstract_elem.text or "").split()) if abstract_elem is not None else ""

        published_elem = entry.find(f"{{{_ARXIV_NS}}}published")
        published = ""
        if published_elem is not None and published_elem.text:
            published = published_elem.text.strip()[:10]  # YYYY-MM-DD

        categories = []
        primary = entry.find(f"{{{_ARXIV_API_NS}}}primary_category")
        if primary is not None:
            term = primary.get("term", "")
            if term:
                categories.append(term)
        for cat in entry.findall(f"{{{_ARXIV_NS}}}category"):
            term = cat.get("term", "")
            if term and term not in categories:
                categories.append(term)

        results.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "published": published,
            "url": f"https://arxiv.org/abs/{arxiv_id}",
            "categories": categories,
        })

    return results


def arxiv_search(query: str) -> str:
    """
    Search arXiv for academic papers, returning structured JSON.

    Never raises — any exception is caught and returns an empty JSON array.

    Args:
        query: Search query string.

    Returns:
        JSON string of a list of result dicts.
    """
    try:
        results = _arxiv_search(query)
    except Exception as e:
        logging.warning("arxiv_search wrapper failed: %s", e)
        results = []
    return json.dumps(results)


# ── URL fetch ─────────────────────────────────────────────────────────────────

_USER_AGENT = "research-agent/0.1 (+https://github.com/aostatham/research-agent)"
_BLEACH_PROSE_TAGS = ["p", "h1", "h2", "h3", "h4", "li", "td", "th"]


def _fetch_url(url: str, max_chars: int, timeout_seconds: int) -> dict:
    """
    Fetch and extract the text content of a URL.

    Steps:
      1. Validate URL scheme (http/https only).
      2. Check robots.txt for the domain (cached per domain; fail open on error).
      3. Fetch via requests.get with User-Agent and timeout.
      4. Extract content via trafilatura; fall back to bleach on None/exception.
      5. Truncate to max_chars and return a structured dict.

    Args:
        url:             The full URL to fetch.
        max_chars:       Maximum characters to return in the text field.
        timeout_seconds: HTTP request timeout in seconds.

    Returns:
        Dict with keys: url, title, author, published_date, text, truncated.
        On any pre-fetch failure: dict with a single "error" key.
    """
    # Step 1 — validate scheme.
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {"error": "invalid URL scheme — only http and https permitted"}

    # Step 2 — robots.txt check (fail open on any fetch/parse error).
    domain = f"{parsed.scheme}://{parsed.netloc}"
    if domain not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{domain}/robots.txt")
        try:
            rp.read()
            _robots_cache[domain] = rp
        except Exception:
            _robots_cache[domain] = None  # None = allow (fail open)

    robot = _robots_cache[domain]
    if robot is not None and not robot.can_fetch("research-agent", url):
        return {"error": "fetch disallowed by robots.txt for this domain"}

    # Step 3 — fetch the page.
    try:
        response = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout_seconds,
        )
    except requests.exceptions.Timeout:
        return {"error": f"fetch timed out after {timeout_seconds}s"}
    except (requests.exceptions.ConnectionError,
            requests.exceptions.RequestException) as e:
        return {"error": f"fetch failed: {type(e).__name__}: {e}"}

    if response.status_code >= 400:
        return {"error": f"HTTP {response.status_code} from {url}"}

    # Step 4 — extract content.
    title = author = published_date = None
    text = ""
    use_fallback = False

    if TRAFILATURA_AVAILABLE:
        try:
            raw = _trafilatura.extract(
                response.text,
                include_metadata=True,
                include_tables=True,
                output_format="json",
            )
            if raw:
                data = json.loads(raw)
                title = data.get("title")
                author = data.get("author")
                published_date = data.get("date")
                text = data.get("text", "") or ""
            else:
                use_fallback = True
        except Exception:
            use_fallback = True
    else:
        use_fallback = True

    if use_fallback:
        try:
            import bleach as _bleach
            text = _bleach.clean(
                response.text,
                tags=_BLEACH_PROSE_TAGS,
                strip=True,
            )
        except Exception:
            text = response.text

    # Step 5 — truncate and return.
    truncated = len(text) > max_chars
    return {
        "url": url,
        "title": title,
        "author": author,
        "published_date": published_date,
        "text": text[:max_chars],
        "truncated": truncated,
    }


def read_url(url: str) -> str:
    """
    Fetch and extract content from a URL, returning structured JSON.

    Uses _max_url_chars and _url_fetch_timeout set by configure_search().
    Never raises — any exception is caught and returned as error JSON.

    Args:
        url: The full URL to fetch.

    Returns:
        JSON string of a result dict (url, title, author, published_date,
        text, truncated) or an error dict with a single "error" key.
    """
    try:
        result = _fetch_url(url, _max_url_chars, _url_fetch_timeout)
    except Exception as e:
        result = {"error": f"read_url failed: {type(e).__name__}: {e}"}
    return json.dumps(result)


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

    Counter is incremented inside the provider function before the API call,
    so failed searches are counted too. Unknown tool names and malformed
    inputs (missing query key) do not increment the counter.
    The Orchestrator reports the total via get_and_reset_search_count().

    kg_ tool calls are routed to the knowledge graph functions. They do not
    increment _search_call_count — they are not billable search calls.

    Used by the orchestrator so citations are carried through to the synthesiser
    and formatted into the final report's References section.

    Args:
        tool_name:  Name of the tool to execute.
        tool_input: Dict of tool arguments.

    Returns:
        Tuple of (result_text, sources) where sources is a list of
        {"title": str, "url": str} dicts, deduplicated by URL.

    Raises:
        ValueError: If tool_name is not recognised.
    """
    if tool_name == "web_search":
        return _web_search_with_sources(tool_input["query"])
    if tool_name == "read_url":
        result = read_url(tool_input.get("url", ""))
        return result, []
    if tool_name == "arxiv_search":
        result = arxiv_search(tool_input.get("query", ""))
        return result, []
    if tool_name == "kg_query_claims_for_topic":
        result = kg_query_claims_for_topic(tool_input.get("topic", ""))
        return result, []
    if tool_name == "kg_check_contradiction":
        result = kg_check_contradiction(
            tool_input.get("claim", ""), tool_input.get("topic", "")
        )
        return result, []
    if tool_name == "kg_write_claim":
        claim_input = tool_input.get("claim_dict", {})
        if isinstance(claim_input, str):
            try:
                claim_input = json.loads(claim_input)
            except (json.JSONDecodeError, ValueError):
                return ('{"status":"rejected",'
                        '"reason":"claim_dict could not be parsed as JSON"}', [])
        if not isinstance(claim_input, dict):
            return ('{"status":"rejected",'
                    '"reason":"claim_dict must be an object"}', [])
        result = kg_write_claim(claim_input)
        return result, []
    raise ValueError(f"Unknown tool: {tool_name}")


# ── Knowledge graph tool functions ────────────────────────────────────────────
# These functions bridge tool dispatch to the knowledge store singleton.
# They do not increment _search_call_count — not billable search calls.

def kg_query_claims_for_topic(topic: str) -> str:
    """Query the knowledge graph for claims related to a topic."""
    from knowledge.store import get_store
    store = get_store()
    if store is None:
        return '{"error": "knowledge graph unavailable"}'
    return store.query_claims_for_topic(topic)


def kg_check_contradiction(claim: str, topic: str) -> str:
    """Check the knowledge graph for contradicting claims on a topic."""
    from knowledge.store import get_store
    store = get_store()
    if store is None:
        return '{"status": "unresolved", "reason": "knowledge graph unavailable"}'
    return store.check_contradiction(claim, topic, staleness_days=_staleness_days)


def kg_write_claim(claim_dict: dict) -> str:
    """Write a single validated claim to the knowledge graph (Analyst-only)."""
    from knowledge.store import get_store
    store = get_store()
    if store is None:
        return '{"status": "error", "reason": "knowledge graph unavailable"}'
    return store.write_claim(claim_dict)


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
    global _search_call_count
    _search_call_count += 1

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

    global _search_call_count
    _search_call_count += 1

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
