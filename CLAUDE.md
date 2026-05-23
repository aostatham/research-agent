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
  evidence/
    schema.py             # EvidenceSource, EvidenceClaim, ProvenanceReport TypedDicts
  output/
    formatter.py          # build_metadata(), convert_to_html(), convert_to_pdf()
    writer.py             # save_report(), update_index()
    provenance.py         # Claim extraction, confidence scoring, source
                          # classification, provenance file writer
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

278 unit tests must pass before every commit.
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
    patch("output.provenance.classify_source_type")  not patch elsewhere
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
- source_classification in config.yaml extends the source type classifier
  with custom domains — see provenance.py classify_source_type() docstring


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
  - provenance.py: classify_source_type(), score_confidence(),
    extract_claims_from_answer(), build_claims_from_results(),
    annotate_report_lines(), write_provenance_file(), build_quality_metrics()
  - evidence/schema.py: EvidenceSource, EvidenceClaim, ProvenanceReport TypedDicts
  - All output functions are independent of the research pipeline

Evidence and provenance pipeline:
  - Triggered in main() when --provenance file or --provenance graph
  - build_claims_from_results() calls extract_claims_from_answer() per question
  - extract_claims_from_answer() uses synth_llm to extract atomic claims via LLM
  - classify_source_type() uses five layers: TLD patterns, stable patterns,
    hardcoded institutional list, custom config domains, LLM fallback
  - score_confidence() scores per claim based on source types and corroboration
  - annotate_report_lines() adds [N] markers to report and sets report_line on claims
  - write_provenance_file() writes .provenance.json alongside the report
  - provenance.py has no imports from agent/ or llm/ — llm_client passed as argument

Source classification maintenance:
  - Layer 3 hardcoded list in classify_source_type() — add only when a domain
    appears in 3+ runs misclassified and LLM fallback unavailable or incorrect
  - Custom domains go in config.yaml source_classification section
  - Never add domains speculatively — only on evidence of misclassification


## Current development phase

Phase C — Evidence Layer is largely complete:
  Part 1  Evidence schema, provenance file pipeline, --provenance flag
  Part 2  Atomic claim extraction, confidence scoring, report line tracking
  Part 3  Source classifier refactor (hybrid pattern + LLM fallback + config)

Remaining Phase C items (not yet implemented):
  - Output mode renderers: dashboard, matrix, academic, bibliography, raw
  - report-evidence mode: inline [N] markers working but sparse (report line
    matching improves in Phase D synthesiser integration)

276 unit tests passing.

Next phases — do not begin without explicit instruction:
  Option A: Phase D — Parallel Research Architecture
  Option B: Phase C remaining output mode renderers
            (dashboard, matrix, academic, bibliography, raw)

Do not begin either option without explicit instruction from the user.


## Roadmap summary

Phase A  Stability and quality                    COMPLETE
Phase B  Output options (markdown/HTML/PDF)       COMPLETE
Phase C  Evidence layer and output modes          LARGELY COMPLETE
Phase D  Parallel research architecture           PENDING
Phase E  Memory and persistent knowledge          PENDING
Phase F  Tools and sources                        PENDING
Phase G  Provider optimisation                    PENDING
Phase H  Observability and production readiness   PENDING
Phase I  Interface                                PENDING