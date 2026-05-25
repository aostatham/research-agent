"""
Agent factory functions for the multi-agent research pipeline.

Mirrors the pattern of llm/builder.py: main.py calls build_agents() at
startup and passes the resulting AgentPool into the Orchestrator.

System prompts are loaded from the prompts/ directory at build time
and stored immutably on each Agent instance.

See DECISIONS.md D004, D011, D012 for design rationale.
"""

from pathlib import Path
from typing import Optional, Union

from agent.base import Agent, AgentPool
from llm.base import LLMClient
from llm.builder import build_client


def build_agent(
    name: str,
    role: str,
    description: str,
    llm: LLMClient,
    prompt_dir: Union[str, Path],
    tools: tuple = (),
    temperature: Optional[float] = None,
    max_iterations: int = 5,
) -> Agent:
    """
    Construct a single Agent, loading its system prompt from prompt_dir/{name}.md.

    Args:
        name:          Agent identifier — must match a .md file in prompt_dir.
        role:          Human-readable description of the agent's purpose.
        description:   Used for future dynamic handoff routing.
        llm:           LLMClient instance to assign to this agent.
        prompt_dir:    Directory containing system prompt .md files.
        tools:         Immutable tuple of tool names available to this agent.
        temperature:   Optional sampling temperature override.
        max_iterations: Per-agent loop budget.

    Returns:
        Constructed Agent with system_prompt loaded from disk.

    Raises:
        FileNotFoundError: If prompt_dir/{name}.md does not exist.
    """
    path = Path(prompt_dir) / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"System prompt not found: {path}")
    system_prompt = path.read_text()
    return Agent(
        name=name,
        role=role,
        description=description,
        llm=llm,
        system_prompt=system_prompt,
        tools=tools,
        temperature=temperature,
        max_iterations=max_iterations,
    )


def build_agents(
    config,
    orch_llm: LLMClient,
    synth_llm: LLMClient,
    prompt_dir: Union[str, Path, None] = None,
) -> AgentPool:
    """
    Build all four pipeline agents and return them as a frozen AgentPool.

    Agent LLM assignments:
      Planner   — orch_llm (no tools)
      Researcher — orch_llm + web_search, max_iterations from config
      Verifier  — synth_llm + web_search
      Editor    — synth_llm by default; separate client if config.editor_provider set

    Editor model resolution (D012):
      editor_provider = config.editor_provider (if set) else synth_provider
      editor_model    = config.anthropic_editor_model or synth_model (anthropic)
                      = config.ollama_editor_model   or synth_model (ollama)

    Args:
        config:     Config instance (may or may not have editor_provider fields).
        orch_llm:   Pre-built orchestration LLM client.
        synth_llm:  Pre-built synthesis LLM client.
        prompt_dir: Directory containing .md prompt files (default: Path("prompts")).

    Returns:
        Frozen AgentPool with planner, researcher, verifier, editor.
    """
    if prompt_dir is None:
        prompt_dir = Path("prompts")

    editor_llm = _resolve_editor_llm(config, synth_llm)

    planner = build_agent(
        name="planner",
        role="Research planner",
        description="Decomposes a research topic into focused, independently researchable sub-questions",
        llm=orch_llm,
        prompt_dir=prompt_dir,
    )
    researcher = build_agent(
        name="researcher",
        role="Research agent",
        description="Answers a single sub-question using web search and synthesises the findings",
        llm=orch_llm,
        prompt_dir=prompt_dir,
        tools=("web_search",),
        max_iterations=config.max_iterations,
    )
    verifier = build_agent(
        name="verifier",
        role="Research verifier",
        description="Checks specific claims from researcher answers against web sources",
        llm=synth_llm,
        prompt_dir=prompt_dir,
        tools=("web_search",),
    )
    editor = build_agent(
        name="editor",
        role="Research editor",
        description="Reviews synthesised reports for coherence defects only — no substantive changes",
        llm=editor_llm,
        prompt_dir=prompt_dir,
    )

    return AgentPool(planner=planner, researcher=researcher, verifier=verifier, editor=editor)


def _resolve_editor_llm(config, synth_llm: LLMClient) -> LLMClient:
    """
    Resolve the LLM client to use for the Editor agent.

    Returns synth_llm unless config.editor_provider is explicitly set,
    in which case a new client is built for that provider and model.
    """
    if not config.editor_provider:
        return synth_llm

    if config.editor_provider == "anthropic":
        editor_model = config.anthropic_editor_model or config.anthropic_synthesis_model
    else:
        editor_model = config.ollama_editor_model or config.ollama_synthesis_model

    return build_client(config.editor_provider, editor_model, config)
