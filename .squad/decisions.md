# parity-zero Decisions

This file records meaningful architectural and product decisions for parity-zero.

Use short ADR-style entries.
Capture only decisions that future contributors or coding agents are likely to need.

---

## ADR-001: Start with a GitHub Action, not a GitHub App

**Status:** Accepted  
**Date:** 2026-03-27

### Decision
The first implementation of parity-zero will be a GitHub Action.

### Rationale
- Faster to scaffold and test
- Lower operational complexity
- Easier to adopt in a single repository
- Good fit for validating the reviewer wedge
- Avoids early complexity around app installation, permissions, and org-wide management

### Consequences
- Initial rollout is repo-by-repo
- Some org-wide control features will come later
- A GitHub App may still be introduced in a later phase if adoption and governance requirements justify it

---

## ADR-002: Build the reviewer before the dashboard

**Status:** Accepted  
**Date:** 2026-03-27

### Decision
The PR reviewer is the first product surface. The dashboard is a later surface.

### Rationale
- The product only matters if the reviewer is useful inside the developer workflow
- Dashboard-first development risks producing a reporting shell without a trusted control underneath
- Reviewer execution generates the telemetry needed for the control plane later

### Consequences
- Phase 1 focuses on PR review flow, findings quality, and structured outputs
- Dashboard work is intentionally delayed until reviewer data exists

---

## ADR-003: Structured JSON is the system contract

**Status:** Accepted  
**Date:** 2026-03-27

### Decision
Every parity-zero scan must emit structured JSON findings.

### Rationale
- Enables reliable ingestion, storage, and downstream analysis
- Decouples reviewer execution from future dashboard and governance features
- Makes output testable and versionable
- Prevents the system from relying only on markdown or loose prose

### Consequences
- Output schema changes must be treated carefully
- Tester review is required for contract changes
- Scribe updates are required when schema semantics change

---

## ADR-004: Use LLM-led reasoning with narrow deterministic guardrails

**Status:** Accepted  
**Date:** 2026-03-27

### Decision
parity-zero will use LLM-based reasoning as the primary Phase 1 reviewer path,
with deterministic checks kept narrow and supplemental.

### Rationale
- Phase 1 should prove the value of an AI reviewer, not drift into building
  another broad scanner
- LLM reasoning is the main source of contextual review value in pull requests
- Narrow deterministic guardrails can still add precision where the signal is
  obvious and low-noise

### Consequences
- The LLM reviewer remains the MVP in Phase 1
- Deterministic checks should stay small, high-signal, and secondary
- Findings should distinguish high-confidence logic from contextual interpretation where possible
- Design must avoid presenting weak inference as certainty

---

## ADR-005: FastAPI is the initial backend choice

**Status:** Accepted  
**Date:** 2026-03-27

### Decision
The initial ingestion and control plane backend will be built with FastAPI.

### Rationale
- Fast to scaffold
- Good fit for JSON-centric APIs
- Easy to pair with Pydantic-style schemas and validation
- Practical choice for an early control plane backend

### Consequences
- Python becomes the likely initial backend language
- API contracts should be explicit and strongly shaped around scan ingestion and retrieval

---

## ADR-006: Postgres is the findings store

**Status:** Accepted  
**Date:** 2026-03-27

### Decision
Structured scan results and findings metadata will be stored in Postgres.

### Rationale
- Good fit for relational reporting and query flexibility
- Supports trend analysis, filtering, repo/team views, and governance queries
- Familiar and operationally simple for an MVP

### Consequences
- Findings schema should be designed with reporting use cases in mind
- Raw artifacts may still be stored separately if needed later

---

## ADR-007: Repo memory is a first-class project asset

**Status:** Accepted  
**Date:** 2026-03-27

### Decision
Durable repo memory will be maintained deliberately through `.squad/` context files and decision records.

### Rationale
- This repo will be worked on repeatedly by AI coding assistants and humans
- Context drift is a major risk in AI-assisted implementation
- Design intent, contracts, and tradeoffs must remain easy to recover

### Consequences
- The Scribe is a core agent, not an optional one
- Documentation must stay concise and decision-oriented
- Changes that alter assumptions or contracts must update repo memory

---

## ADR-008: Phase 1 repository layout uses three top-level Python packages

**Status:** Accepted  
**Date:** 2026-03-27

### Decision
The Phase 1 scaffold uses three top-level Python packages: `reviewer/`, `api/`, and `schemas/`, plus a `tests/` directory.

### Rationale
- `schemas/` is the shared contract layer — both `reviewer/` and `api/` import from it, enforcing ADR-003
- `reviewer/` is a standalone package that can run inside a GitHub Action without the API
- `api/` is a thin FastAPI stub that depends only on `schemas/` — it does not import reviewer internals
- This layout keeps the reviewer and ingestion API loosely coupled via the JSON contract
- `tests/` mirrors the package structure with `test_schemas.py`, `test_reviewer.py`, and `test_api.py`

### Consequences
- Adding new reviewer checks only touches `reviewer/`
- Schema changes are visible and central — they naturally trigger review
- The API can evolve independently toward Phase 2 persistence without affecting the reviewer

---

## ADR-009: Decision enum and ScanMeta base model in findings contract

**Status:** Accepted  
**Date:** 2026-03-27

### Decision
The findings contract adds a `Decision` enum (`block`, `warn`, `pass`) and a `ScanMeta` base model that `ScanResult` inherits from.

### Rationale
- A scan-level decision field is needed for the reviewer to express an overall assessment, separate from individual finding severities
- Extracting scan metadata into a dedicated `ScanMeta` base class makes the metadata contract explicit and independently testable
- Using inheritance preserves the existing flat JSON shape — no breaking change to the ingestion contract
- The `decision` field defaults to `pass`, so existing callers and payloads without it remain valid

### Consequences
- `ScanResult` now inherits from `ScanMeta` instead of `BaseModel` directly
- All ScanResult payloads include a `decision` field (defaulting to `pass`)
- Consumers can validate metadata independently via `ScanMeta`
- The ingestion API may need to handle the new `decision` field if present in payloads

---

## ADR-010: Secrets detection as second deterministic check category

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
Add a narrow, high-confidence `secrets` deterministic check targeting obvious hardcoded secret patterns: AWS access key IDs, PEM private key headers, and GitHub personal access / app installation tokens.

### Rationale
- Hardcoded secrets are a high-value, low-noise finding category with distinctive formats
- These three patterns (AKIA prefix, PEM headers, ghp_/ghs_ prefix) have very low false-positive rates
- Secrets detection supports the reviewer wedge without expanding into broad SAST territory
- The `secrets` category already exists in the findings taxonomy
- Keeping patterns narrow aligns with ADR-004 (narrow deterministic guardrails)

### Consequences
- `reviewer/checks.py` now detects two categories: `insecure_configuration` and `secrets`
- Findings use `Category.SECRETS` with `Severity.HIGH` / `Confidence.HIGH`
- Only three pattern families are covered — this is intentionally narrow
- mock_run output now includes both category types

### Known limitations
- Does not detect secrets from other providers (GCP, Azure, Stripe, etc.)
- Does not detect encoded, obfuscated, or multi-line secrets
- Does not support path-based suppression (e.g. test fixtures or example files)
- Does not detect generic high-entropy strings (intentionally avoided to reduce noise)

### Later considerations
- Path-based suppression or annotation-based exclusion for test fixtures
- Additional provider-specific patterns may be added incrementally
- Integration with dedicated secret scanning tools may reduce the need for in-reviewer detection
- Confidence levels could vary by pattern specificity in future iterations

---

## ADR-011: PRContent abstraction for reviewer inputs

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
Introduce `PRFile` and `PRContent` dataclasses in `reviewer/models.py` as the primary input structure for the analysis engine, replacing direct use of `dict[str, str]`.

### Rationale
- Decouples the engine interface from raw dict shape
- Establishes a seam for future metadata enrichment (file status, language, diff hunks) without changing the engine signature
- Makes the reviewer input contract explicit and testable
- `from_dict()` / `to_dict()` provide backward compatibility during Phase 1 transition
- The engine accepts both `PRContent` and `dict[str, str]` for backward compatibility

### Consequences
- `engine.analyse()` now accepts `PRContent` (preferred) or `dict[str, str]` (legacy)
- `action.py` uses `PRContent.from_dict()` for both `run()` and `mock_run()`
- Checks and reasoning modules still receive `dict[str, str]` internally — the engine converts via `to_dict()`
- No changes to the ScanResult JSON contract

### Later considerations
- `PRFile` may later carry `status` (added/modified/renamed), `language`, or diff hunk metadata
- `PRContent` construction should eventually be driven by the GitHub changed-files API response
- The conversion to `dict[str, str]` inside the engine is a Phase 1 convenience — later, checks and reasoning may operate on `PRFile` directly
- GitHub API integration for file content fetching should produce `PRContent` as its output

---

## ADR-012: Phase 1 risk scoring is intentionally coarse and temporary

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
The current Phase 1 risk scoring model (severity weights: high=25, medium=15, low=5; WARN threshold at 25) is accepted as intentionally coarse and temporary for MVP flow validation.

### Rationale
- Phase 1 needs a working decision derivation to validate the full reviewer output path
- A simple weight-based model is sufficient to demonstrate PASS/WARN behaviour
- Premature refinement of scoring would pull effort away from the reviewer wedge
- The model is explicitly documented as temporary to prevent it from being treated as a final design

### Consequences
- The scoring model is adequate for Phase 1 flow validation but not for production severity handling
- Current weighting does not account for confidence levels
- Repeated low-severity findings accumulate linearly, which may not reflect real risk

### Later refinements needed
- Severity weighting may need non-linear scaling
- Confidence should influence effective severity or weight
- Repeated low-severity accumulation may need diminishing returns
- Distinction between `WARN` and future `BLOCK` behaviour needs explicit policy rules
- Policy-mode-aware decisioning (e.g. advisory vs enforcement) is a Phase 3 concern
- Threshold values should be validated against real reviewer output data

---

## ADR-013: Deterministic checks are a supporting signal layer, not the primary product value

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
Deterministic checks (secrets, insecure configuration patterns) are repositioned as a **supporting signal layer**.  The primary product value comes from contextual, repo-aware security review.

### Rationale
- The product thesis is an AI reviewer that reasons like a security engineer, not a deterministic scanner with an AI wrapper
- Deterministic checks provide high-confidence anchoring signals but cannot detect architectural issues, logic bugs, or context-dependent vulnerabilities
- Leaning too heavily into deterministic checks risks drifting the product into "just another scanner" territory
- Contextual review over PR delta + repo baseline is the differentiating value

### Consequences
- Existing deterministic checks (insecure configuration, secrets) remain operational as early confidence anchors
- New deterministic checks should only be added when they provide clear, high-signal value
- The review engine architecture explicitly positions deterministic checks as one input to the contextual review engine
- Product and engineering decisions should prioritise contextual review capabilities over expanding regex checks

---

## ADR-014: parity-zero is moving toward a repo-aware contextual review model

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
parity-zero is evolving toward a **repository-aware contextual review model** where PR reviews operate in the context of a repository security baseline and accumulated review memory.

### Rationale
- Stateless, file-by-file scanning misses architectural context, convention violations, and repo-specific security patterns
- A security engineer reviews code with knowledge of the codebase — parity-zero should too
- Repository-aware review reduces false positives and increases finding relevance
- This direction differentiates parity-zero from commodity scanning tools

### Consequences
- A baseline repository profiler is being introduced to build repo security profiles
- A PR context builder combines changed files with baseline context for review
- The review engine is architecturally positioned to consume repo context
- Full implementation is incremental — Phase 1 introduces foundations, not complete functionality

---

## ADR-015: Baseline repository review provides context for PR review

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
A **baseline repository profiler** generates a lightweight repository security profile that provides context for subsequent PR reviews.

### Rationale
- PR review in isolation cannot reason about the broader repository context
- Detecting languages, frameworks, sensitive paths, and auth patterns enables focused review
- A baseline profile is a prerequisite for context-aware reasoning
- The profiler should be lightweight and enrichable over time, not a comprehensive scanner

### Consequences
- `RepoSecurityProfile` and `BaselineScanResult` models are introduced
- A baseline profiler stub (`reviewer/baseline.py`) performs basic detection
- Phase 1 detection is intentionally minimal: languages, frameworks, sensitive paths
- Later iterations will enrich profiling with deeper analysis
- The profiler is a context generator, not a findings generator

---

## ADR-016: Persistent security memory/context is a first-class design requirement

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
Persistent security memory is a **first-class architectural concept** in parity-zero.  Review context should accumulate over time so that later reviews become increasingly repo-aware.

### Rationale
- Stateless reviews lose knowledge between runs
- Accumulated context enables detection of recurring patterns, posture drift, and convention violations
- Memory enables the reviewer to avoid repeating false positives on known-safe patterns
- This is a prerequisite for the reviewer to behave like a security engineer who knows the codebase

