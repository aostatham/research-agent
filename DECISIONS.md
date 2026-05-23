# Research Agent — Decision Log

A record of significant architectural and design decisions made during development,
with rationale. Ordered chronologically.

---

## Architecture

### A001 — Agentic pipeline structure
**Decision:** Decompose → Research loop → Reflect → Synthesise
**Rationale:** Separating planning, research, reflection, and synthesis into distinct
stages allows each to be optimised, replaced, or parallelised independently. Single-prompt
approaches cannot iterate or self-correct.
**Date:** Session 1

### A002 — LLM provider abstraction
**Decision:** Abstract all LLM calls behind a normalised LLMClient interface with
AnthropicClient and OllamaClient implementations. LLMResponse is normalised across providers.
**Rationale:** Enables model swapping, benchmark testing, cost optimisation, and future
provider additions without changing agent logic. Provider lock-in is a significant risk
for a long-lived project.
**Date:** Session 1

### A003 — Model tiering
**Decision:** Use cheaper model (Haiku) for orchestration, stronger model (Sonnet) for synthesis.
**Rationale:** Orchestration involves many small tool-routing decisions that don't require
full reasoning capability. Synthesis is the quality-critical step. Tiering reduces cost
by ~60-70% with minimal quality loss.
**Date:** Session 1

### A004 — src layout
**Decision:** Moved agent, llm, config packages under src/ rather than flat project root.
**Rationale:** Standard Python packaging convention for non-trivial projects. Prevents
accidental imports of local code during testing. Better separation if the project is
later packaged or published.
**Date:** Mid-session, after initial flat layout

### A005 — Mixed provider support
**Decision:** Orchestration and synthesis providers are independently configurable via
--orchestration-provider and --synthesis-provider flags.
**Rationale:** Enables free Ollama orchestration with high-quality Anthropic synthesis —
best quality/cost balance. Confirmed working: Ollama orchestration + Sonnet synthesis
produces noticeably better reports than pure Ollama at ~$0.20 vs ~$0.80 per run.
**Date:** Phase G.1

### A006 — main.py refactor — thin entry point
**Decision:** Extracted output formatting (formatter.py), file writing (writer.py),
provenance (provenance.py stub), and LLM construction (builder.py) from main.py.
main.py is now a thin CLI entry point only.
**Rationale:** main.py had six distinct responsibilities. As Phase C adds provenance
generation, keeping all output logic in one file would become unmanageable. Clean
module boundaries also make each concern independently testable.
**Date:** Pre-Phase C

---

## Search

### S001 — Web search always uses Anthropic or Tavily regardless of LLM provider
**Decision:** Web searches route through execute_tool_with_sources() in tools.py,
which uses the configured search provider independently of the LLM provider.
**Rationale:** Ollama cannot execute web searches — it has no internet access.
Anthropic's web_search tool requires the Anthropic API. This is non-obvious and
must be understood before estimating costs for Ollama runs.
**Impact:** Ollama runs still cost $0.01 per search (Anthropic) or use Tavily free tier.

### S002 — Tavily as primary alternative to Anthropic search
**Decision:** Tavily chosen as first alternative search provider over SearXNG or Brave.
**Rationale:** Free 1,000/month, designed specifically for AI agents, #1 on DeepResearch
Bench, simplest integration (single pip install). SearXNG requires self-hosting.
Brave has a smaller free tier.
**Date:** Phase E

### S003 — Search provider configured once at startup
**Decision:** configure_search() is called once in main() before any research begins.
Module-level globals in tools.py store the active provider.
**Rationale:** Avoids passing provider config through the entire call stack
(orchestrator → tools). Side-effecting but contained. Simpler than dependency injection
for a single-process CLI tool.
**Date:** Phase E

### S004 — Anthropic citations are on text blocks not tool_result blocks
**Decision:** Documented as a key architectural note in tools.py and CLAUDE.md.
**Rationale:** Non-obvious API behaviour discovered during development. Citations appear
on the text blocks in the response, not on the tool_result blocks as might be expected.
Getting this wrong results in empty citation lists despite searches succeeding.
**Date:** Phase A debugging

