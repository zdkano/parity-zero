# parity-zero Product Context

## Summary

parity-zero is a **repository-aware, GitHub-native AI security reviewer** with
persistent security memory and a thin control plane for security teams.

It is designed to help organisations apply the same security expectations to
AI-assisted code changes as they do to human-written code.

Its core principle is:

**AI-generated code must meet the same security standards as human-written code.**

parity-zero is **not** another deterministic scanner with a thin AI wrapper.

The real product is a **security reviewer that reasons like a security engineer**
over repository context, architectural patterns, security-relevant conventions,
prior review memory, and the specific PR delta.

---

## Product model

### 1. Baseline repository review
Before reviewing individual pull requests, parity-zero builds a **repository
security profile** — a lightweight baseline capturing:
- detected languages and frameworks
- authentication and authorisation patterns
- sensitive paths and directories
- security-relevant conventions
- architectural signals

This baseline makes subsequent PR reviews context-aware rather than stateless.

### 2. PR delta review against baseline context
Each PR review operates **in the context of the repository baseline**:
- what changed relative to the established security posture
- whether the change introduces novel risk or architectural inconsistency
- how the change relates to known sensitive areas

This is closer to how a security engineer reviews a real codebase — not a
pattern-matching pass over isolated files.

### 3. Deterministic support layer
Narrow, high-confidence deterministic checks remain valuable as a **supporting
signal layer**:
- catch obvious issues (hardcoded secrets, debug mode, CORS wildcards)
- enrich confidence of contextual findings
- provide anchoring signals

Deterministic checks are **not** the primary product value.  They support
the contextual review engine.

### 4. Persistent security memory / context
Over time, parity-zero accumulates **persistent review memory**:
- baseline repository profiles
- prior review findings and themes
- accepted risks or exceptions (later)
- recurring issue patterns per repo
- evolution of repository security posture

This memory allows later reviews to become increasingly repo-aware and
reduces repeated false positives and noise.

---

## Product surfaces

## 1. AI Security PR Reviewer
This is the primary product surface.

It runs in GitHub pull request workflows and is responsible for:
- analysing changed code **in the context of the repository baseline**
- identifying meaningful security issues through contextual reasoning
- producing structured JSON findings
- generating a developer-friendly markdown summary
- consuming deterministic support signals
- optionally influencing merge decisions later

This is the workflow-native wedge.

---

## 2. AI Security Control Plane
This is the secondary product surface.

It receives structured reviewer outputs centrally and is responsible for:
- adoption visibility
- findings aggregation
- trend analysis
- control effectiveness reporting
- repo and team risk visibility
- future governance and policy workflows
- persistent memory storage and retrieval

This is not the initial wedge.

---

## User types

### Developers
Need low-friction feedback inside pull requests.
Value:
- clear findings
- actionable recommendations
- low-noise output
- minimal workflow disruption

### Security engineers / AppSec / DevSecOps
Need confidence that AI-assisted development is being reviewed meaningfully.
Value:
- structured outputs
- repeatable findings
- evidence of risk patterns
- visibility into what is being caught before merge
- context-aware review that improves over time

### Security leadership / engineering leadership
Need visibility at scale.
Value:
- reviewer coverage
- findings trends
- high-risk repo hotspots
- adoption and remediation metrics

---

## Problems parity-zero is solving

### Problem 1: Existing controls are necessary but not enough
Traditional SAST, SCA, secret scanning, and IaC scanning remain essential, but
they do not fully address the review and governance needs introduced by
AI-assisted development.

### Problem 2: Stateless scanning misses context
Most automated scanners review code in isolation without understanding the
repository's architecture, conventions, or security posture.  A security
engineer brings context; parity-zero should too.

### Problem 3: Security teams need workflow-native controls
A useful control must fit into GitHub pull request workflows and help before
merge, not only after release or in central dashboards.

### Problem 4: Security leaders need measurable outcomes
At scale, organisations need to know:
- where the reviewer is enabled
- what it is finding
- which teams or repos are most exposed
- whether findings are being resolved before merge

---

## MVP scope

### In scope for Phase 1
- GitHub Action-based reviewer
- changed-code review focused on pull requests
- structured JSON findings
- markdown PR summary
- basic ingestion stub
- initial findings taxonomy
- test scaffolding
- **baseline repository profiling foundation** (models and stub)
- **PR context builder** (combining changed files with baseline profile)
- **persistent memory structures** (foundational models, not full persistence)

### Out of scope for Phase 1
- full dashboard implementation
- full policy administration UI
- IDE integrations
- MCP runtime enforcement
- threat modelling platform
- broad enterprise workflow automation
- full database-backed memory persistence
- real LLM provider integration
- heavy GitHub API integration beyond changed files

---

## Non-goals

parity-zero is not initially intended to be:
- a replacement for SAST or SCA
- another deterministic scanner with an AI wrapper
- a general AI governance platform
- a broad AppSec platform
- a full code assistant
- a full agent runtime security product

Those may become adjacent areas later, but they are not the initial product
boundary.

---

## Product shape

The intended progression is:

### Phase 1
Reviewer wedge — establish the reviewer flow, baseline profiling foundation,
and memory structures.

### Phase 2
Ingestion, thin control plane, and baseline profiling enrichment.

### Phase 3
Policy and governance workflows.

### Phase 4
Rich repo-aware review with full memory-backed reasoning.

The repo should be built with this shape in mind, but implementation must
remain disciplined and phase-based.