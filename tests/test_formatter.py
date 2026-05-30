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
from output.formatter import (
    build_metadata,
    convert_to_html,
    render_raw,
    render_bibliography,
    render_academic,
)


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


# ── FIX 6 — bleach missing raises ImportError ────────────────────────────────

def test_html_missing_bleach_raises_import_error():
    """When markdown is available but bleach is missing, convert_to_html raises ImportError."""
    with patch("output.formatter.BLEACH_AVAILABLE", False), \
         patch("output.formatter.MARKDOWN_AVAILABLE", True), \
         patch("output.formatter.markdown", _make_mock_markdown()):
        with pytest.raises(ImportError, match="pip install bleach"):
            convert_to_html("Topic", "", "**bold**")


def test_html_missing_bleach_error_states_html_output_requirement():
    """ImportError message states bleach is required for HTML output specifically."""
    with patch("output.formatter.BLEACH_AVAILABLE", False), \
         patch("output.formatter.MARKDOWN_AVAILABLE", True), \
         patch("output.formatter.markdown", _make_mock_markdown()):
        with pytest.raises(ImportError, match="bleach is required for HTML output"):
            convert_to_html("Topic", "", "content")


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


# ── Line anchors ─────────────────────────────────────────────────────────────

def _make_identity_markdown():
    """Minimal markdown mock that returns the input text unchanged."""
    mock = MagicMock()
    mock.markdown.side_effect = lambda text, extensions=None: text
    return mock


def test_html_report_body_contains_line_anchors():
    """convert_to_html() report body contains span elements with id='L1', 'L2' etc."""
    with patch("output.formatter.markdown", _make_identity_markdown()), \
         patch("output.formatter.MARKDOWN_AVAILABLE", True):
        result = convert_to_html("Topic", "", "First line\nSecond line")
    assert 'id="L1"' in result
    assert 'id="L2"' in result


def test_html_line_anchors_are_one_based_and_sequential():
    """Line anchors start at L1 and increment by 1."""
    with patch("output.formatter.markdown", _make_identity_markdown()), \
         patch("output.formatter.MARKDOWN_AVAILABLE", True):
        result = convert_to_html("Topic", "", "A\nB\nC")
    assert 'id="L1"' in result
    assert 'id="L2"' in result
    assert 'id="L3"' in result
    assert 'id="L0"' not in result


def test_html_bleach_preserves_span_id_attribute():
    """bleach does not strip the id attribute from span elements."""
    with patch("output.formatter.markdown", _make_identity_markdown()), \
         patch("output.formatter.MARKDOWN_AVAILABLE", True):
        result = convert_to_html("Topic", "", "Some content")
    assert '<span id="L' in result


def test_html_line_anchors_only_in_report_body_not_metadata():
    """Line anchors do not appear in the metadata section — only in the report body."""
    with patch("output.formatter.markdown", _make_identity_markdown()), \
         patch("output.formatter.MARKDOWN_AVAILABLE", True):
        result = convert_to_html("Topic", "Key: Val", "Report line")
    meta_start = result.find('<div class="metadata">')
    meta_end = result.find('</div>', meta_start)
    meta_section = result[meta_start:meta_end]
    assert 'id="L' not in meta_section


# ── render_raw() ─────────────────────────────────────────────────────────────

def test_render_raw_removes_metadata_table_block():
    """render_raw() strips the --- wrapped metadata block at the top of the report."""
    report = (
        "---\n"
        "| | |\n"
        "|---|---|\n"
        "| **Topic** | test |\n"
        "---\n"
        "\n"
        "## Executive Summary\n"
        "\n"
        "Prose content here."
    )
    result = render_raw(report)
    assert "| **Topic** | test |" not in result
    assert "Prose content here." in result


def test_render_raw_removes_references_section():
    """render_raw() strips the ## References section from the end of the report."""
    report = (
        "## Executive Summary\n\nProse here.\n\n"
        "## References\n\n- [1] Source A. https://example.com.\n- [2] Source B."
    )
    result = render_raw(report)
    assert "## References" not in result
    assert "[1] Source A." not in result
    assert "Prose here." in result


def test_render_raw_returns_prose_when_neither_section_present():
    """render_raw() returns the report unchanged when no metadata block or References are present."""
    report = "Just plain prose with no markers."
    result = render_raw(report)
    assert result == "Just plain prose with no markers."


def test_render_raw_handles_prose_only_unchanged():
    """render_raw() with only prose (no metadata, no references) returns it unchanged."""
    report = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    result = render_raw(report)
    assert result == "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."


