import json
from llm.base import LLMClient, LLMResponse
from agent.tools import ALL_TOOLS, execute_tool


# ── Prompts ───────────────────────────────────────────────────────────────────

DECOMPOSE_PROMPT = """You are a research planning assistant.

Given a topic, decompose it into 3-5 focused sub-questions that together would 
provide comprehensive coverage of the topic.

You MUST respond ONLY with a raw JSON array of strings. No markdown, no code fences, no preamble, no explanation.

Example:
["What is X?", "How does X work?", "What are the limitations of X?"]
"""

AGENT_SYSTEM_PROMPT = """You are a research assistant with access to a web search tool.

Your job is to answer a specific research question by searching the web.
- Call the web_search tool with a focused query
- You may search multiple times if the first result is insufficient
- Once you have enough information, summarise your findings clearly
- Be factual, cite what you found, note any conflicting information
"""

REFLECT_PROMPT = """You are a research quality reviewer.

Given a research topic and the findings gathered so far, determine if the
research is sufficient to write a comprehensive report.

You MUST respond ONLY with raw JSON. No markdown, no code fences, no explanation.

{"sufficient": true, "missing": []}
or
{"sufficient": false, "missing": ["topic 1", "topic 2"]}
"""

SYNTHESISE_PROMPT = """You are a research report writer.

Given a topic and structured research findings, write a comprehensive, 
well-structured report in markdown format.

The report should include:
- An executive summary
- A section for each major finding
- A conclusion
- Noted gaps or areas for further research

Be factual, clear, and well-organised.
"""


# ── Orchestrator ──────────────────────────────────────────────────────────────

class Orchestrator:

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def decompose(self, topic: str) -> list[str]:
        """Break a topic into focused sub-questions."""
        print(f"\n📋 Decomposing topic: '{topic}'")

        response = self.llm.chat(
            messages=[{"role": "user", "content": DECOMPOSE_PROMPT + f"\n\nTopic: {topic}"}]
        )

        try:
            questions = json.loads(response.content)
            for i, q in enumerate(questions, 1):
                print(f"  {i}. {q}")
            return questions
        except json.JSONDecodeError:
            print("  ⚠️  Failed to parse questions, using fallback")
            return [f"What is {topic}?", f"What are recent developments in {topic}?",
                    f"What are the key challenges in {topic}?"]

    def research_question(self, question: str) -> str:
        """Run the agent loop for a single question."""
        print(f"\n🔍 Researching: '{question}'")

        messages = [
            {"role": "user", "content": question}
        ]

        max_iterations = 5
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            response = self.llm.chat(messages=messages, tools=ALL_TOOLS)

            if response.type == "tool_call":
                print(f"  🌐 Searching: '{response.tool_input.get('query')}'")

                # Execute the tool
                tool_result = execute_tool(response.tool_name, response.tool_input)

                messages.append({
                    "role": "assistant",
                    "content": f"I'll search for information about this. Searching for: {response.tool_input.get('query')}"
                })
                messages.append({
                    "role": "user",
                    "content": f"Here are the search results:\n\n{tool_result}\n\nPlease summarise the findings to answer the original question."
                })
            elif response.type == "text":
                print(f"  ✅ Answer found ({len(response.content)} chars)")
                return response.content

        return "Research incomplete — max iterations reached."

    def reflect(self, topic: str, results: dict) -> tuple[bool, list[str]]:
        """Check if gathered research is sufficient."""
        print(f"\n🤔 Reflecting on research completeness...")

        findings_summary = "\n".join([
            f"Q: {q}\nA: {a[:200]}..." for q, a in results.items()
        ])

        prompt = (
            REFLECT_PROMPT +
            f"\n\nTopic: {topic}\n\nFindings so far:\n{findings_summary}"
        )

        response = self.llm.chat(messages=[{"role": "user", "content": prompt}])

        try:
            result = json.loads(response.content)
            sufficient = result.get("sufficient", True)
            missing = result.get("missing", [])
            if sufficient:
                print("  ✅ Research is sufficient")
            else:
                print(f"  ⚠️  Missing: {missing}")
            return sufficient, missing
        except json.JSONDecodeError:
            print("  ⚠️  Could not parse reflection, proceeding anyway")
            return True, []

    def run(self, topic: str) -> dict:
        """
        Full orchestration loop:
        1. Decompose topic into questions
        2. Research each question
        3. Reflect on completeness
        4. Research any gaps
        5. Return all findings
        """
        # Step 1: Decompose
        questions = self.decompose(topic)
        results = {}

        # Step 2: Research each question
        for question in questions:
            results[question] = self.research_question(question)

        # Step 3: Reflect
        sufficient, missing = self.reflect(topic, results)

        # Step 4: Research gaps if needed
        if not sufficient and missing:
            print(f"\n🔄 Researching {len(missing)} gaps...")
            for gap in missing:
                results[gap] = self.research_question(gap)

        print(f"\n✅ Research complete — {len(results)} questions answered")
        return results
    