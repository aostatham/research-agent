"""
Tests for eval/harness.py — EvalResult, compute_eval_result, save/load, compare.

Verifies:
  - EvalResult can be constructed with all fields
  - compute_eval_result populates report_line_coverage correctly
  - compute_eval_result returns 0.0 coverage when claim_count is 0
  - save_eval_result writes a valid JSON line to the file
  - load_eval_results returns EvalResult objects matching what was saved
  - load_eval_results returns empty list when file absent
  - compare_phases returns correct delta values
  - compare_phases returns None when a phase has no results for the topic
"""

import dataclasses
import json
import os
import pytest
from eval.harness import (
    EvalResult,
    compute_eval_result,
    save_eval_result,
    load_eval_results,
    compare_phases,
    print_comparison,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_result(
    topic="nuclear fusion energy",
    phase="Phase E",
    timestamp="2026-01-01T00:00:00+00:00",
    **overrides,
) -> EvalResult:
    defaults = dict(
        topic=topic,
        run_id="run-001",
        timestamp=timestamp,
        phase=phase,
        report_chars=1000,
        question_count=5,
        search_count=10,
        claim_count=20,
        verified_claims=8,
        disputed_claims=2,
        unverified_claims=10,
        anchored_claims=12,
        paraphrased_claims=3,
        omitted_claims=3,
        not_attempted_claims=2,
        report_line_coverage=0.75,
        avg_confidence=0.65,
        duration_seconds=45.0,
    )
    defaults.update(overrides)
    return EvalResult(**defaults)


def _make_claims(*statuses) -> list:
    return [{"synthesis_status": s, "confidence": 0.5} for s in statuses]


def _make_quality_metrics(verified=5, disputed=1, unverified=4, confidence=0.6) -> dict:
    return {
        "verified_claims": verified,
        "disputed_claims": disputed,
        "unverified_claims": unverified,
        "confidence": confidence,
    }


# ── EvalResult construction ────────────────────────────────────────────────────

def test_eval_result_can_be_constructed_with_all_fields():
    """EvalResult accepts all fields and stores them correctly."""
    result = _make_result()
    assert result.topic == "nuclear fusion energy"
    assert result.phase == "Phase E"
    assert result.claim_count == 20
    assert result.report_line_coverage == 0.75


# ── compute_eval_result ───────────────────────────────────────────────────────

def test_compute_eval_result_coverage_anchored_plus_paraphrased_over_total():
    """report_line_coverage = (anchored + paraphrased) / total claims."""
    claims = _make_claims(
        "anchored", "anchored", "paraphrased",  # 3 toward numerator
        "omitted", "not_attempted",              # 2 not in numerator
    )
    result = compute_eval_result(
        topic="t", run_id="r", report="x" * 100, claims=claims,
        quality_metrics=_make_quality_metrics(),
        search_count=5, question_count=3, duration_seconds=10.0, phase="P",
    )
    assert result.report_line_coverage == pytest.approx(3 / 5)


def test_compute_eval_result_coverage_zero_when_no_claims():
    """report_line_coverage is 0.0 when claim_count is 0."""
    result = compute_eval_result(
        topic="t", run_id="r", report="x", claims=[],
        quality_metrics=_make_quality_metrics(),
        search_count=0, question_count=0, duration_seconds=1.0, phase="P",
    )
    assert result.report_line_coverage == 0.0
    assert result.claim_count == 0


def test_compute_eval_result_populates_verification_counts():
    """verified/disputed/unverified_claims come from quality_metrics."""
    result = compute_eval_result(
        topic="t", run_id="r", report="x", claims=_make_claims("anchored"),
        quality_metrics=_make_quality_metrics(verified=7, disputed=2, unverified=1),
        search_count=0, question_count=0, duration_seconds=1.0, phase="P",
    )
    assert result.verified_claims == 7
    assert result.disputed_claims == 2
    assert result.unverified_claims == 1


def test_compute_eval_result_synthesis_status_counts():
    """anchored/paraphrased/omitted/not_attempted counts are correct."""
    claims = _make_claims("anchored", "anchored", "paraphrased", "omitted", "not_attempted")
    result = compute_eval_result(
        topic="t", run_id="r", report="x", claims=claims,
        quality_metrics=_make_quality_metrics(),
        search_count=0, question_count=0, duration_seconds=1.0, phase="P",
    )
    assert result.anchored_claims == 2
    assert result.paraphrased_claims == 1
    assert result.omitted_claims == 1
    assert result.not_attempted_claims == 1


def test_compute_eval_result_report_chars():
    """report_chars is len(report)."""
    report = "x" * 4200
    result = compute_eval_result(
        topic="t", run_id="r", report=report, claims=[],
        quality_metrics=_make_quality_metrics(),
        search_count=0, question_count=0, duration_seconds=1.0, phase="P",
    )
    assert result.report_chars == 4200


# ── save_eval_result ──────────────────────────────────────────────────────────

def test_save_eval_result_writes_valid_json_line(tmp_path):
    """save_eval_result appends exactly one valid JSON line to eval_results.jsonl."""
    result = _make_result()
    path = save_eval_result(result, eval_dir=str(tmp_path))
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["topic"] == "nuclear fusion energy"
    assert parsed["phase"] == "Phase E"


def test_save_eval_result_returns_path_to_file(tmp_path):
    """save_eval_result returns the path to the jsonl file."""
    result = _make_result()
    path = save_eval_result(result, eval_dir=str(tmp_path))
    assert path.endswith("eval_results.jsonl")


def test_save_eval_result_creates_eval_dir(tmp_path):
    """save_eval_result creates eval_dir if it does not exist."""
    eval_dir = str(tmp_path / "nested" / "eval")
    save_eval_result(_make_result(), eval_dir=eval_dir)
    assert os.path.exists(eval_dir)


def test_save_eval_result_appends_multiple_lines(tmp_path):
    """save_eval_result appends; existing lines are not overwritten."""
    save_eval_result(_make_result(phase="Phase D"), eval_dir=str(tmp_path))
    save_eval_result(_make_result(phase="Phase E"), eval_dir=str(tmp_path))
    path = os.path.join(str(tmp_path), "eval_results.jsonl")
    with open(path, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    assert len(lines) == 2


# ── load_eval_results ─────────────────────────────────────────────────────────

def test_load_eval_results_returns_empty_list_when_file_absent(tmp_path):
    """load_eval_results returns [] when eval_results.jsonl does not exist."""
    results = load_eval_results(eval_dir=str(tmp_path))
    assert results == []


def test_load_eval_results_returns_eval_result_objects(tmp_path):
    """load_eval_results returns a list of EvalResult instances."""
    save_eval_result(_make_result(), eval_dir=str(tmp_path))
    results = load_eval_results(eval_dir=str(tmp_path))
    assert len(results) == 1
    assert isinstance(results[0], EvalResult)


def test_load_eval_results_matches_saved_data(tmp_path):
    """Loaded EvalResult fields match the saved values."""
    original = _make_result(report_chars=9999, avg_confidence=0.77)
    save_eval_result(original, eval_dir=str(tmp_path))
    loaded = load_eval_results(eval_dir=str(tmp_path))[0]
    assert loaded.report_chars == 9999
    assert loaded.avg_confidence == pytest.approx(0.77)
    assert loaded.topic == original.topic
    assert loaded.phase == original.phase


def test_load_eval_results_returns_all_saved_results(tmp_path):
    """load_eval_results returns one EvalResult per saved line."""
    for i in range(3):
        save_eval_result(_make_result(run_id=f"run-{i}"), eval_dir=str(tmp_path))
    results = load_eval_results(eval_dir=str(tmp_path))
    assert len(results) == 3


# ── compare_phases ─────────────────────────────────────────────────────────────

def test_compare_phases_returns_correct_deltas(tmp_path):
    """compare_phases computes delta = b - a for each numeric field."""
    r_a = _make_result(phase="Phase D", timestamp="2026-01-01T00:00:00+00:00",
                       report_chars=800, claim_count=10, avg_confidence=0.5)
    r_b = _make_result(phase="Phase E", timestamp="2026-02-01T00:00:00+00:00",
                       report_chars=1200, claim_count=15, avg_confidence=0.7)
    results = [r_a, r_b]

    comparison = compare_phases(results, "nuclear fusion energy", "Phase D", "Phase E")
    assert comparison is not None
    assert comparison["report_chars"]["a"] == 800
    assert comparison["report_chars"]["b"] == 1200
    assert comparison["report_chars"]["delta"] == 400
    assert comparison["avg_confidence"]["delta"] == pytest.approx(0.2)


def test_compare_phases_returns_none_when_phase_a_absent():
    """compare_phases returns None when phase_a has no result for the topic."""
    results = [_make_result(phase="Phase E")]
    assert compare_phases(results, "nuclear fusion energy", "Phase D", "Phase E") is None


def test_compare_phases_returns_none_when_phase_b_absent():
    """compare_phases returns None when phase_b has no result for the topic."""
    results = [_make_result(phase="Phase D")]
    assert compare_phases(results, "nuclear fusion energy", "Phase D", "Phase E") is None


def test_compare_phases_returns_none_when_topic_absent():
    """compare_phases returns None when neither phase has a result for the topic."""
    results = [
        _make_result(topic="other topic", phase="Phase D"),
        _make_result(topic="other topic", phase="Phase E"),
    ]
    assert compare_phases(results, "nuclear fusion energy", "Phase D", "Phase E") is None


def test_compare_phases_uses_most_recent_by_timestamp():
    """When multiple results exist for a phase, the most recent timestamp wins."""
    old = _make_result(phase="Phase D", timestamp="2026-01-01T00:00:00+00:00",
                       report_chars=500)
    new = _make_result(phase="Phase D", timestamp="2026-03-01T00:00:00+00:00",
                       report_chars=900)
    r_b = _make_result(phase="Phase E", report_chars=1000)
    results = [old, new, r_b]

    comparison = compare_phases(results, "nuclear fusion energy", "Phase D", "Phase E")
    assert comparison["report_chars"]["a"] == 900
