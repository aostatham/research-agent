"""
Tests for output/provenance.py — classify_source_type(), build_quality_metrics(),
write_provenance_file(), extract_claims_from_answer(), build_claims_from_results().

Verifies:
  - classify_source_type(): government (.gov/.mil), academic (arxiv etc),
    news (bbc etc), general (unknown domain)
  - build_quality_metrics(): empty input zeros, coverage calculation,
    mean confidence, contradiction count
  - write_provenance_file(): file creation, valid JSON output, correct
    .provenance.json path, quality_metrics embedded in output
  - extract_claims_from_answer(): verification="verified" sets verification_status="verified";
    verification="refuted" sets verification_status="disputed";
    default (verification="unverified") sets verification_status="unverified"

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
    """An unrecognised domain is classified as general."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://someblog.com/post/fusion") == "general"


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


def test_build_quality_metrics_counts_disputed():
    """disputed_claims counts claims with verification_status == 'disputed'."""
    from output.provenance import build_quality_metrics
    claims = [
        {"verification_status": "verified", "confidence": 0.8, "contradictions": []},
        {"verification_status": "disputed", "confidence": 0.4, "contradictions": []},
        {"verification_status": "disputed", "confidence": 0.3, "contradictions": []},
    ]
    metrics = build_quality_metrics(claims)
    assert metrics["disputed_claims"] == 2
    assert metrics["verified_claims"] == 1


def test_build_quality_metrics_empty_has_disputed_key():
    """build_quality_metrics([]) includes disputed_claims key set to 0."""
    from output.provenance import build_quality_metrics
    metrics = build_quality_metrics([])
    assert "disputed_claims" in metrics
    assert metrics["disputed_claims"] == 0


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


# ── extract_claims_from_answer() — verification propagation ──────────────────

def test_extract_claims_verification_verified_sets_status_verified():
    """extract_claims_from_answer(verification='verified') produces claims with verification_status='verified'."""
    from output.provenance import extract_claims_from_answer
    llm = _make_mock_llm('["Fusion is hot.", "Plasma is ionised gas."]')
    claims = extract_claims_from_answer("What is fusion?", "Fusion is hot.", [], llm, verification="verified")
    assert all(c["verification_status"] == "verified" for c in claims)


def test_extract_claims_verification_unverified_sets_status_unverified():
    """extract_claims_from_answer(verification='unverified') produces claims with verification_status='unverified'."""
    from output.provenance import extract_claims_from_answer
    llm = _make_mock_llm('["Fusion is hot.", "Plasma is ionised gas."]')
    claims = extract_claims_from_answer("What is fusion?", "Fusion is hot.", [], llm, verification="unverified")
    assert all(c["verification_status"] == "unverified" for c in claims)


def test_extract_claims_verification_refuted_sets_status_disputed():
    """extract_claims_from_answer(verification='refuted') produces claims with verification_status='disputed'."""
    from output.provenance import extract_claims_from_answer
    llm = _make_mock_llm('["Fusion is hot."]')
    claims = extract_claims_from_answer("What is fusion?", "Fusion is hot.", [], llm, verification="refuted")
    assert all(c["verification_status"] == "disputed" for c in claims)


def test_extract_claims_default_verification_is_unverified():
    """extract_claims_from_answer() defaults to verification='unverified'."""
    from output.provenance import extract_claims_from_answer
    llm = _make_mock_llm('["Fact one."]')
    claims = extract_claims_from_answer("Q?", "Answer.", [], llm)
    assert claims[0]["verification_status"] == "unverified"


def test_build_quality_metrics_counts_verified_from_mixed_statuses():
    """build_quality_metrics() counts verified_claims correctly from mixed verification statuses."""
    from output.provenance import build_quality_metrics
    claims = [
        {"verification_status": "verified", "confidence": 0.9, "contradictions": []},
        {"verification_status": "verified", "confidence": 0.8, "contradictions": []},
        {"verification_status": "unverified", "confidence": 0.5, "contradictions": []},
    ]
    metrics = build_quality_metrics(claims)
    assert metrics["verified_claims"] == 2
    assert metrics["unverified_claims"] == 1
    assert metrics["coverage"] == pytest.approx(2 / 3)