### Consequences
- `ReviewMemory` and `ReviewMemoryEntry` models are introduced as foundational structures
- Full persistence (database-backed storage and retrieval) is deferred to Phase 2+
- Phase 1 defines the data shapes and integration points
- `PullRequestContext` carries an optional memory reference for future use

### Future memory requirements
When persistent memory is fully implemented, it should track:
- baseline profile snapshots (versioned)
- prior findings themes and categories per repo
- accepted risks or exceptions
- recurring issue patterns by repo
- evolution of repository security posture over time
- policy/intent context where available

---

## ADR-017: Phase 1 risk scoring is intentionally coarse and temporary (reaffirmed)

**Status:** Accepted (reaffirmed)  
**Date:** 2026-03-28

### Decision
Reaffirms ADR-012.  The Phase 1 risk scoring model is intentionally coarse and temporary.  It is adequate for flow validation but not for production use.

### Rationale
- Same as ADR-012
- This reaffirmation explicitly captures that later scoring should account for:
  - confidence influence on effective severity
  - repeated low-severity accumulation (diminishing returns)
  - policy-aware behaviour (advisory vs enforcement)
  - future WARN vs BLOCK distinction
  - repo sensitivity/context influence on thresholds
  - baseline-aware scoring adjustments

### Consequences
- No changes to the current scoring model in this iteration
- The scoring model will need refinement as contextual review matures
- Policy-mode-aware decisioning remains a Phase 3 concern

---

## ADR-018: PullRequestContext combines PR delta with repo context and memory

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
A `PullRequestContext` model is introduced to combine PR delta information (changed files), baseline repository profile, and review memory into a single context object for the review engine.

### Rationale
- The review engine needs a unified context object rather than multiple separate inputs
- This establishes the seam for future enrichment without changing the engine signature
- Backward compatibility with `PRContent` and `dict[str, str]` is preserved
- The context builder pattern separates concern of context assembly from analysis

### Consequences
- `PullRequestContext` carries `PRContent`, optional `RepoSecurityProfile`, and optional `ReviewMemory`
- The engine accepts `PullRequestContext`, `PRContent`, or `dict[str, str]` for backward compatibility
- Phase 1 baseline and memory fields are typically None — they become populated as those capabilities mature
- No changes to the ScanResult JSON contract

---

## ADR-019: PullRequestContext is the canonical review engine input

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
`PullRequestContext` is now the **canonical input** to both the analysis engine and the contextual review layer.  The reasoning module (`run_reasoning`) accepts `PullRequestContext` directly so it can consume baseline profile and review memory.

### Rationale
- The contextual review layer needs access to baseline profile and review memory to produce context-aware notes
- Passing `PullRequestContext` directly avoids lossy conversion to `dict[str, str]` before the reasoning layer
- This makes the data flow explicit: engine normalises → passes full context → reasoning uses it
- Backward compatibility with `dict[str, str]` is preserved via automatic wrapping

### Consequences
- `run_reasoning()` now accepts `PullRequestContext` (preferred) or `dict[str, str]` (legacy compat)
- The engine passes the full `PullRequestContext` to `run_reasoning()` instead of raw dicts
- Callers using `dict[str, str]` or `PRContent` continue to work — the engine wraps them
- No changes to the ScanResult JSON contract

---

## ADR-020: Baseline-aware contextual review notes (first implementation)

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
The contextual review layer now produces **baseline-aware review notes** based on overlap between the PR delta and the repository security profile.

### Rationale
- Context-aware review is the primary product direction (ADR-014)
- Making baseline profile materially influence review output is the first step toward repo-aware review
- Heuristic path-based and pattern-based notes provide value without requiring full LLM integration
- Notes are informational and do not create fake certainty or inflate findings

### What is implemented
- Changed files overlapping baseline sensitive paths → contextual note about sensitive areas
- Changed files in auth-related path segments → contextual note about auth areas
- Baseline auth patterns (JWT, OAuth, etc.) → contextual note about existing auth mechanisms
- Framework context from baseline → contextual note about framework conventions
- Multi-language context → contextual note about cross-language boundaries
- Review memory entries with categories matching inferred path categories → historical awareness notes
- Relevant memory summaries surfaced as prior review notes (bounded to avoid noise)

### Consequences
- Contextual review notes are now materially influenced by repository context
- Notes appear in `AnalysisResult.reasoning_notes` and flow into the review output
- Notes are informational only — they do not produce findings or affect risk scoring
- The JSON contract is unchanged
- Deterministic checks continue to operate independently as the supporting signal layer

### Known limitations and deferred concerns
- Contextual notes are heuristic-based, not full repository reasoning
- Notes are path-segment-based and may miss deeper semantic relationships
- Memory is modelled but not yet persistently stored (Phase 2+)
- Baseline context is lightweight; richer enrichment is needed later
- Context can influence review attention but does not yet influence scoring
- Scoring remains coarse and intentionally temporary (ADR-012, ADR-017)
- LLM-based reasoning is not yet connected — current notes are rule-derived
- Memory relevance matching is category-based; deeper content matching is deferred

---

## ADR-021: Introduce ReviewPlan as contextual review planning primitive

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
A lightweight `ReviewPlan` model and a `build_review_plan()` planner now bridge the gap between raw PR context and contextual review reasoning.

The planner derives structured review focus from `PullRequestContext` (PR delta + baseline profile + review memory) and produces a `ReviewPlan` that the reasoning layer consumes to generate plan-driven contextual notes.

### Rationale
- Context was influencing review notes via ad-hoc overlap checks scattered in the reasoning layer
- A single planning step makes review attention explicit, testable, and extensible
- The plan captures focus areas, review flags, sensitive/auth paths touched, relevant memory categories, and framework/auth-pattern context
- This separates the "what to focus on" decision from the "how to express notes" decision
- The planner is a natural integration point for future provider-backed reasoning

### What is implemented
- `ReviewPlan` dataclass in `reviewer/models.py` with explicit fields for focus areas, flags, path overlap, memory categories, framework/auth context, and reviewer guidance
- `reviewer/planner.py` with `build_review_plan(ctx)` function deriving focus from PR delta and context
- Path analysis helpers (`sensitive_path_overlap`, `auth_path_overlap`, `infer_path_categories`, `relevant_memory_entries`) moved to `planner.py` as canonical location, re-exported from `reasoning.py` for backward compatibility
- `reviewer/reasoning.py` refactored: when a `ReviewPlan` is provided, notes are generated from the structured plan rather than ad-hoc overlap checks
- `reviewer/engine.py` builds a `ReviewPlan` from context and passes it to the reasoning layer
- 69 new tests covering planner output, engine integration, flow stability, no-overclaiming, and backward compatibility

### Key design choices
- **Plan guides attention, does not claim vulnerabilities.** The plan influences which areas receive closer review; it does not produce findings or affect risk scoring.
- **Backward compatible.** Reasoning layer falls back to legacy overlap checks if no plan is provided. Helper functions re-exported for existing callers.
- **No schema change.** The `ScanResult` JSON contract is unchanged.
- **Lightweight.** The planner is heuristic-based and intentionally small. No policy engine or deep semantic analysis.

### Consequences
- Review attention is now structurally driven by context, not ad-hoc
- The planner is a natural point to later incorporate provider-backed planning (LLM reasoning about what to focus on)
- Focus areas and review flags are explicit and testable
- The JSON contract is unchanged
- Deterministic checks continue to operate independently

### Deferred concerns
- LLM-backed plan enrichment (provider integration phase)
- Plan-influenced risk scoring (plan currently informational only)
- Deeper memory relevance matching (content-level, not just category-level)
- Persistent memory storage and retrieval (Phase 2+)
- Plan-driven finding generation (requires provider reasoning)

---

## ADR-022: Introduce ReviewConcern as plan-informed contextual concern

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
A lightweight `ReviewConcern` model and a `generate_concerns()` function now produce **plan-informed contextual concerns** — areas that may deserve closer security attention based on ReviewPlan signals, baseline context, and review memory.

Concerns are **distinct from findings**.  They represent contextual observations, not proven issues.

### Rationale
- The reviewer should behave more like a security engineer: surfacing what deserves scrutiny, highlighting plausible concern areas, preserving uncertainty honestly
- ReviewPlan (ADR-021) captures structured review focus but did not yet produce actionable concern-level output
- Concerns bridge the gap between plan-level attention signals and developer-visible review output
- They prepare the way for future provider-backed deeper reasoning without requiring LLM integration now
- Phase 1 heuristic-based concern generation provides value within current constraints

### What is implemented
- `ReviewConcern` dataclass in `reviewer/models.py` with fields: category, title, summary, confidence, basis, related_paths
- `generate_concerns(plan, ctx)` in `reviewer/planner.py` deriving concerns from combinations of plan signals
- Concern generation rules:
  - Sensitive paths + auth paths touched → auth-sensitive concern (medium confidence)
  - Baseline auth patterns + auth paths changed → auth consistency concern (medium confidence)
  - Auth paths only (no sensitive overlap) → standalone auth concern (low confidence)
  - Sensitive paths only (no auth overlap) → configuration concern (low confidence)
  - Memory categories matching PR areas → recurring theme concern (low confidence)
  - Framework context + sensitive paths → framework convention concern (low confidence)
- `ReasoningResult` and `AnalysisResult` carry concerns alongside findings and notes
- `format_markdown()` renders concerns in a clearly separated "Review Concerns" section with an explicit disclaimer
- `mock_run()` returns concerns in its output dict
- 37 new tests covering generation, relevance, noise control, markdown output, no-overclaiming, and JSON contract stability

### Key design choices
- **Concerns are internal and markdown-only.** The ScanResult JSON contract is unchanged — concerns do not appear in the JSON payload. This avoids premature contract expansion.
- **Concerns preserve uncertainty honestly.** Confidence is capped at medium; vulnerability language is avoided; the markdown section includes an explicit "not proven findings" disclaimer.
- **Concerns do not affect scoring.** Risk score and decision remain derived from findings only (ADR-012, ADR-017).
- **No noise for weak context.** If the plan carries no meaningful signals (no sensitive paths, no auth areas, no relevant memory), no concerns are generated.
- **Backward compatible.** `format_markdown()` accepts optional concerns parameter; existing callers continue to work without changes.

### Consequences
- Review output now clearly distinguishes: deterministic findings, contextual review concerns, and contextual notes
- Developers see context-aware observations that help them understand why specific areas deserve attention
- The concern model is a natural integration point for future provider-backed reasoning
- The JSON contract is unchanged
- Risk scoring is unchanged

### Deferred concerns
- Provider-backed concern generation (LLM reasoning about what deserves attention)
- Concern-to-finding promotion (upgrading a concern to a finding when evidence supports it)
- Concern influence on scoring (if concerns should affect risk score, this needs explicit design)
- Concern aggregation across PRs (control plane feature, Phase 2+)
- Adding concerns to the JSON contract (if downstream consumers need machine-readable concerns)

---

## ADR-023: ReviewBundle — structured review evidence aggregation

**Status:** Accepted  
**Date:** 2026-03-28

### Context
PullRequestContext carries raw PR delta, baseline profile, and review memory.
ReviewPlan derives focus areas and guidance.  However, the contextual review
layer still consumed these as loosely connected inputs — paths, notes, and
flags — without a unified per-file evidence structure.

Moving toward richer contextual review (and eventually provider-backed
reasoning) requires a structured intermediate representation that gathers
the relevant evidence for each file under review together with the
surrounding context explaining why it matters.

### Decision
Introduce **ReviewBundle** and **ReviewBundleItem** as lightweight internal
models for structured review evidence aggregation.

- `ReviewBundleItem` captures a single changed file with: path, content,
  review reason (why it is in focus), applicable focus areas from the
  ReviewPlan, baseline context, memory context, and related paths.
- `ReviewBundle` collects items together with aggregate plan summary,
  framework context, and auth pattern context.

A builder module (`reviewer/bundle.py`) assembles the bundle from
PullRequestContext and ReviewPlan using simple, explainable heuristics.

### What is implemented
- `ReviewBundleItem` and `ReviewBundle` dataclasses in `reviewer/models.py`
- `build_review_bundle(ctx, plan)` in `reviewer/bundle.py` that:
  - Classifies each changed file by review reason (sensitive_path, auth_area, sensitive_auth, changed_file)
  - Derives per-file focus areas from plan/path intersection
  - Enriches items with baseline context (auth patterns, frameworks) when relevant
  - Enriches items with memory context (matching category entries) when available
  - Computes related paths from same-directory and shared-area heuristics
  - Carries plan guidance and aggregate baseline context
- Integration in `run_reasoning()` (ADR-021): bundle is built when a plan is present
- `ReasoningResult.bundle` and `AnalysisResult.bundle` carry the bundle through the flow
- 52 new tests covering creation, sensitive/auth classification, memory enrichment, weak context, flow stability, no-overclaiming, and JSON contract stability

