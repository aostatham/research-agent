# Research Agent — Project Context Document

## Purpose
This document serves two purposes:
1. Context handoff when starting a new conversation
2. Briefing document for Claude Code to enable informed coding contributions

---

## Project Overview

A from-scratch agentic research pipeline built in Python. Given a topic, the agent
autonomously decomposes it into sub-questions, searches the web, reflects on gaps,
synthesises a structured report, and generates a machine-readable provenance file
with per-claim evidence chains.

**Strategic goal:** Build a genuinely usable tool while learning agentic architecture patterns.
**Primary differentiator:** Machine-readable provenance file with per-claim source typing,
confidence scoring, and evidence chains — unique among open-source research agents.

## User Stories

Three user stories in priority order. Primary drives all
prioritisation decisions. See DECISIONS.md M006 for full rationale.

**Primary — Policy Analyst**
A policy analyst building a briefing document from public sources
wants a structured report with traceable evidence chains so they can
defend every claim if challenged.

**Secondary — Journalist**
A journalist fact-checking claims in a press release or public
statement wants a structured research brief with flagged disputed
claims and source citations, produced in under five minutes.

**Tertiary — Developer/Researcher**
A developer or technical researcher evaluating an unfamiliar
technology wants a comprehensive report covering specifications,
comparisons, limitations, and community maturity in a single run.

**Developer:** Andrew (experienced developer, learning Python specifically)
**Repository:** https://github.com/aostatham/research-agent

---

## Technology Stack

- Python 3.11
- Anthropic SDK (Claude Haiku for orchestration, Sonnet for synthesis)
- Ollama (llama3.1 for local inference)
- Anthropic web search tool (citations included)
- Tavily search API (free 1,000/month)
- weasyprint (PDF export)
- pytest + pytest-mock
- PyYAML, python-dotenv, requests, markdown, tavily-python

---

## Project Structure

```
research-agent/
├── main.py                   # Thin CLI entry point only
├── config.yaml               # Project configuration
├── .env                      # API keys (never commit)
├── .gitignore
├── requirements.txt
├── pytest.ini
├── README.md
├── CLAUDE.md                 # Claude Code briefing
├── DECISIONS.md              # Architectural decision log
├── PROJECT_CONTEXT.md        # This file
├── prompts/                  # Agent system prompts (versioned in git)
├── src/
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── orchestrator.py   # Decompose, research loop, reflect
│   │   ├── synthesiser.py    # Report generation (full / short modes)
│   │   ├── tools.py          # Tool definitions + Anthropic/Tavily search
│   │   └── builder.py        # build_agent(), build_agents(), AgentPool
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py           # Abstract LLMClient + LLMResponse
│   │   ├── anthropic_client.py
│   │   ├── ollama_client.py
│   │   ├── retry.py          # Exponential backoff decorator
│   │   └── builder.py        # build_client(), build_llms() factory
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py       # Config dataclass + three-layer loader
│   ├── evidence/
│   │   ├── __init__.py
│   │   └── schema.py         # EvidenceSource, EvidenceClaim, ProvenanceReport
│   └── output/
│       ├── __init__.py
│       ├── formatter.py      # build_metadata(), convert_to_html(), convert_to_pdf()
│       ├── writer.py         # save_report(), update_index()
│       └── provenance.py     # classify_source_type(), score_confidence(),
│                             # extract_claims_from_answer(),
│                             # build_claims_from_results(),
│                             # annotate_report_lines(),
│                             # write_provenance_file(),
│                             # build_quality_metrics()
├── tests/
│   ├── test_base.py
│   ├── test_anthropic_client.py
│   ├── test_ollama_client.py
│   ├── test_provider_swap.py
│   ├── test_retry.py
│   ├── test_config.py
│   ├── test_orchestrator.py
│   ├── test_synthesiser.py
│   ├── test_cli.py
│   ├── test_tools.py
│   ├── test_provenance.py
│   └── test_integration_smoke.py
└── output/                   # Generated reports (git-ignored)
```

---

## Architecture — Current State

