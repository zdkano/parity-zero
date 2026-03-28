# Getting Started

This guide covers installing, configuring, and running parity-zero locally.

## Requirements

- **Python 3.12+** (the GitHub Action uses Python 3.12)
- **pip** for dependency management

## Installation

```bash
git clone https://github.com/zdkano/parity-zero.git
cd parity-zero
pip install -r requirements.txt
```

Dependencies are intentionally minimal:
- `pydantic` — structured models and JSON contract
- `fastapi` / `uvicorn` — ingestion API stub
- `pytest` / `httpx` — testing

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `PARITY_REASONING_PROVIDER` | `disabled` | Provider selection: `disabled`, `github-models`, `anthropic`, `openai` |
| `PARITY_REASONING_MODEL` | *(per-provider)* | Model identifier override |
| `GITHUB_TOKEN` | *(none)* | GitHub API token; required for `github-models` provider |
| `ANTHROPIC_API_KEY` | *(none)* | Anthropic API key; required for `anthropic` provider |
| `OPENAI_API_KEY` | *(none)* | OpenAI API key; required for `openai` provider |
| `OPENAI_API_BASE` | *(none)* | Optional base URL for OpenAI-compatible endpoints |

No configuration is required for basic usage. The reviewer defaults to `disabled` provider mode — no API keys needed.

## Running the Reviewer Locally

### With disabled provider (default)

```bash
python -m reviewer.action
```

This runs the full reviewer pipeline with no live provider. It reads PR context from GitHub Actions environment variables (`GITHUB_EVENT_PATH`, `GITHUB_REPOSITORY`, `PR_NUMBER`). Outside of Actions, it produces output with empty PR context.

### Mock demo

The `mock_run()` function exercises the full pipeline with synthetic file contents:

```bash
python -c "
from reviewer.action import mock_run
result = mock_run()
print(result['markdown'])
print('---')
print(result['json'])
"
```

This demonstrates: file analysis → deterministic checks → reasoning → concerns → observations → ScanResult → markdown output.

### With a live provider

Set the appropriate environment variables before running:

```bash
# GitHub Models
export PARITY_REASONING_PROVIDER=github-models
export GITHUB_TOKEN=your-github-token
python -m reviewer.action

# Anthropic
export PARITY_REASONING_PROVIDER=anthropic
export ANTHROPIC_API_KEY=your-anthropic-key
python -m reviewer.action

# OpenAI
export PARITY_REASONING_PROVIDER=openai
export OPENAI_API_KEY=your-openai-key
python -m reviewer.action
```

Provider output is non-authoritative — see [Trust Model](trust-model.md).

## Running Tests

```bash
# Run the full test suite (~1000 tests)
python -m pytest tests/ -v

# Run a specific test file
python -m pytest tests/test_schemas.py -v

# Run validation scenario tests
python -m pytest tests/test_validation_harness.py -v

# Run with short output
python -m pytest tests/ -q
```

## Running Validation Scenarios

The validation harness runs curated PR scenarios through the full reviewer pipeline:

```bash
# All scenarios via pytest
python -m pytest tests/test_validation_harness.py -v

# Programmatic access
python -c "
from reviewer.validation.scenario import SCENARIOS, list_scenario_ids
print('Available scenarios:', list_scenario_ids())
"
```

See [Validation Harness](validation.md) for full details.

## Starting the Ingestion API (stub)

```bash
uvicorn api.main:app --reload
```

This runs the FastAPI ingestion stub locally. It is a placeholder for the future control plane — not a required component for reviewer operation.

## Troubleshooting

### `ModuleNotFoundError` when running commands

Ensure you are running from the repository root and dependencies are installed:

```bash
cd parity-zero
pip install -r requirements.txt
```

### Provider falls back to disabled

If you set `PARITY_REASONING_PROVIDER` but the reviewer logs show it falling back to `disabled`, check that the corresponding API key environment variable is set and non-empty. The resolver requires:
- `github-models` → `GITHUB_TOKEN`
- `anthropic` → `ANTHROPIC_API_KEY`
- `openai` → `OPENAI_API_KEY`

### Empty output from `python -m reviewer.action`

Outside of a GitHub Actions environment, the reviewer has no PR context to discover changed files. Use `mock_run()` for local testing, or run in a GitHub Actions workflow.

### Tests fail on import

Verify you are using Python 3.12+. The codebase uses `X | Y` union syntax and other 3.10+ features.
