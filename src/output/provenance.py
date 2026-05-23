"""
Provenance file generation for the research-agent pipeline.

Writes a .provenance.json file alongside each report, recording the
claims made, their sources, confidence scores, and quality metrics.

In Part 1, claims are placeholder objects built directly from raw
research results. Full claim extraction and confidence scoring
arrive in Part 2.

Public API:
  write_provenance_file()    — write .provenance.json next to the report
  build_quality_metrics()    — compute aggregate metrics from a claims list
  classify_source_type()     — classify a URL into government/academic/news/blog
  build_placeholder_claims() — build minimal claims from raw results/sources
"""

import json
import os
from datetime import datetime

from evidence.schema import EvidenceSource, EvidenceClaim, ProvenanceReport


def write_provenance_file(
    output_path: str,
    claims: list,
    quality_metrics: dict
) -> str:
    """
    Write a .provenance.json file alongside the report.

    Derives the provenance path by replacing the report extension:
      output/nuclear_fusion.md -> output/nuclear_fusion.provenance.json

    Args:
        output_path:     Path to the saved report file (any extension)
        claims:          List of EvidenceClaim dicts
        quality_metrics: Dict from build_quality_metrics()

    Returns:
        Path to the written provenance file
    """
    base = os.path.splitext(output_path)[0]
    prov_path = f"{base}.provenance.json"

    os.makedirs(os.path.dirname(prov_path) or ".", exist_ok=True)

    report = ProvenanceReport(
        report_file=os.path.basename(output_path),
        generated=datetime.utcnow().isoformat(),
        quality_metrics=quality_metrics,
        claims=claims
    )

    with open(prov_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return prov_path


def build_quality_metrics(claims: list) -> dict:
    """
    Compute quality metrics from a list of EvidenceClaim objects.

    Returns a dict with:
      coverage         — verified_claims / total_claims (0.0 if no claims)
      confidence       — mean of all claim confidence scores (0.0 if no claims)
      contradictions   — total count across all claims
      verified_claims  — count where verification_status == "verified"
      unverified_claims — count where verification_status == "unverified"
    """
    if not claims:
        return {
            "coverage": 0.0,
            "confidence": 0.0,
            "contradictions": 0,
            "verified_claims": 0,
            "unverified_claims": 0,
        }

    verified = sum(1 for c in claims if c["verification_status"] == "verified")
    unverified = sum(1 for c in claims if c["verification_status"] == "unverified")
    total = len(claims)
    contradictions = sum(len(c["contradictions"]) for c in claims)
    confidence = sum(c["confidence"] for c in claims) / total
    coverage = verified / total

    return {
        "coverage": coverage,
        "confidence": confidence,
        "contradictions": contradictions,
        "verified_claims": verified,
        "unverified_claims": unverified,
    }


def classify_source_type(url: str) -> str:
    """
    Classify a URL into a source type based on domain patterns.

    Rules (checked in order):
      .gov or .mil                             -> government
      .edu or known academic domains           -> academic
        (arxiv.org, pubmed, nature.com, science.org,
         springer, wiley, jstor)
      known news domains                       -> news
        (bbc., reuters.com, apnews.com, nytimes.com,
         theguardian.com, wsj.com, ft.com, economist.com)
      everything else                          -> blog
    """
    u = url.lower()

    if ".gov" in u or ".mil" in u:
        return "government"

    academic_markers = [
        ".edu", "arxiv.org", "pubmed", "nature.com", "science.org",
        "springer", "wiley", "jstor",
    ]
    if any(m in u for m in academic_markers):
        return "academic"

    news_markers = [
        "bbc.", "reuters.com", "apnews.com", "nytimes.com",
        "theguardian.com", "wsj.com", "ft.com", "economist.com",
    ]
    if any(m in u for m in news_markers):
        return "news"

    return "blog"


def build_placeholder_claims(results: dict, sources: dict) -> list:
    """
    Build minimal EvidenceClaim objects from existing results and sources.

    Used in Part 1 before full claim extraction is implemented.
    Each question/answer pair becomes one placeholder claim.

    Defaults:
      confidence          = 0.5  (unscored)
      verification_status = "unverified"
      evidence_type       = "qualitative"
      report_line         = None

    Args:
        results: {question: answer} dict from orchestrator.run()
        sources: {question: [{"title": str, "url": str}]} from orchestrator.run()

    Returns:
        List of EvidenceClaim dicts (one per question)
    """
    now = datetime.utcnow().isoformat()
    claims = []

    for i, (question, answer) in enumerate(results.items(), start=1):
        question_sources = sources.get(question, [])
        primary_url = question_sources[0]["url"] if question_sources else ""

        evidence_sources = [
            EvidenceSource(
                title=s.get("title", ""),
                url=s.get("url", ""),
                source_type=classify_source_type(s.get("url", "")),
                retrieved=now,
            )
            for s in question_sources
        ]

        claim = EvidenceClaim(
            id=i,
            claim=answer,
            source=primary_url,
            confidence=0.5,
            contradictions=[],
            evidence_type="qualitative",
            verification_status="unverified",
            timestamp=now,
            sources=evidence_sources,
            report_line=None,
        )
        claims.append(claim)

    return claims
