"""
Tests for output/provenance.py — classify_source_type(), build_quality_metrics(),
write_provenance_file(), and build_placeholder_claims().

Verifies:
  - classify_source_type(): government (.gov/.mil), academic (arxiv etc),
    news (bbc etc), blog (unknown domain)
  - build_quality_metrics(): empty input zeros, coverage calculation,
    mean confidence, contradiction count
  - write_provenance_file(): file creation, valid JSON output, correct
    .provenance.json path, quality_metrics embedded in output
  - build_placeholder_claims(): one claim per question, correct defaults
    (confidence=0.5, unverified, qualitative, report_line=None)

All tests are unit tests — no external API calls.
"""

import json
import os
import pytest


# ── classify_source_type() tests ──────────────────────────────────────────────

def test_classify_source_type_government():
    """A .gov URL is classified as government."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://energy.gov/nuclear") == "government"


def test_classify_source_type_military():
    """A .mil URL is classified as government."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.defense.mil/news") == "government"


def test_classify_source_type_academic():
    """An arxiv.org URL is classified as academic."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://arxiv.org/abs/2301.00001") == "academic"


def test_classify_source_type_academic_edu():
    """.edu URLs are classified as academic."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://mit.edu/research/fusion") == "academic"


def test_classify_source_type_news():
    """A BBC URL is classified as news."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.bbc.co.uk/news/science") == "news"


def test_classify_source_type_news_reuters():
    """A Reuters URL is classified as news."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.reuters.com/technology") == "news"


