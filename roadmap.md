# Research Agent — Full Roadmap

| Phase | # | Item | Description | Comments | Dependencies |
|---|---|---|---|---|---|
| **A — Stability & Quality** | | | | ✅ Complete | |
| A | 1 | Provider abstraction | Normalised LLMClient interface with AnthropicClient and OllamaClient | ✅ Done | — |
| A | 2 | Model tiering | Haiku for orchestration, Sonnet for synthesis | ✅ Done | A1 |
| A | 3 | Exponential backoff retry | @with_retry decorator on all LLM calls | ✅ Done | A1 |
| A | 4 | Three-layer config | Hardcoded defaults → config.yaml → CLI flags | ✅ Done | — |
| A | 5 | Message history fix | Tool call string detection, fabricated assistant turn | ✅ Done | A1 |
| A | 6 | Reflection / critic | Same-model critic identifies research gaps | ✅ Done — Phase D improves this | A1 |
| A | 7 | Source citations | Extract citations from Anthropic text blocks | ✅ Done — non-obvious API behaviour | A1 |
| A | 8 | Repeated query detection | Inject synthesis prompt instead of re-searching | ✅ Done — H4 fix extends to cyclic detection | A1 |
| A | 9 | Fallback synthesis | Rescue questions that hit max_iterations | ✅ Done | A8 |
| **B — Output Options** | | | | ✅ Complete | |
| B | 1 | Report metadata table | Two-column markdown table at top of every report | ✅ Done | — |
| B | 2 | --short flag | Executive summary mode | ✅ Done | — |
| B | 3 | HTML output | Styled HTML page via markdown library | ✅ Done | — |
| B | 4 | PDF export | HTML → PDF via weasyprint | ✅ Done — requires brew install pango on macOS | B3 |
| B | 5 | Report index | output/index.md tracks all runs with metadata | ✅ Done | — |
| **C — Evidence Layer** | | | | 🔄 Largely complete | |
| C | 1 | Evidence schema | EvidenceSource, EvidenceClaim, ProvenanceReport TypedDicts | ✅ Done | — |
| C | 2 | Provenance file pipeline | .provenance.json generated alongside every report | ✅ Done | C1 |
| C | 3 | --provenance flag | none / file / graph | ✅ Done | C2 |
| C | 4 | Atomic claim extraction | LLM extracts 3-8 atomic claims per research answer | ✅ Done | C1 |
| C | 5 | Confidence scoring | Source type + corroboration heuristic per claim | ✅ Done — Phase D improves with real verification | C1, C4 |
| C | 6 | Report line tracking | [N] inline markers linking report to provenance | ✅ Done — sparse, Phase D synthesiser integration improves | C4 |
| C | 7 | Source classifier | Five-layer hybrid: TLD → patterns → hardcoded → config → LLM fallback | ✅ Done | — |
| C | 8 | Nine-type taxonomy | government, academic, news, reference, institutional, industry, video, forum, general | ✅ Done | C7 |
| C | 9 | Source deduplication | Per-claim URL deduplication | ✅ Done | C4 |
| C | 10 | --output-mode flag | Stub wired through config | ✅ Done — renderers pending | — |
| C | 11 | Output mode renderers | dashboard, matrix, academic, bibliography, raw | ⏳ Pending | C1, C4, C5 |
| C | 12 | HTML interactive provenance | Hover sentence → source card with confidence and disputed flag | ⏳ Pending — makes the moat visible | C2, C6, B3 |
| **D — Parallel Research + Multi-Agent** | | | | 🔄 Part 1 complete | |
| D | 1 | Parallel asyncio workers | Research all questions concurrently | ✅ Done — 58.4s vs ~75s sequential | A1 |
| D | 2 | --max-workers flag | Configurable worker count, default 2 | ✅ Done — Ollama safe ceiling 2, Anthropic 4+ | D1 |
| D | 3 | Worker failure handling | One failed worker does not abort the run | ✅ Done | D1 |
| D | 4 | Agent abstraction | Agent dataclass: name, system_prompt, model, tools | ⏳ Pending — design before wiring more roles | A1, A4 |
| D | 5 | Dedicated planner agent | Hypothesis generation, smarter decomposition | ⏳ Pending | D4 |
| D | 6 | Independent verifier agent | Separate model verifies claims — fixes self-critique weakness | ⏳ Pending — highest quality leverage remaining | D4, C1 |
| D | 7 | Fact-checker agent | Cross-references claims across multiple sources | ⏳ Pending | D4, D6, C1 |
| D | 8 | Editor agent | Post-synthesis coherence and contradiction removal | ⏳ Pending | D4 |
| D | 9 | Contradiction detection | Flag conflicting claims across sources | ⏳ Pending — deferred from Phase C (E005) | D6, C1 |
| D | 10 | Synthesiser integration | Report line tracking during synthesis, not post-hoc matching | ⏳ Pending — fixes sparse [N] markers | D4, C6 |
| D | 11 | Iterative reflection loop | Reflect → gap fill → reflect again with bound, not single pass | ⏳ Pending | D5 |
| D | 12 | Per-turn multi-tool calls | Allow agent to issue multiple tool calls in one turn | ⏳ Pending — free parallelism per Anthropic guidance | D4 |
| **F partial — Core Tools** | | | | ⏳ Pending | |
| F | 1 | read_url | Fetch and read full page content — bridges snippets to real research | ⏳ Pending — highest priority tool | A7 |
| F | 2 | arxiv_search | Academic paper search and structured extraction | ⏳ Pending | F1 |
| F | 3 | pdf_reader | Extract content from PDFs | ⏳ Pending | F1 |
| **PKG — Packaging** | | | | ⏳ Pending — after D complete | |
| PKG | 1 | Dockerfile | Single-command installation, no Python setup required | ⏳ Pending — removes 90% of installation drop-off | All Phase A-D |
| PKG | 2 | pipx package | pip-installable CLI, no virtualenv management | ⏳ Pending | PKG1 |
| PKG | 3 | Preset configs | quick.yaml, standard.yaml, deep.yaml, free-tier.yaml, local-only.yaml | ⏳ Pending — makes configuration accessible to non-developers | A4, PKG1 |
| PKG | 4 | First-run wizard | Interactive setup: API keys, default provider, search provider | ⏳ Pending | PKG2, PKG3 |
| PKG | 5 | Config validation | Clear error messages for missing keys or invalid config | ⏳ Pending | A4 |
| PKG | 6 | Documentation | Full user docs: installation, configuration, examples, provenance guide | ⏳ Pending | PKG1-5 |
| **E — Memory & Persistent Knowledge** | | | | ⏳ Pending | |
| E | 1 | KnowledgeStore abstraction | Abstract base: KuzuStore, SQLiteStore, MemoryStore | ⏳ Pending | C1 |
| E | 2 | KuzuStore implementation | Embedded graph DB, Cypher-compatible, no server required | ⏳ Pending | E1 |
| E | 3 | SQLiteStore implementation | Relational fallback, zero extra dependencies | ⏳ Pending | E1 |
| E | 4 | MemoryStore implementation | Tests and ephemeral runs | ⏳ Pending | E1 |
| E | 5 | Retrieval cache | Check store before searching — major cost reduction | ⏳ Pending | E2 |
| E | 6 | Cross-run accumulation | Claims persist and extend across runs on same topic | ⏳ Pending | E2 |
| E | 7 | --provenance graph | Write evidence to knowledge store | ⏳ Pending | E2, C3 |
| E | 8 | Source freshness tracking | Flag citations older than configurable threshold | ⏳ Pending | E2 |
| E | 9 | Follow-up mode | --follow-up extends a previous report with new evidence | ⏳ Pending | E6 |
| E | 10 | diff output mode | Changes vs previous run on same topic | ⏳ Pending | E6, C10 |
| E | 11 | Context window management | Summarise long message histories mid-loop | ⏳ Pending | A5 |
| **UI — Comprehensive Web UI** | | | | ⏳ Pending — after Phase E | |
| UI | 1 | FastAPI backend | REST API serving research execution and report retrieval | ⏳ Pending | All Phase A-E |
| UI | 2 | Research execution panel | Topic input, full option specification, preset selector | ⏳ Pending — replaces CLI for non-developers | UI1, PKG3 |
| UI | 3 | Progress streaming | Live SSE updates: questions researched, gaps found, synthesis running | ⏳ Pending | UI1, D1 |
| UI | 4 | Report viewer | Rendered report with metadata, download options (md/html/pdf) | ⏳ Pending | UI1, B3, B4 |
| UI | 5 | Provenance explorer | Hoverable [N] markers → source cards with confidence, type, disputed flag | ⏳ Pending — makes the moat visible | UI4, C2, C6, C12 |
| UI | 6 | Quality metrics display | Coverage, confidence, contradiction count, verified/disputed breakdown | ⏳ Pending | UI4, C5 |
| UI | 7 | Report library | History of all runs, search and filter by topic/date/provider/mode | ⏳ Pending | UI1, E6 |
| UI | 8 | Diff view | Side-by-side comparison of two runs on the same topic | ⏳ Pending | UI7, E10 |
| UI | 9 | Follow-up panel | Extend a previous report — select and continue | ⏳ Pending | UI7, E9 |
| UI | 10 | Knowledge graph browser | Visual exploration of accumulated claims and relationships | ⏳ Pending | UI1, E2 |
| UI | 11 | Configuration panel | API keys, default providers, search settings, custom domain rules | ⏳ Pending | UI1, PKG3 |
| UI | 12 | Webhook support | Notify on completion — Slack, email, custom endpoint | ⏳ Pending | UI1 |
| **F remaining — Extended Tools** | | | | ⏳ Pending — after UI | |
| F | 4 | SearXNG self-hosted | Unlimited free search, aggregates Google+Bing+DDG | ⏳ Pending | A7 |
| F | 5 | Brave Search API | 2,000/month free, independent index | ⏳ Pending | A7 |
| F | 6 | youtube_transcript | Extract spoken content from video | ⏳ Pending | F1 |
| F | 7 | file_reader | Include local documents as research context | ⏳ Pending | F1 |
| F | 8 | Browser tool | Interact with JavaScript-rendered pages | ⏳ Pending | F1 |
| F | 9 | Configurable tool set | Select active tools per run via CLI or UI | ⏳ Pending | UI2, F1-8 |
| **G — Provider Optimisation** | | | | 🔄 G.1 complete | |
| G | 1 | Mixed provider support | --orchestration-provider + --synthesis-provider | ✅ Done | A1, A2 |
| G | 2 | Provider-specific prompts | Separate prompt variants per provider in config | ⏳ Pending | A4, D4 |
| G | 3 | Comparative question rephrasing | Break "X vs Y" into two simpler questions for weaker models | ⏳ Pending | G2 |
| G | 4 | simple_questions flag | Instructs decomposer to avoid comparative questions | ⏳ Pending | G3 |
| G | 5 | System prompt support | Optional system prompt in LLMClient | ⏳ Pending | A1 |
| G | 6 | Ollama model registry | Config-driven map of models with tool-calling capability | ⏳ Pending | A1 |
| **H — Observability** | | | | ⏳ Pending | |
| H | 1 | Structured logging | Per-run log with timing, token counts, model calls | ⏳ Pending | A1 |
| H | 2 | Cost tracking | Real-time token + search cost accumulation with budget limits | ⏳ Pending — raw data already in response.raw | H1 |
| H | 3 | Run replay | Store full inputs/outputs to reproduce any run | ⏳ Pending | H1 |
| H | 4 | Confidence threshold | Refuse to synthesise if evidence quality below minimum | ⏳ Pending | C5, D6 |
| H | 5 | Streaming output | Stream synthesis tokens to terminal in real time | ⏳ Pending | A1 |
| H | 6 | Source freshness alerts | Warn when key citations exceed configurable age | ⏳ Pending | E8 |