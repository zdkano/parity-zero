# Validation Harness

The PR validation harness is a scenario-based testing and evaluation framework for validating reviewer behavior across representative pull request situations. See ADR-032 and ADR-038.

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

## Current Scenarios

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
# Run all validation scenario tests
python -m pytest tests/test_validation_harness.py -v

# Run all evaluation tests (output quality, comparison, etc.)
python -m pytest tests/test_evaluation.py -v

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

```bash
# Run all scenarios
python -m reviewer.validation

# Run a single scenario
python -m reviewer.validation auth-sensitive

# Compare one scenario across provider modes
python -m reviewer.validation --compare auth-sensitive

# Print concise evaluation summary table
python -m reviewer.validation --summary

# List all scenarios with metadata
python -m reviewer.validation --list

# List scenarios by tag
python -m reviewer.validation --tag auth
```

### Programmatic access

```python
from reviewer.validation import (
    SCENARIOS, get_scenario, list_scenario_ids,
    get_scenarios_by_tag, list_tags,
    run_scenario, run_comparison, format_comparison_summary,
)

# List available scenarios
print(list_scenario_ids())

# Filter by tag
auth_scenarios = get_scenarios_by_tag("auth")

# Run a single scenario
scenario = get_scenario("auth-sensitive")
result = run_scenario(scenario)

print(f"Passed: {result.passed}")
for a in result.assertions:
    status = "✓" if a.passed else "✗"
    print(f"  {status} {a.name}" + (f" — {a.detail}" if a.detail else ""))

# Compare across provider modes
comp = run_comparison(scenario)
print(format_comparison_summary(comp))
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

The evaluation layer encodes these practical quality expectations (see `tests/test_evaluation.py`):

- **No generic filler** — low-signal scenarios produce no findings, concerns, or observations
- **No duplicated output** — no duplicate finding title+file pairs
- **Observations tied to changed paths** — every observation references a file from the PR
- **Weak-signal scenarios stay quiet** — no provider invocation, no provider notes, minimal output
- **Provider notes do not become findings** — trust boundary enforced
- **Provider-enriched observations remain non-authoritative** — trust boundary enforced
- **Markdown structure remains correct** — correct sections present/absent based on content
- **Output remains concise** — no-findings scenarios have bounded markdown length

These are **heuristic quality checks**, not scientific benchmarks. They will evolve as the reviewer improves.

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

- **Live provider comparison** — testing with real API calls; structurally supported, needs credentials
- **Benchmark scoring** — quantitative precision/recall metrics across a large corpus
- **Performance measurement** — timing and resource usage tracking
- **Scenario generation** — automatic scenario creation from real PR data
- **Cross-scenario regression** — comparing results across corpus versions
- **Corpus versioning** — no version tagging for corpus snapshots

These may be added in future phases as the reviewer pipeline matures.
