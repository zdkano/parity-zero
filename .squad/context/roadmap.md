# parity-zero Roadmap Context

## Purpose

This file captures the phased delivery shape for parity-zero.

It is intentionally concise.
It exists to prevent scope confusion and keep implementation aligned to the current phase.

---

## Phase 1: Reviewer wedge and baseline foundation

### Goal
Establish parity-zero as a useful GitHub-native security reviewer **with
baseline repository context and memory foundations**.

### In scope
- GitHub Action reviewer
- changed-code analysis flow
- markdown PR summary
- structured JSON findings
- ingestion stub
- initial findings schema
- test scaffolding
- **baseline repository profiler** (stub with basic language/framework/path detection)
- **PR context builder** (combining changed files with baseline profile)
- **persistent memory models** (foundational structures, not full persistence)
- **contextual review engine direction** (architecture positioned for repo-aware review)

### Out of scope
- full dashboard
- full policy administration
- broad org-level governance workflows
- IDE integrations
- runtime agent enforcement
- full database-backed memory persistence
- real LLM provider integration

### Upcoming Phase 1 work direction
The next steps within Phase 1 should prioritise:
1. enriching baseline profiling with real repository analysis
2. wiring PR context builder into the review engine
3. connecting an LLM provider for contextual review
4. exercising memory models in the review flow

The focus should shift **away from expanding deterministic regex checks** and
**toward contextual review capabilities**.

---

## Phase 2: Ingestion, persistence, and baseline enrichment

### Goal
Turn reviewer output into central visibility for security teams, and begin
persisting baseline profiles and review memory.

### In scope
- findings ingestion backend
- findings store
- overview metrics
- repo-level views
- trend views
- basic filtering and search
- **persistent baseline profile storage**
- **review memory persistence** (prior findings themes, recurring patterns)
- **baseline profile refresh workflow**

### Out of scope
- advanced exception workflows
- large policy management features
- broad enterprise integration work

---

## Phase 3: Policy and governance

### Goal
Add control and governance features around reviewer adoption and decisioning.

### In scope
- policy modes
- exception handling
- reviewer coverage reporting
- control drift visibility
- governance-oriented metadata views
- **policy/intent context influencing review**

### Notes
This phase should only happen after the reviewer and thin dashboard prove useful.

---

## Phase 4: Rich repo-aware review with full memory

### Goal
Make parity-zero deeply context-aware with full memory-backed reasoning.

### In scope
- full repo-specific security context
- framework-aware overlays
- rich reasoning inputs from accumulated memory
- stronger mapping between repo intent and reviewer behaviour
- **recurring pattern detection from review history**
- **accepted risk and exception tracking**
- **security posture evolution tracking**

### Notes
This phase should improve signal quality without turning the product into a
general design platform.  The reviewer should increasingly behave like a
security engineer who knows the codebase.

---

## Roadmap guidance

### Stay phase-disciplined
Do not pull later-phase platform ideas into phase 1 without a strong reason.

### Protect the wedge
The reviewer remains the core product wedge even as the control plane grows.

### Context over scanning
Upcoming work should prioritise making the reviewer **more context-aware**
rather than expanding deterministic check coverage.

### Use evidence
If roadmap changes are proposed, base them on real reviewer usage or a clear
product rationale, not speculative breadth.