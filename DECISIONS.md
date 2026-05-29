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
provenance (provenance.py), and LLM construction (builder.py) from main.py.
main.py is now a thin CLI entry point only.
**Rationale:** main.py had six distinct responsibilities. Clean module boundaries
make each concern independently testable and prevent provenance logic from
being buried in the CLI entry point.
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

### O007 — HTML sanitisation via bleach post-rendering
**Decision:** convert_to_html() sanitises report output by passing the rendered HTML
through bleach.clean() with a tag allowlist after markdown.markdown(). The topic
variable is escaped via html.escape() before interpolation into the HTML template.
html.escape() must not be applied to the report body — it runs before markdown
rendering and causes double-encoding inside fenced code blocks.
**Rationale:** Pre-rendering escape (html.escape on report body) was introduced as
an XSS fix in Pass 2 but caused double-encoding of code blocks at runtime. Post-rendering
sanitisation via bleach correctly strips disallowed tags from the rendered HTML without
corrupting markdown-formatted content.
**Date:** Phase D Part 2 QA Pass 3

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
> news > general), corroboration (multiple sources), and recency.
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
over-penalising legitimate academic and institutional sources.
**Superseded by:** E006 — the domain list approach requires ongoing maintenance.
**Date:** Phase C Part 2

### E005 — Contradiction detection deferred to Phase D
**Decision:** Contradiction detection is not implemented in Phase C. Deferred to
Phase D where the independent verifier agent handles it more robustly.
**Rationale:** Shallow within-answer contradiction detection in Phase C would be replaced
by the Phase D independent verifier anyway. Implementing a weaker version now and
replacing it in Phase D is waste.
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
**Date:** Phase C classifier refactor

### E007 — Source deduplication in claim extraction
**Decision:** Sources are deduplicated by URL within each claim in
extract_claims_from_answer(). Each claim receives a deduped source list.
**Rationale:** Without deduplication, sources from a research question were copied
to every atomic claim extracted from that answer, inflating source counts and
skewing classification statistics.
**Note:** Full per-claim source attribution (only sources supporting that specific
claim) is a Phase D item requiring LLM source attribution during extraction.
**Date:** Phase C post-Part 2 fix

### E008 — Source taxonomy expansion: nine types replacing general catch-all
**Decision:** Expanded from five types to nine: government, academic, news, reference,
institutional, industry, video, forum, general.
institutional covers think tanks and industry associations (weforum.org, rand.org,
world-nuclear.org). Video covers YouTube/Vimeo. Forum covers Reddit/Quora.
Industry has no hardcoded list — too numerous and volatile, left as general catch-all
with config.yaml override available.
**Confidence scoring weights:** institutional +0.08, industry +0.02, video +0.01,
forum +0.00, general +0.00.
**Date:** Phase C classifier refinement

### E009 — Rename source type "blog" to "general"
**Decision:** Renamed the catch-all source type from "blog" to "general" throughout
the codebase.
**Rationale:** "blog" implies a specific content format rather than an unclassified
catch-all. "general" more accurately describes sources that didn't match any specific
pattern. Confidence weight unchanged at +0.00. Pure rename — no logic change.
**Date:** Phase C classifier refinement

---

## Phase D — Multi-Agent Architecture

### D001 — Parallel workers: provider-specific safe ceiling
**Decision:** asyncio parallel research workers confirmed working. Ollama serialises
LLM requests internally — concurrent requests queue and hit the 60s read timeout at
max_workers=4. Safe ceiling: max_workers=2 for Ollama, max_workers=4+ for Anthropic.
Default changed to 2.
**Rationale:** Confirmed by timing tests: 4 questions in 58.4s with max_workers=4
vs ~75s sequential. Ollama crash at gap phase with max_workers=4 confirmed the ceiling.
Phase G will auto-detect safe ceiling based on configured provider.
**Date:** Phase D Part 1

### D002 — asyncio.run() wrapper pattern
**Decision:** Orchestrator must not call asyncio.run() directly in run(). Pattern:
run_async() is the core async implementation. run() is a synchronous wrapper for
CLI use only calling asyncio.run(self.run_async(topic)). All async contexts
(FastAPI Phase I, async tests) call run_async() directly.
**Rationale:** asyncio.run() raises RuntimeError if called from inside an already-
running event loop. Identified by Opus 4.7 codebase review as blocking Phase I.
**Date:** Phase D Part 1 / Opus bug fix

### D003 — Agent abstraction in src/agent/base.py
**Decision:** Agent dataclass placed in src/agent/base.py, not src/llm/base.py.
LLMClient knows how to talk to a model — it is infrastructure. Agent knows what it
is and what it's for — it is a pipeline concept that wraps LLMClient with identity,
persona, system prompt, and tool set.
**Rationale:** Clean separation between llm/ layer (provider abstraction) and agent/
layer (pipeline abstraction). Agent is base behaviour for the agent layer, not the
LLM layer.
**Date:** Phase D Part 2 design