---

## Output

### O001 — Metadata as markdown table at top of every report
**Decision:** Every report begins with a two-column markdown table: Field | Value.
**Rationale:** Provides immediate context for any reader — when was this run, which
models, how many searches, how long. Table format renders correctly in VS Code,
GitHub, and HTML. Bold key-value pairs on one line were rejected as unreadable.
**Date:** Phase B

### O002 — Separate provenance file with line number references
**Decision:** Provenance is generated as a separate .provenance.json file alongside
the report, not inline in the report text.
**Rationale:** Keeps the report clean and readable for normal use. Provenance file
is machine-readable and queryable. Line number references allow tooling to link
specific report sentences to their evidence chains. Inline markers (footnote numbers
only) link the two files without cluttering the prose.
**Alternative rejected:** Full inline provenance — makes reports unreadable.
**Date:** Phase C design

### O003 — Output mode and provenance as independent flags
**Decision:** --output-mode controls report rendering. --provenance controls whether
a provenance file is generated. They are independent.
**Rationale:** A user may want a clean report with a provenance file, or a report
with inline markers without a provenance file. Coupling the two would prevent valid
combinations. Independence gives full control over both dimensions.
**Date:** Phase C design

### O004 — Output modes list
**Decision:** Supported output modes: report (default), report-evidence, data,
dashboard, slides, matrix, academic, bibliography, diff, raw.
**Rationale:** Different use cases need different output shapes. The research pipeline
is identical for all modes — only the renderer changes. This keeps the pipeline clean
and makes adding new renderers straightforward.
**Note:** diff mode requires Phase E knowledge store. graph provenance requires Phase E.
**Date:** Phase C design

### O005 — PDF via weasyprint (HTML pipeline)
**Decision:** PDF export converts the HTML output via weasyprint rather than building
a reportlab layout.
**Rationale:** weasyprint renders the same HTML/CSS as the browser output, ensuring
consistent styling between HTML and PDF. Building a reportlab layout would require
duplicating all formatting logic and would diverge from the HTML output over time.
**Dependency:** brew install pango (macOS), pip install weasyprint.
**Date:** Phase B.5

### O006 — Index file tracks all reports
**Decision:** output/index.md is a running markdown table of all reports generated,
including date, topic, providers, search provider, question count, search count,
mode, and file link.
**Rationale:** Makes it easy to find previous reports and compare runs across providers
and settings without opening each file individually.
**Date:** Phase B

---

## Knowledge & Persistence

### K001 — Knowledge store abstraction with config-driven backend
**Decision:** KnowledgeStore abstract base class with KuzuStore (default), SQLiteStore
(fallback), and MemoryStore (tests) implementations. Backend selected via config.yaml:
knowledge_store: kuzu | sqlite | memory | none.
**Rationale:** Same pattern as LLM provider abstraction. Switching from Kuzu to SQLite
or a future Neo4j implementation requires only a config change. Agent code never imports
a concrete store directly.
**Date:** Phase E design

### K002 — Kuzu as default knowledge store
**Decision:** Kuzu chosen over SQLite, NetworkX, and Neo4j as the default graph store.
**Rationale:** Embedded (no server), graph-native (Cypher-compatible queries), actively
developed, designed for AI agent use cases. SQLite is awkward for graph traversal.
NetworkX requires manual JSON serialisation. Neo4j requires a running server.
**Date:** Phase E design

### K003 — Knowledge graph schema
**Decision:** Four relationship types: Claim SUPPORTED_BY Source, Claim CONTRADICTS Claim,
Claim BELONGS_TO Topic, Topic PRECEDED_BY Topic.
**Rationale:** Minimal schema that supports the core provenance queries — which sources
support a claim, which claims contradict each other, how claims relate to topics across
runs. Additional relationship types can be added as Phase E develops.
**Date:** Phase E design

