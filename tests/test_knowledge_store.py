"""
Tests for src/knowledge/store.py — KuzuStore.

Verifies:
- KuzuStore creates tables on init without error
- write_run() writes a claim and source correctly
- _is_valid_graph_claim() rejects invalid claims
- query_claims_for_topic() returns [] for unknown topic
- query_claims_for_topic() returns claims after write_run()
- check_contradiction() returns no_contradiction for unknown claim
- check_contradiction() returns contradiction_found when contradicting
  claim exists in graph
- check_contradiction() returns unresolved when claims are beyond staleness
  threshold
- write_claim() returns rejected for invalid claim
- write_claim() returns written for valid claim
- All methods return error JSON when store is unavailable

All tests use a temporary directory for the database.
"""

import json
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from knowledge.store import KuzuStore


# ── Helpers ───────────────────────────────────────────────────────────────────

def _source(url="https://example.com", source_type="general",
            retrieved="2026-01-15T10:00:00Z"):
    return {"url": url, "title": "Test Source", "source_type": source_type,
            "retrieved": retrieved}


def _claim(id=1, text="The speed of light is approximately 3×10⁸ m/s.",
           vstatus="unverified", confidence=0.7,
           timestamp="2026-01-15T10:00:00Z", sources=None):
    return {
        "id": id,
        "claim": text,
        "verification_status": vstatus,
        "confidence": confidence,
        "evidence_type": "cited",
        "timestamp": timestamp,
        "sources": sources if sources is not None else [_source()],
    }


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    """KuzuStore backed by a temporary directory."""
    db_path = str(tmp_path / "test_knowledge.db")
    s = KuzuStore(db_path)
    yield s
    s.close()


# ── Init and schema ───────────────────────────────────────────────────────────

def test_store_creates_tables_on_init(tmp_path):
    """KuzuStore.__init__ creates all node and relationship tables without error."""
    db_path = str(tmp_path / "init_test.db")
    s = KuzuStore(db_path)
    assert s._available is True
    s.close()


def test_store_is_available_after_init(store):
    """Store reports itself as available after successful init."""
    assert store._available is True


# ── write_run ─────────────────────────────────────────────────────────────────

def test_write_run_writes_claim_and_source(store):
    """write_run() persists a claim that is then retrievable for its topic."""
    claims = [_claim(1, "Fusion releases enormous energy.")]
    sources = [_source("https://energy.gov/fusion")]
    store.write_run("run1", "nuclear fusion", claims, sources, "2026-01-15T10:00:00Z")

    result = json.loads(store.query_claims_for_topic("nuclear fusion"))
    assert isinstance(result, list)
    assert len(result) >= 1
    assert any("Fusion" in c["claim"] for c in result)


def test_write_run_skips_invalid_claims(store):
    """write_run() skips claims that fail _is_valid_graph_claim() without raising."""
    invalid = _claim(1, "")  # empty text
    invalid["claim"] = ""
    store.write_run("run1", "topic", [invalid], [], "2026-01-15T10:00:00Z")
    result = json.loads(store.query_claims_for_topic("topic"))
    assert result == []


def test_write_run_does_not_raise_when_unavailable(tmp_path):
    """write_run() on an unavailable store is a silent no-op."""
    store = KuzuStore("/dev/null/invalid/path/cannot/exist")
    store.write_run("run1", "topic", [_claim()], [], "2026-01-15T10:00:00Z")


# ── _is_valid_graph_claim ─────────────────────────────────────────────────────

def test_is_valid_graph_claim_rejects_empty_text(store):
    c = _claim(1, "")
    c["claim"] = ""
    assert store._is_valid_graph_claim(c) is False


def test_is_valid_graph_claim_rejects_markdown_header(store):
    c = _claim(1, "## Introduction")
    assert store._is_valid_graph_claim(c) is False


def test_is_valid_graph_claim_rejects_extraction_failed(store):
    c = _claim(1, "[extraction failed] could not parse")
    assert store._is_valid_graph_claim(c) is False


def test_is_valid_graph_claim_rejects_too_long(store):
    c = _claim(1, "A" * 501)
    assert store._is_valid_graph_claim(c) is False


def test_is_valid_graph_claim_rejects_no_sources(store):
    c = _claim(1, "Valid claim text here.", sources=[])
    assert store._is_valid_graph_claim(c) is False