### Key design choices
- **Bundle is internal only.** It does not appear in ScanResult or the JSON contract. This avoids premature contract expansion.
- **Bundle does not produce findings.** It aggregates evidence — it does not claim vulnerabilities or affect scoring.
- **Heuristic-based classification.** Review reasons and focus areas are derived from path segment matching and plan intersection, not AST or semantic analysis.
- **Bounded related context.** Related paths are capped at 3 per item; memory context at 3 entries per item.
- **Backward compatible.** Existing callers are unaffected; the bundle is carried as an optional field.
- **Phase 1 appropriate.** No AST parsing, code graph traversal, or provider-backed reasoning.

### Consequences
- The contextual review layer now operates on better structured review evidence per file
- Each file carries explicit annotation of why it is under review and what context is relevant
- The bundle provides a natural integration point for future provider-backed reasoning
- Concerns generation and notes can leverage bundle item context
- The JSON contract is unchanged
- Risk scoring is unchanged

### Deferred concerns
- Enriching bundle items with diff hunks (only changed lines, not full content)
- Adding symbol-level context (function/class names, imports)
- Route/middleware context from framework-specific analysis
- Repository graph signals (call graphs, dependency edges)
- Provider-backed semantic enrichment of bundle items
- Bundle persistence or caching across review runs
- Adding bundle information to the JSON contract (if downstream consumers need it)
- AST-based or code-graph-based related-file discovery

---

## ADR-024: ReviewObservation — per-file security review observations from ReviewBundle

**Status:** Accepted  
**Date:** 2026-03-28

### Context
ReviewBundle (ADR-023) gathers structured per-file evidence for contextual review.
ReviewConcern (ADR-022) produces plan-level observations about areas deserving
attention.  However, the reviewer did not yet produce targeted, per-file analysis
that explains *why a specific changed file* deserves scrutiny based on its gathered
context.

Moving toward semantically useful review analysis requires a layer that translates
per-file bundle evidence into reviewer-like observations — connecting focus areas,
baseline context, memory context, and review reasons into actionable notes.

### Decision
Introduce **ReviewObservation** as a lightweight dataclass representing a targeted
security review observation tied to a specific changed file.

- `ReviewObservation` carries: path, focus_area, title, summary, confidence, basis,
  related_paths.
- Observations are generated from ReviewBundle items by `generate_observations(bundle)`
  in a dedicated `reviewer/observations.py` module.
- Observations flow through `ReasoningResult.observations` and `AnalysisResult.observations`
  to `format_markdown()` where they appear in a dedicated "Review Observations" section.

### What is implemented
- `ReviewObservation` dataclass in `reviewer/models.py`
- `generate_observations(bundle)` in `reviewer/observations.py` deriving observations from
  ReviewBundleItem context:
  - Sensitive + auth combined item → boundary preservation observation (medium confidence)
  - Auth area with baseline auth patterns → auth flow consistency observation (medium confidence)
  - Auth area without baseline patterns → auth path observation (low confidence)
  - Sensitive path with framework context → framework secure defaults observation (low confidence)
  - Sensitive path without framework context → sensitive path observation (low confidence)
  - Item with memory context alignment → recurring attention area observation (low confidence)
  - Plain changed file with no signals → no observation (noise control)
- `ReasoningResult` and `AnalysisResult` carry observations alongside findings, concerns, and notes
- `format_markdown()` renders observations in a clearly separated "📋 Review Observations" section
  with an explicit "not findings or proven issues" disclaimer
- `mock_run()` returns observations in its output dict
- 48 new tests covering generation, relevance, noise control, markdown output, no-overclaiming,
  JSON contract stability, and full pipeline integration

### Key design choices
- **Observations are per-file and bundle-driven.** Unlike concerns (which are plan-level),
  observations are tied to specific files and derived from ReviewBundleItem evidence.  This makes
  them more targeted and specific.
- **Observations are internal and markdown-only.** The ScanResult JSON contract is unchanged —
  observations do not appear in the JSON payload.
- **Observations preserve uncertainty honestly.** Confidence is capped at medium; vulnerability
  language is avoided; the markdown section includes an explicit disclaimer.
- **Observations do not affect scoring.** Risk score and decision remain derived from findings only.
- **No noise for weak context.** Plain changed files with no sensitive/auth/memory signals produce
  no observations.
- **Observations are distinct from concerns.** Concerns are plan-level signals; observations are
  per-file bundle-derived analysis.  Both are distinct from findings.
- **Bounded output.** Maximum 10 observations per bundle to avoid excessive verbosity.
- **Backward compatible.** `format_markdown()` accepts optional observations parameter; existing
  callers continue to work without changes.

### Consequences
- Review output now clearly distinguishes three layers: findings (proven), concerns (plan-level),
  observations (per-file analysis)
- Developers and security engineers see targeted per-file notes explaining why closer scrutiny
  is warranted and what contextual basis supports that attention
- The observation model is a natural integration point for future provider-backed reasoning
- The JSON contract is unchanged
- Risk scoring is unchanged

### Deferred concerns
- Provider-backed semantic analysis to enrich observation quality beyond heuristics
- Observation-to-concern or observation-to-finding promotion logic
- Scoring impact from observations (if observations should influence risk score)
- Observation aggregation across PRs (control plane feature, Phase 2+)
- Adding observations to the JSON contract (if downstream consumers need them)
- Richer observation templates using diff hunks or symbol-level context

---

## ADR-025: Provider-agnostic reasoning runtime boundary

**Status:** Accepted  
**Date:** 2026-03-28

### Context
The parity-zero reviewer has established a structured pipeline: PullRequestContext →
ReviewPlan → ReviewBundle → concerns → observations → deterministic findings.  The next
step toward real semantic review is enabling provider-backed reasoning (GitHub Models,
external LLMs) without requiring live integration or credentials for default operation.

The pipeline needs a clean boundary between the reviewer's structured context and
external reasoning providers.

### Decision
Introduce a provider-agnostic reasoning runtime boundary with:

1. **`ReasoningProvider`** — an abstract interface that reasoning backends implement.
   It accepts a structured `ReasoningRequest` and returns a `ReasoningResponse`.
2. **`ReasoningRequest`** — structured input assembled from pipeline context (plan,
   bundle, baseline, memory, deterministic findings).  This is not a raw prompt string —
   it is structured data that provider adapters can format according to their conventions.
3. **`ReasoningResponse`** — structured output carrying candidate notes and (future)
   candidate findings.  Provider output is treated as *candidate* material — the pipeline
   decides what to trust and surface.
4. **`DisabledProvider`** — no-op default provider.  Returns empty response.  Current
   heuristic-based flow runs unchanged.
5. **`MockProvider`** — predictable provider for testing and local development.  Returns
   structured notes reflecting request context without generating findings.
6. **`build_reasoning_request()`** — canonical prompt/input builder that assembles a
   `ReasoningRequest` from the pipeline context.  This is a first-class part of the
   reviewer pipeline.

The engine accepts an optional `provider` parameter.  When no provider is supplied or
the provider is disabled, the pipeline behaves exactly as before.

### Rationale
- **No live credentials for tests or default flow.** DisabledProvider preserves existing
  behavior.  MockProvider enables pipeline testing without external dependencies.
- **Structured input over raw prompts.** ReasoningRequest carries typed context slices
  rather than a freeform prompt string.  Provider adapters can format as they wish.
- **Candidate output, not trusted findings.** Provider output is explicitly candidate
  material.  Trust calibration (when provider findings can become real findings) is a
  separate design dimension deferred to later phases.
- **Minimal interface.** ReasoningProvider has three methods: `reason()`,
  `is_available()`, `name`.  No plugin framework, no configuration system, no
  registry abstraction.
- **Pipeline preservation.** The existing heuristic path (plan-driven notes, concerns,
  observations, deterministic checks) runs unchanged.  Provider output is additive.

### What is implemented
- `ReasoningProvider` abstract base in `reviewer/providers.py` with `reason()`,
  `is_available()`, and `name` methods
- `ReasoningRequest` and `ReasoningResponse` data models in `reviewer/providers.py`
- `DisabledProvider` and `MockProvider` implementations in `reviewer/providers.py`
- `build_reasoning_request()` in `reviewer/prompt_builder.py` — assembles structured
  input from PullRequestContext, ReviewPlan, ReviewBundle, concerns, observations, and
  deterministic findings
- `run_reasoning()` updated to accept optional `provider` and `deterministic_findings`
  parameters — assembles a reasoning request and integrates provider output when provider
  is available
- `analyse()` updated to accept optional `provider` parameter and pass deterministic
  findings as context to the reasoning layer
- `ReasoningResult` extended with `reasoning_request` and `provider_name` fields for
  debugging and testing
- 103 new tests covering providers, prompt builder, and integration

### Key design choices
- **Provider output does not produce findings in Phase 1.** MockProvider generates notes
  only; DisabledProvider generates nothing.  Provider-backed findings require trust
  calibration first.
- **Reasoning request is structured, not string-formatted.** Future provider adapters
  will format the request according to their own conventions.
- **Prompt builder is a first-class pipeline component.** It has its own module, tests,
  and explicit inputs rather than being embedded in provider code.
- **No scoring impact from provider output.** Risk score and decision remain derived
  from deterministic findings only.
- **ScanResult JSON contract unchanged.** No new fields leak into the structured output.
- **Backward compatible.** All existing callers continue to work without changes.

### Consequences
- The reviewer pipeline now has a clean integration point for future provider-backed
  reasoning (GitHub Models, external LLMs)
- Tests can exercise the full pipeline with MockProvider without any credentials
- The prompt builder makes the reasoning input structure explicit and testable
- Provider integration can be added incrementally by implementing ReasoningProvider
- The JSON contract is unchanged
- Risk scoring is unchanged

### Deferred concerns
- Live provider integration (GitHub Models, external LLMs) — requires credentials,
  rate limiting, error handling, and response parsing
- Prompt quality optimisation — current request structure is functional but not
  tuned for any specific provider
- Provider output trust calibration — when can provider-generated candidate findings
  become real findings?  This is an explicit design dimension for later phases
- Provider-backed candidate concerns or richer observations — future providers may
  enrich concern/observation quality beyond current heuristics
- Provider-backed reasoning should remain constrained by repo-aware context, not
  generic freeform prompting
- Provider selection and configuration — later phases may need provider selection
  based on org/repo preferences
- Rate limiting and cost management for live providers
- Caching and deduplication for repeated reasoning requests

---

## ADR-026: GitHub Models as first live reasoning provider

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
Implement `GitHubModelsProvider` as the first live reasoning provider, using the
GitHub Models inference API (OpenAI-compatible chat completions endpoint).  The
provider is optional, additive, and disabled by default.

### Rationale
- **GitHub-native.** GitHub Models is accessed via `GITHUB_TOKEN`, which is already
  available in GitHub Actions.  No separate credential management needed.
- **Phase-appropriate.** Adds live reasoning capability without changing the trust
  model, scoring, or ScanResult contract.
- **Safe by default.** Disabled unless explicitly configured via environment variable.
  Missing credentials or provider failure degrade gracefully to the existing
  heuristic-based flow.
- **Additive.** Provider output flows through the existing `ReasoningProvider`
  interface (ADR-025) as candidate notes only — it does not create findings,
  alter scoring, or influence decisions.
- **Minimal configuration.** Three environment variables: `PARITY_REASONING_PROVIDER`,
  `PARITY_REASONING_MODEL`, and `GITHUB_TOKEN`.  No configuration framework.

### What is implemented
- `GitHubModelsProvider` class in `reviewer/providers.py` implementing the
  `ReasoningProvider` interface
- Prompt formatting from `ReasoningRequest` to system+user messages
- Response parsing from model output to structured candidate notes
- `reviewer/provider_config.py` — minimal environment-based provider resolution
- `resolve_provider()` function wired into the GitHub Action entry point
- 56 new tests covering provider interface, configuration, error handling,
  pipeline integration, and contract stability

### Key design choices
- **Disabled by default.** `PARITY_REASONING_PROVIDER` defaults to `"disabled"`.
  GitHub Models is enabled only when `PARITY_REASONING_PROVIDER=github-models`
  and `GITHUB_TOKEN` is set.
- **Provider output is candidate material only.** Notes from the provider are
  integrated into the PR summary as contextual observations.  They do not
  become findings, affect risk_score, or influence the decision.
- **Graceful failure everywhere.** Network errors, timeouts, HTTP errors, and
  invalid responses all result in an empty response — the reviewer pipeline
  continues with its existing heuristic-based flow.
- **No new dependencies.** Uses `httpx` which is already in `requirements.txt`.
- **ScanResult JSON contract unchanged.** No provider-specific data leaks into
  the structured output.
- **Token passed as constructor argument.** The provider does not read
  environment variables directly — `provider_config.py` handles resolution.

### Trust boundary
Provider output remains explicitly non-authoritative:
- Candidate notes only — no candidate findings in Phase 1
- Notes are clearly labelled as provider-generated in the pipeline
- `is_from_live_provider=True` distinguishes live output from mock/disabled
- No scoring impact: risk_score and decision derived from deterministic findings only

