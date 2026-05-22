from llm.base import LLMClient
from config import Config


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

    def __init__(self, llm: LLMClient, config: Config = None):
        self.llm = llm
        self.config = config or Config()

    def synthesise(self, topic: str, results: dict,
                   sources: dict = None, max_tokens: int = None) -> str:
        """
        Synthesise research findings into a structured report.

        Args:
            topic:      Research topic
            results:    {question: answer} dict from orchestrator
            sources:    {question: [{"title": str, "url": str}]} from orchestrator
            max_tokens: Override config value if needed
        """
        print("\n📝 Synthesising report...")

        max_tokens = max_tokens or self.config.max_tokens_synthesis
        findings = self._format_findings(results, sources or {})

        prompt = (
            SYNTHESISE_PROMPT +
            f"\n\n# Topic\n{topic}\n\n# Research Findings\n{findings}"
        )

        response = self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens
        )

        report = response.content

        # Append master reference list if sources available
        if sources:
            references = self._format_master_references(sources)
            if references:
                report += "\n\n" + references

        print(f"  ✅ Report generated ({len(report)} chars)")
        return report

    def _format_findings(self, results: dict, sources: dict) -> str:
        """Format findings with inline source attribution."""
        sections = []
        for i, (question, answer) in enumerate(results.items(), 1):
            question_sources = sources.get(question, [])
            source_text = ""
            if question_sources:
                source_lines = "\n".join([
                    f"  - [{s['title']}]({s['url']})"
                    for s in question_sources
                ])
                source_text = f"\n\n**Sources:**\n{source_lines}"
            sections.append(
                f"## Finding {i}\n**Question:** {question}\n\n"
                f"**Answer:**\n{answer}{source_text}"
            )
        return "\n\n---\n\n".join(sections)

    def _format_master_references(self, sources: dict) -> str:
        """Build a deduplicated master reference list."""
        seen = set()
        all_sources = []
        for question_sources in sources.values():
            for s in question_sources:
                if s["url"] not in seen:
                    seen.add(s["url"])
                    all_sources.append(s)

        if not all_sources:
            return ""

        lines = ["## References\n"]
        for i, s in enumerate(all_sources, 1):
            lines.append(f"{i}. [{s['title']}]({s['url']})")

        return "\n".join(lines)