# ── classify_source_type() — expanded domains ────────────────────────────────

def test_classify_iaea_as_government():
    """iaea.org is classified as government (intergovernmental organisation)."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.iaea.org/news/fusion") == "government"


def test_classify_iter_as_government():
    """iter.org is classified as government."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.iter.org/proj/inafewwords") == "government"


def test_classify_sciencedirect_as_academic():
    """sciencedirect.com is classified as academic."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.sciencedirect.com/article/pii/X") == "academic"


def test_classify_frontiersin_as_academic():
    """frontiersin.org is classified as academic."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.frontiersin.org/articles/10.3389/fphy") == "academic"


def test_classify_epj_conferences_as_academic():
    """epj-conferences.org is classified as academic."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.epj-conferences.org/articles/epjconf") == "academic"


def test_classify_wikipedia_as_reference():
    """wikipedia.org is classified as reference."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://en.wikipedia.org/wiki/Nuclear_fusion") == "reference"


def test_classify_bbc_com_as_news():
    """bbc.com is classified as news."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.bbc.com/news/science") == "news"


# ── score_confidence() tests ─────────────────────────────────────────────────

def test_score_confidence_no_sources_returns_base():
    """No sources returns the base score of 0.4."""
    from output.provenance import score_confidence
    assert score_confidence([]) == pytest.approx(0.4)


def test_score_confidence_government_source_increases_score():
    """A government source raises score above base."""
    from output.provenance import score_confidence
    sources = [{"source_type": "government"}]
    assert score_confidence(sources) > 0.4


def test_score_confidence_academic_source_increases_score():
    """An academic source raises score above base."""
    from output.provenance import score_confidence
    sources = [{"source_type": "academic"}]
    assert score_confidence(sources) > 0.4


def test_score_confidence_multiple_sources_corroboration_bonus():
    """Three sources add the corroboration bonus on top of per-source bonuses."""
    from output.provenance import score_confidence
    two = [{"source_type": "general"}, {"source_type": "general"}]
    three = [{"source_type": "general"}, {"source_type": "general"}, {"source_type": "general"}]
    assert score_confidence(three) > score_confidence(two)


def test_score_confidence_capped_at_one():
    """Score never exceeds 1.0 regardless of inputs."""
    from output.provenance import score_confidence
    sources = [{"source_type": "government"}] * 10 + [{"source_type": "academic"}] * 10
    assert score_confidence(sources) == pytest.approx(1.0)


def test_score_confidence_mixed_sources():
    """Mixed source types accumulate bonuses from each type."""
    from output.provenance import score_confidence
    gov_only = [{"source_type": "government"}]
    mixed = [{"source_type": "government"}, {"source_type": "academic"}]
    assert score_confidence(mixed) > score_confidence(gov_only)


# ── extract_claims_from_answer() tests ───────────────────────────────────────

def _make_mock_llm(response_text):
    """Return a minimal mock LLMClient whose chat() returns response_text."""
    from unittest.mock import MagicMock
    from llm.base import LLMResponse
    mock = MagicMock()
    mock.chat.return_value = LLMResponse(type="text", content=response_text)
    return mock


def test_extract_claims_returns_list_of_evidence_claims():
    """extract_claims_from_answer() returns a list of dicts."""
    from output.provenance import extract_claims_from_answer
    llm = _make_mock_llm('["Fusion is hot.", "Plasma is ionised gas."]')
    claims = extract_claims_from_answer("What is fusion?", "Fusion is hot.", [], llm)
    assert isinstance(claims, list)
    assert all(isinstance(c, dict) for c in claims)


def test_extract_claims_count_between_3_and_8():
    """The LLM response list is preserved as-is when it is 3–8 items."""
    from output.provenance import extract_claims_from_answer
    texts = [f"Claim {i}." for i in range(5)]
    llm = _make_mock_llm(json.dumps(texts))
    claims = extract_claims_from_answer("Q?", "Answer.", [], llm)
    assert len(claims) == 5


def test_extract_claims_handles_json_parse_error_gracefully():
    """Malformed JSON falls back to a single placeholder claim."""
    from output.provenance import extract_claims_from_answer
    llm = _make_mock_llm("This is not JSON at all.")
    claims = extract_claims_from_answer("Q?", "Some answer text.", [], llm)
    assert len(claims) == 1
    assert "extraction failed" in claims[0]["claim"] or claims[0]["claim"].startswith("Some")


def test_extract_claims_handles_fenced_json_response():
    """LLM response wrapped in ```json ... ``` fences is parsed correctly."""
    from output.provenance import extract_claims_from_answer
    fenced = '```json\n["Claim one.", "Claim two."]\n```'
    llm = _make_mock_llm(fenced)
    claims = extract_claims_from_answer("Q?", "Some answer text.", [], llm)
    assert len(claims) == 2
    assert claims[0]["claim"] == "Claim one."
    assert claims[1]["claim"] == "Claim two."


def test_extract_claims_assigns_sequential_ids():
    """IDs start at claim_id_start and increment."""
    from output.provenance import extract_claims_from_answer
    llm = _make_mock_llm('["Claim A.", "Claim B.", "Claim C."]')
    claims = extract_claims_from_answer("Q?", "Answer.", [], llm, claim_id_start=5)
    assert claims[0]["id"] == 5
    assert claims[1]["id"] == 6
    assert claims[2]["id"] == 7


def test_extract_claims_scores_confidence():
    """Returned claims have a confidence score between 0 and 1."""
    from output.provenance import extract_claims_from_answer
    llm = _make_mock_llm('["Fact one."]')
    claims = extract_claims_from_answer("Q?", "Fact one.", [], llm)
    assert 0.0 <= claims[0]["confidence"] <= 1.0


def test_extract_claims_deduplicates_sources_by_url():
    """Each claim's sources list contains no duplicate URLs."""
    from output.provenance import extract_claims_from_answer
    sources = [
        {"title": "Page A", "url": "https://example.com/a"},
        {"title": "Page A duplicate", "url": "https://example.com/a"},
        {"title": "Page B", "url": "https://example.com/b"},
    ]
    llm = _make_mock_llm('["Claim one.", "Claim two."]')
    claims = extract_claims_from_answer("Q?", "Answer.", sources, llm)
    for claim in claims:
        urls = [s["url"] for s in claim["sources"]]
        assert len(urls) == len(set(urls))