### Consequences
- The reviewer can now optionally use live LLM reasoning for contextual notes
- GitHub Actions workflows can enable reasoning by setting two environment variables
- All existing behavior is preserved when the provider is disabled (default)
- Tests do not require live credentials — all HTTP interactions are mocked
- The configuration approach is minimal and can be extended later

### Deferred concerns
- **External provider support** — non-GitHub providers (OpenAI direct, Anthropic,
  etc.) are not yet supported.  The `ReasoningProvider` interface is ready for
  them, but provider resolution and configuration are GitHub Models-only for now.
- **Prompt tuning** — the system prompt and user prompt formatting are functional
  but not optimised.  Iteration will be needed once live usage generates feedback.
- **Provider-backed findings** — the trust model for promoting provider candidate
  findings to real findings is unresolved.  Phase 1 produces notes only.
- **Rate limits and token limits** — GitHub Models has rate limits and token
  budgets.  The provider does not yet handle rate limiting, retry logic, or
  prompt size constraints.
- **Prompt sizing** — large PRs may exceed model context windows.  No truncation
  or chunking strategy is implemented yet.
- **Cost management** — no cost tracking or budget enforcement for API calls.
- **Caching** — repeated reasoning requests for the same PR context are not cached.

---

## ADR-027: Provider output quality pass — prompt shaping, note normalization, overlap suppression

**Date:** 2026-03-28

**Status:** Accepted

**Context:**

ADR-025 and ADR-026 established the provider-agnostic reasoning interface and
the GitHub Models provider.  Provider output flows as candidate notes — non-
authoritative, markdown-only material.  However, the initial implementation had
several quality gaps:

- The system prompt was generic, not security-review-specific.
- Provider notes were unstructured strings (`list[str]`), making deduplication
  and rendering difficult.
- No mechanism prevented provider notes from restating concerns, observations,
  or deterministic findings already present in the pipeline.
- Provider notes were not rendered as a distinct section in markdown output.
- The note cap was too generous (20), risking noisy output.

These gaps reduce the usefulness of provider-backed review output without
changing the trust model.

**Decision:**

Improve the provider-backed reasoning path in a single quality pass:

1. **Prompt shaping** — rewrite the system prompt to be more security-review-
   specific.  Explicitly instruct the model to: not restate deterministic
   findings, not produce generic best-practice filler, be file-specific, express
   genuine uncertainty, and return structured JSON objects instead of flat
   strings.  The user prompt now groups already-detected context (concerns,
   observations, deterministic findings) under a clear "ALREADY DETECTED"
   heading to reduce redundant output.

2. **CandidateNote normalization** — introduce an internal `CandidateNote`
   dataclass in `providers.py` with fields: `title`, `summary`,
   `related_paths`, `confidence`, `source`.  The response parser now handles
   both structured JSON objects (preferred) and flat string arrays (backward-
   compatible fallback).  Confidence values are clamped to `low`/`medium` — 
   candidate notes never carry `high` confidence.  `ReasoningResponse` gains
   a `structured_notes` field alongside the backward-compatible
   `candidate_notes`.

3. **Overlap suppression** — add lightweight keyword-based overlap suppression
   in `reasoning.py`.  Provider notes that share >60% keyword overlap with
   existing concerns, observations, or deterministic findings are suppressed.
   Remaining notes are capped at 5.  This is intentionally heuristic — a
   simple, explainable filter rather than a complex ranking engine.

4. **Markdown rendering** — add a distinct "Additional Review Notes" section in
   `formatter.py`, rendered after observations and before the footer.  Notes
   are explicitly marked as non-authoritative AI-generated material.  The
   section is capped at 5 notes and omitted entirely when empty.

5. **Note cap** — reduced from 20 to 10 at the parsing stage, and further
   to 5 after overlap suppression and in markdown rendering.

**What did not change:**

- The trust model: provider notes remain non-finding, non-scoring.
- ScanResult JSON contract: no new fields, no shape change.
- Deterministic checks: unaffected.
- DisabledProvider behavior: preserved exactly.
- Backward compatibility: all existing callers and tests continue to work.

**Consequences:**

- Provider output is now more security-review-relevant and less generic.
- Redundant output is suppressed against existing pipeline context.
- Markdown output clearly separates provider notes from proven findings,
  concerns, and observations.
- The `CandidateNote` dataclass provides a clean internal shape for future
  note-level reasoning (e.g., selective invocation, richer schemas).
- The overlap suppression threshold (60%) and note cap (5) are tunable
  heuristics that may need adjustment with live usage data.

**Tests:**

- 49 new focused tests covering prompt structure, CandidateNote normalization,
  overlap suppression, markdown rendering, trust-model regression, and pipeline
  flow.
- All 717 tests pass (664 original + 53 new/updated).

**Deferred concerns:**

- **Provider notes remain non-authoritative** — the trust model for promoting
  provider notes to findings is not changed.  This remains a future concern.
- **Prompt tuning is iterative** — the current prompt wording is improved but
  not final.  Live usage will reveal further tuning opportunities.
- **Overlap suppression is heuristic** — keyword-based overlap is simple and
  explainable but may miss semantic equivalence or over-suppress.  Future work
  may introduce embedding-based similarity.
- **Ranking/selection remains basic** — notes are capped but not ranked by
  quality.  Future iterations may rank by confidence, relevance, or novelty.
- **Richer provider note schemas** — `CandidateNote` could grow fields like
  `category`, `suggested_action`, or `evidence_snippet`.  Deferred until the
  provider trust model matures.
- **Selective provider invocation** — calling the provider only for high-focus
  files would reduce cost and noise.  Deferred to later iterations.

---

## ADR-028: Provider-backed observation refinement

**Date:** 2026-03-28

**Status:** Accepted

**Context:**

ADR-024 introduced ReviewObservation as per-file security review analysis notes
derived from ReviewBundle items.  ADR-025/026/027 established the provider-agnostic
reasoning interface, the GitHub Models provider, and the provider output quality
pass.  Provider output currently flows as CandidateNote objects shown in a
separate "Additional Review Notes" section — distinct from observations.

The next step is to use provider reasoning to make ReviewObservations more
semantically useful and security-engineer-like, without changing the trust model
or scoring behavior.

**Decision:**

Implement provider-backed observation refinement in `reviewer/observations.py`,
integrated into the reasoning pipeline in `reviewer/reasoning.py`:

1. **Enrichment** — when a provider CandidateNote targets the same file as an
   existing observation (path match) or shares significant keyword overlap
   (≥35% threshold), the observation's summary is augmented with hedged
   provider detail (capped at 200 chars).  The observation's basis is marked
   with `+provider_enriched`.  The original observation text is preserved;
   enrichment appends rather than replaces.

2. **Supplementary observations** — provider notes that target specific files
   not already covered by an existing observation may generate new observations
   with `basis="provider_refinement"`.  Supplementary observations use hedged
   language ("may warrant attention") and are capped at 3 per refinement pass.

3. **Pipeline integration** — refinement runs after overlap suppression and
   before the final ReasoningResult is returned.  Flow:
   generate_observations → provider call → overlap suppression → refine_observations.

4. **Caps** — total observations remain capped at 10 (`_MAX_OBSERVATIONS`).
   Supplementary observations are capped at 3 (`_MAX_SUPPLEMENTARY`).
   Enrichment detail is capped at 200 characters (`_MAX_ENRICHMENT_CHARS`).

5. **Trust boundaries preserved:**
   - Observations remain non-finding and non-scoring.
   - Provider output does not create findings.
   - ScanResult JSON contract unchanged.
   - risk_score and decision unchanged.
   - DisabledProvider and MockProvider behavior preserved.
   - Enrichment and supplementary observations use hedged language.

**What did not change:**

- ScanResult JSON contract: unchanged — observations are markdown-only.
- risk_score and decision: derived from deterministic findings only.
- Deterministic checks: unaffected.
- DisabledProvider behavior: preserved exactly — no refinement occurs.
- Existing observation generation: unchanged — refinement is additive.
- CandidateNote rendering in markdown: still available as separate section.
- Backward compatibility: all existing callers and tests work unchanged.

**Consequences:**

- ReviewObservations are now semantically richer when provider output is available.
- Enriched observations carry provider-specific detail with hedged language.
- Supplementary observations surface provider insights for files not otherwise
  observed, increasing review coverage.
- The refinement function (`refine_observations`) is pure and testable — it
  takes observations + notes and returns refined observations.
- Original observation objects are not mutated; refinement works on copies.

**Tests:**

- 45 new focused tests covering: refinement path (enrichment + supplementary),
  scoring impact (none), no-overclaiming, dedup/overlap, disabled provider
  behavior, JSON contract stability, and markdown output.
- All 762 tests pass (717 original + 45 new).

**Deferred concerns:**

- **Provider-backed observations are still non-authoritative** — refinement
  enriches observations but does not change their trust level.  Observations
  remain markdown-only, non-scoring context.
- **Provider-backed findings remain deferred** — provider output still cannot
  create findings.  The trust model for promoting provider output is unchanged.
- **Observation enrichment quality will need tuning** — the keyword match
  threshold (35%), enrichment cap (200 chars), and supplementary cap (3) are
  heuristic values that may need adjustment with live usage data.
- **Selection/merging remains heuristic** — matching is path-based then
  keyword-based.  Semantic similarity or embedding-based matching is deferred.
- **External provider support still deferred** — refinement works with any
  ReasoningProvider implementation, but only GitHub Models is available.
- **Scoring remains deliberately independent from provider output** — no
  change to the scoring model or decision derivation.

---

## ADR-029: Provider invocation gating

**Status:** Accepted  
**Date:** 2026-03-28

### Decision

Introduce a lightweight provider invocation gating mechanism that evaluates
whether live provider reasoning should run based on context richness and
security relevance signals from the ``ReviewPlan`` and ``ReviewBundle``.

The gate sits between request assembly and ``provider.reason()`` in
``run_reasoning()``.  When the gate decides to skip, provider reasoning is
not invoked and the reviewer continues with the existing non-provider flow.

### Components

1. **``ProviderGateResult``** — frozen dataclass with ``should_invoke: bool``
   and ``reasons: list[str]``.  Always populated regardless of decision
   direction.

2. **``evaluate_provider_gate(plan, bundle)``** — pure function that examines
   plan and bundle signals to produce a ``ProviderGateResult``.  Located in
   ``reviewer/provider_gate.py``.

3. **Integration in ``run_reasoning()``** — gate is evaluated after bundle
   assembly but before ``provider.reason()``.  Only runs when provider is
   available (``provider.is_available() is True``).  ``DisabledProvider``
   short-circuits before gating.

### Signals that drive invocation

The gate considers:
- Whether sensitive paths are touched (from ``plan.sensitive_paths_touched``)
- Whether auth-related paths are touched (from ``plan.auth_paths_touched``)
- Whether meaningful focus areas exist (from ``plan.focus_areas``)
- Whether relevant memory categories are present (from ``plan.relevant_memory_categories``)
- Whether the ``ReviewBundle`` contains items with elevated review focus
  (``bundle.has_high_focus_items``)

At least one positive signal is required for invocation.  All signals are
derived from existing pipeline structures — no new data sources.

### Gating policy

- **Invoke when:** at least one meaningful context signal is present
  (sensitive paths, auth paths, focus areas, memory overlap, high-focus
  bundle items).
- **Skip when:** no meaningful signals — context is trivial or low-value
  for provider reasoning.
- **Disabled provider:** gate is never evaluated; ``DisabledProvider``
  short-circuits via ``is_available() is False``.
- **No plan (legacy path):** gate returns skip with explicit reason.

### What changed

- ``reviewer/provider_gate.py`` added with ``ProviderGateResult`` and
  ``evaluate_provider_gate()``.
- ``reviewer/reasoning.py`` updated: gate evaluated before
  ``provider.reason()``; result recorded in ``ReasoningResult.provider_gate_result``.
- ``ReasoningResult`` gains ``provider_gate_result: ProviderGateResult | None``
  field (internal only, not in JSON contract).
- Existing tests updated: tests that verify provider output flow now use
  security-relevant file paths to pass the gate.
- 45 new focused tests in ``tests/test_provider_gate.py``.

### What did not change

- ScanResult JSON contract: unchanged — gate result is internal only.
- risk_score and decision: derived from deterministic findings only.
- Deterministic checks: unaffected.
- DisabledProvider behavior: preserved exactly — gate never runs.
- Provider output trust model: unchanged — output remains non-authoritative.
- Scoring: unchanged.
- Existing non-provider flow: unchanged when gate skips.
- MockProvider and GitHubModelsProvider implementations: unchanged.

### Consequences

- Provider reasoning now only runs when the PR context justifies it.
- Cost and runtime are reduced for trivial PRs.
- Signal quality improves because provider is not invoked on low-value context.
- Gating decisions are explainable via ``ProviderGateResult.reasons``.
- The gate is intentionally simple — a heuristic, not a scoring engine.

### Tests

