"""
Tests for output/writer.py — update_index().

Verifies:
  - First call creates the index file with header + one row.
  - Second call appends a second row without duplicating the header.
  - os.replace() is called for atomicity (not direct open-and-write).
  - Concurrent calls from multiple threads produce the correct row count
    without interleaving or data loss.
"""

import os
import threading
import pytest
from datetime import datetime
from unittest.mock import patch


def _call_update_index(topic="Nuclear Fusion", output_path="output/report.md",
                       started_at=None, short=False):
    from output.writer import update_index
    if started_at is None:
        started_at = datetime(2026, 1, 1, 12, 0)
    update_index(
        topic=topic,
        output_path=output_path,
        started_at=started_at,
        orch_provider="anthropic",
        orch_model="claude-haiku-4-5-20251001",
        synth_provider="anthropic",
        synth_model="claude-sonnet-4-6",
        search_provider="anthropic",
        question_count=4,
        search_count=8,
        short=short,
        provenance="none",
    )


# ── First-call behaviour ──────────────────────────────────────────────────────

def test_update_index_creates_file_on_first_call(tmp_path, monkeypatch):
    """First call creates output/index.md with header and one data row."""
    monkeypatch.chdir(tmp_path)
    _call_update_index()
    index = (tmp_path / "output" / "index.md").read_text()
    assert "# Research Agent" in index
    assert "Nuclear Fusion" in index


def test_update_index_first_call_has_header_row(tmp_path, monkeypatch):
    """First call writes the column header row."""
    monkeypatch.chdir(tmp_path)
    _call_update_index()
    index = (tmp_path / "output" / "index.md").read_text()
    assert "| Date | Topic |" in index


def test_update_index_first_call_has_one_data_row(tmp_path, monkeypatch):
    """First call results in exactly one data row (header rows excluded)."""
    monkeypatch.chdir(tmp_path)
    _call_update_index(topic="Nuclear Fusion")
    index = (tmp_path / "output" / "index.md").read_text()
    data_rows = [l for l in index.splitlines()
                 if l.startswith("| 20") or l.startswith("| 19")]
    assert len(data_rows) == 1


# ── Second-call behaviour ─────────────────────────────────────────────────────

def test_update_index_second_call_appends_row(tmp_path, monkeypatch):
    """Second call adds a second data row without duplicating the header."""
    monkeypatch.chdir(tmp_path)
    _call_update_index(topic="Fusion Energy")
    _call_update_index(topic="Space Exploration")
    index = (tmp_path / "output" / "index.md").read_text()
    assert "Fusion Energy" in index
    assert "Space Exploration" in index


def test_update_index_second_call_does_not_duplicate_header(tmp_path, monkeypatch):
    """Second call does not write a second copy of the header."""
    monkeypatch.chdir(tmp_path)
    _call_update_index()
    _call_update_index()
    index = (tmp_path / "output" / "index.md").read_text()
    assert index.count("# Research Agent") == 1
    assert index.count("| Date | Topic |") == 1


# ── Atomicity ─────────────────────────────────────────────────────────────────

def test_update_index_uses_os_replace(tmp_path, monkeypatch):
    """update_index() calls os.replace() to atomically rename the temp file."""
    monkeypatch.chdir(tmp_path)
    with patch("output.writer.os.replace", wraps=os.replace) as mock_replace:
        _call_update_index()
    mock_replace.assert_called_once()
    tmp_arg, dst_arg = mock_replace.call_args[0]
    assert dst_arg.endswith("index.md")
    assert dst_arg != tmp_arg


# ── Concurrency ────────────────────────────────────────────────────────────────

def test_update_index_concurrent_threads_produce_correct_row_count(tmp_path, monkeypatch):
    """Concurrent calls from multiple threads each append exactly one row."""
    monkeypatch.chdir(tmp_path)
    n_threads = 8
    barrier = threading.Barrier(n_threads)

    def _worker(i):
        barrier.wait()  # release all threads simultaneously
        _call_update_index(topic=f"Topic {i}")

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    index = (tmp_path / "output" / "index.md").read_text()
    data_rows = [l for l in index.splitlines() if l.startswith("| 20") or l.startswith("| 19")]
    assert len(data_rows) == n_threads
