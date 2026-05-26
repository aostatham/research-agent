"""
Shared utility functions for agent tool-call handling.

Public API:
  _validate_tool_input() — extract query string from a tool_input dict,
                           returning None for any malformed input
"""

import logging
from typing import Optional


def _validate_tool_input(tool_input) -> Optional[str]:
    """
    Extract the query string from a tool_input dict.

    Returns None (instead of raising) for any malformed input: None,
    non-dict, or dict missing the "query" key. Callers should treat a
    None return as "no usable query" and skip or log the tool call.

    Args:
        tool_input: The tool_input value from an LLMResponse tool_call.

    Returns:
        The query string, or None if tool_input is malformed.
    """
    if not isinstance(tool_input, dict):
        logging.warning("_validate_tool_input: expected dict, got %r", type(tool_input))
        return None
    query = tool_input.get("query")
    if not isinstance(query, str) or not query:
        logging.warning("_validate_tool_input: missing or non-string 'query' in %r", tool_input)
        return None
    return query
