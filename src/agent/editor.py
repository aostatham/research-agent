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

    Pre-processing: if the response starts with a preamble (e.g. "Here is
    the edited report:") followed by the original text, the preamble is
    stripped and the result returned directly.

    A response is only accepted if both conditions are true:
      1. len(edited) > 0.5 * len(original)  — proportional length floor
         (strictly greater than 50%; exactly 50% is rejected).
      2. SequenceMatcher ratio >= 0.5  — edited text is substantially
         similar to the original (catches refusals and complete rewrites).
         Skipped for strings exceeding 100000 characters.

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

    # M5: strip preamble when the model prefixes the report with boilerplate.
    # If edited doesn't start with the same 80 chars as original but contains
    # original as a substring, strip everything before the report starts.
    original_prefix = report.strip()[:80]
    if not edited.startswith(original_prefix):
        idx = edited.find(report)
        if idx > 0:
            return edited[idx:]

    # M6: <= instead of < so an exactly-50%-length response is also rejected.
    if len(edited) <= 0.5 * len(report):
        logging.warning(
            "Editor response rejected: %d chars < 50%% of original %d chars",
            len(edited), len(report),
        )
        return report
    # Skip similarity check for very long strings to bound O(N*M) cost.
    if len(report) > 100000 or len(edited) > 100000:
        logging.debug(
            "Editor: skipping similarity check — strings exceed 100000 char cap"
        )
        return edited
    sm = difflib.SequenceMatcher(None, report, edited, autojunk=False)
    ratio = sm.ratio()
    if ratio < 0.5:
        logging.warning(
            "Editor response rejected: similarity ratio %.2f < 0.5 "
            "(original %d chars, edited %d chars)",
            ratio, len(report), len(edited),
        )
        return report
    return edited