### D004 — Agent construction in src/agent/builder.py
**Decision:** Agent factory functions build_agent() and build_agents() placed in
src/agent/builder.py, mirroring src/llm/builder.py pattern. main.py calls both
builders at startup and passes results into the pipeline.
**Rationale:** Agent layer owns its construction logic. main.py stays thin.
Consistent with the existing LLM builder pattern.
**Date:** Phase D Part 2 design

### D005 — AgentPool typed container replaces dict
**Decision:** Typed AgentPool dataclass (frozen=True) replaces dict[str, Agent] for
passing agents to Orchestrator. AgentPool fields: researcher, verifier, editor.
**Rationale:** dict[str, Agent] produces KeyError at runtime for missing agents and
lacks IDE support. AgentPool is type-checked, IDE-friendly, and refactor-safe.
Grows by field rather than expanding argument lists. Dynamic agent spawning (Phase G)
will require a registry — defer that change to that phase.
**Date:** Phase D Part 2 design

### D006 — Agent dataclass fields
**Decision:** Agent dataclass is frozen=True with fields:
  name: str                          — identifier e.g. "researcher", "verifier"
  role: str                          — human-readable description
  description: str                   — for future dynamic handoff routing
  llm: LLMClient                     — underlying provider
  system_prompt: str                 — persona and instructions (native parameter)
  tools: tuple = ()                  — immutable per-agent tool subset
  temperature: Optional[float] = None
  max_iterations: int = 5            — per-agent loop budget, not global
  output_schema: Optional[type] = None  — return contract for validation
**Rationale:** output_schema and max_iterations added on Opus 4.7 recommendation —
each agent needs its own output contract and loop budget. description added for
future dynamic handoff at near-zero cost. frozen=True makes Agent hashable and
prevents runtime mutation. tools is tuple not list to avoid shared-reference bugs.
**Date:** Phase D Part 2 design

### D007 — System prompt as native provider parameter
**Decision:** Agent.chat() passes system_prompt as the native system parameter on
each provider, not prepended to the messages list.
Anthropic: top-level system= parameter on client.messages.create().
Ollama: prepend {"role": "system", "content": system_prompt} to messages list
(idiomatic for Ollama /api/chat).
LLMClient.chat() gains an optional system: Optional[str] = None parameter.
**Rationale:** Anthropic ignores role: system inside the messages list and emits a
warning. Native parameter is the correct approach. Provider-specific assembly
handled by a _build_messages(messages, system) helper on each client.
**Date:** Phase D Part 2 design

### D008 — ResearchResult replaces (answer, sources) tuple
**Decision:** Researcher returns a ResearchResult dataclass containing:
  question: str
  answer: str
  claims: list[EvidenceClaim]
  sources: list[EvidenceSource]
  message_history: list[dict]
  verification: str = "unverified"   # "verified" | "refuted" | "unverified"
**Rationale:** Unblocks per-claim source attribution (E007). Provides Verifier
structured input without re-parsing prose. Preserves researcher message history
so Verifier can see what the researcher considered before concluding. Three-state
verification field (replacing original bool) propagates Verifier outcomes to
the provenance file accurately.
**Date:** Phase D Part 2 design / Pass 3 QA fix (H3)

### D009 — Researcher Agent owns its loop
**Decision:** _research_question_sync() loop logic moves into the Researcher Agent,
not wrapped by it. Orchestrator becomes a thin coordinator. The Agent owns its loop
semantics, budget (max_iterations), and fallback behaviour.
**Rationale:** Consistent with 2026 agent patterns where agents are autonomous within
their scope. "Wrapping" _research_question_sync() would make Researcher a config
bundle, not a real agent.
**Date:** Phase D Part 2 design

### D010 — Verifier has web_search, runs per-Researcher in parallel
**Decision:** Verifier runs after each Researcher completes (not after all research).
Verifier has web_search access. Targets top 3 suspicious claims per heuristic:
contains a number, contains a named entity not in the original question, uses
absolute terms (first, only, always, never). Cheap first pass flags; optional
expensive second pass verifies. Runs outside the semaphore concurrently with
subsequent research questions.
**Rationale:** A Verifier with no tools is self-critique by another name — Princeton
NLP findings confirm same-model maker-checker rarely catches new errors. Per-Researcher
parallelism provides early focused verification without adding serial latency.
**Date:** Phase D Part 2 design

