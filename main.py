"""
Research Agent — CLI entry point.

Thin orchestration layer:
  1. Parse args + load config (three-layer hierarchy)
  2. Configure search provider (anthropic or tavily)
  3. Build LLM clients via llm.builder (supports mixed providers)
  4. Run Orchestrator — decompose topic, research questions, reflect
  5. Synthesise final report via Synthesiser
  6. Format metadata, save report, update output/index.md

Business logic lives in src/: agent/, llm/, config/, output/.
"""

import json
import sys
import os
import logging
import argparse
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from dotenv import load_dotenv
from agent import Orchestrator, Synthesiser
from agent.builder import build_agents
from agent.tools import configure_search
from config import load_config
from agent.tools import configure_knowledge
from knowledge.store import get_store
from llm.builder import build_llms
from observability.events import configure_observability
from output.formatter import build_metadata
from output.writer import save_report, update_index, save_viewer
from output.provenance import (
    build_claims_from_results, build_quality_metrics,
    write_provenance_file, annotate_report_lines,
)

load_dotenv()


def parse_args():
    """
    Parse command-line arguments.

    Short flags: -p (provider), -m (model), -s (short), -f (format)
    Long flags cover all config overrides plus search provider selection.
    """
    parser = argparse.ArgumentParser(description="Research Agent")
    parser.add_argument("topic", nargs="+", help="Research topic")

    # LLM provider
    parser.add_argument("-p", "--provider", choices=["anthropic", "ollama"], default=None,
                        help="LLM provider for both tiers (default: from config.yaml)")
    parser.add_argument("-m", "--model", default=None,
                        help="Model override for both tiers")

    # Mixed provider support
    parser.add_argument("--orchestration-provider", choices=["anthropic", "ollama"],
                        default=None, help="Provider for orchestration tier only")
    parser.add_argument("--orchestration-model", default=None,
                        help="Model for orchestration tier only")
    parser.add_argument("--synthesis-provider", choices=["anthropic", "ollama"],
                        default=None, help="Provider for synthesis tier only")
    parser.add_argument("--synthesis-model", default=None,
                        help="Model for synthesis tier only")

    # Search provider
    parser.add_argument("--search-provider", choices=["anthropic", "tavily"],
                        default=None, help="Search provider (default: from config.yaml)")

    # Research depth
    parser.add_argument("--min-questions", type=int, default=None,
                        help="Minimum number of research questions (default: 4)")
    parser.add_argument("--max-questions", type=int, default=None,
                        help="Maximum number of research questions (default: 5)")
    parser.add_argument("--max-iterations", type=int, default=None,
                        help="Max search iterations per question (default: 5)")
    parser.add_argument("--max-tokens-research", type=int, default=None,
                        help="Max tokens per research call (default: 2048)")
    parser.add_argument("--max-tokens-synthesis", type=int, default=None,
                        help="Max tokens for synthesis call (default: 8192)")
    parser.add_argument("--max-workers", type=int, default=None,
                        help="Parallel research workers (default: 4)")

    # Config and output
    parser.add_argument("--config", default="config.yaml",
                        help="Path to config file (default: config.yaml)")
    parser.add_argument("-s", "--short", action="store_true",
                        help="Generate executive summary only")
    parser.add_argument("-f", "--format", choices=["markdown", "html", "pdf"],
                        default="markdown", help="Output format (default: markdown)")
    parser.add_argument("--provenance", choices=["none", "file", "graph"],
                        default="none",
                        help="Provenance output: none (default), file (.provenance.json), graph (Phase E)")
    parser.add_argument(
        "--output-mode",
        choices=["report", "report-evidence", "data", "dashboard",
                 "slides", "matrix", "academic", "bibliography", "raw"],
        default="report",
        help="Output mode (default: report)"
    )
    parser.add_argument(
        "--resume", metavar="RUN_ID", default=None,
        help="Resume an interrupted run from its last checkpoint"
    )
    parser.add_argument(
        "--follow-up", metavar="RUN_ID", default=None,
        help="Research gaps from a prior run identified by RUN_ID"
    )
    parser.add_argument(
        "--no-observability",
        action="store_true",
        help="Disable observability event logging"
    )
    parser.add_argument(
        "--no-knowledge-write",
        action="store_true",
        help="Skip writing this run to the knowledge graph"
    )
    parser.add_argument(
        "--eval-phase",
        metavar="PHASE",
        help="Record this run as an eval result for the given phase label "
             "(e.g. 'Phase E'). Saves to output/.eval/eval_results.jsonl. "
             "Requires --provenance file."
    )
    parser.add_argument(
        "--eval-compare",
        nargs=2,
        metavar=("PHASE_A", "PHASE_B"),
        help="Compare eval results between two phases for all reference topics. "
             "Does not run the pipeline. Example: --eval-compare 'Phase D' 'Phase E'"
    )

    return parser.parse_args()


