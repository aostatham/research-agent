"""
Configuration management for the research agent.

Defines the Config dataclass (all tuneable knobs with hardcoded defaults) and
load_config(), which builds a Config through a three-layer hierarchy:

    Layer 1 — Config dataclass defaults  (lowest priority)
    Layer 2 — config.yaml values
    Layer 3 — CLI overrides              (highest priority)

None values in overrides are ignored, so argparse defaults do not silently
overwrite file-based config.

The TAVILY_API_KEY is handled separately: if not set in config.yaml or via a
CLI override, it falls back to the TAVILY_API_KEY environment variable.
"""

import os
import yaml
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    """
    All configuration knobs for the research agent.

    Fields are grouped by concern: provider selection, model tiering, search
    provider, research behaviour, token limits, and retry parameters.  Defaults
    represent a reasonable out-of-the-box Anthropic run.
    """

    # ── Provider selection ────────────────────────────────────────────────────

    # Base provider for both tiers if no per-tier override is set.
    provider: str = "anthropic"

    # Global model override — if set, applies to both orchestration and
    # synthesis regardless of provider-specific model fields.
    model: Optional[str] = None

    # ── Mixed provider support ────────────────────────────────────────────────

    # Per-tier provider overrides; take precedence over `provider` for their tier.
    orchestration_provider: Optional[str] = None
    synthesis_provider: Optional[str] = None

    # ── Anthropic model tiering ───────────────────────────────────────────────

    # Haiku for orchestration (fast, cheap); Sonnet for synthesis (higher quality).
    anthropic_orchestration_model: str = "claude-haiku-4-5-20251001"
    anthropic_synthesis_model: str = "claude-sonnet-4-6"

    # ── Ollama model tiering ──────────────────────────────────────────────────

    # Both tiers default to the same model; can be split via config.yaml.
    ollama_orchestration_model: str = "llama3.1"
    ollama_synthesis_model: str = "llama3.1"
    ollama_base_url: str = "http://localhost:11434"

    # ── Search provider ───────────────────────────────────────────────────────

    # "anthropic" uses Anthropic's built-in web_search_20250305 ($0.01/search).
    # "tavily" uses the Tavily API (1,000 free searches/month).
    search_provider: str = "anthropic"  # anthropic | tavily
    tavily_api_key: Optional[str] = None   # loaded from env if not in config
    tavily_max_results: int = 5

    # ── Research behaviour ────────────────────────────────────────────────────

    min_questions: int = 4    # minimum sub-questions generated per topic
    max_questions: int = 5    # hard cap; LLM output sliced to this length
    max_iterations: int = 5   # agentic loop cap per question

    # ── Token limits ──────────────────────────────────────────────────────────

    max_tokens_research: int = 2048   # per-question calls
    max_tokens_synthesis: int = 8192  # final synthesis call needs more room

    # ── Retry behaviour ───────────────────────────────────────────────────────

    retry_max_attempts: int = 3
    retry_base_delay: float = 1.0   # seconds before first retry
    retry_max_delay: float = 30.0   # cap on inter-retry delay

    # ── Source classification ─────────────────────────────────────────────────

    # User-extensible domain overrides for classify_source_type().
    # Add custom domains here rather than modifying the hardcoded list.
    # Format: {"academic": ["mycustomjournal.org"], "government": ["specialagency.int"]}
    # Trigger: domain misclassified in 3+ real research runs.
    source_classification: dict = None

    # ── Output mode ───────────────────────────────────────────────────────────

    # report (default): full narrative report
    # report-evidence, data, dashboard, slides, matrix, academic,
    # bibliography, raw: non-report modes stubbed for Phase C+
    output_mode: str = "report"

    # ── Provenance ────────────────────────────────────────────────────────────

    # none: no provenance output (default)
    # file: write .provenance.json alongside the report
    # graph: Phase E placeholder — not yet implemented
    provenance: str = "none"


def load_config(config_path: str = "config.yaml", overrides: dict = None) -> Config:
    """
    Build a Config instance using the three-layer hierarchy.

    Layers applied in order (later layers win):
      1. Config dataclass defaults
      2. config.yaml key/value pairs (skipped if file does not exist)
      3. CLI overrides dict (None values are skipped to preserve lower-layer values)

    After all layers, the Tavily API key falls back to the TAVILY_API_KEY
    environment variable if it was not set by config or CLI.

    Args:
        config_path: Path to the YAML config file.  Relative paths are
                     resolved from the current working directory.
        overrides:   Dict of field-name → value pairs from the CLI.  Keys that
                     don't exist on Config are silently ignored.  None values
                     are skipped so argparse "not provided" defaults don't
                     overwrite file-based config.

    Returns:
        A fully resolved Config instance.
    """
    config = Config()

    # Layer 1 — apply config.yaml if it exists
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            data = yaml.safe_load(f) or {}  # safe_load returns None for an empty file
        for key, value in data.items():
            if hasattr(config, key) and value is not None:
                setattr(config, key, value)

    # Layer 2 — apply CLI overrides; skip None so absent flags don't clobber file values
    if overrides:
        for key, value in overrides.items():
            if value is not None and hasattr(config, key):
                setattr(config, key, value)

    # Layer 3 — fall back to environment variable for Tavily key
    # Allows `export TAVILY_API_KEY=...` without touching config.yaml
    if not config.tavily_api_key:
        config.tavily_api_key = os.getenv("TAVILY_API_KEY")

    return config
