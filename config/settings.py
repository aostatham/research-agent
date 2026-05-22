import os
import yaml
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    # Provider
    provider: str = "anthropic"
    model: Optional[str] = None  # single override — overrides both tiers if set

    # Anthropic model tiering
    anthropic_orchestration_model: str = "claude-haiku-4-5-20251001"
    anthropic_synthesis_model: str = "claude-sonnet-4-6"

    # Ollama model tiering
    ollama_orchestration_model: str = "llama3.1"
    ollama_synthesis_model: str = "llama3.1"
    ollama_base_url: str = "http://localhost:11434"

    # Research behaviour
    min_questions: int = 4
    max_questions: int = 5
    max_iterations: int = 5

    # Token limits
    max_tokens_research: int = 2048
    max_tokens_synthesis: int = 8192

    # Retry behaviour
    retry_max_attempts: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0


def load_config(config_path: str = "config.yaml", overrides: dict = None) -> Config:
    """
    Build config using three-layer hierarchy:
      1. Hardcoded dataclass defaults
      2. config.yaml values
      3. CLI overrides (only applied if not None)
    """
    config = Config()

    # Layer 1 — apply config.yaml if it exists
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            data = yaml.safe_load(f) or {}
        for key, value in data.items():
            if hasattr(config, key) and value is not None:
                setattr(config, key, value)

    # Layer 2 — apply CLI overrides
    if overrides:
        for key, value in overrides.items():
            if value is not None and hasattr(config, key):
                setattr(config, key, value)

    return config