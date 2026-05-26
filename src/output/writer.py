"""
Report persistence utilities for the research-agent pipeline.

Provides two functions:
  save_report()   — writes a report to output/ in markdown, HTML, or PDF format
  update_index()  — appends a row to output/index.md tracking all runs

Both functions write to the filesystem. Format conversion (HTML/PDF) is
delegated to output.formatter.
"""

import os
import time
from datetime import datetime

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

    # Fallback for punctuation-only or empty topics that sanitise to nothing
    if not filename:
        filename = f"report_{int(time.time())}"

    # Collision handling — append timestamp if file already exists
    ext = ".html" if fmt == "html" else ".pdf" if fmt == "pdf" else ".md"
    filepath = f"output/{filename}{ext}"
    if os.path.exists(filepath):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{filename}_{timestamp}"
        filepath = f"output/{filename}{ext}"

    if fmt == "html":
        html = convert_to_html(topic, metadata, report)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

    elif fmt == "pdf":
        html = convert_to_html(topic, metadata, report)
        convert_to_pdf(html, filepath)

    else:
        # Default: markdown
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# {topic}\n\n")
            f.write(metadata + "\n")
            f.write(report)

    return filepath


_INDEX_HEADER = (
    "# Research Agent — Report Index\n\n"
    "| Date | Topic | Orchestration | Synthesis | Search | Questions | Searches | Mode | Provenance | File |\n"
    "|---|---|---|---|---|---|---|---|---|---|\n"
)


def update_index(topic: str, output_path: str, started_at, orch_provider: str,
                 orch_model: str, synth_provider: str, synth_model: str,
                 search_provider: str, question_count: int, search_count: int,
                 short: bool, provenance: str = "none") -> None:
    """
    Append a row to output/index.md tracking all reports generated.

    Uses an atomic write (read → modify in memory → write to temp file →
    os.replace) to eliminate the TOCTOU race on the header check and
    prevent interleaved rows from concurrent workers.
    """
    os.makedirs("output", exist_ok=True)
    index_path = "output/index.md"

    mode = "Summary" if short else "Full"
    date = started_at.strftime("%Y-%m-%d %H:%M")
    orch = f"{orch_provider}/{orch_model}"
    synth = f"{synth_provider}/{synth_model}"
    filename = os.path.basename(output_path)
    link = f"[{filename}]({filename})"
    row = f"| {date} | {topic} | {orch} | {synth} | {search_provider} | {question_count} | {search_count} | {mode} | {provenance} | {link} |\n"

    # Read existing content into memory; fall back to header for a new file.
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = _INDEX_HEADER

    new_content = content + row

    # Write to a temp file in the same directory, then atomically replace.
    # os.replace() is atomic on POSIX; as close to atomic as Windows allows.
    tmp_path = f"{index_path}.tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    os.replace(tmp_path, index_path)
