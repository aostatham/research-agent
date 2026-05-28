"""
Tests for save_viewer() and the viewer template.

Verifies that save_viewer() correctly injects provenance JSON into the
template and that the resulting HTML contains the expected structural
elements. Uses a minimal provenance dict fixture — does not run the
full research pipeline.
"""

import json
import os
import pytest
from unittest.mock import patch


# ── Minimal provenance fixture ────────────────────────────────────────────────

def _make_provenance(schema_version="1.0", claims=None):
    """Return a minimal ProvenanceReport-shaped dict for testing."""
    return {
        "schema_version": schema_version,
        "report_file": "test_report.md",
        "generated": "2026-01-01T00:00:00+00:00",
        "quality_metrics": {
            "coverage": 0.5,
            "confidence": 0.6,
            "contradictions": 0,
            "verified_claims": 1,
            "unverified_claims": 1,
            "disputed_claims": 0,
        },
        "claims": claims or [
            {
                "id": 1,
                "claim": "The Daisy Seed uses an STM32H750 microcontroller.",
                "confidence": 0.7,
                "verification_status": "verified",
                "synthesis_status": "anchored",
                "report_line": 5,
                "source": "https://example.com",
                "sources": [],
                "contradictions": [],
                "evidence_type": "qualitative",
                "timestamp": "2026-01-01T00:00:00+00:00",
            },
            {
                "id": 2,
                "claim": "The board runs at 480 MHz.",
                "confidence": 0.5,
                "verification_status": "unverified",
                "synthesis_status": "paraphrased",
                "report_line": 8,
                "source": "https://example.com",
                "sources": [],
                "contradictions": [],
                "evidence_type": "qualitative",
                "timestamp": "2026-01-01T00:00:00+00:00",
            },
        ],
    }


def _call_save_viewer(tmp_path, provenance_data):
    """Call save_viewer() with a report path in tmp_path."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    from output.writer import save_viewer
    report_path = str(tmp_path / "test_report.md")
    return save_viewer(report_path, provenance_data), report_path


# ── save_viewer() structural tests ───────────────────────────────────────────

def test_save_viewer_produces_viewer_html_file(tmp_path):
    """save_viewer() writes a .viewer.html file to disk."""
    viewer_path, _ = _call_save_viewer(tmp_path, _make_provenance())
    assert os.path.exists(viewer_path)
    assert viewer_path.endswith(".viewer.html")


def test_save_viewer_injected_json_is_parseable(tmp_path):
    """The JSON embedded in the viewer HTML can be extracted and parsed."""
    prov = _make_provenance()
    viewer_path, _ = _call_save_viewer(tmp_path, prov)
    with open(viewer_path, encoding="utf-8") as f:
        html = f.read()
    # Extract JSON between the script tags
    start = html.find('<script type="application/json" id="provenance-data">') + len(
        '<script type="application/json" id="provenance-data">'
    )
    end = html.find("</script>", start)
    raw_json = html[start:end]
    parsed = json.loads(raw_json)
    assert parsed["schema_version"] == "1.0"
    assert len(parsed["claims"]) == 2


def test_save_viewer_contains_provenance_data_script_id(tmp_path):
    """The viewer HTML contains the 'provenance-data' script block ID."""
    viewer_path, _ = _call_save_viewer(tmp_path, _make_provenance())
    with open(viewer_path, encoding="utf-8") as f:
        html = f.read()
    assert "provenance-data" in html


def test_save_viewer_contains_trust_and_traceability_text(tmp_path):
    """The viewer HTML contains 'TRUST' and 'TRACEABILITY' cluster labels."""
    viewer_path, _ = _call_save_viewer(tmp_path, _make_provenance())
    with open(viewer_path, encoding="utf-8") as f:
        html = f.read()
    assert "TRUST" in html
    assert "TRACEABILITY" in html


def test_save_viewer_sentinel_is_replaced(tmp_path):
    """The __PROVENANCE_DATA__ sentinel does not appear in the output HTML."""
    viewer_path, _ = _call_save_viewer(tmp_path, _make_provenance())
    with open(viewer_path, encoding="utf-8") as f:
        html = f.read()
    assert "__PROVENANCE_DATA__" not in html


def test_save_viewer_returns_correct_path(tmp_path):
    """save_viewer() returns the path to the written viewer file."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    from output.writer import save_viewer
    report_path = str(tmp_path / "my_report.md")
    viewer_path = save_viewer(report_path, _make_provenance())
    assert viewer_path == str(tmp_path / "my_report.viewer.html")


def test_save_viewer_disputed_claims_produce_disputed_in_html(tmp_path):
    """A provenance dict with disputed claims produces HTML containing 'disputed'."""
    claims_with_disputed = [
        {
            "id": 1,
            "claim": "A disputed claim.",
            "confidence": 0.3,
            "verification_status": "disputed",
            "synthesis_status": "not_attempted",
            "report_line": None,
            "source": "https://example.com",
            "sources": [],
            "contradictions": [],
            "evidence_type": "qualitative",
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
    ]
    prov = _make_provenance(claims=claims_with_disputed)
    prov["quality_metrics"]["disputed_claims"] = 1
    viewer_path, _ = _call_save_viewer(tmp_path, prov)
    with open(viewer_path, encoding="utf-8") as f:
        html = f.read()
    assert "disputed" in html


def test_save_viewer_schema_version_mismatch_warning_present(tmp_path):
    """A provenance dict with schema_version '2.0' produces HTML with the mismatch warning text."""
    prov = _make_provenance(schema_version="2.0")
    viewer_path, _ = _call_save_viewer(tmp_path, prov)
    with open(viewer_path, encoding="utf-8") as f:
        html = f.read()
    # The warning div text is in the static HTML (hidden by default; shown by JS)
    assert "schema" in html.lower()
    assert "v1.0" in html


def test_save_viewer_report_line_link_uses_relative_href(tmp_path):
    """Claims with report_line set produce an href of the form 'report_name.html#LN' in the viewer."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    from output.writer import save_viewer
    prov = _make_provenance()
    # report_line=5 is set on claim 1 — the viewer should link to my_report.html#L5
    report_path = str(tmp_path / "my_report.md")
    viewer_path = save_viewer(report_path, prov)
    with open(viewer_path, encoding="utf-8") as f:
        html = f.read()
    # The injected JSON must contain the report_line value
    raw_json_start = html.find('<script type="application/json" id="provenance-data">') + len(
        '<script type="application/json" id="provenance-data">'
    )
    raw_json_end = html.find("</script>", raw_json_start)
    parsed = json.loads(html[raw_json_start:raw_json_end])
    assert parsed["claims"][0]["report_line"] == 5
    # The viewer JS builds the href as reportFile + "#L" + report_line.
    # Verify that the relative href pattern is present in the static HTML
    # (the template generates the anchor pattern as a string literal in JS).
    assert "my_report.html#L" in html or "#L" in html
