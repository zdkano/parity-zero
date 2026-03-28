# Architecture Overview

This is a concise overview of the parity-zero reviewer pipeline for contributors. For detailed architecture context, see [.squad/context/architecture.md](../.squad/context/architecture.md).

## Pipeline Summary

```
PR Event
  │
  ▼
PullRequestContext ──────────── canonical input
  │  (changed files + baseline profile + review memory)
  │
  ▼
ReviewPlan ──────────────────── what to focus on
  │  (sensitive paths, auth areas, focus flags, memory matches)
  │
  ▼
ReviewBundle ────────────────── structured evidence per file
  │  (review reasons, focus areas, baseline context, memory context)
  │
  ├──▶ Deterministic Checks ── narrow high-confidence guardrails
  │      (secrets detection, insecure config patterns)
  │      produces: Finding[]
  │
  ├──▶ ReviewConcern[] ─────── plan-level contextual observations
  │
  ├──▶ ReviewObservation[] ──── per-file analysis notes
  │      (optionally enriched by provider output)
  │
  └──▶ Provider Gate ────────── should we call the provider?
         │
         ▼ (if yes)
       ReasoningProvider ────── candidate notes (non-authoritative)
         │
         ▼
       Observation Refinement ─ enrich observations with provider detail
  │
  ▼
AnalysisResult
  │  (findings + concerns + observations + provider notes + trace)
  │
  ▼
Scoring ─────────────────────── derive decision + risk_score from findings ONLY
  │
  ▼
ScanResult ──────────────────── structured JSON contract (authoritative output)
  │
  ▼
Markdown Summary ────────────── developer-facing PR output
  (findings + concerns + observations + provider notes)
```

## Key Components

### PullRequestContext
Canonical input combining PR delta (changed files), baseline repository profile, and review memory. Everything downstream operates on this context.

### ReviewPlan
Lightweight planning layer that determines review focus areas based on path analysis, baseline context, and memory. Produces plan-level `ReviewConcern` objects.

### ReviewBundle
Per-file evidence aggregation. Classifies files by review reason (sensitive, auth, combined, plain) and enriches them with relevant baseline and memory context.

### Deterministic Checks
Narrow, high-confidence pattern detectors. Currently: AWS key IDs, PEM private keys, GitHub tokens, CORS wildcards, debug mode, SSL verification disablement. These produce `Finding` objects — the only authoritative output.

### Provider Gate
Evaluates whether the PR context is rich enough to justify calling a reasoning provider. Considers sensitive paths, auth paths, focus areas, memory categories, and bundle focus.

### ReasoningProvider
Abstract interface for AI reasoning backends. Implementations: `DisabledProvider` (default no-op), `MockProvider` (testing), `GitHubModelsProvider`, `AnthropicProvider`, `OpenAIProvider`. Provider output is **candidate notes only** — non-authoritative.

### ReviewTrace
Internal traceability record capturing pipeline decisions: gate results, bundle stats, concern/observation counts, provider invocation outcome. Not exposed in ScanResult or markdown.

## Trust Boundary

The critical trust boundary in the pipeline:

- **Findings** (from deterministic checks) → **authoritative** → drive scoring and decision
- **Everything else** (concerns, observations, provider notes) → **non-authoritative** → informational only

Provider output never creates findings, affects scoring, or influences the pass/warn/block decision. This is an enforced invariant. See [Trust Model](trust-model.md).

## Module Map

```
reviewer/
  action.py          ─ entry point (GitHub Action orchestration)
  github_runtime.py  ─ runtime helpers (file discovery, loading, output surfacing)
  engine.py          ─ analysis engine (coordinates all layers)
  models.py          ─ data models (PRContent, PullRequestContext, ReviewPlan, etc.)
  planner.py         ─ review planning
  bundle.py          ─ review bundle building
  checks.py          ─ deterministic checks
  reasoning.py       ─ reasoning layer (contextual notes, provider integration)
  observations.py    ─ observation generation and refinement
  formatter.py       ─ markdown output formatting
  providers.py       ─ provider implementations
  provider_config.py ─ environment-based provider resolution
  provider_gate.py   ─ provider invocation gating
  prompt_builder.py  ─ structured reasoning request assembly
  baseline.py        ─ repository baseline profiling
  validation/        ─ PR validation scenario harness

schemas/
  findings.py        ─ Finding, ScanResult (JSON contract)

api/
  main.py            ─ FastAPI ingestion stub
  routes/ingest.py   ─ POST /ingest endpoint
```
