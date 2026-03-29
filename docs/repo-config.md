# Repo-Level Configuration

parity-zero supports an optional `.parity-zero.yml` configuration file in the repository root. This file allows repository owners to customise reviewer behavior for their codebase.

## Status

**Intentionally narrow.** The repo config is a first step toward a broader configuration model. It currently supports path-level controls only. It does not support finding suppression, policy rules, provider selection, or account-specific settings. These may be added later to the same file without a redesign.

## Config File Location

Place a `.parity-zero.yml` file in the root of your repository (next to your `README.md`).

When the file is **absent**, parity-zero behaves exactly as it does without configuration — no behavior changes.

When the file is **present but invalid**, parity-zero logs a clear warning and falls back to default behavior. It does **not** silently misconfigure.

## Supported Fields

```yaml
# Paths excluded from meaningful review processing.
# Excluded files are not analysed for findings, concerns, or observations.
# They are tracked as skipped files for transparency.
exclude_paths:
  - "vendor/**"
  - "generated/**"
  - "docs/**"
  - "fixtures/golden/**"

# Paths that remain reviewable but receive quieter treatment.
# Observations are suppressed for low-signal files.
# Deterministic checks still run.
low_signal_paths:
  - "tests/**"
  - "*.lock"
  - "*.md"

# Paths where live provider reasoning is skipped.
# The rest of the pipeline (deterministic checks, planning, bundling)
# still processes these files.
provider_skip_paths:
  - "docs/**"
  - "fixtures/**"
  - "scripts/**"
```

All three fields are optional. Omit any field you don't need.

## How Glob Matching Works

Path patterns use glob-style matching via Python's `fnmatch`.  Each pattern is tested against the **full path** and every **path suffix** (successive tails after removing leading segments).

For a path like `test/eval/fixtures/data.json`, the suffixes tried are:

1. `test/eval/fixtures/data.json` (full path)
2. `eval/fixtures/data.json`
3. `fixtures/data.json`
4. `data.json` (basename)

This means a pattern like `fixtures/**` matches both `fixtures/data.json` and `test/eval/fixtures/data.json`.

| Pattern | Matches | Does NOT Match |
|---|---|---|
| `vendor/**` | `vendor/lib/foo.py`, `third_party/vendor/lib.js` | `src/vendor_utils.py` |
| `docs/**` | `docs/readme.md`, `src/docs/api/ref.md` | `src/mydocs.py` |
| `*.lock` | `yarn.lock`, `packages/yarn.lock` | `lockfile.py` |
| `*.generated.py` | `src/model.generated.py` | `src/model.py` |
| `tests/**` | `tests/test_auth.py`, `tests/unit/test_x.py` | `src/test_helper.py` |
| `fixtures/**` | `fixtures/data.json`, `test/eval/fixtures/data.json` | `src/fixtures_helper.py` |
| `README.md` | `README.md` | `docs/README.md` |

## Field Behavior

### `exclude_paths`

Files matching `exclude_paths` are removed from review processing before analysis begins.

**What happens to excluded files:**
- They are **not loaded** into review content
- They do **not** produce findings, concerns, or observations
- They do **not** trigger provider reasoning
- They are tracked as `SkippedFile` entries with reason `config_excluded` for transparency
- They appear in skipped-file counts in backend metadata (if backend integration is configured)

**Good candidates for exclusion:**
- Vendored / third-party code (`vendor/**`, `third_party/**`)
- Generated output (`generated/**`, `*.generated.*`)
- Documentation (`docs/**`)
- Build artifacts (`dist/**`, `build/**`)
- Fixture data for testing frameworks

### `low_signal_paths`

Files matching `low_signal_paths` remain in the review pipeline but receive quieter treatment.

**Current effects:**
- Observations (per-file security notes) are **suppressed** for low-signal files
- Deterministic checks still run — real security issues in tests are still caught
- Files are still included in review planning and bundling