---

## Evidence Layer

### E001 — Evidence objects as TypedDict not dataclass
**Decision:** EvidenceClaim and related types are TypedDict, not dataclasses or Pydantic models.
**Rationale:** TypedDict is natively JSON-serialisable, which is essential for writing
provenance files. No runtime validation overhead. Lightweight. Sufficient for a pipeline
that doesn't mutate evidence objects after creation.
**Date:** Phase C design

### E002 — Confidence scoring approach
**Decision:** Confidence scored per-claim based on source quality (government/academic
> news > blog), corroboration (multiple sources), and recency.
**Rationale:** Simple heuristic that doesn't require a separate LLM call per claim.
Independent verification (separate model) is a Phase D item. Phase C confidence is
a first-pass heuristic, not a verified score.
**Date:** Phase C design

### E003 — Placeholder claims in Phase C Part 1
**Decision:** Part 1 of Phase C generates placeholder claims (one per question/answer
pair) rather than extracting individual claims from text.
**Rationale:** Gets the provenance file pipeline working end-to-end before implementing
full claim extraction. Allows testing of file generation, quality metrics, and CLI flags
without the complexity of NLP claim extraction.
**Date:** Phase C Part 1

### E004 — Source type classifier: interim domain list expansion (superseded by E006)
**Decision:** Expanded classify_source_type() with an explicit domain list covering
academic journals, government bodies, news outlets, and added "reference" as a source
type for Wikipedia. Implemented during Phase C Part 2.
**Rationale:** The initial implementation classified any unrecognised domain as "blog",
over-penalising legitimate academic and institutional sources. Observed on a nuclear
fusion run where iaea.org and sciencedirect.com were classified as blog.
**Superseded by:** E006 — the domain list approach requires ongoing maintenance as new
domains appear. E006 replaces it with a layered hybrid approach.
**Date:** Phase C Part 2

### E005 — Contradiction detection deferred to Phase D
**Decision:** Contradiction detection is not implemented in Phase C. It is deferred to
Phase D where the independent verifier agent handles it more robustly.
**Rationale:** Shallow within-answer contradiction detection in Phase C would be replaced
by the Phase D independent verifier anyway. Phase D's shared evidence store and
independent verifier model are the right architectural home for contradiction detection.
Implementing a weaker version now and replacing it in Phase D is waste.
**Date:** Phase C Part 2 scoping

### E006 — Source type classifier refactor: hybrid pattern + LLM fallback (supersedes E004)
**Decision:** classify_source_type() uses five classification layers in order:
  1. TLD patterns — .gov, .edu, .mil, .gov.uk (most reliable, zero maintenance)
  2. Stable subdomain patterns — arxiv.org, pubmed, doi.org, wikipedia
  3. Short hardcoded list — high-value institutional domains that do not follow TLD
     conventions: iaea.org, iter.org, frontiersin.org, cern.ch etc.
     Addition trigger: domain appears in 3+ runs and is consistently misclassified;
     never add speculatively.
  4. Custom domains — user-supplied via source_classification in config.yaml
  5. LLM fallback — only invoked when llm_client is provided and layers 1-4 match nothing.
**Config approach:** source_classification dict in config.yaml chosen over a database.
Version-controlled, no new dependencies, consistent with project config pattern.
**Maintenance trigger for layer 3:** Domain appears in 3+ research runs and is
consistently misclassified. Never add speculatively.
**Phase F roadmap item:** Expose config UI for managing custom domain additions.
**Rationale:** The flat domain list (E004) requires constant maintenance as new domains
appear. The layered approach separates stable facts (TLDs) from institutional exceptions
(layer 3) from user-specific overrides (config). LLM fallback handles novel domains
without hard-coding them.
**Date:** Phase C classifier refactor (post Part 2)

---

## Testing

