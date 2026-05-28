"""
Observability event logging for the research-agent pipeline.

Writes structured JSON lines to output/.logs/events_YYYYMMDD.jsonl.
Each line is one complete event record, directly appendable and
parseable with standard tooling.

Must never crash the pipeline — all write failures are swallowed
and logged via the standard logging module.

Public API:
  configure_observability()  — called once at startup to set the log path
  log_event()                — write one event record; no-op if not configured
"""

import json
import logging
import os
from datetime import datetime, timezone

_log_path: str | None = None


def configure_observability(log_dir: str = "output/.logs") -> None:
    """
    Set up the events log file path for this process.

    Creates log_dir if it does not exist. Sets the module-level _log_path
    to log_dir/events_YYYYMMDD.jsonl using today's UTC date. Must be
    called once at startup before any pipeline work begins.

    Args:
        log_dir: Directory to write event log files into.
    """
    global _log_path
    os.makedirs(log_dir, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    _log_path = os.path.join(log_dir, f"events_{date_str}.jsonl")


def log_event(
    run_id: str,
    agent: str,
    stage: str,
    event: str,
    duration_ms: int = None,
    tokens_in: int = None,
    tokens_out: int = None,
    metadata: dict = None,
) -> None:
    """
    Write one structured event record to the JSON lines log file.

    Is a no-op if configure_observability() has not been called.
    Silently swallows all write failures — observability must never
    crash the pipeline.

    Args:
        run_id:      Run identifier (from RunState.run_id).
        agent:       Agent name ("researcher", "verifier", "editor",
                     "orchestrator", "synthesiser", etc.).
        stage:       Pipeline stage ("research", "verify", "edit",
                     "pipeline", etc.).
        event:       Event type ("start", "complete", "error", etc.).
        duration_ms: Wall-clock duration in milliseconds (optional).
        tokens_in:   Input token count (optional).
        tokens_out:  Output token count (optional).
        metadata:    Arbitrary extra fields (optional).
    """
    if _log_path is None:
        return

    record: dict = {
        "run_id": run_id,
        "agent": agent,
        "stage": stage,
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if duration_ms is not None:
        record["duration_ms"] = duration_ms
    if tokens_in is not None:
        record["tokens_in"] = tokens_in
    if tokens_out is not None:
        record["tokens_out"] = tokens_out
    if metadata is not None:
        record["metadata"] = metadata

    try:
        with open(_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        logging.warning("log_event: failed to write event: %s", e)
