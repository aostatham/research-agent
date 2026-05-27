"""
Report persistence utilities for the research-agent pipeline.

Provides three functions:
  save_report()   — writes a report to output/ in markdown, HTML, or PDF format
  update_index()  — appends a row to output/index.md tracking all runs
  save_viewer()   — writes a self-contained provenance viewer HTML file

All functions write to the filesystem. Format conversion (HTML/PDF) is
delegated to output.formatter.
"""

import json as _json
import os
import tempfile
import threading
import time
from datetime import datetime

from .formatter import convert_to_html, convert_to_pdf

try:
    import fcntl
    _USE_FLOCK = True
except ImportError:
    _USE_FLOCK = False

_INDEX_LOCK = threading.Lock()


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

    Uses fcntl.flock (POSIX) with a threading.Lock fallback to serialise
    concurrent writers across threads and processes. The full read-modify-write
    sequence is protected by the lock, and the write uses NamedTemporaryFile +
    os.replace() for atomicity so a crash mid-write leaves the index intact.
    """
    os.makedirs("output", exist_ok=True)
    index_path = "output/index.md"
    index_dir = os.path.dirname(os.path.abspath(index_path))

    mode = "Summary" if short else "Full"
    date = started_at.strftime("%Y-%m-%d %H:%M")
    orch = f"{orch_provider}/{orch_model}"
    synth = f"{synth_provider}/{synth_model}"
    filename = os.path.basename(output_path)
    link = f"[{filename}]({filename})"
    row = f"| {date} | {topic} | {orch} | {synth} | {search_provider} | {question_count} | {search_count} | {mode} | {provenance} | {link} |\n"

    with _INDEX_LOCK:
        if _USE_FLOCK:
            # Open (or create) a dedicated lock file — never written to, just locked.
            lock_fd = open(index_path + ".lock", "a")
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                _write_index_row(index_path, index_dir, row)
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
        else:
            _write_index_row(index_path, index_dir, row)


def save_viewer(output_path: str, provenance_data: dict) -> str:
    """
    Write a self-contained provenance viewer HTML file alongside the report.

    Reads the viewer template from src/output/viewer_template.html, injects
    the serialised provenance_data JSON, and writes the result to
    output/<base>.viewer.html (same base name as the report).

    Args:
        output_path:     Path to the saved report file (any extension)
        provenance_data: ProvenanceReport dict to embed in the viewer

    Returns:
        Path to the written viewer file
    """
    template_path = os.path.join(os.path.dirname(__file__), "viewer_template.html")
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    json_str = _json.dumps(provenance_data, ensure_ascii=False)
    viewer_html = template.replace("__PROVENANCE_DATA__", json_str, 1)

    base = os.path.splitext(output_path)[0]
    viewer_path = f"{base}.viewer.html"
    os.makedirs(os.path.dirname(viewer_path) or ".", exist_ok=True)

    with open(viewer_path, "w", encoding="utf-8") as f:
        f.write(viewer_html)

    return viewer_path


def _write_index_row(index_path: str, index_dir: str, row: str) -> None:
    """Read current index (or create header), append row, atomically replace."""
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = _INDEX_HEADER

    new_content = content + row

    tmp_fd, tmp_path = tempfile.mkstemp(dir=index_dir, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(tmp_path, index_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
