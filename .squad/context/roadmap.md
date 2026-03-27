# Roadmap

## Phase 1: Reviewer Wedge
- Build the GitHub Action-based PR reviewer.
- Emit structured JSON findings and markdown PR summaries.
- Focus on low-noise security findings in changed code.

## Phase 2: Ingestion + Dashboard
- Add a central ingestion API and findings store.
- Build a thin dashboard for visibility into findings, adoption, trends, and coverage.
- Keep the dashboard downstream of the reviewer contract.

## Phase 3: Policy and Governance
- Add policy controls, tuning workflows, and risk scoring governance.
- Improve org-level visibility into reviewer quality and enforcement behavior.

## Phase 4: Repo Security Context
- Add richer per-repo context to improve reviewer precision.
- Capture durable security assumptions, architecture context, and historical tuning signals.
