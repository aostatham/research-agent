"""
Tests for main.py — CLI entry point, build_llms(), save_report(),
build_metadata(), and update_index().

Verifies:
    - save_report(): file creation, content structure, filename sanitisation,
      length truncation, html format output.
    - build_metadata(): all key fields present in the metadata table.
    - update_index(): file creation, topic recorded, multiple entries appended,
      short mode noted, mixed providers recorded.
    - main(): full pipeline wiring (orchestrator and synthesiser called with
      correct arguments), report and index files created, --short and --format
      flags propagated correctly, --provider flag selects the right client class.
    - build_llms(): correct client classes instantiated for all provider
      combinations, model overrides applied, mixed-provider support verified.

All tests mock LLM clients and agent classes to avoid API calls.
"""

import pytest
import sys
import os
from unittest.mock import MagicMock, patch
from llm.base import LLMResponse


# ── Sample data ───────────────────────────────────────────────────────────────

SAMPLE_RESULTS = {
    "What is fusion?": "Fusion combines light nuclei releasing energy.",
    "What are the challenges?": "Plasma confinement and materials science."
}

SAMPLE_REPORT = "# Nuclear Fusion\n\n## Executive Summary\n\nFusion is promising."

SAMPLE_METADATA = "| Field | Value |\n|---|---|\n| **Topic** | nuclear fusion |\n"


# ── save_report() tests ───────────────────────────────────────────────────────
# Verify report file creation, content structure, and filename sanitisation.

def test_save_report_creates_file(tmp_path, monkeypatch):
    """save_report() creates the output file."""
    monkeypatch.chdir(tmp_path)
    from main import save_report
    path = save_report("nuclear fusion", SAMPLE_METADATA, "# Report content")
    assert os.path.exists(path)


def test_save_report_contains_topic_heading(tmp_path, monkeypatch):
    """The topic appears as a top-level heading in the saved markdown file."""
    monkeypatch.chdir(tmp_path)
    from main import save_report
    path = save_report("nuclear fusion", SAMPLE_METADATA, "# Report content")
    with open(path) as f:
        content = f.read()
    assert "# nuclear fusion" in content.lower()


def test_save_report_contains_metadata(tmp_path, monkeypatch):
    """The metadata table is included in the saved file."""
    monkeypatch.chdir(tmp_path)
    from main import save_report
    path = save_report("nuclear fusion", SAMPLE_METADATA, "# Report content")
    with open(path) as f:
        content = f.read()
    assert "**Topic**" in content


def test_save_report_contains_report_body(tmp_path, monkeypatch):
    """The report body is included in the saved file."""
    monkeypatch.chdir(tmp_path)
    from main import save_report
    path = save_report("nuclear fusion", SAMPLE_METADATA, "# Report content")
    with open(path) as f:
        content = f.read()
    assert "# Report content" in content


def test_save_report_sanitises_filename(tmp_path, monkeypatch):
    """Special characters are stripped from the filename."""
    monkeypatch.chdir(tmp_path)
    from main import save_report
    path = save_report("nuclear fusion: a review!", SAMPLE_METADATA, "# Report")
    assert ":" not in path
    assert "!" not in path


def test_save_report_truncates_long_topic(tmp_path, monkeypatch):
    """Filenames are truncated to prevent excessively long paths."""
    monkeypatch.chdir(tmp_path)
    from main import save_report
    long_topic = "a " * 60
    path = save_report(long_topic, SAMPLE_METADATA, "# Report")
    filename = os.path.basename(path)
    assert len(filename) <= 60


def test_save_report_returns_path_string(tmp_path, monkeypatch):
    """Return value is a string path ending in .md for markdown format."""
    monkeypatch.chdir(tmp_path)
    from main import save_report
    path = save_report("nuclear fusion", SAMPLE_METADATA, "# Report")
    assert isinstance(path, str)
    assert path.endswith(".md")


