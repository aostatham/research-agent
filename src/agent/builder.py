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
    system_prompt = path.read_text(encoding="utf-8")
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
    Build the three pipeline agents and return them as a frozen AgentPool.

    Agent LLM assignments:
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
        Frozen AgentPool with researcher, verifier, editor.
    """
    if prompt_dir is None:
        prompt_dir = Path("prompts")

    editor_llm = _resolve_editor_llm(config, synth_llm)

    # kg_ read tools are available to Researcher and Verifier when the knowledge
    # graph is configured. kg_write_claim is Analyst-only — not added here.
    kg_tools: tuple = ()
    if getattr(config, "knowledge_store", "none") != "none":
        kg_tools = (
            "kg_query_claims_for_topic",
            "kg_check_contradiction",
            "kg_get_related_topics",
        )

    researcher = build_agent(
        name="researcher",
        role="Research agent",
        description="Answers a single sub-question using web search and synthesises the findings",
        llm=orch_llm,
        prompt_dir=prompt_dir,
        tools=("web_search",) + kg_tools,
        max_iterations=config.max_iterations,
    )
    verifier = build_agent(
        name="verifier",
        role="Research verifier",
        description="Checks specific claims from researcher answers against web sources",
        llm=synth_llm,
        prompt_dir=prompt_dir,
        tools=("web_search",) + kg_tools,
        max_iterations=config.verifier_max_iterations,
    )
    editor = build_agent(
        name="editor",
        role="Research editor",
        description="Reviews synthesised reports for coherence defects only — no substantive changes",
        llm=editor_llm,
        prompt_dir=prompt_dir,
    )

    # Planner Agent deferred to Phase E (D015). When implemented,
    # decompose() will be redesigned with a reconciled prompt and parser.

    # Graph Verifier — populated when knowledge store is configured (D039).
    graph_verifier_agent = None
    if getattr(config, "knowledge_store", "none") != "none":
        graph_verifier_agent = build_graph_verifier(config, synth_llm,
                                                    prompt_dir=prompt_dir)

    # Analyst Agent — populated when knowledge store is configured (D043).
    analyst_agent = None
    if getattr(config, "knowledge_store", "none") != "none":
        analyst_agent = build_analyst(config, synth_llm, prompt_dir=prompt_dir)

    return AgentPool(
        researcher=researcher,
        verifier=verifier,
        editor=editor,
        graph_verifier=graph_verifier_agent,
        analyst=analyst_agent,
    )


def build_graph_verifier(
    config,
    synth_llm: LLMClient,
    prompt_dir: Union[str, Path, None] = None,
) -> "Agent":
    """
    Build the Graph Verifier agent.

    Loads prompts/graph_verifier.md. The Graph Verifier uses synth_llm and
    has access to the three kg_ read tools. It is only built when the knowledge
    store is configured — callers must check before calling.

    Args:
        config:     Config instance (unused directly; reserved for future tuning).
        synth_llm:  Pre-built synthesis LLM client.
        prompt_dir: Directory containing .md prompt files (default: Path("prompts")).

    Returns:
        Agent configured for graph verification.

    Raises:
        FileNotFoundError: If prompts/graph_verifier.md does not exist.
    """
    if prompt_dir is None:
        prompt_dir = Path("prompts")
    return build_agent(
        name="graph_verifier",
        role="Graph Verifier — checks claims against knowledge graph",
        description="Verifies claims against prior-run graph evidence before web verification",
        llm=synth_llm,
        prompt_dir=prompt_dir,
        tools=("kg_check_contradiction", "kg_query_claims_for_topic",
               "kg_get_related_topics"),
        max_iterations=4,
    )


def build_analyst(
    config,
    synth_llm: LLMClient,
    prompt_dir: Union[str, Path, None] = None,
) -> "Agent":
    """
    Build the Analyst agent.

    Loads prompts/tasks/analyst.md. The Analyst uses synth_llm and has access
    to kg_query_claims_for_topic and kg_write_claim tools. It is only built
    when the knowledge store is configured — callers must check before calling.

    Args:
        config:     Config instance (reserved for future tuning).
        synth_llm:  Pre-built synthesis LLM client.
        prompt_dir: Base prompts directory (default: Path("prompts")).

    Returns:
        Agent configured for evidence-informed report quality recommendations.

    Raises:
        FileNotFoundError: If prompts/tasks/analyst.md does not exist.
    """
    task_dir = Path(prompt_dir or "prompts") / "tasks"
    return build_agent(
        name="analyst",
        role="Analyst — evidence-informed report quality recommendations",
        description="Reviews report claims against provenance metadata for quality recommendations",
        llm=synth_llm,
        prompt_dir=task_dir,
        tools=("kg_query_claims_for_topic", "kg_write_claim"),
        max_iterations=2,
    )


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