# ── render_bibliography() ─────────────────────────────────────────────────────

def test_render_bibliography_deduplicates_by_url():
    """render_bibliography() removes duplicate sources sharing the same URL."""
    sources = {
        "Q1": [{"title": "Site A", "url": "https://a.com", "source_type": "general"}],
        "Q2": [{"title": "Site A", "url": "https://a.com", "source_type": "general"}],
    }
    result = render_bibliography("", sources)
    assert result.count("https://a.com") == 1


def test_render_bibliography_groups_by_source_type():
    """render_bibliography() creates a ## section for each source type present."""
    sources = {
        "Q1": [
            {"title": "Gov Doc", "url": "https://gov.gov", "source_type": "government"},
            {"title": "Forum Post", "url": "https://forum.io", "source_type": "forum"},
        ]
    }
    result = render_bibliography("", sources)
    assert "## Government Sources" in result
    assert "## Forum Sources" in result
    assert "## Academic Sources" not in result


def test_render_bibliography_sorts_government_before_academic_before_general():
    """render_bibliography() orders type sections: government → academic → general."""
    sources = {
        "Q1": [
            {"title": "Gen Article", "url": "https://gen.com", "source_type": "general"},
            {"title": "Acad Paper", "url": "https://acad.edu", "source_type": "academic"},
            {"title": "Gov Report", "url": "https://gov.gov", "source_type": "government"},
        ]
    }
    result = render_bibliography("", sources)
    gov_pos = result.find("## Government Sources")
    acad_pos = result.find("## Academic Sources")
    gen_pos = result.find("## General Sources")
    assert gov_pos < acad_pos < gen_pos


def test_render_bibliography_empty_sources_returns_stub():
    """render_bibliography() returns a minimal stub when sources dict is empty."""
    result = render_bibliography("", {})
    assert result == "# Bibliography\n\nNo sources found."


def test_render_bibliography_produces_markdown_headers_per_type():
    """render_bibliography() output contains a ## header for each type that has sources."""
    sources = {
        "Q1": [
            {"title": "Article", "url": "https://news.com", "source_type": "news"},
        ]
    }
    result = render_bibliography("", sources)
    assert result.startswith("# Bibliography")
    assert "## News Sources" in result
    assert "- Article." in result


# ── render_academic() ─────────────────────────────────────────────────────────

_ACADEMIC_REPORT = (
    "## Executive Summary\n\n"
    "This is the executive summary.\n\n"
    "## Introduction\n\n"
    "Introduction content.\n\n"
    "## Findings\n\n"
    "Finding content.\n\n"
    "## References\n\n"
    "- [1] Source One. https://one.com.\n"
    "- [2] Source Two. https://two.com."
)


def test_render_academic_extracts_executive_summary_as_abstract():
    """render_academic() uses the Executive Summary section as the Abstract."""
    result = render_academic(_ACADEMIC_REPORT, "test topic", "")
    assert "## Abstract" in result
    assert "This is the executive summary." in result
    # Abstract should appear before body sections
    assert result.index("## Abstract") < result.index("Introduction content.")


def test_render_academic_falls_back_to_first_two_paragraphs():
    """render_academic() uses first two prose paragraphs as abstract when no summary heading."""
    report = "First para.\n\nSecond para.\n\nThird para.\n\n## Section\n\nContent."
    result = render_academic(report, "test topic", "")
    assert "## Abstract" in result
    assert "First para." in result
    assert "Second para." in result


def test_render_academic_numbers_sections_sequentially():
    """render_academic() converts ## headings to sequentially numbered plain headers."""
    result = render_academic(_ACADEMIC_REPORT, "test topic", "")
    assert "1. Introduction" in result
    assert "2. Findings" in result
    # Original ## headings should be gone (except References which stays as ##)
    assert "## Introduction" not in result
    assert "## Findings" not in result


def test_render_academic_reformats_references_as_numbered_list():
    """render_academic() converts ## References bullet list to [N] numbered format."""
    result = render_academic(_ACADEMIC_REPORT, "test topic", "")
    assert "[1] Source One." in result
    assert "[2] Source Two." in result
    # Original bullet format gone
    assert "- [1]" not in result


def test_render_academic_preserves_all_original_content():
    """render_academic() does not drop any content from the original report."""
    result = render_academic(_ACADEMIC_REPORT, "test topic", "")
    assert "This is the executive summary." in result
    assert "Introduction content." in result
    assert "Finding content." in result
    assert "Source One." in result