def test_save_report_html_format(tmp_path, monkeypatch):
    """fmt='html' saves a .html file."""
    monkeypatch.chdir(tmp_path)
    from main import save_report
    path = save_report("nuclear fusion", SAMPLE_METADATA, "# Report", fmt="html")
    assert path.endswith(".html")
    assert os.path.exists(path)


def test_save_report_html_contains_title(tmp_path, monkeypatch):
    """HTML output contains the topic in the title and a DOCTYPE declaration."""
    monkeypatch.chdir(tmp_path)
    from main import save_report
    path = save_report("nuclear fusion", SAMPLE_METADATA, "# Report", fmt="html")
    with open(path) as f:
        content = f.read()
    assert "nuclear fusion" in content.lower()
    assert "<!DOCTYPE html>" in content


# ── build_metadata() tests ────────────────────────────────────────────────────
# Verify all key run statistics appear in the metadata table.

def test_build_metadata_contains_topic(tmp_path, monkeypatch):
    """Topic string appears in the metadata table."""
    monkeypatch.chdir(tmp_path)
    from main import build_metadata
    from config import Config
    from datetime import datetime
    metadata = build_metadata(
        topic="nuclear fusion",
        config=Config(),
        orch_provider="anthropic",
        orch_model="haiku",
        synth_provider="anthropic",
        synth_model="sonnet",
        started_at=datetime.now(),
        elapsed=10.5,
        question_count=5,
        search_count=8,
        report_chars=5000,
        short=False
    )
    assert "nuclear fusion" in metadata


def test_build_metadata_contains_search_count(tmp_path, monkeypatch):
    """Search count appears in the metadata table."""
    monkeypatch.chdir(tmp_path)
    from main import build_metadata
    from config import Config
    from datetime import datetime
    metadata = build_metadata(
        topic="nuclear fusion",
        config=Config(),
        orch_provider="anthropic",
        orch_model="haiku",
        synth_provider="anthropic",
        synth_model="sonnet",
        started_at=datetime.now(),
        elapsed=10.5,
        question_count=5,
        search_count=8,
        report_chars=5000,
        short=False
    )
    assert "8" in metadata


def test_build_metadata_contains_providers(tmp_path, monkeypatch):
    """Both provider names appear in the metadata table for mixed-provider runs."""
    monkeypatch.chdir(tmp_path)
    from main import build_metadata
    from config import Config
    from datetime import datetime
    metadata = build_metadata(
        topic="nuclear fusion",
        config=Config(),
        orch_provider="ollama",
        orch_model="llama3.1",
        synth_provider="anthropic",
        synth_model="claude-sonnet-4-6",
        started_at=datetime.now(),
        elapsed=10.5,
        question_count=5,
        search_count=8,
        report_chars=5000,
        short=False
    )
    assert "ollama" in metadata
    assert "anthropic" in metadata


def test_build_metadata_short_mode_noted(tmp_path, monkeypatch):
    """Short mode is reflected in the Mode field of the metadata table."""
    monkeypatch.chdir(tmp_path)
    from main import build_metadata
    from config import Config
    from datetime import datetime
    metadata = build_metadata(
        topic="nuclear fusion",
        config=Config(),
        orch_provider="anthropic",
        orch_model="haiku",
        synth_provider="anthropic",
        synth_model="sonnet",
        started_at=datetime.now(),
        elapsed=10.5,
        question_count=5,
        search_count=8,
        report_chars=5000,
        short=True
    )
    assert "summary" in metadata.lower() or "short" in metadata.lower()


def test_build_metadata_full_mode_noted(tmp_path, monkeypatch):
    """Full report mode is reflected in the Mode field."""
    monkeypatch.chdir(tmp_path)
    from main import build_metadata
    from config import Config
    from datetime import datetime
    metadata = build_metadata(
        topic="nuclear fusion",
        config=Config(),
        orch_provider="anthropic",
        orch_model="haiku",
        synth_provider="anthropic",
        synth_model="sonnet",
        started_at=datetime.now(),
        elapsed=10.5,
        question_count=5,
        search_count=8,
        report_chars=5000,
        short=False
    )
    assert "Full Report" in metadata


