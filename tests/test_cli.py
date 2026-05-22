import pytest
import sys
import os
from unittest.mock import MagicMock, patch
from llm.base import LLMResponse


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_RESULTS = {
    "What is fusion?": "Fusion combines light nuclei releasing energy.",
    "What are the challenges?": "Plasma confinement and materials science."
}

SAMPLE_REPORT = "# Nuclear Fusion\n\n## Executive Summary\n\nFusion is promising."


# ── save_report() tests ───────────────────────────────────────────────────────

def test_save_report_creates_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from main import save_report
    path = save_report("nuclear fusion", "# Report content")
    assert os.path.exists(path)


def test_save_report_contains_topic_heading(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from main import save_report
    path = save_report("nuclear fusion", "# Report content")
    with open(path) as f:
        content = f.read()
    assert "# nuclear fusion" in content.lower()


def test_save_report_contains_report_body(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from main import save_report
    path = save_report("nuclear fusion", "# Report content")
    with open(path) as f:
        content = f.read()
    assert "# Report content" in content


def test_save_report_sanitises_filename(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from main import save_report
    path = save_report("nuclear fusion: a review!", "# Report")
    assert ":" not in path
    assert "!" not in path


def test_save_report_truncates_long_topic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from main import save_report
    long_topic = "a " * 60
    path = save_report(long_topic, "# Report")
    filename = os.path.basename(path)
    assert len(filename) <= 60  # 50 chars + .md


def test_save_report_returns_path_string(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from main import save_report
    path = save_report("nuclear fusion", "# Report")
    assert isinstance(path, str)
    assert path.endswith(".md")


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

    mock_orchestrator.run.return_value = (SAMPLE_RESULTS, {})
    mock_synthesiser.synthesise.return_value = SAMPLE_REPORT

    with patch("sys.argv", ["main.py", "nuclear fusion"]), \
         patch("main.AnthropicClient", return_value=mock_llm), \
         patch("main.Orchestrator", return_value=mock_orchestrator), \
         patch("main.Synthesiser", return_value=mock_synthesiser):
        from main import main
        main()

    mock_orchestrator.run.assert_called_once_with("nuclear fusion")
    mock_synthesiser.synthesise.assert_called_once_with("nuclear fusion", SAMPLE_RESULTS, sources={}
)


def test_main_saves_report_to_output(tmp_path, monkeypatch):
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

    output_files = os.listdir(tmp_path / "output")
    assert len(output_files) == 1
    assert output_files[0].endswith(".md")


# ── build_llm() tests ─────────────────────────────────────────────────────────

def test_build_llms_returns_two_anthropic_clients():
    from main import build_llms
    from config import Config
    with patch("main.AnthropicClient") as mock:
        orch, synth = build_llms(Config(provider="anthropic"))
        assert mock.call_count == 2


def test_build_llms_returns_two_ollama_clients():
    from main import build_llms
    from config import Config
    with patch("main.OllamaClient") as mock:
        orch, synth = build_llms(Config(provider="ollama"))
        assert mock.call_count == 2


def test_build_llms_anthropic_uses_different_models_by_default():
    from main import build_llms
    from config import Config
    with patch("main.AnthropicClient") as mock:
        build_llms(Config(provider="anthropic"))
        calls = [c.kwargs.get("model") or c.args[0] if c.args else c.kwargs.get("model")
                 for c in mock.call_args_list]
        models = [mock.call_args_list[0][1].get("model"),
                  mock.call_args_list[1][1].get("model")]
        assert models[0] != models[1]


def test_build_llms_model_override_applies_to_both():
    from main import build_llms
    from config import Config
    with patch("main.AnthropicClient") as mock:
        build_llms(Config(provider="anthropic", model="claude-sonnet-4-6"))
        for call in mock.call_args_list:
            assert call[1].get("model") == "claude-sonnet-4-6"


def test_build_llms_unknown_provider_exits():
    from main import build_llms
    from config import Config
    with pytest.raises(SystemExit):
        build_llms(Config(provider="unknown_provider"))

# ── Integration tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
def test_real_full_pipeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with patch("sys.argv", ["main.py", "the current state of nuclear fusion energy"]):
        from main import main
        main()

    output_files = os.listdir(tmp_path / "output")
    assert len(output_files) == 1

    with open(tmp_path / "output" / output_files[0]) as f:
        content = f.read()

    assert len(content) > 1000
    assert "#" in content
    
    