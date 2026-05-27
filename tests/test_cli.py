"""
Tests for main.py CLI entry point and extracted output/llm modules.

Covers:
- save_report(): file creation, content, filename sanitisation, format variants
  (output.writer)
- build_metadata(): table content, provider display, mode flags
  (output.formatter)
- update_index(): file creation, content, multiple entries, mixed providers
  (output.writer)
- main(): full pipeline, flag passing, provider selection, format selection
- build_llms(): provider routing, model resolution, mixed providers, 6-tuple return
  (llm.builder)
- convert_to_pdf(): weasyprint integration, import error handling
  (output.formatter)

Integration tests require a live Anthropic API key and are marked accordingly.
"""

import pytest
import sys
import os
from unittest.mock import MagicMock, patch
from llm.base import LLMResponse


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_build_agents():
    """Patch build_agents in main for every test in this file.

    All test_main_* tests call main() which now calls build_agents() to load
    prompt files from disk. In tests the prompts/ directory does not exist,
    so we always replace build_agents with a no-op mock. Tests that verify
    agent construction use test_agent_builder.py instead.
    """
    with patch("main.build_agents"):
        yield


# ── Sample data ───────────────────────────────────────────────────────────────

SAMPLE_RESULTS = {
    "What is fusion?": "Fusion combines light nuclei releasing energy.",
    "What are the challenges?": "Plasma confinement and materials science."
}

SAMPLE_REPORT = "# Nuclear Fusion\n\n## Executive Summary\n\nFusion is promising."

SAMPLE_METADATA = "| Field | Value |\n|---|---|\n| **Topic** | nuclear fusion |\n"


# ── save_report() tests ───────────────────────────────────────────────────────

def test_save_report_creates_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import save_report
    path = save_report("nuclear fusion", SAMPLE_METADATA, "# Report content")
    assert os.path.exists(path)