# ── update_index() tests ──────────────────────────────────────────────────────
# Verify index.md creation and row appending.

def test_update_index_creates_file(tmp_path, monkeypatch):
    """update_index() creates output/index.md on first call."""
    monkeypatch.chdir(tmp_path)
    from main import update_index
    from datetime import datetime
    update_index(
        topic="nuclear fusion",
        output_path="output/nuclear_fusion.md",
        started_at=datetime.now(),
        orch_provider="anthropic",
        orch_model="haiku",
        synth_provider="anthropic",
        synth_model="sonnet",
        question_count=5,
        search_count=8,
        short=False
    )
    assert os.path.exists(tmp_path / "output" / "index.md")


def test_update_index_contains_topic(tmp_path, monkeypatch):
    """The topic appears in the index row."""
    monkeypatch.chdir(tmp_path)
    from main import update_index
    from datetime import datetime
    update_index(
        topic="nuclear fusion",
        output_path="output/nuclear_fusion.md",
        started_at=datetime.now(),
        orch_provider="anthropic",
        orch_model="haiku",
        synth_provider="anthropic",
        synth_model="sonnet",
        question_count=5,
        search_count=8,
        short=False
    )
    with open(tmp_path / "output" / "index.md") as f:
        content = f.read()
    assert "nuclear fusion" in content


def test_update_index_appends_multiple_entries(tmp_path, monkeypatch):
    """Multiple calls append multiple rows; all topics are present."""
    monkeypatch.chdir(tmp_path)
    from main import update_index
    from datetime import datetime
    for topic in ["nuclear fusion", "quantum computing"]:
        update_index(
            topic=topic,
            output_path=f"output/{topic.replace(' ', '_')}.md",
            started_at=datetime.now(),
            orch_provider="anthropic",
            orch_model="haiku",
            synth_provider="anthropic",
            synth_model="sonnet",
            question_count=5,
            search_count=8,
            short=False
        )
    with open(tmp_path / "output" / "index.md") as f:
        content = f.read()
    assert "nuclear fusion" in content
    assert "quantum computing" in content


def test_update_index_short_mode_noted(tmp_path, monkeypatch):
    """Short mode is recorded as 'Summary' in the index row."""
    monkeypatch.chdir(tmp_path)
    from main import update_index
    from datetime import datetime
    update_index(
        topic="nuclear fusion",
        output_path="output/nuclear_fusion.md",
        started_at=datetime.now(),
        orch_provider="anthropic",
        orch_model="haiku",
        synth_provider="anthropic",
        synth_model="sonnet",
        question_count=5,
        search_count=8,
        short=True
    )
    with open(tmp_path / "output" / "index.md") as f:
        content = f.read()
    assert "Summary" in content


def test_update_index_mixed_providers_recorded(tmp_path, monkeypatch):
    """Both provider names are recorded in the index row for mixed-provider runs."""
    monkeypatch.chdir(tmp_path)
    from main import update_index
    from datetime import datetime
    update_index(
        topic="nuclear fusion",
        output_path="output/nuclear_fusion.md",
        started_at=datetime.now(),
        orch_provider="ollama",
        orch_model="llama3.1",
        synth_provider="anthropic",
        synth_model="claude-sonnet-4-6",
        question_count=5,
        search_count=8,
        short=False
    )
    with open(tmp_path / "output" / "index.md") as f:
        content = f.read()
    assert "ollama" in content
    assert "anthropic" in content


# ── main() tests ──────────────────────────────────────────────────────────────
# Verify the full pipeline wiring: correct calls to orchestrator, synthesiser,
# and file system, plus flag propagation.

def test_main_exits_without_args():
    """main() exits with code 2 (argparse error) when no topic is provided."""
    with patch("sys.argv", ["main.py"]):
        with pytest.raises(SystemExit) as exc:
            from main import main
            main()
    assert exc.value.code == 2