- 45 new focused tests covering: invoke cases (sensitive, auth, focus areas,
  memory, bundle), skip cases (trivial, empty plan, weak context), reason
  stability, disabled provider behavior, no scoring changes, JSON contract
  stability, pipeline stability (invoke and skip paths), gate integration
  with ``run_reasoning()``, and provider.reason() call verification.
- All 807 tests pass (762 original + 45 new).

### Deferred concerns

- **Current gating remains heuristic and temporary** — the signals and
  threshold are intentionally simple.  Future iterations may refine based
  on live usage data.
- **Future gating may include repo criticality, diff size, policy mode,
  or richer bundle features** — these are not available or needed in Phase 1.
- **Current invocation policy is not yet cost-optimized for all repo types**
  — gating prevents invocation on trivial context but does not yet consider
  API cost budgets, rate limits, or per-repo policy.
- **Provider output remains non-authoritative regardless of invocation
  decision** — gating controls when the provider runs, not how its output
  is trusted.
- **Gate result is not yet surfaced in markdown output** — this may be
  useful for transparency but is deferred to avoid output noise.

---

## ADR-030: ReviewTrace — internal reviewer traceability

**Status:** Accepted  
**Date:** 2026-03-28

### Decision

Introduce a lightweight ``ReviewTrace`` dataclass that captures why the
reviewer behaved the way it did during a run.  The trace is assembled
as part of the reviewer pipeline and is accessible internally from
``ReasoningResult`` and ``AnalysisResult``.

The trace is **internal only**.  It does not appear in:
- ``ScanResult`` JSON contract
- ingestion payloads
- risk scoring or decision derivation
- markdown output

### Components

1. **``ReviewTrace``** — dataclass in ``reviewer/models.py`` with fields:
   - ``provider_attempted``: whether provider reasoning was attempted
   - ``provider_gate_decision``: gate outcome (invoked / skipped / disabled / unavailable)
   - ``provider_gate_reasons``: explainable reasons from gating
   - ``provider_name``: name of the provider used
   - ``active_focus_areas``: focus areas from ReviewPlan
   - ``bundle_item_count``: number of bundle items
   - ``bundle_high_focus_count``: items with elevated review focus
   - ``concern_count``: number of concerns generated
   - ``observation_count``: number of observations generated
   - ``provider_notes_returned``: raw notes from provider
   - ``provider_notes_suppressed``: notes removed by overlap filtering
   - ``provider_notes_kept``: notes retained after suppression
   - ``observation_refinement_applied``: whether provider refinement ran
   - ``entries``: ordered descriptive entries documenting decisions

2. **Integration in ``run_reasoning()``** — trace is assembled as each
   pipeline step executes: plan loading, bundle assembly, concern and
   observation generation, provider gating, provider invocation, overlap
   suppression, and observation refinement.

3. **Threading to ``AnalysisResult``** — the ``trace`` field is propagated
   from ``ReasoningResult`` through ``engine.analyse()`` to
   ``AnalysisResult``.

### What changed

- ``reviewer/models.py``: added ``ReviewTrace`` dataclass.
- ``reviewer/reasoning.py``: trace assembled during ``run_reasoning()``
  and included in ``ReasoningResult``.
- ``reviewer/engine.py``: ``AnalysisResult`` gains ``trace`` field,
  populated from ``ReasoningResult.trace``.
- 37 new focused tests in ``tests/test_trace.py``.

### What did not change

- ScanResult JSON contract: unchanged — trace is internal only.
- risk_score and decision: derived from deterministic findings only.
- Deterministic checks: unaffected.
- Scoring: unchanged.
- Markdown output: unchanged.
- Provider behavior: unchanged — trace is observational, not prescriptive.
- ``action.py`` output: trace is not serialised to stdout or PR comments.

### Consequences

- Future contributors can inspect the trace to understand why the reviewer
  behaved a certain way during a run.
- Debugging and tuning are easier because key pipeline signals are captured.
- Control-plane design can consume trace data when that surface is built.
- Trust calibration is supported by explicit gate decision visibility.

### Tests

- 37 new focused tests covering: trace generation in normal flow, provider
  gate decision visibility, disabled provider visibility, provider invocation
  visibility, suppression/refinement visibility, no trace leak into ScanResult
  JSON contract, ReviewTrace model defaults, and engine-level integration.
- All 844 tests pass (807 original + 37 new).

### Deferred concerns

- **Trace is internal-only for now** — no persistence, export, or API
  exposure.  Future control-plane or analytics surfaces may consume parts
  of the trace.
- **Current trace is intentionally lightweight** — it is not a full
  telemetry or observability framework.  Fields may be added as the pipeline
  grows, but the model should remain small and explicit.
- **No markdown rendering of trace** — the trace is not shown in PR
  comments.  Future phases may optionally surface trace summaries for
  transparency.
- **No structured trace schema yet** — the trace is a plain dataclass,
  not a Pydantic model.  If trace data is later persisted or exported,
  a schema may be defined.

---

## ADR-031: Anthropic and OpenAI as live reasoning providers

**Date:** 2026-03-28

**Status:** Accepted

**Context:**

ADR-026 introduced GitHubModelsProvider as the first live reasoning provider.
The provider abstraction (ADR-025) was designed to support multiple backends.
To give teams flexibility in provider choice and avoid vendor lock-in, we
add Anthropic and OpenAI as second and third live provider options.

Both must fit the existing ``ReasoningProvider`` interface, preserve the
identical trust model (candidate notes only), and degrade gracefully on
any failure.

**Decision:**

Add ``AnthropicProvider`` and ``OpenAIProvider`` as live reasoning providers
in ``reviewer/providers.py``, extending provider resolution in
``reviewer/provider_config.py``.

### Provider naming and config

The ``PARITY_REASONING_PROVIDER`` environment variable now supports:
- ``disabled`` (default) — no live reasoning.
- ``github-models`` — GitHub Models inference API (ADR-026).
- ``anthropic`` — Anthropic Messages API.
- ``openai`` — OpenAI Chat Completions API.

Provider-specific environment variables:
- ``GITHUB_TOKEN`` — required for ``github-models``.
- ``ANTHROPIC_API_KEY`` — required for ``anthropic``.
- ``OPENAI_API_KEY`` — required for ``openai``.
- ``OPENAI_API_BASE`` — optional base URL override for OpenAI-compatible
  endpoints.
- ``PARITY_REASONING_MODEL`` — shared model override, per-provider defaults.

### Anthropic implementation

- Uses the Anthropic Messages API (``/v1/messages``).
- Authenticates via ``x-api-key`` header.
- Sends system prompt as top-level ``system`` field (Anthropic convention).
- Parses response from ``content[0].text`` (text content blocks).
- Default model: ``claude-sonnet-4-20250514``.
- Concatenates multiple text content blocks if returned.

### OpenAI implementation

- Uses the OpenAI Chat Completions API (``/v1/chat/completions``).
- Authenticates via ``Authorization: Bearer`` header.
- Uses same message format as GitHubModelsProvider (OpenAI-compatible).
- Parses response from ``choices[0].message.content``.
- Default model: ``gpt-4o-mini``.
- Supports ``OPENAI_API_BASE`` for third-party OpenAI-compatible endpoints.

### Shared logic

Both providers reuse the existing shared infrastructure:
- ``_format_user_prompt()`` for prompt assembly from ``ReasoningRequest``.
- ``_parse_candidate_notes()`` for normalising model output into
  ``CandidateNote`` objects.
- ``_SYSTEM_PROMPT`` for constraining model output.

OpenAI and GitHub Models share the same API shape (OpenAI chat completions
format).  They are kept as separate provider classes for clarity and to
allow independent evolution (different defaults, auth, endpoints).

### Trust boundaries

The trust model is identical across all three live providers:
- Provider output remains **candidate notes only**.
- Provider output does not create findings.
- Provider output does not affect scoring.
- Provider output does not change ScanResult.
- Overlap suppression and observation refinement continue to apply.
- ReviewTrace remains internal only.
- No provider has special-case authority.

### Fallback and error handling

All provider failures degrade gracefully:
- Missing API key → ``DisabledProvider`` fallback at config resolution.
- Any error during ``reason()`` → empty ``ReasoningResponse``.
- Network, timeout, HTTP error, malformed response → logged warning,
  empty response.
- Reviewer execution is never blocked by provider failure.

### What changed

- ``reviewer/providers.py``: added ``AnthropicProvider`` and
  ``OpenAIProvider`` classes.
- ``reviewer/provider_config.py``: added ``_resolve_anthropic()`` and
  ``_resolve_openai()`` resolution functions; extended ``resolve_provider()``
  to support ``anthropic`` and ``openai`` values.
- ``tests/test_anthropic_provider.py``: 47 new focused tests.
- ``tests/test_openai_provider.py``: 46 new focused tests.
- ``README.md``: updated configuration documentation with all providers.

### What did not change

- ScanResult JSON contract: unchanged.
- risk_score and decision: derived from deterministic findings only.
- Deterministic checks: unaffected.
- Scoring: unchanged.
- Markdown output: unchanged.
- GitHubModelsProvider: unchanged.
- DisabledProvider and MockProvider: unchanged.
- Provider gate (ADR-029): unchanged — applies to all providers.
- Observation refinement (ADR-028): unchanged — applies to all providers.
- ReviewTrace (ADR-030): unchanged — captures whatever provider is used.

### Tests

- 47 new focused tests for AnthropicProvider covering: interface conformance,
  availability checks, API call formatting, response parsing, graceful
  failure (network, timeout, HTTP error, malformed response), config
  resolution, pipeline integration, scoring independence, ScanResult
  contract stability, and provider compatibility.
- 46 new focused tests for OpenAIProvider covering the same categories
  plus base URL override and trust boundary verification.
- All 937 tests pass (844 original + 93 new).

### Consequences

- Teams can choose between GitHub Models, Anthropic, and OpenAI for
  reasoning without code changes — config-driven selection.
- Trust model remains identical — no provider has elevated authority.
- Provider quality comparison remains future work.
- The abstraction supports future providers with minimal changes.

### Deferred concerns

- **Provider-specific prompt tuning** may be needed later — the shared
  system prompt works across providers but may benefit from per-provider
  adaptation as quality data is gathered.
- **Provider quality comparison** remains future work — there is no
  mechanism yet to compare quality/cost/latency across providers.
- **Cost controls, rate limits, and caching** remain deferred — no
  provider-level resource management exists yet.
- **Provider-backed findings remain deferred** — provider output is
  candidate notes only.  Promoting to findings requires trust calibration.
- **Provider selection is config-based, not policy-aware** — there is no
  policy engine for provider routing.  Selection is explicit per-deployment.
- **Provider-specific error codes** are not handled distinctly — all errors
  are treated uniformly as fallback-to-empty.

---

## ADR-032: PR validation harness for scenario-based reviewer testing

**Status:** Accepted
**Date:** 2026-03-28

### Decision

Introduce a lightweight PR validation framework in `reviewer/validation/`
that validates reviewer behavior across curated pull request scenarios.

The framework has three layers:

1. **Scenario format** — `ValidationScenario` pairs synthetic PR inputs
   (changed files, optional baseline profile, optional review memory,
   provider mode) with declarative `ExpectedBehavior` assertions.

2. **Curated corpus** — A small, readable set of 7 representative
   scenarios covering key review paths: auth-sensitive, sensitive-config,
   trivial-docs, memory-influenced, deterministic-only, provider-enriched,
   and low-noise-tests.

3. **Validation runner** — `run_scenario()` executes a scenario through
   the full reviewer pipeline and evaluates expectations as structured
   `Assertion` results in a `ValidationResult`.

### Rationale

- **Regression testing**: Scenarios encode expected behavior so pipeline
  changes can be validated against known-good baselines.
- **Quality tuning**: Scenarios make it easy to verify that tuning
  changes (prompt, heuristic, threshold) produce intended effects.
- **Provider safety**: All scenarios use `DisabledProvider` or
  `MockProvider` — no live credentials required.
- **Trust-boundary validation**: Every scenario asserts that provider
  output does not pollute decision, risk_score, or findings.
- **Phase alignment**: This is a reviewer-first testing tool, not a
  benchmark platform or dashboard feature.

### What the harness validates

- Provider gate invoked or skipped as expected
- Findings count and category presence/absence
- Concern and observation presence/absence
- Markdown output containing or omitting key sections
- Trust-boundary invariants (decision/risk deterministic from findings)
- ScanResult JSON contract stability

### What the harness does NOT do

- Change ScanResult, scoring, or decision logic
- Require live provider credentials
- Build a full benchmark schema or scoring platform
- Add dashboard or reporting features
- Replace existing unit tests

### Consequences

- 66 new focused tests cover scenario loading, validation runner
  behavior, all 7 curated scenarios, provider gate expectations,
  trust-boundary invariants, ScanResult contract stability, and
  provider compatibility.
- All 1003 tests pass (937 original + 66 new).
- Scenarios are parameterized — `@pytest.mark.parametrize` runs all
  corpus scenarios in a single test class for easy expansion.

### Deferred concerns

- **Full benchmark scoring** remains deferred — the harness validates
  behavior, not quality metrics or provider comparison scores.
