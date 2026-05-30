"""
Eval harness for the research pipeline.

Records pipeline quality metrics after each phase using fixed reference
topics. Enables phase-over-phase comparison via save, load, and compare
functions.

Public API:
  compute_eval_result()  — build an EvalResult from pipeline outputs
  save_eval_result()     — append result as a JSON line to eval_results.jsonl
  load_eval_results()    — read all saved results from eval_results.jsonl
  compare_phases()       — diff two named phases for a single topic
  print_comparison()     — print a readable table to stdout
"""

import dataclasses
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


REFERENCE_TOPICS = [
    "nuclear fusion energy",
    "electrosmith daisy seed",
    "large language model training",
]


@dataclass
class EvalResult:
    """Snapshot of pipeline quality metrics for one run."""
    topic: str
    run_id: str
    timestamp: str
    phase: str
    report_chars: int
    question_count: int
    search_count: int
    claim_count: int
    verified_claims: int
    disputed_claims: int
    unverified_claims: int
    anchored_claims: int
    paraphrased_claims: int
    omitted_claims: int
    not_attempted_claims: int
    report_line_coverage: float
    avg_confidence: float
    duration_seconds: float


def compute_eval_result(
    topic: str,
    run_id: str,
    report: str,
    claims: list,
    quality_metrics: dict,
    search_count: int,
    question_count: int,
    duration_seconds: float,
    phase: str,
) -> EvalResult:
    """
    Build an EvalResult from pipeline outputs.

    Args:
        topic:            Research topic string.
        run_id:           Run identifier from the orchestrator.
        report:           Final synthesised report text.
        claims:           Flat list of EvidenceClaim dicts from build_claims_from_results().
        quality_metrics:  Dict from build_quality_metrics() — keys: verified_claims,
                          disputed_claims, unverified_claims, confidence.
        search_count:     Number of web searches performed (orchestrator.search_count).
        question_count:   Number of research questions answered.
        duration_seconds: Wall-clock time for the full pipeline run.
        phase:            Label for this phase (e.g. "Phase E").

    Returns:
        Populated EvalResult.
    """
    claim_count = len(claims)
    anchored = sum(1 for c in claims if c.get("synthesis_status") == "anchored")
    paraphrased = sum(1 for c in claims if c.get("synthesis_status") == "paraphrased")
    omitted = sum(1 for c in claims if c.get("synthesis_status") == "omitted")
    not_attempted = sum(1 for c in claims if c.get("synthesis_status") == "not_attempted")

    coverage = (anchored + paraphrased) / claim_count if claim_count > 0 else 0.0

    return EvalResult(
        topic=topic,
        run_id=run_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        phase=phase,
        report_chars=len(report),
        question_count=question_count,
        search_count=search_count,
        claim_count=claim_count,
        verified_claims=quality_metrics.get("verified_claims", 0),
        disputed_claims=quality_metrics.get("disputed_claims", 0),
        unverified_claims=quality_metrics.get("unverified_claims", 0),
        anchored_claims=anchored,
        paraphrased_claims=paraphrased,
        omitted_claims=omitted,
        not_attempted_claims=not_attempted,
        report_line_coverage=coverage,
        avg_confidence=quality_metrics.get("confidence", 0.0),
        duration_seconds=duration_seconds,
    )


def save_eval_result(result: EvalResult, eval_dir: str = "output/.eval") -> str:
    """
    Append an EvalResult as a JSON line to eval_dir/eval_results.jsonl.

    Creates eval_dir if it does not exist.

    Args:
        result:   EvalResult to persist.
        eval_dir: Directory to write to (default: output/.eval).

    Returns:
        Absolute path to the eval_results.jsonl file.
    """
    os.makedirs(eval_dir, exist_ok=True)
    path = os.path.join(eval_dir, "eval_results.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(dataclasses.asdict(result)) + "\n")
    return path


def load_eval_results(eval_dir: str = "output/.eval") -> list:
    """
    Read all saved EvalResult objects from eval_dir/eval_results.jsonl.

    Args:
        eval_dir: Directory containing eval_results.jsonl (default: output/.eval).

    Returns:
        List of EvalResult objects in file order. Empty list if file absent or empty.
    """
    path = os.path.join(eval_dir, "eval_results.jsonl")
    if not os.path.exists(path):
        return []
    results = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            results.append(EvalResult(**json.loads(line)))
    return results


def compare_phases(
    results: list,
    topic: str,
    phase_a: str,
    phase_b: str,
) -> Optional[dict]:
    """
    Diff two named phases for a single topic.

    Finds the most recent result for (topic, phase_a) and (topic, phase_b)
    by timestamp. Returns a comparison dict or None if either phase has no
    result for the topic.

    Args:
        results: List of EvalResult objects (from load_eval_results()).
        topic:   Topic string to filter on.
        phase_a: Label for the baseline phase.
        phase_b: Label for the comparison phase.

    Returns:
        Dict with keys: topic, phase_a, phase_b, and for each numeric metric
        field a sub-dict with keys a, b, delta (b minus a).
        None if either phase has no result for the topic.
    """
    def _latest(phase: str) -> Optional[EvalResult]:
        matching = [r for r in results if r.topic == topic and r.phase == phase]
        if not matching:
            return None
        return max(matching, key=lambda r: r.timestamp)

    result_a = _latest(phase_a)
    result_b = _latest(phase_b)
    if result_a is None or result_b is None:
        return None

    numeric_fields = [
        f.name for f in dataclasses.fields(EvalResult)
        if f.type in (int, float, "int", "float")
    ]

    comparison: dict = {"topic": topic, "phase_a": phase_a, "phase_b": phase_b}
    for field in numeric_fields:
        val_a = getattr(result_a, field)
        val_b = getattr(result_b, field)
        comparison[field] = {"a": val_a, "b": val_b, "delta": val_b - val_a}

    return comparison


def print_comparison(comparison: dict) -> None:
    """
    Print a readable phase-comparison table to stdout.

    Args:
        comparison: Dict from compare_phases() — must not be None.
    """
    topic = comparison["topic"]
    phase_a = comparison["phase_a"]
    phase_b = comparison["phase_b"]

    print(f"\nTopic: {topic}")
    print(f"{'Metric':<30}  {phase_a:>12}  {phase_b:>12}  {'Delta':>10}")
    print("-" * 70)

    skip = {"topic", "phase_a", "phase_b"}
    for key, vals in comparison.items():
        if key in skip:
            continue
        val_a = vals["a"]
        val_b = vals["b"]
        delta = vals["delta"]
        sign = "+" if delta > 0 else ""
        if isinstance(val_a, float):
            print(f"  {key:<28}  {val_a:>12.3f}  {val_b:>12.3f}  {sign}{delta:>9.3f}")
        else:
            print(f"  {key:<28}  {val_a:>12}  {val_b:>12}  {sign}{delta:>9}")