### D011 — Editor Agent scope is coherence only, configurable model
**Decision:** Three editor types identified:
  1. Mechanical — clean_report() post-process function in formatter.py, no LLM.
  2. Coherence — Editor Agent, Phase D scope.
  3. Substantive restructuring — Analyst Agent, Phase E scope (see D013).
Editor Agent targets type 2 only. System prompt biased heavily toward no edit:
"only edit when a specific identifiable defect exists; if in doubt, leave it alone;
never add new information."
Model: configurable via editor_provider / editor_model, defaults to synthesis model.
At Sonnet capability, over-editing is a bigger risk than under-editing.
**Rationale:** Clear separation prevents drift. Mechanical cleanup is a function.
Coherence editing needs synthesis-equivalent capability. Substantive restructuring
needs evidence graph access (Phase E).
**Date:** Phase D Part 2 design

### D012 — Editor model configurable, defaults to Synthesiser model
**Decision:** Editor inherits synthesis provider and model by default. Configurable
via editor_provider, anthropic_editor_model, ollama_editor_model — same three-layer
resolution as synthesis tier.
Resolution:
  editor_provider = config.editor_provider or synth_provider
  editor_model = config.anthropic_editor_model or synth_model  (if anthropic)
              or config.ollama_editor_model or synth_model     (if ollama)
**Rationale:** Default behaviour (Editor = Synthesiser model) is correct for 90% of
users. Power users can set a cheaper mechanical editor (Haiku/llama3.1) or a stronger
substantive editor (Opus) without changing the pipeline.
**Date:** Phase D Part 2 design

### D013 — Analyst Agent deferred to Phase E
**Decision:** Type 3 editing (substantive restructuring) requires knowledge graph
access to be meaningful. Implemented as a distinct Analyst Agent in Phase E, not
a configuration of the Editor Agent.
**Rationale:** Analyst reads claim confidence, coverage metrics, and evidence
relationships to decide what to restructure, drop, or strengthen. This requires
Phase E's Kuzu knowledge store. The Editor Agent (Phase D) targets prose coherence
only. Analyst Agent (Phase E) targets evidence-informed restructuring.
**See also:** D011 (three editor types established).
**Date:** Phase D Part 2 design

### D014 — Editor minimum response length guard
**Decision:** editor.py rejects a response if len(edited) < 0.5 * len(original)
or if the first 60 characters match a known refusal phrase. Falls back to
original report unchanged. The 100-character absolute floor introduced by
Claude Code in Step 9 was insufficient — a 276-char refusal against a
5000-char report passed the floor.
**Rationale:** Editor output_schema (Agent.output_schema) is not yet enforced.
Until it is, a proportional heuristic is the most reliable guard against
model refusals and truncated responses replacing the synthesised report.
**Date:** Phase D Part 2 QA fixes

### D015 — Planner Agent deferred to Phase E
**Decision:** Planner is removed from AgentPool in Pass 2. Orchestrator.decompose()
continues to use self.llm with the inline DECOMPOSE_PROMPT. The Planner field,
builder code, and prompts/planner.md are removed until Phase E when decompose()
is redesigned with a reconciled prompt and parser.
**Rationale:** QA (H2) found the Planner was built and loaded but never called.
Wiring it without reconciling the numbered-list prompt against the json.loads()
parser would introduce new bugs. Deferral is cleaner than a partial fix.
**Date:** Phase D Part 2 QA fixes

### D016 — Inline researcher fallback path removed in Pass 2
**Decision:** The conditional delegate pattern in Orchestrator._research_question_sync()
— which called researcher.research() when agent_pool was set and fell back to
the old inline loop otherwise — is removed in Pass 2. The inline loop is deleted.
The agent path is now unconditional.
**Rationale:** QA (M5) found the inline loop had diverged from the agent loop.
Maintaining two paths is a correctness risk. The agent path is stable and tested.
**Date:** Phase D Part 2 QA fixes

### D017 — Agent.chat() silently discards caller-supplied system kwarg
**Decision:** Agent.chat() calls kwargs.pop('system', None) before injecting
system=self.system_prompt. Any system= kwarg supplied by a caller is silently
discarded. self.system_prompt is always used.
**Rationale:** QA (M2) found that passing system= explicitly to agent.chat()
raised TypeError due to kwarg collision. The agent's system prompt is
non-negotiable — callers have no legitimate reason to override it. Silent
discard is safer than raising.
**Date:** Phase D Part 2 QA fixes

### D018 — asyncio.gather always called with return_exceptions=True
**Decision:** Every asyncio.gather() call in orchestrator.py uses
return_exceptions=True. After the gather, results are iterated and
exceptions are logged as warnings and skipped. The pipeline continues
with whatever results were successfully collected.
**Rationale:** QA (H5) found that a single worker failure aborted the entire
pipeline. One failed research question should not destroy a run that
otherwise produced four good answers.
**Date:** Phase D Part 2 QA fixes

