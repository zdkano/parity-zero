# Validation Harness

The PR validation harness is a scenario-based testing and evaluation framework for validating reviewer behavior across representative pull request situations. See ADR-032, ADR-038, and ADR-039.

## Purpose

The harness answers: "Does the reviewer behave correctly for this kind of PR?"

It runs curated PR scenarios through the **full reviewer pipeline** — context building, planning, bundling, analysis, scoring, and formatting — and evaluates the output against declarative expectations.

This supports:
- **Regression testing** — catch unintended behavior changes as the pipeline evolves
- **Quality tuning** — verify that low-noise, high-signal behavior is maintained
- **Trust boundary enforcement** — confirm provider output never pollutes findings or scoring
- **Pipeline coverage** — exercise different review paths (auth-sensitive, trivial, memory-influenced, etc.)
- **Provider comparison** — compare reviewer behavior across disabled/mock provider modes
- **Output quality validation** — verify conciseness, structure, and non-redundancy of output

## Two Corpora

The harness contains two complementary corpora:

- **Synthetic corpus** (13 scenarios) — inline content, minimal stubs covering key review paths. Defined in `reviewer/validation/scenario.py`.
- **Realistic corpus** (10 scenarios) — file-backed fixtures in `test/eval/fixtures/` with representative PR-like content. Defined in `reviewer/validation/realistic.py`.

Both corpora use the same `ValidationScenario` format. CLI commands like `--list`, `--tag`, `--summary`, `--compare`, and single-scenario lookup search **both** corpora by default. The `--realistic` command runs only the realistic corpus.

## What a Scenario Contains

A `ValidationScenario` pairs synthetic PR inputs with expected reviewer behavior:

```
ValidationScenario
├── id                   — unique identifier (e.g. "auth-sensitive")
├── description          — human-readable intent
├── changed_files        — dict of {path: content}
├── baseline_profile     — optional RepoSecurityProfile
├── memory               — optional ReviewMemory
├── provider_mode        — "disabled" or "mock" (never live)
├── tags                 — classification tags for filtering/grouping
├── security_focus       — expected security focus areas
├── provider_value_expected — whether provider should add meaningful value
└── expected             — ExpectedBehavior
    ├── provider_gate_invoked    — should gate invoke? (True/False/None)
    ├── min_findings             — minimum expected count
    ├── max_findings             — maximum expected count
    ├── finding_categories_present   — categories that must appear
    ├── finding_categories_absent    — categories that must NOT appear
    ├── has_concerns             — should concerns be present?
    ├── has_observations         — should observations be present?
    ├── max_concerns             — maximum expected concern count
    ├── max_observations         — maximum expected observation count
    ├── has_provider_notes       — should provider notes be present?
    ├── expected_sections        — markdown sections that must appear
    ├── absent_sections          — markdown sections that must NOT appear
    ├── markdown_contains        — substrings markdown must contain
    ├── markdown_omits           — substrings markdown must NOT contain
    └── no_trust_boundary_violations — provider did not pollute scoring (default: True)
```

## Synthetic Scenarios (13)

| ID | Description | Provider Mode | Tags |
|---|---|---|---|
| `auth-sensitive` | Auth-related files with baseline context and hardcoded AWS key | mock | auth, secrets, provider-value |
| `sensitive-config` | Debug mode and CORS wildcard in config | disabled | config, deterministic |
| `trivial-docs` | Documentation-only PR, no security signals | disabled | low-signal, no-findings, gate-skip |
| `memory-influenced` | Auth routes with review memory of prior issues | mock | auth, memory, provider-value |
| `deterministic-only` | Hardcoded AWS key, detected by deterministic checks only | disabled | secrets, deterministic, no-provider |
| `provider-enriched` | Auth middleware with mock provider enriching observations | mock | auth, provider-value, observations |
| `low-noise-tests` | Test-file-only PR, should produce clean quiet output | disabled | low-signal, no-findings, gate-skip |
| `pem-key-in-config` | PEM private key committed in config file | disabled | secrets, deterministic, no-provider |
| `plain-refactor` | Pure code refactoring, no security signals | disabled | low-signal, no-findings, gate-skip |
| `provider-gated-out` | Utility file, mock provider present but gate skips | mock | gate-skip, low-signal, provider-no-value |
| `mixed-auth-and-tests` | Auth code mixed with test files | mock | auth, mixed-signal, provider-value |
| `dependency-lockfile` | Lockfile-only changes, no code | disabled | low-signal, no-findings, gate-skip |
| `input-validation-risk` | Unsafe input handling in auth-adjacent code | mock | input-validation, memory, provider-value |

## Running the Harness

### Via pytest (recommended)