def test_main_runs_full_pipeline(tmp_path, monkeypatch):
    """main() calls orchestrator.run() and synthesiser.synthesise() with correct args."""
    monkeypatch.chdir(tmp_path)

    mock_llm = MagicMock()
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()

    mock_orchestrator.run.return_value = (SAMPLE_RESULTS, {})
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion"]), \
         patch("main.AnthropicClient", return_value=mock_llm), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    mock_orchestrator.run.assert_called_once_with("nuclear fusion")
    mock_synthesiser.synthesise.assert_called_once_with(
        topic="nuclear fusion",
        results=SAMPLE_RESULTS,
        sources={},
        short=False
    )


def test_main_saves_report_to_output(tmp_path, monkeypatch):
    """main() creates exactly one .md report file in output/ (excluding index.md)."""
    monkeypatch.chdir(tmp_path)

    mock_llm = MagicMock()
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()

    mock_orchestrator.run.return_value = (SAMPLE_RESULTS, {})
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion"]), \
         patch("main.AnthropicClient", return_value=mock_llm), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    output_files = [f for f in os.listdir(tmp_path / "output")
                    if f.endswith(".md") and f != "index.md"]
    assert len(output_files) == 1
    assert output_files[0].endswith(".md")


def test_main_short_flag_passed_to_synthesiser(tmp_path, monkeypatch):
    """--short flag causes synthesise() to receive short=True."""
    monkeypatch.chdir(tmp_path)

    mock_llm = MagicMock()
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()

    mock_orchestrator.run.return_value = (SAMPLE_RESULTS, {})
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion", "--short"]), \
         patch("main.AnthropicClient", return_value=mock_llm), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    call_kwargs = mock_synthesiser.synthesise.call_args[1]
    assert call_kwargs.get("short") is True


def test_main_html_format_saves_html_file(tmp_path, monkeypatch):
    """--format html saves a .html file in output/."""
    monkeypatch.chdir(tmp_path)

    mock_llm = MagicMock()
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()

    mock_orchestrator.run.return_value = (SAMPLE_RESULTS, {})
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion", "--format", "html"]), \
         patch("main.AnthropicClient", return_value=mock_llm), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    output_files = os.listdir(tmp_path / "output")
    html_files = [f for f in output_files if f.endswith(".html")]
    assert len(html_files) == 1


def test_main_creates_index_entry(tmp_path, monkeypatch):
    """main() creates output/index.md and records the topic."""
    monkeypatch.chdir(tmp_path)

    mock_llm = MagicMock()
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()

    mock_orchestrator.run.return_value = (SAMPLE_RESULTS, {})
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion"]), \
         patch("main.AnthropicClient", return_value=mock_llm), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    assert os.path.exists(tmp_path / "output" / "index.md")
    with open(tmp_path / "output" / "index.md") as f:
        content = f.read()
    assert "nuclear fusion" in content


def test_main_mixed_provider_orchestration(tmp_path, monkeypatch):
    """--orchestration-provider ollama --synthesis-provider anthropic instantiates both clients."""
    monkeypatch.chdir(tmp_path)

    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()

    mock_orchestrator.run.return_value = (SAMPLE_RESULTS, {})
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion",
                             "--orchestration-provider", "ollama",
                             "--orchestration-model", "llama3.1",
                             "--synthesis-provider", "anthropic",
                             "--synthesis-model", "claude-sonnet-4-6"]), \
         patch("main.OllamaClient") as mock_ollama, \
         patch("main.AnthropicClient") as mock_anthropic, \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    assert mock_ollama.called
    assert mock_anthropic.called


# ── build_llms() tests ────────────────────────────────────────────────────────
# Verify provider/model resolution for all Config combinations.

def test_build_llms_returns_two_anthropic_clients():
    """provider='anthropic' instantiates AnthropicClient for both tiers."""
    from main import build_llms
    from config import Config
    with patch("main.AnthropicClient") as mock:
        orch, synth, orch_p, orch_m, synth_p, synth_m = build_llms(Config(provider="anthropic"))
        assert mock.call_count == 2


