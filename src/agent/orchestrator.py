"""
Research orchestration layer.

Implements the full agentic research loop:

    1. decompose()         — LLM breaks a topic into 4–5 focused sub-questions.
    2. research_question() — Agentic loop per question: LLM calls web_search
                             until it has enough information to write an answer.
    3. reflect()           — Critic LLM identifies genuine gaps in the combined
                             findings.
    4. run()               — Ties all three together, optionally researching gaps
                             identified by the critic.

Key robustness mechanisms in research_question():
    - Repeated query detection: if the model issues the same search twice,
      a synthesis-forcing message is injected instead of executing another search.
    - Tool-call string detection: some smaller models return a literal "[Calling …]"
      string as text; this is caught and redirected.
    - Fallback synthesis: if max_iterations is reached but search results were
      accumulated, a standalone LLM call synthesises from those results rather
      than returning a failure message.
"""

import json
from llm.base import LLMClient
from agent.tools import ALL_TOOLS, execute_tool_with_sources
from config import Config


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

    def __init__(self, llm: LLMClient, config: Config = None):
        """
        Initialise the orchestrator.

        Args:
            llm:    LLMClient instance to use for all orchestration calls
                    (decompose, research_question, reflect).
            config: Config instance; defaults to Config() if not provided.
        """
        self.llm = llm
        self.config = config or Config()

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
            questions = json.loads(response.content)
            # Enforce the hard cap; the model sometimes ignores the max instruction
            questions = questions[:self.config.max_questions]
            if len(questions) < self.config.min_questions:
                print(f"  ⚠️  Only {len(questions)} questions generated, expected "
                      f"at least {self.config.min_questions}")
            for i, q in enumerate(questions, 1):
                print(f"  {i}. {q}")
            return questions
        except json.JSONDecodeError:
            # The model returned non-JSON; use safe generic questions so the
            # pipeline doesn't hard-fail at the very first step.
            print("  ⚠️  Failed to parse questions, using fallback")
            return [f"What is {topic}?", f"What are recent developments in {topic}?",
                    f"What are the key challenges in {topic}?",
                    f"Who are the key players in {topic}?"]

    def research_question(self, question: str) -> tuple[str, list[dict]]:
        """
        Run the agentic research loop for a single sub-question.

        The loop runs until:
          - The LLM returns a text response (answer found), or
          - max_iterations is reached (fallback synthesis attempted), or
          - A repeated query is detected and synthesis is forced.

        Message history is built manually as a list of role/content dicts.
        After each search, a forceful "do not call any tools" instruction is
        appended so smaller models don't loop indefinitely.

        Args:
            question: The sub-question to research.

        Returns:
            Tuple of (answer, sources) where:
              - answer is the synthesised text answer string.
              - sources is a deduplicated list of {"title", "url"} dicts.
            Returns a failure string and empty sources only if max_iterations
            is reached with no accumulated search results.
        """
        print(f"\n🔍 Researching: '{question}'")

        messages = [{"role": "user", "content": question}]
        iteration = 0
        all_sources = []
        last_query = None           # tracks the previous search query for repeat detection
        repeated_query_count = 0
        accumulated_results = []    # saves all search outputs for fallback synthesis

        while iteration < self.config.max_iterations:
            iteration += 1
            response = self.llm.chat(
                messages=messages,
                tools=ALL_TOOLS,
                max_tokens=self.config.max_tokens_research
            )

            if response.type == "tool_call":
                current_query = response.tool_input.get("query")

                if current_query == last_query:
                    # Same query as last time — the model already has these results.
                    # Injecting a synthesis message here breaks the loop for smaller
                    # models (e.g. llama3.1) that tend to keep re-searching.
                    repeated_query_count += 1
                    print(f"  ⚠️  Repeated query detected ({repeated_query_count}x), "
                          f"prompting synthesis...")
                    messages.append({
                        "role": "assistant",
                        "content": f"I will search for: {current_query}"
                    })
                    messages.append({
                        "role": "user",
                        "content": (
                            f"You have already searched for '{current_query}' and received results. "
                            f"Do not search again. Based on everything you have found so far, "
                            f"please provide a comprehensive text answer to the original question: "
                            f"{question}\n\nDo not use any tools. Write your answer now."
                        )
                    })
                    continue

                # New query — execute the actual search
                print(f"  🌐 Searching: '{current_query}'")
                tool_result, sources = execute_tool_with_sources(
                    response.tool_name, response.tool_input
                )
                all_sources.extend(sources)
                last_query = current_query
                repeated_query_count = 0
                # Save for fallback synthesis in case max_iterations is reached
                accumulated_results.append(f"Search: '{current_query}'\n{tool_result}")

                # Build assistant turn first (required by the message format),
                # then inject results as a user turn with a synthesis instruction.
                messages.append({
                    "role": "assistant",
                    "content": (
                        f"I need to search for more information to answer this question. "
                        f"I will search for: {current_query}"
                    )
                })
                messages.append({
                    "role": "user",
                    "content": (
                        f"Search results for '{current_query}':\n\n"
                        f"{tool_result}\n\n"
                        f"---\n"
                        f"Original question: {question}\n\n"
                        f"Based on these search results, please provide a comprehensive "
                        f"answer to the original question as plain text NOW. "
                        f"Do not call any tools. Do not search again. "
                        f"Write your answer directly."
                    )
                })

            elif response.type == "text":
                content = response.content.strip()
                if content.startswith("[Calling") or content.startswith("I'll search"):
                    # Some models (notably llama3.1) return a literal tool-call
                    # representation as text instead of a proper tool_call response.
                    # Detect this and redirect the model toward answering directly.
                    print(f"  ⚠️  Detected tool call string, forcing summary...")
                    messages.append({"role": "assistant", "content": content})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Please provide a direct text answer to the original question: "
                            f"{question}\n\nDo not use any tools. Summarise what you know."
                        )
                    })
                    continue

                # Genuine text answer — deduplicate sources and return
                print(f"  ✅ Answer found ({len(content)} chars)")
                seen = set()
                unique_sources = []
                for s in all_sources:
                    if s["url"] not in seen:
                        seen.add(s["url"])
                        unique_sources.append(s)
                return content, unique_sources

        # Max iterations reached — attempt fallback synthesis from accumulated results.
        # This rescues questions where the model kept searching without answering,
        # producing a shorter but usable answer from whatever was gathered.
        if accumulated_results:
            print(f"  ⚠️  Max iterations reached, attempting fallback synthesis...")
            combined = "\n\n".join(accumulated_results)
            fallback_response = self.llm.chat(
                messages=[{
                    "role": "user",
                    "content": (
                        f"Based on the following search results, please provide a comprehensive "
                        f"answer to this question: {question}\n\n"
                        f"Search results:\n{combined}\n\n"
                        f"Provide a clear, factual answer. Do not use any tools."
                    )
                }],
                max_tokens=self.config.max_tokens_research
            )
            if fallback_response.type == "text" and len(fallback_response.content.strip()) > 50:
                print(f"  ✅ Fallback synthesis succeeded ({len(fallback_response.content)} chars)")
                seen = set()
                unique_sources = []
                for s in all_sources:
                    if s["url"] not in seen:
                        seen.add(s["url"])
                        unique_sources.append(s)
                return fallback_response.content, unique_sources

        # No accumulated results at all — genuine research failure
        print(f"  ❌ Research failed for: '{question}'")
        return f"Unable to retrieve information on: {question}", []

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

            result = json.loads(content)
            sufficient = result.get("sufficient", True)
            missing = result.get("missing", [])

            if sufficient:
                print("  ✅ Research is sufficient")
            else:
                print(f"  ⚠️  Gaps identified: {missing}")
                return False, missing

            return sufficient, missing

        except json.JSONDecodeError:
            # If we can't parse the reflection, assume research is good enough
            # rather than triggering unnecessary extra research.
            print("  ⚠️  Could not parse reflection, proceeding anyway")
            return True, []

    def run(self, topic: str) -> tuple[dict, dict]:
        """
        Execute the full orchestration pipeline for a topic.

        Steps:
          1. Decompose the topic into sub-questions.
          2. Research each sub-question via the agentic loop.
          3. Reflect on completeness; research any identified gaps.

        Args:
            topic: The research topic string.

        Returns:
            Tuple of (results, sources) where:
              - results = {question: answer} dict (includes gap questions).
              - sources = {question: [{"title": str, "url": str}]} dict.
        """
        questions = self.decompose(topic)
        results = {}
        sources = {}

        for question in questions:
            answer, question_sources = self.research_question(question)
            results[question] = answer
            sources[question] = question_sources

        sufficient, missing = self.reflect(topic, results)

        if not sufficient and missing:
            print(f"\n🔄 Researching {len(missing)} gaps...")
            for gap in missing:
                answer, gap_sources = self.research_question(gap)
                results[gap] = answer
                sources[gap] = gap_sources

        print(f"\n✅ Research complete — {len(results)} questions answered")
        return results, sources
