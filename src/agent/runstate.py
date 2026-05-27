"""
RunState dataclass and checkpoint persistence for the research pipeline.

RunState tracks the current stage and accumulated results across the full
pipeline (decompose → research → reflect → synthesise → edit → complete).
Checkpoints are written to output/.checkpoints/{run_id}.json after each
stage so interrupted runs can be resumed with a consistent run_id.

  RunState             — mutable dataclass capturing full pipeline state
  save_checkpoint()    — serialise and write state to disk
  load_checkpoint()    — deserialise state from disk by run_id
"""

import dataclasses
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RunState:
    """
    Full pipeline state for one research run.

    accumulated_research_results stores dicts (dataclasses.asdict() output
    of ResearchResult objects) rather than ResearchResult instances so the
    state is directly JSON-serialisable.
    """

    run_id: str
    current_stage: str                   # "decompose" | "research" | "reflect"
                                         # | "synthesise" | "edit" | "complete"
    topic: str
    questions: list                      # list of str; populated after decompose
    accumulated_research_results: list   # list of dicts; grows through research
    report_text: str                     # set after synthesise; empty until then
    started_at: str                      # ISO8601 UTC timestamp
    last_checkpoint_at: str              # ISO8601 UTC timestamp; updated on save


def save_checkpoint(
    state: RunState,
    checkpoint_dir: str = "output/.checkpoints",
) -> str:
    """
    Serialise RunState to JSON and write to checkpoint_dir/{run_id}.json.

    Updates state.last_checkpoint_at to the current UTC time before writing.

    Args:
        state:          RunState instance to persist.
        checkpoint_dir: Directory to write checkpoints into (created if absent).

    Returns:
        Path to the written checkpoint file.
    """
    os.makedirs(checkpoint_dir, exist_ok=True)
    state.last_checkpoint_at = datetime.now(timezone.utc).isoformat()
    path = os.path.join(checkpoint_dir, f"{state.run_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dataclasses.asdict(state), f, indent=2)
    return path


def load_checkpoint(
    run_id: str,
    checkpoint_dir: str = "output/.checkpoints",
) -> RunState:
    """
    Deserialise a RunState from checkpoint_dir/{run_id}.json.

    Args:
        run_id:         The run_id string used when the checkpoint was saved.
        checkpoint_dir: Directory to search for the checkpoint file.

    Returns:
        RunState instance populated from the stored JSON.

    Raises:
        FileNotFoundError: If no checkpoint file exists for the given run_id.
    """
    path = os.path.join(checkpoint_dir, f"{run_id}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No checkpoint found for run_id '{run_id}' — expected at {path}"
        )
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return RunState(**data)