def test_build_llms_returns_two_ollama_clients():
    """provider='ollama' instantiates OllamaClient for both tiers."""
    from main import build_llms
    from config import Config
    with patch("main.OllamaClient") as mock:
        orch, synth, orch_p, orch_m, synth_p, synth_m = build_llms(Config(provider="ollama"))
        assert mock.call_count == 2


def test_build_llms_anthropic_uses_different_models_by_default():
    """Default Anthropic config uses different models for orchestration and synthesis."""
    from main import build_llms
    from config import Config
    with patch("main.AnthropicClient") as mock:
        build_llms(Config(provider="anthropic"))
        models = [c[1].get("model") for c in mock.call_args_list]
        assert models[0] != models[1]


def test_build_llms_model_override_applies_to_both():
    """Global model override sets the same model for both tiers."""
    from main import build_llms
    from config import Config
    with patch("main.AnthropicClient") as mock:
        build_llms(Config(provider="anthropic", model="claude-sonnet-4-6"))
        for call in mock.call_args_list:
            assert call[1].get("model") == "claude-sonnet-4-6"


def test_build_llms_unknown_provider_exits():
    """An unrecognised provider triggers SystemExit."""
    from main import build_llms
    from config import Config
    with pytest.raises(SystemExit):
        build_llms(Config(provider="unknown_provider"))


def test_build_llms_mixed_providers():
    """orchestration_provider='ollama' + synthesis_provider='anthropic' uses both clients."""
    from main import build_llms
    from config import Config
    with patch("main.OllamaClient") as mock_ollama, \
         patch("main.AnthropicClient") as mock_anthropic:
        orch, synth, orch_p, orch_m, synth_p, synth_m = build_llms(
            Config(provider="anthropic",
                   orchestration_provider="ollama",
                   synthesis_provider="anthropic")
        )
    assert mock_ollama.called
    assert mock_anthropic.called
    assert orch_p == "ollama"
    assert synth_p == "anthropic"


def test_build_llms_returns_correct_provider_names():
    """build_llms() returns the resolved provider and model strings in the 6-tuple."""
    from main import build_llms
    from config import Config
    with patch("main.AnthropicClient"):
        _, _, orch_p, orch_m, synth_p, synth_m = build_llms(Config(provider="anthropic"))
    assert orch_p == "anthropic"
    assert synth_p == "anthropic"
    assert orch_m == "claude-haiku-4-5-20251001"
    assert synth_m == "claude-sonnet-4-6"


def test_main_uses_anthropic_by_default(tmp_path, monkeypatch):
    """Without a --provider flag, AnthropicClient is used."""
    monkeypatch.chdir(tmp_path)
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()
    mock_orchestrator.run.return_value = (SAMPLE_RESULTS, {})
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion"]), \
         patch("main.AnthropicClient") as mock_anthropic, \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()
    assert mock_anthropic.called


def test_main_uses_ollama_when_specified(tmp_path, monkeypatch):
    """--provider ollama causes OllamaClient to be used."""
    monkeypatch.chdir(tmp_path)
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()
    mock_orchestrator.run.return_value = (SAMPLE_RESULTS, {})
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion", "--provider", "ollama"]), \
         patch("main.OllamaClient") as mock_ollama, \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()
    assert mock_ollama.called


# ── Integration tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
def test_real_full_pipeline(tmp_path, monkeypatch):
    """Live end-to-end pipeline run produces a non-trivial report with metadata."""
    monkeypatch.chdir(tmp_path)

    with patch("sys.argv", ["main.py", "the current state of nuclear fusion energy"]):
        from main import main
        main()

    output_files = [f for f in os.listdir(tmp_path / "output")
                    if f.endswith(".md") and f != "index.md"]
    assert len(output_files) == 1

    with open(tmp_path / "output" / output_files[0]) as f:
        content = f.read()

    assert len(content) > 1000
    assert "#" in content
    assert "**Topic**" in content