**Good candidates for low-signal treatment:**
- Test files (`tests/**`, `*_test.py`, `test_*.py`)
- Lock files (`*.lock`, `package-lock.json`)
- Documentation-adjacent files (`*.md`, `CHANGELOG*`)
- Fixture and support code (`fixtures/**`, `testdata/**`)

### `provider_skip_paths`

Files matching `provider_skip_paths` are not sent to live provider reasoning, but the rest of the pipeline still processes them.

**Current effects:**
- When **all** changed files in a PR match `provider_skip_paths`, provider reasoning is skipped entirely
- When **some** files match, provider reasoning still runs for the non-matching files
- Deterministic checks still run for all files (including provider-skip files)
- Planning, bundling, and concern generation are unaffected

**Good candidates for provider skip:**
- Documentation (`docs/**`)
- Fixtures and test data (`fixtures/**`, `testdata/**`)
- Generated code (`generated/**`)
- Low-value bulk files (lock files, changelogs)
- Scripts and tooling (`scripts/**`, `tools/**`)

## What Config Does NOT Affect

The repo config does **not** change:

- **Trust boundaries** — provider output remains non-authoritative regardless of config
- **ScanResult JSON contract** — the structured output shape is unchanged
- **Scoring** — `decision` and `risk_score` are derived entirely from findings, not config
- **Finding categories** — the taxonomy is unchanged
- **Deterministic check behavior** — checks run on all non-excluded files (including low-signal and provider-skip files)

See [Trust Model](trust-model.md) for full details on output semantics.

## Invalid Config Handling

If `.parity-zero.yml` is present but invalid, parity-zero:

1. Logs a clear warning describing the problem
2. Falls back to default behavior (empty config / no-op)
3. Does **not** silently misconfigure or partially apply rules

Invalid config examples:
- YAML syntax errors
- Top-level value is not a mapping
- Unrecognised keys (typos, unsupported fields)
- Path list contains non-string or empty entries

## Example Configs

### Minimal — exclude vendored code only

```yaml
exclude_paths:
  - "vendor/**"
```

### Moderate — exclude generated, quieten tests, skip docs from provider

```yaml
exclude_paths:
  - "generated/**"
  - "vendor/**"
low_signal_paths:
  - "tests/**"
  - "*.lock"
provider_skip_paths:
  - "docs/**"
```

### Full — all three fields

```yaml
exclude_paths:
  - "vendor/**"
  - "generated/**"
  - "dist/**"
  - "fixtures/golden/**"
low_signal_paths:
  - "tests/**"
  - "*_test.py"
  - "*.lock"
  - "*.md"
provider_skip_paths:
  - "docs/**"
  - "fixtures/**"
  - "scripts/**"
  - "tools/**"
```

## Extendability

The config model is designed to support future fields without a redesign. Possible future additions include:

- `focus_paths` — paths that should receive elevated review attention
- `suppressions` — finding suppression rules (category + path)
- `repo_criticality` — repo-level risk classification
- `provider_policy` — provider selection or constraint rules
- `trust_settings` — per-repo trust calibration

These are **intentionally deferred**. The current config shape is narrow and phase-appropriate. See ADR-041 in `.squad/decisions.md`.

## Current Limitations

- **No finding suppression** — config cannot suppress specific finding types. This is deferred to avoid premature policy complexity.
- **No config precedence / merging** — there is one config source (the YAML file). Environment variables and Action inputs are not merged with config.
- **No per-path provider selection** — provider_skip_paths is all-or-nothing at the PR level (all paths must match to skip provider entirely).
- **No wildcard negation** — you cannot express "all tests except integration tests". Use explicit positive patterns.
- **Basename matching is simple** — `*.lock` matches any file ending in `.lock` regardless of depth. Complex patterns like `**/test_*.py` rely on fnmatch behavior.

These limitations are expected in the initial implementation and may be addressed in future iterations.
