"""
Tests for agent/builder.py — build_agent() and build_agents().

Verifies:
  - build_agent() loads system prompt from prompt_dir/{name}.md
  - build_agent() raises FileNotFoundError with correct message when prompt missing
  - build_agents() returns AgentPool with three agents (no planner — D015)
  - build_agents() assigns correct llm per agent
  - Editor inherits synth_llm when config.editor_provider is not set
  - Editor uses a separately constructed LLM when config.editor_provider is set

All LLM construction is mocked — no real API calls.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from agent.builder import build_agent, build_agents
from agent.base import Agent, AgentPool
from llm.base import LLMResponse


def make_mock_llm():
    mock = MagicMock()
    mock.chat.return_value = LLMResponse(type="text", content="ok")
    return mock


def make_config(editor_provider=None, anthropic_editor_model=None,
                ollama_editor_model=None, knowledge_store="none"):
    """Build a minimal mock Config object."""
    cfg = MagicMock()
    cfg.max_iterations = 5
    cfg.provider = "anthropic"
    cfg.synthesis_provider = None
    cfg.orchestration_provider = None
    cfg.anthropic_synthesis_model = "claude-sonnet-4-6"
    cfg.ollama_synthesis_model = "llama3.1"
    cfg.editor_provider = editor_provider
    cfg.anthropic_editor_model = anthropic_editor_model
    cfg.ollama_editor_model = ollama_editor_model
    cfg.ollama_base_url = "http://localhost:11434"
    # Set explicitly: MagicMock auto-generates truthy attributes, which would
    # make knowledge_store != "none" evaluate to True for all mock configs.
    cfg.knowledge_store = knowledge_store
    return cfg


# ── build_agent() ─────────────────────────────────────────────────────────────

def test_build_agent_loads_prompt_from_file(tmp_path):
    """build_agent() reads the system prompt from prompt_dir/{name}.md."""
    (tmp_path / "myagent.md").write_text("Be helpful.")
    llm = make_mock_llm()
    agent = build_agent("myagent", "role", "desc", llm, tmp_path)
    assert agent.system_prompt == "Be helpful."


def test_build_agent_returns_agent_instance(tmp_path):
    (tmp_path / "myagent.md").write_text("prompt")
    agent = build_agent("myagent", "role", "desc", make_mock_llm(), tmp_path)
    assert isinstance(agent, Agent)


def test_build_agent_sets_name(tmp_path):
    (tmp_path / "myagent.md").write_text("prompt")
    agent = build_agent("myagent", "role", "desc", make_mock_llm(), tmp_path)
    assert agent.name == "myagent"


def test_build_agent_sets_tools(tmp_path):
    (tmp_path / "myagent.md").write_text("prompt")
    agent = build_agent("myagent", "role", "desc", make_mock_llm(), tmp_path, tools=("web_search",))
    assert agent.tools == ("web_search",)


def test_build_agent_sets_max_iterations(tmp_path):
    (tmp_path / "myagent.md").write_text("prompt")
    agent = build_agent("myagent", "role", "desc", make_mock_llm(), tmp_path, max_iterations=7)
    assert agent.max_iterations == 7


def test_build_agent_raises_file_not_found_when_prompt_missing(tmp_path):
    """Missing prompt file raises FileNotFoundError with the exact path in the message."""
    with pytest.raises(FileNotFoundError) as exc_info:
        build_agent("missing", "role", "desc", make_mock_llm(), tmp_path)
    expected_path = str(tmp_path / "missing.md")
    assert f"System prompt not found: {expected_path}" in str(exc_info.value)


def test_build_agent_prompt_path_uses_name_and_dir(tmp_path):
    """Prompt is loaded from exactly prompt_dir/{name}.md."""
    (tmp_path / "special.md").write_text("special prompt")
    agent = build_agent("special", "r", "d", make_mock_llm(), tmp_path)
    assert agent.system_prompt == "special prompt"


def test_build_agent_reads_prompt_with_utf8_encoding(tmp_path):
    """build_agent() reads prompt file with encoding='utf-8'."""
    prompt_file = tmp_path / "myagent.md"
    prompt_file.write_text("Be helpful.", encoding="utf-8")
    with patch("agent.builder.Path") as mock_path_cls:
        mock_path_inst = MagicMock()
        mock_path_inst.exists.return_value = True
        mock_path_inst.read_text.return_value = "Be helpful."
        mock_path_cls.return_value.__truediv__ = lambda self, other: mock_path_inst
        build_agent("myagent", "role", "desc", make_mock_llm(), tmp_path)
        mock_path_inst.read_text.assert_called_once_with(encoding="utf-8")


# ── build_agents() ────────────────────────────────────────────────────────────

def _make_prompt_dir(tmp_path):
    """Write the prompt files needed by build_agents()."""
    for name in ("researcher", "verifier", "editor", "graph_verifier"):
        (tmp_path / f"{name}.md").write_text(f"{name} prompt")
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "analyst.md").write_text("analyst prompt")
    return tmp_path


def test_build_agents_returns_agentpool(tmp_path):
    cfg = make_config()
    pool = build_agents(cfg, make_mock_llm(), make_mock_llm(), prompt_dir=_make_prompt_dir(tmp_path))
    assert isinstance(pool, AgentPool)


def test_build_agents_has_no_planner(tmp_path):
    """build_agents() does not build a planner agent — planner deferred to Phase E (D015)."""
    pool = build_agents(make_config(), make_mock_llm(), make_mock_llm(), prompt_dir=_make_prompt_dir(tmp_path))
    assert not hasattr(pool, "planner")


def test_build_agents_researcher_uses_orch_llm(tmp_path):
    orch_llm = make_mock_llm()
    synth_llm = make_mock_llm()
    pool = build_agents(make_config(), orch_llm, synth_llm, prompt_dir=_make_prompt_dir(tmp_path))
    assert pool.researcher.llm is orch_llm


def test_build_agents_verifier_uses_synth_llm(tmp_path):
    orch_llm = make_mock_llm()
    synth_llm = make_mock_llm()
    pool = build_agents(make_config(), orch_llm, synth_llm, prompt_dir=_make_prompt_dir(tmp_path))
    assert pool.verifier.llm is synth_llm


def test_build_agents_researcher_has_web_search_tool(tmp_path):
    pool = build_agents(make_config(), make_mock_llm(), make_mock_llm(), prompt_dir=_make_prompt_dir(tmp_path))
    assert "web_search" in pool.researcher.tools


def test_build_agents_verifier_has_web_search_tool(tmp_path):
    pool = build_agents(make_config(), make_mock_llm(), make_mock_llm(), prompt_dir=_make_prompt_dir(tmp_path))
    assert "web_search" in pool.verifier.tools


def test_build_agents_editor_has_no_tools(tmp_path):
    pool = build_agents(make_config(), make_mock_llm(), make_mock_llm(), prompt_dir=_make_prompt_dir(tmp_path))
    assert pool.editor.tools == ()


def test_build_agents_researcher_max_iterations_from_config(tmp_path):
    cfg = make_config()
    cfg.max_iterations = 7
    pool = build_agents(cfg, make_mock_llm(), make_mock_llm(), prompt_dir=_make_prompt_dir(tmp_path))
    assert pool.researcher.max_iterations == 7


def test_build_agents_verifier_max_iterations_from_config(tmp_path):
    """Verifier max_iterations comes from config.verifier_max_iterations."""
    cfg = make_config()
    cfg.verifier_max_iterations = 6
    pool = build_agents(cfg, make_mock_llm(), make_mock_llm(), prompt_dir=_make_prompt_dir(tmp_path))
    assert pool.verifier.max_iterations == 6


def test_build_agents_editor_inherits_synth_llm_when_no_editor_provider(tmp_path):
    """When editor_provider is not configured, editor uses synth_llm directly."""
    synth_llm = make_mock_llm()
    pool = build_agents(make_config(editor_provider=None), make_mock_llm(), synth_llm,
                        prompt_dir=_make_prompt_dir(tmp_path))
    assert pool.editor.llm is synth_llm


def test_build_agents_editor_uses_separate_llm_when_editor_provider_set(tmp_path):
    """When editor_provider is set, a new LLM client is built for the editor."""
    synth_llm = make_mock_llm()
    separate_llm = make_mock_llm()
    cfg = make_config(editor_provider="anthropic", anthropic_editor_model="claude-haiku-4-5-20251001")

    with patch("agent.builder.build_client", return_value=separate_llm) as mock_build:
        pool = build_agents(cfg, make_mock_llm(), synth_llm, prompt_dir=_make_prompt_dir(tmp_path))

    assert pool.editor.llm is separate_llm
    assert pool.editor.llm is not synth_llm
    mock_build.assert_called_once_with("anthropic", "claude-haiku-4-5-20251001", cfg)


def test_build_agents_editor_uses_anthropic_editor_model_when_set(tmp_path):
    """Editor uses anthropic_editor_model rather than synthesis model when explicitly configured."""
    cfg = make_config(editor_provider="anthropic", anthropic_editor_model="claude-haiku-4-5-20251001")
    with patch("agent.builder.build_client") as mock_build:
        mock_build.return_value = make_mock_llm()
        build_agents(cfg, make_mock_llm(), make_mock_llm(), prompt_dir=_make_prompt_dir(tmp_path))
    mock_build.assert_called_once_with("anthropic", "claude-haiku-4-5-20251001", cfg)


def test_build_agents_prompts_loaded_correctly(tmp_path):
    """Each agent's system_prompt matches its respective prompt file."""
    pool = build_agents(make_config(), make_mock_llm(), make_mock_llm(), prompt_dir=_make_prompt_dir(tmp_path))
    assert pool.researcher.system_prompt == "researcher prompt"
    assert pool.verifier.system_prompt == "verifier prompt"
    assert pool.editor.system_prompt == "editor prompt"