```bash
# Run all tests (from repo root — pytest.ini restricts to tests/)
python -m pytest tests/ -v

# Run all validation scenario tests
python -m pytest tests/test_validation_harness.py -v

# Run all evaluation tests (output quality, comparison, etc.)
python -m pytest tests/test_evaluation.py -v

# Run all realistic evaluation tests
python -m pytest tests/test_realistic_evaluation.py -v

# Run quality tuning assertions
python -m pytest tests/test_quality_tuning.py -v

# Run a specific scenario class
python -m pytest tests/test_validation_harness.py::TestAuthSensitiveScenario -v

# Run all scenarios through the parametrized pass check
python -m pytest tests/test_validation_harness.py::TestAllScenariosPass -v

# Run comparison tests
python -m pytest tests/test_evaluation.py::TestComparisonMode -v

# Run output quality tests
python -m pytest tests/test_evaluation.py::TestOutputQuality -v
```

### Via CLI entrypoint

All CLI commands search **both** synthetic and realistic corpora unless otherwise noted.

```bash
# Run all scenarios (synthetic + realistic)
python -m reviewer.validation

# Run a single scenario (searches both corpora)
python -m reviewer.validation auth-sensitive

# Compare one scenario across provider modes (searches both corpora)
python -m reviewer.validation --compare auth-sensitive

# Print concise evaluation summary table (all scenarios)
python -m reviewer.validation --summary

# List all scenarios with metadata (both corpora)
python -m reviewer.validation --list

# List scenarios by tag (searches both corpora)
python -m reviewer.validation --tag auth

# Run only realistic corpus
python -m reviewer.validation --realistic

# Print evaluation scorecard (realistic corpus)
python -m reviewer.validation --scorecard
```

### Programmatic access

```python
from reviewer.validation import (
    SCENARIOS, REALISTIC_SCENARIOS,
    all_scenarios, all_tags, all_scenarios_by_tag, find_scenario,
    run_scenario, run_comparison, format_comparison_summary,
    build_scorecard, format_scorecard,
)

# List all scenario ids (both corpora)
from reviewer.validation import all_scenario_ids
print(all_scenario_ids())

# Filter by tag across both corpora
auth_scenarios = all_scenarios_by_tag("auth")

# Look up any scenario by id (searches both corpora)
scenario = find_scenario("auth-sensitive")
result = run_scenario(scenario)

print(f"Passed: {result.passed}")
for a in result.assertions:
    status = "✓" if a.passed else "✗"
    print(f"  {status} {a.name}" + (f" — {a.detail}" if a.detail else ""))

# Compare across provider modes
comp = run_comparison(scenario)
print(format_comparison_summary(comp))

# Build scorecard for realistic corpus
scorecard = build_scorecard(REALISTIC_SCENARIOS)
print(format_scorecard(scorecard))
```

## Provider Comparison

The comparison layer runs the same scenario across provider modes and captures:

| Metric | What it shows |
|---|---|
| `findings_stable` | Whether deterministic findings are the same across modes |
| `decision_stable` | Whether decision/risk_score are the same |
| `provider_added_observations` | Whether mock mode added observations beyond disabled |
| `provider_added_notes` | Whether mock mode produced provider notes |
| `gate_differed` | Whether the gate decision differed |
| `trust_boundaries_held` | Whether trust boundaries held in all modes |

Comparison currently supports **disabled** and **mock** modes only. Live provider comparison (github-models, anthropic, openai) is structurally supported but requires credentials and is deferred.

## Realistic Scenarios (10)

The realistic corpus (ADR-039) extends the evaluation layer with 10 file-backed scenarios that load fixture content from `test/eval/fixtures/`. These provide more representative PR-like inputs than the synthetic scenarios above.

### How it differs from synthetic scenarios

- **File-backed** — changed file content is loaded from fixture files, not inline strings
- **Richer patterns** — fixtures contain realistic code structures, not minimal stubs
- **Representative** — scenarios cover the categories developers actually encounter in PRs

### Scenario categories

| ID | Description | Provider Mode | Tags |
|---|---|---|---|
| `realistic-missing-auth-route` | Auth route missing authentication middleware | mock | realistic, auth, provider-value |
| `realistic-authz-business-logic` | Authorization bypass in business logic | mock | realistic, authz, provider-value |
| `realistic-unsafe-sql-input` | Unsafe SQL input construction | mock | realistic, input-validation, memory, provider-value |
| `realistic-insecure-session-config` | Insecure configuration settings | disabled | realistic, config, deterministic |
| `realistic-github-token-exposure` | GitHub token exposed in source | disabled | realistic, secrets, deterministic, no-provider |
| `realistic-harmless-refactor` | Pure code refactor, no security signals | disabled | realistic, low-signal, no-findings, gate-skip |
| `realistic-docs-changelog` | Documentation and changelog changes only | disabled | realistic, low-signal, no-findings, gate-skip |
| `realistic-test-expansion` | Test file additions only | disabled | realistic, low-signal, no-findings, gate-skip |
| `realistic-provider-helpful-auth` | Auth code where provider adds useful context | mock | realistic, auth, provider-value, observations |
| `realistic-memory-recurring-vuln` | Recurring vulnerability flagged by review memory | mock | realistic, auth, authz, memory, provider-value |