```
python main.py "your topic"
       │
       ▼
  parse_args() + load_config()      — three-layer config hierarchy
       │
       ▼
  configure_search()                — sets search provider once at startup
       │
       ▼
  build_llms(config)                — returns 6-tuple, supports mixed providers
       │
       ▼
  Orchestrator.decompose()          — LLM breaks topic into 4-8 sub-questions
       │
       ▼
  Orchestrator.run()                — sync wrapper → asyncio.run(run_async())
       │
       ▼
  Orchestrator.run_async()          — parallel asyncio workers
       │  ├── research_all_async()  — max_workers concurrent questions
       │  │   └── research_question_async() per question
       │  │       └── _research_question_sync() — agentic loop
       │  │           ├── LLM tool call → web_search
       │  │           ├── execute_tool_with_sources() → Anthropic or Tavily
       │  │           ├── seen_queries set — cyclic query detection
       │  │           └── fallback synthesis if max iterations reached
       │  └── reflect() → gaps → research_all_async(gaps)
       │
       ▼
  Synthesiser.synthesise()          — LLM writes structured report
       │
       ▼
  build_claims_from_results()       — extract atomic claims via LLM
       │  ├── extract_claims_from_answer() per question
       │  ├── classify_source_type() — 9-type hybrid classifier (5 layers)
       │  └── score_confidence() — source quality heuristic
       │
       ▼
  annotate_report_lines()           — add [N] markers to report
       │
       ▼
  write_provenance_file()           — .provenance.json alongside report
       │
       ▼
  save_report() + update_index()    — .md / .html / .pdf + index entry
  output/index.md.lock              — operational artifact created by fcntl.flock
                                       in writer.py; gitignored; safe to ignore (see D022)
```

---

## Key Design Patterns

### 1. LLM Provider Abstraction
All LLM calls go through `LLMClient` abstract base class.
`LLMResponse` is normalised: `type="text"` or `type="tool_call"`.
`build_llms()` in `llm/builder.py` returns a 6-tuple:
`(orch_llm, synth_llm, orch_provider, orch_model, synth_provider, synth_model)`

Mixed provider: `--orchestration-provider ollama --synthesis-provider anthropic`
enables free local orchestration with quality Sonnet synthesis.

### 2. Three-Layer Config
```
CLI flags              ← highest priority
      ↓
config.yaml            ← project defaults
      ↓
Config dataclass       ← hardcoded fallback
```

### 3. Model Tiering
- Orchestration: `claude-haiku-4-5-20251001` (fast, cheap)
- Synthesis: `claude-sonnet-4-6` (quality)

### 4. Parallel Research
- `run_async()` is the core — single event loop across entire pipeline
- `run()` is a synchronous CLI wrapper only — do not call from async contexts
- `max_workers=2` default — safe for Ollama (serialises internally)
- Warning printed when Ollama + max_workers > 2

### 5. Search Provider Abstraction
`configure_search()` called once at startup. Routes to:
- `_anthropic_search_with_sources()` — citations on text blocks (not tool_result)
- `_tavily_search_with_sources()` — per-result citations

### 6. Agentic Loop Guards
- `seen_queries: set` — prevents A→B→A→B oscillation (not just consecutive)
- Tool-call-string detection — handles malformed LLM responses
- Fallback synthesis — rescues questions that hit max_iterations

### 7. Evidence & Provenance Pipeline
- `EvidenceClaim` TypedDict — JSON-serialisable, no Pydantic overhead
- `classify_source_type()` — 5-layer hybrid: TLD → stable patterns →
  hardcoded institutional → custom config → LLM fallback
- 9 source types: government, academic, news, reference, institutional,
  industry, video, forum, general
- Confidence scoring: base 0.4 + per-source-type increments + corroboration bonus
- `annotate_report_lines()` — prose-only substring matching for [N] markers
- Provenance output: `topic.provenance.json` alongside `topic.md`

---

## Config Reference

