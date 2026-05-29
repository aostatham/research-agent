"""
Analyst Agent pass for the research pipeline.

Reviews the synthesised report against provenance claims to generate
evidence-informed quality recommendations (qualify, strengthen,
surface_contradiction). Applied after annotate_report_lines() and
before write_provenance_file() in main.py.

Public API:
  analyse() — run the Analyst Agent on a report + claims
"""

import json
import logging
from pathlib import Path
from string import Template

from agent.base import Agent
from agent.tools import build_tool_list

_ANALYST_PROMPT_PATH = (
    Path(__file__).parent.parent.parent / "prompts" / "tasks" / "analyst.md"
)


def analyse(agent: Agent, report: str, claims: list, config) -> tuple:
    """
    Run the Analyst Agent on a synthesised report.

    Filters claims to those with report_line set, builds a task prompt from
    prompts/tasks/analyst.md (with threshold values substituted), and calls
    the agent with the line-numbered report and provenance JSON.

    Applies JSON recommendations to the report text:
      qualify            — inserts suggested_qualifier (or default) before
                           the matched claim text on the relevant report line.
      strengthen         — appends "(Note: based on a single community source)"
                           after the relevant report line.
      surface_contradiction — inserts "⚠️ (disputed) " before the matched
                           claim text on the relevant report line.

    Claims are never modified; only the report text changes.

    On any exception (including agent failure or JSON parse error), logs a
    WARNING and returns the original (report, claims) unchanged so the Analyst
    never crashes the pipeline.

    Args:
        agent:   Analyst Agent with kg_ tools and max_iterations configured.
        report:  Synthesised report text after the Editor pass.
        claims:  List of EvidenceClaim dicts (may include claims without report_line).
        config:  Config instance supplying analyst_qualify_threshold and
                 analyst_strengthen_source_types.

    Returns:
        Tuple of (modified_report, claims).  claims is returned unchanged.
    """
    try:
        lines = report.split("\n")
        line_numbered = "\n".join(f"L{i + 1}: {line}" for i, line in enumerate(lines))

        filtered_claims = [c for c in claims if c.get("report_line") is not None]

        raw_prompt = _ANALYST_PROMPT_PATH.read_text(encoding="utf-8")
        analyst_prompt = Template(raw_prompt).safe_substitute(
            qualify_threshold=str(config.analyst_qualify_threshold),
            strengthen_source_types=str(config.analyst_strengthen_source_types),
        )

        user_msg = (
            f"{analyst_prompt}\n\n"
            f"Report:\n{line_numbered}\n\n"
            f"Provenance claims:\n{json.dumps(filtered_claims, indent=2)}"
        )

        response = agent.chat(
            messages=[{"role": "user", "content": user_msg}],
            tools=build_tool_list(agent.tools),
            max_tokens=2048,
        )

        if response.type != "text":
            return report, claims

        content = response.content.strip()
        start = content.find("[")
        end = content.rfind("]")
        if start == -1 or end == -1 or end <= start:
            logging.warning("Analyst: no JSON array found in response")
            return report, claims

        try:
            recommendations = json.loads(content[start:end + 1])
        except (json.JSONDecodeError, ValueError) as e:
            logging.warning("Analyst: JSON parse failed: %s", e)
            return report, claims

        claim_by_id = {c.get("id"): c for c in filtered_claims}
        modified_lines = list(lines)

        # surface_contradiction first, qualify second, strengthen third.
        # Within each type, ascending claim_id for determinism.
        _TYPE_ORDER = {"surface_contradiction": 0, "qualify": 1, "strengthen": 2}

        valid_recs = []
        for rec in recommendations:
            if not isinstance(rec, dict):
                continue
            if rec.get("report_line") is None:
                continue
            line_idx = rec["report_line"] - 1
            if not (0 <= line_idx < len(modified_lines)):
                continue
            valid_recs.append(rec)

        sorted_recs = sorted(
            valid_recs,
            key=lambda r: (_TYPE_ORDER.get(r.get("type", ""), 99),
                           r.get("claim_id") or 0),
        )

        # Per (line, type): keep first by claim_id, warn on extras.
        seen: dict = {}
        deduped_recs = []
        for rec in sorted_recs:
            rec_type = rec.get("type")
            report_line = rec.get("report_line")
            claim_id = rec.get("claim_id")
            key = (report_line, rec_type)
            if key in seen:
                logging.warning(
                    "Analyst: Multiple %s recommendations for line %d "
                    "— applying claim_id %s only",
                    rec_type, report_line, seen[key],
                )
                continue
            seen[key] = claim_id
            deduped_recs.append(rec)

        for rec in deduped_recs:
            rec_type = rec.get("type")
            report_line = rec.get("report_line")
            claim_id = rec.get("claim_id")
            line_idx = report_line - 1
            claim = claim_by_id.get(claim_id)
            claim_text = claim.get("claim", "") if claim else ""

            if rec_type == "qualify":
                qualifier = rec.get("suggested_qualifier", "According to available sources, ")
                if claim_text and claim_text in modified_lines[line_idx]:
                    modified_lines[line_idx] = modified_lines[line_idx].replace(
                        claim_text, qualifier + claim_text, 1
                    )
                else:
                    modified_lines[line_idx] = qualifier + modified_lines[line_idx]

            elif rec_type == "strengthen":
                modified_lines[line_idx] = (
                    modified_lines[line_idx] + " (Note: based on a single community source)"
                )

            elif rec_type == "surface_contradiction":
                marker = "⚠️ (disputed) "
                if claim_text and claim_text in modified_lines[line_idx]:
                    modified_lines[line_idx] = modified_lines[line_idx].replace(
                        claim_text, marker + claim_text, 1
                    )
                else:
                    modified_lines[line_idx] = marker + modified_lines[line_idx]

        return "\n".join(modified_lines), claims

    except Exception as e:
        logging.warning(
            "Analyst pass failed (%s: %s) — using original report",
            type(e).__name__, e,
        )
        return report, claims
