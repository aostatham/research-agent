import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from dotenv import load_dotenv
from llm import AnthropicClient, OllamaClient
from agent import Orchestrator, Synthesiser
from config import load_config

load_dotenv()


def build_llms(config):
    """Return (orchestration_llm, synthesis_llm) based on config."""
    if config.provider == "anthropic":
        orch_model = config.model or config.anthropic_orchestration_model
        synth_model = config.model or config.anthropic_synthesis_model
        return (
            AnthropicClient(model=orch_model),
            AnthropicClient(model=synth_model)
        )
    elif config.provider == "ollama":
        orch_model = config.model or config.ollama_orchestration_model
        synth_model = config.model or config.ollama_synthesis_model
        return (
            OllamaClient(model=orch_model, base_url=config.ollama_base_url),
            OllamaClient(model=synth_model, base_url=config.ollama_base_url)
        )
    else:
        print(f"❌ Unknown provider: '{config.provider}'. Choose 'anthropic' or 'ollama'.")
        sys.exit(1)
        
def parse_args():
    parser = argparse.ArgumentParser(description="Research Agent")
    parser.add_argument("topic", nargs="+", help="Research topic")
    parser.add_argument("--provider", choices=["anthropic", "ollama"], default=None,
                        help="LLM provider (default: from config.yaml)")
    parser.add_argument("--model", default=None,
                        help="Model override (e.g. claude-sonnet-4-6, llama3.1)")
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
    parser.add_argument("--orchestration-model", default=None,
                    help="Override orchestration model specifically")
    parser.add_argument("--synthesis-model", default=None,
                    help="Override synthesis model specifically")
    return parser.parse_args()


def main():
    args = parse_args()

    overrides = {
        "provider": args.provider,
        "model": args.model,
        "min_questions": args.min_questions,
        "max_questions": args.max_questions,
        "max_iterations": args.max_iterations,
        "max_tokens_research": args.max_tokens_research,
        "max_tokens_synthesis": args.max_tokens_synthesis,
    }
    config = load_config(config_path=args.config, overrides=overrides)

    topic = " ".join(args.topic)

    orch_model = config.model or (
        config.anthropic_orchestration_model
        if config.provider == "anthropic"
        else config.ollama_orchestration_model
    )
    synth_model = config.model or (
        config.anthropic_synthesis_model
        if config.provider == "anthropic"
        else config.ollama_synthesis_model
    )

    print(f"\n🔬 Research Agent")
    print(f"{'─' * 50}")
    print(f"Topic:              {topic}")
    print(f"Provider:           {config.provider}")
    print(f"Orchestration model:{orch_model}")
    print(f"Synthesis model:    {synth_model}")
    print(f"Questions:          {config.min_questions}–{config.max_questions}")
    print(f"{'─' * 50}")

    orch_llm, synth_llm = build_llms(config)
    orchestrator = Orchestrator(llm=orch_llm, config=config)
    synthesiser = Synthesiser(llm=synth_llm, config=config)

    results, sources = orchestrator.run(topic)
    report = synthesiser.synthesise(topic, results, sources=sources)
    output_path = save_report(topic, report)

    print(f"\n{'─' * 50}")
    print(f"✅ Done — report saved to {output_path}")
    print(f"{'─' * 50}\n")

def save_report(topic: str, report: str) -> str:
    os.makedirs("output", exist_ok=True)
    filename = topic.lower()
    filename = "".join(c if c.isalnum() or c == " " else "" for c in filename)
    filename = filename.strip().replace(" ", "_")[:50]
    filename = f"output/{filename}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# {topic}\n\n")
        f.write(report)
    return filename


if __name__ == "__main__":
    main()