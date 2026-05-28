"""
Tests for src/observability/events.py.

Covers:
- log_event() is a no-op before configure_observability() is called
- configure_observability() creates the log directory if missing
- log_event() writes a valid JSON line to the log file
- Each written line is parseable with json.loads()
- None fields are omitted from the written record
- run_id, agent, stage, event, timestamp are always present
- log_event() does not raise when the log file is not writable
"""

import json
import os
import pytest
from unittest.mock import patch


def _reset_module():
    """Reset the module-level _log_path to None between tests."""
    import observability.events as ev
    ev._log_path = None


def test_log_event_is_noop_before_configure(tmp_path):
    """log_event() does nothing if configure_observability() has not been called."""
    _reset_module()
    # Should not raise, and no file should be created
    from observability.events import log_event
    log_event("run1", "researcher", "research", "complete")
    # No log file should have been created anywhere
    assert list(tmp_path.glob("*.jsonl")) == []


def test_configure_creates_log_directory(tmp_path):
    """configure_observability() creates the log directory when it does not exist."""
    _reset_module()
    from observability.events import configure_observability
    log_dir = str(tmp_path / "nested" / "logs")
    assert not os.path.exists(log_dir)
    configure_observability(log_dir=log_dir)
    assert os.path.isdir(log_dir)


def test_log_event_writes_json_line(tmp_path):
    """log_event() writes a line to the log file after configure_observability()."""
    _reset_module()
    from observability.events import configure_observability, log_event
    configure_observability(log_dir=str(tmp_path))
    log_event("run1", "researcher", "research", "complete")
    log_files = list(tmp_path.glob("events_*.jsonl"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8").strip()
    assert content != ""


def test_log_event_line_is_parseable(tmp_path):
    """Each line written by log_event() is valid JSON."""
    _reset_module()
    from observability.events import configure_observability, log_event
    configure_observability(log_dir=str(tmp_path))
    log_event("run1", "orchestrator", "pipeline", "start", metadata={"topic": "fusion"})
    log_files = list(tmp_path.glob("events_*.jsonl"))
    for line in log_files[0].read_text(encoding="utf-8").splitlines():
        parsed = json.loads(line)
        assert isinstance(parsed, dict)


def test_log_event_omits_none_fields(tmp_path):
    """None-valued optional fields are not written to the log record."""
    _reset_module()
    from observability.events import configure_observability, log_event
    configure_observability(log_dir=str(tmp_path))
    log_event("run1", "editor", "edit", "complete")  # all optionals omitted
    log_files = list(tmp_path.glob("events_*.jsonl"))
    record = json.loads(log_files[0].read_text(encoding="utf-8").strip())
    assert "duration_ms" not in record
    assert "tokens_in" not in record
    assert "tokens_out" not in record
    assert "metadata" not in record


def test_log_event_always_includes_required_fields(tmp_path):
    """run_id, agent, stage, event, and timestamp are always present."""
    _reset_module()
    from observability.events import configure_observability, log_event
    configure_observability(log_dir=str(tmp_path))
    log_event("myrun", "verifier", "verify", "complete", duration_ms=250)
    log_files = list(tmp_path.glob("events_*.jsonl"))
    record = json.loads(log_files[0].read_text(encoding="utf-8").strip())
    assert record["run_id"] == "myrun"
    assert record["agent"] == "verifier"
    assert record["stage"] == "verify"
    assert record["event"] == "complete"
    assert "timestamp" in record


def test_log_event_does_not_raise_on_write_failure(tmp_path):
    """log_event() swallows IOError and does not raise when the log file is not writable."""
    _reset_module()
    from observability.events import configure_observability, log_event
    configure_observability(log_dir=str(tmp_path))
    with patch("builtins.open", side_effect=IOError("permission denied")):
        # Must not raise
        log_event("run1", "researcher", "research", "complete")


# ── Agent boundary tests ──────────────────────────────────────────────────────

def test_researcher_calls_log_event_on_complete():
    """log_event is called with agent='researcher' and event='complete' after research()."""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    from unittest.mock import MagicMock, call
    from llm.base import LLMResponse
    from agent.base import Agent
    from agent.researcher import research
    from evidence.schema import ResearchResult

    mock_llm = MagicMock()
    mock_llm.chat.return_value = LLMResponse(type="text", content="The answer is 42.")

    agent = Agent(
        name="researcher",
        role="Researcher",
        description="Test researcher",
        llm=mock_llm,
        system_prompt="You are a researcher.",
        tools=(),
        max_iterations=5,
    )

    with patch("agent.researcher.log_event") as mock_log, \
         patch("agent.researcher.execute_tool_with_sources"):
        result = research(agent, "What is the answer?", max_tokens=512)

    mock_log.assert_called_once()
    call_kwargs = mock_log.call_args
    assert call_kwargs[1]["agent"] == "researcher" or call_kwargs[0][1] == "researcher"
    assert call_kwargs[1]["event"] == "complete" or call_kwargs[0][3] == "complete"
