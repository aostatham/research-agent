# Research Agent

An agentic research assistant that autonomously decomposes topics, searches the web, reflects on gaps, and synthesises structured markdown reports with citations.

Built as a learning project for agentic architecture patterns using the Anthropic API.

---

## Architecture

```
python main.py "your topic"
       │
       ▼
  Orchestrator.decompose()         — LLM breaks topic into sub-questions
       │
       ▼
  Orchestrator.research_question() — agentic loop per question
       │  └── tool calls → execute_tool_with_sources() → web search + citations
       │
       ▼
  Orchestrator.reflect()           — critic LLM checks for gaps
       │
       ▼
  Synthesiser.synthesise()         — LLM writes structured report
       │
       ▼
  output/report.md                 — markdown report with References section
```

---

## Agentic Patterns Demonstrated

| Pattern | Where |
|---|---|
| Planning | Orchestrator decomposes topic into sub-questions |
| Tool use | Agent calls web search, feeds results back into context |
| Agentic loop | Runs until answer found or max iterations reached |
| Reflection | Critic reviews research completeness before synthesising |
| Fallback synthesis | Rescues questions that exhaust search iterations |
| Provider abstraction | Normalised LLM interface across Anthropic and Ollama |
| Model tiering | Cheaper model for orchestration, stronger for synthesis |
| Mixed provider | Ollama orchestration + Anthropic synthesis in one run |
| Exponential backoff | Handles transient API failures gracefully |
| Three-layer config | Hardcoded defaults → config.yaml → CLI overrides |

---

## Requirements

- Python 3.11+
- Anthropic API key (for Anthropic provider and web search)
- Tavily API key (optional — free 1,000/month at app.tavily.com)
- Ollama (optional, for local inference)

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
New accounts receive approximately $5 in free trial credits.