### D019 — Prompt location policy: agent identity vs task instruction
**Decision:** Agent system prompts go in prompts/ as .md files. Task
instruction prompts stay inline in source files.
**Rationale:** Agent prompts (Researcher, Verifier, Editor) define
persona, behaviour, and output contract for autonomous agents. They
evolve independently of code, benefit from distinct git history, and
can be swapped without code changes. Task prompts (decompose, reflect,
synthesis, fallback) are tightly coupled to parsing logic and runtime
string interpolation — separating them from the code that depends on
their exact output shape creates invisible coupling and increases the
risk of breakage.
**Exception:** If a task prompt grows complex enough to need per-model
variants or independent versioning, extract it to prompts/ and record
a superseding decision.
**Superseded by:** D028 — three-category prompt location policy.
**Date:** Phase D Part 2 / Pass 3

### D020 — Editor coherence scope: adjacent paragraphs plus summary/body contradictions
**Decision:** The Editor checks for contradictions between adjacent
paragraphs only, plus one additional case: a claim in an executive
summary or conclusions section that directly contradicts a specific
finding in the report body. Non-adjacent contradictions elsewhere in
the report are out of scope.
**Rationale:** Adjacent contradictions are structural defects a reader
encounters immediately and that the Editor can fix with high confidence.
Non-adjacent contradictions across the full report are often deliberate
nuance, qualified claims, or genuine uncertainty in source material —
fixing them risks substantive judgement the Editor is not equipped to
make. The summary/body exception is added because executive summary
contradictions are visible to any reader and unambiguously confusing.
Full cross-report contradiction detection requires the claim graph
from Phase E.
**Date:** Phase D Part 2 / Pass 3

### D021 — Retry classifier must not include APIStatusError base class
**Decision:** _ANTHROPIC_EXCEPTIONS contains only RateLimitError and
InternalServerError. APIStatusError must never be added — it is the
base class for the entire Anthropic status-error hierarchy and its
inclusion causes isinstance to match non-retryable errors including
AuthenticationError and BadRequestError.
**Rationale:** Pass-3 QA (H1) found that including APIStatusError made
_is_retryable return True for AuthenticationError, causing a 7-second
hang on bad API key before failure. The string-match fallback form had
the same hole in theory but avoided it in practice because the SDK
raises concrete subclasses whose names differ from "APIStatusError".
**Date:** Phase D Part 2 QA Pass 4

### D022 — index.md.lock is an operational artifact, not source
**Decision:** output/index.md.lock is created by fcntl.flock in
writer.py on every update_index() call and is never deleted. It is
added to .gitignore.
**Rationale:** The lock file is an operational artifact required for
concurrency-safe index writes. Deleting it after each write would
introduce a race between deletion and the next lock acquisition.
Ignoring it in git is cleaner than documenting it in README.
**Date:** Phase D Part 2 QA Pass 4

### D023 — Verifier runs inside semaphore when synth_provider is Ollama
**Decision:** When synth_provider is "ollama", the Verifier runs inside
the research semaphore after each Researcher completes, before the
semaphore is released. When synth_provider is "anthropic", the Verifier
runs outside the semaphore concurrently with subsequent research
questions (original D010 behaviour).
**Rationale:** The Verifier uses synth_llm; serialise when synth_provider
is ollama. Ollama serialises LLM requests internally. Running Verifier
calls outside the semaphore pushes Ollama past its 60s read timeout and
crashes research workers. Serialising the Verifier with the semaphore
prevents queue buildup at the cost of small additional latency per
question. Anthropic can handle true parallelism so the original concurrent
pattern is preserved for that provider.
**Date:** Phase D Part 2 QA Pass 4 live run fix

---

## Phase E — Knowledge Store and Persistence

### D024 — decompose() stays a function, not an Agent
**Decision:** Orchestrator.decompose() will not be promoted to a
Planner Agent in Phase E. The prompt moves to
prompts/tasks/decomposer.md per the D019 three-category update.
decompose() remains a function in orchestrator.py.
**Rationale:** decompose() does not have state, tools, or a loop. It
is a single-shot LLM call with a JSON parser. Wrapping it in an Agent
gives nothing except type inflation. The Agent abstraction is reserved
for things with loop semantics, tool use, and state.
**Date:** Phase E pre-flight review

