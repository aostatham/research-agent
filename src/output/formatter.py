"""
Report formatting utilities for the research-agent pipeline.

Provides:
  build_metadata()         — markdown metadata table prepended to every report
  convert_to_html()        — converts markdown report to a styled HTML page
  convert_to_pdf()         — converts HTML to PDF via weasyprint (optional dep)
  render_raw()             — strips metadata block and References, returns prose
  render_bibliography()    — formatted bibliography grouped by source type
  render_academic()        — academic style with abstract and numbered sections
  render_report_evidence() — report with inline confidence/verification markers

These functions are format-only; they do not touch the filesystem.
See output.writer for save_report() and update_index().
"""

import html


try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    markdown = None  # type: ignore[assignment]
    MARKDOWN_AVAILABLE = False

try:
    import bleach
    BLEACH_AVAILABLE = True
except ImportError:
    BLEACH_AVAILABLE = False


_SAFE_TAGS = [
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "a", "ul", "ol", "li", "strong", "em", "code", "pre",
    "blockquote", "hr", "br", "table", "thead", "tbody", "tr", "th", "td",
    "span",
]

_SAFE_ATTRS = {"a": ["href"], "span": ["id"]}


def _add_line_anchors(html_str: str) -> str:
    """
    Wrap each line of rendered HTML in a <span id="LN"> element.

    N is the 1-based line number. Enables the provenance viewer to link
    directly to the report line referenced in each claim's report_line field.

    Args:
        html_str: Rendered HTML string (post-markdown, pre-bleach)

    Returns:
        HTML string with each line wrapped in <span id="LN">...</span>
    """
    lines = html_str.split("\n")
    wrapped = [f'<span id="L{i + 1}">{line}</span>' for i, line in enumerate(lines)]
    return "\n".join(wrapped)


def build_metadata(topic: str, config, orch_provider: str, orch_model: str,
                   synth_provider: str, synth_model: str, started_at,
                   elapsed: float, question_count: int, search_count: int,
                   report_chars: int, short: bool) -> str:
    """
    Build a markdown metadata table for the top of the report.

    Returns a markdown table string with topic, generation time, providers,
    search stats, and mode. Included verbatim at the top of every report.
    """
    mode = "Executive Summary" if short else "Full Report"
    lines = [
        "| | |",
        "|---|---|",
        f"| **Topic** | {topic} |",
        f"| **Generated** | {started_at.strftime('%Y-%m-%d %H:%M')} |",
        f"| **Orchestration** | {orch_provider} / {orch_model} |",
        f"| **Synthesis** | {synth_provider} / {synth_model} |",
        f"| **Search provider** | {config.search_provider} |",
        f"| **Questions researched** | {question_count} |",
        f"| **Web searches** | {search_count} |",
        f"| **Time** | {elapsed:.1f}s |",
        f"| **Report length** | {report_chars:,} chars |",
        f"| **Mode** | {mode} |",
        "",
    ]
    return "\n".join(lines)


