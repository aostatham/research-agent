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

    def __init__(self, llm: LLMClient, config: Config = None):
        self.llm = llm
        self.config = config or Config()

    def decompose(self, topic: str) -> list[str]:
        """Break a topic into focused sub-questions."""
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
            questions = questions[:self.config.max_questions]
            if len(questions) < self.config.min_questions:
                print(f"  ⚠️  Only {len(questions)} questions generated, expected "
                      f"at least {self.config.min_questions}")
            for i, q in enumerate(questions, 1):
                print(f"  {i}. {q}")
            return questions
        except json.JSONDecodeError:
            print("  ⚠️  Failed to parse questions, using fallback")
            return [f"What is {topic}?", f"What are recent developments in {topic}?",
                    f"What are the key challenges in {topic}?",
                    f"Who are the key players in {topic}?"]

    def research_question(self, question: str) -> tuple[str, list[dict]]:
        """
        Run the agent loop for a single question.
        Returns (answer, sources) where sources is a list of {"title", "url"} dicts.
        """
        print(f"\n🔍 Researching: '{question}'")

        messages = [{"role": "user", "content": question}]
        iteration = 0
        all_sources = []
        last_query = None
        repeated_query_count = 0
        accumulated_results = []  # track all search results for fallback

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
                    # Repeated query — search already happened, push toward synthesis
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

                # New query — execute the search
                print(f"  🌐 Searching: '{current_query}'")
                tool_result, sources = execute_tool_with_sources(
                    response.tool_name, response.tool_input
                )
                all_sources.extend(sources)
                last_query = current_query
                repeated_query_count = 0
                accumulated_results.append(f"Search: '{current_query}'\n{tool_result}")

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

                print(f"  ✅ Answer found ({len(content)} chars)")
                seen = set()
                unique_sources = []
                for s in all_sources:
                    if s["url"] not in seen:
                        seen.add(s["url"])
                        unique_sources.append(s)
                return content, unique_sources

        # Max iterations reached — attempt fallback synthesis from accumulated results
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

        print(f"  ❌ Research failed for: '{question}'")
        return f"Unable to retrieve information on: {question}", []

    def reflect(self, topic: str, results: dict) -> tuple[bool, list[str]]:
        """Critic-based reflection to identify genuine research gaps."""
        print(f"\n🤔 Reflecting on research completeness...")

        findings_summary = "\n\n".join([
            f"Q: {q}\nA: {a[:300]}..." for q, a in results.items()
        ])

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
            print("  ⚠️  Could not parse reflection, proceeding anyway")
            return True, []

    def run(self, topic: str) -> tuple[dict, dict]:
        """
        Full orchestration loop.
        Returns (results, sources) where:
          results = {question: answer}
          sources = {question: [{"title": str, "url": str}]}
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