### D025 — Knowledge store as tool family, not agent
**Decision:** Kuzu integration modelled as a tool family added to
agent tool sets. No KnowledgeStore Agent. Initial tool family:
kg_query_claims_for_topic, kg_check_contradiction,
kg_get_related_topics. Analyst gets additional write tools.
**Rationale:** 2026 best practice treats retrieval as a capability
distributed across agents, not centralised in a dedicated agent.
Consistent with existing architecture — Researcher already calls
tools. An Indexer or Knowledge Agent would centralise something that
should be distributed.
**Date:** Phase E pre-flight review

### D026 — Graph Verifier as second Verifier instance in Phase E
**Decision:** Phase E adds a Graph Verifier — same Agent class as the
web Verifier, different tool set (knowledge graph tools, no web
search). Runs after all research completes, before synthesis. Order:
graph verification first against existing knowledge graph; web
Verifier runs only on claims the graph could not resolve. AgentPool
gains one field.
**Rationale:** Verification and analysis are different jobs — is this
claim true vs what should the report say. Conflating graph
verification in Analyst makes Analyst's scope vaguer. Two clean
contracts are better than one vague one. Graph-first ordering reduces
cost and uses the more reliable source first. Graph evidence is
preferred when available because it carries verification provenance
from prior runs; web evidence is the fallback when the graph has
nothing to say. This is a reliability ordering, not a performance
optimisation — future contributors must not parallelise the two
verification passes.
**Date:** Phase E pre-flight review

### D027 — Durable execution (RunState) as Phase E pre-requisite
**Decision:** A RunState dataclass pickled after each pipeline stage
(decompose, research, reflect, synthesise, edit) must be implemented
before Phase E begins. Minimal option: no new dependency, resume from
last completed stage.
**Rationale:** Knowledge graph writes must be atomic with run
completion — a crash after research but before graph write loses
everything. Follow-up mode requires prior run state. HITL requires
pause and resume. Phase E is not meaningful without this foundation.
Durable execution is the single most important 2026 architectural
pattern to adopt before adding Phase E complexity.
**Date:** Phase E pre-flight review

### D028 — D019 prompt location policy: three categories
**Decision:** Supersedes D019. Three categories:
  1. Agent system prompts — prompts/<agent>.md. Non-interpolated,
     immutable across a session. Current: researcher, verifier, editor.
  2. Task prompts with stable structure — prompts/tasks/<name>.md.
     Substantive content, light interpolation (one or two named
     placeholders), not coupled to message-list construction.
     Promotion trigger: prompt exceeds 20 lines, or needs per-model
     variant, or needs independent versioning.
  3. Inline glue — stays in source. Heavy interpolation, tightly
     coupled to message history construction, parser-dependent.
     Examples: fallback synthesis, reflection prompts.
  Discriminator: how many distinct things the prompt depends on to
  be valid. One placeholder, stable structure → file. Three
  placeholders plus conditional message history shape → inline.
**Rationale:** Two-category D019 had a fuzzy boundary that caused
arguments at every borderline case. Three categories with an explicit
discriminator and a promotion trigger are stable.
**First application:** decompose() prompt moved to
prompts/tasks/decomposer.md. Loaded in Orchestrator.__init__ via pathlib;
FileNotFoundError raised if file is absent.
**Date:** Phase E pre-flight review

### D032 — Viewer fully inline, no CDN
**Decision:** The provenance viewer template contains no CDN-loaded
dependencies. All CSS and JS are inline. JSON is injected via
`<script type="application/json">` and parsed with `JSON.parse()` —
never `eval()` or innerHTML string interpolation.
**Rationale:** The viewer displays web-fetched data processed through
an LLM. A compromised CDN could run arbitrary code against this
data. Fully inline guarantees security and offline operation.
This is a permanent constraint — no future contributor should add
CDN dependencies to the viewer.
**Date:** HTML provenance viewer phase

### D033 — schema_version field on ProvenanceReport
**Decision:** ProvenanceReport includes `schema_version: str` set to
`"1.0"` at write time. The viewer reads this field and warns on
mismatch. Unknown fields are ignored gracefully.
**Rationale:** Phase E will add cross-report contradiction flags,
knowledge graph references, and corroboration depth to the provenance
schema. Without versioning, every Phase E schema change requires a
viewer audit. With versioning, additions are additive and the viewer
degrades gracefully until updated.
**Date:** HTML provenance viewer phase

### D034 — Viewer is infrastructure-class not throwaway
**Decision:** The provenance viewer template is versioned in git,
reviewed in commits, and treated as infrastructure. It needs tests
(integration via save_viewer()), an iteration story (template updated
atomically with schema changes), and ownership clarity (Lead Architect
owns it; comprehensive web UI post-Phase E will supersede or extend
it, not discard it).
**Rationale:** The viewer is the primary user-facing surface of the
project's differentiator. It is the first thing an evaluator sees.
Treating it as throwaway would repeat the pattern of shipping
infrastructure without a maintenance story.
**Date:** HTML provenance viewer phase

