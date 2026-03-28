# parity-zero

AI-powered security reviewer for GitHub pull requests.

**AI-generated code must meet the same security standards as human-written code.**

## Overview

parity-zero is a GitHub-native AI security reviewer with a thin control plane for security teams. It runs in pull request workflows, reviews changed code for meaningful security risk, and emits structured JSON findings as a core system contract.

See `.squad/context/product.md` for full product context and `.squad/context/architecture.md` for architecture details.

## Current Phase

**Phase 1 — Reviewer wedge.** See `.squad/context/roadmap.md`.

Phase 1 keeps the LLM reviewer as the MVP. parity-zero is being built as an
AI reviewer for pull requests, not as a replacement for SAST, SCA, or other
broader scanning tooling.

## Repository Structure

```
reviewer/          GitHub Action reviewer (primary product surface)
  action.py        Entry point — orchestrates the review flow
  engine.py        Analysis engine — coordinates LLM review + guardrails
  checks.py        Narrow deterministic guardrail stubs
  reasoning.py     LLM review layer stub
  formatter.py     Markdown PR summary formatter

api/               FastAPI ingestion stub
  main.py          App entry point with health check
  routes/ingest.py POST /ingest endpoint

schemas/           Core JSON contract (ADR-003)
  findings.py      Pydantic models: Finding, ScanResult

tests/             Test scaffolding
  test_schemas.py  Schema validation tests
  test_reviewer.py Reviewer smoke tests
  test_api.py      API endpoint tests

action.yml         GitHub Action metadata
.github/workflows/ CI workflows
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/ -v

# Start the ingestion API locally
uvicorn api.main:app --reload
```

## Key Decisions

Architecture decisions are recorded in `.squad/decisions.md`.

## Reasoning Provider Configuration

parity-zero supports optional AI-powered reasoning via the provider system (ADR-025, ADR-026, ADR-031).  By default, reasoning is **disabled** — the reviewer runs with heuristic-based contextual notes only.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PARITY_REASONING_PROVIDER` | `disabled` | Provider selection: `disabled`, `github-models`, `anthropic`, or `openai` |
| `PARITY_REASONING_MODEL` | *(per-provider default)* | Model identifier override |
| `GITHUB_TOKEN` | *(none)* | GitHub token for authentication (required for `github-models`) |
| `ANTHROPIC_API_KEY` | *(none)* | Anthropic API key (required for `anthropic`) |
| `OPENAI_API_KEY` | *(none)* | OpenAI API key (required for `openai`) |
| `OPENAI_API_BASE` | *(none)* | Optional base URL override for OpenAI-compatible endpoints |

### Enabling GitHub Models

```yaml
env:
  PARITY_REASONING_PROVIDER: github-models
  GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  # PARITY_REASONING_MODEL: openai/gpt-4o  # optional: override default (openai/gpt-4o-mini)
```

### Enabling Anthropic

```yaml
env:
  PARITY_REASONING_PROVIDER: anthropic
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  # PARITY_REASONING_MODEL: claude-sonnet-4-20250514  # optional: override default
```

### Enabling OpenAI

```yaml
env:
  PARITY_REASONING_PROVIDER: openai
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  # PARITY_REASONING_MODEL: gpt-4o  # optional: override default (gpt-4o-mini)
  # OPENAI_API_BASE: https://my-proxy.example.com/v1  # optional: custom endpoint
```

When enabled, any provider generates **candidate notes** that appear in the PR summary as contextual observations.  Provider output is non-authoritative — it does not create findings, affect scoring, or influence the pass/warn decision.  The trust model is identical across all providers.

### Behavior When Disabled

When the provider is disabled (default), the reviewer produces the same output as before: heuristic-based contextual notes, deterministic findings, and structured scoring.  No API calls are made.

### Error Handling

If the provider is enabled but fails (network error, timeout, invalid response), the reviewer continues with its existing heuristic-based flow.  Provider failure never prevents a review from completing.