def test_save_report_contains_topic_heading(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import save_report
    path = save_report("nuclear fusion", SAMPLE_METADATA, "# Report content")
    with open(path) as f:
        content = f.read()
    assert "# nuclear fusion" in content.lower()


def test_save_report_contains_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import save_report
    path = save_report("nuclear fusion", SAMPLE_METADATA, "# Report content")
    with open(path) as f:
        content = f.read()
    assert "**Topic**" in content


def test_save_report_contains_report_body(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import save_report
    path = save_report("nuclear fusion", SAMPLE_METADATA, "# Report content")
    with open(path) as f:
        content = f.read()
    assert "# Report content" in content


def test_save_report_sanitises_filename(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import save_report
    path = save_report("nuclear fusion: a review!", SAMPLE_METADATA, "# Report")
    assert ":" not in path
    assert "!" not in path


def test_save_report_truncates_long_topic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import save_report
    long_topic = "a " * 60
    path = save_report(long_topic, SAMPLE_METADATA, "# Report")
    filename = os.path.basename(path)
    assert len(filename) <= 60


def test_save_report_returns_path_string(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import save_report
    path = save_report("nuclear fusion", SAMPLE_METADATA, "# Report")
    assert isinstance(path, str)
    assert path.endswith(".md")


def test_save_report_html_format(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import save_report
    path = save_report("nuclear fusion", SAMPLE_METADATA, "# Report", fmt="html")
    assert path.endswith(".html")
    assert os.path.exists(path)


def test_save_report_html_contains_title(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import save_report
    path = save_report("nuclear fusion", SAMPLE_METADATA, "# Report", fmt="html")
    with open(path) as f:
        content = f.read()
    assert "nuclear fusion" in content.lower()
    assert "<!DOCTYPE html>" in content


def test_save_report_pdf_format(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import save_report
    with patch("output.writer.convert_to_pdf") as mock_pdf:
        path = save_report("nuclear fusion", SAMPLE_METADATA, "# Report", fmt="pdf")
    assert path.endswith(".pdf")
    mock_pdf.assert_called_once()


def test_save_report_pdf_passes_html_to_converter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import save_report
    with patch("output.writer.convert_to_pdf") as mock_pdf, \
         patch("output.writer.convert_to_html", return_value="<html>test</html>") as mock_html:
        save_report("nuclear fusion", SAMPLE_METADATA, "# Report", fmt="pdf")
    mock_html.assert_called_once()
    mock_pdf.assert_called_once_with("<html>test</html>", "output/nuclear_fusion.pdf")


def test_save_report_pdf_not_md_or_html(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import save_report
    with patch("output.writer.convert_to_pdf"):
        path = save_report("nuclear fusion", SAMPLE_METADATA, "# Report", fmt="pdf")
    assert not path.endswith(".md")
    assert not path.endswith(".html")


def test_save_report_handles_punctuation_only_topic(tmp_path, monkeypatch):
    """Punctuation-only topic must not produce a hidden file (output/.md)."""
    monkeypatch.chdir(tmp_path)
    from output.writer import save_report
    path = save_report("???", "| Field | Value |", "# Report")
    filename = os.path.basename(path)
    assert not filename.startswith(".")
    assert os.path.exists(path)


def test_save_report_handles_empty_sanitised_topic(tmp_path, monkeypatch):
    """Topic that sanitises to empty string produces a valid fallback filename."""
    monkeypatch.chdir(tmp_path)
    from output.writer import save_report
    path = save_report("!!!", "| Field | Value |", "# Report")
    assert os.path.exists(path)
    assert os.path.basename(path) != ".md"


def test_save_report_default_is_markdown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import save_report
    path = save_report("nuclear fusion", SAMPLE_METADATA, "# Report")
    assert path.endswith(".md")


# ── build_metadata() tests ────────────────────────────────────────────────────

def test_build_metadata_contains_topic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.formatter import build_metadata
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
    monkeypatch.chdir(tmp_path)
    from output.formatter import build_metadata
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
    monkeypatch.chdir(tmp_path)
    from output.formatter import build_metadata
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
    monkeypatch.chdir(tmp_path)
    from output.formatter import build_metadata
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
    monkeypatch.chdir(tmp_path)
    from output.formatter import build_metadata
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


def test_build_metadata_contains_search_provider(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.formatter import build_metadata
    from config import Config
    from datetime import datetime
    config = Config()
    config.search_provider = "tavily"
    metadata = build_metadata(
        topic="nuclear fusion",
        config=config,
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
    assert "tavily" in metadata


def test_build_metadata_contains_elapsed_time(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.formatter import build_metadata
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
        elapsed=42.5,
        question_count=5,
        search_count=8,
        report_chars=5000,
        short=False
    )
    assert "42.5" in metadata


def test_build_metadata_is_markdown_table(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.formatter import build_metadata
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
    assert "|" in metadata
    assert "---" in metadata


# ── update_index() tests ──────────────────────────────────────────────────────

def test_update_index_creates_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import update_index
    from datetime import datetime
    update_index(
        topic="nuclear fusion",
        output_path="output/nuclear_fusion.md",
        started_at=datetime.now(),
        orch_provider="anthropic",
        orch_model="haiku",
        synth_provider="anthropic",
        synth_model="sonnet",
        search_provider="anthropic",
        question_count=5,
        search_count=8,
        short=False,
        provenance="none"
    )
    assert os.path.exists(tmp_path / "output" / "index.md")


def test_update_index_contains_topic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import update_index
    from datetime import datetime
    update_index(
        topic="nuclear fusion",
        output_path="output/nuclear_fusion.md",
        started_at=datetime.now(),
        orch_provider="anthropic",
        orch_model="haiku",
        synth_provider="anthropic",
        synth_model="sonnet",
        search_provider="anthropic",
        question_count=5,
        search_count=8,
        short=False,
        provenance="none"
    )
    with open(tmp_path / "output" / "index.md") as f:
        content = f.read()
    assert "nuclear fusion" in content


def test_update_index_appends_multiple_entries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import update_index
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
            search_provider="anthropic",
            question_count=5,
            search_count=8,
            short=False,
            provenance="none"
        )
    with open(tmp_path / "output" / "index.md") as f:
        content = f.read()
    assert "nuclear fusion" in content
    assert "quantum computing" in content


def test_update_index_short_mode_noted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import update_index
    from datetime import datetime
    update_index(
        topic="nuclear fusion",
        output_path="output/nuclear_fusion.md",
        started_at=datetime.now(),
        orch_provider="anthropic",
        orch_model="haiku",
        synth_provider="anthropic",
        synth_model="sonnet",
        search_provider="anthropic",
        question_count=5,
        search_count=8,
        short=True,
        provenance="none"
    )
    with open(tmp_path / "output" / "index.md") as f:
        content = f.read()
    assert "Summary" in content


def test_update_index_full_mode_noted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import update_index
    from datetime import datetime
    update_index(
        topic="nuclear fusion",
        output_path="output/nuclear_fusion.md",
        started_at=datetime.now(),
        orch_provider="anthropic",
        orch_model="haiku",
        synth_provider="anthropic",
        synth_model="sonnet",
        search_provider="anthropic",
        question_count=5,
        search_count=8,
        short=False,
        provenance="none"
    )
    with open(tmp_path / "output" / "index.md") as f:
        content = f.read()
    assert "Full" in content


def test_update_index_mixed_providers_recorded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import update_index
    from datetime import datetime
    update_index(
        topic="nuclear fusion",
        output_path="output/nuclear_fusion.md",
        started_at=datetime.now(),
        orch_provider="ollama",
        orch_model="llama3.1",
        synth_provider="anthropic",
        synth_model="claude-sonnet-4-6",
        search_provider="anthropic",
        question_count=5,
        search_count=8,
        short=False,
        provenance="none"
    )
    with open(tmp_path / "output" / "index.md") as f:
        content = f.read()
    assert "ollama" in content
    assert "anthropic" in content


def test_update_index_creates_header_row(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import update_index
    from datetime import datetime
    update_index(
        topic="nuclear fusion",
        output_path="output/nuclear_fusion.md",
        started_at=datetime.now(),
        orch_provider="anthropic",
        orch_model="haiku",
        synth_provider="anthropic",
        synth_model="sonnet",
        search_provider="anthropic",
        question_count=5,
        search_count=8,
        short=False,
        provenance="none"
    )
    with open(tmp_path / "output" / "index.md") as f:
        content = f.read()
    assert "# Research Agent" in content
    assert "| Date |" in content


def test_update_index_contains_file_link(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from output.writer import update_index
    from datetime import datetime
    update_index(
        topic="nuclear fusion",
        output_path="output/nuclear_fusion.md",
        started_at=datetime.now(),
        orch_provider="anthropic",
        orch_model="haiku",
        synth_provider="anthropic",
        synth_model="sonnet",
        search_provider="anthropic",
        question_count=5,
        search_count=8,
        short=False,
        provenance="none"
    )
    with open(tmp_path / "output" / "index.md") as f:
        content = f.read()
    assert "nuclear_fusion.md" in content


# ── main() tests ──────────────────────────────────────────────────────────────

def test_main_exits_without_args():
    with patch("sys.argv", ["main.py"]):
        with pytest.raises(SystemExit) as exc:
            from main import main
            main()
    assert exc.value.code == 2


def test_main_runs_full_pipeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    mock_llm = MagicMock()
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()

    mock_orchestrator.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion"]), \
         patch("llm.builder.AnthropicClient", return_value=mock_llm), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    mock_orchestrator.run.assert_called_once_with("nuclear fusion")
    mock_synthesiser.synthesise.assert_called_once_with(
        topic="nuclear fusion",
        results=SAMPLE_RESULTS,
        sources={},
        short=False,
        claims=None,
    )


def test_main_saves_report_to_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    mock_llm = MagicMock()
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()

    mock_orchestrator.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion"]), \
         patch("llm.builder.AnthropicClient", return_value=mock_llm), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    output_files = [f for f in os.listdir(tmp_path / "output")
                    if f.endswith(".md") and f != "index.md"]
    assert len(output_files) == 1
    assert output_files[0].endswith(".md")


def test_main_short_flag_passed_to_synthesiser(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    mock_llm = MagicMock()
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()

    mock_orchestrator.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion", "--short"]), \
         patch("llm.builder.AnthropicClient", return_value=mock_llm), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    call_kwargs = mock_synthesiser.synthesise.call_args[1]
    assert call_kwargs.get("short") is True


def test_main_short_flag_short_form(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    mock_llm = MagicMock()
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()

    mock_orchestrator.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion", "-s"]), \
         patch("llm.builder.AnthropicClient", return_value=mock_llm), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    call_kwargs = mock_synthesiser.synthesise.call_args[1]
    assert call_kwargs.get("short") is True


def test_main_html_format_saves_html_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    mock_llm = MagicMock()
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()

    mock_orchestrator.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion", "--format", "html"]), \
         patch("llm.builder.AnthropicClient", return_value=mock_llm), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    output_files = os.listdir(tmp_path / "output")
    html_files = [f for f in output_files if f.endswith(".html")]
    assert len(html_files) == 1


def test_main_pdf_format_saves_pdf_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    mock_llm = MagicMock()
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()

    mock_orchestrator.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion", "--format", "pdf"]), \
         patch("llm.builder.AnthropicClient", return_value=mock_llm), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser), \
         patch("output.writer.convert_to_pdf") as mock_pdf, \
         patch.dict("sys.modules", {"weasyprint": MagicMock()}):
        from main import main
        main()

    mock_pdf.assert_called_once()


def test_main_creates_index_entry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    mock_llm = MagicMock()
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()

    mock_orchestrator.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion"]), \
         patch("llm.builder.AnthropicClient", return_value=mock_llm), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    assert os.path.exists(tmp_path / "output" / "index.md")
    with open(tmp_path / "output" / "index.md") as f:
        content = f.read()
    assert "nuclear fusion" in content


def test_main_mixed_provider_orchestration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()

    mock_orchestrator.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion",
                             "--orchestration-provider", "ollama",
                             "--orchestration-model", "llama3.1",
                             "--synthesis-provider", "anthropic",
                             "--synthesis-model", "claude-sonnet-4-6"]), \
         patch("llm.builder.OllamaClient") as mock_ollama, \
         patch("llm.builder.AnthropicClient") as mock_anthropic, \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    assert mock_ollama.called
    assert mock_anthropic.called


def test_main_uses_anthropic_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()
    mock_orchestrator.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion"]), \
         patch("llm.builder.AnthropicClient") as mock_anthropic, \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()
    assert mock_anthropic.called


def test_main_uses_ollama_when_specified(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()
    mock_orchestrator.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion", "--provider", "ollama"]), \
         patch("llm.builder.OllamaClient") as mock_ollama, \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()
    assert mock_ollama.called


def test_main_multi_word_topic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()
    mock_orchestrator.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "the", "current", "state", "of", "nuclear", "fusion"]), \
         patch("llm.builder.AnthropicClient"), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    mock_orchestrator.run.assert_called_once_with(
        "the current state of nuclear fusion"
    )


# ── build_llms() tests ────────────────────────────────────────────────────────

def test_build_llms_returns_two_anthropic_clients():
    from llm.builder import build_llms
    from config import Config
    with patch("llm.builder.AnthropicClient") as mock:
        orch, synth, orch_p, orch_m, synth_p, synth_m = build_llms(Config(provider="anthropic"))
        assert mock.call_count == 2


def test_build_llms_returns_two_ollama_clients():
    from llm.builder import build_llms
    from config import Config
    with patch("llm.builder.OllamaClient") as mock:
        orch, synth, orch_p, orch_m, synth_p, synth_m = build_llms(Config(provider="ollama"))
        assert mock.call_count == 2


def test_build_llms_anthropic_uses_different_models_by_default():
    from llm.builder import build_llms
    from config import Config
    with patch("llm.builder.AnthropicClient") as mock:
        build_llms(Config(provider="anthropic"))
        models = [c[1].get("model") for c in mock.call_args_list]
        assert models[0] != models[1]


def test_build_llms_model_override_applies_to_both():
    from llm.builder import build_llms
    from config import Config
    with patch("llm.builder.AnthropicClient") as mock:
        build_llms(Config(provider="anthropic", model="claude-sonnet-4-6"))
        for call in mock.call_args_list:
            assert call[1].get("model") == "claude-sonnet-4-6"


def test_build_llms_unknown_provider_raises_value_error():
    from llm.builder import build_llms
    from config import Config
    with pytest.raises(ValueError, match="unknown_provider"):
        build_llms(Config(provider="unknown_provider"))


def test_main_exits_on_unknown_provider(tmp_path, monkeypatch):
    """main() catches ValueError from build_llms and exits with code 1."""
    monkeypatch.chdir(tmp_path)
    from config import Config
    bad_config = Config(provider="unknown_provider")
    with patch("sys.argv", ["main.py", "nuclear fusion"]), \
         patch("main.load_config", return_value=bad_config):
        with pytest.raises(SystemExit) as exc:
            from main import main
            main()
    assert exc.value.code == 1


def test_build_llms_mixed_providers():
    from llm.builder import build_llms
    from config import Config
    with patch("llm.builder.OllamaClient") as mock_ollama, \
         patch("llm.builder.AnthropicClient") as mock_anthropic:
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
    from llm.builder import build_llms
    from config import Config
    with patch("llm.builder.AnthropicClient"):
        _, _, orch_p, orch_m, synth_p, synth_m = build_llms(Config(provider="anthropic"))
    assert orch_p == "anthropic"
    assert synth_p == "anthropic"
    assert orch_m == "claude-haiku-4-5-20251001"
    assert synth_m == "claude-sonnet-4-6"


def test_build_llms_returns_six_tuple():
    from llm.builder import build_llms
    from config import Config
    with patch("llm.builder.AnthropicClient"):
        result = build_llms(Config(provider="anthropic"))
    assert len(result) == 6


# ── convert_to_pdf() tests ────────────────────────────────────────────────────

def test_convert_to_pdf_calls_weasyprint(tmp_path):
    from output.formatter import convert_to_pdf

    mock_html_class = MagicMock()
    mock_css_class = MagicMock()
    mock_font_config = MagicMock()

    mock_weasyprint = MagicMock()
    mock_weasyprint.HTML = mock_html_class
    mock_weasyprint.CSS = mock_css_class

    mock_fonts = MagicMock()
    mock_fonts.FontConfiguration = MagicMock(return_value=mock_font_config)

    with patch.dict("sys.modules", {
        "weasyprint": mock_weasyprint,
        "weasyprint.text": MagicMock(),
        "weasyprint.text.fonts": mock_fonts
    }):
        convert_to_pdf("<html>test</html>", str(tmp_path / "test.pdf"))

    mock_html_class.assert_called_once_with(string="<html>test</html>")
    mock_html_class.return_value.write_pdf.assert_called_once()


def test_convert_to_pdf_raises_on_missing_weasyprint(tmp_path):
    from output.formatter import convert_to_pdf
    with patch.dict("sys.modules", {"weasyprint": None}):
        with pytest.raises((ImportError, Exception)):
            convert_to_pdf("<html>test</html>", str(tmp_path / "test.pdf"))


# ── H1 — CLI model override aliasing tests ───────────────────────────────────

def test_orchestration_model_sets_only_ollama_field_when_ollama_provider(
    tmp_path, monkeypatch
):
    """--orchestration-model with Ollama provider only sets ollama_orchestration_model."""
    monkeypatch.chdir(tmp_path)
    captured = {}
    mock_synth = MagicMock()
    mock_synth.synthesise.return_value = SAMPLE_REPORT

    def capture_orchestrator(*args, **kwargs):
        captured["config"] = kwargs.get("config") or args[1]
        m = MagicMock()
        m.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
        return m

    with patch("sys.argv", ["main.py", "nuclear fusion",
                             "--orchestration-provider", "ollama",
                             "--orchestration-model", "llama3.1"]), \
         patch("llm.builder.OllamaClient"), \
         patch("llm.builder.AnthropicClient"), \
         patch("main.Orchestrator", side_effect=capture_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synth):
        from main import main
        main()

    config = captured["config"]
    assert config.ollama_orchestration_model == "llama3.1"
    assert config.anthropic_orchestration_model == "claude-haiku-4-5-20251001"


def test_orchestration_model_sets_only_anthropic_field_when_anthropic_provider(
    tmp_path, monkeypatch
):
    """--orchestration-model with Anthropic provider only sets anthropic_orchestration_model."""
    monkeypatch.chdir(tmp_path)
    captured = {}
    mock_synth = MagicMock()
    mock_synth.synthesise.return_value = SAMPLE_REPORT

    def capture_orchestrator(*args, **kwargs):
        captured["config"] = kwargs.get("config") or args[1]
        m = MagicMock()
        m.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
        return m

    with patch("sys.argv", ["main.py", "nuclear fusion",
                             "--orchestration-provider", "anthropic",
                             "--orchestration-model", "claude-sonnet-4-6"]), \
         patch("llm.builder.AnthropicClient"), \
         patch("main.Orchestrator", side_effect=capture_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synth):
        from main import main
        main()

    config = captured["config"]
    assert config.anthropic_orchestration_model == "claude-sonnet-4-6"
    assert config.ollama_orchestration_model == "llama3.1"


# ── bleach import guard tests ────────────────────────────────────────────────

def test_main_exits_when_bleach_missing_and_html_format(tmp_path, monkeypatch, capsys):
    """main() exits with code 1 and prints an error when bleach is absent and format=html."""
    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["main.py", "nuclear fusion", "--format", "html"]), \
         patch("main.load_config", return_value=MagicMock(
             provider="anthropic", orchestration_provider=None,
             synthesis_provider=None, model=None,
             orchestration_model=None, synthesis_model=None,
             search_provider="anthropic", tavily_api_key=None,
             tavily_max_results=5, anthropic_search_model="claude-haiku-4-5-20251001",
         )), \
         patch.dict("sys.modules", {"bleach": None}):
        with pytest.raises(SystemExit) as exc:
            from main import main
            main()
    assert exc.value.code == 1
    assert "bleach" in capsys.readouterr().err


def test_main_exits_when_bleach_missing_and_pdf_format(tmp_path, monkeypatch, capsys):
    """main() exits with code 1 and prints an error when bleach is absent and format=pdf."""
    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["main.py", "nuclear fusion", "--format", "pdf"]), \
         patch("main.load_config", return_value=MagicMock(
             provider="anthropic", orchestration_provider=None,
             synthesis_provider=None, model=None,
             orchestration_model=None, synthesis_model=None,
             search_provider="anthropic", tavily_api_key=None,
             tavily_max_results=5, anthropic_search_model="claude-haiku-4-5-20251001",
         )), \
         patch.dict("sys.modules", {"bleach": None}):
        with pytest.raises(SystemExit) as exc:
            from main import main
            main()
    assert exc.value.code == 1
    assert "bleach" in capsys.readouterr().err


def test_main_exits_when_weasyprint_missing_and_pdf_format(tmp_path, monkeypatch, capsys):
    """main() exits with code 1 and prints brew hint when weasyprint absent and format=pdf."""
    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["main.py", "nuclear fusion", "--format", "pdf"]), \
         patch("main.load_config", return_value=MagicMock(
             provider="anthropic", orchestration_provider=None,
             synthesis_provider=None, model=None,
             orchestration_model=None, synthesis_model=None,
             search_provider="anthropic", tavily_api_key=None,
             tavily_max_results=5, anthropic_search_model="claude-haiku-4-5-20251001",
         )), \
         patch.dict("sys.modules", {"weasyprint": None}):
        with pytest.raises(SystemExit) as exc:
            from main import main
            main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "weasyprint" in err
    assert "brew install pango" in err


# ── Ollama max_workers warning tests ─────────────────────────────────────────

def test_main_warns_when_ollama_exceeds_safe_workers(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()
    mock_orchestrator.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion",
                             "--provider", "ollama",
                             "--max-workers", "4"]), \
         patch("llm.builder.OllamaClient"), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    captured = capsys.readouterr()
    assert "Warning" in captured.out
    assert "max_workers" in captured.out


def test_main_no_warning_when_ollama_safe_workers(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()
    mock_orchestrator.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion",
                             "--provider", "ollama",
                             "--max-workers", "2"]), \
         patch("llm.builder.OllamaClient"), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    captured = capsys.readouterr()
    assert "Warning" not in captured.out


def test_main_no_warning_when_anthropic_high_workers(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()
    mock_orchestrator.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion",
                             "--provider", "anthropic",
                             "--max-workers", "8"]), \
         patch("llm.builder.AnthropicClient"), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    captured = capsys.readouterr()
    assert "Warning" not in captured.out


# ── Provenance pipeline ordering tests ───────────────────────────────────────

def test_main_synthesise_receives_claims_when_provenance_file(tmp_path, monkeypatch):
    """When --provenance file, synthesise() receives the claims list extracted before it."""
    import json as _json
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / "output", exist_ok=True)
    # write_provenance_file must return a real path so main() can json.load it
    prov_json_path = str(tmp_path / "output" / "nuclear_fusion.provenance.json")
    with open(prov_json_path, "w") as _f:
        _json.dump({"schema_version": "1.0", "claims": [], "quality_metrics": {}}, _f)

    mock_llm = MagicMock()
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()
    mock_orchestrator.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT
    fake_claims = [{"id": 1, "claim": "fusion works", "synthesis_status": "not_attempted"}]

    with patch("sys.argv", ["main.py", "nuclear fusion", "--provenance", "file"]), \
         patch("llm.builder.AnthropicClient", return_value=mock_llm), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser), \
         patch("main.build_claims_from_results", return_value=fake_claims), \
         patch("main.annotate_report_lines", return_value=(SAMPLE_REPORT, fake_claims)), \
         patch("main.write_provenance_file", return_value=prov_json_path), \
         patch("main.save_viewer", return_value="output/nuclear_fusion.viewer.html"), \
         patch("main.build_quality_metrics", return_value={}):
        from main import main
        main()

    call_kwargs = mock_synthesiser.synthesise.call_args[1]
    assert call_kwargs.get("claims") == fake_claims


def test_main_synthesise_receives_no_claims_when_provenance_none(tmp_path, monkeypatch):
    """When provenance is none (default), synthesise() is called with claims=None."""
    monkeypatch.chdir(tmp_path)
    mock_llm = MagicMock()
    mock_orchestrator = MagicMock()
    mock_synthesiser = MagicMock()
    mock_orchestrator.run.return_value = ((SAMPLE_RESULTS, {}), "test-run-id-123")
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion"]), \
         patch("llm.builder.AnthropicClient", return_value=mock_llm), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    call_kwargs = mock_synthesiser.synthesise.call_args[1]
    assert call_kwargs.get("claims") is None


# ── Integration tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
def test_real_full_pipeline(tmp_path, monkeypatch):
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


@pytest.mark.integration
def test_real_html_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with patch("sys.argv", ["main.py", "nuclear fusion", "--format", "html", "--short"]):
        from main import main
        main()

    output_files = [f for f in os.listdir(tmp_path / "output")
                    if f.endswith(".html")]
    assert len(output_files) == 1

    with open(tmp_path / "output" / output_files[0]) as f:
        content = f.read()

    assert "<!DOCTYPE html>" in content
    assert "nuclear fusion" in content.lower()