### D035 — RunState v1: checkpoint-per-stage, no skip-ahead
**Decision:** RunState is a dataclass serialised to JSON after each pipeline
stage (decompose, research, reflect, synthesise, edit). v1 always runs all
stages even when resuming — it preserves run_id for consistency but does not
skip completed stages. Skip-ahead resume logic is deferred to Phase E when
follow-up mode requires it.
**Schema:** run_id, current_stage, topic, questions,
accumulated_research_results, report_text, started_at, last_checkpoint_at.
**Rationale:** Phase E (knowledge graph, follow-up mode, HITL) requires
durable run state. Option (a) from D027 — minimal, no new dependency, fits
on one screen. Resist scope creep during implementation. Checkpoints written
to output/.checkpoints/, gitignored.
**Date:** RunState implementation
Stage-skipping resume implemented in Phase E Component 4. Follow-up mode implemented per D038.

### D036 — Observability hooks: JSON lines to file, no backend
**Decision:** log_event() writes structured JSON lines to output/.logs/events_YYYYMMDD.jsonl. Called at agent boundaries (researcher, verifier, editor complete; orchestrator pipeline start/complete). configure_observability() called once at startup in main(). log_event() is a no-op if not configured — observability never crashes the pipeline. No external backend in this phase — Phase H formalises with structured logging backends, dashboards, and cost tracking.
**Rationale:** Phase E debugging without traces will be miserable. Minimum viable observability added before Phase E complexity lands. JSON lines format is simple, appendable, and parseable with any tool. run_id links events to RunState checkpoints for correlation. --no-observability flag disables for runs where file logging is unwanted.
**Date:** Observability hooks implementation

---

## Phase E — Knowledge Store and Persistence

### D037 — Temporal handling in knowledge graph
**Decision:** Three requirements: (a) retrieved-date persisted on
every Claim node from the source's retrieved field; (b)
check_contradiction() returns both claims' timestamps as
claim_retrieved and contradicting_retrieved; (c) SUPERSEDES edge
added as the fifth relationship type (Claim SUPERSEDES Claim).
Heuristic population: same topic, same named entity, newer timestamp,
contradictory value → candidate supersession. Staleness threshold
configurable via knowledge_staleness_threshold_days in Config,
default 90 days. Graph Verifier treats claims more than this
threshold apart as potential staleness (unresolved) rather than
contradiction.
**Rationale:** The dominant failure mode in accumulating graph memory
is stale-data false contradictions, not wrong-data contradictions.
A provenance tool that generates false disputes trains users to ignore
disputes — the more the graph is used, the worse the signal. Fix is
cheap at schema-design time and expensive after the graph is
populated. Adding SUPERSEDES now avoids a graph migration later.
**Date:** Phase E design

### D038 — Follow-up mode bypasses decompose()
**Decision:** --follow-up RUN_ID loads prior RunState, extracts gap
questions from reflect() output, passes them directly to
research_all_async() without calling decompose(). decompose() stays
single-contract: topic → questions, always.
**Rationale:** Gap questions are already sub-questions. Feeding them
into decompose() creates a two-input-contract function and violates
D015's intent. Bypass is less code, cleaner, and respects the
single-contract principle.
**Date:** Phase E design
Implemented in Phase E Component 4. run_followup_async() in orchestrator.py.

### D039 — Analyst requires knowledge graph
**Decision:** Analyst is populated in AgentPool only when
knowledge_store != "none". No graph-free Analyst mode. Analyst field
on AgentPool: analyst: Agent = None.
**Rationale:** An Analyst without graph access has no information the
Editor lacks. Its distinct value is cross-run evidence: prior
contradictions, corroboration depth, source patterns across runs.
Without the graph it is a third agent processing single-run data —
the self-critique failure rejected in D010.
**Date:** Phase E design

### D040 — Analyst scope: claim_id-constrained restructuring advisor
**Decision:** The Analyst reads the synthesised report and the
provenance file and emits a list of recommendations — each one
pointing at a specific claim_id and naming a specific defect (low
confidence, thin sourcing, or an unsurfaced contradiction) — without
ever proposing new prose beyond a suggested qualifier phrase.
IT DOES NOT: rewrite the report directly (produces a JSON
recommendation list the Synthesiser applies); add new information
(works only from existing claims and graph); evaluate the research
question itself (does not judge whether the topic or approach was
correct).
Output schema: JSON list, each item: {type: qualify|strengthen|
surface_contradiction, claim_id, reason, suggested_qualifier (optional)}.
Runs after Editor, before final save. Populated only when
knowledge_store != "none".
**Rationale:** Scope locked before prompt drafting per D011 pattern.
The claim_id constraint is the structural limit that prevents Analyst
from drifting into Synthesiser territory — it can only speak about
claims that already exist.
**Date:** Phase E design

