"""
Tests for agent/orchestrator.py — Orchestrator.

Verifies:
    - decompose(): JSON parsing, max_questions enforcement, fallback on bad JSON,
      prompt includes min/max bounds, max_tokens passed from config.
    - _research_question_sync(): delegates to agent.researcher.research(), passes
      the researcher agent and max_tokens.
    - research_question_async(): async wrapper, semaphore gating, always calls
      verifier (D010), result returned from verifier.
    - research_all_async(): async wrapper, semaphore gating, parallel dispatch,
      result and source aggregation, single-worker failure does not abort pipeline.
    - reflect(): JSON parsing, sufficient/insufficient paths, markdown-fenced JSON
      handling, fallback on parse error, topic and findings included in prompt.
    - run(): full pipeline composition, gap research triggered on insufficient
      reflection, gap research skipped when sufficient.

All tests mock the LLM; research and verify calls are patched at the function level.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch
from agent.orchestrator import Orchestrator
from evidence.schema import ResearchResult
from llm.base import LLMResponse
from config import Config


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def config():
    """Standard Config for orchestrator tests."""
    return Config(
        min_questions=4,
        max_questions=5,
        max_iterations=5,
        max_tokens_research=2048,
        max_tokens_synthesis=8192
    )


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    return MagicMock()


@pytest.fixture
def mock_pool():
    """Mock AgentPool with three mock agents."""
    return MagicMock()


@pytest.fixture
def orchestrator(mock_llm, config, mock_pool):
    """Orchestrator wired to a mock LLM, test config, and mock agent pool."""
    return Orchestrator(llm=mock_llm, agent_pool=mock_pool, config=config)


@pytest.fixture(autouse=True)
def patch_save_checkpoint():
    """Suppress checkpoint writes in all orchestrator tests (filesystem side-effect)."""
    with patch("agent.orchestrator.save_checkpoint"):
        yield


def make_text_response(content):
    """Build a text LLMResponse with the given content string."""
    return LLMResponse(type="text", content=content)


def make_rr(question="Q?", answer="answer", sources=None):
    """Build a ResearchResult for use as a mock return value."""
    return ResearchResult(question=question, answer=answer, sources=sources or [])


# ── decompose() tests ─────────────────────────────────────────────────────────
# Verify topic decomposition: JSON parsing, slicing to max_questions, fallback.

def test_decompose_returns_list_of_questions(orchestrator, mock_llm):
    """Valid JSON array response is parsed into a list of question strings."""
    mock_llm.chat.return_value = make_text_response(
        '["What is fusion?", "How does fusion work?", "What are fusion challenges?", "Who leads fusion research?"]'
    )
    questions = orchestrator.decompose("nuclear fusion")
    assert isinstance(questions, list)
    assert len(questions) >= 1
    assert all(isinstance(q, str) for q in questions)


def test_decompose_invalid_json_returns_fallback(orchestrator, mock_llm):
    """Non-JSON response triggers the four-question fallback list."""
    mock_llm.chat.return_value = make_text_response("not valid json at all")
    questions = orchestrator.decompose("nuclear fusion")
    assert isinstance(questions, list)
    assert len(questions) >= 4


def test_decompose_calls_llm_once(orchestrator, mock_llm):
    """decompose() makes exactly one LLM call."""
    mock_llm.chat.return_value = make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]')
    orchestrator.decompose("nuclear fusion")
    assert mock_llm.chat.call_count == 1


def test_decompose_respects_max_questions(orchestrator, mock_llm, config):
    """Returned list is capped at config.max_questions even if LLM returns more."""
    config.max_questions = 3
    mock_llm.chat.return_value = make_text_response(
        '["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"]'
    )
    questions = orchestrator.decompose("nuclear fusion")
    assert len(questions) <= 3


def test_decompose_includes_min_max_in_prompt(orchestrator, mock_llm, config):
    """Prompt sent to LLM includes both min and max question counts."""
    config.min_questions = 3
    config.max_questions = 6
    mock_llm.chat.return_value = make_text_response('["Q1?", "Q2?", "Q3?"]')
    orchestrator.decompose("nuclear fusion")
    call_content = mock_llm.chat.call_args[1]["messages"][0]["content"]
    assert "3" in call_content
    assert "6" in call_content


def test_decompose_fallback_meets_min_questions(orchestrator, mock_llm):
    """Fallback list always has at least 4 questions."""
    mock_llm.chat.return_value = make_text_response("not valid json")
    questions = orchestrator.decompose("nuclear fusion")
    assert len(questions) >= 4


def test_decompose_uses_config_max_tokens(orchestrator, mock_llm, config):
    """max_tokens passed to LLM matches config.max_tokens_research."""
    config.max_tokens_research = 512
    mock_llm.chat.return_value = make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]')
    orchestrator.decompose("nuclear fusion")
    assert mock_llm.chat.call_args[1]["max_tokens"] == 512


# ── _research_question_sync() tests ──────────────────────────────────────────
# Verify delegation to the Researcher Agent.

def test_research_question_sync_delegates_to_researcher(orchestrator):
    """_research_question_sync delegates to agent.researcher.research()."""
    rr = make_rr(question="What is fusion?", answer="Fusion combines atoms.")
    with patch("agent.researcher.research", return_value=rr) as mock_research:
        result = orchestrator._research_question_sync("What is fusion?")
    mock_research.assert_called_once_with(
        orchestrator.agent_pool.researcher,
        "What is fusion?",
        max_tokens=orchestrator.config.max_tokens_research,
    )
    assert result is rr


def test_research_question_sync_passes_max_tokens(orchestrator):
    """max_tokens_research from config is forwarded to research()."""
    orchestrator.config.max_tokens_research = 1234
    rr = make_rr()
    with patch("agent.researcher.research", return_value=rr) as mock_research:
        orchestrator._research_question_sync("Q?")
    assert mock_research.call_args[1]["max_tokens"] == 1234


def test_research_question_sync_returns_research_result(orchestrator):
    """Return value from research() is returned unchanged."""
    rr = make_rr(question="Q?", answer="precise answer")
    with patch("agent.researcher.research", return_value=rr):
        result = orchestrator._research_question_sync("Q?")
    assert result is rr


# ── Verifier semaphore placement (D023) ──────────────────────────────────────
# Gate is on synth_provider (Verifier uses synth_llm).
# When synth_provider is "ollama", the Verifier runs *inside* the semaphore.
# When synth_provider is "anthropic", the Verifier runs *outside* (D010 behaviour).

def test_verifier_runs_inside_semaphore_for_ollama():
    """Ollama path: verify is awaited while the semaphore is still held."""
    cfg = Config(provider="ollama")
    orch = Orchestrator(llm=MagicMock(), agent_pool=MagicMock(), config=cfg)
    sem = asyncio.Semaphore(1)
    sem_locked_during_verify = []

    rr = make_rr(question="Q?", answer="ans")

    def fake_verify(agent, result, max_tokens):
        sem_locked_during_verify.append(sem.locked())
        return result

    with patch.object(orch, '_research_question_sync', return_value=rr):
        with patch("agent.verifier.verify", side_effect=fake_verify):
            asyncio.run(orch.research_question_async("Q?", sem))

    assert sem_locked_during_verify == [True]


def test_verifier_runs_outside_semaphore_for_anthropic():
    """Anthropic path: verify is awaited after the semaphore has been released."""
    cfg = Config(provider="anthropic")
    orch = Orchestrator(llm=MagicMock(), agent_pool=MagicMock(), config=cfg)
    sem = asyncio.Semaphore(1)
    sem_locked_during_verify = []

    rr = make_rr(question="Q?", answer="ans")

    def fake_verify(agent, result, max_tokens):
        sem_locked_during_verify.append(sem.locked())
        return result

    with patch.object(orch, '_research_question_sync', return_value=rr):
        with patch("agent.verifier.verify", side_effect=fake_verify):
            asyncio.run(orch.research_question_async("Q?", sem))

    assert sem_locked_during_verify == [False]


def test_ollama_warning_printed_once_per_run(orchestrator, mock_llm, capsys):
    """Ollama semaphore warning is printed exactly once per run regardless of question count."""
    orchestrator.config.provider = "ollama"
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]'),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer="ans")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        orchestrator.run("topic")
    out = capsys.readouterr().out
    assert out.count("Verifier will run inside the research semaphore") == 1


def test_anthropic_no_ollama_warning(orchestrator, mock_llm, capsys):
    """No Ollama semaphore warning is printed when synth_provider is anthropic."""
    orchestrator.config.provider = "anthropic"
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]'),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer="ans")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        orchestrator.run("topic")
    out = capsys.readouterr().out
    assert "Verifier will run inside the research semaphore" not in out


# ── Mixed-provider semaphore placement (D023) ─────────────────────────────────
# The gate checks synth_provider, not orch_provider. These tests verify that
# the mixed-provider configurations route correctly.

def test_verifier_outside_semaphore_mixed_orch_ollama_synth_anthropic():
    """Mixed (orch=ollama, synth=anthropic): Verifier runs outside semaphore."""
    cfg = Config(orchestration_provider="ollama", synthesis_provider="anthropic")
    orch = Orchestrator(llm=MagicMock(), agent_pool=MagicMock(), config=cfg)
    sem = asyncio.Semaphore(1)
    sem_locked_during_verify = []

    rr = make_rr(question="Q?", answer="ans")

    def fake_verify(agent, result, max_tokens):
        sem_locked_during_verify.append(sem.locked())
        return result

    with patch.object(orch, '_research_question_sync', return_value=rr):
        with patch("agent.verifier.verify", side_effect=fake_verify):
            asyncio.run(orch.research_question_async("Q?", sem))

    assert sem_locked_during_verify == [False]


def test_verifier_inside_semaphore_mixed_orch_anthropic_synth_ollama():
    """Mixed (orch=anthropic, synth=ollama): Verifier runs inside semaphore."""
    cfg = Config(orchestration_provider="anthropic", synthesis_provider="ollama")
    orch = Orchestrator(llm=MagicMock(), agent_pool=MagicMock(), config=cfg)
    sem = asyncio.Semaphore(1)
    sem_locked_during_verify = []

    rr = make_rr(question="Q?", answer="ans")

    def fake_verify(agent, result, max_tokens):
        sem_locked_during_verify.append(sem.locked())
        return result

    with patch.object(orch, '_research_question_sync', return_value=rr):
        with patch("agent.verifier.verify", side_effect=fake_verify):
            asyncio.run(orch.research_question_async("Q?", sem))

    assert sem_locked_during_verify == [True]


def test_verifier_inside_semaphore_pure_ollama():
    """Pure ollama (orch=ollama, synth=ollama): Verifier runs inside semaphore."""
    cfg = Config(orchestration_provider="ollama", synthesis_provider="ollama")
    orch = Orchestrator(llm=MagicMock(), agent_pool=MagicMock(), config=cfg)
    sem = asyncio.Semaphore(1)
    sem_locked_during_verify = []

    rr = make_rr(question="Q?", answer="ans")

    def fake_verify(agent, result, max_tokens):
        sem_locked_during_verify.append(sem.locked())
        return result

    with patch.object(orch, '_research_question_sync', return_value=rr):
        with patch("agent.verifier.verify", side_effect=fake_verify):
            asyncio.run(orch.research_question_async("Q?", sem))

    assert sem_locked_during_verify == [True]


def test_verifier_outside_semaphore_pure_anthropic():
    """Pure anthropic (orch=anthropic, synth=anthropic): Verifier runs outside semaphore."""
    cfg = Config(orchestration_provider="anthropic", synthesis_provider="anthropic")
    orch = Orchestrator(llm=MagicMock(), agent_pool=MagicMock(), config=cfg)
    sem = asyncio.Semaphore(1)
    sem_locked_during_verify = []

    rr = make_rr(question="Q?", answer="ans")

    def fake_verify(agent, result, max_tokens):
        sem_locked_during_verify.append(sem.locked())
        return result

    with patch.object(orch, '_research_question_sync', return_value=rr):
        with patch("agent.verifier.verify", side_effect=fake_verify):
            asyncio.run(orch.research_question_async("Q?", sem))

    assert sem_locked_during_verify == [False]


# ── research_question_async() tests ──────────────────────────────────────────
# Verify async wrapper, semaphore gating, and unconditional verifier call.

def test_research_question_async_calls_sync(orchestrator):
    """research_question_async delegates to _research_question_sync."""
    sem = asyncio.Semaphore(4)
    rr = make_rr(question="Q?", answer="ans", sources=[{"title": "T", "url": "u"}])
    with patch.object(orchestrator, '_research_question_sync', return_value=rr) as m:
        with patch("agent.verifier.verify", return_value=rr):
            result_rr = asyncio.run(orchestrator.research_question_async("Q?", sem))
    m.assert_called_once_with("Q?")
    assert result_rr.answer == "ans"


def test_research_question_async_always_calls_verifier(orchestrator):
    """Verifier is always invoked after research — unconditional (D010)."""
    sem = asyncio.Semaphore(4)
    rr = make_rr(question="Q?", answer="ans")
    with patch.object(orchestrator, '_research_question_sync', return_value=rr):
        with patch("agent.verifier.verify", return_value=rr) as mock_verify:
            asyncio.run(orchestrator.research_question_async("Q?", sem))
    mock_verify.assert_called_once()


def test_research_question_async_returns_verifier_result(orchestrator):
    """Return value is the ResearchResult produced by the verifier."""
    sem = asyncio.Semaphore(4)
    original = make_rr(question="Q?", answer="original")
    verified = make_rr(question="Q?", answer="verified", sources=[])
    with patch.object(orchestrator, '_research_question_sync', return_value=original):
        with patch("agent.verifier.verify", return_value=verified):
            result = asyncio.run(orchestrator.research_question_async("Q?", sem))
    assert result is verified


def test_research_question_async_passes_verifier_agent(orchestrator):
    """Verifier is called with agent_pool.verifier."""
    sem = asyncio.Semaphore(4)
    rr = make_rr()
    with patch.object(orchestrator, '_research_question_sync', return_value=rr):
        with patch("agent.verifier.verify", return_value=rr) as mock_verify:
            asyncio.run(orchestrator.research_question_async("Q?", sem))
    assert mock_verify.call_args[0][0] is orchestrator.agent_pool.verifier


# ── reflect() tests ───────────────────────────────────────────────────────────
# Verify JSON parsing, sufficient/insufficient paths, prompt content, edge cases.

def test_reflect_returns_sufficient_true(orchestrator, mock_llm):
    """sufficient=true JSON response returns (True, [])."""
    mock_llm.chat.return_value = make_text_response('{"sufficient": true, "missing": []}')
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is True
    assert missing == []


def test_reflect_returns_sufficient_false_with_gaps(orchestrator, mock_llm):
    """sufficient=false JSON response returns the missing list."""
    mock_llm.chat.return_value = make_text_response(
        '{"sufficient": false, "missing": ["commercial viability", "development timeline"]}'
    )
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is False
    assert "commercial viability" in missing
    assert "development timeline" in missing


def test_reflect_invalid_json_defaults_to_sufficient(orchestrator, mock_llm):
    """Parse failure defaults to sufficient=True to avoid spurious extra research."""
    mock_llm.chat.return_value = make_text_response("not valid json")
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is True
    assert missing == []


def test_reflect_uses_config_max_tokens(orchestrator, mock_llm, config):
    """max_tokens for the reflect call matches config.max_tokens_research."""
    config.max_tokens_research = 512
    mock_llm.chat.return_value = make_text_response('{"sufficient": true, "missing": []}')
    orchestrator.reflect("fusion", {"Q1": "A1"})
    assert mock_llm.chat.call_args[1]["max_tokens"] == 512


def test_reflect_includes_topic_in_prompt(orchestrator, mock_llm):
    """The topic string appears in the prompt sent to the LLM."""
    mock_llm.chat.return_value = make_text_response('{"sufficient": true, "missing": []}')
    orchestrator.reflect("nuclear fusion", {"Q1": "A1"})
    call_content = mock_llm.chat.call_args[1]["messages"][0]["content"]
    assert "nuclear fusion" in call_content


def test_reflect_includes_findings_in_prompt(orchestrator, mock_llm):
    """The question strings from the results dict appear in the prompt."""
    mock_llm.chat.return_value = make_text_response('{"sufficient": true, "missing": []}')
    orchestrator.reflect("fusion", {"What is fusion?": "Fusion combines nuclei."})
    call_content = mock_llm.chat.call_args[1]["messages"][0]["content"]
    assert "What is fusion?" in call_content


def test_reflect_handles_markdown_fenced_json(orchestrator, mock_llm):
    """JSON wrapped in ```json code fences is stripped and parsed correctly."""
    mock_llm.chat.return_value = make_text_response(
        '```json\n{"sufficient": true, "missing": []}\n```'
    )
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is True


def test_reflect_prompt_includes_full_findings(orchestrator, mock_llm):
    """Answers up to 300 chars are included in the prompt (truncation check)."""
    mock_llm.chat.return_value = make_text_response('{"sufficient": true, "missing": []}')
    results = {"What is fusion?": "A" * 400}
    orchestrator.reflect("fusion", results)
    call_content = mock_llm.chat.call_args[1]["messages"][0]["content"]
    assert "A" * 300 in call_content


def test_reflect_returns_all_gaps_without_filtering(orchestrator, mock_llm):
    """All gap strings are returned regardless of their length."""
    mock_llm.chat.return_value = make_text_response(
        '{"sufficient": false, "missing": ["timeline", "cost", "commercial viability and investment landscape"]}'
    )
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is False
    assert "timeline" in missing
    assert "cost" in missing
    assert "commercial viability and investment landscape" in missing


# ── H6/M8: JSON shape hardening ──────────────────────────────────────────────

def test_decompose_handles_dict_wrapper_shape(orchestrator, mock_llm):
    """decompose() extracts questions from {"questions": [...]} dict shape."""
    mock_llm.chat.return_value = make_text_response(
        '{"questions": ["What is fusion?", "How hot is plasma?", "What is ITER?", "What is NIF?"]}'
    )
    questions = orchestrator.decompose("fusion")
    assert "What is fusion?" in questions
    assert len(questions) >= 1


def test_decompose_handles_non_list_json_with_fallback(orchestrator, mock_llm):
    """decompose() falls back to generic questions when JSON is not a list or recognisable dict."""
    mock_llm.chat.return_value = make_text_response('"just a string"')
    questions = orchestrator.decompose("fusion")
    assert len(questions) >= 4
    assert any("fusion" in q.lower() for q in questions)


def test_reflect_handles_bare_list_as_gaps(orchestrator, mock_llm):
    """reflect() treats a bare JSON list as a list of gap strings (sufficient=False)."""
    mock_llm.chat.return_value = make_text_response(
        '["cost of construction", "timeline to commercial viability"]'
    )
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is False
    assert "cost of construction" in missing


def test_reflect_handles_non_dict_non_list_json_with_fallback(orchestrator, mock_llm):
    """reflect() falls back to (True, []) when JSON is neither dict nor list."""
    mock_llm.chat.return_value = make_text_response('"sufficient"')
    sufficient, missing = orchestrator.reflect("fusion", {"Q1": "A1"})
    assert sufficient is True
    assert missing == []


# ── run() tests ───────────────────────────────────────────────────────────────
# Verify the full pipeline composition: decompose + research + reflect + gap fill.
# Research calls are patched via research_question_async; mock_llm handles
# decompose and reflect only.

def test_run_returns_dict_of_results(orchestrator, mock_llm):
    """run() returns a results dict with one entry per question."""
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]'),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer=f"Answer for {q}")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        (results, sources), _ = orchestrator.run("nuclear fusion")
    assert isinstance(results, dict)
    assert isinstance(sources, dict)
    assert len(results) == 4


def test_run_returns_sources_dict(orchestrator, mock_llm):
    """run() returns a sources dict keyed by question."""
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]'),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    mock_sources = [{"title": "Source", "url": "https://example.com"}]
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer="ans", sources=mock_sources)
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        (results, sources), _ = orchestrator.run("nuclear fusion")
    assert isinstance(sources, dict)
    for question in results:
        assert question in sources


def test_run_researches_gaps_when_insufficient(orchestrator, mock_llm):
    """Gap questions identified by reflect() are added to results and sources."""
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]'),
        make_text_response('{"sufficient": false, "missing": ["commercial timeline"]}'),
    ]
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer=f"Answer for {q}")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        (results, sources), _ = orchestrator.run("nuclear fusion")
    assert "commercial timeline" in results
    assert "commercial timeline" in sources


def test_run_does_not_research_gaps_when_sufficient(orchestrator, mock_llm):
    """When reflect returns sufficient=True, no extra LLM calls are made."""
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]'),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer="ans")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        orchestrator.run("nuclear fusion")
    # 1 decompose + 1 reflect = exactly 2 mock_llm calls (research goes through agent_pool)
    assert mock_llm.chat.call_count == 2


def test_run_uses_config_question_bounds(orchestrator, mock_llm, config):
    """run() respects config.max_questions by researching exactly that many questions."""
    config.min_questions = 3
    config.max_questions = 3
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?"]'),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer="ans")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        (results, sources), _ = orchestrator.run("nuclear fusion")
    assert len(results) == 3


# ── Async / parallel research tests (Phase D Part 1) ─────────────────────────
# Verify research_question_async, research_all_async, and max_workers config.

def test_run_async_returns_correct_tuple_shape(orchestrator, mock_llm):
    """run_async() returns a ((results, sources), run_id) tuple."""
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]'),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer="ans")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        (results, sources), run_id = asyncio.run(orchestrator.run_async("nuclear fusion"))
    assert isinstance(results, dict)
    assert isinstance(sources, dict)
    assert isinstance(run_id, str)


def test_config_max_workers_default():
    """Config defaults max_workers to 2 (safe ceiling for Ollama)."""
    assert Config().max_workers == 2


def test_research_all_async_results_have_all_questions(orchestrator):
    """research_all_async returns one result entry per input question."""
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer="answer")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        results, _ = asyncio.run(orchestrator.research_all_async(["Q1?", "Q2?", "Q3?"]))
    assert set(results.keys()) == {"Q1?", "Q2?", "Q3?"}


def test_research_all_async_sources_have_all_questions(orchestrator):
    """research_all_async returns one sources entry per input question."""
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer="answer")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        _, sources = asyncio.run(orchestrator.research_all_async(["Q1?", "Q2?"]))
    assert set(sources.keys()) == {"Q1?", "Q2?"}


def test_research_all_async_calls_per_question(orchestrator):
    """research_question_async is invoked once per input question."""
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer="a")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa) as m:
        asyncio.run(orchestrator.research_all_async(["Q1?", "Q2?", "Q3?"]))
    assert m.call_count == 3


def test_research_all_async_one_worker_failure_continues(orchestrator):
    """Single worker exception does not abort pipeline; remaining results are returned."""
    async def fake_rqa(q, sem):
        if q == "Q2?":
            raise RuntimeError("worker failure")
        return make_rr(question=q, answer=f"Answer for {q}")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        results, sources = asyncio.run(orchestrator.research_all_async(["Q1?", "Q2?", "Q3?"]))
    assert "Q1?" in results
    assert "Q3?" in results
    assert "Q2?" not in results


def test_research_all_async_empty_questions(orchestrator):
    """research_all_async with an empty list returns empty dicts."""
    results, sources = asyncio.run(orchestrator.research_all_async([]))
    assert results == {}
    assert sources == {}


def test_research_all_async_preserves_answers(orchestrator):
    """research_all_async passes through each answer from research_question_async."""
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer=f"Answer for {q}")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        results, _ = asyncio.run(orchestrator.research_all_async(["Q1?", "Q2?"]))
    assert results["Q1?"] == "Answer for Q1?"
    assert results["Q2?"] == "Answer for Q2?"


def test_run_max_workers_respected(orchestrator, mock_llm, config):
    """run() processes all questions even when max_workers is smaller than question count."""
    config.max_workers = 2
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]'),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer="ans")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        (results, sources), _ = orchestrator.run("nuclear fusion")
    assert len(results) == 4


def test_run_gap_research_also_parallel(orchestrator, mock_llm):
    """Gap questions identified by reflect() are also researched via research_all_async."""
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]'),
        make_text_response('{"sufficient": false, "missing": ["gap1", "gap2"]}'),
    ]
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer=f"Answer for {q}")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        (results, sources), _ = orchestrator.run("nuclear fusion")
    assert "gap1" in results
    assert "gap2" in results
    assert "gap1" in sources
    assert "gap2" in sources


# ── Orchestrator construction ─────────────────────────────────────────────────

def test_orchestrator_requires_agent_pool(mock_llm, config):
    """Orchestrator raises TypeError when agent_pool is not provided."""
    with pytest.raises(TypeError):
        Orchestrator(llm=mock_llm, config=config)


def test_orchestrator_stores_agent_pool(mock_llm, config):
    """Provided AgentPool is stored on self.agent_pool."""
    mock_pool = MagicMock()
    orch = Orchestrator(llm=mock_llm, agent_pool=mock_pool, config=config)
    assert orch.agent_pool is mock_pool


def test_orchestrator_stores_llm(mock_llm, config, mock_pool):
    """LLM client is stored on self.llm."""
    orch = Orchestrator(llm=mock_llm, agent_pool=mock_pool, config=config)
    assert orch.llm is mock_llm


def test_orchestrator_stores_config(mock_llm, config, mock_pool):
    """Config is stored on self.config."""
    orch = Orchestrator(llm=mock_llm, agent_pool=mock_pool, config=config)
    assert orch.config is config


def test_orchestrator_defaults_config_when_none(mock_llm, mock_pool):
    """When config=None, a default Config() is used."""
    orch = Orchestrator(llm=mock_llm, agent_pool=mock_pool)
    assert isinstance(orch.config, Config)


def test_orchestrator_search_count_initialises_to_zero(mock_llm, config, mock_pool):
    """search_count starts at 0 before any run."""
    orch = Orchestrator(llm=mock_llm, agent_pool=mock_pool, config=config)
    assert orch.search_count == 0


def test_run_search_count_comes_from_module_counter(orchestrator, mock_llm):
    """search_count is populated from get_and_reset_search_count() after all research."""
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?"]'),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer="ans")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa), \
         patch("agent.orchestrator.get_and_reset_search_count", return_value=7):
        orchestrator.run("topic")
    assert orchestrator.search_count == 7


def test_run_search_count_reset_at_start_prevents_cross_run_leakage(orchestrator, mock_llm):
    """A failed first run does not leak its search count into the next successful run."""
    from agent.tools import _search_call_count as _orig  # noqa: F401
    import agent.tools as tools_mod

    # Manually set a residual count as if a previous failed run left it dirty
    tools_mod._search_call_count = 5

    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?"]'),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer="ans")

    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        orchestrator.run("topic")

    # The counter was reset at run start, so the final search_count reflects
    # only the current run (0 actual searches via mocked rqa), not the residue.
    assert orchestrator.search_count == 0


# ── RunState checkpoint tests ─────────────────────────────────────────────────

def test_run_async_saves_checkpoint_at_each_stage(orchestrator, mock_llm):
    """run_async() calls save_checkpoint at the decompose, research, reflect, and synthesise stages."""
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]'),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer="ans")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa), \
         patch("agent.orchestrator.save_checkpoint") as mock_ckpt:
        asyncio.run(orchestrator.run_async("nuclear fusion"))
    # 4 saves: initial (decompose), after decompose (research),
    # after initial research (reflect), after gap research (synthesise)
    assert mock_ckpt.call_count == 4


def test_run_async_returns_run_id_tuple(orchestrator, mock_llm):
    """run_async() returns a ((results, sources), run_id) 2-tuple."""
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]'),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer="ans")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        result = asyncio.run(orchestrator.run_async("nuclear fusion"))
    assert len(result) == 2
    research_output, run_id = result
    results, sources = research_output
    assert isinstance(results, dict)
    assert isinstance(run_id, str)
    assert len(run_id) > 0


def test_run_async_generates_new_run_id_when_none_provided(orchestrator, mock_llm):
    """A new run_id is generated when no run_id is passed to run_async()."""
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]'),
        make_text_response('{"sufficient": true, "missing": []}'),
        make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]'),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer="ans")
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        _, run_id_1 = asyncio.run(orchestrator.run_async("nuclear fusion"))
        _, run_id_2 = asyncio.run(orchestrator.run_async("nuclear fusion"))
    assert run_id_1 != run_id_2


def test_run_async_uses_provided_run_id(orchestrator, mock_llm):
    """When a run_id is provided, run_async() uses it rather than generating a new one."""
    mock_llm.chat.side_effect = [
        make_text_response('["Q1?", "Q2?", "Q3?", "Q4?"]'),
        make_text_response('{"sufficient": true, "missing": []}'),
    ]
    async def fake_rqa(q, sem):
        return make_rr(question=q, answer="ans")
    fixed_id = "myspecialrunid123"
    with patch.object(orchestrator, 'research_question_async', side_effect=fake_rqa):
        _, returned_id = asyncio.run(orchestrator.run_async("nuclear fusion", run_id=fixed_id))
    assert returned_id == fixed_id


# ── Integration tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
def test_real_orchestrator_run():
    """Live end-to-end orchestrator run produces a populated results dict."""
    from llm import AnthropicClient
    from dotenv import load_dotenv
    load_dotenv()

    llm = AnthropicClient()
    mock_pool = MagicMock()
    orchestrator = Orchestrator(llm=llm, agent_pool=mock_pool)
    (results, sources), run_id = orchestrator.run("the current state of nuclear fusion energy")

    assert isinstance(results, dict)
    assert isinstance(sources, dict)
    assert isinstance(run_id, str)
    assert len(results) >= 3
    for question, answer in results.items():
        assert isinstance(question, str)
        assert isinstance(answer, str)
        assert len(answer) > 100
