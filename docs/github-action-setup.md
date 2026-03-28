# GitHub Action Setup

parity-zero is designed to run as a GitHub Action on pull request events. This document covers workflow configuration for each provider mode.

## How It Works

1. A pull request is opened, synchronized, or reopened
2. The GitHub Action checks out the repository
3. parity-zero installs its Python dependencies
4. The reviewer runs: reads PR context → discovers changed files → runs analysis → emits JSON + markdown
5. Output is printed to the workflow log (PR comment posting is planned but not yet wired)

The action is defined in `action.yml` as a **composite action** that sets up Python 3.12 and runs `python -m reviewer.action`.

## Permissions

The workflow needs:

```yaml
permissions:
  contents: read          # Read repository contents
  pull-requests: write    # Post PR comments (when wired)
```

## Basic Workflow (Disabled Provider)

This is the simplest setup. No API keys needed. The reviewer runs with deterministic checks and heuristic-based contextual notes only.

```yaml
name: parity-zero Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    name: Security Review
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Run parity-zero reviewer
        uses: zdkano/parity-zero@main
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

When no `PARITY_REASONING_PROVIDER` is set, the reviewer defaults to `disabled` mode. This is safe — the reviewer produces structured findings from deterministic checks and contextual notes from heuristic analysis.

## GitHub Models Workflow

Uses the GitHub Models inference API. The `GITHUB_TOKEN` provided by Actions is sufficient — no additional secrets needed.

```yaml
name: parity-zero Review (GitHub Models)

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    name: Security Review
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Run parity-zero reviewer
        uses: zdkano/parity-zero@main
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
        env:
          PARITY_REASONING_PROVIDER: github-models
          # PARITY_REASONING_MODEL: openai/gpt-4o  # optional override (default: openai/gpt-4o-mini)
```

## Anthropic Workflow

Requires an Anthropic API key stored as a repository or organization secret.

```yaml
name: parity-zero Review (Anthropic)

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    name: Security Review
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Run parity-zero reviewer
        uses: zdkano/parity-zero@main
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
        env:
          PARITY_REASONING_PROVIDER: anthropic
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          # PARITY_REASONING_MODEL: claude-sonnet-4-20250514  # optional override
```

**To add the secret:** Repository → Settings → Secrets and variables → Actions → New repository secret → Name: `ANTHROPIC_API_KEY`

## OpenAI Workflow

Requires an OpenAI API key stored as a repository or organization secret.

```yaml
name: parity-zero Review (OpenAI)

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    name: Security Review
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Run parity-zero reviewer
        uses: zdkano/parity-zero@main
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
        env:
          PARITY_REASONING_PROVIDER: openai
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          # PARITY_REASONING_MODEL: gpt-4o  # optional override (default: gpt-4o-mini)
          # OPENAI_API_BASE: https://my-proxy.example.com/v1  # optional custom endpoint
```

**To add the secret:** Repository → Settings → Secrets and variables → Actions → New repository secret → Name: `OPENAI_API_KEY`

## Environment Variables Reference

| Variable | Required For | How to Set in Actions |
|---|---|---|
| `PARITY_REASONING_PROVIDER` | All provider modes | `env:` block in workflow |
| `PARITY_REASONING_MODEL` | None (optional override) | `env:` block in workflow |
| `GITHUB_TOKEN` | `github-models` | `${{ secrets.GITHUB_TOKEN }}` (auto-provided) |
| `ANTHROPIC_API_KEY` | `anthropic` | `${{ secrets.ANTHROPIC_API_KEY }}` (add as secret) |
| `OPENAI_API_KEY` | `openai` | `${{ secrets.OPENAI_API_KEY }}` (add as secret) |
| `OPENAI_API_BASE` | None (optional) | `env:` block in workflow |

## Safe Fallback Behavior

parity-zero is designed to **never fail** due to missing provider configuration:

- If `PARITY_REASONING_PROVIDER` is unset or `disabled` → runs with deterministic checks and heuristic notes only
- If a provider is configured but its API key is missing → falls back to `disabled` mode with a log warning
- If a provider is configured and available but the API call fails → continues with heuristic-based flow

Provider failure never prevents a review from completing. The reviewer always produces structured JSON output and a markdown summary regardless of provider availability.

## Referencing the Action

### From the same repository

```yaml
uses: ./
```

### From another repository (by branch)

```yaml
uses: zdkano/parity-zero@main
```

### From another repository (by tag — when available)

```yaml
uses: zdkano/parity-zero@v1.0.0
```

Tagged releases are not yet published. See [Release & Packaging](release-packaging.md) for Marketplace direction.

## Current Limitations

- **PR comment posting is not yet wired** — output goes to the workflow log. PR comment integration via the GitHub API is planned.
- **File contents are not yet read from the workspace** — the action discovers changed file paths via the GitHub API but currently passes empty content. The `mock_run()` path demonstrates the full engine with realistic content.
- **No caching** — dependencies are installed fresh on each run. pip caching can be added to the workflow for faster runs.
- **Single-job only** — the action runs as a single step. Matrix or parallel review is not supported.

These limitations are expected in Phase 1 and will be addressed as the reviewer matures.
