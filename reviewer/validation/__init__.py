"""PR validation harness for parity-zero (ADR-032, ADR-038).

Provides a lightweight framework for validating reviewer behavior across
curated pull request scenarios.  Designed for regression testing, quality
tuning, prompt tuning, and trust-boundary validation — without requiring
live provider credentials.

The harness has four layers:

1. **Scenario format** — ``ValidationScenario`` describes a PR situation
   and its expected reviewer behavior, with optional metadata (tags,
   security focus, provider-value expectations).
2. **Curated corpus** — ``SCENARIOS`` is a readable set of representative
   PR scenarios covering key review paths.
3. **Validation runner** — ``run_scenario`` executes a scenario through
   the reviewer pipeline and returns a ``ValidationResult`` with
   structured pass/fail assertions.
4. **Comparison runner** — ``run_comparison`` runs the same scenario
   across provider modes and produces a ``ComparisonResult`` with
   cross-mode diffs.

See ADR-032 for the original decision record and ADR-038 for the
evaluation and benchmarking layer.
"""

from reviewer.validation.scenario import (
    ExpectedBehavior,
    ValidationScenario,
    SCENARIOS,
    get_scenario,
    list_scenario_ids,
    get_scenarios_by_tag,
    list_tags,
)
from reviewer.validation.runner import (
    Assertion,
    ValidationResult,
    run_scenario,
)
from reviewer.validation.comparison import (
    ModeResult,
    ComparisonResult,
    run_comparison,
    format_comparison_summary,
)

__all__ = [
    "Assertion",
    "ExpectedBehavior",
    "ValidationScenario",
    "ValidationResult",
    "ModeResult",
    "ComparisonResult",
    "SCENARIOS",
    "get_scenario",
    "list_scenario_ids",
    "get_scenarios_by_tag",
    "list_tags",
    "run_scenario",
    "run_comparison",
    "format_comparison_summary",
]
