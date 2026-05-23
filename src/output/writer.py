"""
Report persistence utilities for the research-agent pipeline.

Provides two functions:
  save_report()   — writes a report to output/ in markdown, HTML, or PDF format
  update_index()  — appends a row to output/index.md tracking all runs

Both functions write to the filesystem. Format conversion (HTML/PDF) is
delegated to output.formatter.
"""

import os

from .formatter import convert_to_html, convert_to_pdf


def save_report(topic: str, metadata: str, report: str, fmt: str = "markdown") -> str:
    """
    Save report to output/ directory in the specified format.

    Filename is derived from topic — lowercased, non-alphanumeric chars
    stripped, spaces replaced with underscores, truncated to 50 chars.

    Args:
        topic:    Research topic (used for filename)
        metadata: Markdown metadata table string
        report:   Report body markdown string
        fmt:      "markdown", "html", or "pdf"

    Returns:
        Path to saved file
    """
    os.makedirs("output", exist_ok=True)

    # Sanitise topic into a safe filename
    filename = topic.lower()
    filename = "".join(c if c.isalnum() or c == " " else "" for c in filename)
    filename = filename.strip().replace(" ", "_")[:50]

    if fmt == "html":
        filepath = f"output/{filename}.html"
        html = convert_to_html(topic, metadata, report)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

    elif fmt == "pdf":
        filepath = f"output/{filename}.pdf"
        html = convert_to_html(topic, metadata, report)
        convert_to_pdf(html, filepath)

    else:
        # Default: markdown
        filepath = f"output/{filename}.md"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# {topic}\n\n")
            f.write(metadata + "\n")
            f.write(report)

    return filepath


def update_index(topic, output_path, started_at, orch_provider, orch_model,
                 synth_provider, synth_model, search_provider, question_count,
                 search_count, short, provenance: str = "none"):
    """
    Append a row to output/index.md tracking all reports generated.
    Creates the index file with header if it doesn't exist.
    """
    os.makedirs("output", exist_ok=True)
    index_path = "output/index.md"

    if not os.path.exists(index_path):
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("# Research Agent — Report Index\n\n")
            f.write("| Date | Topic | Orchestration | Synthesis | Search | Questions | Searches | Mode | Provenance | File |\n")
            f.write("|---|---|---|---|---|---|---|---|---|---|\n")

    mode = "Summary" if short else "Full"
    date = started_at.strftime("%Y-%m-%d %H:%M")
    orch = f"{orch_provider}/{orch_model}"
    synth = f"{synth_provider}/{synth_model}"
    filename = os.path.basename(output_path)
    link = f"[{filename}]({filename})"

    row = f"| {date} | {topic} | {orch} | {synth} | {search_provider} | {question_count} | {search_count} | {mode} | {provenance} | {link} |\n"

    with open(index_path, "a", encoding="utf-8") as f:
        f.write(row)
