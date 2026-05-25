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

**Built as a learning project for agentic architecture patterns.**

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
├── src/
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── orchestrator.py   # Decompose, research loop, reflect
│   │   ├── synthesiser.py    # Report generation (full / short modes)
│   │   └── tools.py          # Tool definitions + Anthropic/Tavily search
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

## Architecture — How It Works

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
  Orchestrator.run()                — researches all questions
       │  ├── research_question()   — agentic loop per question
       │  │   ├── LLM tool call → web_search
       │  │   ├── execute_tool_with_sources() → Anthropic or Tavily
       │  │   ├── repeated query detection → synthesis forced
       │  │   └── fallback synthesis if max iterations reached
       │  └── reflect() → identifies gaps → researches gaps
       │
       ▼
  Synthesiser.synthesise()          — LLM writes structured report
       │
       ▼
  build_claims_from_results()       — extract atomic claims via LLM
       │  ├── extract_claims_from_answer() per question
       │  ├── classify_source_type() — 9-type hybrid classifier
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

### 4. Search Provider Abstraction
`configure_search()` called once at startup. Routes to:
- `_anthropic_search_with_sources()` — citations on text blocks (not tool_result)
- `_tavily_search_with_sources()` — per-result citations

### 5. Agentic Loop Guards
- Repeated query detection — injects synthesis prompt instead of re-searching
- Tool-call-string detection — handles malformed LLM responses
- Fallback synthesis — rescues questions that hit max_iterations

### 6. Evidence & Provenance Pipeline
- `EvidenceClaim` TypedDict — JSON-serialisable, no Pydantic overhead
- `classify_source_type()` — 5-layer hybrid: TLD patterns → stable patterns →
  hardcoded institutional → custom config → LLM fallback
- 9 source types: government, academic, news, reference, institutional,
  industry, video, forum, general
- Confidence scoring: base 0.4 + per-source-type increments + corroboration bonus
- `annotate_report_lines()` — substring matching for [N] inline markers
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
max_workers: 4                # parallel research workers (Phase D)

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
--min-questions N     # default: 4
--max-questions N     # default: 5
--max-iterations N    # default: 5
--max-workers N       # default: 4 (parallel workers)
--max-tokens-research N
--max-tokens-synthesis N

# Output
-s, --short           # executive summary
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
pytest tests/ -m "not integration" -v     # 295 passing

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

### Source Classifier Maintenance
Layer 3 hardcoded list in `classify_source_type()`:
- Add only when domain appears in 3+ runs misclassified
- Never add speculatively
- Custom domains go in `config.yaml` source_classification

### Provenance Pipeline
- `provenance.py` has no imports from `agent/` or `llm/`
- `llm_client` is passed as argument to `extract_claims_from_answer()`
- `annotate_report_lines()` uses simple substring matching — sparse results
  expected until Phase D synthesiser integration

---

## Completed Phases

### Phase A — Stability & Quality ✅
Provider abstraction, model tiering, retry, config, message history fix,
reflection, citations, repeated query + fallback synthesis.

### Phase B — Output Options ✅
Metadata table, --short, --format (markdown/html/pdf), output/index.md.

### Phase C — Evidence Layer ✅ (largely)
Evidence schema (TypedDict), provenance file pipeline, --provenance flag,
atomic claim extraction, confidence scoring, report line tracking,
hybrid source classifier (5 layers), 9-type source taxonomy,
source deduplication, --output-mode flag stub.
Pending: output mode renderers (dashboard, matrix, academic, bibliography, raw).

### Phase E (Tavily) ✅
configure_search(), Anthropic + Tavily routing, --search-provider flag.

### Phase G.1 ✅
Mixed provider support, --orchestration-provider / --synthesis-provider,
build_llms() returns 6-tuple.

---

## Pending Phases

### Phase D — Parallel Research Architecture (IN PROGRESS)
**Part 1 (in progress):** asyncio workers, --max-workers flag, configurable
parallelism, worker failure handling. Target: 194s → ~50s.

**Part 2 (pending):**
- Independent verifier agent (separate model, not self-critique)
- Dedicated planner agent
- Fact-checker agent
- Editor agent
- Synthesiser integration for report line tracking

### Phase E — Memory & Persistent Knowledge
KnowledgeStore abstraction (Kuzu default, SQLite fallback, Memory for tests),
retrieval cache, cross-run accumulation, follow-up mode (--follow-up),
--provenance graph mode.

### Phase F — Tools & Sources
SearXNG, Brave Search, read_url, arxiv_search, pdf_reader,
youtube_transcript, file_reader, browser tool.

### Phase G — Provider Optimisation (remaining)
Provider-specific prompts, simple_questions flag, system prompt support,
Ollama model registry.

### Phase H — Observability
Structured logging, cost tracking, run replay, confidence threshold,
streaming output.

### Phase I — Interface
FastAPI + frontend, SSE streaming, report library, interactive provenance
viewer, REST API, webhooks.

---

## North Star

Every claim in every report traceable to sources, confidence, verification
status, and contradiction history. Two delivery modes:

1. **Report mode** — clean prose with [N] footnote markers and ⚠️ disputed flags
2. **Provenance file** — `.provenance.json` with line references, quality metrics,
   full evidence chain per claim

```json
{
  "report_file": "nuclear_fusion_energy.md",
  "generated": "2026-05-23T09:49:00",
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
```

---

## Example Commands

```bash
# Standard run
python main.py "nuclear fusion energy"

# Maximum depth
python main.py "nuclear fusion energy" \
  --min-questions 6 --max-questions 8 \
  --max-iterations 5 \
  --max-tokens-research 4096 \
  --max-tokens-synthesis 8192

# Free run (Ollama + Tavily)
python main.py "nuclear fusion energy" \
  -p ollama -m llama3.1 \
  --search-provider tavily \
  --provenance file -s

# Mixed provider
python main.py "nuclear fusion energy" \
  --orchestration-provider ollama \
  --orchestration-model llama3.1 \
  --synthesis-provider anthropic \
  --synthesis-model claude-sonnet-4-6

# With provenance
python main.py "nuclear fusion energy" --provenance file

# Run tests
pytest tests/ -m "not integration" -v
```

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

## Known Issues & Observations

- Comparative questions harder for llama3.1 — hits max iterations more often
- Llama3.1 synthesis shallower than Sonnet — report depth is model-dependent
- Fallback synthesis rescues questions but produces shorter answers
- Anthropic web searches cost $0.01 each regardless of LLM provider
- Tavily citations are per-result not per-sentence — less granular
- Reflection uses same model as research — Phase D independent verifier fixes this
- report_line mostly null — Phase D synthesiser integration fixes this
- Sequential research loop — Phase D Part 1 in progress
