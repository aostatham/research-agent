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

import sys
import os
import argparse
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from dotenv import load_dotenv
from agent import Orchestrator, Synthesiser
from agent.builder import build_agents
from agent.tools import configure_search
from config import load_config
from llm.builder import build_llms
from output.formatter import build_metadata
from output.writer import save_report, update_index
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
    args = parse_args()

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

    # Configure search provider once at startup
    # All web searches route through execute_tool_with_sources() in tools.py
    configure_search(
        provider=config.search_provider,
        tavily_api_key=config.tavily_api_key,
        tavily_max_results=config.tavily_max_results
    )

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
    orchestrator = Orchestrator(llm=orch_llm, config=config, agent_pool=agent_pool)
    synthesiser = Synthesiser(llm=synth_llm, config=config)

    # orchestrator.run() returns ({question: answer}, {question: [sources]})
    results, sources = orchestrator.run(topic)

    # Count total web searches across all questions
    search_count = sum(len(s) for s in sources.values())

    # Synthesise — full report or executive summary
    report = synthesiser.synthesise(
        topic=topic,
        results=results,
        sources=sources,
        short=args.short
    )

    elapsed = time.time() - start_time

    # Build provenance claims before saving so annotated report is written to disk
    claims = []
    prov_path = None
    if config.provenance in ("file", "graph"):
        claims = build_claims_from_results(
            results, sources, synth_llm,
            custom_domains=config.source_classification,
        )
        if config.output_mode != "data":
            report, claims = annotate_report_lines(report, claims)

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
    elif config.provenance == "graph":
        print("   ⚠️  Graph provenance not yet implemented (Phase E)")

    # Print run summary
    print(f"\n{'─' * 50}")
    print(f"✅ Done — report saved to {output_path}")
    print(f"   Questions: {len(results)}  Searches: {search_count}  "
          f"Search provider: {config.search_provider}  Time: {elapsed:.1f}s")
    print(f"{'─' * 50}\n")


if __name__ == "__main__":
    main()
