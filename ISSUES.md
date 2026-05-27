# Research Agent — Issues Log

Single source of truth for all issues found in QA passes and live
runs. Do not duplicate issue status in CLAUDE.md or PROJECT_CONTEXT.md
— those files reference this one.

## Schema

| Field | Values |
|-------|--------|
| ID | Sequential: I001, I002, ... |
| Severity | High, Medium, Low |
| Area | src path or component |
| Issue | One-line description |
| Found | QA pass or live run |
| Status | Open, Deferred, Closed |
| Fixed In | Blank if Open, target phase if Deferred, pass name if Closed |

Severity tracks impact if unresolved, not effort to resolve.
Issues that become permanent policies migrate to DECISIONS.md.
Closed issues remain in the file — history is more valuable than
a clean table.

## Current State (updated at phase boundaries)

Open: 0 High, 0 Medium, 0 Low
Deferred: 0 High, 2 Medium (I003, I004), 0 Low
Last updated: Phase D close

Status values: Open | Deferred | Closed
Fixed In: blank for Open, target phase for Deferred, pass name for Closed.

grep examples:
  grep "| Open |" ISSUES.md        — all open issues
  grep "| Deferred |" ISSUES.md    — all deferred issues
  grep "| High |" ISSUES.md        — all high severity issues

| ID | Severity | Area | Issue | Found | Status | Fixed In |
|----|----------|------|-------|-------|--------|----------|
| I001 | High | agent/editor.py | ReadTimeout not caught — editor crash kills pipeline and discards all research | Pass 3 live run | Closed | Pass 4 |
| I002 | Medium | agent/verifier.py | Verifier runs Ollama calls outside semaphore — causes timeouts when provider is Ollama | Pass 3 live run | Closed | Pass 4 |
| I033 | High | agent/editor.py | Editor did not catch ReadTimeout — pipeline crashed on Ollama timeout | Pass 4 live run | Closed | Pass 4 |
| I034 | Medium | agent/orchestrator.py | Verifier ran outside semaphore with Ollama — caused timeout cascades on research workers | Pass 4 live run | Closed | Pass 4 |
| I003 | Medium | agent/tools.py | Module-level globals for search config block concurrent FastAPI request handlers | Pass 3 QA | Deferred | Phase I |
| I004 | Medium | agent/orchestrator.py | Orchestrator.run() calls asyncio.run() — raises RuntimeError in async contexts | Pass 1 QA | Deferred | Phase I |
| I005 | High | agent/researcher.py | System prompt bypassed — agent.llm.chat() called directly instead of agent.chat() | Pass 1 QA | Closed | Pass 1 |
| I006 | High | agent/orchestrator.py | Single worker failure aborted entire pipeline — no return_exceptions=True | Pass 1 QA | Closed | Pass 1 |
| I007 | High | output/provenance.py | Verifier outcome never reached provenance file — verified: bool flattened to two states | Pass 1 QA | Closed | Pass 3 |
| I008 | High | agent/verifier.py | _is_refuted substring match flipped "not refuted" to refuted | Pass 3 QA | Closed | Pass 3 |
| I009 | High | output/formatter.py | XSS fix double-encoded code blocks — html.escape() before markdown rendering | Pass 3 QA | Closed | Pass 3 |
| I010 | High | output/writer.py | Index file write lost concurrent updates — PID-only tmp path, no file lock | Pass 3 QA | Closed | Pass 3 |
| I011 | High | agent/researcher.py | Malformed tool input raised AttributeError — no guard in researcher | Pass 3 QA | Closed | Pass 3 |
| I012 | High | agent/orchestrator.py | reflect() and decompose() crashed on unexpected JSON shapes | Pass 3 QA | Closed | Pass 3 |
| I013 | High | llm/retry.py | APIStatusError in isinstance tuple made all SDK errors retryable including bad key | Pass 4 QA | Closed | Pass 4 |
| I014 | Medium | agent/editor.py | Editor accepted refusal message as valid report — 100-char floor too low | Pass 1 QA | Closed | Pass 1 |
| I015 | Medium | agent/editor.py | SequenceMatcher autojunk produced near-zero ratio on repetitive content | Pass 4 QA | Closed | Pass 4 |
| I016 | Medium | agent/editor.py | Editor accepted preamble glued to report — original preserved as substring | Pass 3 QA | Closed | Pass 4 |
| I017 | Medium | agent/verifier.py | Verifier parse failure marked verified=True — inverted logic on failure paths | Pass 3 QA | Closed | Pass 3 |
| I018 | Medium | agent/verifier.py | Verifier sources appended without URL deduplication | Pass 3 QA | Closed | Pass 3 |
| I019 | Medium | agent/verifier.py | No repeated-query guard — same query burned max_iterations searches | Pass 3 QA | Closed | Pass 3 |
| I020 | Medium | agent/orchestrator.py | Planner Agent built and loaded but never called | Pass 2 QA | Closed | Pass 2 |
| I021 | Medium | agent/orchestrator.py | Inline researcher fallback diverged from agent loop | Pass 2 QA | Closed | Pass 2 |
| I022 | Medium | output/formatter.py | XSS in HTML/PDF — report content interpolated without escaping | Pass 2 QA | Closed | Pass 2 |
| I023 | Medium | agent/tools.py | Anthropic search model hardcoded — not configurable | Pass 2 QA | Closed | Pass 2 |
| I024 | Medium | output/writer.py | Index file write not concurrency-safe | Pass 2 QA | Closed | Pass 2 |
| I025 | Medium | agent/verifier.py | Malformed tool input raised KeyError in verifier | Pass 2 QA | Closed | Pass 2 |
| I026 | Medium | agent/researcher.py | search_count excluded Verifier searches — under-counted billed work | Pass 4 QA | Closed | Pass 4 |
| I027 | Medium | agent/researcher.py | Malformed-input handler continued without corrective messages — wasted iterations | Pass 4 QA | Closed | Pass 4 |
| I028 | Low | output/writer.py | output/index.md.lock accumulates and never cleaned up | Pass 4 QA | Closed | Pass 4 |
| I029 | Low | output/formatter.py | bleach and markdown shared one ImportError block — failure mode ambiguous | Pass 4 QA | Closed | Pass 4 |
| I030 | Low | agent/builder.py | path.read_text() used platform default encoding — UnicodeDecodeError on Windows | Pass 3 QA | Closed | Pass 3 |
| I031 | Low | llm/retry.py | Anthropic exceptions matched by string name — silent failure on SDK rename | Pass 3 QA | Closed | Pass 3 |
| I032 | Low | agent/builder.py | Verifier max_iterations hard-coded — not tunable from Config | Pass 4 QA | Closed | Pass 4 |