Get a free Tavily key at [app.tavily.com](https://app.tavily.com) — no credit card required.

---

## Usage

### Basic

```bash
python main.py "your research topic"
```

### With provider selection

```bash
# Anthropic (default) — Haiku orchestration, Sonnet synthesis
python main.py "nuclear fusion energy"

# Ollama (local inference)
python main.py "nuclear fusion energy" -p ollama -m llama3.1

# Tavily search instead of Anthropic search
python main.py "nuclear fusion energy" --search-provider tavily
```

### Mixed provider — Ollama orchestration + Anthropic synthesis

```bash
python main.py "nuclear fusion energy" \
  --orchestration-provider ollama \
  --orchestration-model llama3.1 \
  --synthesis-provider anthropic \
  --synthesis-model claude-sonnet-4-6
```

### Maximum depth — Anthropic

```bash
python main.py "the current state of nuclear fusion energy" \
  --provider anthropic \
  --min-questions 6 \
  --max-questions 8 \
  --max-iterations 5 \
  --max-tokens-research 4096 \
  --max-tokens-synthesis 8192
```

### Maximum depth — Ollama

```bash
python main.py "the current state of nuclear fusion energy" \
  --provider ollama \
  --model llama3.1 \
  --min-questions 6 \
  --max-questions 8 \
  --max-iterations 5 \
  --max-tokens-research 4096 \
  --max-tokens-synthesis 8192
```

### All CLI options

```
positional arguments:
  topic                                   Research topic

optional arguments:
  -p, --provider {anthropic,ollama}       LLM provider for both tiers
  -m, --model MODEL                       Model override for both tiers
  --orchestration-provider {anthropic,ollama}
  --orchestration-model MODEL
  --synthesis-provider {anthropic,ollama}
  --synthesis-model MODEL
  --search-provider {anthropic,tavily}    Search provider (default: anthropic)
  --min-questions N                       Minimum sub-questions (default: 4)
  --max-questions N                       Maximum sub-questions (default: 5)
  --max-iterations N                      Max search iterations per question (default: 5)
  --max-tokens-research N                 Max tokens per research call (default: 2048)
  --max-tokens-synthesis N                Max tokens for synthesis (default: 8192)
  -s, --short                             Executive summary only
  -f, --format {markdown,html}            Output format (default: markdown)
  --config PATH                           Custom config file path
```

Reports are saved to `output/<topic>.md` or `output/<topic>.html`.

---

## Example Output

```
🔬 Research Agent
──────────────────────────────────────────────────
Topic:              the current state of nuclear fusion energy
Orch provider:      anthropic / claude-haiku-4-5-20251001
Synth provider:     anthropic / claude-sonnet-4-6
Search provider:    anthropic
Questions:          4–5
──────────────────────────────────────────────────

📋 Decomposing topic: 'the current state of nuclear fusion energy'
  1. What recent technological breakthroughs have advanced fusion?
  2. What are the current engineering challenges?
  3. Which organisations are leading development?
  4. What are the economic and regulatory considerations?

🔍 Researching: 'What recent technological breakthroughs...'
  🌐 Searching: 'nuclear fusion breakthroughs 2025 2026'
  ✅ Answer found (1842 chars)

...

🤔 Reflecting on research completeness...
  ✅ Research is sufficient

📝 Synthesising report...
  ✅ Report generated (8203 chars)

──────────────────────────────────────────────────
✅ Done — report saved to output/the_current_state_of_nuclear_fusion_energy.md
   Questions: 16  Searches: 63  Search provider: anthropic  Time: 455.8s
──────────────────────────────────────────────────
```

---

## Search Providers

| Provider | Cost | Free Limit | Notes |
|---|---|---|---|
| **Anthropic** (default) | $10/1,000 searches | None | Native citations, highest quality |
| **Tavily** | Pay-as-you-go | 1,000/month | Designed for AI agents, #1 DeepResearch Bench |

Configure in `config.yaml` or per-run with `--search-provider`:

```yaml
search_provider: tavily
# tavily_api_key: tvly-...  # or set TAVILY_API_KEY in .env
```

> **Note:** Web searches always use the configured search provider regardless of which LLM provider handles orchestration. Ollama runs still use Anthropic or Tavily for web search.

---

## Ollama Setup (Local Inference)

Ollama lets you run models locally — no API key needed for LLM inference.

### Install

Download and install from [ollama.com](https://ollama.com). On macOS, the desktop app is recommended.

### Start the server

```bash
ollama serve
```

### Pull a model

Tool calling support is required:

```bash
# Recommended — good tool calling support
ollama pull llama3.1

# Lighter weight option
ollama pull llama3.2
```

### Configure model storage (optional)

To store models on an external drive, add to `~/.zshrc`:

```bash
export OLLAMA_MODELS=/Volumes/YourDriveName/ollama-models
```

Then reload: `source ~/.zshrc`

### Ollama vs Anthropic quality

| Aspect | Anthropic (Sonnet) | Ollama (llama3.1) |
|---|---|---|
| Report depth | High | Moderate |
| Citation quality | Excellent | Good |
| Synthesis quality | Excellent | Moderate |
| Comparative questions | Handles well | May need fallback |
| Speed | Fast | Slower |
| LLM cost | ~$0.10–$1.00/run | Free (local compute) |

**Best of both worlds:** Use `--orchestration-provider ollama --synthesis-provider anthropic` for free orchestration with high-quality Sonnet synthesis.

---

## Configuration

All settings have hardcoded defaults, can be overridden in `config.yaml`, and further overridden per-run via CLI flags.

### config.yaml

```yaml
# LLM Provider
provider: anthropic

# Anthropic model tiering
anthropic_orchestration_model: claude-haiku-4-5-20251001
anthropic_synthesis_model: claude-sonnet-4-6

# Ollama model tiering
ollama_orchestration_model: llama3.1
ollama_synthesis_model: llama3.1
ollama_base_url: http://localhost:11434

# Mixed provider (optional — overrides provider for specific tiers)
# orchestration_provider: ollama
# synthesis_provider: anthropic

# Search provider
search_provider: anthropic   # anthropic | tavily
# tavily_api_key: tvly-...   # or set TAVILY_API_KEY in .env
# tavily_max_results: 5

# Research behaviour
min_questions: 4
max_questions: 5
max_iterations: 5

# Token limits
max_tokens_research: 2048
max_tokens_synthesis: 8192

# Retry behaviour
retry_max_attempts: 3
retry_base_delay: 1.0
retry_max_delay: 30.0
```

### Three-layer config hierarchy

```
CLI flags              ← highest priority
      ↓ overrides
config.yaml            ← project defaults
      ↓ overrides
hardcoded defaults     ← fallback
```

---

## Project Structure

```
research-agent/
├── main.py                   # CLI entry point
├── config.yaml               # Project configuration
├── .env                      # API keys (never commit)
├── .gitignore
├── requirements.txt
├── pytest.ini
├── README.md
├── PROJECT_CONTEXT.md        # Handoff doc for continuing development
├── src/                      # Source packages (src layout)
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── orchestrator.py   # Decompose, research loop, reflect
│   │   ├── synthesiser.py    # Report generation
│   │   └── tools.py          # Tool definitions + Anthropic/Tavily search
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py           # Abstract LLMClient + LLMResponse
│   │   ├── anthropic_client.py
│   │   ├── ollama_client.py
│   │   └── retry.py          # Exponential backoff decorator
│   └── config/
│       ├── __init__.py
│       └── settings.py       # Config dataclass + three-layer loader
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
│   └── test_integration_smoke.py
└── output/                   # Generated reports + index.md
```

---

## Running Tests

```bash
# Unit tests only (no API calls, no Ollama required)
pytest tests/ -m "not integration" -v

# Anthropic integration tests (requires API key)
pytest tests/ -m "integration and not ollama" -v

# Ollama integration tests (requires Ollama running)
pytest tests/ -m "ollama" -v

# Full suite
pytest tests/ -v
```

Current test count: **183 unit tests passing**.

---

## LLM Provider Abstraction

The agent is provider-agnostic. All providers implement the same interface:

```python
class LLMClient(ABC):
    def chat(self, messages: list, tools: list = None, max_tokens: int = 2048) -> LLMResponse:
        ...
```

Responses are normalised regardless of provider:

```python
# Text response
LLMResponse(type="text", content="...")

# Tool call response
LLMResponse(type="tool_call", tool_name="web_search", tool_input={"query": "..."})
```

To add a new provider (e.g. OpenAI), create `src/llm/openai_client.py` implementing `LLMClient` and register it in `main.py`'s `build_llms()`.

---

## API Costs

| Component | Cost |
|---|---|
| Anthropic web search | $10 / 1,000 searches |
| Tavily search | Free up to 1,000/month |
| Haiku orchestration | $1.00 / 1M input tokens, $5.00 / 1M output tokens |
| Sonnet synthesis | $3.00 / 1M input tokens, $15.00 / 1M output tokens |
| Typical default run (Anthropic search) | ~$0.05–$0.15 |
| Maximum depth run (Anthropic search) | ~$0.50–$1.00 |
| Ollama orchestration + Anthropic synthesis | ~$0.10–$0.20 |
| Full Tavily search run | Search cost: $0 (within free tier) |

---

## Roadmap

### Phase A — Stability & Quality ✅ Complete
- [x] `-p` / `--provider` CLI flag
- [x] Exponential backoff retry on API failures
- [x] Config file with three-layer hierarchy
- [x] Fix message history edge case
- [x] Model tiering — Haiku orchestration, Sonnet synthesis
- [x] Stronger reflection / critic persona
- [x] Source citations in final report
- [x] Repeated query detection + fallback synthesis

### Phase B — Output Options ✅ Complete
- [x] Report metadata table (date, topic, models, search count, time)
- [x] `-s` / `--short` flag — executive summary only
- [x] `-f` / `--format` flag — markdown or HTML output
- [x] `output/index.md` — running index of all reports
- [ ] PDF export (requires `weasyprint` or `pdfkit`)

### Phase C — Memory & Context
- [ ] Persistent result cache
- [ ] Cross-run topic index
- [ ] Context window management
- [ ] Follow-up mode (`--follow-up`)

### Phase D — Multi-Agent
- [ ] Separate planner and researcher agents
- [ ] Critic agent
- [ ] Fact-checker agent
- [ ] Parallel research

### Phase E — Tools & Sources ✅ Tavily Complete
- [x] **Tavily** search — free 1,000/month, AI-optimised
- [ ] SearXNG self-hosted search (unlimited)
- [ ] Brave Search API (2,000/month free)
- [ ] `read_url` tool
- [ ] `arxiv_search` tool
- [ ] `youtube_transcript` tool
- [ ] `file_reader` tool

### Phase F — Interface
- [ ] Web UI (Flask or FastAPI)
- [ ] Progress streaming via SSE
- [ ] Report library browser
- [ ] REST API

### Phase G — Ollama & Provider Optimisation
- [x] Mixed-provider support (Ollama orchestration + Anthropic synthesis)
- [ ] Provider-specific prompt variants
- [ ] Rephrase comparative questions for weaker models
- [ ] `simple_questions` config flag
- [ ] System prompt support in `LLMClient`
- [ ] Ollama model capability registry

### Suggested Order of Attack

| Priority | Phase | Reason |
|---|---|---|
| Next | B.5 — PDF | Completes Phase B |
| Then | E — SearXNG | Fully free, unlimited search option |
| Then | C | Makes agent stateful across runs |
| Then | D | Most architecturally interesting |
| Then | E — remaining tools | Highest research quality gains |
| Last | F | Only needed if sharing with others |

---

## Known Issues & Observations

- Comparative questions ("How does X compare to Y?") harder for llama3.1 — more likely to hit max iterations
- Llama3.1 synthesis shallower than Sonnet — report depth is model-dependent
- Fallback synthesis reliably rescues failed questions but produces shorter answers
- Anthropic web searches cost $0.01 each regardless of LLM provider
- Tavily citations are per-result rather than per-sentence (less granular than Anthropic)

---

## Notes

- Reports saved to `output/` — add to `.gitignore` if topics are sensitive
- Haiku handles orchestration by default (fast, cheap); Sonnet handles synthesis (quality)
- Ollama tool calling quality varies — `llama3.1` more reliable than `llama3.2`
- See `PROJECT_CONTEXT.md` for full architectural context and handoff documentation

---

## Licence

MIT
