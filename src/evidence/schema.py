"""
TypedDict schemas for the evidence layer.

All types are TypedDicts (not dataclasses or Pydantic) so they serialise
directly to/from JSON without a custom encoder.

  EvidenceSource    — a single cited source for a claim
  EvidenceClaim     — a single research claim with provenance metadata
  ProvenanceReport  — full provenance file written alongside a report
"""

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


class ProvenanceReport(TypedDict):
    """Top-level structure written to the .provenance.json file."""
    report_file: str
    generated: str
    quality_metrics: dict
    claims: list                 # list of EvidenceClaim
