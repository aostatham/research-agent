"""
Editor Agent pass for the research pipeline.

Runs a synthesised report through the Editor Agent for coherence-only
copy-editing (D011).  The editor system prompt is biased heavily toward
no-edit; it only changes text when a specific coherence defect exists.

Public API:
  edit() — run the Editor Agent on a synthesised report
"""

import difflib
import logging

from agent.base import Agent


def edit(agent: Agent, report: str, max_tokens: int = 8192) -> str:
    """
    Run the Editor Agent on a synthesised report.

    The editor's system prompt restricts it to coherence defects only:
    broken cross-references, adjacent contradictions, and section headings
    that do not match their content.  It must return the full report text
    (edited or unedited) with no preamble.

    A response is only accepted if both conditions are true:
      1. len(edited) >= 0.5 * len(original)  — proportional length floor.
      2. SequenceMatcher ratio >= 0.5  — edited text is substantially
         similar to the original (catches refusals, preamble-only replies,
         and complete rewrites that ignore the source report).

    Either failure logs a WARNING and returns the original report unchanged.

    Args:
        agent:      Editor Agent (no tools, coherence scope only — D011).
        report:     Full synthesised report text.
        max_tokens: Token budget for the editor call. Should be large
                    enough to hold the full report (default 8192).

    Returns:
        Edited report string, or the original report if the response is
        rejected by either acceptance check.
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
            "Editor response rejected: %d chars < 50%% of original %d chars",
            len(edited), len(report),
        )
        return report
    ratio = difflib.SequenceMatcher(None, report, edited).ratio()
    if ratio < 0.5:
        logging.warning(
            "Editor response rejected: similarity ratio %.2f < 0.5 "
            "(original %d chars, edited %d chars)",
            ratio, len(report), len(edited),
        )
        return report
    return edited
