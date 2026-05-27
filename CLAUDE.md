# Research Agent — Claude Code Instructions

## Project layout

main.py                   # Thin CLI entry point: parse_args(), main() only
src/
  agent/
    base.py               # Agent and AgentPool frozen dataclasses
    orchestrator.py       # Decompose, research loop, reflect
    researcher.py         # Researcher Agent — owns the agentic loop
    verifier.py           # Verifier Agent — parallel claim verification
    editor.py             # Editor Agent — coherence pass after synthesis
    synthesiser.py        # Report generation (two modes: full / short)
    tools.py              # Tool definitions + Anthropic/Tavily search routing
    tool_utils.py         # Shared tool input validation helper
    builder.py            # build_agent(), build_agents(), AgentPool factory
  llm/
    base.py               # LLMClient ABC + LLMResponse dataclass
    anthropic_client.py   # Anthropic implementation
    ollama_client.py      # Ollama implementation
    retry.py              # Exponential backoff decorator
    builder.py            # build_client(), build_llms() factory functions
  config/
    settings.py           # Config dataclass + three-layer loader
  evidence/
    schema.py             # EvidenceSource, EvidenceClaim, ProvenanceReport,
                          # ResearchResult TypedDicts
  output/
    formatter.py          # build_metadata(), convert_to_html(), convert_to_pdf()
    writer.py             # save_report(), update_index()
    provenance.py         # Claim extraction, confidence scoring, source
                          # classification, provenance file writer
config.yaml               # Default runtime config (provider, models, search, limits)
prompts/                  # Agent system prompts (versioned in git)
  researcher.md           # Researcher Agent system prompt
  verifier.md             # Verifier Agent system prompt
  editor.md               # Editor Agent system prompt
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
  python main.py "your topic" --max-workers 4


## Test baseline

528 unit tests must pass before every commit.
Always run: pytest tests/ -m "not integration" -v
Never commit with a failing test.


## Test conventions

- Unit tests mock all external clients (anthropic.Anthropic, TavilyClient, OllamaClient)
- Integration tests are marked @pytest.mark.integration and excluded from the default run
- Ollama integration tests are marked @pytest.mark.ollama
- Anthropic integration tests are marked @pytest.mark.anthropic_integration (costs money)
- Patch at the module where the name is looked up, not where it is defined:
    patch("src.agent.builder.AnthropicClient")     not patch("src.llm.anthropic_client.AnthropicClient")
    patch("src.agent.builder.OllamaClient")        not patch elsewhere
    patch("src.output.writer.update_index")        not patch("main.update_index")
    patch("src.output.formatter.convert_to_pdf")   not patch("main.convert_to_pdf")
    patch("src.output.provenance.classify_source_type") not patch elsewhere
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
- New config fields go in Config dataclass in src/config/settings.py
- New CLI flags go in parse_args() in main.py and overrides dict in main()
- Agent system prompts go in prompts/ as .md files (D019). Task
  instruction prompts with inline string interpolation or tight parser
  coupling stay in source files.
- New agent types go in src/agent/<name>.py, mirroring existing agent files


## Config and environment

- .env is gitignored — never commit it
- ANTHROPIC_API_KEY and TAVILY_API_KEY are env vars only
- config.yaml holds runtime defaults; CLI flags override them; neither is secret
- Three-layer config hierarchy: hardcoded defaults -> config.yaml -> CLI flags
- source_classification in config.yaml extends the source type classifier
  with custom domains — see provenance.py classify_source_type() docstring
- max_workers default is 2 — safe for both Ollama and Anthropic
  Ollama safe ceiling: 2. Anthropic safe ceiling: 4+


## Key architectural notes

Provider abstraction:
  - LLMClient is the abstract base — AnthropicClient and OllamaClient implement it
  - LLMResponse is normalised: type="text" or type="tool_call"
  - build_llms() in llm/builder.py returns a 6-tuple:
    (orch_llm, synth_llm, orch_provider, orch_model, synth_provider, synth_model)
  - Mixed provider: orchestration and synthesis can use different backends per run

Agent layer:
  - Agent and AgentPool are frozen dataclasses in src/agent/base.py
  - Agent.chat() is the only place system= is injected — never call
    agent.llm.chat() directly from agent implementation code (D007, D017)
  - Agent.chat() silently discards any system= kwarg passed by the caller —
    self.system_prompt is always used (D017)
  - AgentPool has three fields: researcher, verifier, editor (Planner deferred
    to Phase E — D015)
  - AgentPool is required by Orchestrator — there is no fallback path
  - ResearchResult is returned by Researcher.research() and carries:
    question, answer, claims, sources, message_history,
    verification (str: "verified" | "refuted" | "unverified")

Search routing:
  - Controlled by module-level globals in tools.py set once via configure_search()
  - configure_search() is called at startup in main() before any research begins
  - Anthropic web search citations appear on TEXT blocks, not tool_result blocks
    This is non-obvious behaviour — documented in tools.py
  - Anthropic search model is configurable via config.anthropic_search_model
    Default: claude-haiku-4-5-20251001

Researcher Agent loop guards (src/agent/researcher.py):
  - Repeated query detection — seen_queries set prevents A->B->A->B oscillation
  - Tool-call-string detection — handles malformed LLM responses
  - Malformed tool input guard via _validate_tool_input() in tool_utils.py
  - Fallback synthesis — rescues questions that exhaust max iterations
  - accumulated_results enables fallback even when no clean answer was found

