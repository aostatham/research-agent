import sys
import os
import argparse
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from dotenv import load_dotenv
from llm import AnthropicClient, OllamaClient
from agent import Orchestrator, Synthesiser
from config import load_config

load_dotenv()


def build_client(provider: str, model: str, config) -> object:
    """Build a single LLM client for a given provider and model."""
    if provider == "anthropic":
        return AnthropicClient(model=model)
    elif provider == "ollama":
        return OllamaClient(model=model, base_url=config.ollama_base_url)
    else:
        print(f"❌ Unknown provider: '{provider}'. Choose 'anthropic' or 'ollama'.")
        sys.exit(1)


def build_llms(config):
    """
    Return (orchestration_llm, synthesis_llm) based on config.
    Supports mixed providers — orchestration and synthesis can use different backends.
    """
    # Resolve orchestration provider and model
    orch_provider = config.orchestration_provider or config.provider
    if orch_provider == "anthropic":
        orch_model = config.model or config.anthropic_orchestration_model
    else:
        orch_model = config.model or config.ollama_orchestration_model

    # Resolve synthesis provider and model
    synth_provider = config.synthesis_provider or config.provider
    if synth_provider == "anthropic":
        synth_model = config.model or config.anthropic_synthesis_model
    else:
        synth_model = config.model or config.ollama_synthesis_model

    orch_llm = build_client(orch_provider, orch_model, config)
    synth_llm = build_client(synth_provider, synth_model, config)

    return orch_llm, synth_llm, orch_provider, orch_model, synth_provider, synth_model


def parse_args():
    parser = argparse.ArgumentParser(description="Research Agent")
    parser.add_argument("topic", nargs="+", help="Research topic")
    parser.add_argument("-p", "--provider", choices=["anthropic", "ollama"], default=None,
                        help="LLM provider for both tiers (default: from config.yaml)")
    parser.add_argument("-m", "--model", default=None,
                        help="Model override for both tiers")
    parser.add_argument("--orchestration-provider", choices=["anthropic", "ollama"],
                        default=None, help="Provider for orchestration tier")
    parser.add_argument("--orchestration-model", default=None,
                        help="Model for orchestration tier")
    parser.add_argument("--synthesis-provider", choices=["anthropic", "ollama"],
                        default=None, help="Provider for synthesis tier")
    parser.add_argument("--synthesis-model", default=None,
                        help="Model for synthesis tier")
    parser.add_argument("--min-questions", type=int, default=None,
                        help="Minimum number of research questions")
    parser.add_argument("--max-questions", type=int, default=None,
                        help="Maximum number of research questions")
    parser.add_argument("--max-iterations", type=int, default=None,
                        help="Max search iterations per question")
    parser.add_argument("--max-tokens-research", type=int, default=None,
                        help="Max tokens for research calls")
    parser.add_argument("--max-tokens-synthesis", type=int, default=None,
                        help="Max tokens for synthesis call")
    parser.add_argument("--config", default="config.yaml",
                        help="Path to config file (default: config.yaml)")
    parser.add_argument("-s", "--short", action="store_true",
                        help="Generate executive summary only")
    parser.add_argument("-f", "--format", choices=["markdown", "html"], default="markdown",
                        help="Output format (default: markdown)")
    return parser.parse_args()


def main():
    args = parse_args()

    overrides = {
        "provider": args.provider,
        "model": args.model,
        "orchestration_provider": args.orchestration_provider,
        "synthesis_provider": args.synthesis_provider,
        "anthropic_orchestration_model": args.orchestration_model,
        "anthropic_synthesis_model": args.synthesis_model,
        "ollama_orchestration_model": args.orchestration_model,
        "ollama_synthesis_model": args.synthesis_model,
        "min_questions": args.min_questions,
        "max_questions": args.max_questions,
        "max_iterations": args.max_iterations,
        "max_tokens_research": args.max_tokens_research,
        "max_tokens_synthesis": args.max_tokens_synthesis,
    }
    config = load_config(config_path=args.config, overrides=overrides)

    topic = " ".join(args.topic)
    started_at = datetime.now()
    start_time = time.time()

    orch_llm, synth_llm, orch_provider, orch_model, synth_provider, synth_model = build_llms(config)

    print(f"\n🔬 Research Agent")
    print(f"{'─' * 50}")
    print(f"Topic:              {topic}")
    print(f"Orch provider:      {orch_provider} / {orch_model}")
    print(f"Synth provider:     {synth_provider} / {synth_model}")
    print(f"Questions:          {config.min_questions}–{config.max_questions}")
    if args.short:
        print(f"Mode:               Executive summary only")
    print(f"{'─' * 50}")

    orchestrator = Orchestrator(llm=orch_llm, config=config)
    synthesiser = Synthesiser(llm=synth_llm, config=config)

    results, sources = orchestrator.run(topic)
    search_count = sum(len(s) for s in sources.values())

    report = synthesiser.synthesise(
        topic=topic,
        results=results,
        sources=sources,
        short=args.short
    )

    elapsed = time.time() - start_time

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
        question_count=len(results),
        search_count=search_count,
        short=args.short
    )

    print(f"\n{'─' * 50}")
    print(f"✅ Done — report saved to {output_path}")
    print(f"   Questions: {len(results)}  Searches: {search_count}  Time: {elapsed:.1f}s")
    print(f"{'─' * 50}\n")


