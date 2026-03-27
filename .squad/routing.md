# Work Routing

Use the smallest lead agent that can responsibly complete the work. Pull in additional agents when a change affects product intent, contracts, or verification.

## Lead Agent by Work Type

### Security Lead leads when work changes:
- security architecture
- reviewer scope or boundaries
- governance model
- policy behavior
- risk scoring principles
- what qualifies as a security finding

### Security Engineer leads when work changes:
- findings taxonomy
- detection logic
- rule design
- security heuristics
- secure defaults
- schema fields that originate from reviewer analysis

### Software Engineer leads when work changes:
- repo layout
- service boundaries
- API contracts
- GitHub Action implementation
- ingestion pipeline behavior
- operational plumbing for later dashboard support

### Tester leads when work changes:
- test strategy
- validation logic
- regression coverage
- false-positive controls
- output compatibility checks

### Scribe leads when work changes:
- repo memory
- architecture documentation
- ADRs
- roadmap state
- scope framing
- implementation rationale

## Escalation Rules

- Escalate to **Security Lead** when a proposed change could expand reviewer authority, alter security claims, or trade precision for broader coverage.
- Escalate to **Security Engineer** when implementation details affect detection fidelity, taxonomy boundaries, or secure defaults.
- Escalate to **Software Engineer** when a design choice adds service boundaries, workflow complexity, or integration coupling.
- Escalate to **Tester** when outputs, schemas, compatibility, or regressions are in question.
- Escalate to **Scribe** whenever the repo’s durable memory may become stale or misleading.

## Mandatory Reviews

### Security Lead review is required for:
- findings taxonomy changes
- policy logic
- risk scoring logic
- architecture changes

### Tester review is required before completing:
- reviewer output changes
- schema changes
- PR comment format changes
- dashboard metric changes

### Scribe involvement is required whenever:
- architecture decisions are made
- scope changes materially
- schemas or contracts change
- roadmap phase boundaries shift
- assumptions are invalidated
