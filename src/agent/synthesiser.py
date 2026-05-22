"""
Report synthesis layer.

Takes the structured research findings produced by the Orchestrator and
generates a polished markdown report via a single LLM call.

Two modes are supported:
    - Full report (default): executive summary, per-finding sections,
      conclusion, gaps, and a deduplicated References section.
    - Executive summary (--short): 3–5 paragraphs, no References section,
      lower token limit.

Sources are formatted at two levels:
    1. Inline per-finding "Sources:" block within the formatted prompt so the
       LLM can reference them in-text.
    2. Master deduplicated References section appended to the final report.
"""

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

SHORT_SYNTHESISE_PROMPT = """You are a research report writer.

Given a topic and structured research findings, write a concise executive summary
in markdown format.

The summary should:
- Be 3-5 paragraphs
- Cover the most important findings only
- Include a brief conclusion
- Note the most critical gaps

Be factual, concise, and well-organised.
You MUST respond ONLY with the markdown summary. No preamble, no explanation.
"""


class Synthesiser:
    """
    Generates a structured markdown report from orchestrator findings.

    Receives the {question: answer} results dict and the {question: sources}
    dict, formats them into a structured prompt, and delegates the actual
    writing to an LLM.  Post-processes the response to append a deduplicated
    master References section.
    """

    def __init__(self, llm: LLMClient, config: Config = None):
        """
        Initialise the synthesiser.

        Args:
            llm:    LLMClient instance for synthesis calls.  Typically a higher-
                    quality model than the orchestration client (e.g. Sonnet vs
                    Haiku).
            config: Config instance; defaults to Config() if not provided.
        """
        self.llm = llm
        self.config = config or Config()

    def synthesise(self, topic: str, results: dict,
                   sources: dict = None, max_tokens: int = None,
                   short: bool = False) -> str:
        """
        Synthesise research findings into a structured markdown report.

        Formats findings with inline sources into a prompt, calls the LLM,
        then appends a master References section (full mode only).

        Args:
            topic:      The research topic string.
            results:    {question: answer} dict from the orchestrator.
            sources:    {question: [{"title": str, "url": str}]} from the
                        orchestrator.  Optional — omit or pass None/empty dict
                        for no citation output.
            max_tokens: Override the config token limit for this call.
            short:      If True, use the shorter executive-summary prompt and
                        a lower token limit (min(2048, config.max_tokens_synthesis)).

        Returns:
            Markdown string.  Full mode appends a References section;
            short mode does not.
        """
        print("\n📝 Synthesising report...")

        if short:
            print("   (executive summary mode)")
            # Cap short-mode tokens so we don't waste budget on a brief summary
            max_tokens = max_tokens or min(2048, self.config.max_tokens_synthesis)
            prompt_template = SHORT_SYNTHESISE_PROMPT
        else:
            max_tokens = max_tokens or self.config.max_tokens_synthesis
            prompt_template = SYNTHESISE_PROMPT

        findings = self._format_findings(results, sources or {})

        prompt = (
            prompt_template +
            f"\n\n# Topic\n{topic}\n\n# Research Findings\n{findings}"
        )

        response = self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens
        )

        report = response.content

        # Append master reference list in full mode only; short summaries omit it
        if sources and not short:
            references = self._format_master_references(sources)
            if references:
                report += "\n\n" + references

        print(f"  ✅ Report generated ({len(report)} chars)")
        return report

    def _format_findings(self, results: dict, sources: dict) -> str:
        """
        Format the findings dict as numbered markdown sections for the prompt.

        Each section includes the question, the answer, and an inline Sources
        block listing the citations for that question.  Sections are separated
        by horizontal rules so the LLM can clearly distinguish findings.

        Args:
            results: {question: answer} dict.
            sources: {question: [{"title": str, "url": str}]} dict.
                     Missing keys are treated as an empty source list.

        Returns:
            Multi-section markdown string, or empty string if results is empty.
        """
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
        """
        Build a deduplicated numbered References section from all sources.

        Iterates sources in question order, deduplicating by URL so each
        source appears exactly once even if it was cited across multiple
        questions.

        Args:
            sources: {question: [{"title": str, "url": str}]} dict.

        Returns:
            Markdown "## References" section string, or empty string if
            no sources are available.
        """
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
