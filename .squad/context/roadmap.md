# parity-zero Roadmap Context

## Purpose

This file captures the phased delivery shape for parity-zero.

It is intentionally concise.
It exists to prevent scope confusion and keep implementation aligned to the current phase.

---

## Phase 1: Reviewer wedge

### Goal
Establish parity-zero as a useful GitHub-native security reviewer.

### In scope
- GitHub Action reviewer
- changed-code analysis flow
- markdown PR summary
- structured JSON findings
- ingestion stub
- initial findings schema
- test scaffolding

### Out of scope
- full dashboard
- full policy administration
- broad org-level governance workflows
- IDE integrations
- runtime agent enforcement

---

## Phase 2: Ingestion and thin control plane

### Goal
Turn reviewer output into central visibility for security teams.

### In scope
- findings ingestion backend
- findings store
- overview metrics
- repo-level views
- trend views
- basic filtering and search

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

### Notes
This phase should only happen after the reviewer and thin dashboard prove useful.

---

## Phase 4: Repo security context

### Goal
Make parity-zero more context-aware and policy-aware at repository level.

### In scope
- repo-specific security context
- framework-aware overlays
- richer reasoning inputs
- stronger mapping between repo intent and reviewer behaviour

### Notes
This phase should improve signal quality without turning the product into a general design platform.

---

## Roadmap guidance

### Stay phase-disciplined
Do not pull later-phase platform ideas into phase 1 without a strong reason.

### Protect the wedge
The reviewer remains the core product wedge even as the control plane grows.

### Use evidence
If roadmap changes are proposed, base them on real reviewer usage or a clear product rationale, not speculative breadth.