def test_is_valid_graph_claim_rejects_multi_paragraph(store):
    c = _claim(1, "First paragraph.\n\nSecond paragraph.")
    assert store._is_valid_graph_claim(c) is False


def test_is_valid_graph_claim_accepts_valid_claim(store):
    c = _claim(1, "The boiling point of water is 100°C at sea level.")
    assert store._is_valid_graph_claim(c) is True


# ── query_claims_for_topic ────────────────────────────────────────────────────

def test_query_claims_for_unknown_topic_returns_empty_list(store):
    """query_claims_for_topic() returns [] when topic has no claims."""
    result = json.loads(store.query_claims_for_topic("unknown topic xyz"))
    assert result == []


def test_query_claims_for_topic_returns_claims_after_write(store):
    """query_claims_for_topic() returns written claims."""
    claims = [
        _claim(1, "Fusion requires extreme temperatures."),
        _claim(2, "Fusion produces helium as a byproduct."),
    ]
    store.write_run("run1", "fusion energy", claims, [], "2026-01-15T10:00:00Z")
    result = json.loads(store.query_claims_for_topic("fusion energy"))
    assert isinstance(result, list)
    assert len(result) == 2
    texts = {c["claim"] for c in result}
    assert "Fusion requires extreme temperatures." in texts
    assert "Fusion produces helium as a byproduct." in texts


def test_query_claims_returns_error_json_when_unavailable():
    """query_claims_for_topic() returns error JSON when store is unavailable."""
    store = KuzuStore("/dev/null/invalid/cannot/exist")
    result = json.loads(store.query_claims_for_topic("topic"))
    assert "error" in result


# ── check_contradiction ───────────────────────────────────────────────────────

def test_check_contradiction_no_contradiction_for_unknown_topic(store):
    """check_contradiction returns no_contradiction when topic has no claims."""
    result = json.loads(store.check_contradiction("some claim", "unknown topic"))
    assert result["status"] == "no_contradiction"


def test_check_contradiction_returns_contradiction_found(store):
    """check_contradiction returns contradiction_found when a CONTRADICTS edge exists
    and claim_text is a substring of one of the contradicting claims."""
    claims = [
        _claim(1, "Fusion produces net energy.",
               vstatus="verified", confidence=0.9,
               timestamp="2026-05-01T00:00:00Z"),
        _claim(2, "Fusion does not produce net energy.",
               vstatus="unverified", confidence=0.8,
               timestamp="2026-05-02T00:00:00Z"),
    ]
    store.write_run("run1", "contradiction topic", claims, [],
                    "2026-05-01T00:00:00Z")
    # Manually create CONTRADICTS edge — auto-creation is disabled
    store._create_edge(
        "MATCH (a:Claim {claim_id: $a}), (b:Claim {claim_id: $b}) "
        "CREATE (a)-[:CONTRADICTS]->(b)",
        {"a": "run1_1", "b": "run1_2"},
    )
    # "produces net energy" is a substring of claim 1
    result = json.loads(store.check_contradiction("produces net energy", "contradiction topic"))
    assert result["status"] == "contradiction_found"
    assert "contradicting_claim" in result
    assert "claim_retrieved" in result
    assert "contradicting_retrieved" in result
    assert "confidence_delta" in result


def test_check_contradiction_returns_unresolved_when_staleness_exceeded(store):
    """check_contradiction returns unresolved when timestamps are > staleness_days apart."""
    claims = [
        _claim(1, "Staleness claim is definitively true.",
               vstatus="verified", confidence=0.9,
               timestamp="2020-01-01T00:00:00Z"),   # very old
        _claim(2, "Staleness claim is definitively false.",
               vstatus="refuted", confidence=0.8,
               timestamp="2026-05-01T00:00:00Z"),   # recent
    ]
    store.write_run("run1", "staleness topic", claims, [],
                    "2026-05-01T00:00:00Z")
    # Manually create CONTRADICTS edge — auto-creation is disabled
    store._create_edge(
        "MATCH (a:Claim {claim_id: $a}), (b:Claim {claim_id: $b}) "
        "CREATE (a)-[:CONTRADICTS]->(b)",
        {"a": "run1_1", "b": "run1_2"},
    )
    # "Staleness claim" is a substring of both claims
    result = json.loads(
        store.check_contradiction("Staleness claim", "staleness topic", staleness_days=90)
    )
    assert result["status"] == "unresolved"
    assert "staleness" in result.get("reason", "")