- **Live-provider quality comparison** remains future work — scenarios
  use only disabled/mock providers.
- **Markdown snapshot stability** may need tuning later — assertions
  use substring matching, not full-output snapshots, to minimize
  brittleness.
- **Scenario corpus expansion** — the initial 7 scenarios cover key
  paths but the corpus should grow as the reviewer pipeline matures.
- **Cross-provider scenario comparison** — running the same scenario
  against multiple live providers for quality analysis is not yet
  supported.
- **Scenario versioning** — scenarios are currently in code; a
  file-based format may be useful if the corpus grows significantly.

---

## ADR-033: Documentation structure for onboarding and operability

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
Add a `docs/` directory with structured documentation for contributors and operators, covering getting started, trust model, validation harness, GitHub Action setup, architecture overview, and release packaging.

### Rationale
- The reviewer pipeline has matured to a point where operability and onboarding clarity are the next priority
- New contributors and operators need practical documentation without reading internal `.squad/context/` files
- GitHub Action setup needs explicit workflow examples for each provider mode
- Trust model boundaries (findings vs concerns vs observations vs provider notes) need a clear, standalone reference
- Release/Marketplace direction needs honest documentation of current state vs future intent

### Structure
- `docs/getting-started.md` — installation, configuration, running locally
- `docs/trust-model.md` — output semantics and trust boundaries
- `docs/validation.md` — scenario harness usage
- `docs/github-action-setup.md` — workflow YAML examples per provider mode
- `docs/architecture-overview.md` — high-level pipeline for contributors
- `docs/release-packaging.md` — Marketplace direction and current state
- `README.md` — updated as primary entry point with links to deeper docs

### Consequences
- `.squad/context/` remains the durable internal architecture reference
- `docs/` is the contributor/operator-facing documentation surface
- Documentation must be kept aligned with implementation reality as the reviewer evolves
- No code changes, scoring changes, or contract changes were made

## ADR-034: GitHub Action runtime completeness and PR output integration

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
Complete the GitHub Action runtime so parity-zero can genuinely review real pull requests: discover changed files, load file contents from the workspace, run the full reviewer pipeline, and surface results in GitHub-native ways (job summary and PR comment).

### Context
Prior to this change, the action discovered changed file paths but passed empty content strings to the reviewer pipeline. Output was only written to stdout. The reviewer pipeline was fully functional internally but the action path was incomplete for real PR review.

### Changes

**Changed file discovery:**
- Primary: `git diff --name-only --diff-filter=ACMR <base_sha> HEAD` using the PR base SHA from the GitHub event payload
- Fallback: GitHub REST API (existing `get_changed_files()`) when git diff is unavailable
- Deleted files are excluded (no content to review)
- Decision: git diff was chosen over API-only because it works with the already-checked-out repo, requires no additional API calls, and handles the common case robustly

**File content loading:**
- Read files from `GITHUB_WORKSPACE` (or cwd)
- Skip binary files (UTF-8 decode failure)
- Skip large files (> 1 MB)
- Skip missing/deleted/unreadable files
- Log skipped files with reason
- New module: `reviewer/github_runtime.py`

**Output surfacing:**
- GitHub job summary (`GITHUB_STEP_SUMMARY`) — baseline, always available
- PR comment — created or updated via GitHub REST API
- PR comment uses `<!-- parity-zero-review -->` marker for idempotent updates
- Comment update searches first 100 comments; duplicate may occur on very large PRs (documented limitation)
- Both outputs use the same markdown from `format_markdown()`

**Action YAML:**
- Added "Fetch PR base for diff" step to `action.yml` so the base commit is available for `git diff`

### What did NOT change
- ScanResult JSON contract — unchanged
- Scoring model — unchanged (findings-only, deterministic)
- Trust boundaries — unchanged (provider output remains non-authoritative)
- Validation harness — all 7 scenarios still pass
- Mock run path — unchanged
- Provider implementations — unchanged

### Known limitations (intentionally deferred)
- PR comment dedup checks first 100 comments only; very large PRs may get duplicates
- Binary files are skipped entirely (no review of images, compiled artifacts)
- Files > 1 MB are skipped
- Deleted files cannot be reviewed (no content exists at HEAD)
- Marketplace branding and versioned releases still needed
- Backend persistence / control-plane still deferred
- Richer PR metadata (labels, reviewers, draft status) may be useful later

### Test coverage
- 50 new focused tests in `tests/test_github_runtime.py`
- Covers: git diff discovery, file loading, job summary, PR comment, PullRequestContext assembly, ScanResult contract stability, output format, validation harness compatibility
- All mocked — no live GitHub API credentials required
- Total: 1053 tests pass (1003 existing + 50 new)

---

## ADR-035: Thin backend persistence with SQLite and bearer token auth

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
Implement a thin backend persistence layer using SQLite for storage and bearer token authentication for access control. Wire the GitHub Action to optionally send results to the backend after each review run.

### Context
The reviewer pipeline is mature (deterministic checks, contextual reasoning, provider support, GitHub-native output). The next step toward a control plane foundation is persisting review results so they can be retrieved and inspected. This must be minimal, practical, and not over-built.

### Storage choice: SQLite
- Zero external dependencies — uses Python's built-in `sqlite3` module
- No database server to install, configure, or maintain
- Easy local setup — critical for Phase 2 bridge work
- Phase-appropriate simplicity
- ADR-006 identified Postgres as the eventual store; SQLite bridges the gap
- Migration to Postgres expected later as query/reporting/multi-user needs grow

### Auth model: Bearer token
- Single shared token configured via `PARITY_ZERO_AUTH_TOKEN` env var
- FastAPI dependency injection for clean enforcement
- Constant-time comparison via `secrets.compare_digest`
- If server token not configured, all authenticated requests rejected — operator must explicitly set it
- No user accounts, OAuth, RBAC, or SSO at this phase

### Endpoints
- `POST /ingest` — accept, validate, authenticate, and persist ScanResult payloads
- `GET /runs` — list recent runs (paginated, optional repo filter)
- `GET /runs/{scan_id}` — get single run with findings
- `GET /health` — liveness check (no auth)

### Action-to-backend wiring
- Opt-in via `PARITY_ZERO_API_URL` and `PARITY_ZERO_API_TOKEN` env vars
- If either is absent, ingest is silently skipped
- Backend ingest failure never crashes the action
- Internal logging makes ingest attempt and outcome visible
- action.yml updated: `api_endpoint` input renamed to `api_url`, new `api_token` input

### Ingest failure policy
Backend ingest failure is logged as a warning but does not affect the reviewer exit code. The reviewer run is considered successful regardless of backend availability. This preserves the reviewer-first principle — the action is useful even if the backend is down.

### Persistence schema
- `runs` table: scan_id, repo, pr_number, commit_sha, ref, timestamp, decision, risk_score, findings_count, provider_name, ingested_at
- `findings` table: id, scan_id, category, severity, confidence, title, description, file, start_line, end_line, recommendation
- Indexes on scan_id, repo, ingested_at

### What did NOT change
- ScanResult JSON contract — unchanged
- Scoring model — unchanged (findings-only, deterministic)
- Trust boundaries — unchanged (provider output remains non-authoritative)
- Provider implementations — unchanged
- Validation harness — all scenarios still pass
- Reviewer pipeline internals — unchanged

### Deferred concerns
- **Full control plane / dashboard** — intentionally deferred to later phases
- **Multi-user auth / RBAC / SSO / OAuth** — deferred; single shared token is phase-appropriate
- **Postgres migration** — expected when query/reporting needs grow beyond SQLite capabilities
- **Richer query / search / analytics / reporting API** — deferred to dashboard phase
- **Trace persistence / export** — ReviewTrace is internal only; persistence deferred
- **Skipped-file metadata preservation** — github_runtime.py logs skipped files but does not preserve metadata in PRContent; deferred as a separate targeted improvement
- **Review memory persistence** — memory models exist but write-through persistence deferred
- **Database migrations framework** — schema is simple enough for CREATE IF NOT EXISTS; formal migrations deferred

### Test coverage
- 51 new tests across 4 test files:
  - `tests/test_api.py` — ingest, validation, round-trip, persistence, retrieval (30 tests, rewritten)
  - `tests/test_persistence.py` — ScanStore CRUD, schema, edge cases (18 tests)
  - `tests/test_auth.py` — auth enforcement, token validation, unconfigured server (10 tests)
  - `tests/test_backend_ingest.py` — action wiring, skip/attempt/error handling (10 tests)
- All tests use in-memory SQLite — no database file created during testing
- All 1053 existing tests continue to pass unchanged
- Total: 1104 tests pass

---

## ADR-036: Hardening pass — skipped-file awareness, test isolation, and run summary metadata

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
Perform a combined hardening and storage-shape evolution pass: add skipped-file awareness to the reviewer pipeline, harden test isolation, and extend backend persistence with run summary metadata columns.

### Context
ADR-035 delivered thin backend persistence. Several follow-up improvements were identified:
- `load_file_contents()` silently discarded files it could not load — no metadata about what was skipped or why
- Test suites shared module-level fixtures, risking cross-test contamination
- The `runs` table stored only core ScanResult fields — no visibility into provider behaviour, concern/observation volume, or file discovery stats

### Skipped-file awareness
- New `SkippedFile` frozen dataclass in `reviewer/models.py` — captures `path` and `reason` (`not_found`, `binary`, `too_large`, `unreadable`)
- `load_file_contents()` in `reviewer/github_runtime.py` now returns `tuple[dict[str, str], list[SkippedFile]]`
- `PRContent` carries `skipped_files` list and exposes `skipped_file_count` property
- `action.py` logs skipped files with path and reason, and passes `skipped_files_count` to backend ingest

### Test isolation
- New `tests/conftest.py` with autouse fixture that resets `app.dependency_overrides` between tests
- `test_api.py` rewritten with per-test fixtures — no module-level global store/auth overrides
- `test_auth.py` cleanup improved to prevent cross-module bleed

### Run summary metadata — 8 new columns in `runs` table
All additive with safe defaults (0 or empty string):
- `provider_invoked` (INTEGER) — whether provider was called
- `provider_gate_decision` (TEXT) — gate outcome
- `concerns_count` (INTEGER) — ReviewConcern count
- `observations_count` (INTEGER) — ReviewObservation count
- `provider_notes_count` (INTEGER) — raw provider notes
- `provider_notes_suppressed_count` (INTEGER) — notes filtered by overlap
- `changed_files_count` (INTEGER) — total changed files discovered
- `skipped_files_count` (INTEGER) — files that could not be loaded

These are summary counts only — full internal objects (ReviewPlan, ReviewBundle, ReviewTrace, concern/observation text, provider note text, skipped-file details) are intentionally not persisted.

### What did NOT change
- ScanResult JSON contract — unchanged
- Scoring model — unchanged (findings-only, deterministic)
- Trust boundaries — unchanged (provider output remains non-authoritative)
- Provider implementations — unchanged
- Validation harness — all scenarios still pass
- Auth model — unchanged

### Deferred concerns
- **Full internal object persistence** — storing full ReviewTrace, concerns, observations, provider notes deferred to control-plane phase
- **Per-file skipped-file metadata in backend** — only total count stored, not per-file path/reason
- **Database migrations framework** — still using CREATE IF NOT EXISTS; formal migrations deferred

### Test coverage
- 39 new tests in `tests/test_hardening.py`
- Covers: SkippedFile model, PRContent with skipped files, run summary metadata persistence and retrieval, backend ingest pass-through, ScanResult contract stability, scoring invariance, provider trust boundaries
- All 1104 existing tests continue to pass unchanged
- Total: 1143 tests pass

---

## ADR-037: Lightweight additive SQLite schema migration for upgrade safety

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
Add lightweight additive schema migration to the SQLite persistence layer so that databases created by earlier versions of parity-zero are upgraded automatically when opened by the current version.

### Context
ADR-036 added run summary metadata columns (`provider_invoked`, `provider_gate_decision`, `concerns_count`, `observations_count`, `provider_notes_count`, `provider_notes_suppressed_count`, `changed_files_count`, `skipped_files_count`) to the `runs` table. The schema initialisation uses `CREATE TABLE IF NOT EXISTS`, which only creates the table if it is absent — it does not add missing columns to an existing table. Databases created before ADR-036 would fail at runtime because `save_run()` tries to INSERT into columns that do not exist.

### Migration approach
- On store connection, after `CREATE TABLE IF NOT EXISTS`, run a migration helper
- The helper inspects the `runs` table via `PRAGMA table_info(runs)` to get existing column names
- For each expected additive column not yet present, execute `ALTER TABLE runs ADD COLUMN ... NOT NULL DEFAULT ...`
- Safe defaults: integers default to 0, text columns default to empty string — matching the semantics in `_SCHEMA_SQL` and `save_run()`
- The migration is idempotent: safe to run multiple times, on fresh DBs, and on already-migrated DBs

