# Validation Harness

The PR validation harness is a scenario-based testing framework for validating reviewer behavior across representative pull request situations. See ADR-032.

## Purpose

The harness answers: "Does the reviewer behave correctly for this kind of PR?"

It runs curated PR scenarios through the **full reviewer pipeline** — context building, planning, bundling, analysis, scoring, and formatting — and evaluates the output against declarative expectations.

This supports:
- **Regression testing** — catch unintended behavior changes as the pipeline evolves
- **Quality tuning** — verify that low-noise, high-signal behavior is maintained
- **Trust boundary enforcement** — confirm provider output never pollutes findings or scoring
- **Pipeline coverage** — exercise different review paths (auth-sensitive, trivial, memory-influenced, etc.)

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
└── expected             — ExpectedBehavior
    ├── provider_gate_invoked    — should gate invoke? (True/False/None)
    ├── min_findings             — minimum expected count
    ├── max_findings             — maximum expected count
    ├── finding_categories_present   — categories that must appear
    ├── finding_categories_absent    — categories that must NOT appear
    ├── has_concerns             — should concerns be present?
    ├── has_observations         — should observations be present?
    ├── markdown_contains        — substrings markdown must contain
    ├── markdown_omits           — substrings markdown must NOT contain
    └── no_trust_boundary_violations — provider did not pollute scoring (default: True)
```

## Current Scenarios

| ID | Description | Provider Mode |
|---|---|---|
| `auth-sensitive` | Auth-related files with baseline context and hardcoded AWS key | mock |
| `sensitive-config` | Debug mode and CORS wildcard in config | disabled |
| `trivial-docs` | Documentation-only PR, no security signals | disabled |
| `memory-influenced` | Auth routes with review memory of prior issues | mock |
| `deterministic-only` | Hardcoded AWS key, detected by deterministic checks only | disabled |
| `provider-enriched` | Auth middleware with mock provider enriching observations | mock |
| `low-noise-tests` | Test-file-only PR, should produce clean quiet output | disabled |

## Running the Harness

### Via pytest (recommended)

```bash
# Run all validation scenario tests
python -m pytest tests/test_validation_harness.py -v

# Run a specific scenario class
python -m pytest tests/test_validation_harness.py::TestAuthSensitiveScenario -v

# Run all scenarios through the parametrized pass check
python -m pytest tests/test_validation_harness.py::TestAllScenariosPass -v
```

### Programmatic access

```python
from reviewer.validation.scenario import SCENARIOS, get_scenario, list_scenario_ids
from reviewer.validation.runner import run_scenario

# List available scenarios
print(list_scenario_ids())

# Run a single scenario
scenario = get_scenario("auth-sensitive")
result = run_scenario(scenario)

print(f"Passed: {result.passed}")
for a in result.assertions:
    status = "✓" if a.passed else "✗"
    print(f"  {status} {a.name}" + (f" — {a.detail}" if a.detail else ""))
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
| `markdown_contains` / `markdown_omits` | Substring presence/absence in markdown output |
| `trust_boundary:no_provider_findings` | No findings originated from provider output |
| `trust_boundary:decision_deterministic` | Decision and risk_score match what findings alone would produce |

## Trust Boundary Invariants

Every scenario with `no_trust_boundary_violations=True` (the default) verifies:

1. **No provider-sourced findings** — provider output never creates findings
2. **Decision is deterministic** — decision and risk_score are derivable from findings alone

These invariants are enforced regardless of whether the provider is disabled or mock.

## Credentials

The harness **never requires live credentials**. It uses only `DisabledProvider` and `MockProvider`. This means scenarios are:
- Deterministic and reproducible
- Safe to run in any environment
- Fast (no network calls)

## Intentionally Deferred

The following are intentionally **not** part of the current harness:

- **Benchmark scoring** — quantitative precision/recall metrics across a large corpus
- **Live provider comparison** — testing with real API calls to compare provider quality
- **Performance measurement** — timing and resource usage tracking
- **Scenario generation** — automatic scenario creation from real PR data
- **Cross-scenario regression** — comparing results across scenario versions

These may be added in future phases as the reviewer pipeline matures.
