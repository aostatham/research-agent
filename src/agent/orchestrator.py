"""
Research orchestration layer.

Implements the research pipeline:

    1. decompose()                — LLM breaks a topic into 4–5 focused sub-questions.
    2. _research_question_sync()  — Delegates to the Researcher Agent (agent/researcher.py)
                                    which owns the agentic search loop.
    3. research_question_async()  — Async wrapper: runs researcher then verifier.
    4. research_all_async()       — Researches all questions in parallel using asyncio.
    5. reflect()                  — Critic LLM identifies genuine gaps in the findings.
    6. run()                      — Ties all steps together; uses research_all_async()
                                    for both initial questions and gap fill.
"""

import asyncio
import json
import logging
from llm.base import LLMClient
from config import Config
from evidence.schema import ResearchResult
from agent.tools import get_and_reset_search_count


DECOMPOSE_PROMPT = """You are a research planning assistant.

Given a topic, decompose it into sub-questions that together provide comprehensive coverage.

You MUST respond ONLY with a raw JSON array of strings. No markdown, no code fences, no preamble, no explanation.

Example:
["What is X?", "How does X work?", "What are the limitations of X?"]
"""

REFLECT_PROMPT = """You are a rigorous research critic reviewing findings before a report is written.

Your job is to identify genuine gaps, weaknesses, and missing perspectives in the research.

Be demanding. Ask yourself:
- Are all major aspects of the topic covered?
- Are there conflicting viewpoints that haven't been addressed?
- Is there missing quantitative data, timelines, or key players?
- Are any findings too shallow or vague to be useful?
- Would a domain expert consider this research incomplete?

Topic: {topic}

Research findings:
{findings}

You MUST respond ONLY with raw JSON. No markdown, no code fences, no explanation.

If research is sufficient:
{{"sufficient": true, "missing": []}}

If research has genuine gaps (be specific, actionable):
{{"sufficient": false, "missing": ["specific gap 1", "specific gap 2"]}}

Only mark as insufficient if the gaps would meaningfully improve the final report.
Do not invent gaps for the sake of it — if coverage is genuinely good, mark as sufficient.
"""


