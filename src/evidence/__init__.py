"""
Evidence layer for the research-agent pipeline.

Exports the TypedDict schemas used for structured claim tracking
and provenance file generation.
"""

from .schema import EvidenceSource, EvidenceClaim, ProvenanceReport

__all__ = ["EvidenceSource", "EvidenceClaim", "ProvenanceReport"]
