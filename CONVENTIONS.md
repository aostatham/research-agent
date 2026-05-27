# Research Agent — Conventions

A reference document for all collaborators: Lead Architect (Sonnet),
Principal Reviewer (Opus), Adversarial QA (Opus), and Claude Code.
Read this before contributing to the project.

Full architectural context: PROJECT_CONTEXT.md
Full decision history: DECISIONS.md
Claude Code instructions: CLAUDE.md

---

## Team Roles

Andrew (Product Owner)
  Defines requirements. Evaluates real output. Makes all strategic
  decisions. All work ultimately serves his judgement.

Lead Architect (Sonnet — main conversation in this Project)
  Maintains architectural context across sessions. Designs phases
  before implementation. Generates Claude Code prompts. Evaluates
  QA findings. Maintains all context documents. Day-to-day design
  conversation with Andrew.

Principal Reviewer (Opus — separate chat in this Project)
  Periodic architecture reviews at phase boundaries and before major
  changes. Reviews Lead Architect designs before Claude Code implements
  them. Checks current best practice. Does not do day-to-day work.

Adversarial QA (Opus — separate chat in this Project)
  Finds bugs and weaknesses after each phase completes. Operates
  adversarially — given source files and a test count, no context.
  Does not do day-to-day work.

Claude Code (terminal)
  Implements what the Lead Architect specifies. Reads CLAUDE.md
  automatically on each session. Never makes architectural decisions.
  Never begins work without a written prompt from the Lead Architect.

---

## Handoff Rules

Lead Architect → Principal Reviewer
  Trigger: before implementing any major new phase or architectural change.
  What to hand off: a structured design document (see format below).
  Andrew pastes it into the Principal Reviewer chat.
  Findings come back to the Lead Architect for evaluation.
  Never start implementing before the Principal Reviewer has signed off.

Lead Architect → Adversarial QA
  Trigger: after a phase is complete and all tests pass.
  What to hand off: a completion brief (see format below).
  Andrew initiates the QA chat with source files attached.
  Findings come back to the Lead Architect for evaluation.
  Never mark a phase complete before the QA pass.

Lead Architect → Claude Code
  Trigger: whenever implementation work is needed.
  What to hand off: a written prompt (see format below).
  Results (test counts, summaries) come back to the Lead Architect.

Principal Reviewer → Lead Architect
  Deliver findings as a structured review document (see format below).
  The Lead Architect evaluates and decides what to act on.

Adversarial QA → Lead Architect
  Deliver findings as a structured QA report (see format below).
  The Lead Architect evaluates and decides what to fix and when.

---

## Document Formats

### Principal Reviewer Design Handoff

Used by: Lead Architect when handing a design to the Principal Reviewer.

  Phase: [phase name and number]
  Status: proposed — not yet implemented
  Author: Lead Architect

  Summary
  [2-3 sentences on what this phase does and why]

  Decisions
  [list of key design decisions with rationale, referencing DECISIONS.md
  entry IDs where they exist]

  Files affected
  [list of files to be created or modified]

  Open questions
  [anything the Lead Architect is uncertain about and wants reviewed]

  Review requested
  [specific questions for the Principal Reviewer to answer]


### Principal Reviewer Findings

Used by: Principal Reviewer when returning findings to the Lead Architect.

  Phase reviewed: [phase name]
  Verdict: approved / approved with conditions / requires redesign

  Findings
  [numbered list: severity (High/Medium/Low), file if applicable,
  issue, recommended fix]

  Conditions for approval (if any)
  [what must change before implementation proceeds]

  Best practice notes
  [anything observed about current practice worth recording]


### Adversarial QA Completion Brief

Used by: Lead Architect when initiating an Adversarial QA pass.

  Phase: [phase name and number]
  Test count: [N] unit tests passing
  Commit: [hash]

  What was implemented
  [bullet list of new files and key changes — no architectural context]

  Find what is wrong. No other context.


### Adversarial QA Report

Used by: Adversarial QA when returning findings to the Lead Architect.

  Executive summary
  [3-5 sentences: overall verdict, most critical findings]

  High / Medium / Low findings
  [for each: severity, file and line, issue description, fix recommendation,
  runtime-verified or needs verification]

  Summary table
  | # | Severity | File | Issue |


