# parity-zero

AI-powered security reviewer for GitHub pull requests.

**AI-generated code must meet the same security standards as human-written code.**

## What is parity-zero?

parity-zero is a GitHub-native AI security reviewer that runs inside pull request workflows. It reviews changed code for meaningful security risk and emits structured JSON findings as a core system contract.

It is designed to reason like a security engineer — using repository context, baseline profiling, review memory, and structured planning — rather than pattern-matching like a traditional scanner.

parity-zero is **not** a replacement for SAST, SCA, or secret scanning. It is a contextual security reviewer that complements those tools.

## Status

**Phase 1 — Reviewer wedge.**

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
- stable ScanResult JSON contract
- **real PR file content loading** from workspace checkout
- **GitHub-native output**: job summary + PR comment posting
- **git diff-based changed file discovery** with API fallback

The control plane dashboard is intentionally deferred. See [roadmap context](.squad/context/roadmap.md).

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

# Run all tests (~1000 tests)
python -m pytest tests/ -v

# Run the reviewer locally with disabled provider
python -m reviewer.action

# Run the mock demo through the full pipeline
python -c "from reviewer.action import mock_run; r = mock_run(); print(r['markdown'])"

# Run validation scenarios
python -m pytest tests/test_validation_harness.py -v
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

See [GitHub Action Setup](docs/github-action-setup.md) for complete workflow examples with each provider mode.

## Documentation

| Document | Purpose |
|---|---|
| [Getting Started](docs/getting-started.md) | Installation, configuration, running locally |
| [Trust Model](docs/trust-model.md) | What outputs mean, what is authoritative, what is not |
| [GitHub Action Setup](docs/github-action-setup.md) | Workflow YAML examples, secrets, permissions |
| [Validation Harness](docs/validation.md) | Scenario-based testing and quality regression |
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