class Orchestrator:
    """
    Manages the full research lifecycle for a given topic.

    Coordinates decomposition, per-question agentic research loops, and
    critic-based gap reflection.  Passes a single LLMClient for all
    orchestration LLM calls (decompose, research, reflect); the synthesiser
    uses a separate client that may be a different model or provider.
    """

    def __init__(self, llm: LLMClient, agent_pool, config: Config = None):
        """
        Initialise the orchestrator.

        Args:
            llm:        LLMClient instance for decompose and reflect calls.
            agent_pool: AgentPool containing the researcher, verifier, and editor agents.
            config:     Config instance; defaults to Config() if not provided.
        """
        self.llm = llm
        self.agent_pool = agent_pool
        self.config = config or Config()
        self._last_research_results: list = []
        self.search_count: int = 0

    def decompose(self, topic: str) -> list[str]:
        """
        Break a research topic into focused sub-questions.

        Asks the LLM to produce a JSON array of question strings.  If JSON
        parsing fails, falls back to four generic questions so the pipeline
        can always continue.

        Args:
            topic: The research topic string.

        Returns:
            List of question strings, capped at config.max_questions.
            Never shorter than four questions (fallback guarantees this).
        """
        print(f"\n📋 Decomposing topic: '{topic}'")

        prompt = (
            DECOMPOSE_PROMPT +
            f"\n\nGenerate between {self.config.min_questions} and "
            f"{self.config.max_questions} sub-questions."
            f"\n\nTopic: {topic}"
        )

        response = self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=self.config.max_tokens_research
        )

        try:
            parsed = json.loads(response.content)
            # H6: handle {"questions": [...]} wrapper shape some models emit
            if isinstance(parsed, dict):
                parsed = parsed.get("questions", [])
            if not isinstance(parsed, list):
                raise ValueError(f"expected list, got {type(parsed).__name__}")
            # Discard non-string items (defensive: model may include dicts)
            questions = [q for q in parsed if isinstance(q, str)]
            # Enforce the hard cap; the model sometimes ignores the max instruction
            questions = questions[:self.config.max_questions]
            if len(questions) < self.config.min_questions:
                print(f"  ⚠️  Only {len(questions)} questions generated, expected "
                      f"at least {self.config.min_questions}")
            for i, q in enumerate(questions, 1):
                print(f"  {i}. {q}")
            return questions
        except (json.JSONDecodeError, ValueError, AttributeError, TypeError):
            # The model returned non-JSON or unexpected shape; use safe generic
            # questions so the pipeline doesn't hard-fail at the very first step.
            print("  ⚠️  Failed to parse questions, using fallback")
            return [f"What is {topic}?", f"What are recent developments in {topic}?",
                    f"What are the key challenges in {topic}?",
                    f"Who are the key players in {topic}?"]

    def _research_question_sync(self, question: str) -> ResearchResult:
        """
        Delegate to the Researcher Agent for a single sub-question.

        Args:
            question: The sub-question to research.

        Returns:
            ResearchResult with answer, sources, and message_history.
        """
        from agent.researcher import research
        return research(
            self.agent_pool.researcher,
            question,
            max_tokens=self.config.max_tokens_research,
        )

    async def research_question_async(
        self, question: str, semaphore: asyncio.Semaphore
    ) -> ResearchResult:
        """
        Async wrapper: runs the Researcher then the Verifier.

        Acquires the semaphore before running the researcher to cap concurrent
        workers at config.max_workers.

        Verifier placement depends on the orchestration provider (D023):
          - anthropic: Verifier runs outside the semaphore so subsequent
            researchers can start while the verifier runs (original D010 behaviour).
          - ollama: Verifier runs inside the semaphore to prevent Ollama queue
            buildup that causes 60s read timeout crashes.

        Args:
            question:  The sub-question to research.
            semaphore: Shared semaphore limiting concurrent workers.

        Returns:
            ResearchResult with verified field set by the Verifier Agent.
        """
        from agent.verifier import verify
        orch_provider = self.config.orchestration_provider or self.config.provider
        if orch_provider == "ollama":
            async with semaphore:
                rr = await asyncio.to_thread(self._research_question_sync, question)
                rr = await asyncio.to_thread(
                    verify, self.agent_pool.verifier, rr,
                    self.config.max_tokens_research,
                )
        else:
            async with semaphore:
                rr = await asyncio.to_thread(self._research_question_sync, question)
            rr = await asyncio.to_thread(
                verify, self.agent_pool.verifier, rr,
                self.config.max_tokens_research,
            )
        return rr

    async def research_all_async(
        self, questions: list[str]
    ) -> tuple[dict, dict]:
        """
        Research all questions in parallel, up to config.max_workers concurrently.

        Uses asyncio.gather so all questions are submitted at once; the semaphore
        inside research_question_async() limits actual concurrency.  Question
        ordering in the returned dicts matches the input list.

        Sets self._last_research_results to the list of ResearchResult objects
        produced by this call (overwritten on each call; run_async() accumulates
        across initial + gap rounds into a final self._last_research_results).

        Args:
            questions: List of sub-question strings.

        Returns:
            Tuple of (results, sources) dicts keyed by question string.
        """
        semaphore = asyncio.Semaphore(self.config.max_workers)
        tasks = [self.research_question_async(q, semaphore) for q in questions]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        results: dict = {}
        sources: dict = {}
        self._last_research_results = []
        for question, rr in zip(questions, raw_results):
            if isinstance(rr, BaseException):
                logging.warning(f"Worker failed for '{question}': {rr}")
                continue
            results[question] = rr.answer
            sources[question] = rr.sources
            self._last_research_results.append(rr)
        return results, sources

    def reflect(self, topic: str, results: dict) -> tuple[bool, list[str]]:
        """
        Run the critic reflection pass to identify genuine research gaps.

        Sends a structured critic prompt to the LLM with the topic and a
        truncated summary of all findings.  Parses the JSON response to
        determine whether research is sufficient and what specific gaps remain.

        Handles markdown-fenced JSON responses (``` or ```json wrappers) from
        models that ignore the "raw JSON only" instruction.

        Args:
            topic:   The original research topic.
            results: Dict of {question: answer} from the research phase.
                     Answers are truncated to 300 chars in the prompt to stay
                     within token limits.

        Returns:
            Tuple of (sufficient, missing) where:
              - sufficient is True if no meaningful gaps were found.
              - missing is a list of gap description strings.
            Returns (True, []) if JSON parsing fails (conservative default).
        """
        print(f"\n🤔 Reflecting on research completeness...")

        # Truncate answers to 300 chars each to keep the prompt size reasonable
        findings_summary = "\n\n".join([
            f"Q: {q}\nA: {a[:300]}..." for q, a in results.items()
        ])

        # REFLECT_PROMPT uses .format() with {{ }} escaping for literal braces
        # in the JSON examples — do not change to f-string.
        prompt = REFLECT_PROMPT.format(
            topic=topic,
            findings=findings_summary
        )

        response = self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=self.config.max_tokens_research
        )

        try:
            content = response.content.strip()
            # Strip markdown code fences if the model wrapped the JSON
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            parsed = json.loads(content)
            # H6/M8: handle a bare list — treat it as a list of gap strings
            if isinstance(parsed, list):
                missing = [g for g in parsed if isinstance(g, str)]
                if missing:
                    print(f"  ⚠️  Gaps identified (bare list): {missing}")
                    return False, missing
                return True, []
            if not isinstance(parsed, dict):
                raise ValueError(f"expected dict or list, got {type(parsed).__name__}")
            sufficient = bool(parsed.get("sufficient", True))
            missing = parsed.get("missing", [])
            if not isinstance(missing, list):
                missing = []

            if sufficient:
                print("  ✅ Research is sufficient")
            else:
                print(f"  ⚠️  Gaps identified: {missing}")
                return False, missing

            return sufficient, missing

        except (json.JSONDecodeError, ValueError, AttributeError, TypeError):
            # If we can't parse the reflection, assume research is good enough
            # rather than triggering unnecessary extra research.
            print("  ⚠️  Could not parse reflection, proceeding anyway")
            return True, []

    async def run_async(self, topic: str) -> tuple[dict, dict]:
        """
        Async version of run(). Await this from async contexts (FastAPI, async tests).

        Steps:
          1. Decompose the topic into sub-questions.
          2. Research all sub-questions in parallel via research_all_async().
          3. Reflect on completeness; research any identified gaps in parallel.

        Args:
            topic: The research topic string.

        Returns:
            Tuple of (results, sources) where:
              - results = {question: answer} dict (includes gap questions).
              - sources = {question: [{"title": str, "url": str}]} dict.
        """
        # Reset here in addition to __init__ — a reused Orchestrator instance must not
        # leak results across runs.
        self._last_research_results = []
        questions = self.decompose(topic)

        orch_provider = self.config.orchestration_provider or self.config.provider
        if orch_provider == "ollama":
            print(
                "Warning: Ollama provider detected — Verifier will run inside the "
                "research semaphore to prevent timeouts. This adds latency per question."
            )

        print(f"\n🚀 Researching {len(questions)} questions "
              f"(workers: {self.config.max_workers})...")
        results, sources = await self.research_all_async(questions)
        all_rr = list(self._last_research_results)

        sufficient, missing = self.reflect(topic, results)

        if not sufficient and missing:
            print(f"\n🔄 Researching {len(missing)} gaps "
                  f"(workers: {self.config.max_workers})...")
            gap_results, gap_sources = await self.research_all_async(missing)
            all_rr.extend(self._last_research_results)
            results.update(gap_results)
            sources.update(gap_sources)

        self._last_research_results = all_rr
        self.search_count = get_and_reset_search_count()
        print(f"\n✅ Research complete — {len(results)} questions answered")
        return results, sources

    def run(self, topic: str) -> tuple[dict, dict]:
        """
        Synchronous entry point for CLI use.
        Do not call from inside an already-running event loop.
        Use run_async() for async contexts (FastAPI, async tests).

        Args:
            topic: The research topic string.

        Returns:
            Tuple of (results, sources).
        """
        return asyncio.run(self.run_async(topic))
