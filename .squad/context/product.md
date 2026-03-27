# parity-zero Product Context

## Summary

parity-zero is a GitHub-native AI security reviewer with a thin control plane for security teams.

It is designed to help organisations apply the same security expectations to AI-assisted code changes as they do to human-written code.

Its core principle is:

**AI-generated code must meet the same security standards as human-written code.**

---

## Product surfaces

## 1. AI Security PR Reviewer
This is the primary product surface in the initial phase.

It runs in GitHub pull request workflows and is responsible for:
- analysing changed code
- identifying meaningful security issues
- producing structured JSON findings
- generating a developer-friendly markdown summary
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
Traditional SAST, SCA, secret scanning, and IaC scanning remain essential, but they do not fully address the review and governance needs introduced by AI-assisted development.

### Problem 2: Security teams need workflow-native controls
A useful control must fit into GitHub pull request workflows and help before merge, not only after release or in central dashboards.

### Problem 3: Security leaders need measurable outcomes
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

### Out of scope for Phase 1
- full dashboard implementation
- full policy administration UI
- IDE integrations
- MCP runtime enforcement
- threat modelling platform
- broad enterprise workflow automation

---

## Non-goals

parity-zero is not initially intended to be:
- a replacement for SAST or SCA
- a general AI governance platform
- a broad AppSec platform
- a full code assistant
- a full agent runtime security product

Those may become adjacent areas later, but they are not the initial product boundary.

---

## Product shape

The intended progression is:

### Phase 1
Reviewer wedge

### Phase 2
Ingestion plus thin control plane

### Phase 3
Policy and governance workflows

### Phase 4
Richer repo security context and broader control intelligence

The repo should be built with this shape in mind, but implementation must remain disciplined and phase-based.