### D041 — Graph Verifier three-state handoff to web Verifier
**Decision:** Graph Verifier returns per-claim result:
resolved_confirmed, resolved_contradicted, or unresolved. Web
Verifier runs on unresolved claims only. resolved_confirmed and
resolved_contradicted claims do not go to the web Verifier.
"Unresolved" covers: no graph evidence, timestamps suggest staleness
(gap exceeds knowledge_staleness_threshold_days), or graph
unavailable.
**Rationale:** Concrete handoff boundary prevents ambiguity at
implementation time and ensures the two Verifiers are not
double-checking the same claims.
**Date:** Phase E design
Implemented in Phase E Component 3. graph_verify() in verifier.py handles the three-state result.

### D042 — kg_write_claim validates before writing
**Decision:** kg_write_claim rejects claims that are: empty text,
markdown headers (starts with #), LLM refusal phrases, longer than
500 characters, multi-paragraph, or sourceless. Uses the same
predicate as _is_valid_claim() in provenance.py. Returns rejected
status with reason rather than raising.
**Rationale:** The graph is permanent. Write-time validation is the
cheapest point to prevent permanent contamination. A claim that
passes _is_valid_claim() at extraction time may still arrive at
the graph write boundary via a code path that bypasses extraction —
the gate must exist at both points.
**Date:** Phase E design

### D043 — Analyst prompt in prompts/tasks/ with Config-driven thresholds
**Decision:** The Analyst Agent task prompt lives in prompts/tasks/analyst.md.
Threshold values (analyst_qualify_threshold, analyst_strengthen_source_types)
are substituted into the prompt at runtime via str.replace() before the
agent call, not hardcoded in the prompt file or in source code.
**Rationale:** Follows D028 (task prompts with interpolation in prompts/tasks/).
Config-driven thresholds allow operators to tune the Analyst without touching
source or prompt files. The substitution is simple string replacement; no
template engine is warranted for two values.
**Date:** Phase E Component 5

### D044 — Analyst filters claims to those with report_line set
**Decision:** analyse() filters the claims list to only those where
report_line is not None before constructing the prompt and looking up
claims by id. Claims without report_line are not passed to the agent and
cannot be targeted by recommendations.
**Rationale:** Recommendations require a valid line to modify. Passing
unanchored claims would either confuse the agent or result in
out-of-bounds line indices. The Analyst's job is line-level annotation;
claims that annotate_report_lines() could not anchor are not actionable.
**Date:** Phase E Component 5

---

## Testing

### T001 — Free providers as default for integration tests
**Decision:** Integration tests default to Ollama + Tavily. Anthropic-specific tests
are marked @pytest.mark.anthropic_integration and excluded from default integration runs.
**Rationale:** Running Anthropic tests costs money and hits rate limits. The pipeline
behaviour being tested is provider-agnostic. Anthropic-specific behaviour warrants
its own explicitly-run test suite.
**Date:** test_integration_smoke.py rewrite

### T002 — Patch at lookup site not definition site
**Decision:** Always patch at the module where the name is looked up.
patch("src.agent.builder.AnthropicClient") not patch("src.llm.anthropic_client.AnthropicClient")
**Rationale:** Python's unittest.mock patches the name in the namespace where it is used,
not where it is defined. Patching at the definition site has no effect on
already-imported references.
**Date:** Established during Phase A testing

### T003 — Growing test count as commit gate
**Decision:** pytest tests/ -m "not integration" -v must pass all existing tests before
every commit. Count grows with each phase — treat any reduction as a regression signal.
Started at 199. Current count maintained in CLAUDE.md.
**Rationale:** Prevents regressions from accumulating.
**Date:** Ongoing

---

## Provider & Model

### P001 — Repeated query detection
**Decision:** If the agentic loop produces the same search query twice, inject a
synthesis-forcing message instead of executing the search again.
**Rationale:** Smaller models (llama3.1) sometimes loop on the same query when they
can't synthesise from the results. Without detection, this exhausts max_iterations
and produces a poor fallback.
**Date:** Phase A debugging

### P002 — Fallback synthesis on max iterations
**Decision:** If a question hits max_iterations with accumulated results, attempt
a standalone synthesis call rather than returning a failure string.
**Rationale:** A question that searched multiple times likely has useful content
accumulated even if no clean answer was found. Fallback synthesis rescues these
questions and produces shorter but usable answers.
**Date:** Phase A

### P003 — Comparative questions are harder for smaller models
**Decision:** Documented as a known issue. Phase G will add prompt variants that
rephrase comparative questions into two simpler questions for weaker models.
**Rationale:** "How does X compare to Y" requires holding two concepts simultaneously.
Llama3.1 hits max iterations on these more often than on factual questions.
**Date:** Phase A observation

---

## Project Management

### M001 — Claude Code for mechanical changes, this conversation for architecture
**Decision:** Structural refactors, commenting passes, and file generation go to
Claude Code. Architectural decisions, design discussions, and quality assessments
stay in this conversation.
**Rationale:** Claude Code is better at mechanical multi-file changes with immediate
feedback loops. This conversation is better at holding architectural context and
making tradeoffs.
**Date:** Ongoing

### M002 — Roadmap as living document
**Decision:** Roadmap is regenerated after every significant architectural decision,
not just at phase boundaries.
**Rationale:** A static roadmap diverges from reality quickly.
**Date:** Ongoing

### M003 — CLAUDE.md as Claude Code briefing
**Decision:** CLAUDE.md in project root contains architecture, commands, conventions,
and current phase context for Claude Code.
**Rationale:** Claude Code starts each session without conversation context. CLAUDE.md
is read automatically and provides the persistent briefing.
**Date:** Pre-Phase C

### M004 — Decision log maintained throughout development
**Decision:** DECISIONS.md records all significant architectural and design decisions
with rationale. Updated whenever a significant decision is made.
**Rationale:** Decisions made mid-session are easily forgotten. The log provides
context for future contributors and prevents re-litigating settled decisions.
**Date:** Mid-project retrospective

### M005 — Strategic goal: build a thing people use while learning
**Decision:** Project goal confirmed as building a genuinely usable tool, not purely
a learning exercise. Roadmap rebalanced: HTML provenance viewer and read_url tool
moved up to immediately after Phase D Part 2. Dockerfile/pipx packaging added before
Phase H. One concrete user story (journalist/analyst/paralegal workflow) to be
identified to guide Phase D Part 2 and viewer design.
**Rationale:** The provenance pipeline is the primary differentiator — making it
visible to evaluators is the highest priority user-facing work. Generic "research"
is what everyone else does; "auditable research" is the defensible position.
**Date:** Mid-project strategic review

### M006 — User stories: primary, secondary, tertiary
**Decision:** Three user stories adopted in priority order. Primary
drives all prioritisation decisions when items compete. Secondary and
tertiary inform design but do not override primary.

Primary — Policy Analyst (B):
  A policy analyst building a briefing document from public sources
  wants a structured report with traceable evidence chains so they
  can defend every claim if challenged.
  Drives: provenance viewer, report_line wiring, confidence scoring
  calibration, disputed claims display.

Secondary — Journalist (A):
  A journalist fact-checking claims in a press release or public
  statement wants a structured research brief with flagged disputed
  claims and source citations, produced in under five minutes.
  Drives: verification and disputed claims design, ⚠️ flags in
  reports, verification_status in provenance file.

Tertiary — Developer/Researcher (C):
  A developer or technical researcher evaluating an unfamiliar
  technology wants a comprehensive report covering specifications,
  comparisons, limitations, and community maturity in a single run.
  Drives: Phase F tool breadth (read_url, arxiv_search), output
  mode depth.

**Rationale:** Without a primary user story the roadmap is unrankable —
every pending item has a plausible case. Primary B maps directly to
the provenance differentiator. Secondary A drives the verification
features that differentiate this tool from general research assistants.
Tertiary C is easiest to demonstrate today and drives tool breadth.
Secondary A is ranked above C because A has more direct influence on
the differentiating features even though C is easier to demonstrate.
**Supersedes:** M005 open to-do ("one concrete user story to be
identified") — that to-do is now resolved.
**Date:** Phase D completion / Principal Reviewer strategic review

### M007 — report_line match rate baseline and optimisation deferred
**Decision:** report_line wiring marked complete at 59% overall match rate
(baseline measured May 2026 across three reference topics: nuclear
fusion energy 65%, electrosmith daisy seed 43%, large language model
training 69%). Distribution: 17% anchored, 43% paraphrased, 20%
omitted, 21% not_attempted.
Further improvement deferred to a dedicated optimisation phase after
Phase E. Candidates: embedding similarity matching, stronger synthesiser
anchor instructions, or constrained decoding. not_attempted claims are
correctly represented in the provenance file — they reflect synthesiser
paraphrasing beyond matcher recovery, not a pipeline failure.
**Rationale:** Diminishing returns from keyword matching do not justify
the complexity cost at this stage. The four synthesis_status values
already give the analyst full signal about each claim's traceability.
**Date:** report_line wiring completion, May 2026