def test_build_agents_graph_verifier_populated_when_knowledge_store_kuzu(tmp_path):
    """build_agents() sets graph_verifier when knowledge_store is 'kuzu'."""
    cfg = make_config(knowledge_store="kuzu")
    pool = build_agents(cfg, make_mock_llm(), make_mock_llm(), prompt_dir=_make_prompt_dir(tmp_path))
    assert pool.graph_verifier is not None


def test_build_agents_graph_verifier_none_when_knowledge_store_none(tmp_path):
    """build_agents() leaves graph_verifier as None when knowledge_store is 'none'."""
    pool = build_agents(make_config(knowledge_store="none"), make_mock_llm(), make_mock_llm(),
                        prompt_dir=_make_prompt_dir(tmp_path))
    assert pool.graph_verifier is None


def test_build_agent_populates_tool_descriptors(tmp_path):
    """build_agent() sets tool_descriptors to the pre-built descriptor list."""
    from agent.tools import WEB_SEARCH_TOOL
    (tmp_path / "myagent.md").write_text("prompt")
    agent = build_agent("myagent", "role", "desc", make_mock_llm(), tmp_path,
                        tools=("web_search",))
    assert agent.tool_descriptors == (WEB_SEARCH_TOOL,)


def test_build_agent_tool_descriptors_empty_when_no_tools(tmp_path):
    """build_agent() leaves tool_descriptors empty when no tools specified."""
    (tmp_path / "myagent.md").write_text("prompt")
    agent = build_agent("myagent", "role", "desc", make_mock_llm(), tmp_path)
    assert agent.tool_descriptors == ()