### What this enables
- Upgrade-in-place: operators can upgrade parity-zero without deleting their database
- Pre-existing rows receive safe default values for new columns
- New rows are written with full column coverage as before
- API endpoints return expected data shapes for both legacy and new rows

### What did NOT change
- ScanResult JSON contract — unchanged
- Scoring model — unchanged
- Trust boundaries — unchanged
- Provider implementations — unchanged
- API endpoints — unchanged (same request/response shapes)
- Fresh database behaviour — unchanged

### Deferred concerns
- **Full migration framework (Alembic or similar)** — still deferred; the current approach is additive-column-only and does not handle column renames, type changes, or destructive schema changes
- **Schema versioning table** — not introduced; column-presence detection is sufficient for current needs
- **Postgres migration path** — this migration logic is SQLite-specific; a future Postgres layer would use its own migration tooling
- **Non-additive schema changes** — if future phases require column renames, type changes, or table restructuring, a more formal migration approach will be needed

### Test coverage
- 17 new tests in `tests/test_schema_migration.py`
- Covers: old-schema upgrade, save/retrieve after upgrade, pre-existing row defaults, coexistence of legacy and new rows, fresh DB unchanged, migration idempotence (multiple reopens, direct helper calls), API behaviour on upgraded DB (ingest + retrieval), partial migration scenarios
- All 1143 existing tests continue to pass unchanged
- Total: 1160 tests pass

---

## ADR-038: Evaluation and benchmarking layer for reviewer quality

**Status:** Accepted  
**Date:** 2026-03-28

### Decision
Build a structured evaluation and benchmarking layer to make reviewer quality measurable, comparable, and tunable across provider modes.

### Context
The reviewer pipeline is functionally complete but there was no systematic way to:
- evaluate whether the reviewer is useful on representative PRs
- compare reviewer behavior across disabled/mock provider modes
- verify output quality beyond "pipeline worked"
- codify quality expectations as enforceable assertions
- detect regressions in noise levels, trust boundaries, or output structure

### What changed

#### Scenario model enrichment
- `ValidationScenario` gains: `tags` (classification), `security_focus` (expected focus areas), `provider_value_expected` (whether provider should add value)
- `ExpectedBehavior` gains: `max_concerns`, `max_observations`, `has_provider_notes`, `expected_sections`, `absent_sections`
- New helpers: `get_scenarios_by_tag()`, `list_tags()`

#### Expanded evaluation corpus
Corpus expanded from 7 to 13 curated scenarios:
- **pem-key-in-config** — PEM private key detection (deterministic secrets)
- **plain-refactor** — pure refactoring with no security signals (low-signal)
- **provider-gated-out** — mock provider present but gate correctly skips (gate validation)
- **mixed-auth-and-tests** — auth code mixed with test files (mixed-signal)
- **dependency-lockfile** — lockfile-only changes (low-signal)
- **input-validation-risk** — unsafe input patterns in auth-adjacent code (provider-value)

#### Provider comparison
- `run_comparison(scenario, modes)` runs the same scenario across provider modes
- `ComparisonResult` captures: per-mode summaries, findings stability, decision stability, provider observation/notes contribution, gate differences, trust boundary status
- `format_comparison_summary()` produces human-readable comparison output

#### Output quality assertions
- No empty findings in markdown when findings exist
- Provider notes section absent when no notes
- Observations reference changed files
- No duplicate finding title+file pairs
- Markdown conciseness bound for no-findings scenarios
- Provider notes bounded and never create findings
- No provider notes when gate is skipped

#### Low-noise checks
- Low-signal scenarios produce no findings, concerns, observations, or provider notes
- Gate-skip scenarios actually skip provider invocation
- Deterministic scenarios detect findings without provider

#### CLI entrypoint
- `python -m reviewer.validation` runs all scenarios
- `python -m reviewer.validation --list` lists corpus with metadata
- `python -m reviewer.validation --summary` prints evaluation table
- `python -m reviewer.validation --compare <id>` compares across modes
- `python -m reviewer.validation --tag <tag>` lists by tag
- `python -m reviewer.validation <id>` runs single scenario

### What did NOT change
- ScanResult JSON contract — unchanged
- Scoring model — unchanged (findings-only, deterministic)
- Trust boundaries — unchanged (provider output remains non-authoritative)
- Provider implementations — unchanged
- Existing pipeline behavior — unchanged
- Backend persistence — unchanged
- Auth model — unchanged

### Design decisions
- **Scenario metadata is additive** — existing scenarios gain tags/focus but no behavior changes
- **Comparison is local-test-safe** — only disabled/mock modes; no live credentials required
- **Quality assertions are heuristic** — they encode practical expectations, not scientific benchmarks
- **Corpus remains curated** — prefer fewer high-value scenarios over many shallow ones
- **CLI is minimal** — small utility for running/comparing; not a benchmark platform

### Deferred concerns
- **Live provider comparison** — comparing with real API calls to github-models/anthropic/openai is structurally supported but deferred; requires credentials and may be non-deterministic
- **Benchmark scoring/metrics** — quantitative precision/recall or F1-style metrics are intentionally not built; current evaluation is assertion-based
- **Corpus versioning** — no version tagging for corpus snapshots; comparison is point-in-time
- **Performance measurement** — timing and resource usage tracking deferred
- **Scenario generation from real PRs** — automatic scenario creation from production data deferred
- **Quality assertions will evolve** — current heuristics are starting points that will be refined as the reviewer improves

### Test coverage
- 97 new tests in `tests/test_evaluation.py`
- Covers: scenario metadata/tags/expectations, expanded corpus loading/determinism, comparison mode (disabled vs mock), output quality assertions, low-noise/usefulness checks, trust boundaries across expanded corpus, ScanResult contract stability, all 13 scenarios pass integration tests, cross-scenario comparison trust boundaries
- All 1160 existing tests continue to pass unchanged
- Total: 1263 tests pass (after including expanded parametrized scenarios in existing test file)

---

## ADR-039: Realistic evaluation corpus and lightweight scorecard for reviewer tuning

**Status:** Accepted
**Date:** 2026-03-29

### Decision

Build a realistic, file-backed evaluation corpus and lightweight scorecard to support evidence-based reviewer tuning.

### Context

The evaluation layer (ADR-038) provided assertion-based testing with 13 curated synthetic scenarios, but lacked representative PR-like fixtures and a structured way to assess overall reviewer behavior across a corpus. Synthetic scenarios use inline strings — useful for fast iteration but not representative of real PR content. There was no aggregate view of reviewer quality.

### What changed

#### Realistic corpus
- 10 realistic scenarios backed by fixture files in `test/eval/fixtures/`
- Categories: missing auth, authz business logic, unsafe SQL input, insecure config, GitHub token exposure, harmless refactor, docs/changelog, test expansion, provider-helpful auth, memory-recurring vuln
- Scenarios prefixed with `realistic-` and tagged `realistic`
- Fixture content loaded from files for readability and maintainability

#### Evaluation scorecard
- `EvaluationScorecard` with aggregate rates: findings stability, decision stability, provider value, gate accuracy, trust boundaries, quietness, noise
- Scorecard is explicitly "a practical tuning aid, not a scientific benchmark"
- Rates are aggregate percentages across all scenarios, not per-scenario grades

#### CLI extensions
- `python -m reviewer.validation --realistic` — run realistic corpus
- `python -m reviewer.validation --scorecard` — print evaluation scorecard

#### Test coverage
- 144 new tests covering: corpus structure, execution, comparison, scorecard, output quality, quietness/value-add, trust boundaries, ScanResult contract, regression safety
- Total: 1407 tests pass

### What did NOT change
- ScanResult JSON contract — unchanged
- Scoring model — unchanged (findings-only, deterministic)
- Trust boundaries — unchanged (provider output remains non-authoritative)
- Provider implementations — unchanged
- Existing pipeline behavior — unchanged
- Backend persistence — unchanged

### Design decisions
- **Fixtures stored as files** — for readability and maintainability over inline strings
- **Realistic scenarios prefixed with `realistic-`** — clear namespace separation from synthetic scenarios
- **Scorecard rates are aggregate percentages** — not per-scenario grades; avoids false precision
- **Scorecard is a tuning aid** — explicitly not a scientific benchmark
- **Live-provider comparison structurally supported but deferred** — requires credentials, non-deterministic
- **Comparison defaults to disabled/mock modes only** — safe to run without credentials

### Deferred concerns
- **Live-provider benchmarking** — requires credentials, non-deterministic; structurally supported but not exercised
- **Benchmark scoring/metrics** — quantitative precision/recall deferred; current evaluation is assertion-based
- **Corpus versioning** — point-in-time only, no snapshot tagging
- **Fixture generation from real PRs** — manual curation for now
- **Scorecard trend tracking over time** — single-run snapshot for now
- **Provider comparison quality** — may vary by prompt/provider tuning

---

## ADR-040: Reviewer quality tuning pass — anti-redundancy, specificity, and conciseness

**Status:** Accepted
**Date:** 2026-03-29

### Decision

Improve reviewer output quality through targeted tuning of provider notes, observation generation, overlap suppression, and markdown presentation, driven by the realistic evaluation corpus.

### Context

With the realistic evaluation corpus and comparison layer in place (ADR-039), practical quality issues became visible:

1. **Generic provider notes** — MockProvider produced metadata restatements (file counts, focus area lists, baseline context) that added zero security insight.
2. **Useless observation enrichment** — provider detail like "Analysed 1 changed file(s)" was being appended to observations.
3. **Redundant Recommendations section** — duplicated inline recommendations already shown per-finding.
4. **Generic observation titles** — same title for every auth-sensitive file regardless of which file.
5. **Redundant concerns** — multiple concerns all targeting the same single file with overlapping messaging.
6. **Weak overlap suppression** — did not catch metadata restatement patterns.

### What changed

#### Provider note quality (MockProvider)
- MockProvider generates file-specific, security-relevant notes referencing actual changed file paths, review reasons, and focus areas.
- Cross-file interaction note only generated for multi-file PRs.
- Empty request produces no notes (correct quiet behavior).

#### System prompt improvements (live providers)
- Added anti-redundancy guidance: "do not restate context metadata".
- Added anti-summary guidance: "only provide new observations".
- Added concrete code reference guidance: "reference concrete code patterns, functions, or configurations".

#### Overlap suppression improvements
- Content-quality filter rejects metadata restatement notes (file counts, focus areas, baseline context, memory categories).
- Minimum summary length filter (15 chars) rejects too-terse notes.
- Combined with existing 60% keyword overlap threshold.

#### Observation enrichment quality
- Enrichment rejected when provider detail is too short (< 30 chars).
- Enrichment rejected when provider detail heavily overlaps existing summary (> 60% keyword overlap).
- Each observation enriched at most once (no double-enrichment from multiple matching notes).

#### Observation title specificity
- Titles now include the actual file basename (e.g., "Auth-sensitive boundary: users.py").
- All six observation types updated: sensitive_auth, auth_consistency, auth_area, framework_sensitive, sensitive_path, memory_alignment.

#### Markdown output improvements
- Removed redundant Recommendations section — recommendations shown inline per finding via 💡 marker.
- Concern display deduplicated when multiple concerns target same paths (max 2 per path group, max 5 total, highest confidence first).
- Provider notes display capped at 3 for conciseness.

#### Quality assertions
- 124 new focused tests in `tests/test_quality_tuning.py`.
- Auth scenario specificity: observations reference changed files, titles include filename.
- Low-signal quietness: zero output, short markdown (< 500 chars), no concern/observation/note sections.
- Provider note quality: non-generic, file-specific, metadata restatement detection.
- Redundancy suppression: overlapping notes filtered, metadata filtered, no duplicate titles.
- Markdown quality: correct headers/footers, no redundant sections, concern deduplication.
- Comparison quality: provider value detection, quietness, trust boundaries, stability.
- Trust boundary regression: no provider-sourced findings, clean JSON, deterministic scoring.

### What did NOT change
- ScanResult JSON contract — unchanged
- Scoring model — unchanged (findings-only, deterministic)
- Trust boundaries — unchanged (provider output remains non-authoritative)
- Finding categories — unchanged
- Provider trust level — unchanged
- Backend/persistence — unchanged
- Existing evaluation harness behavior — unchanged

### Design decisions
- **Metadata restatement filter uses phrase matching** — simple, maintainable, low false-positive risk for known patterns.
- **Concern deduplication in formatter, not generator** — generation logic unchanged, display caps redundancy.
- **Single enrichment per observation** — avoids noisy compound summaries.
- **Quality assertions are explicit, not snapshot-based** — specific property checks rather than brittle golden-file comparisons.
- **Low-signal markdown threshold at 500 chars** — verified empirically against realistic corpus.

### Deferred concerns
- **Provider quality still depends on prompt/provider tuning** — mock provider is a proxy; live provider quality may differ.
- **Provider-backed findings remain deferred** — trust calibration not yet in place.
- **Some quality rules remain heuristic** — metadata phrase list, keyword overlap thresholds may need refinement.
- **Richer ranking/reranking of provider notes remains future work** — current approach is suppression-based.
- **Concern de-duplication could be done at generation time** — kept at display layer for now to avoid disrupting existing logic.

