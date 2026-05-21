from llm.base import LLMClient


SYNTHESISE_PROMPT = """You are a research report writer.

Given a topic and structured research findings, write a comprehensive,
well-structured report in markdown format.

The report should include:
- An executive summary (2-3 paragraphs)
- A section for each major finding with clear headings
- A conclusion summarising the overall picture
- A final section noting gaps or areas for further research

Guidelines:
- Be factual and precise
- Use clear, professional language
- Use markdown headings, bullet points, and bold text where appropriate
- Do not invent information not present in the findings
- Where findings conflict, note the conflict explicitly

You MUST respond ONLY with the markdown report. No preamble, no explanation.
"""


class Synthesiser:

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def synthesise(self, topic: str, results: dict) -> str:
        """
        Take a topic and dict of {question: answer} findings,
        return a structured markdown report.
        """
        print("\n📝 Synthesising report...")

        findings = self._format_findings(results)

        prompt = (
            SYNTHESISE_PROMPT +
            f"\n\n# Topic\n{topic}\n\n# Research Findings\n{findings}"
        )

        response = self.llm.chat(
            messages=[{"role": "user", "content": prompt}]
        )

        print(f"  ✅ Report generated ({len(response.content)} chars)")
        return response.content

    def _format_findings(self, results: dict) -> str:
        """Format findings dict into a readable string for the prompt."""
        sections = []
        for i, (question, answer) in enumerate(results.items(), 1):
            sections.append(f"## Finding {i}\n**Question:** {question}\n\n**Answer:**\n{answer}")
        return "\n\n---\n\n".join(sections)
    