```yaml
# LLM Provider
provider: anthropic
anthropic_orchestration_model: claude-haiku-4-5-20251001
anthropic_synthesis_model: claude-sonnet-4-6
ollama_orchestration_model: llama3.1
ollama_synthesis_model: llama3.1
ollama_base_url: http://localhost:11434

# Mixed provider overrides
orchestration_provider: null
synthesis_provider: null

# Search
search_provider: anthropic    # anthropic | tavily
tavily_api_key: null          # or TAVILY_API_KEY env var
tavily_max_results: 5

# Research behaviour
min_questions: 4
max_questions: 5
max_iterations: 5
max_workers: 2                # default 2 — safe for Ollama and Anthropic
                              # Ollama ceiling: 2, Anthropic ceiling: 4+

# Token limits
max_tokens_research: 2048
max_tokens_synthesis: 8192

# Output
output_mode: report           # report | report-evidence | data | dashboard |
                              # slides | matrix | academic | bibliography | raw
provenance: none              # none | file | graph

# Retry
retry_max_attempts: 3
retry_base_delay: 1.0
retry_max_delay: 30.0

# Custom source classification
# source_classification:
#   academic: [mycustomjournal.org]
#   government: [specialagency.int]
```

---

## CLI Reference

```bash
python main.py "topic" [options]

# Provider
-p, --provider {anthropic,ollama}
-m, --model MODEL
--orchestration-provider {anthropic,ollama}
--orchestration-model MODEL
--synthesis-provider {anthropic,ollama}
--synthesis-model MODEL

# Search
--search-provider {anthropic,tavily}

# Research depth
--min-questions N         # default: 4
--max-questions N         # default: 5
--max-iterations N        # default: 5
--max-workers N           # default: 2 (Ollama safe ceiling: 2, Anthropic: 4+)
--max-tokens-research N
--max-tokens-synthesis N

# Output
-s, --short               # executive summary
-f, --format {markdown,html,pdf}
--output-mode {report,report-evidence,data,dashboard,slides,
               matrix,academic,bibliography,raw}
--provenance {none,file,graph}

--config PATH
```

---

## Test Structure

```bash
# Unit tests (always free, no API calls)
pytest tests/ -m "not integration" -v     # See CLAUDE.md for current test count

# Free integration tests (Ollama + Tavily)
pytest tests/test_integration_smoke.py -m "ollama" -v

# Anthropic integration tests (costs money)
pytest tests/test_integration_smoke.py -m "anthropic_integration" -v
```

Test markers: `integration`, `ollama`, `anthropic_integration`

---

## Important Implementation Notes

### Web Search
`execute_tool_with_sources()` always calls the configured search provider
regardless of LLM provider. Ollama runs still cost $0.01/search (Anthropic)
or use Tavily free tier.

### Anthropic Citations
Citations appear on **text blocks** not tool_result blocks. Getting this wrong
produces empty citation lists despite searches succeeding.

### Message History
Manually constructed as list of dicts. After a tool call:
1. Assistant: "I will search for: {query}"
2. User: search results + "Do not call any tools. Write your answer directly."
The forceful instruction is critical — without it smaller models loop.

### asyncio Pattern
`run_async()` is the core — use this from async contexts.
`run()` is a synchronous CLI wrapper only. Never call `run()` from an
async context — it calls `asyncio.run()` which raises RuntimeError inside
an already-running event loop.

### CLI Model Override (H1 fix)
`args.orchestration_model` sets ONLY the field matching the resolved provider.
Does NOT set both `anthropic_orchestration_model` and `ollama_orchestration_model`.
Prevents silent config corruption when using tier-specific overrides.

### Source Classifier Maintenance
Layer 3 hardcoded list in `classify_source_type()`:
- Add only when domain appears in 3+ runs misclassified
- Never add speculatively
- Custom domains go in `config.yaml` source_classification

### Provenance Pipeline
- `provenance.py` has no imports from `agent/` or `llm/`
- `llm_client` is passed as argument to `extract_claims_from_answer()`
- `annotate_report_lines()` only annotates prose — skips References section
- `report_line` mostly null until Phase D synthesiser integration

---

## Current Status

