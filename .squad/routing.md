# parity-zero Routing Rules

## Purpose

This file defines which agent should lead different kinds of work, when escalation is required, and when supporting review is mandatory.

The goal is to stop role confusion, prevent weak changes from slipping through, and maintain design discipline as the repo evolves.

---

## Primary routing

### Route to Security Lead when the work involves:
- security architecture changes
- reviewer scope changes
- risk scoring model changes
- policy logic changes
- trust model changes
- findings taxonomy changes
- changes that affect product positioning or control boundaries
- changes that may weaken enforcement, findings quality, or reviewer trust

### Route to Security Engineer when the work involves:
- detection logic
- rule design
- finding categories
- severity mapping
- confidence mapping
- reviewer heuristics
- secure defaults
- AI-specific security review patterns

### Route to Software Engineer when the work involves:
- repository layout
- implementation details
- API contracts
- GitHub Action plumbing
- ingestion pipeline implementation
- storage model implementation
- service boundaries
- internal refactoring
- control plane plumbing in later phases

### Route to Tester when the work involves:
- output validation
- regression testing
- schema validation
- edge case coverage
- false positive analysis
- end-to-end flow validation
- contract verification between reviewer and ingestion API

### Route to Scribe when the work involves:
- architecture decisions
- scope changes
- schema or contract changes
- roadmap changes
- changed assumptions
- tradeoff capture
- recording deferred work
- updating durable product or architecture context

---

## Mandatory review rules

### Security Lead review is required for:
- findings taxonomy changes
- policy logic changes
- risk scoring logic changes
- architecture changes
- control boundary changes
- changes that alter what the reviewer claims to detect or enforce

### Tester review is required before completion of:
- reviewer output changes
- JSON schema changes
- PR comment format changes
- ingestion payload changes
- dashboard metric definitions
- finding severity or confidence semantics

### Scribe involvement is required whenever:
- architecture decisions are made
- scope changes materially
- schemas or contracts change
- roadmap phase boundaries shift
- earlier assumptions are invalidated
- a tradeoff is accepted that future contributors need to understand

---

## Escalation rules

Escalate to Security Lead immediately if:
- a finding may be misleading or overstated
- a change could create false confidence in the reviewer
- a change blurs the boundary between deterministic checks and reasoning
- the product starts drifting toward dashboard-first development
- a proposed feature expands beyond the current phase without a clear reason

Escalate to Tester if:
- a contract is changing
- there is uncertainty about backward compatibility
- output quality may regress
- a new check could create noisy or unstable findings

Escalate to Scribe if:
- you made a non-trivial decision
- you rejected an alternative that may come up again later
- you changed an assumption that appears in docs or roadmap
- the current repo context no longer reflects reality

---

## Phase discipline

### Phase 1 routing bias
During phase 1, prefer work that directly supports:
- GitHub Action reviewer execution
- structured JSON findings
- markdown PR summaries
- ingestion stub
- basic test scaffolding

Deprioritise:
- large dashboard features
- policy administration UI
- enterprise governance workflows
- advanced org management
- broad integrations beyond GitHub

If a proposed change does not strengthen the reviewer wedge or its immediate data contract, challenge it.

---

## Conflict resolution

If agents disagree:
1. Re-anchor on current product phase.
2. Re-check `team.md` principles.
3. Prefer the simpler design unless there is a strong security reason not to.
4. Prefer preserving the JSON contract over short-term implementation convenience.
5. Record the decision in `decisions.md` if the disagreement exposed a meaningful tradeoff.

---

## Anti-patterns

Do not route work in ways that create these failures:

- Security Lead acting as sole implementer
- Software Engineer changing risk semantics without security review
- Tester being added only at the end after outputs are already assumed correct
- Scribe being skipped because “it was obvious”
- Dashboard work being treated as equal priority to reviewer trust in phase 1

These are failure modes, not shortcuts.