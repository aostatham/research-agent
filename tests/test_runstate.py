"""
Tests for src/agent/runstate.py.

Covers:
- RunState construction with all fields
- save_checkpoint() writes a readable JSON file
- save_checkpoint() updates last_checkpoint_at on each call
- load_checkpoint() returns a RunState matching the saved state
- load_checkpoint() raises FileNotFoundError for unknown run_id
- round-trip: save then load produces identical field values
"""

import json
import os
import time
import pytest


def _make_state(run_id: str = "abc123") -> "RunState":
    from agent.runstate import RunState
    return RunState(
        run_id=run_id,
        current_stage="decompose",
        topic="nuclear fusion energy",
        questions=[],
        accumulated_research_results=[],
        report_text="",
        started_at="2026-01-01T00:00:00+00:00",
        last_checkpoint_at="",
    )


def test_runstate_construction_sets_all_fields():
    """RunState can be constructed with all required fields."""
    from agent.runstate import RunState
    state = _make_state("myrunid")
    assert state.run_id == "myrunid"
    assert state.current_stage == "decompose"
    assert state.topic == "nuclear fusion energy"
    assert state.questions == []
    assert state.accumulated_research_results == []
    assert state.report_text == ""
    assert state.started_at == "2026-01-01T00:00:00+00:00"
    assert state.last_checkpoint_at == ""


def test_save_checkpoint_writes_readable_json(tmp_path, monkeypatch):
    """save_checkpoint() writes a JSON file that can be read and parsed."""
    monkeypatch.chdir(tmp_path)
    from agent.runstate import save_checkpoint
    state = _make_state("run001")
    path = save_checkpoint(state, checkpoint_dir=str(tmp_path / "checkpoints"))
    assert os.path.exists(path)
    with open(path) as f:
        data = json.load(f)
    assert data["run_id"] == "run001"
    assert data["current_stage"] == "decompose"


def test_save_checkpoint_updates_last_checkpoint_at(tmp_path):
    """save_checkpoint() sets last_checkpoint_at to a non-empty timestamp."""
    from agent.runstate import save_checkpoint
    state = _make_state("run002")
    assert state.last_checkpoint_at == ""
    save_checkpoint(state, checkpoint_dir=str(tmp_path))
    assert state.last_checkpoint_at != ""


def test_save_checkpoint_timestamp_advances_on_second_call(tmp_path):
    """Each save_checkpoint() call updates last_checkpoint_at."""
    from agent.runstate import save_checkpoint
    state = _make_state("run003")
    save_checkpoint(state, checkpoint_dir=str(tmp_path))
    first_ts = state.last_checkpoint_at
    time.sleep(0.01)
    save_checkpoint(state, checkpoint_dir=str(tmp_path))
    second_ts = state.last_checkpoint_at
    assert second_ts >= first_ts


def test_load_checkpoint_returns_matching_runstate(tmp_path):
    """load_checkpoint() returns a RunState with the same field values as saved."""
    from agent.runstate import RunState, save_checkpoint, load_checkpoint
    state = RunState(
        run_id="loadme",
        current_stage="research",
        topic="daisy seed",
        questions=["What is it?", "How does it work?"],
        accumulated_research_results=[{"question": "What is it?", "answer": "A microcontroller"}],
        report_text="",
        started_at="2026-06-01T10:00:00+00:00",
        last_checkpoint_at="",
    )
    save_checkpoint(state, checkpoint_dir=str(tmp_path))
    loaded = load_checkpoint("loadme", checkpoint_dir=str(tmp_path))
    assert loaded.run_id == "loadme"
    assert loaded.current_stage == "research"
    assert loaded.topic == "daisy seed"
    assert loaded.questions == ["What is it?", "How does it work?"]
    assert loaded.accumulated_research_results == [{"question": "What is it?", "answer": "A microcontroller"}]


def test_load_checkpoint_raises_for_unknown_run_id(tmp_path):
    """load_checkpoint() raises FileNotFoundError when run_id has no checkpoint."""
    from agent.runstate import load_checkpoint
    with pytest.raises(FileNotFoundError, match="no-such-run"):
        load_checkpoint("no-such-run", checkpoint_dir=str(tmp_path))


def test_roundtrip_save_load_produces_identical_fields(tmp_path):
    """save then load restores every field value exactly."""
    from agent.runstate import RunState, save_checkpoint, load_checkpoint
    original = RunState(
        run_id="rt99",
        current_stage="synthesise",
        topic="large language models",
        questions=["Q1?", "Q2?"],
        accumulated_research_results=[],
        report_text="# Report\n\nSome content.",
        started_at="2026-05-01T08:00:00+00:00",
        last_checkpoint_at="",
    )
    save_checkpoint(original, checkpoint_dir=str(tmp_path))
    loaded = load_checkpoint("rt99", checkpoint_dir=str(tmp_path))
    assert loaded.run_id == original.run_id
    assert loaded.current_stage == original.current_stage
    assert loaded.topic == original.topic
    assert loaded.questions == original.questions
    assert loaded.accumulated_research_results == original.accumulated_research_results
    assert loaded.report_text == original.report_text
    assert loaded.started_at == original.started_at
    # last_checkpoint_at was updated by save_checkpoint — just verify it's non-empty
    assert loaded.last_checkpoint_at != ""


# ── get_resume_stage() ────────────────────────────────────────────────────────

def test_get_resume_stage_returns_correct_stage(tmp_path):
    """get_resume_stage() returns current_stage from an existing checkpoint."""
    from agent.runstate import save_checkpoint, get_resume_stage
    state = _make_state("res_run")
    state.current_stage = "reflect"
    save_checkpoint(state, checkpoint_dir=str(tmp_path))
    assert get_resume_stage("res_run", checkpoint_dir=str(tmp_path)) == "reflect"


def test_get_resume_stage_returns_none_for_unknown_run_id(tmp_path):
    """get_resume_stage() returns None when no checkpoint exists for run_id."""
    from agent.runstate import get_resume_stage
    assert get_resume_stage("no-such-run", checkpoint_dir=str(tmp_path)) is None


# ── restore_research_results() ────────────────────────────────────────────────

def test_restore_research_results_converts_dicts_to_instances():
    """restore_research_results() returns ResearchResult instances from stored dicts."""
    from agent.runstate import restore_research_results
    from evidence.schema import ResearchResult
    state = _make_state()
    state.accumulated_research_results = [{
        "question": "Q1?", "answer": "A1.", "claims": [],
        "sources": [], "message_history": [], "verification": "unverified",
    }]
    results = restore_research_results(state, ResearchResult)
    assert len(results) == 1
    assert isinstance(results[0], ResearchResult)
    assert results[0].question == "Q1?"
    assert results[0].answer == "A1."


def test_restore_research_results_returns_empty_list_for_empty_input():
    """restore_research_results() returns [] when accumulated_research_results is empty."""
    from agent.runstate import restore_research_results
    from evidence.schema import ResearchResult
    state = _make_state()
    assert restore_research_results(state, ResearchResult) == []


def test_restore_research_results_handles_missing_fields_with_defaults():
    """restore_research_results() fills in default values for missing optional fields."""
    from agent.runstate import restore_research_results
    from evidence.schema import ResearchResult
    state = _make_state()
    state.accumulated_research_results = [{"question": "Q?", "answer": "A."}]
    results = restore_research_results(state, ResearchResult)
    assert len(results) == 1
    assert results[0].claims == []
    assert results[0].sources == []
    assert results[0].verification == "unverified"