def test_check_contradiction_no_match_returns_no_contradiction(store):
    """check_contradiction returns no_contradiction when CONTRADICTS edges exist on the topic
    but claim_text is not a substring of any contradicting claim."""
    claims = [
        _claim(1, "Solar panels are efficient.",
               vstatus="verified", confidence=0.9,
               timestamp="2026-05-01T00:00:00Z"),
        _claim(2, "Solar panels are inefficient.",
               vstatus="refuted", confidence=0.8,
               timestamp="2026-05-02T00:00:00Z"),
    ]
    store.write_run("run1", "solar topic", claims, [], "2026-05-01T00:00:00Z")
    store._create_edge(
        "MATCH (a:Claim {claim_id: $a}), (b:Claim {claim_id: $b}) "
        "CREATE (a)-[:CONTRADICTS]->(b)",
        {"a": "run1_1", "b": "run1_2"},
    )
    # "nuclear fusion" doesn't appear in any solar claim
    result = json.loads(store.check_contradiction("nuclear fusion", "solar topic"))
    assert result["status"] == "no_contradiction"


def test_check_contradiction_returns_unresolved_when_unavailable():
    """check_contradiction returns unresolved when store is unavailable."""
    store = KuzuStore("/dev/null/invalid/cannot/exist")
    result = json.loads(store.check_contradiction("claim", "topic"))
    assert result["status"] == "unresolved"
    assert "reason" in result


# ── write_claim ───────────────────────────────────────────────────────────────

def test_write_claim_returns_rejected_for_invalid_claim(store):
    """write_claim returns rejected JSON for a claim with no sources."""
    claim = {"claim": "A valid sentence.", "sources": []}
    result = json.loads(store.write_claim(claim))
    assert result["status"] == "rejected"
    assert "reason" in result


def test_write_claim_returns_written_for_valid_claim(store):
    """write_claim returns written JSON with claim_id for a valid claim."""
    claim = {
        "claim": "The speed of light is approximately 3×10⁸ m/s.",
        "confidence": 0.95,
        "verification_status": "verified",
        "evidence_type": "cited",
        "timestamp": "2026-01-15T10:00:00Z",
        "sources": [_source()],
    }
    result = json.loads(store.write_claim(claim))
    assert result["status"] == "written"
    assert "claim_id" in result


def test_write_claim_returns_error_when_unavailable():
    """write_claim returns error JSON when store is unavailable."""
    store = KuzuStore("/dev/null/invalid/cannot/exist")
    claim = {"claim": "test claim", "sources": [_source()]}
    result = json.loads(store.write_claim(claim))
    assert result["status"] == "error"
    assert "reason" in result


# ── write_run with prior_run_id ───────────────────────────────────────────────

def test_write_run_with_prior_run_id_creates_preceded_by_edge(store):
    """write_run() with prior_run_id creates a RUN_PRECEDED_BY edge."""
    store.write_run("run1", "topic", [], [], "2026-01-01T00:00:00Z")
    store.write_run("run2", "topic", [], [], "2026-01-02T00:00:00Z",
                    prior_run_id="run1")
    history = store.get_run_history("run2")
    assert "run1" in history


# ── get_run_history ───────────────────────────────────────────────────────────

def test_get_run_history_returns_chain(store):
    """get_run_history follows RUN_PRECEDED_BY edges across multiple hops."""
    store.write_run("run1", "topic", [], [], "2026-01-01T00:00:00Z")
    store.write_run("run2", "topic", [], [], "2026-01-02T00:00:00Z",
                    prior_run_id="run1")
    store.write_run("run3", "topic", [], [], "2026-01-03T00:00:00Z",
                    prior_run_id="run2")
    history = store.get_run_history("run3")
    assert "run2" in history
    assert "run1" in history


def test_get_run_history_returns_empty_for_unknown_run(store):
    """get_run_history returns [] when run has no predecessors."""
    history = store.get_run_history("nonexistent-run-id")
    assert history == []
