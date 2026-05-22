"""
Tests for config/settings.py — Config dataclass and load_config().

Verifies:
    - Config dataclass default values for all fields.
    - load_config() applies the three-layer hierarchy correctly:
        Layer 1 (defaults) < Layer 2 (config.yaml) < Layer 3 (CLI overrides).
    - None overrides do not clobber file-based values.
    - Unknown keys in config.yaml are silently ignored.
    - Empty and missing config files fall back to defaults.
    - Custom config file paths work correctly.
    - Model and mixed-provider fields are configurable independently.
"""

import pytest
import os
import yaml
from config.settings import Config, load_config


# ── Config dataclass defaults ─────────────────────────────────────────────────
# Confirm that a bare Config() has the expected out-of-the-box values.

def test_default_provider():
    config = Config()
    assert config.provider == "anthropic"


def test_default_min_questions():
    config = Config()
    assert config.min_questions == 4


def test_default_max_questions():
    config = Config()
    assert config.max_questions == 5


def test_default_max_iterations():
    config = Config()
    assert config.max_iterations == 5


def test_default_max_tokens_research():
    config = Config()
    assert config.max_tokens_research == 2048


def test_default_max_tokens_synthesis():
    config = Config()
    assert config.max_tokens_synthesis == 8192


# ── load_config() — no file ───────────────────────────────────────────────────
# When config.yaml does not exist, load_config() should return pure defaults.

def test_load_config_returns_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = load_config("config.yaml")
    assert config.provider == "anthropic"
    assert config.max_questions == 5


# ── load_config() — from file ─────────────────────────────────────────────────
# File values override dataclass defaults (Layer 2 > Layer 1).

def test_load_config_reads_provider_from_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_data = {"provider": "ollama"}
    with open(tmp_path / "config.yaml", "w") as f:
        yaml.dump(config_data, f)
    config = load_config("config.yaml")
    assert config.provider == "ollama"


def test_load_config_reads_question_counts_from_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_data = {"min_questions": 3, "max_questions": 7}
    with open(tmp_path / "config.yaml", "w") as f:
        yaml.dump(config_data, f)
    config = load_config("config.yaml")
    assert config.min_questions == 3
    assert config.max_questions == 7


def test_load_config_ignores_unknown_keys(tmp_path, monkeypatch):
    """Unknown keys in config.yaml must be silently dropped, not set as attributes."""
    monkeypatch.chdir(tmp_path)
    config_data = {"unknown_key": "some_value", "provider": "ollama"}
    with open(tmp_path / "config.yaml", "w") as f:
        yaml.dump(config_data, f)
    config = load_config("config.yaml")
    assert config.provider == "ollama"
    assert not hasattr(config, "unknown_key")


def test_load_config_handles_empty_file(tmp_path, monkeypatch):
    """An empty config.yaml is equivalent to no file — defaults apply."""
    monkeypatch.chdir(tmp_path)
    with open(tmp_path / "config.yaml", "w") as f:
        f.write("")
    config = load_config("config.yaml")
    assert config.provider == "anthropic"


# ── load_config() — CLI overrides ─────────────────────────────────────────────
# CLI overrides are Layer 3 and win over both defaults and file values.

def test_cli_override_takes_precedence_over_file(tmp_path, monkeypatch):
    """CLI override beats config.yaml value."""
    monkeypatch.chdir(tmp_path)
    config_data = {"provider": "ollama"}
    with open(tmp_path / "config.yaml", "w") as f:
        yaml.dump(config_data, f)
    config = load_config("config.yaml", overrides={"provider": "anthropic"})
    assert config.provider == "anthropic"


def test_none_override_does_not_overwrite_file_value(tmp_path, monkeypatch):
    """A None override (argparse 'not provided') must not clobber a file value."""
    monkeypatch.chdir(tmp_path)
    config_data = {"max_questions": 7}
    with open(tmp_path / "config.yaml", "w") as f:
        yaml.dump(config_data, f)
    config = load_config("config.yaml", overrides={"max_questions": None})
    assert config.max_questions == 7


def test_cli_override_takes_precedence_over_defaults(tmp_path, monkeypatch):
    """CLI override beats the dataclass default even without a config file."""
    monkeypatch.chdir(tmp_path)
    config = load_config("config.yaml", overrides={"max_questions": 10})
    assert config.max_questions == 10


def test_all_three_layers_in_correct_priority(tmp_path, monkeypatch):
    """Full three-layer scenario: CLI > file > default."""
    monkeypatch.chdir(tmp_path)
    # File sets max_questions=7, CLI overrides to 10
    config_data = {"max_questions": 7, "min_questions": 3}
    with open(tmp_path / "config.yaml", "w") as f:
        yaml.dump(config_data, f)
    config = load_config("config.yaml", overrides={"max_questions": 10})
    assert config.max_questions == 10   # CLI wins
    assert config.min_questions == 3    # file wins over default
    assert config.provider == "anthropic"  # default used (absent from file and CLI)


# ── Custom config path ────────────────────────────────────────────────────────

def test_custom_config_path(tmp_path):
    """load_config() accepts an arbitrary file path, not just 'config.yaml'."""
    custom_path = tmp_path / "custom_config.yaml"
    config_data = {"provider": "ollama", "max_questions": 8}
    with open(custom_path, "w") as f:
        yaml.dump(config_data, f)
    config = load_config(str(custom_path))
    assert config.provider == "ollama"
    assert config.max_questions == 8


# ── model configuration ────────────────────────────────────────────────────────
# Verify model tiering defaults and per-tier configurability.

def test_default_anthropic_orchestration_model():
    config = Config()
    assert config.anthropic_orchestration_model == "claude-haiku-4-5-20251001"


def test_default_anthropic_synthesis_model():
    config = Config()
    assert config.anthropic_synthesis_model == "claude-sonnet-4-6"


def test_default_ollama_models_are_same():
    """Ollama defaults both tiers to the same model (no quality tiering for local models)."""
    config = Config()
    assert config.ollama_orchestration_model == config.ollama_synthesis_model


def test_ollama_models_configurable_independently(tmp_path, monkeypatch):
    """Each Ollama model tier can be set to a different value via config.yaml."""
    monkeypatch.chdir(tmp_path)
    config_data = {
        "ollama_orchestration_model": "llama3.1",
        "ollama_synthesis_model": "llama3.2"
    }
    with open(tmp_path / "config.yaml", "w") as f:
        yaml.dump(config_data, f)
    config = load_config("config.yaml")
    assert config.ollama_orchestration_model == "llama3.1"
    assert config.ollama_synthesis_model == "llama3.2"


# ── Mixed provider support ────────────────────────────────────────────────────

def test_default_orchestration_provider_is_none():
    """Per-tier provider is None by default (falls back to global provider)."""
    config = Config()
    assert config.orchestration_provider is None


def test_default_synthesis_provider_is_none():
    """Per-tier synthesis provider is None by default."""
    config = Config()
    assert config.synthesis_provider is None


def test_orchestration_provider_configurable(tmp_path, monkeypatch):
    """Mixed-provider config can set orchestration and synthesis to different providers."""
    monkeypatch.chdir(tmp_path)
    config_data = {"orchestration_provider": "ollama", "synthesis_provider": "anthropic"}
    with open(tmp_path / "config.yaml", "w") as f:
        yaml.dump(config_data, f)
    config = load_config("config.yaml")
    assert config.orchestration_provider == "ollama"
    assert config.synthesis_provider == "anthropic"
