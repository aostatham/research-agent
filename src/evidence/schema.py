"""
TypedDict schemas and dataclasses for the evidence layer.

TypedDicts serialise directly to/from JSON without a custom encoder.
ResearchResult is a dataclass (mutable) — it is an in-flight pipeline
object, not a serialisable report artefact.

  EvidenceSource    — a single cited source for a claim
  EvidenceClaim     — a single research claim with provenance metadata
  ProvenanceReport  — full provenance file written alongside a report
  ResearchResult    — structured output from a single Researcher run
"""

from dataclasses import dataclass, field
from typing import TypedDict, Optional


class EvidenceSource(TypedDict):
    """A single cited source attached to an EvidenceClaim."""
    title: str
    url: str
    source_type: str  # government | academic | news | reference |
                      # institutional | industry | video | forum | general
    retrieved: str      # ISO date string


class EvidenceClaim(TypedDict):
    """
    A single research claim with provenance metadata.

    confidence and verification_status are set to placeholder values
    in Part 1; full scoring arrives in Part 2.
    """
    id: int
    claim: str
    source: str                  # primary URL
    confidence: float            # 0.0 to 1.0
    contradictions: list
    evidence_type: str           # quantitative | qualitative | cited | inferred
    verification_status: str     # verified | unverified | disputed
    timestamp: str               # ISO date string
    sources: list                # list of EvidenceSource
    report_line: Optional[int]   # set during synthesis; None until then
    # "anchored" — matched via key phrase (Tier 1, language close to claim)
    # "paraphrased" — matched via number/overlap (Tier 2 or 3)
    # "omitted" — synthesiser explicitly listed as omitted
    # "not_attempted" — provenance not active or claims not passed to synthesiser
    synthesis_status: str        # set by annotate_report_lines or synthesiser


class ProvenanceReport(TypedDict):
    """Top-level structure written to the .provenance.json file."""
    report_file: str
    generated: str
    quality_metrics: dict
    claims: list                 # list of EvidenceClaim


@dataclass
class ResearchResult:
    """
    Structured output from a single Researcher agent run.

    Replaces the bare (answer, sources) tuple so downstream stages
    (Verifier, provenance pipeline) receive structured, typed data.
    message_history preserves the full researcher dialogue for the
    Verifier to inspect before concluding — see DECISIONS.md D008.
    """

    question: str
    answer: str
    claims: list = field(default_factory=list)    # list[EvidenceClaim]
    sources: list = field(default_factory=list)   # list[EvidenceSource]
    message_history: list = field(default_factory=list)  # list[dict]
    # "verified" | "refuted" | "unverified"
    verification: str = "unverified"