### Completed
- Phase A — Stability and quality
- Phase B — Output options (markdown/HTML/PDF)
- Phase C — Evidence layer (pending: output mode renderers)
- Phase D Part 1 — Parallel asyncio workers
- Phase D Part 2 — Multi-agent architecture (423 → 528 across QA passes)
- Phase E partial (Tavily)
- Phase G.1 (mixed provider)

### Phase D Part 2 — what was built
- Agent and AgentPool dataclasses (src/agent/base.py)
- Agent system prompts (prompts/)
- Agent builder with prompt loading (src/agent/builder.py)
- ResearchResult replaces (answer, sources) tuple (src/evidence/schema.py)
- System prompt routing on LLMClient (src/llm/)
- Researcher Agent owns the agentic loop (src/agent/researcher.py)
- Parallel Verifier after each Researcher (src/agent/verifier.py)
- Editor Agent after synthesis (src/agent/editor.py)
- Editor config fields (src/config/settings.py, config.yaml)
- QA fixes: system prompt injection, gather exception handling,
  verifier outcome propagation, editor response validation,
  cross-run state reset

### Known issues carried forward to Pass 2
- H2: Planner Agent never called — to be resolved by removal (D015)
- M5: Inline researcher fallback has diverged — to be removed (D016)
- H7: XSS in HTML/PDF formatter
- M8: Index file write not concurrency-safe
- M9: Search uses hardcoded model name
- M3, M4, M6, M7: Verifier robustness gaps

### Revised priority order (post Principal Reviewer strategic review)

1. Pass 5 Group B fixes — in progress
2. Final Pass 5 QA — if clean, Phase D marked complete
3. report_line wired through synthesis
4. HTML provenance viewer
5. RunState durable execution (D027) — Phase E pre-requisite
6. Observability hooks (src/observability/events.py)
7. Phase C output renderers (parallel, low risk)
8. Phase E — knowledge store, Graph Verifier, Analyst Agent (after
   items 1-6 complete)
9. Phase F partial — read_url, arxiv_search
10. Packaging — Dockerfile, pipx
11. Phase F remaining — SearXNG, pdf_reader, youtube_transcript,
    browser
12. Phase G remaining — provider optimisation
13. Phase H — observability (formalise hooks added in item 6)
14. Phase I — REST API, webhooks
15. Web UI — full interface (after Phase E)

User story drives prioritisation: Primary B (analyst) → items 3, 4.
Secondary A (journalist) → items 3, 4 disputed claims display.
Tertiary C (developer) → items 9, 7.

---

## Four-Collaborator Development Process

| Role | Collaborator | Trigger |
|---|---|---|
| Product Owner | Andrew | Always |
| Lead Architect | Sonnet 4.6 (main conversation) | Always |
| Principal Reviewer | Opus 4.7 Session 1 | Phase boundaries, design reviews |
| QA / Adversarial | Opus 4.7 Session 2 | Phase completion, pre-release |
| Implementation | Claude Code | Always |

Opus 4.7 Session 1 brief: architecture and current practice review
Opus 4.7 Session 2 brief: adversarial — find what's wrong, no context given

---

## North Star

Every claim in every report traceable to sources, confidence, verification
status, and contradiction history. Two delivery modes:

1. **Report mode** — clean prose with [N] footnote markers and ⚠️ disputed flags
2. **Provenance file** — `.provenance.json` with line references, quality metrics,
   full evidence chain per claim

---

## API Costs

| Component | Cost |
|---|---|
| Anthropic web search | $10 / 1,000 searches |
| Tavily search | Free up to 1,000/month |
| Haiku orchestration | $1.00 / 1M input, $5.00 / 1M output |
| Sonnet synthesis | $3.00 / 1M input, $15.00 / 1M output |
| Typical default run | ~$0.05–$0.15 |
| Maximum depth run | ~$0.50–$1.00 |
| Ollama + Tavily run | ~$0 (within free tier) |

---

## Known Issues

See ISSUES.md for the full issues log.
grep "| Open |" ISSUES.md to list current open items.

No open issues at close of Phase D.
Deferred to Phase I: I003 (search globals), I004 (run() footgun)