def test_extract_claims_sources_count_not_inflated():
    """Total source entries per claim does not exceed the unique URL count."""
    from output.provenance import extract_claims_from_answer
    sources = [
        {"title": f"Page {i}", "url": f"https://example.com/{i}"}
        for i in range(5)
    ]
    llm = _make_mock_llm('["Claim one.", "Claim two.", "Claim three."]')
    claims = extract_claims_from_answer("Q?", "Answer.", sources, llm)
    unique_url_count = len({s["url"] for s in sources})
    for claim in claims:
        assert len(claim["sources"]) <= unique_url_count


def test_extract_claims_classifies_sources():
    """Sources attached to returned claims have source_type set."""
    from output.provenance import extract_claims_from_answer
    sources = [{"title": "IAEA", "url": "https://www.iaea.org/news"}]
    llm = _make_mock_llm('["Nuclear energy is regulated."]')
    claims = extract_claims_from_answer("Q?", "Nuclear energy is regulated.", sources, llm)
    assert claims[0]["sources"][0]["source_type"] == "government"


# ── annotate_report_lines() tests ────────────────────────────────────────────

def test_annotate_report_lines_returns_tuple():
    """annotate_report_lines() returns a (str, list) tuple."""
    from output.provenance import annotate_report_lines
    result = annotate_report_lines("Some report text.", [])
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_annotate_report_lines_adds_marker_to_matching_sentence():
    """A claim whose content words match the report line gets a [N] marker."""
    from output.provenance import annotate_report_lines
    report = "Nuclear fusion combines light nuclei to release energy."
    claim = {
        "id": 1, "claim": "Nuclear fusion combines light nuclei to release energy.",
        "report_line": None,
    }
    annotated, _ = annotate_report_lines(report, [claim])
    assert "[1]" in annotated


