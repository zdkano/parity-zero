"""PR validation harness for parity-zero (ADR-032).

Provides a lightweight framework for validating reviewer behavior across
curated pull request scenarios.  Designed for regression testing, quality
tuning, prompt tuning, and trust-boundary validation — without requiring
live provider credentials.

The harness has three layers:

1. **Scenario format** — ``ValidationScenario`` describes a PR situation
   and its expected reviewer behavior.
2. **Curated corpus** — ``SCENARIOS`` is a small, readable set of
   representative PR scenarios covering key review paths.
3. **Validation runner** — ``run_scenario`` executes a scenario through
   the reviewer pipeline and returns a ``ValidationResult`` with
   structured pass/fail assertions.

See ADR-032 for the decision record.
"""

from reviewer.validation.scenario import (
    ExpectedBehavior,
    ValidationScenario,
    SCENARIOS,
    get_scenario,
    list_scenario_ids,
)
from reviewer.validation.runner import (
    ValidationResult,
    run_scenario,
)

__all__ = [
    "ExpectedBehavior",
    "ValidationScenario",
    "ValidationResult",
    "SCENARIOS",
    "get_scenario",
    "list_scenario_ids",
    "run_scenario",
]
