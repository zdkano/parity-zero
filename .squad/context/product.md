# Product Context

## Product

AI Security PR Reviewer + Control Plane

## Reviewer Surface

The primary surface is a GitHub pull request reviewer that analyzes changed code, identifies meaningful security issues, emits structured JSON findings, and posts a developer-friendly markdown summary back into the PR workflow.

## Control Plane Surface

The secondary surface is a thin central dashboard for security teams. It ingests reviewer results and provides visibility into findings, adoption, trends, and coverage across repositories.

## User Types

- **Application developers:** receive security feedback in pull requests and fix issues before merge.
- **Security engineers:** define policy, tune findings quality, and track reviewer coverage.
- **Security program owners:** monitor adoption, trends, and risk patterns across teams.

## Problems Solved

- Catch meaningful security issues while code is still under review.
- Give developers feedback in the workflow they already use.
- Produce structured outputs that can be aggregated without re-parsing markdown.
- Give security teams visibility without forcing them into the primary developer loop.

## MVP Scope

- GitHub-native PR reviewer
- changed-code security analysis
- deterministic checks plus LLM reasoning
- structured JSON findings
- markdown PR summary
- ingestion-ready output contract

## Non-Goals

- broad codebase-wide SAST replacement
- full policy platform on day one
- dashboard-led workflow design
- noisy issue generation without clear remediation value