def main():
    """
    Main entry point for the research agent CLI.

    Flow:
      1. Parse args + load config (three-layer hierarchy)
      2. Configure search provider
      3. Build LLM clients (supports mixed providers)
      4. Run orchestrator — decompose, research, reflect
      5. Synthesise report
      6. Build metadata, save report, update index
    """
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s:%(name)s:%(message)s")

    args = parse_args()

    if args.eval_compare:
        if args.resume:
            print("❌ --eval-compare and --resume cannot be used together.", file=sys.stderr)
            sys.exit(1)
        if args.follow_up:
            print("❌ --eval-compare and --follow-up cannot be used together.", file=sys.stderr)
            sys.exit(1)
        from eval.harness import (
            load_eval_results, compare_phases, print_comparison, REFERENCE_TOPICS,
        )
        results = load_eval_results()
        if not results:
            print("No eval results found. Run with --eval-phase to record results.")
            sys.exit(1)
        found_any = False
        for topic in REFERENCE_TOPICS:
            comparison = compare_phases(results, topic,
                                        args.eval_compare[0], args.eval_compare[1])
            if comparison:
                print_comparison(comparison)
                found_any = True
            else:
                print(f"No results for '{topic}' in one or both phases")
        sys.exit(0)

    if not args.no_observability:
        configure_observability()

    # Resolve which provider each tier will use (CLI args only — config.yaml not yet loaded)
    resolved_orch_provider = args.orchestration_provider or args.provider or None
    resolved_synth_provider = args.synthesis_provider or args.provider or None

    # Build config overrides from CLI args — None values are ignored by load_config
    overrides = {
        "provider": args.provider,
        "model": args.model,
        "orchestration_provider": args.orchestration_provider,
        "synthesis_provider": args.synthesis_provider,
        "search_provider": args.search_provider,
        "min_questions": args.min_questions,
        "max_questions": args.max_questions,
        "max_iterations": args.max_iterations,
        "max_tokens_research": args.max_tokens_research,
        "max_tokens_synthesis": args.max_tokens_synthesis,
        "max_workers": args.max_workers,
        "provenance": args.provenance,
        "output_mode": args.output_mode,
    }

    # Only set model fields for the resolved provider — prevents silently overwriting
    # the other provider's model config when --orchestration-model is passed
    if args.orchestration_model:
        if resolved_orch_provider == "ollama":
            overrides["ollama_orchestration_model"] = args.orchestration_model
        else:
            overrides["anthropic_orchestration_model"] = args.orchestration_model

    if args.synthesis_model:
        if resolved_synth_provider == "ollama":
            overrides["ollama_synthesis_model"] = args.synthesis_model
        else:
            overrides["anthropic_synthesis_model"] = args.synthesis_model

    config = load_config(config_path=args.config, overrides=overrides)

    # Fail fast if bleach is not installed when HTML or PDF output is requested.
    # Without bleach the rendered HTML is unsanitised; better to error early.
    if args.format in ("html", "pdf"):
        try:
            import bleach  # noqa: F401
        except ImportError:
            print(
                "Error: bleach is required for HTML and PDF output. "
                "Install it with: pip install bleach",
                file=sys.stderr,
            )
            sys.exit(1)

    if args.format == "pdf":
        try:
            import weasyprint  # noqa: F401
        except ImportError:
            print(
                "Error: weasyprint is required for PDF output. "
                "Install with: pip install weasyprint "
                "(macOS also requires: brew install pango)",
                file=sys.stderr,
            )
            sys.exit(1)

    # Configure search provider once at startup
    # All web searches route through execute_tool_with_sources() in tools.py
    configure_search(
        provider=config.search_provider,
        tavily_api_key=config.tavily_api_key,
        tavily_max_results=config.tavily_max_results,
        search_model=config.anthropic_search_model,
    )

    configure_knowledge(config)

    topic = " ".join(args.topic)
    started_at = datetime.now()
    start_time = time.time()

    # Build LLM clients — returns 6-tuple to support mixed providers
    try:
        orch_llm, synth_llm, orch_provider, orch_model, synth_provider, synth_model = build_llms(config)
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)

    if orch_provider == "ollama" and config.max_workers > 2:
        print(f"  ⚠️  Warning: max_workers={config.max_workers} may cause "
              f"timeouts with Ollama (safe ceiling: 2)")
        print(f"     Use --max-workers 2 for Ollama provider")

    # Print run header
    print(f"\n🔬 Research Agent")
    print(f"{'─' * 50}")
    print(f"Topic:              {topic}")
    print(f"Orch provider:      {orch_provider} / {orch_model}")
    print(f"Synth provider:     {synth_provider} / {synth_model}")
    print(f"Search provider:    {config.search_provider}")
    print(f"Questions:          {config.min_questions}–{config.max_questions}")
    print(f"Workers:            {config.max_workers}")
    if args.short:
        print(f"Mode:               Executive summary only")
    if config.output_mode != "report":
        print(f"Output mode:        {config.output_mode}")
    print(f"{'─' * 50}")

    # Build agent pool and run research pipeline
    agent_pool = build_agents(config, orch_llm, synth_llm)
    orchestrator = Orchestrator(llm=orch_llm, agent_pool=agent_pool, config=config)
    synthesiser = Synthesiser(llm=synth_llm, config=config)

    if args.resume and args.follow_up:
        print("❌ --resume and --follow-up cannot be used together.", file=sys.stderr)
        sys.exit(1)

    if args.resume:
        print(f"  Resuming run: {args.resume}")

    if args.follow_up:
        print(f"  Following up on run: {args.follow_up}")

    # orchestrator.run() / run_followup_async() returns ((results, sources), run_id)
    import asyncio as _asyncio
    if args.follow_up:
        (results, sources), run_id = _asyncio.run(
            orchestrator.run_followup_async(topic, prior_run_id=args.follow_up)
        )
    else:
        (results, sources), run_id = orchestrator.run(topic, run_id=args.resume)

    # Count researcher web searches (excludes verifier searches)
    search_count = orchestrator.search_count

    # Extract provenance claims before synthesis so the synthesiser can anchor them.
    # Also extract when knowledge_store is active so the Analyst and graph write
    # receive claims even when no provenance file is requested.
    claims = []
    prov_path = None
    if config.knowledge_store != "none" or config.provenance in ("file", "graph"):
        claims = build_claims_from_results(
            orchestrator._last_research_results, synth_llm,
            topic=topic,
            custom_domains=config.source_classification,
        )

    # Graph Verifier pass — operates on the flat claims list from build_claims_from_results().
    # The prior per-rr loop was a no-op because rr.claims is never populated by
    # build_claims_from_results() (it returns a new list, not a writeback).
    if agent_pool.graph_verifier is not None and claims:
        from agent.verifier import graph_verify
        claims = graph_verify(agent_pool.graph_verifier, claims, topic)
        disputed = sum(
            1 for c in claims if c.get("verification_status") == "disputed"
        )
        print(f"  ✅ Graph verification complete ({len(claims)} claims, {disputed} disputed)")

    # Synthesise — full report or executive summary
    report = synthesiser.synthesise(
        topic=topic,
        results=results,
        sources=sources,
        short=args.short,
        claims=claims if claims else None,
    )

    # Editor Agent pass — coherence only, biased toward no-edit (D011)
    from agent.editor import edit
    print("  ✍️  Running Editor Agent pass...")
    report = edit(agent_pool.editor, report, max_tokens=config.max_tokens_synthesis)

    elapsed = time.time() - start_time

    if config.knowledge_store != "none" or config.provenance in ("file", "graph"):
        if config.output_mode != "data":
            report, claims = annotate_report_lines(report, claims)

    if agent_pool.analyst is not None and claims:
        from agent.analyst import analyse
        print("  ✍️  Running Analyst Agent pass...")
        report, claims = analyse(agent_pool.analyst, report, claims, config)

    # Build metadata table and save outputs
    metadata = build_metadata(
        topic=topic,
        config=config,
        orch_provider=orch_provider,
        orch_model=orch_model,
        synth_provider=synth_provider,
        synth_model=synth_model,
        started_at=started_at,
        elapsed=elapsed,
        question_count=len(results),
        search_count=search_count,
        report_chars=len(report),
        short=args.short
    )

    # Apply output mode transformations before saving
    if config.output_mode == "raw":
        from output.formatter import render_raw
        report = render_raw(report)

    elif config.output_mode == "bibliography":
        from output.formatter import render_bibliography
        report = render_bibliography(report, sources)

    elif config.output_mode == "academic":
        from output.formatter import render_academic
        report = render_academic(report, topic, metadata)

    output_path = save_report(
        topic=topic,
        metadata=metadata,
        report=report,
        fmt=args.format
    )

    update_index(
        topic=topic,
        output_path=output_path,
        started_at=started_at,
        orch_provider=orch_provider,
        orch_model=orch_model,
        synth_provider=synth_provider,
        synth_model=synth_model,
        search_provider=config.search_provider,
        question_count=len(results),
        search_count=search_count,
        short=args.short,
        provenance=config.provenance,
    )

    if config.provenance == "file":
        metrics = build_quality_metrics(claims)
        prov_path = write_provenance_file(output_path, claims, metrics)
        print(f"   Provenance saved to {prov_path}")
        with open(prov_path, encoding="utf-8") as _f:
            provenance_dict = json.load(_f)
        viewer_path = save_viewer(output_path, provenance_dict)
        print(f"   Viewer saved to    {viewer_path}")
    elif config.provenance == "graph":
        print("   ⚠️  Graph provenance not yet implemented (Phase E)")

    if args.eval_phase:
        if config.provenance not in ("file", "graph") or not claims:
            logging.warning(
                "Eval requires --provenance file. Skipping eval save."
            )
        else:
            from eval.harness import compute_eval_result, save_eval_result
            eval_quality_metrics = build_quality_metrics(claims)
            duration_seconds = time.time() - start_time
            eval_result = compute_eval_result(
                topic=topic,
                run_id=run_id,
                report=report,
                claims=claims,
                quality_metrics=eval_quality_metrics,
                search_count=orchestrator.search_count,
                question_count=len(orchestrator._last_research_results),
                duration_seconds=duration_seconds,
                phase=args.eval_phase,
            )
            eval_path = save_eval_result(eval_result)
            print(f"  📊 Eval result saved: {eval_path}")

    if config.knowledge_store != "none" and not args.no_knowledge_write:
        store = get_store()
        if store is not None:
            # Build flat deduplicated source list across all research results
            seen_urls: set = set()
            all_sources = []
            for rr in orchestrator._last_research_results:
                for src in getattr(rr, "sources", []):
                    url = src.get("url", "") if isinstance(src, dict) else ""
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_sources.append(src)
            store.write_run(
                run_id=run_id,
                topic=topic,
                claims=claims,
                sources=all_sources,
                started_at=datetime.now(timezone.utc).isoformat(),
                prior_run_id=args.follow_up or None,
            )
            print(f"  Knowledge graph updated")

    # Print run summary
    print(f"\n{'─' * 50}")
    print(f"✅ Done — report saved to {output_path}")
    print(f"   Questions: {len(results)}  Searches: {search_count}  "
          f"Search provider: {config.search_provider}  Time: {elapsed:.1f}s")
    print(f"   Run ID:  {run_id}")
    print(f"{'─' * 50}\n")


if __name__ == "__main__":
    main()