def test_annotate_report_lines_sets_report_line_on_claim():
    """The matched claim has report_line set to the 1-based line number."""
    from output.provenance import annotate_report_lines
    report = "Line one.\nNuclear fusion produces enormous energy.\nLine three."
    claim = {
        "id": 2, "claim": "Nuclear fusion produces enormous energy.",
        "report_line": None,
    }
    _, claims_out = annotate_report_lines(report, [claim])
    assert claims_out[0]["report_line"] == 2


def test_annotate_report_lines_no_match_leaves_report_unchanged():
    """A claim with no matching text leaves the report unmodified."""
    from output.provenance import annotate_report_lines
    report = "The sky is blue."
    claim = {
        "id": 1, "claim": "Quantum chromodynamics governs quark interactions.",
        "report_line": None,
    }
    annotated, claims_out = annotate_report_lines(report, [claim])
    assert annotated == report
    assert claims_out[0]["report_line"] is None


# ── annotate_report_lines() — three-tier matching tests ──────────────────────

def test_annotate_tier1_matches_capitalised_phrase():
    """Tier 1: a 2+ word capitalised run in the claim matches verbatim; synthesis_status='anchored'."""
    from output.provenance import annotate_report_lines
    report = "Background.\nThe National Ignition Facility achieved fusion ignition in 2022.\nAnother line."
    claim = {"id": 5, "claim": "National Ignition Facility achieved a historic scientific milestone.", "report_line": None, "synthesis_status": "not_attempted"}
    annotated, claims_out = annotate_report_lines(report, [claim])
    assert "[5]" in annotated
    assert claims_out[0]["report_line"] == 2
    assert claims_out[0]["synthesis_status"] == "anchored"


def test_annotate_tier2_matches_on_number_with_shared_words():
    """Tier 2: digit+overlap match; synthesis_status='paraphrased'."""
    from output.provenance import annotate_report_lines
    report = "Background line.\nThe reactor produced 500 megawatts of clean fusion power output.\nAnother line."
    claim = {"id": 6, "claim": "Fusion power output reached 500 megawatts of clean energy.", "report_line": None, "synthesis_status": "not_attempted"}
    annotated, claims_out = annotate_report_lines(report, [claim])
    assert "[6]" in annotated
    assert claims_out[0]["report_line"] == 2
    assert claims_out[0]["synthesis_status"] == "paraphrased"


def test_annotate_tier3_matches_on_content_word_overlap():
    """Tier 3: content word overlap match; synthesis_status='paraphrased'."""
    from output.provenance import annotate_report_lines
    report = "Background.\nScientists discovered that plasma confinement techniques dramatically improved efficiency.\nAnother."
    claim = {"id": 7, "claim": "Plasma confinement techniques improved efficiency in scientific experiments.", "report_line": None, "synthesis_status": "not_attempted"}
    annotated, claims_out = annotate_report_lines(report, [claim])
    assert "[7]" in annotated
    assert claims_out[0]["report_line"] == 2
    assert claims_out[0]["synthesis_status"] == "paraphrased"


def test_annotate_no_match_when_insufficient_overlap():
    """A claim with no tier match leaves report_line None and synthesis_status unchanged."""
    from output.provenance import annotate_report_lines
    report = "The results showed some promise for future applications."
    claim = {"id": 8, "claim": "Results showed promise.", "report_line": None, "synthesis_status": "not_attempted"}
    annotated, claims_out = annotate_report_lines(report, [claim])
    assert claims_out[0]["report_line"] is None
    assert claims_out[0]["synthesis_status"] == "not_attempted"
    assert "[8]" not in annotated


def test_annotate_each_line_annotated_at_most_once():
    """First claim to match a line wins; the same line is not annotated by a second claim."""
    from output.provenance import annotate_report_lines
    report = "Scientists proved plasma confinement techniques vastly improved fusion energy efficiency levels."
    claim1 = {"id": 9, "claim": "Plasma confinement techniques improved fusion energy efficiency dramatically.", "report_line": None}
    claim2 = {"id": 10, "claim": "Plasma confinement techniques improved fusion energy efficiency results.", "report_line": None}
    annotated, claims_out = annotate_report_lines(report, [claim1, claim2])
    assert "[9]" in annotated
    assert "[10]" not in annotated
    assert claims_out[1]["report_line"] is None


