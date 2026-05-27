"""
Research loop logic for the Researcher Agent.

Contains the agentic loop that was previously inlined in
Orchestrator._research_question_sync(). Extracted here so the Agent
owns its loop semantics rather than delegating to the Orchestrator.

See DECISIONS.md D009 for rationale.
"""

import logging
import time
from agent.base import Agent
from agent.tool_utils import _validate_tool_input
from agent.tools import ALL_TOOLS, execute_tool_with_sources
from evidence.schema import ResearchResult


def research(agent: Agent, question: str, max_tokens: int = 2048) -> ResearchResult:
    """
    Run the agentic research loop for a single question.

    All loop guards are preserved exactly as in the original Orchestrator
    implementation — no behaviour change, only relocation:
      - seen_queries set: prevents A→B→A→B oscillation
      - tool-call-string detection: handles malformed model responses
      - fallback synthesis: rescues questions at max_iterations

    Args:
        agent:      Researcher Agent with llm and max_iterations configured.
        question:   The research question to answer.
        max_tokens: Token budget per LLM call.

    Returns:
        ResearchResult with answer, sources, and full message_history.
    """
    print(f"\n🔍 Researching: '{question}'")
    start = time.time()

    messages = [{"role": "user", "content": question}]
    iteration = 0
    all_sources = []
    seen_queries: set[str] = set()
    accumulated_results = []

    while iteration < agent.max_iterations:
        iteration += 1
        response = agent.chat(
            messages=messages,
            tools=ALL_TOOLS,
            max_tokens=max_tokens
        )

        if response.type == "tool_call":
            current_query = _validate_tool_input(response.tool_input)
            if current_query is None:
                logging.warning("Researcher: malformed tool input %r, skipping",
                                response.tool_input)
                continue

            if current_query in seen_queries:
                print(f"  ⚠️  Repeated query detected ('{current_query}'), "
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

            print(f"  🌐 Searching: '{current_query}'")
            tool_result, sources = execute_tool_with_sources(
                response.tool_name, response.tool_input
            )
            all_sources.extend(sources)
            seen_queries.add(current_query)
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

            elapsed = time.time() - start
            print(f"  ✅ Answer found ({len(content)} chars, {elapsed:.1f}s)")
            unique_sources = _dedup_sources(all_sources)
            return ResearchResult(
                question=question,
                answer=content,
                sources=unique_sources,
                message_history=messages,
            )

    # Max iterations reached — attempt fallback synthesis
    if accumulated_results:
        print(f"  ⚠️  Max iterations reached, attempting fallback synthesis...")
        combined = "\n\n".join(accumulated_results)
        fallback_response = agent.chat(
            messages=[{
                "role": "user",
                "content": (
                    f"Based on the following search results, please provide a comprehensive "
                    f"answer to this question: {question}\n\n"
                    f"Search results:\n{combined}\n\n"
                    f"Provide a clear, factual answer. Do not use any tools."
                )
            }],
            max_tokens=max_tokens
        )
        if fallback_response.type == "text" and len(fallback_response.content.strip()) > 50:
            elapsed = time.time() - start
            print(f"  ✅ Fallback synthesis succeeded ({len(fallback_response.content)} chars, {elapsed:.1f}s)")
            return ResearchResult(
                question=question,
                answer=fallback_response.content,
                sources=_dedup_sources(all_sources),
                message_history=messages,
            )

    elapsed = time.time() - start
    print(f"  ❌ Research failed for: '{question}' ({elapsed:.1f}s)")
    return ResearchResult(
        question=question,
        answer=f"Unable to retrieve information on: {question}",
        sources=[],
        message_history=messages,
    )


def _dedup_sources(sources: list) -> list:
    """Return sources with duplicate URLs removed, preserving first-seen order."""
    seen = set()
    unique = []
    for s in sources:
        if s["url"] not in seen:
            seen.add(s["url"])
            unique.append(s)
    return unique