# ── build_analyst() ───────────────────────────────────────────────────────────

def test_build_analyst_returns_agent_with_empty_tools(tmp_path):
    """build_analyst() returns an Agent with tools=() — Analyst has no tools."""
    from agent.builder import build_analyst
    agent = build_analyst(make_config(), make_mock_llm(),
                          prompt_dir=_make_prompt_dir(tmp_path))
    assert agent.tools == ()


def test_build_analyst_returns_agent_with_empty_tool_descriptors(tmp_path):
    """build_analyst() returns an Agent with tool_descriptors=() — no descriptors needed."""
    from agent.builder import build_analyst
    agent = build_analyst(make_config(), make_mock_llm(),
                          prompt_dir=_make_prompt_dir(tmp_path))
    assert agent.tool_descriptors == ()


def test_build_agent_tool_descriptors_are_deep_copies(tmp_path):
    """Each Agent gets independent copies of descriptor dicts — mutating one does not affect another."""
    from agent.tools import WEB_SEARCH_TOOL
    (tmp_path / "agent_a.md").write_text("prompt a")
    (tmp_path / "agent_b.md").write_text("prompt b")
    agent_a = build_agent("agent_a", "role", "desc", make_mock_llm(), tmp_path,
                          tools=("web_search",))
    agent_b = build_agent("agent_b", "role", "desc", make_mock_llm(), tmp_path,
                          tools=("web_search",))
    # Mutate agent_a's descriptor copy
    agent_a.tool_descriptors[0]["injected"] = True
    # agent_b and the module constant must be unaffected
    assert "injected" not in agent_b.tool_descriptors[0]
    assert "injected" not in WEB_SEARCH_TOOL


def test_url_and_arxiv_tool_descriptors_are_deep_copies(tmp_path):
    """URL and arXiv descriptors are deep-copied — mutating one agent does not affect another or the module constants."""
    from agent.tools import URL_TOOL_DESCRIPTORS, ARXIV_TOOL_DESCRIPTORS
    (tmp_path / "agent_a.md").write_text("prompt a")
    (tmp_path / "agent_b.md").write_text("prompt b")
    agent_a = build_agent("agent_a", "role", "desc", make_mock_llm(), tmp_path,
                          tools=("read_url", "arxiv_search"))
    agent_b = build_agent("agent_b", "role", "desc", make_mock_llm(), tmp_path,
                          tools=("read_url", "arxiv_search"))
    # Find read_url descriptor in agent_a and mutate it
    read_url_desc = next(d for d in agent_a.tool_descriptors if d["name"] == "read_url")
    read_url_desc["name"] = "mutated"
    # Other agent and module constant must be unaffected
    other_read_url = next(d for d in agent_b.tool_descriptors if d["name"] == "read_url")
    assert other_read_url["name"] == "read_url"
    assert URL_TOOL_DESCRIPTORS["read_url"]["name"] == "read_url"
