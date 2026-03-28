# GitHub Action Setup

parity-zero is designed to run as a GitHub Action on pull request events. This document covers workflow configuration for each provider mode.

## How It Works

1. A pull request is opened, synchronized, or reopened
2. The GitHub Action checks out the repository
3. The action fetches the PR base commit (for `git diff`)
4. parity-zero installs its Python dependencies
5. The reviewer discovers changed files via `git diff` against the PR base
6. File contents are loaded from the workspace checkout
7. The reviewer runs: deterministic checks + contextual analysis → structured findings
8. Results are output as:
   - **GitHub job summary** — visible in the workflow run summary tab
   - **PR comment** — posted/updated on the pull request (when token has `pull-requests: write`)
   - **Structured JSON** — printed to the workflow log

The action is defined in `action.yml` as a **composite action** that sets up Python 3.12, fetches the PR base, and runs `python -m reviewer.action`.

## How Changed Files Are Discovered

The reviewer uses a two-tier approach:

1. **Primary: `git diff`** — runs `git diff --name-only --diff-filter=ACMR <base_sha> HEAD` using the PR base SHA from the GitHub event payload. This works with the checked-out repository and requires no additional API calls.
2. **Fallback: GitHub REST API** — if `git diff` fails (e.g., base SHA not available), falls back to the GitHub API to list changed files for the PR.

Files with status `removed` (deletions) are excluded — there is no content to review for deleted files.

## How File Contents Are Loaded

File contents are read from the workspace checkout (`GITHUB_WORKSPACE`):

- **Text files** (UTF-8 decodable) are loaded and reviewed
- **Binary files** are skipped (detected via UTF-8 decode failure)
- **Large files** (> 1 MB) are skipped with a log warning
- **Missing/deleted files** are skipped gracefully
- **Unreadable files** are skipped with a log message

This means the reviewer operates on the actual file contents from the PR head commit, as checked out by `actions/checkout`.

## How Results Are Surfaced

### GitHub Job Summary (baseline — always available)

The reviewer writes its markdown summary to `GITHUB_STEP_SUMMARY`. This is visible in the Actions workflow run page under the "Summary" tab. No additional permissions are required.

### PR Comment (when permissions allow)

The reviewer posts its markdown summary as a comment on the pull request. This requires the `pull-requests: write` permission.

**Comment behavior:**
- On first run, a new comment is created
- On subsequent runs, the **existing comment is updated** (not duplicated)
- The comment is identified by a `<!-- parity-zero-review -->` HTML marker
- If the token lacks `pull-requests: write`, the comment is silently skipped

**Known limitation:** The comment search checks the first 100 comments only. On PRs with more than 100 comments, a duplicate comment may be posted. This is a known Phase 1 limitation.

## Permissions

The workflow needs:

```yaml
permissions:
  contents: read          # Read repository contents and run git diff
  pull-requests: write    # Post/update PR comments
```

If `pull-requests: write` is not granted, the reviewer still works — it writes results to the job summary and workflow log, but skips PR comment posting.

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
| `PARITY_ZERO_API_URL` | Backend ingest (optional) | `${{ secrets.PARITY_ZERO_API_URL }}` (add as secret) |
| `PARITY_ZERO_API_TOKEN` | Backend ingest (optional) | `${{ secrets.PARITY_ZERO_API_TOKEN }}` (add as secret) |

## Safe Fallback Behavior

parity-zero is designed to **never fail** due to missing provider configuration:

- If `PARITY_REASONING_PROVIDER` is unset or `disabled` → runs with deterministic checks and heuristic notes only
- If a provider is configured but its API key is missing → falls back to `disabled` mode with a log warning
- If a provider is configured and available but the API call fails → continues with heuristic-based flow

Provider failure never prevents a review from completing. The reviewer always produces structured JSON output and a markdown summary regardless of provider availability.

## Backend Integration (Optional)

parity-zero can optionally send review results to a backend ingest API for persistence. This is fully opt-in — if not configured, the reviewer runs exactly as before.

### Configuring Backend Integration

Add these secrets to your repository:

1. **`PARITY_ZERO_API_URL`** — the base URL of your backend (e.g. `https://parity-zero.example.com`)
2. **`PARITY_ZERO_API_TOKEN`** — the bearer token for authentication

**To add secrets:** Repository → Settings → Secrets and variables → Actions → New repository secret

### Workflow with Backend Integration

```yaml
name: parity-zero Review (with backend)

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
          api_url: ${{ secrets.PARITY_ZERO_API_URL }}
          api_token: ${{ secrets.PARITY_ZERO_API_TOKEN }}
```

You can combine backend integration with any provider mode:

```yaml
      - name: Run parity-zero reviewer
        uses: zdkano/parity-zero@main
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          api_url: ${{ secrets.PARITY_ZERO_API_URL }}
          api_token: ${{ secrets.PARITY_ZERO_API_TOKEN }}
        env:
          PARITY_ZERO_API_URL: ${{ secrets.PARITY_ZERO_API_URL }}
          PARITY_ZERO_API_TOKEN: ${{ secrets.PARITY_ZERO_API_TOKEN }}
          PARITY_REASONING_PROVIDER: github-models
```

### Backend Integration Behavior

| Condition | Behavior |
|---|---|
| `PARITY_ZERO_API_URL` not set | Ingest silently skipped; reviewer runs normally |
| `PARITY_ZERO_API_TOKEN` not set | Ingest skipped with log warning; reviewer runs normally |
| Both set, backend reachable | Results sent to backend after review completes |
| Both set, backend unreachable | Ingest fails with log warning; **reviewer still succeeds** |
| Both set, backend returns error | Ingest fails with log warning; **reviewer still succeeds** |

Backend ingest failure **never** causes the GitHub Action to fail. The reviewer run is considered successful regardless of backend availability. Check the workflow logs for ingest status messages.

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

- **Comment dedup on large PRs** — the comment search checks the first 100 comments. PRs with more than 100 comments may get duplicate review comments.
- **Binary files are skipped** — non-UTF-8 files (images, compiled artifacts) are not reviewed.
- **Large files are skipped** — files over 1 MB are excluded to keep review times reasonable.
- **Deleted files are not reviewed** — files removed in the PR have no content to review; only added/modified/renamed files are analyzed.
- **No caching** — dependencies are installed fresh on each run. pip caching can be added to the workflow for faster runs.
- **Single-job only** — the action runs as a single step. Matrix or parallel review is not supported.
- **Shallow clone considerations** — the action fetches the PR base commit, but very shallow clones may occasionally cause `git diff` to fall back to the API method.

These limitations are expected in Phase 1 and will be addressed as the reviewer matures.
