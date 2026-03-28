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
