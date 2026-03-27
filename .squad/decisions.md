# Architecture Decision Record Log

Keep entries short. Add a new ADR when intent, architecture, or contracts change in a durable way.

---

## ADR-001: Use GitHub Action first, GitHub App later
- **Status:** Accepted
- **Decision:** Ship the reviewer as a GitHub Action before considering a GitHub App.
- **Rationale:** The Action is the fastest GitHub-native wedge for PR review workflows and requires less platform surface to prove value.

## ADR-002: Prioritize reviewer before dashboard
- **Status:** Accepted
- **Decision:** Build the PR reviewer before the control plane dashboard.
- **Rationale:** Structured findings must exist before visibility tooling is worth building. The reviewer creates the data and adoption path.

## ADR-003: Make structured JSON the system contract
- **Status:** Accepted
- **Decision:** Treat structured JSON findings as the primary contract between review, ingestion, and reporting surfaces.
- **Rationale:** Stable machine-readable outputs reduce ambiguity, support testing, and keep the control plane optional but ready.

## ADR-004: Use FastAPI for the ingestion and control plane backend
- **Status:** Accepted
- **Decision:** Use FastAPI for the backend API layer.
- **Rationale:** FastAPI is a practical fit for typed request/response contracts, lightweight services, and clear schema handling.

## ADR-005: Use Postgres as the findings store
- **Status:** Accepted
- **Decision:** Persist reviewer findings and related metadata in Postgres.
- **Rationale:** Findings, runs, repositories, and policy metadata are naturally relational and benefit from durable querying.

## ADR-006: Keep the dashboard thin in later phases
- **Status:** Accepted
- **Decision:** Delay a full dashboard until ingestion and findings storage exist; keep the initial dashboard scope thin.
- **Rationale:** The second surface should summarize reviewer data, not drive early product complexity.

## ADR-007: Treat repo memory and decision tracking as first-class assets
- **Status:** Accepted
- **Decision:** Maintain `.squad/` context and ADRs as part of normal implementation work.
- **Rationale:** Repeated agent-assisted development needs accurate local context to avoid drift, rework, and shallow decisions.