# ── build_claims_from_results() tests ────────────────────────────────────────

def test_build_claims_from_results_returns_list():
    """build_claims_from_results() returns a list."""
    from output.provenance import build_claims_from_results
    from evidence.schema import ResearchResult
    llm = _make_mock_llm('["Fact one.", "Fact two."]')
    research_results = [ResearchResult(question="Q1", answer="Answer one.")]
    claims = build_claims_from_results(research_results, llm)
    assert isinstance(claims, list)


def test_build_claims_from_results_calls_extraction_per_question():
    """One LLM call is made per question in results."""
    from output.provenance import build_claims_from_results
    from evidence.schema import ResearchResult
    llm = _make_mock_llm('["Fact."]')
    research_results = [
        ResearchResult(question="Q1", answer="A1"),
        ResearchResult(question="Q2", answer="A2"),
        ResearchResult(question="Q3", answer="A3"),
    ]
    build_claims_from_results(research_results, llm)
    assert llm.chat.call_count == 3


# ── classify_source_type() — E006 hybrid layer tests ─────────────────────────

def test_classify_gov_tld_as_government():
    """Layer 1: .gov TLD is classified as government."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://energy.gov/nuclear") == "government"


def test_classify_edu_tld_as_academic():
    """Layer 1: .edu TLD is classified as academic."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://mit.edu/research/fusion") == "academic"


def test_classify_gov_uk_as_government():
    """Layer 1: .gov.uk TLD is classified as government."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.gov.uk/government/publications") == "government"


def test_classify_arxiv_as_academic():
    """Layer 2: arxiv.org is classified as academic."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://arxiv.org/abs/2301.00001") == "academic"


def test_classify_doi_as_academic():
    """Layer 2: doi.org links are classified as academic."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://doi.org/10.1038/s41586-021-03665-2") == "academic"


def test_classify_wikipedia_reference_layer2():
    """Layer 2: wikipedia.org is classified as reference."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://en.wikipedia.org/wiki/Fusion") == "reference"


def test_classify_iaea_institutional_government():
    """Layer 3: iaea.org is classified as government (no .gov TLD)."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.iaea.org/topics/fusion") == "government"


def test_classify_iter_institutional_government():
    """Layer 3: iter.org is classified as government."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.iter.org/proj/inafewwords") == "government"


def test_classify_frontiersin_institutional_academic():
    """Layer 3: frontiersin.org is classified as academic."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.frontiersin.org/articles/10.3389/fphy") == "academic"


def test_classify_epj_conferences_institutional_academic():
    """Layer 3: epj-conferences.org is classified as academic."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.epj-conferences.org/articles/epjconf") == "academic"


def test_classify_custom_academic_domain():
    """Layer 4: custom academic domain from config is classified correctly."""
    from output.provenance import classify_source_type
    custom = {"academic": ["mycustomjournal.org"]}
    assert classify_source_type("https://mycustomjournal.org/papers/42", custom_domains=custom) == "academic"


def test_classify_custom_government_domain():
    """Layer 4: custom government domain from config is classified correctly."""
    from output.provenance import classify_source_type
    custom = {"government": ["specialagency.int"]}
    assert classify_source_type("https://specialagency.int/reports", custom_domains=custom) == "government"


def test_custom_domains_override_blog_default():
    """Layer 4: without custom_domains, unknown domain falls through to general."""
    from output.provenance import classify_source_type
    url = "https://obscure-but-legit-org.net/paper"
    assert classify_source_type(url) == "general"
    custom = {"academic": ["obscure-but-legit-org.net"]}
    assert classify_source_type(url, custom_domains=custom) == "academic"