Parallel research:
  - Orchestrator.run_async() is the core async implementation
  - Orchestrator.run() is a synchronous wrapper for CLI use only
  - All async contexts (FastAPI, async tests) must call run_async() directly
  - asyncio.gather() always called with return_exceptions=True (D018)
  - After gather, exceptions are logged as warnings and skipped
  - max_workers=2 default — safe for Ollama (serialises internally)
  - Warning printed when Ollama + max_workers > 2
  - Verifier runs per-Researcher outside the semaphore concurrently
    with subsequent research questions

Output pipeline:
  - formatter.py: build_metadata(), convert_to_html(), convert_to_pdf()
  - HTML output is sanitised post-rendering via bleach.clean() with a tag
    allowlist — do not use html.escape() on report body (causes double-encoding
    in code blocks)
  - writer.py: save_report(), update_index()
  - update_index() uses fcntl.flock + NamedTemporaryFile + os.replace for
    concurrency-safe atomic writes
  - output/index.md.lock is created on every update_index() call and
    is gitignored — it is an operational artifact, not source or output
  - provenance.py: classify_source_type(), score_confidence(),
    extract_claims_from_answer(), build_claims_from_results(),
    annotate_report_lines(), write_provenance_file(), build_quality_metrics()
  - evidence/schema.py: EvidenceSource, EvidenceClaim, ProvenanceReport,
    ResearchResult TypedDicts
  - All output functions are independent of the research pipeline

Evidence and provenance pipeline:
  - Triggered in main() when --provenance file or --provenance graph
  - build_claims_from_results() calls extract_claims_from_answer() per question
  - extract_claims_from_answer() accepts verification: str from ResearchResult
    and maps: "verified" -> verified, "refuted" -> disputed, "unverified" ->
    unverified on each EvidenceClaim.verification_status
  - extract_claims_from_answer() uses synth_llm to extract atomic claims via LLM
  - classify_source_type() uses five layers: TLD patterns, stable patterns,
    hardcoded institutional list, custom config domains, LLM fallback
  - Nine source types: government, academic, news, reference, institutional,
    industry, video, forum, general
  - score_confidence() scores per claim based on source types and corroboration
  - annotate_report_lines() adds [N] markers to report and sets report_line on claims
  - write_provenance_file() writes .provenance.json alongside the report
  - provenance.py has no imports from agent/ or llm/ — llm_client passed as argument
  - disputed_claims in quality_metrics counts claims with verification_status="disputed"

Source classification maintenance:
  - Layer 3 hardcoded list in classify_source_type() — add only when a domain
    appears in 3+ runs misclassified and LLM fallback unavailable or incorrect
  - Custom domains go in config.yaml source_classification section
  - Never add domains speculatively — only on evidence of misclassification


## Current development phase

Phase D — Parallel Research Architecture: COMPLETE

  Part 1  COMPLETE — asyncio workers, --max-workers, worker failure handling
  Part 2  COMPLETE — multi-agent architecture
          unit tests passing — see test baseline at top of this file
          Pass 1 QA fixes: system prompt injection, gather exception handling,
            verifier outcome propagation, editor response validation,
            cross-run state reset
          Pass 2 QA fixes: Planner removed, inline fallback deleted,
            XSS sanitisation, configurable search model, atomic index write,
            verifier robustness
          Phase D Part 2 COMPLETE — see ISSUES.md for open items

## Open issues and known gaps

See ISSUES.md for the full issues log including all QA findings and
their status. grep "| Open |" ISSUES.md to list current open items.

No open issues. See ISSUES.md for full log.

Deferred to Phase I:
  I003 — agent/tools.py: module-level search globals block FastAPI
  I004 — agent/orchestrator.py: run() footgun in async contexts

Next — do not begin without explicit instruction:
  Pass 4 Group B fixes (see current prompt from Lead Architect)
  Phase C remaining output mode renderers (parallel workstream)
  Phase F partial — read_url, arxiv_search tools


## Agent architecture (Phase D Part 2 — COMPLETE)

Agent dataclass (src/agent/base.py — frozen=True):
  name: str                          # identifier
  role: str                          # human-readable description
  description: str                   # for future dynamic handoff routing
  llm: LLMClient                     # underlying provider
  system_prompt: str                 # passed as native provider system parameter
  tools: tuple = ()                  # immutable per-agent tool subset
  temperature: Optional[float] = None
  max_iterations: int = 5            # per-agent loop budget
  output_schema: Optional[type] = None

AgentPool dataclass (frozen=True):
  researcher: Agent    # Haiku, web_search, owns its agentic loop
  verifier: Agent      # Sonnet, web_search, runs per-Researcher in parallel
  editor: Agent        # configurable model (defaults to synthesis model), no tools
  # Planner deferred to Phase E (D015)

ResearchResult dataclass (src/evidence/schema.py):
  question: str
  answer: str
  claims: list          # list[EvidenceClaim]
  sources: list         # list[EvidenceSource]
  message_history: list[dict]
  verification: str = "unverified"   # "verified" | "refuted" | "unverified"

System prompts in prompts/ directory, loaded by agent builder.
See DECISIONS.md D003-D019 for full rationale.


## Roadmap summary

Phase A  Stability and quality                    COMPLETE
Phase B  Output options (markdown/HTML/PDF)       COMPLETE
Phase C  Evidence layer and output modes          LARGELY COMPLETE
Phase D  Parallel research + multi-agent          COMPLETE (Pass 3 QA in progress)
Phase E  Memory and persistent knowledge          PENDING
Phase F  Tools and sources (read_url priority)    PENDING
PKG      Packaging (Docker/pipx)                  PENDING
UI       Comprehensive web UI                     PENDING
Phase G  Provider optimisation                    PARTIAL
Phase H  Observability                            PENDING
Phase I  Interface                                PENDING
