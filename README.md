# Research Agent

An agentic research assistant that autonomously decomposes topics, searches the web,
reflects on gaps, synthesises structured reports, and generates machine-readable
provenance files with per-claim evidence chains.

Built as a learning project for agentic architecture patterns — with a strategic goal
of producing a genuinely usable research tool.

**Primary differentiator:** Every claim in every report is traceable to its sources,
confidence level, and verification status via a `.provenance.json` file — unique among
open-source research agents.

---

## Architecture

```
python main.py "your topic"
       │
       ▼
  Orchestrator.decompose()         — LLM breaks topic into sub-questions
       │
       ▼
  Orchestrator.run_async()         — parallel asyncio workers
       │  └── Researcher.research() per question
       │       ├── agentic loop + web search + citations
       │       └── Verifier.verify() — parallel claim verification
       │
       ▼
  Orchestrator.reflect()           — critic identifies gaps → researches them
       │
       ▼
  Synthesiser.synthesise()         — LLM writes structured report
       │
       ▼
  Editor.edit()                    — coherence pass on synthesised report
       │
       ▼
  build_claims_from_results()      — extract atomic claims + classify sources
       │
       ▼
  write_provenance_file()          — .provenance.json alongside report
       │
       ▼
  output/report.md + .provenance.json
```

---

## Agentic Patterns Demonstrated

| Pattern | Where |
|---|---|
| Planning | Orchestrator decomposes topic into sub-questions |
| Tool use | Agent calls web search, feeds results back into context |
| Agentic loop | Researcher Agent runs until answer found or max iterations reached |
| Parallel workers | asyncio fan-out for concurrent question research |
| Parallel verification | Verifier runs per-Researcher concurrently with subsequent questions |
| Reflection | Critic reviews completeness before synthesising |
| Coherence editing | Editor Agent reviews synthesised report for coherence defects |
| Fallback synthesis | Rescues questions that exhaust search iterations |
| Provider abstraction | Normalised LLM interface across Anthropic and Ollama |
| Model tiering | Cheaper model for orchestration, stronger for synthesis |
| Mixed provider | Ollama orchestration + Anthropic synthesis in one run |
| Evidence extraction | LLM extracts atomic claims from research answers |
| Claim verification | Verifier adjusts confidence on confirmed and refuted claims |
| Source classification | 9-type hybrid classifier with LLM fallback |
| Provenance file | Machine-readable per-claim evidence chain |
| Exponential backoff | Handles transient API failures gracefully |
| Three-layer config | Hardcoded defaults → config.yaml → CLI overrides |

---

## Requirements

- Python 3.11+
- Anthropic API key (for Anthropic provider and web search)
- Tavily API key (optional — free 1,000/month at app.tavily.com)
- Ollama (optional, for local inference)
- bleach (HTML sanitisation — installed via requirements.txt)
- pango (optional, for PDF export — `brew install pango` on macOS)

---

## Installation

### 1. Clone and set up environment

```bash
git clone <your-repo-url>
cd research-agent
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure API keys

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
TAVILY_API_KEY=tvly-your-key-here   # optional
```