### Running the realistic corpus

```bash
# Run only realistic scenarios
python -m reviewer.validation --realistic

# Print evaluation scorecard (realistic corpus)
python -m reviewer.validation --scorecard

# Compare a realistic scenario across provider modes
python -m reviewer.validation --compare realistic-missing-auth-route
```

## Assertion Types

The harness supports these assertion types:

| Assertion | What it checks |
|---|---|
| `provider_gate_invoked` | Whether the provider gate decided to invoke |
| `min_findings` / `max_findings` | Finding count bounds |
| `category_present` / `category_absent` | Specific finding categories present or absent |
| `has_concerns` | Whether ReviewConcerns were generated |
| `has_observations` | Whether ReviewObservations were generated |
| `max_concerns` / `max_observations` | Concern/observation count bounds |
| `has_provider_notes` | Whether provider notes were generated |
| `section_present` / `section_absent` | Markdown section presence/absence |
| `markdown_contains` / `markdown_omits` | Substring presence/absence in markdown output |
| `trust_boundary:no_provider_findings` | No findings originated from provider output |
| `trust_boundary:decision_deterministic` | Decision and risk_score match what findings alone would produce |

## Quality Expectations

The evaluation layer encodes these practical quality expectations (see `tests/test_evaluation.py`, `tests/test_realistic_evaluation.py`, and `tests/test_quality_tuning.py`):

- **No generic filler** — low-signal scenarios produce no findings, concerns, or observations
- **No duplicated output** — no duplicate finding title+file pairs
- **Observations tied to changed paths** — every observation references a file from the PR
- **Observation titles are file-specific** — include the actual file basename
- **Weak-signal scenarios stay quiet** — no provider invocation, no provider notes, minimal output (< 500 chars)
- **Provider notes do not become findings** — trust boundary enforced
- **Provider notes are non-generic** — metadata restatements are filtered
- **Provider-enriched observations remain non-authoritative** — trust boundary enforced, single-enrichment cap
- **Markdown structure remains correct** — correct sections present/absent based on content
- **Output remains concise** — no-findings scenarios have bounded markdown length, concerns capped per path

These are **heuristic quality checks**, not scientific benchmarks. They will evolve as the reviewer improves.

### API Surface Expansion Coverage (ADR-042)

Dedicated test coverage in `tests/test_api_surface_review.py` validates that:

- **New routes/endpoints trigger review interest** — path-based and content-based detection
- **CRUD resource stacks trigger provider invocation** — gate opens for API surface expansion
- **Concerns and observations are generated** — authorization-focused, non-authoritative
- **Low-signal changes remain quiet** — docs, tests, lockfiles, plain utilities unaffected
- **Trust boundaries hold** — no findings from provider, no scoring change, ScanResult unchanged
- **Config exclusions still work** — provider-skip and exclude paths suppress correctly
- **Mixed scenarios work** — API surface with secrets, with memory, with auth patterns

## Trust Boundary Invariants

Every scenario with `no_trust_boundary_violations=True` (the default) verifies:

1. **No provider-sourced findings** — provider output never creates findings
2. **Decision is deterministic** — decision and risk_score are derivable from findings alone

These invariants are enforced regardless of whether the provider is disabled or mock, and across all comparison modes.

## Credentials

The harness **never requires live credentials**. It uses only `DisabledProvider` and `MockProvider`. This means scenarios are:
- Deterministic and reproducible
- Safe to run in any environment
- Fast (no network calls)

## Intentionally Deferred

The following are intentionally **not** part of the current harness:

- **Live provider comparison** — testing with real API calls; structurally supported but remains opt-in (requires credentials, non-deterministic)
- **Benchmark scoring** — quantitative precision/recall metrics remain intentionally lightweight; the scorecard is a tuning aid, not a scientific benchmark
- **Performance measurement** — timing and resource usage tracking
- **Scenario generation** — automatic scenario creation from real PR data
- **Corpus expansion and versioning** — current corpus is point-in-time; snapshot tagging and systematic expansion remain future work
- **Cross-scenario regression** — comparing results across corpus versions
- **Quality assertions** — current heuristics are starting points that will evolve as the reviewer improves

These may be added in future phases as the reviewer pipeline matures.

## Repo Config Interaction

The validation harness runs scenarios without a `.parity-zero.yml` config file by default. This ensures baseline behavior is validated without config influence. Config-aware scenarios can be tested separately by passing a `RepoConfig` to the engine's `analyse()` function — see `tests/test_repo_config.py` for examples of config-aware testing.

Config behavior (ADR-041) does not affect trust boundary invariants — the harness continues to enforce that provider output never creates findings and that scoring is deterministic, regardless of config.
