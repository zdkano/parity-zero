# parity-zero Copilot Instructions

You are working in the `parity-zero` repository.

This repository builds a **GitHub-native AI security PR reviewer** with a later **control plane** for security teams.

## Core product principle

**AI-generated code must meet the same security standards as human-written code.**

Everything in this repo should reinforce that principle.

---

## Current phase

This repo is currently in **Phase 1: reviewer wedge**.

Focus only on:
- GitHub Action based reviewer flow
- structured JSON findings
- markdown PR summary output
- FastAPI ingestion stub
- test scaffolding
- clean internal module boundaries

Do **not** drift into:
- full dashboard implementation
- policy administration UI
- broad organisation management features
- IDE integrations
- runtime agent enforcement
- speculative platform abstractions

---

## Mandatory repo context

Before making meaningful changes, read and follow:

- `.squad/team.md`
- `.squad/routing.md`
- `.squad/decisions.md`
- `.squad/hooks/before-write.md`
- `.squad/context/product.md`
- `.squad/context/architecture.md`
- `.squad/context/findings-taxonomy.md`
- `.squad/context/roadmap.md`

Treat these files as the durable product and engineering context for the repo.

If your proposed change conflicts with those files, do not proceed silently.
Call out the conflict and propose the smallest aligned change.

---

## Product intent

`parity-zero` has two surfaces:

1. **AI Security PR Reviewer**
   - primary product surface today
   - runs inside GitHub pull request workflows
   - reviews changed code
   - emits structured JSON findings
   - produces developer-friendly markdown output

2. **AI Security Control Plane**
   - later product surface
   - ingests reviewer results centrally
   - provides visibility into adoption, trends, and outcomes
   - must not become the main build focus during Phase 1

The reviewer is the wedge.
The control plane comes later.

---

## Engineering principles

### Reviewer first, dashboard second
Do not prioritise dashboard or reporting work over reviewer usefulness and trust.

### GitHub-native workflow is the wedge
Prefer designs that keep value inside the pull request flow.

### Structured JSON is a core contract
Every scan must emit machine-readable structured findings.
Do not casually change schema shape or semantics.

### Rules plus reasoning
Prefer deterministic checks where precision is possible.
Use reasoning for context, summarisation, and ambiguity handling.
Do not treat LLM output as unquestionable truth.

### Low-noise findings beat broad noisy coverage
Prefer a smaller number of useful findings over a larger number of weak ones.

### Simplicity over speculative architecture
Build only what the current phase needs.
Avoid plugin systems, excessive indirection, or premature platform layers.

---

## Current MVP finding categories

Only use these initial categories unless explicitly asked to expand them:

- authentication
- authorisation
- input validation
- secrets
- insecure configuration
- dependency risk

Do not invent extra categories during normal implementation.

---

## Expected output qualities

### Findings
Findings should be:
- concrete
- actionable
- appropriately scoped
- honest about confidence
- tied to changed code where possible

Do not produce vague security prose.

### Markdown PR summaries
PR output should be:
- concise
- structured
- readable by developers
- low-noise
- focused on meaningful issues

### JSON output
JSON findings must remain:
- stable
- explicit
- strongly shaped
- suitable for ingestion and later aggregation

---

## How to behave when making changes

### Before coding
- summarise the proposed change briefly
- state which phase goal it supports
- identify affected modules or contracts
- call out any likely schema or architecture impact

### While coding
- keep code clear and maintainable
- add comments only where they help explain intent or non-obvious behaviour
- avoid broad refactors unless necessary for the current task
- prefer explicit types and contracts

### After coding
- note what changed
- note any tradeoffs
- identify whether `decisions.md` or `.squad/context/*` should be updated
- highlight any deferred work rather than silently expanding scope

---

## Routing expectations

Follow `.squad/routing.md`.

In particular:

- involve **Security Lead** logic for:
  - findings taxonomy changes
  - risk scoring changes
  - policy logic changes
  - architecture changes

- involve **Tester** logic for:
  - schema changes
  - markdown output changes
  - ingestion payload changes
  - risk score behaviour changes

- involve **Scribe** logic when:
  - decisions change
  - assumptions change
  - contracts change
  - roadmap boundaries shift

If a change affects durable repo memory, say so explicitly.

---

## Anti-patterns to avoid

Do not:
- build the dashboard before the reviewer is credible
- add generic “AI platform” abstractions
- create broad policy engines too early
- overclaim what the reviewer can detect
- use optional-everything schemas
- replace structured findings with freeform prose
- silently change contracts
- let implementation drift away from the repo context

---

## Preferred implementation style

Prefer:
- small modules
- explicit schemas
- readable code
- straightforward tests
- narrow, phase-aligned changes
- clear separation between reviewer, schemas, and ingestion

Avoid:
- unnecessary indirection
- speculative extensibility
- hidden coupling
- magic behaviour without test coverage

---

## If unsure

If uncertain:
1. re-check the current phase
2. re-read `.squad/team.md` and `.squad/context/product.md`
3. choose the simpler design
4. preserve the JSON contract
5. avoid scope creep
