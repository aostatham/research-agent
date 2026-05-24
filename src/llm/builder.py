"""
LLM client factory for the research-agent pipeline.

Constructs AnthropicClient or OllamaClient instances from a Config object.
Supports mixed providers — orchestration and synthesis can use different
backends. Resolution order for each tier:
  1. orchestration_provider / synthesis_provider (explicit tier override)
  2. provider (applies to both tiers)
  3. Hardcoded defaults in the Config dataclass
"""

from .anthropic_client import AnthropicClient
from .base import LLMClient
from .ollama_client import OllamaClient


def build_client(provider: str, model: str, config) -> LLMClient:
    """
    Build a single LLM client for a given provider and model.

    Args:
        provider: "anthropic" or "ollama"
        model:    Model name string
        config:   Config dataclass instance (used for ollama_base_url)

    Returns:
        Instantiated LLMClient subclass
    """
    if provider == "anthropic":
        return AnthropicClient(model=model)
    elif provider == "ollama":
        return OllamaClient(model=model, base_url=config.ollama_base_url)
    else:
        raise ValueError(
            f"Unknown provider: {provider!r}. Choose 'anthropic' or 'ollama'."
        )


def build_llms(config):
    """
    Build orchestration and synthesis LLM clients from config.

    Supports mixed providers — orchestration and synthesis can use different
    backends. Resolution order:
      1. orchestration_provider / synthesis_provider (explicit tier override)
      2. provider (applies to both tiers)
      3. Hardcoded defaults in Config dataclass

    Returns:
        Tuple of (orch_llm, synth_llm, orch_provider, orch_model,
                  synth_provider, synth_model)
    """
    # Resolve orchestration provider and model
    orch_provider = config.orchestration_provider or config.provider
    if orch_provider == "anthropic":
        orch_model = config.model or config.anthropic_orchestration_model
    else:
        orch_model = config.model or config.ollama_orchestration_model

    # Resolve synthesis provider and model
    synth_provider = config.synthesis_provider or config.provider
    if synth_provider == "anthropic":
        synth_model = config.model or config.anthropic_synthesis_model
    else:
        synth_model = config.model or config.ollama_synthesis_model

    orch_llm = build_client(orch_provider, orch_model, config)
    synth_llm = build_client(synth_provider, synth_model, config)

    return orch_llm, synth_llm, orch_provider, orch_model, synth_provider, synth_model
