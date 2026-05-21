import sys
import os
from dotenv import load_dotenv
from llm import AnthropicClient
from agent import Orchestrator, Synthesiser

load_dotenv()


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py \"your research topic\"")
        print("Example: python main.py \"the current state of nuclear fusion energy\"")
        sys.exit(1)

    topic = " ".join(sys.argv[1:])

    print(f"\n🔬 Research Agent")
    print(f"{'─' * 50}")
    print(f"Topic: {topic}")
    print(f"{'─' * 50}")

    # Initialise LLM and agents
    llm = AnthropicClient()
    orchestrator = Orchestrator(llm=llm)
    synthesiser = Synthesiser(llm=llm)

    # Run research
    results = orchestrator.run(topic)

    # Synthesise report
    report = synthesiser.synthesise(topic, results)

    # Save report
    output_path = save_report(topic, report)

    print(f"\n{'─' * 50}")
    print(f"✅ Done — report saved to {output_path}")
    print(f"{'─' * 50}\n")


def save_report(topic: str, report: str) -> str:
    """Save report to output/ directory, return path."""
    os.makedirs("output", exist_ok=True)

    # Sanitise topic for filename
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
    