"""
Editor Agent pass for the research pipeline.

Runs a synthesised report through the Editor Agent for coherence-only
copy-editing (D011).  The editor system prompt is biased heavily toward
no-edit; it only changes text when a specific coherence defect exists.

Public API:
  edit() — run the Editor Agent on a synthesised report
"""

from agent.base import Agent


def edit(agent: Agent, report: str, max_tokens: int = 8192) -> str:
    """
    Run the Editor Agent on a synthesised report.

    The editor's system prompt restricts it to coherence defects only:
    broken cross-references, adjacent contradictions, and section headings
    that do not match their content.  It must return the full report text
    (edited or unedited) with no preamble.

    If the response is shorter than 100 characters or is not a text
    response, the original report is returned unchanged.  This guards
    against a truncated or malformed editor response discarding content.

    Args:
        agent:      Editor Agent (no tools, coherence scope only — D011).
        report:     Full synthesised report text.
        max_tokens: Token budget for the editor call. Should be large
                    enough to hold the full report (default 8192).

    Returns:
        Edited report string, or the original report if the response is
        invalid or too short to be the real report.
    """
    response = agent.chat(
        messages=[{"role": "user", "content": report}],
        max_tokens=max_tokens,
    )
    if response.type == "text" and len(response.content.strip()) >= 100:
        return response.content.strip()
    return report