Get your Anthropic API key from [console.anthropic.com](https://console.anthropic.com).
Get a free Tavily key at [app.tavily.com](https://app.tavily.com) — no credit card required.

---

## Usage

### Basic

```bash
python main.py "your research topic"
```

### With provenance file

```bash
python main.py "nuclear fusion energy" --provenance file
# Generates: output/nuclear_fusion_energy.md
#            output/nuclear_fusion_energy.provenance.json
```

### With provider selection

```bash
# Anthropic (default) — Haiku orchestration, Sonnet synthesis
python main.py "nuclear fusion energy"

# Ollama (local inference, free)
python main.py "nuclear fusion energy" -p ollama -m llama3.1

# Tavily search (free tier)
python main.py "nuclear fusion energy" --search-provider tavily

# Mixed — Ollama orchestration + Anthropic synthesis (best cost/quality balance)
python main.py "nuclear fusion energy" \
  --orchestration-provider ollama \
  --orchestration-model llama3.1 \
  --synthesis-provider anthropic \
  --synthesis-model claude-sonnet-4-6
```

### Fully free run

```bash
python main.py "nuclear fusion energy" \
  -p ollama -m llama3.1 \
  --search-provider tavily \
  --provenance file -s
```

### Maximum depth

```bash
python main.py "nuclear fusion energy" \
  --min-questions 6 --max-questions 8 \
  --max-iterations 5 \
  --max-workers 4 \
  --max-tokens-research 4096 \
  --max-tokens-synthesis 8192
```

### Resume an interrupted run

Every run generates a Run ID printed at completion. If a run is
interrupted, rerun with `--resume` to reuse the same Run ID:

```bash
python main.py "nuclear fusion energy" --resume abc123def456
```

Resume skips completed stages based on the checkpoint's current stage:
decompose is skipped from research onward, research is skipped from
reflect onward, and reflect is skipped from synthesise onward.

### Follow-up mode

Research the gaps identified in a prior run:

```bash
python main.py "nuclear fusion energy" --follow-up abc123def456
```

Follow-up mode loads the gap questions identified by the prior run's
reflection step and researches them directly, without decomposing the
topic again. Results are linked to the prior run in the knowledge graph
when `--knowledge-store kuzu` is active.

Note: `--follow-up` and `--resume` cannot be used together.

### All CLI options

```
positional arguments:
  topic                                     Research topic

optional arguments:
  -p, --provider {anthropic,ollama}         LLM provider for both tiers
  -m, --model MODEL                         Model override for both tiers
  --orchestration-provider {anthropic,ollama}
  --orchestration-model MODEL
  --synthesis-provider {anthropic,ollama}
  --synthesis-model MODEL
  --editor-provider {anthropic,ollama}      Editor LLM provider (default: synthesis provider)
  --search-provider {anthropic,tavily}      Search provider (default: anthropic)
  --min-questions N                         Minimum sub-questions (default: 4)
  --max-questions N                         Maximum sub-questions (default: 5)
  --max-iterations N                        Max search iterations per question (default: 5)
  --max-workers N                           Parallel research workers (default: 2)
  --max-tokens-research N                   Max tokens per research call (default: 2048)
  --max-tokens-synthesis N                  Max tokens for synthesis (default: 8192)
  -s, --short                               Executive summary only
  -f, --format {markdown,html,pdf}          Output format (default: markdown)
  --output-mode {report,report-evidence,    Output rendering mode
                 data,dashboard,slides,
                 matrix,academic,
                 bibliography,raw}
  --provenance {none,file,graph}            Provenance output (default: none)
  --config PATH                             Custom config file path
```

---

## Provenance File

Every research run can optionally generate a `.provenance.json` file alongside
the report with machine-readable evidence chains:

```json
{
  "report_file": "nuclear_fusion_energy.md",
  "generated": "2026-05-23T09:49:00+00:00",
  "quality_metrics": {
    "coverage": 0.87,
    "confidence": 0.81,
    "contradictions": 0,
    "verified_claims": 12,
    "unverified_claims": 3,
    "disputed_claims": 1
  },
  "claims": [
    {
      "id": 1,
      "report_line": 42,
      "claim": "NIF achieved ignition in December 2022",
      "confidence": 0.96,
      "verification_status": "verified",
      "evidence_type": "quantitative",
      "sources": [
        {
          "title": "DOE National Lab Makes History",
          "url": "https://energy.gov/...",
          "source_type": "government",
          "retrieved": "2026-05-23"
        }
      ],
      "contradictions": []
    }
  ]
}
```

Verification statuses: `verified`, `unverified`, `disputed`
Source types: `government`, `academic`, `news`, `reference`, `institutional`,
`industry`, `video`, `forum`, `general`

---

## Provenance Viewer

When `--provenance file` is active, the pipeline generates a self-contained
viewer file alongside the report and provenance JSON:

```
output/nuclear_fusion_energy.md
output/nuclear_fusion_energy.provenance.json
output/nuclear_fusion_energy.viewer.html
```

Open the `.viewer.html` file in any browser. No server required.
The viewer shows quality metrics, disputed claims highlighted, all claims
with sources and confidence scores, and links back to the report for
verified claims.

---

## Search Providers

| Provider | Cost | Free Limit | Notes |
|---|---|---|---|
| **Anthropic** (default) | $10/1,000 searches | None | Per-sentence citations |
| **Tavily** | Pay-as-you-go | 1,000/month | AI-optimised, #1 DeepResearch Bench |

> Web searches always use the configured search provider regardless of LLM provider.
> Ollama runs still require a search API.

> Note: Anthropic searches are retried on transient failures
> (up to 3 attempts per query). The displayed search count reflects
> billable API attempts, so an Anthropic run may show a higher count
> than an equivalent Tavily run for the same number of queries.

---

## Ollama Setup (Local Inference)

Ollama runs LLM orchestration and synthesis locally — no API key needed for LLM calls.

```bash
# Install from ollama.com, then:
ollama serve
ollama pull llama3.1
```

To store models on an external drive:
```bash
export OLLAMA_MODELS=/Volumes/YourDriveName/ollama-models  # add to ~/.zshrc
```

**Provider-specific worker limits:**
- `--max-workers 2` — safe for Ollama (serialises requests internally)
- `--max-workers 4` — safe for Anthropic (parallel API servers)

| Aspect | Anthropic (Sonnet) | Ollama (llama3.1) |
|---|---|---|
| Report depth | High | Moderate |
| Citation quality | Excellent | Good |
| Speed | Fast | Slower |
| LLM cost | ~$0.10–$1.00/run | Free |

---

## Configuration

```yaml
# config.yaml
provider: anthropic
anthropic_orchestration_model: claude-haiku-4-5-20251001
anthropic_synthesis_model: claude-sonnet-4-6
ollama_orchestration_model: llama3.1
ollama_synthesis_model: llama3.1
ollama_base_url: http://localhost:11434

# Mixed provider (optional)
# orchestration_provider: ollama
# synthesis_provider: anthropic

# Editor (optional — defaults to synthesis provider and model)
# editor_provider: anthropic
# anthropic_editor_model: claude-haiku-4-5-20251001
# ollama_editor_model: llama3.1

search_provider: anthropic    # anthropic | tavily
# tavily_api_key: tvly-...    # or TAVILY_API_KEY env var
# anthropic_search_model: claude-haiku-4-5-20251001

min_questions: 4
max_questions: 5
max_iterations: 5
max_workers: 2

max_tokens_research: 2048
max_tokens_synthesis: 8192

# Custom source classification (optional)
# source_classification:
#   academic: [mycustomjournal.org]
#   government: [specialagency.int]
```

Three-layer hierarchy: hardcoded defaults → `config.yaml` → CLI flags

---

## Project Structure

```
research-agent/
├── main.py                   # CLI entry point
├── config.yaml               # Configuration
├── prompts/                  # Agent system prompts
│   ├── researcher.md
│   ├── verifier.md
│   └── editor.md
├── src/
│   ├── agent/
│   │   ├── base.py           # Agent and AgentPool dataclasses
│   │   ├── orchestrator.py   # Research pipeline
│   │   ├── researcher.py     # Researcher Agent — owns agentic loop
│   │   ├── verifier.py       # Verifier Agent — parallel claim verification
│   │   ├── editor.py         # Editor Agent — coherence pass
│   │   ├── synthesiser.py    # Report generation
│   │   ├── tools.py          # Search routing
│   │   ├── tool_utils.py     # Shared tool input validation
│   │   └── builder.py        # Agent factory
│   ├── llm/
│   │   ├── base.py           # LLMClient + LLMResponse
│   │   ├── anthropic_client.py
│   │   ├── ollama_client.py
│   │   ├── retry.py
│   │   └── builder.py        # LLM factory
│   ├── config/
│   │   └── settings.py
│   ├── evidence/
│   │   └── schema.py         # TypedDicts for provenance + ResearchResult
│   └── output/
│       ├── formatter.py      # HTML, PDF rendering
│       ├── writer.py         # File saving, index
│       └── provenance.py     # Claim extraction, classification
└── tests/                    # See CLAUDE.md for current test count
```

---

## Running Tests

```bash
# Unit tests (no API calls required)
pytest tests/ -m "not integration" -v

# Free integration tests (Ollama + Tavily)
pytest tests/test_integration_smoke.py -m "ollama" -v

# Anthropic integration tests (costs money)
pytest tests/test_integration_smoke.py -m "anthropic_integration" -v
```

Current test count: See CLAUDE.md for current test count.

---

## Eval Harness

Record pipeline quality metrics after each phase to track improvement over time.
Results saved to `output/.eval/eval_results.jsonl`.

Baseline run (Anthropic — full quality). Use at phase boundaries and for periodic resets:

```bash
python main.py "nuclear fusion energy" \
  --orchestration-provider anthropic \
  --orchestration-model claude-haiku-4-5-20251001 \
  --synthesis-provider anthropic \
  --synthesis-model claude-sonnet-4-6 \
  --search-provider anthropic \
  --eval-phase "Phase E" \
  --provenance file \
  --max-workers 4
```

Routine run (Ollama + Tavily — free). Use after every phase:

```bash
python main.py "nuclear fusion energy" \
  -p ollama -m llama3.1 \
  --search-provider tavily \
  --eval-phase "Phase E" \
  --provenance file
```

Run all three reference topics then compare two phases:

```bash
python main.py --eval-compare "Phase D" "Phase E"
```

Reference topics:
- `"nuclear fusion energy"`
- `"electrosmith daisy seed"`
- `"large language model training"`

Metrics tracked: report length, claim count, verification distribution
(verified/disputed/unverified), report_line coverage, average confidence,
search count, duration.

Note: `--eval-phase` requires `--provenance file` to be active.

---

## API Costs

| Component | Cost |
|---|---|
| Anthropic web search | $10 / 1,000 searches |
| Tavily search | Free up to 1,000/month |
| Haiku orchestration | $1.00 / 1M input, $5.00 / 1M output |
| Sonnet synthesis | $3.00 / 1M input, $15.00 / 1M output |
| Typical run (Anthropic search) | ~$0.05–$0.15 |
| Maximum depth run | ~$0.50–$1.00 |
| Ollama + Tavily run | ~$0 (within free tier) |

---

## Roadmap

### Complete ✅
- **Phase A** — Stability, provider abstraction, model tiering, retry, citations
- **Phase B** — Output options: metadata, --short, HTML, PDF, index
- **Phase C** — Evidence layer: atomic claims, confidence scoring, source classification (9 types), provenance file pipeline
- **Phase D** — Parallel research + multi-agent: Researcher, Verifier, Editor agents, parallel workers, claim verification
- **Phase E (partial)** — Tavily search provider
- **Phase G.1** — Mixed provider support

### In Progress 🔄
- **Phase D QA Pass 3** — correctness and robustness fixes from Adversarial QA

### Next
- **Phase C remaining** — Output mode renderers (dashboard, matrix, academic, bibliography, raw)
- **Phase F partial** — read_url, arxiv_search tools
- **Packaging** — Dockerfile, pipx, preset configs
- **Phase E** — Knowledge store (Kuzu), persistence, follow-up mode
- **Web UI** — Full interface exposing all features + provenance explorer (after Phase E)
- **Phase F remaining** — SearXNG, pdf_reader, youtube_transcript, browser
- **Phase H** — Observability: cost tracking, structured logging
- **Phase I** — REST API, webhooks

---

## Notes

- Reports saved to `output/` — add to `.gitignore` if topics are sensitive
- Running the agent creates `output/index.md.lock` — an operational artifact used for concurrency-safe index writes. It is gitignored and can be safely ignored.
- Haiku handles orchestration (fast, cheap); Sonnet handles synthesis (quality)
- Verifier runs in parallel with subsequent research questions — no serial latency penalty
- Ollama tool calling: `llama3.1` more reliable than `llama3.2`
- See `PROJECT_CONTEXT.md` for full architectural context
- See `DECISIONS.md` for all architectural decision rationale

---

## Licence

MIT