### Claude Code Prompt

Used by: Lead Architect when sending work to Claude Code.

  Test baseline: [N] unit tests passing. All must pass before every
  commit. Count must not decrease.

  Read CLAUDE.md before starting. [one commit per step / one commit
  for this change]. Run pytest tests/ -m "not integration" -v after
  every commit before proceeding.

  [STEP N or FIX N — short title]
  [file(s) affected]
  [exact specification of what to implement]
  [exact specification of tests to add or update]
  Commit: [imperative commit message]

Rules for Claude Code prompts:
- Plain text only. No markdown headers, no code fences around the prompt itself.
- Every step specifies files, behaviour, and tests explicitly.
- Commit message on every step.
- Baseline test count stated at the top of every prompt.
- One concern per commit.

---

## Document Responsibilities

CLAUDE.md
  Owner: Lead Architect. Read automatically by Claude Code on every
  session. Authoritative for: Claude Code instructions, test conventions,
  code conventions, commit style, and architectural constraints.
  Updated after every phase completes or any structural change.

DECISIONS.md
  Owner: Lead Architect. Records all significant architectural and
  design decisions with rationale, ordered chronologically. See below
  for entry format. Updated continuously — not just at phase boundaries.

PROJECT_CONTEXT.md
  Owner: Lead Architect. Full project context for handoffs and briefings.
  Updated after every phase completes.

README.md
  Owner: Lead Architect. User-facing documentation. Updated when
  user-visible behaviour changes.

CONVENTIONS.md (this file)
  Owner: Lead Architect. Shared process reference for all collaborators.
  Updated when team process changes.

prompts/
  Owner: Lead Architect (design), Claude Code (implementation).
  System prompts for each agent, versioned in git. Changes to prompts
  are architectural decisions and must be recorded in DECISIONS.md.

---

## Decision Log Conventions

File: DECISIONS.md

Entry format:
  ### [PREFIX][N] — [short title]
  Decision: [what was decided]
  Rationale: [why]
  Date: [phase or session]

Prefix key:
  A — Architecture
  S — Search
  O — Output
  K — Knowledge and persistence
  E — Evidence layer
  D — Phase D agent architecture
  T — Testing
  P — Provider and model
  M — Project management

Add an entry for every decision that: introduces a new pattern,
overrides a previous decision, resolves a design ambiguity, or records
a non-obvious constraint discovered at runtime.

Never re-litigate a recorded decision without a superseding entry.

---

## Code, Test, and Commit Conventions

These are defined in full in CLAUDE.md. Summary for non-Claude Code
collaborators:

- One concern per commit. Imperative subject line. No Co-Authored-By.
- Type hints and docstrings on all public functions.
- Unit test count must not decrease across any commit.
- All external clients mocked in unit tests — no real API calls.
- Patch at the lookup site, not the definition site.
- New config fields go in Config dataclass. New CLI flags go in parse_args().
- New agent system prompts go in prompts/ as .md files.

---

## Architectural Constraints

These constraints are settled. Do not re-litigate without a superseding
DECISIONS.md entry. Full rationale for each is in DECISIONS.md.

- LLM calls go through LLMClient abstract base — never call provider
  SDKs directly from agent or pipeline code.
- Agent system prompts are passed as the native system parameter, not
  prepended to the messages list (D007).
- Agent.chat() is the only place system= is injected — never call
  agent.llm.chat() directly from agent implementation code (D007, H1 fix).
- Web searches always use the configured search provider regardless of
  LLM provider — Ollama cannot search (S001).
- Anthropic web search citations appear on text blocks, not tool_result
  blocks (S004).
- asyncio.run() must not be called from inside an already-running event
  loop. Orchestrator.run() is a CLI wrapper only. All async contexts
  call run_async() directly (D002).
- provenance.py has no imports from agent/ or llm/ — llm_client is
  passed as an argument (A006).
- EvidenceClaim and related types are TypedDict — not dataclasses,
  not Pydantic models (E001).
- max_workers default is 2 — safe ceiling for Ollama. Anthropic
  ceiling is 4+ (D001).