def test_classify_unknown_domain_without_llm_returns_blog():
    """Layer 5: no llm_client means unknown domain falls back to general."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://randomsite12345.xyz/post") == "general"


def test_classify_unknown_domain_with_llm_calls_llm():
    """Layer 5: llm_client is called when no pattern layer matches."""
    from output.provenance import classify_source_type
    llm = _make_mock_llm("academic")
    result = classify_source_type("https://unknownsite.xyz/paper", llm_client=llm)
    assert llm.chat.call_count == 1
    assert result == "academic"


def test_classify_llm_fallback_not_called_for_known_domain():
    """Layer 5: llm_client is NOT called when a pattern layer matches."""
    from output.provenance import classify_source_type
    llm = _make_mock_llm("general")
    classify_source_type("https://arxiv.org/abs/1234.5678", llm_client=llm)
    assert llm.chat.call_count == 0


# ── classify_source_type() — full spec tests ─────────────────────────────────

def test_classify_ac_uk_tld_as_academic():
    """Layer 1: .ac.uk TLD is classified as academic."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.ox.ac.uk/research/fusion") == "academic"


def test_classify_mil_tld_as_government():
    """Layer 1: .mil TLD is classified as government."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.darpa.mil/program/fusion") == "government"


def test_classify_pubmed_as_academic():
    """Layer 2: pubmed.ncbi pattern is classified as academic."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://pubmed.ncbi.nlm.nih.gov/12345678/") == "academic"


def test_classify_britannica_as_reference():
    """Layer 2: britannica.com is classified as reference."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.britannica.com/science/nuclear-fusion") == "reference"


def test_classify_who_as_government():
    """Layer 3: who.int is classified as government."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.who.int/health-topics/energy") == "government"


def test_classify_springer_as_academic():
    """Layer 3: springer.com is classified as academic."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://link.springer.com/article/10.1007/s00339") == "academic"


def test_classify_ieee_as_academic():
    """Layer 3: ieee.org is classified as academic."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://ieeexplore.ieee.org/document/9123456") == "academic"


def test_classify_reuters_as_news():
    """Layer 3: reuters.com is classified as news."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.reuters.com/technology/fusion") == "news"


def test_classify_bbc_as_news():
    """Layer 3: bbc.co.uk is classified as news."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.bbc.co.uk/news/science-12345678") == "news"


def test_classify_nature_news_as_news():
    """Layer 3: nature.com/news path is classified as news."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.nature.com/news/fusion-breakthrough-2024") == "news"


def test_custom_domains_none_handled_gracefully():
    """Layer 4: custom_domains=None does not raise."""
    from output.provenance import classify_source_type
    result = classify_source_type("https://example.com/page", custom_domains=None)
    assert result == "general"


def test_llm_fallback_invalid_response_returns_blog():
    """Layer 5: LLM returning an invalid type falls back to general."""
    from output.provenance import classify_source_type
    llm = _make_mock_llm("definitely_not_a_type")
    result = classify_source_type("https://unknownsite.xyz/paper", llm_client=llm)
    assert result == "general"


def test_llm_fallback_response_stripped_and_lowercased():
    """Layer 5: LLM response is stripped and lowercased before validation."""
    from output.provenance import classify_source_type
    llm = _make_mock_llm("  Academic\n")
    result = classify_source_type("https://unknownsite.xyz/paper", llm_client=llm)
    assert result == "academic"


def test_classify_source_type_works_with_url_only():
    """Backward compatibility: calling with url argument only must not raise."""
    from output.provenance import classify_source_type
    result = classify_source_type("https://iaea.org/news")
    assert result == "government"


# ── classify_source_type() — new taxonomy types ───────────────────────────────

def test_classify_youtube_as_video():
    """Layer 2: youtube.com is classified as video."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.youtube.com/watch?v=abc123") == "video"


def test_classify_youtu_be_as_video():
    """Layer 2: youtu.be short links are classified as video."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://youtu.be/abc123") == "video"


def test_classify_vimeo_as_video():
    """Layer 2: vimeo.com is classified as video."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://vimeo.com/123456789") == "video"


def test_classify_reddit_as_forum():
    """Layer 2: reddit.com is classified as forum."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.reddit.com/r/fusion/comments/abc") == "forum"


def test_classify_quora_as_forum():
    """Layer 2: quora.com is classified as forum."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.quora.com/What-is-nuclear-fusion") == "forum"


