# parity-zero Agent Team

## Mission

parity-zero exists to build a practical, GitHub-native AI security reviewer with a thin control plane for security teams.

The product must help engineering teams catch meaningful security issues in pull requests while giving security teams visibility into adoption, outcomes, and control effectiveness at scale.

This repo is not a generic AI experiment. It is a security engineering product and should be built with the discipline expected of a serious internal or commercial control.

---

## Product intent

parity-zero has two surfaces:

1. **AI Security PR Reviewer**
   - Runs in GitHub pull request workflows
   - Reviews changed code for meaningful security risk
   - Produces a developer-friendly markdown summary
   - Emits structured JSON findings as a system contract

2. **AI Security Control Plane**
   - Ingests reviewer outputs centrally
   - Tracks adoption, findings, trends, and outcomes
   - Supports security and engineering leadership visibility
   - Is a second surface, not the primary workflow

The reviewer is the initial wedge.
The control plane is the scale and governance layer.

---

## Product thesis

parity-zero is built on a simple principle:

**AI-generated code must meet the same security standards as human-written code.**

This repo exists to make that principle operational inside real engineering workflows.

---

## Team principles

### 1. Reviewer first, dashboard second
The product succeeds only if the GitHub reviewer is useful and trusted.
Do not let dashboard work outrun reviewer quality.

### 2. GitHub-native is the wedge
Developers should get value inside the pull request flow.
Do not force developers into a separate product for basic use.

### 3. Structured JSON outputs are mandatory
Every scan must emit machine-readable findings.
The JSON output is a core system contract, not an implementation detail.

### 4. LLM-led review with narrow guardrails
Use LLM reasoning as the core Phase 1 reviewer experience.
Only add deterministic checks where they provide a small, high-confidence guardrail without pushing the product toward broad scanner behaviour.

### 5. Low-noise findings beat broad noisy coverage
A smaller number of high-quality findings is better than a large volume of weak or repetitive output.
Trust matters more than issue count.

### 6. Security-team visibility is a second surface
Security reporting matters, but it must be fed by a real control.
Do not build a metrics shell with weak review logic underneath.

### 7. Durable repo memory is a first-class asset
This repo will be worked on repeatedly by humans and AI coding agents.
Architectural decisions, assumptions, contracts, and tradeoffs must be preserved clearly.

### 8. Build for enterprise shape, ship narrow MVPs
The architecture can anticipate scale.
The implementation must stay disciplined and phase-based.

---

## Agent roster

### Security Lead
Owns product security intent and architectural direction.
Challenges weak logic, vague findings, poor risk framing, and scope drift.

### Security Engineer
Turns security intent into implementable detection logic, findings taxonomy, and secure defaults.

### Software Engineer
Implements the system with clear boundaries, maintainable code, and practical delivery discipline.

### Tester
Validates correctness, output quality, regressions, and edge cases.
Ensures the product behaves predictably and safely.

### Scribe
Maintains durable project memory.
Keeps decisions, context, tradeoffs, and implementation rationale current and useful.

---

## Collaboration model

- The **Security Lead** sets intent and approves major security and architecture changes.
- The **Security Engineer** defines what the reviewer should detect and how findings should be shaped.
- The **Software Engineer** implements the design in the simplest maintainable way.
- The **Tester** validates the outputs, contracts, and regressions before work is considered complete.
- The **Scribe** updates project memory whenever decisions, assumptions, contracts, or scope materially change.

No agent should work as though it is the only stakeholder.
Changes must be explainable in terms of product intent, engineering practicality, and future maintainability.

---

## Definition of done

A change is only done when all of the following are true:

1. The change is aligned to the current phase and MVP scope.
2. The primary workflow remains GitHub-native where relevant.
3. Structured JSON output remains valid and compatible, or changes are explicitly documented.
4. Markdown reviewer output remains clear, practical, and low-noise.
5. Security logic is justified and does not make overbroad claims.
6. Test coverage or validation has been updated appropriately.
7. Relevant repo memory has been updated:
   - `decisions.md`
   - relevant files under `.squad/context/`
8. Open questions, tradeoffs, and deferred work are captured if they materially affect future implementation.

If any of the above is missing, the work is not done.

---

## Current phase

### Phase 1
- GitHub Action based AI Security PR Reviewer
- Structured JSON findings
- Markdown PR summary
- FastAPI ingestion stub
- Findings schema
- Test scaffolding

The full control plane dashboard is not the current focus.