def build_metadata(topic, config, orch_provider, orch_model, synth_provider,
                   synth_model, started_at, elapsed, question_count,
                   search_count, report_chars, short):
    """Build a metadata table for the top of the report."""
    mode = "Executive Summary" if short else "Full Report"
    lines = [
        "| Field | Value |",
        "|---|---|",
        f"| **Topic** | {topic} |",
        f"| **Generated** | {started_at.strftime('%Y-%m-%d %H:%M')} |",
        f"| **Orchestration** | {orch_provider} / {orch_model} |",
        f"| **Synthesis** | {synth_provider} / {synth_model} |",
        f"| **Questions researched** | {question_count} |",
        f"| **Web searches** | {search_count} |",
        f"| **Time** | {elapsed:.1f}s |",
        f"| **Report length** | {report_chars:,} chars |",
        f"| **Mode** | {mode} |",
        "",
    ]
    return "\n".join(lines)


def save_report(topic: str, metadata: str, report: str, fmt: str = "markdown") -> str:
    """Save report to output/ directory, return path."""
    os.makedirs("output", exist_ok=True)
    filename = topic.lower()
    filename = "".join(c if c.isalnum() or c == " " else "" for c in filename)
    filename = filename.strip().replace(" ", "_")[:50]

    if fmt == "html":
        filepath = f"output/{filename}.html"
        html = convert_to_html(topic, metadata, report)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
    else:
        filepath = f"output/{filename}.md"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# {topic}\n\n")
            f.write(metadata + "\n")
            f.write(report)

    return filepath


def convert_to_html(topic: str, metadata: str, report: str) -> str:
    """Convert markdown report to a clean HTML page."""
    try:
        import markdown
        meta_html = markdown.markdown(metadata, extensions=["tables"])
        report_html = markdown.markdown(report, extensions=["tables", "fenced_code"])
    except ImportError:
        meta_html = f"<pre>{metadata}</pre>"
        report_html = f"<pre>{report}</pre>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{topic}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                max-width: 860px; margin: 40px auto; padding: 0 20px;
                color: #1a1a1a; line-height: 1.7; }}
        h1 {{ border-bottom: 2px solid #e0e0e0; padding-bottom: 12px; }}
        h2 {{ margin-top: 2em; color: #2c2c2c; }}
        hr {{ border: none; border-top: 1px solid #e0e0e0; margin: 1.5em 0; }}
        code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 3px;
                font-size: 0.9em; }}
        pre {{ background: #f5f5f5; padding: 16px; border-radius: 6px;
               overflow-x: auto; }}
        blockquote {{ border-left: 4px solid #e0e0e0; margin: 0;
                      padding-left: 16px; color: #555; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #e0e0e0; padding: 8px 12px; text-align: left; }}
        th {{ background: #f5f5f5; }}
        a {{ color: #0066cc; }}
        .metadata {{ background: #f9f9f9; border: 1px solid #e0e0e0;
                     border-radius: 6px; padding: 16px; margin-bottom: 2em;
                     font-size: 0.9em; }}
    </style>
</head>
<body>
    <h1>{topic}</h1>
    <div class="metadata">{meta_html}</div>
    {report_html}
</body>
</html>"""


def update_index(topic, output_path, started_at, orch_provider, orch_model,
                 synth_provider, synth_model, question_count, search_count, short):
    """Append entry to output/index.md."""
    os.makedirs("output", exist_ok=True)
    index_path = "output/index.md"

    if not os.path.exists(index_path):
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("# Research Agent — Report Index\n\n")
            f.write("| Date | Topic | Orchestration | Synthesis | Questions | Searches | Mode | File |\n")
            f.write("|---|---|---|---|---|---|---|---|\n")

    mode = "Summary" if short else "Full"
    date = started_at.strftime("%Y-%m-%d %H:%M")
    orch = f"{orch_provider}/{orch_model}"
    synth = f"{synth_provider}/{synth_model}"
    filename = os.path.basename(output_path)
    link = f"[{filename}]({filename})"

    row = f"| {date} | {topic} | {orch} | {synth} | {question_count} | {search_count} | {mode} | {link} |\n"

    with open(index_path, "a", encoding="utf-8") as f:
        f.write(row)


if __name__ == "__main__":
    main()