def test_classify_source_type_blog():
    """An unrecognised domain is classified as blog."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://someblog.com/post/fusion") == "blog"


# ── build_quality_metrics() tests ─────────────────────────────────────────────

def test_build_quality_metrics_empty():
    """Empty claims list returns all-zero metrics."""
    from output.provenance import build_quality_metrics
    metrics = build_quality_metrics([])
    assert metrics["coverage"] == 0.0
    assert metrics["confidence"] == 0.0
    assert metrics["contradictions"] == 0
    assert metrics["verified_claims"] == 0
    assert metrics["unverified_claims"] == 0


def test_build_quality_metrics_all_verified():
    """All verified claims produce coverage of 1.0."""
    from output.provenance import build_quality_metrics
    claims = [
        {"verification_status": "verified", "confidence": 0.9, "contradictions": []},
        {"verification_status": "verified", "confidence": 0.8, "contradictions": []},
    ]
    metrics = build_quality_metrics(claims)
    assert metrics["coverage"] == 1.0
    assert metrics["verified_claims"] == 2


def test_build_quality_metrics_confidence():
    """Mean confidence is computed correctly."""
    from output.provenance import build_quality_metrics
    claims = [
        {"verification_status": "unverified", "confidence": 0.4, "contradictions": []},
        {"verification_status": "unverified", "confidence": 0.6, "contradictions": []},
    ]
    metrics = build_quality_metrics(claims)
    assert metrics["confidence"] == pytest.approx(0.5)


def test_build_quality_metrics_contradictions():
    """Contradictions are summed across all claims."""
    from output.provenance import build_quality_metrics
    claims = [
        {"verification_status": "unverified", "confidence": 0.5, "contradictions": ["a", "b"]},
        {"verification_status": "unverified", "confidence": 0.5, "contradictions": ["c"]},
    ]
    metrics = build_quality_metrics(claims)
    assert metrics["contradictions"] == 3


def test_build_quality_metrics_partial_verified():
    """Coverage equals verified / total."""
    from output.provenance import build_quality_metrics
    claims = [
        {"verification_status": "verified", "confidence": 0.8, "contradictions": []},
        {"verification_status": "unverified", "confidence": 0.5, "contradictions": []},
        {"verification_status": "unverified", "confidence": 0.5, "contradictions": []},
    ]
    metrics = build_quality_metrics(claims)
    assert metrics["coverage"] == pytest.approx(1 / 3)
    assert metrics["unverified_claims"] == 2


# ── write_provenance_file() tests ─────────────────────────────────────────────

def test_write_provenance_file_creates_file(tmp_path, monkeypatch):
    """write_provenance_file() creates the .provenance.json file."""
    monkeypatch.chdir(tmp_path)
    from output.provenance import write_provenance_file
    os.makedirs(tmp_path / "output", exist_ok=True)
    prov_path = write_provenance_file("output/nuclear_fusion.md", [], {"coverage": 0.0})
    assert os.path.exists(prov_path)


def test_write_provenance_file_valid_json(tmp_path, monkeypatch):
    """The written file is valid JSON."""
    monkeypatch.chdir(tmp_path)
    from output.provenance import write_provenance_file
    os.makedirs(tmp_path / "output", exist_ok=True)
    prov_path = write_provenance_file("output/nuclear_fusion.md", [], {})
    with open(prov_path) as f:
        data = json.load(f)
    assert isinstance(data, dict)


def test_write_provenance_file_correct_path(tmp_path, monkeypatch):
    """The provenance file path ends with .provenance.json."""
    monkeypatch.chdir(tmp_path)
    from output.provenance import write_provenance_file
    os.makedirs(tmp_path / "output", exist_ok=True)
    prov_path = write_provenance_file("output/nuclear_fusion.md", [], {})
    assert prov_path.endswith(".provenance.json")
    assert "nuclear_fusion" in prov_path


def test_write_provenance_file_contains_metrics(tmp_path, monkeypatch):
    """quality_metrics are embedded in the output JSON."""
    monkeypatch.chdir(tmp_path)
    from output.provenance import write_provenance_file
    os.makedirs(tmp_path / "output", exist_ok=True)
    metrics = {"coverage": 0.8, "confidence": 0.7}
    prov_path = write_provenance_file("output/nuclear_fusion.md", [], metrics)
    with open(prov_path) as f:
        data = json.load(f)
    assert "quality_metrics" in data
    assert data["quality_metrics"]["coverage"] == pytest.approx(0.8)


def test_write_provenance_file_html_path(tmp_path, monkeypatch):
    """Works for HTML report paths too (.html -> .provenance.json)."""
    monkeypatch.chdir(tmp_path)
    from output.provenance import write_provenance_file
    os.makedirs(tmp_path / "output", exist_ok=True)
    prov_path = write_provenance_file("output/nuclear_fusion.html", [], {})
    assert prov_path == "output/nuclear_fusion.provenance.json"


# ── build_placeholder_claims() tests ─────────────────────────────────────────

def test_build_placeholder_claims_count():
    """One claim is created per question."""
    from output.provenance import build_placeholder_claims
    results = {"Q1": "Answer 1", "Q2": "Answer 2", "Q3": "Answer 3"}
    claims = build_placeholder_claims(results, {})
    assert len(claims) == 3


def test_build_placeholder_claims_defaults():
    """Placeholder claims have correct default values."""
    from output.provenance import build_placeholder_claims
    results = {"What is fusion?": "Fusion combines nuclei."}
    claims = build_placeholder_claims(results, {})
    c = claims[0]
    assert c["confidence"] == 0.5
    assert c["verification_status"] == "unverified"
    assert c["evidence_type"] == "qualitative"
    assert c["report_line"] is None


def test_build_placeholder_claims_ids_sequential():
    """Claims are numbered sequentially from 1."""
    from output.provenance import build_placeholder_claims
    results = {"Q1": "A1", "Q2": "A2"}
    claims = build_placeholder_claims(results, {})
    assert claims[0]["id"] == 1
    assert claims[1]["id"] == 2


def test_build_placeholder_claims_sources_attached():
    """Sources from the sources dict are attached to the corresponding claim."""
    from output.provenance import build_placeholder_claims
    results = {"What is fusion?": "Answer."}
    sources = {
        "What is fusion?": [
            {"title": "Fusion Basics", "url": "https://example.com/fusion"}
        ]
    }
    claims = build_placeholder_claims(results, sources)
    assert len(claims[0]["sources"]) == 1
    assert claims[0]["source"] == "https://example.com/fusion"


def test_build_placeholder_claims_empty_sources():
    """Claims with no sources have an empty sources list and empty primary URL."""
    from output.provenance import build_placeholder_claims
    results = {"Q1": "Answer."}
    claims = build_placeholder_claims(results, {})
    assert claims[0]["sources"] == []
    assert claims[0]["source"] == ""
