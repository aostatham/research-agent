"""
Report formatting utilities for the research-agent pipeline.

Provides three functions:
  build_metadata()   — markdown metadata table prepended to every report
  convert_to_html()  — converts markdown report to a styled HTML page
  convert_to_pdf()   — converts HTML to PDF via weasyprint (optional dep)

These functions are format-only; they do not touch the filesystem.
See output.writer for save_report() and update_index().
"""


def build_metadata(topic, config, orch_provider, orch_model, synth_provider,
                   synth_model, started_at, elapsed, question_count,
                   search_count, report_chars, short):
    """
    Build a markdown metadata table for the top of the report.

    Returns a markdown table string with topic, generation time, providers,
    search stats, and mode. Included verbatim at the top of every report.
    """
    mode = "Executive Summary" if short else "Full Report"
    lines = [
        "| Field | Value |",
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
    try:
        import markdown
        meta_html = markdown.markdown(metadata, extensions=["tables"])
        report_html = markdown.markdown(report, extensions=["tables", "fenced_code"])
    except ImportError:
        # Fallback if markdown library not installed
        meta_html = f"<pre>{metadata}</pre>"
        report_html = f"<pre>{report}</pre>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{topic}</title>
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
    <h1>{topic}</h1>
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

    except ImportError:
        raise ImportError(
            "weasyprint not installed. Run: pip install weasyprint\n"
            "On macOS also run: brew install pango"
        )