def convert_to_html(topic: str, metadata: str, report: str) -> str:
    """
    Convert markdown report to a styled HTML page.

    Uses the markdown library with tables and fenced_code extensions.
    Falls back to preformatted text if markdown library is not installed.

    The metadata block is rendered in a styled div separate from the
    report body, matching the two-section structure of the markdown output.

    Args:
        topic:    Used as the HTML page title and h1
        metadata: Markdown metadata table string
        report:   Report body markdown string

    Returns:
        Complete HTML document as a string
    """
    safe_topic = html.escape(topic)

    if MARKDOWN_AVAILABLE and BLEACH_AVAILABLE:
        meta_html = markdown.markdown(metadata, extensions=["tables"])
        report_html = markdown.markdown(report, extensions=["tables", "fenced_code"])
        report_html = _add_line_anchors(report_html)
        meta_html = bleach.clean(
            meta_html,
            tags=_SAFE_TAGS,
            attributes=_SAFE_ATTRS,
            strip=True,
        )
        report_html = bleach.clean(
            report_html,
            tags=_SAFE_TAGS,
            attributes=_SAFE_ATTRS,
            strip=True,
        )
    elif MARKDOWN_AVAILABLE and not BLEACH_AVAILABLE:
        raise ImportError(
            "bleach is required for HTML output. "
            "Install it with: pip install bleach"
        )
    else:
        # Fallback if markdown not installed
        meta_html = f"<pre>{html.escape(metadata)}</pre>"
        report_html = f"<pre>{html.escape(report)}</pre>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{safe_topic}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                max-width: 860px; margin: 40px auto; padding: 0 20px;
                color: #1a1a1a; line-height: 1.7; }}
        h1 {{ border-bottom: 2px solid #e0e0e0; padding-bottom: 12px; }}
        h2 {{ margin-top: 2em; color: #2c2c2c; }}
        hr {{ border: none; border-top: 1px solid #e0e0e0; margin: 1.5em 0; }}
        code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 3px;
                font-size: 0.9em; }}
        pre {{ background: #f5f5f5; padding: 16px; border-radius: 6px;
               overflow-x: auto; }}
        blockquote {{ border-left: 4px solid #e0e0e0; margin: 0;
                      padding-left: 16px; color: #555; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #e0e0e0; padding: 8px 12px; text-align: left; }}
        th {{ background: #f5f5f5; }}
        a {{ color: #0066cc; }}
        .metadata {{ background: #f9f9f9; border: 1px solid #e0e0e0;
                     border-radius: 6px; padding: 16px; margin-bottom: 2em;
                     font-size: 0.9em; }}
    </style>
</head>
<body>
    <h1>{safe_topic}</h1>
    <div class="metadata">{meta_html}</div>
    {report_html}
</body>
</html>"""


def convert_to_pdf(html: str, filepath: str):
    """
    Convert an HTML string to a PDF file using weasyprint.

    Uses the same HTML pipeline as convert_to_html() to ensure consistent
    styling between HTML and PDF outputs. Additional print CSS is applied
    for page sizing, margins, and link URL display.

    Requires:
        pip install weasyprint
        brew install pango  (macOS)

    Args:
        html:     Complete HTML document string (from convert_to_html)
        filepath: Output path for the PDF file

    Raises:
        ImportError: If weasyprint is not installed
    """
    try:
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration
    except ImportError:
        raise ImportError(
            "weasyprint not installed. Run: pip install weasyprint\n"
            "On macOS also run: brew install pango"
        )

    font_config = FontConfiguration()

    # Print-specific CSS — overrides screen CSS for PDF rendering
    print_css = CSS(string="""
        @page {
            size: A4;
            margin: 2cm;
        }
        body {
            font-size: 11pt;
            max-width: none;
            margin: 0;
            padding: 0;
        }
        h1 { font-size: 20pt; }
        h2 { font-size: 15pt; }
        h3 { font-size: 13pt; }
        pre, code {
            font-size: 9pt;
            white-space: pre-wrap;
            word-break: break-all;
        }
        table {
            font-size: 9pt;
            width: 100%;
        }
        a::after {
            content: " (" attr(href) ")";
            font-size: 8pt;
            color: #666;
        }
        .metadata {
            border: 1pt solid #ccc;
            padding: 10pt;
            margin-bottom: 15pt;
            font-size: 9pt;
        }
    """, font_config=font_config)

    HTML(string=html).write_pdf(
        filepath,
        stylesheets=[print_css],
        font_config=font_config
    )


def render_raw(report: str) -> str:
    """Return report text stripped of the leading metadata block and References section.

    The metadata block is expected between the first and second ``---`` markers
    at the top of the report (a ``---``-wrapped table block).  If no such block
    exists the stripping is a no-op.  The ``## References`` section is stripped
    from the last occurrence to the end of the string.

    Args:
        report: Full report string, optionally containing a leading
                ``---``-wrapped metadata block and/or a trailing References section.

    Returns:
        Prose-only string with metadata block and References removed, stripped
        of leading/trailing whitespace.
    """
    text = report

    # Strip leading metadata block (between first and second --- markers).
    # Normalise: if the string starts with "---\n" (no preceding newline) prepend one
    # so the search pattern "\n---\n" works uniformly.
    if text.startswith("---\n"):
        text = "\n" + text

    sep = "\n---\n"
    first = text.find(sep)
    if first != -1:
        second = text.find(sep, first + len(sep))
        if second != -1:
            text = text[second + len(sep):]

    # Strip trailing References section (last occurrence).
    ref_marker = "\n## References"
    ref_idx = text.rfind(ref_marker)
    if ref_idx != -1:
        text = text[:ref_idx]

    return text.strip()


_BIBLIOGRAPHY_TYPE_ORDER = [
    "government", "academic", "news", "reference",
    "institutional", "industry", "general", "forum", "video",
]

_BIBLIOGRAPHY_TYPE_LABELS = {
    "government": "Government Sources",
    "academic": "Academic Sources",
    "news": "News Sources",
    "reference": "Reference Sources",
    "institutional": "Institutional Sources",
    "industry": "Industry Sources",
    "general": "General Sources",
    "forum": "Forum Sources",
    "video": "Video Sources",
}


def render_bibliography(report: str, sources: dict) -> str:
    """Generate a formatted bibliography from the sources dict.

    Deduplicates by URL across all questions, sorts by source type
    (government first through video last) then alphabetically by title
    within each type, and renders a markdown document with one ## section
    per source type present.

    Args:
        report:  Report body string (unused in output, present for signature
                 consistency with other render functions).
        sources: {question: [{"title": str, "url": str, "source_type": str}]}
                 from the orchestrator.

    Returns:
        Markdown bibliography string.  Returns a minimal stub when sources
        is empty.
    """
    from datetime import datetime as _dt

    retrieved = _dt.now().strftime("%Y-%m-%d")

    # Deduplicate by URL across all questions; sources without URL pass through.
    seen_urls: set = set()
    unique: list = []
    for src_list in sources.values():
        for src in src_list:
            url = src.get("url", "")
            if url:
                if url not in seen_urls:
                    seen_urls.add(url)
                    unique.append(src)
            else:
                unique.append(src)

    if not unique:
        return "# Bibliography\n\nNo sources found."

    # Group by source_type.
    grouped: dict = {}
    for src in unique:
        stype = src.get("source_type", "general")
        grouped.setdefault(stype, []).append(src)

    # Sort within each type by title.
    for stype in grouped:
        grouped[stype].sort(key=lambda s: s.get("title", "").lower())

    lines = ["# Bibliography", ""]
    for stype in _BIBLIOGRAPHY_TYPE_ORDER:
        if stype not in grouped:
            continue
        lines.append(f"## {_BIBLIOGRAPHY_TYPE_LABELS[stype]}")
        lines.append("")
        for src in grouped[stype]:
            title = src.get("title", "Untitled")
            url = src.get("url", "")
            entry = f"- {title}."
            if url:
                entry += f" {url}."
            entry += f" Retrieved {retrieved}."
            lines.append(entry)
        lines.append("")

    return "\n".join(lines).rstrip()


def render_academic(report: str, topic: str, metadata: str) -> str:
    """Reformat a report into structured academic style.

    Structure:
      1. Title — topic in title case.
      2. Abstract — content of the Executive Summary section (or first two
         prose paragraphs if no Executive Summary heading is found).
      3. Body — remaining sections with ## headings converted to numbered
         plain-text headers (``## Introduction`` → ``1. Introduction``).
         The ## References heading is left intact for step 4.
      4. References — existing ## References section reformatted as a
         numbered ``[N]`` list.

    Original content is not added to or removed (beyond the abstract
    extraction and heading numbering).

    Args:
        report:   Report body markdown string.
        topic:    Research topic string — used as the document title.
        metadata: Metadata table string (accepted for signature consistency;
                  not included in the academic output).

    Returns:
        Academic-formatted markdown string.
    """
    import re

    title = topic.title()

    # Find Executive Summary section and use it as the abstract.
    summary_re = re.compile(
        r"^## [^\n]*(?:Executive Summary|Summary)[^\n]*\n(.*?)(?=^## |\Z)",
        re.DOTALL | re.MULTILINE | re.IGNORECASE,
    )
    match = summary_re.search(report)
    if match:
        abstract_text = match.group(1).strip()
        body = report[: match.start()] + report[match.end() :]
    else:
        # Fall back to first two non-heading prose paragraphs.
        paragraphs = [
            p.strip()
            for p in re.split(r"\n\n+", report)
            if p.strip() and not p.strip().startswith("#")
        ]
        abstract_text = "\n\n".join(paragraphs[:2])
        body = report

    # Number all ## headings sequentially, leaving ## References un-numbered
    # so the references reformatter can locate it cleanly.
    counter = [0]

    def _number_heading(m: re.Match) -> str:
        heading = m.group(1)
        if heading.strip().lower() == "references":
            return m.group(0)
        counter[0] += 1
        return f"{counter[0]}. {heading}"

    body = re.sub(r"^## (.+)$", _number_heading, body, flags=re.MULTILINE)

    # Reformat ## References as a numbered [N] list.
    ref_re = re.compile(r"^## References\n+(.*)", re.DOTALL | re.MULTILINE)
    ref_match = ref_re.search(body)
    if ref_match:
        ref_lines = ref_match.group(1).strip().split("\n")
        numbered: list = []
        n = 1
        for line in ref_lines:
            stripped = line.strip()
            if re.match(r"^[-*]\s", stripped):
                content = stripped[2:]
                # Strip any existing [N] prefix so we don't double-number.
                content = re.sub(r"^\[\d+\]\s*", "", content)
                numbered.append(f"[{n}] {content}")
                n += 1
            elif stripped:
                numbered.append(stripped)
        new_refs = "## References\n\n" + "\n".join(numbered)
        body = body[: ref_match.start()] + new_refs

    parts = [
        f"# {title}",
        "",
        "## Abstract",
        "",
        abstract_text,
        "",
        body.strip(),
    ]
    return "\n".join(parts)
