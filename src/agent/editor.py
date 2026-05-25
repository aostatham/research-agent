"""
Editor Agent pass for the research pipeline.

Runs a synthesised report through the Editor Agent for coherence-only
copy-editing (D011).  The editor system prompt is biased heavily toward
no-edit; it only changes text when a specific coherence defect exists.

Public API:
  edit() — run the Editor Agent on a synthesised report
"""

import logging

from agent.base import Agent


def edit(agent: Agent, report: str, max_tokens: int = 8192) -> str:
    """
    Run the Editor Agent on a synthesised report.

    The editor's system prompt restricts it to coherence defects only:
    broken cross-references, adjacent contradictions, and section headings
    that do not match their content.  It must return the full report text
    (edited or unedited) with no preamble.

    A response is only accepted if it passes two checks:
      1. Length >= 50% of the original report (proportional floor).
      2. Does not start with a refusal phrase in the first 60 characters.
    Either failure returns the original report unchanged.

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
    if response.type != "text":
        return report
    edited = response.content.strip()
    if len(edited) < 0.5 * len(report):
        logging.warning(
            f"Editor response rejected: {len(edited)} chars < 50% of original {len(report)} chars"
        )
        return report
    refusal_phrases = ("sorry", "i cannot", "i can't", "i'm unable", "as an ai")
    if any(phrase in edited[:60].lower() for phrase in refusal_phrases):
        logging.warning("Editor response rejected: starts with refusal phrase")
        return report
    return edited
