"""
Tests for output/formatter.py — build_metadata() and convert_to_html().

Verifies:
  - build_metadata(): produces a markdown table with expected field values.
  - convert_to_html(): bleach strips disallowed tags (script, b, etc.) from
    rendered HTML; safe tags (p, strong, table, etc.) pass through; topic
    is html.escape()'d in <title> and <h1>; fallback path (no markdown/bleach)
    html.escape()'s report content.
"""

import re
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from output.formatter import build_metadata, convert_to_html


def _make_mock_markdown():
    """Minimal markdown mock: converts **text** → <strong>text</strong>."""
    mock = MagicMock()
    mock.markdown.side_effect = lambda text, extensions=None: re.sub(
        r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text
    )
    return mock


# ── build_metadata() tests ────────────────────────────────────────────────────

def _make_config(search_provider="anthropic"):
    cfg = MagicMock()
    cfg.search_provider = search_provider
    return cfg


def test_build_metadata_contains_topic():
    """Topic appears verbatim in the metadata table."""
    config = _make_config()
    result = build_metadata(
        topic="nuclear fusion",
        config=config,
        orch_provider="anthropic",
        orch_model="claude-haiku-4-5-20251001",
        synth_provider="anthropic",
        synth_model="claude-sonnet-4-6",
        started_at=datetime(2026, 1, 1, 12, 0),
        elapsed=30.0,
        question_count=4,
        search_count=8,
        report_chars=5000,
        short=False,
    )
    assert "nuclear fusion" in result


def test_build_metadata_shows_full_report_mode():
    """Mode field says 'Full Report' when short=False."""
    config = _make_config()
    result = build_metadata(
        topic="test",
        config=config,
        orch_provider="anthropic",
        orch_model="claude-haiku-4-5-20251001",
        synth_provider="anthropic",
        synth_model="claude-sonnet-4-6",
        started_at=datetime(2026, 1, 1, 12, 0),
        elapsed=10.0,
        question_count=4,
        search_count=4,
        report_chars=1000,
        short=False,
    )
    assert "Full Report" in result


def test_build_metadata_shows_summary_mode():
    """Mode field says 'Executive Summary' when short=True."""
    config = _make_config()
    result = build_metadata(
        topic="test",
        config=config,
        orch_provider="anthropic",
        orch_model="claude-haiku-4-5-20251001",
        synth_provider="anthropic",
        synth_model="claude-sonnet-4-6",
        started_at=datetime(2026, 1, 1, 12, 0),
        elapsed=10.0,
        question_count=4,
        search_count=4,
        report_chars=500,
        short=True,
    )
    assert "Executive Summary" in result


# ── convert_to_html() — XSS sanitisation (bleach post-render, H1 fix) ───────

def test_html_strips_script_tag_in_report():
    """bleach strips <script> tags from rendered report — no executable script."""
    result = convert_to_html("Topic", "", "<script>alert(1)</script>")
    assert "<script>" not in result


def test_html_strips_disallowed_tag_in_report():
    """bleach strips disallowed tags (e.g. <b>) from report; raw injection blocked."""
    result = convert_to_html("Topic", "", "<b>injected</b>")
    assert "<b>injected</b>" not in result


def test_html_safe_tags_pass_through():
    """bleach allows safe markdown-generated tags such as <p> and <strong>."""
    with patch("output.formatter.markdown", _make_mock_markdown()), \
         patch("output.formatter.MARKDOWN_AVAILABLE", True):
        result = convert_to_html("Topic", "", "**bold text**")
    assert "<strong>bold text</strong>" in result


def test_html_normal_content_unchanged():
    """Report content without HTML special characters passes through intact."""
    result = convert_to_html("Topic", "", "Normal report content without special characters")
    assert "Normal report content without special characters" in result


def test_html_escapes_script_tag_in_topic_title():
    """<script> in the topic is escaped via html.escape() in the <title> element."""
    result = convert_to_html("<script>evil</script>", "", "Report body")
    assert "<title><script>" not in result
    assert "&lt;script&gt;" in result


def test_html_escapes_script_tag_in_topic_h1():
    """<script> in the topic is escaped via html.escape() in the <h1> element."""
    result = convert_to_html("<script>evil</script>", "", "Report body")
    assert "<h1><script>" not in result


def test_html_fallback_path_escapes_report():
    """Fallback path (no markdown) applies html.escape() to report content."""
    with patch("output.formatter.MARKDOWN_AVAILABLE", False):
        result = convert_to_html("Topic", "", "<script>alert(1)</script>")
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


# ── FIX 6 — split markdown/bleach import failure modes ───────────────────────

def test_html_missing_bleach_logs_warning(caplog):
    """When bleach is unavailable, a WARNING is logged and markdown is still rendered."""
    import logging
    with patch("output.formatter.BLEACH_AVAILABLE", False), \
         patch("output.formatter.MARKDOWN_AVAILABLE", True), \
         patch("output.formatter.markdown", _make_mock_markdown()):
        with caplog.at_level(logging.WARNING, logger="output.formatter"):
            result = convert_to_html("Topic", "", "**bold**")
    assert any("bleach" in record.message.lower() for record in caplog.records)


def test_html_missing_bleach_still_renders_markdown():
    """When bleach is unavailable, markdown rendering still produces HTML."""
    with patch("output.formatter.BLEACH_AVAILABLE", False), \
         patch("output.formatter.MARKDOWN_AVAILABLE", True), \
         patch("output.formatter.markdown", _make_mock_markdown()):
        result = convert_to_html("Topic", "", "**bold text**")
    assert "<strong>bold text</strong>" in result


def test_html_missing_markdown_falls_back_to_preformatted():
    """When markdown is unavailable, report falls back to html-escaped preformatted text."""
    with patch("output.formatter.MARKDOWN_AVAILABLE", False):
        result = convert_to_html("Topic", "", "<script>alert(1)</script>")
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_html_missing_both_degrades_gracefully():
    """When both markdown and bleach are unavailable, fallback path applies."""
    with patch("output.formatter.MARKDOWN_AVAILABLE", False), \
         patch("output.formatter.BLEACH_AVAILABLE", False):
        result = convert_to_html("Topic", "", "Normal content")
    assert "Normal content" in result