### T001 — Free providers as default for integration tests
**Decision:** Integration tests default to Ollama + Tavily. Anthropic-specific tests
are marked @pytest.mark.anthropic_integration and excluded from default integration runs.
**Rationale:** Running Anthropic tests costs money and hits rate limits. The pipeline
behaviour being tested (does it produce a report, does the index update) is provider-
agnostic. Anthropic-specific behaviour (citation format, tool call structure) warrants
its own explicitly-run test suite.
**Date:** test_integration_smoke.py rewrite

### T002 — Patch at lookup site not definition site
**Decision:** Always patch at the module where the name is looked up.
patch("llm.builder.AnthropicClient") not patch("llm.anthropic_client.AnthropicClient")
**Rationale:** Python's unittest.mock patches the name in the namespace where it is used,
not where it is defined. Patching at the definition site has no effect on already-imported
references. This is a common source of tests that appear to pass but don't actually mock
anything.
**Date:** Established during Phase A testing

### T003 — Growing test count as commit gate
**Decision:** pytest tests/ -m "not integration" -v must pass all existing tests before
every commit. Count grows with each phase — treat any reduction as a regression signal.
Started at 199, currently 221+.
**Rationale:** Prevents regressions from accumulating. Each phase adds tests alongside
code so the count grows over time.
**Date:** Ongoing

---

## Provider & Model

### P001 — Repeated query detection
**Decision:** If the agentic loop produces the same search query twice, inject a
synthesis-forcing message instead of executing the search again.
**Rationale:** Smaller models (llama3.1) sometimes loop on the same query when they
can't synthesise from the results. Without detection, this exhausts max_iterations
and produces a poor fallback. Forcing synthesis earlier produces a better answer
from the accumulated results.
**Date:** Phase A debugging

### P002 — Fallback synthesis on max iterations
**Decision:** If a question hits max_iterations with accumulated results, attempt
a standalone synthesis call rather than returning a failure string.
**Rationale:** A question that searched multiple times likely has useful content
accumulated even if no single answer was found. Fallback synthesis rescues these
questions and produces shorter but usable answers. Pure failure messages degrade
the final report significantly.
**Date:** Phase A

### P003 — Comparative questions are harder for smaller models
**Decision:** Documented as a known issue. Phase G will add prompt variants that
rephrase comparative questions into two simpler questions for weaker models.
**Rationale:** "How does X compare to Y" requires holding two concepts simultaneously.
Llama3.1 hits max iterations on these more often than on factual questions. Splitting
into "What are the strengths of X" and "What are the strengths of Y" produces better
results and lets the synthesiser do the comparison.
**Date:** Phase A observation

---

## Project Management

### M001 — Claude Code for mechanical changes, this conversation for architecture
**Decision:** Structural refactors, commenting passes, and file generation go to
Claude Code. Architectural decisions, design discussions, and quality assessments
stay in this conversation.
**Rationale:** Claude Code is better at mechanical multi-file changes with immediate
feedback loops. This conversation is better at holding architectural context and
making tradeoffs. Mixing the two leads to architectural drift.
**Date:** Ongoing

### M002 — Roadmap as living document
**Decision:** Roadmap is regenerated after every significant architectural decision,
not just at phase boundaries.
**Rationale:** A static roadmap diverges from reality quickly. Keeping it current
ensures the next phase prompt reflects actual project state rather than original plans.
**Date:** Ongoing

### M003 — CLAUDE.md as Claude Code briefing
**Decision:** CLAUDE.md in project root contains architecture, commands, conventions,
and current phase context for Claude Code.
**Rationale:** Claude Code starts each session without conversation context. CLAUDE.md
is read automatically and provides the persistent briefing that would otherwise need
to be repeated every session.
**Date:** Pre-Phase C

### M004 — Decision log maintained throughout development
**Decision:** DECISIONS.md records all significant architectural and design decisions
with rationale. Updated whenever a significant decision is made, not just at phase end.
**Rationale:** Decisions made mid-session are easily forgotten. The log provides
context for future contributors (human or AI) and prevents re-litigating settled
decisions. Also useful for onboarding Claude Code to project history.
**Date:** Mid-project retrospective
