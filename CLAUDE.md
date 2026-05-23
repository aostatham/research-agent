# Research Agent — Claude Code Instructions

## Project layout

main.py                   # Thin CLI entry point: parse_args(), main() only
src/
  agent/
    orchestrator.py       # Decompose, research loop, reflect
    synthesiser.py        # Report generation (two modes: full / short)
    tools.py              # Tool definitions + Anthropic/Tavily search routing
  llm/
    base.py               # LLMClient ABC + LLMResponse dataclass
    anthropic_client.py   # Anthropic implementation
    ollama_client.py      # Ollama implementation
    retry.py              # Exponential backoff decorator
    builder.py            # build_client(), build_llms() factory functions
  config/
    settings.py           # Config dataclass + three-layer loader
  output/
    formatter.py          # build_metadata(), convert_to_html(), convert_to_pdf()
    writer.py             # save_report(), update_index()
    provenance.py         # Phase C stub — not yet implemented
config.yaml               # Default runtime config (provider, models, search, limits)
tests/                    # Unit tests — one file per source module


## Commands

Unit tests — always run before committing:
  pytest tests/ -m "not integration" -v

Integration tests — free (Ollama + Tavily, requires live services):
  pytest tests/test_integration_smoke.py -m "ollama" -v

Integration tests — Anthropic-specific (costs money, run explicitly only):
  pytest tests/test_integration_smoke.py -m "anthropic_integration" -v

Run the agent:
  python main.py "your topic"
  python main.py "your topic" -p ollama -m llama3.1
  python main.py "your topic" --search-provider tavily
  python main.py "your topic" --orchestration-provider ollama --synthesis-provider anthropic
  python main.py "your topic" -f pdf -s
  python main.py "your topic" --output-mode report-evidence --provenance file


## Test baseline

199 unit tests must pass before every commit.
Always run: pytest tests/ -m "not integration" -v
Never commit with a failing test.


## Test conventions

- Unit tests mock all external clients (anthropic.Anthropic, TavilyClient, OllamaClient)
- Integration tests are marked @pytest.mark.integration and excluded from the default run
- Ollama integration tests are marked @pytest.mark.ollama
- Anthropic integration tests are marked @pytest.mark.anthropic_integration (costs money)
- Patch at the module where the name is looked up, not where it is defined:
    patch("llm.builder.AnthropicClient")       not patch("llm.anthropic_client.AnthropicClient")
    patch("output.writer.update_index")        not patch("main.update_index")
    patch("output.formatter.convert_to_pdf")   not patch("main.convert_to_pdf")
- Every new function needs at least one unit test
- New modules need a test file: tests/test_<module>.py


## Commit style

- One-line subject, imperative mood, no trailing period
- Body paragraph explaining the why, not the what
- No Co-Authored-By lines
- Stage specific files — never git add -A
- Logic changes and structural changes in separate commits


## Code conventions

- Docstrings on all public functions and modules
- Inline comments only when the WHY is non-obvious — not the what
- Type hints on all function signatures
- No logic changes during structural refactors — one concern per commit
- New config fields go in Config dataclass in config/settings.py
- New CLI flags go in parse_args() in main.py and overrides dict in main()


## Config and environment

- .env is gitignored — never commit it
- ANTHROPIC_API_KEY and TAVILY_API_KEY are env vars only
- config.yaml holds runtime defaults; CLI flags override them; neither is secret
- Three-layer config hierarchy: hardcoded defaults -> config.yaml -> CLI flags


## Key architectural notes

Provider abstraction:
  - LLMClient is the abstract base — AnthropicClient and OllamaClient implement it
  - LLMResponse is normalised: type="text" or type="tool_call"
  - build_llms() in llm/builder.py returns a 6-tuple:
    (orch_llm, synth_llm, orch_provider, orch_model, synth_provider, synth_model)
  - Mixed provider: orchestration and synthesis can use different backends per run

Search routing:
  - Controlled by module-level globals in tools.py set once via configure_search()
  - configure_search() is called at startup in main() before any research begins
  - Anthropic web search citations appear on TEXT blocks, not tool_result blocks
    This is non-obvious behaviour — documented in tools.py

Agentic loop guards in orchestrator.py:
  - Repeated query detection — prevents infinite search loops
  - Tool-call-string detection — handles malformed LLM responses
  - Fallback synthesis — rescues questions that exhaust max iterations
  - accumulated_results enables fallback even when no clean answer was found

Output pipeline:
  - formatter.py: build_metadata(), convert_to_html(), convert_to_pdf()
  - writer.py: save_report(), update_index()
  - provenance.py: Phase C placeholder — not yet implemented
  - All output functions are independent of the research pipeline


## Current development phase

Phase C — Evidence Layer is next to implement. Do not begin until explicitly instructed.

When Phase C begins, the key changes will be:
  - Evidence objects replace raw text answers throughout the pipeline
  - orchestrator.py returns structured evidence objects not raw strings
  - synthesiser.py receives evidence objects and writes with confidence hedging
  - provenance.py implements provenance file generation
  - New CLI flags: --output-mode and --provenance
  - New output modes: report (default), report-evidence, data, dashboard, raw
  - New provenance options: none (default), file, graph

Evidence object schema (TypedDict):
  {
    "claim": str,
    "source": str,
    "confidence": float,
    "contradictions": list,
    "evidence_type": str,    # quantitative | qualitative | cited | inferred
    "verification_status": str,  # verified | unverified | disputed
    "timestamp": str
  }

Provenance file format:
  nuclear_fusion_energy.provenance.json
  {
    "report_file": "nuclear_fusion_energy.md",
    "generated": "2026-05-22T13:50:00",
    "quality_metrics": {
      "coverage": 0.87,
      "confidence": 0.81,
      "contradictions": 2,
      "verified_claims": 14,
      "unverified_claims": 3
    },
    "claims": [
      {
        "id": 1,
        "report_line": 42,
        "claim": "NIF achieved ignition in December 2022",
        "confidence": 0.96,
        "verification_status": "verified",
        "evidence_type": "quantitative",
        "sources": [...],
        "contradictions": []
      }
    ]
  }


## Roadmap summary

Phase A  Stability and quality                    COMPLETE
Phase B  Output options (markdown/HTML/PDF)       COMPLETE
Phase C  Evidence layer and output modes          NEXT
Phase D  Parallel research architecture           PENDING
Phase E  Memory and persistent knowledge          PENDING
Phase F  Tools and sources                        PENDING
Phase G  Provider optimisation                    PENDING
Phase H  Observability and production readiness   PENDING
Phase I  Interface                                PENDING