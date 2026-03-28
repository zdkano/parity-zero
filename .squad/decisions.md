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
