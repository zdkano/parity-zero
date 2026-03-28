# parity-zero

AI-powered security reviewer for GitHub pull requests.

**AI-generated code must meet the same security standards as human-written code.**

## What is parity-zero?

parity-zero is a GitHub-native AI security reviewer that runs inside pull request workflows. It reviews changed code for meaningful security risk and emits structured JSON findings as a core system contract.

It is designed to reason like a security engineer — using repository context, baseline profiling, review memory, and structured planning — rather than pattern-matching like a traditional scanner.

parity-zero is **not** a replacement for SAST, SCA, or secret scanning. It is a contextual security reviewer that complements those tools.

## Status

**Phase 1 → Phase 2 bridge — Reviewer wedge + hardened backend persistence.**

parity-zero is in active early development. The reviewer pipeline is functional with:
- baseline repository profiling
- review memory
- structured review planning (ReviewPlan)
- review evidence aggregation (ReviewBundle)
- plan-level concerns (ReviewConcern)
- per-file observations (ReviewObservation)
- deterministic findings (secrets, insecure configuration)
- provider-agnostic reasoning runtime with gating
- GitHub Models, Anthropic, and OpenAI provider support
- internal reviewer traceability (ReviewTrace)
- PR validation scenario harness
- **evaluation and benchmarking layer** — 13 curated scenarios, provider comparison, output-quality assertions (ADR-038)
- stable ScanResult JSON contract
- **real PR file content loading** from workspace checkout
- **skipped-file awareness** — changed files that are deleted, binary, too large, or unreadable are tracked with path and reason metadata (ADR-036)
- **GitHub-native output**: job summary + PR comment posting
- **git diff-based changed file discovery** with API fallback
- **thin backend persistence** — SQLite-backed ingest API with bearer token auth
- **run summary metadata** — provider status, concerns/observations/notes counts, changed/skipped file counts persisted per run (ADR-036)
- **optional action-to-backend wiring** — reviewer can send results to backend
- **hardened test isolation** — per-test fixtures, no shared global state (ADR-036)

The full control plane dashboard is intentionally deferred. See [roadmap context](.squad/context/roadmap.md).

## Supported Providers

| Provider | Env Value | Credentials Required |
|---|---|---|
| Disabled (default) | `disabled` | None |
| Mock (testing) | — | None |
| GitHub Models | `github-models` | `GITHUB_TOKEN` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` |
| OpenAI / ChatGPT | `openai` | `OPENAI_API_KEY` |

All providers are disabled by default. Provider output is **non-authoritative** — it does not create findings, affect scoring, or influence the pass/warn decision. See [trust model](docs/trust-model.md).

## Quick Start

```bash
# Clone and install
pip install -r requirements.txt

# Run all tests (~1260 tests)
python -m pytest tests/ -v

# Run the reviewer locally with disabled provider
python -m reviewer.action

# Run the mock demo through the full pipeline
python -c "from reviewer.action import mock_run; r = mock_run(); print(r['markdown'])"

# Run validation scenarios
python -m pytest tests/test_validation_harness.py -v

# Run evaluation summary
python -m reviewer.validation --summary

# Compare a scenario across provider modes
python -m reviewer.validation --compare auth-sensitive
```

See [Getting Started](docs/getting-started.md) for full setup instructions.

## GitHub Action Usage

parity-zero is designed to run as a GitHub Action on pull request events:

```yaml
- name: Run parity-zero reviewer
  uses: zdkano/parity-zero@main
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
```

The action automatically:
1. Discovers changed files via `git diff` against the PR base
2. Loads file contents from the checked-out workspace
3. Runs the full reviewer pipeline (deterministic checks + contextual analysis)
4. Posts results as a **GitHub job summary** (always) and **PR comment** (when permissions allow)
5. Optionally sends structured results to a backend ingest API (when `api_url` and `api_token` are configured)

See [GitHub Action Setup](docs/github-action-setup.md) for complete workflow examples with each provider mode and backend integration.

## Backend (Optional)

parity-zero includes a thin backend API for persisting review results:

- **SQLite-backed** — zero external dependencies, works locally
- **Authenticated** — bearer token auth via `PARITY_ZERO_AUTH_TOKEN`
- **Minimal** — ingest + retrieval only, no dashboard or analytics yet
- **Run summary metadata** — persists provider status, concern/observation/note counts, changed/skipped file counts per run

```bash
# Run the backend locally
export PARITY_ZERO_AUTH_TOKEN="your-secret-token"
uvicorn api.main:app --port 8000

# Send a result
curl -X POST http://localhost:8000/ingest \
  -H "Authorization: Bearer your-secret-token" \
  -H "Content-Type: application/json" \
  -d '{"repo":"acme/webapp","pr_number":1,"commit_sha":"abc1234","ref":"main","findings":[]}'
```

See [Backend Getting Started](docs/backend-getting-started.md) and [API Reference](docs/api.md).

## Documentation

| Document | Purpose |
|---|---|
| [Getting Started](docs/getting-started.md) | Installation, configuration, running locally |
| [Backend Getting Started](docs/backend-getting-started.md) | Backend setup, storage, auth, local testing |
| [API Reference](docs/api.md) | Endpoints, request/response shapes, auth, examples |
| [Trust Model](docs/trust-model.md) | What outputs mean, what is authoritative, what is not |
| [GitHub Action Setup](docs/github-action-setup.md) | Workflow YAML examples, secrets, permissions, backend integration |
| [Validation Harness](docs/validation.md) | Scenario-based testing, evaluation, and provider comparison |
| [Quality Rubric](docs/quality-rubric.md) | Reviewer quality expectations and what is enforced |
| [Architecture Overview](docs/architecture-overview.md) | High-level pipeline for contributors |
| [Release & Packaging](docs/release-packaging.md) | Marketplace direction and current packaging state |

### Internal Context

Architecture decisions and durable project context are in:
- `.squad/decisions.md` — ADR-style decision records
- `.squad/context/product.md` — product context
- `.squad/context/architecture.md` — detailed architecture
- `.squad/context/findings-taxonomy.md` — finding categories
- `.squad/context/roadmap.md` — phased delivery plan

## GitHub Marketplace

parity-zero is being built toward GitHub Action distribution and future GitHub Marketplace packaging. The current repo is functional as a GitHub Action referenced by path or repository, but Marketplace-specific release packaging is not yet complete. See [Release & Packaging](docs/release-packaging.md).
