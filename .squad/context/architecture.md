# parity-zero Architecture Context

## Summary

parity-zero is designed as a reviewer-first, control-plane-ready system.

The initial implementation focuses on a GitHub-native reviewer that emits structured findings.
A thin backend and later dashboard are built around that contract.

---

## High-level components

### 1. GitHub Action Reviewer
Runs on pull request events and coordinates the review workflow.

Responsibilities:
- gather changed files and metadata
- invoke analysis logic
- produce markdown review output
- emit structured JSON
- optionally send output to a central backend

---

### 2. Analysis Engine
Evaluates pull request changes for security issues.

This combines:
- LLM-led contextual review
- narrow deterministic guardrails where they improve reviewer quality

The analysis engine is not expected to replace traditional scanners.
It is intended to provide focused review value in the PR workflow.

---

### 3. Deterministic Checks
Used only where small, high-confidence guardrails reduce reviewer noise or
catch obvious issues in changed code.

Examples:
- obvious insecure configuration
- simple auth/authz anti-patterns in known frameworks
- dangerous input handling patterns

These checks are intentionally narrow in Phase 1.
They support the reviewer but do not define the product.

---

### 4. Reasoning Layer
This is the primary Phase 1 analysis path.

Used for:
- contextual interpretation
- summarisation
- developer-friendly explanation
- ambiguous logic review
- prioritisation support

This layer should drive the reviewer experience in Phase 1 while staying
grounded in changed-code review rather than broad scanner-style coverage.

---

### 5. Central Ingestion API
Receives structured scan output from reviewer runs.

Responsibilities:
- validate payloads
- store scans and findings
- support retrieval and aggregation later
- establish a stable contract between reviewer and control plane

---

### 6. Findings Store
Stores scan metadata and structured findings.

The initial choice is Postgres because it supports:
- relational reporting
- filtering
- trend analysis
- repo and team views
- governance extensions later

---

### 7. Control Plane Dashboard
A later-phase UI for security teams.

Responsibilities:
- show reviewer adoption
- show findings trends
- show repo/team hotspots
- show outcome metrics
- support future governance views

This is intentionally not the first build priority.

---

## Architecture principles

### Reviewer-first
The system should remain useful even if the dashboard does not yet exist.

### Structured outputs first
The reviewer output contract is central.
All downstream components depend on it.

### Loose coupling
The reviewer and control plane should be linked by structured contracts, not hidden implementation dependencies.

### Simplicity over platform sprawl
The early system should remain easy to understand and easy to modify.

---

## High-level architecture diagram

```mermaid id="jy2b2v"
flowchart LR
    A[Developer or Coding Agent] --> B[GitHub Pull Request]
    B --> C[GitHub Action Reviewer]

    C --> D[Analysis Engine]
    D --> E[Narrow Guardrails]
    D --> F[LLM Review Layer]

    E --> G[Structured Findings JSON]
    F --> G

    G --> H[PR Comment / Check Output]
    G --> I[Central Ingestion API]

    I --> J[(Postgres Findings Store)]
    J --> K[Control Plane Dashboard]