## ADR-041: Repo-level configuration file for path exclusion and signal tuning

**Date:** 2026-03-29

### Decision

Introduce an optional `.parity-zero.yml` repo-level configuration file supporting three path-control fields: `exclude_paths`, `low_signal_paths`, and `provider_skip_paths`. The config shape is intentionally narrow but extendable for future settings.

### Context

As parity-zero reviews real repositories, different repos need different path-level controls:
- Vendored/generated code should not produce findings or consume provider resources
- Test files and lock files may produce noisy observations without proportional security value
- Documentation and fixture files rarely benefit from live provider reasoning

Without repo-level config, every file changed in a PR receives equal review treatment. This produces noise for repos with large non-code or low-signal file areas.

### What changed

#### New module: `reviewer/repo_config.py`
- `RepoConfig` frozen dataclass with `exclude_paths`, `low_signal_paths`, `provider_skip_paths` as tuples of glob strings
- `load_config(repo_root)` — loads `.parity-zero.yml` from repo root using `yaml.safe_load`; returns empty config when file is absent
- `load_config_from_text(text)` — convenience loader for testing
- Strict validation: rejects unknown keys, non-list values, empty strings; logs warning and falls back to empty config on any invalid input
- `filter_excluded_paths(file_contents, config)` — removes excluded files and returns excluded path list
- `all_provider_skip(paths, config)` — checks if all paths match provider_skip_paths
- `_matches_any(path, patterns)` — glob matching against full path and basename via `fnmatch`

#### Pipeline integration
- **`engine.py`**: `analyse()` accepts optional `config` parameter. Applies `exclude_paths` before analysis — excluded files are removed from `file_contents` and tracked as `SkippedFile(reason="config_excluded")`. Passes config to reasoning layer.
- **`reasoning.py`**: `run_reasoning()` accepts optional `config`. Suppresses observations for `low_signal_paths`. Short-circuits provider gate when all changed paths match `provider_skip_paths`.
- **`action.py`**: Loads config from `GITHUB_WORKSPACE` at pipeline start, passes to `analyse()`.

#### Dependencies
- Added `pyyaml>=6.0,<7.0` to `requirements.txt`.

#### Tests (`tests/test_repo_config.py`)
- Config loading (valid, partial, empty YAML, from text)
- No-op when file absent (empty config, no effect on analysis)
- Invalid config handling (non-dict, unknown keys, wrong types, malformed YAML)
- `exclude_paths` behavior (glob matching, filtering, excluded files produce no findings, tracked as skipped)
- `low_signal_paths` behavior (observation suppression)
- `provider_skip_paths` behavior (matching, all_provider_skip logic)
- Trust boundary preservation (config never creates findings, never affects scoring)
- ScanResult contract unchanged
- Scoring unchanged with and without config

#### Documentation
- New `docs/repo-config.md` — dedicated config documentation with field semantics, glob matching, examples, limitations
- Updated `README.md` — mentions repo config in status and docs table
- Updated `docs/getting-started.md` — config file section with example
- Updated `docs/github-action-setup.md` — `config_excluded` skip reason in table
- Updated `docs/trust-model.md` — config does not affect trust boundaries
- Updated `docs/validation.md` — config interaction with harness

### What did NOT change
- **ScanResult JSON contract** — unchanged
- **Scoring model** — unchanged (findings-only, deterministic)
- **Trust boundaries** — unchanged (provider output remains non-authoritative)
- **Finding categories** — unchanged
- **Deterministic checks** — still run on all non-excluded files
- **Provider trust level** — unchanged
- **Validation harness behavior** — scenarios run without config by default

### Design decisions
- **YAML over TOML/JSON** — YAML is familiar, widely used for CI/repo configs, supports comments, and aligns with GitHub Actions ecosystem.
- **Strict unknown-key rejection** — prevents silent misconfiguration from typos. Invalid config falls back to empty rather than partial application.
- **Frozen dataclass** — config is immutable after loading, preventing accidental mutation during pipeline execution.
- **Basename matching** — `*.lock` matches `deep/path/yarn.lock` via basename fallback, which is practical for common patterns.
- **exclude_paths tracks as SkippedFile** — excluded files remain visible in skipped-file metadata for transparency rather than being silently dropped.
- **Low-signal suppresses observations only** — deterministic checks still run on low-signal paths because real secrets in tests should still be caught.
- **Provider-skip is all-or-nothing at PR level** — if all changed paths match, provider is skipped entirely. Mixed PRs still invoke provider for non-skip files.

### Deferred concerns
- **Finding suppression remains deferred** — config cannot suppress specific finding types. This avoids premature policy complexity.
- **Richer policy/config remains deferred** — focus paths, repo criticality, provider policies, trust settings may be added later to the same file.
- **Config precedence/merging is simple** — one config source (the YAML file), no merging with env vars or Action inputs.
- **Per-path provider control** — provider_skip_paths is PR-level, not per-file within provider invocation.
- **Wildcard negation** — no exclusion-from-exclusion patterns (e.g. "all tests except integration tests").
- **Config validation could be stricter** — e.g. warning on redundant patterns, detecting unreachable globs. Kept simple for Phase 1.

## ADR-042: API surface expansion as a first-class review-triggering signal

**Date:** 2026-04-01

### Decision

Treat API surface expansion (new routes, endpoints, controllers, CRUD resources) as a first-class review-triggering signal. The provider gate is intentionally more permissive for security-relevant code-shape changes that expand the externally reachable API surface.

### Context

A recent PR that introduced a new authenticated CRUD resource and route stack did not trigger meaningful AI review. The existing planner and provider gate relied on sensitive-path and auth-path heuristics that missed new endpoint/resource patterns when they did not live in `auth/`, `config/`, or other traditionally sensitive directories.

New endpoints and CRUD resources are security-relevant: they create object-access patterns, require authentication enforcement, and need authorization consistency. Missing review for these changes is a product gap.

### What changed

#### Planner (`reviewer/planner.py`)
- Added `_API_SURFACE_PATH_SEGMENTS` (routes, controllers, handlers, endpoints, views, api, routers, resources)
- Added `_ROUTE_CONTENT_PATTERNS` — regex-based detection for route registration decorators, API router instantiation, versioned API paths, CRUD function definitions, auth middleware references, and resource controller classes
- `build_review_plan()` now calls `_apply_api_surface_focus()` which combines path-based and content-based signals
- When API surface expansion is detected: `api_surface_expansion` review flag is set, matched paths are added to `sensitive_paths_touched`, authentication/authorization focus areas are ensured
- New concern generated: "New API surface or CRUD resource" with `basis="api_surface_expansion"` and authorization category
- Reviewer guidance includes API surface note

#### Provider gate (`reviewer/provider_gate.py`)
- New signal: `api_surface_expansion` review flag triggers provider invocation
- Gate remains explicit and reason-based — the new signal is an additive invoke reason, not a threshold change

#### Bundle builder (`reviewer/bundle.py`)
- New review reason: `api_surface` for files detected in API surface areas
- `_classify_review_reason()` accepts `is_api_surface` parameter
- API surface files are treated as high-focus items (existing `has_high_focus_items` property already handles non-`changed_file` reasons)

#### Observation generator (`reviewer/observations.py`)
- New observation type: `_api_surface_observation()` for files with `api_surface` review reason
- Observations include authorization-focused guidance (object-level authz, cross-user data, auth enforcement)
- `basis="api_surface_bundle_item"` for traceability

#### Tests (`tests/test_api_surface_review.py`)
- 47 focused tests covering:
  - Path-based API surface detection (routes, controllers, handlers, endpoints, views, api directories)
  - Content-based route detection (FastAPI, Express, Flask, CRUD patterns, auth middleware)
  - Plan focus and flags
  - Provider gate behavior (invokes for routes, skips for plain utils)
  - Concern generation (authorization category, mentions access control)
  - Observation generation (API surface observations, no observations for plain files)
  - Full pipeline with mock and disabled providers
  - Negative cases (docs-only, tests, lockfiles, plain utilities stay quiet)
  - Scoring unchanged, ScanResult contract unchanged
  - Config exclusions still work
  - Trust boundary preservation (no provider-sourced findings)
  - Mixed scenarios (route + secret, auth route + memory)

#### Documentation
- `docs/quality-rubric.md` — added expectation 13 (API Surface Expansion Triggers Review)
- `docs/validation.md` — added API surface expansion test coverage section
- `docs/trust-model.md` — clarified that API surface expansion lowers gate threshold

### What did NOT change
- **ScanResult JSON contract** — unchanged
- **Scoring model** — unchanged (findings-only, deterministic)
- **Trust boundaries** — unchanged (provider output remains non-authoritative)
- **Finding categories** — unchanged (no new categories)
- **Deterministic checks** — unchanged
- **Low-signal quietness** — docs, tests, lockfiles, fixtures remain quiet

### Design decisions
- **Combined path + content detection** — path segments catch directory-organized routes; content patterns catch route registration in any file. Both are needed for broad coverage.
- **Content patterns exclude non-code files** — markdown, JSON, YAML, lock, and image files are excluded from content scanning to avoid false positives.
- **API surface paths treated as sensitive** — adding to `sensitive_paths_touched` leverages existing planner/bundle/observation infrastructure without a new code path.
- **`api_surface` review reason in bundle** — gives the observation generator a distinct code path for API-focused observations.
- **Concern at medium confidence** — API surface expansion is a reasonable basis for security concern but is heuristic, not deterministic.

### Deferred concerns
- **Content-based detection is regex heuristic** — it may miss custom routing frameworks or catch decorative uses. This is acceptable for Phase 1.
- **No AST-level analysis** — route detection does not parse code. Future phases may add framework-specific analysis.
- **Provider-backed findings remain deferred** — the gate opens more readily, but provider output still does not create findings.
- **Further gating refinement may be needed** — some patterns may produce false positives for internal utilities or test helpers that use route-like patterns.
- **Deterministic endpoint checks remain separate** — this change adds review triggering, not deterministic security rules for endpoints.

---

## ADR-043: Bounded code evidence in provider requests

**Status:** Accepted
**Date:** 2026-04-01
**Phase:** 1

### Context

Provider-backed review previously received primarily metadata about changed files — file paths, review reasons, focus areas, and existing concerns/observations. The actual file content available in `ReviewBundleItem.content` was not included in `ReasoningRequest` or the formatted user prompt. This caused vague, stereotype-driven provider output based on file names rather than code evidence (e.g., generic validation concerns for anything in a `routes/` directory).

### Decision

Provider requests now include bounded code evidence from `ReviewBundle` items via a new `review_targets` field on `ReasoningRequest`. Each review target carries:
- file path
- review reason and focus areas
- bounded code excerpt (max 1500 chars per file)
- related changed paths (when present)
- memory context and baseline context (when present)

Evidence is **intentionally bounded and prioritized**:
- Maximum 8 review targets per request
- Items prioritized by review reason: `sensitive_auth` > `api_surface` > `auth_area` > `sensitive_path` > `changed_file`
- Large files truncated to excerpt limit with `[truncated]` marker

The formatted user prompt now includes a `REVIEW TARGETS` section with code blocks and per-file metadata. The system prompt instructs the provider to base observations on actual code evidence and avoid vague path-based speculation.

### Consequences

**Unchanged:**
- **ScanResult JSON contract** — unchanged
- **Scoring model** — unchanged (findings-only, deterministic)
- **Trust boundaries** — unchanged (provider output remains non-authoritative candidate material)
- **Finding categories** — unchanged
- **Provider gate logic** — unchanged
- **Deterministic checks** — unchanged

**Changed:**
- `ReasoningRequest` gains a `review_targets` field with structured code evidence
- `build_reasoning_request()` builds prioritized, bounded review targets from ReviewBundle
- `_format_user_prompt()` renders a `REVIEW TARGETS` section with code blocks
- `_SYSTEM_PROMPT` instructs provider to use code evidence and avoid vague path-based observations

### Design decisions
- **Evidence-first over metadata-first prompting** — provider sees actual code, not just file names. This reduces vague output.
- **Bounded by design** — max 8 targets, max 1500 chars per excerpt. No complex token optimizer needed yet.
- **Priority-based selection** — security-relevant files (auth, sensitive, API surface) are selected before generic changed files.
- **ReviewBundle as evidence source** — reuses existing structured evidence rather than building a new data path.
- **Additive change** — the `changed_files_summary` field is preserved for backward compatibility; `review_targets` is a new addition.

### Deferred concerns
- **Diff-hunk-specific prompting** — currently sends file content, not diff hunks. Hunk-based excerpts may improve precision later.
- **Richer token budgeting** — current bounding is simple (char limit). Dynamic token budgeting across targets remains future work.
- **Provider-backed findings remain deferred** — evidence improvement does not change the trust boundary.
- **Larger multi-file semantic reasoning** — cross-file analysis with evidence remains future work.
- **Evidence quality metrics** — measuring whether evidence improves provider output quality is not automated yet.
