"""
Tests for agent/tool_utils.py — _validate_tool_input().

Verifies:
  - Returns query string for a well-formed dict with "query" key.
  - Returns None for None input.
  - Returns None for non-dict input (int, list, str).
  - Returns None when "query" key is absent.
  - Returns None when "query" value is empty string.
  - Returns None when "query" value is not a string (None, int).
"""

import pytest
from agent.tool_utils import _validate_tool_input


def test_returns_query_for_valid_input():
    """Well-formed dict with a non-empty 'query' string returns the query."""
    assert _validate_tool_input({"query": "fusion reactor"}) == "fusion reactor"


def test_returns_none_for_none_input():
    """None input returns None without raising."""
    assert _validate_tool_input(None) is None


def test_returns_none_for_int_input():
    """Non-dict input (int) returns None."""
    assert _validate_tool_input(42) is None


def test_returns_none_for_list_input():
    """Non-dict input (list) returns None."""
    assert _validate_tool_input(["query"]) is None


def test_returns_none_for_string_input():
    """Non-dict input (str) returns None — the string is not treated as a query."""
    assert _validate_tool_input("fusion reactor") is None


def test_returns_none_when_query_key_absent():
    """Dict without 'query' key returns None."""
    assert _validate_tool_input({"search": "fusion"}) is None


def test_returns_none_when_query_is_empty_string():
    """Empty string 'query' value returns None."""
    assert _validate_tool_input({"query": ""}) is None


def test_returns_none_when_query_is_none():
    """None 'query' value returns None."""
    assert _validate_tool_input({"query": None}) is None


def test_returns_none_when_query_is_int():
    """Non-string 'query' value (int) returns None."""
    assert _validate_tool_input({"query": 42}) is None


def test_extra_keys_are_ignored():
    """Extra keys in the dict do not affect extraction of the query."""
    assert _validate_tool_input({"query": "ITER", "max_results": 5}) == "ITER"