def test_classify_stackoverflow_as_forum():
    """Layer 2: stackoverflow.com is classified as forum."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://stackoverflow.com/questions/12345") == "forum"


def test_classify_weforum_as_institutional():
    """Layer 3: weforum.org is classified as institutional."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.weforum.org/stories/fusion-energy") == "institutional"


def test_classify_rand_as_institutional():
    """Layer 3: rand.org is classified as institutional."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.rand.org/research/fusion") == "institutional"


def test_classify_chathamhouse_as_institutional():
    """Layer 3: chathamhouse.org is classified as institutional."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.chathamhouse.org/research/energy") == "institutional"


def test_classify_fusionindustryassociation_as_institutional():
    """Layer 3: fusionindustryassociation.org is classified as institutional."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.fusionindustryassociation.org/report") == "institutional"


def test_classify_world_nuclear_as_institutional():
    """Layer 3: world-nuclear.org is classified as institutional."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://www.world-nuclear.org/information-library") == "institutional"


# ── score_confidence() — new type weights ────────────────────────────────────

def test_score_confidence_institutional_increases_score():
    """An institutional source raises score above base."""
    from output.provenance import score_confidence
    sources = [{"source_type": "institutional"}]
    assert score_confidence(sources) > 0.4


def test_score_confidence_video_minimal_increase():
    """A video source gives a minimal increase above base."""
    from output.provenance import score_confidence
    sources = [{"source_type": "video"}]
    assert score_confidence(sources) > 0.4
    assert score_confidence(sources) < score_confidence([{"source_type": "news"}])


def test_score_confidence_forum_no_increase():
    """A forum source gives no increase above base (same as general)."""
    from output.provenance import score_confidence
    forum = [{"source_type": "forum"}]
    general = [{"source_type": "general"}]
    assert score_confidence(forum) == score_confidence(general)


def test_score_confidence_industry_minimal_increase():
    """An industry source gives a small increase above base."""
    from output.provenance import score_confidence
    sources = [{"source_type": "industry"}]
    assert score_confidence(sources) > 0.4
    assert score_confidence(sources) < score_confidence([{"source_type": "institutional"}])


# ── backward compatibility ────────────────────────────────────────────────────

def test_classify_unknown_domain_still_returns_general():
    """Unknown domains still fall through to general."""
    from output.provenance import classify_source_type
    assert classify_source_type("https://some-random-unknown-site.xyz/page") == "general"


def test_score_confidence_general_no_increase():
    """General sources give no increase above base score."""
    from output.provenance import score_confidence
    assert score_confidence([{"source_type": "general"}]) == pytest.approx(0.4)


# ── ResearchResult ────────────────────────────────────────────────────────────

def test_research_result_default_verification_unverified():
    """ResearchResult.verification defaults to 'unverified'."""
    from evidence.schema import ResearchResult
    result = ResearchResult(question="Q?", answer="A.")
    assert result.verification == "unverified"


def test_research_result_fields_are_mutable():
    """ResearchResult is not frozen — fields can be reassigned."""
    from evidence.schema import ResearchResult
    result = ResearchResult(question="Q?", answer="A.")
    result.verification = "verified"
    assert result.verification == "verified"


def test_research_result_stores_question():
    from evidence.schema import ResearchResult
    result = ResearchResult(question="What is X?", answer="X is Y.")
    assert result.question == "What is X?"


def test_research_result_stores_answer():
    from evidence.schema import ResearchResult
    result = ResearchResult(question="Q?", answer="The answer.")
    assert result.answer == "The answer."


def test_research_result_claims_defaults_to_empty_list():
    from evidence.schema import ResearchResult
    result = ResearchResult(question="Q?", answer="A.")
    assert result.claims == []


def test_research_result_sources_defaults_to_empty_list():
    from evidence.schema import ResearchResult
    result = ResearchResult(question="Q?", answer="A.")
    assert result.sources == []


def test_research_result_message_history_defaults_to_empty_list():
    from evidence.schema import ResearchResult
    result = ResearchResult(question="Q?", answer="A.")
    assert result.message_history == []
