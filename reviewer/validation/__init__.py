"""PR validation harness for parity-zero (ADR-032, ADR-038, ADR-039).

Provides a lightweight framework for validating reviewer behavior across
curated pull request scenarios.  Designed for regression testing, quality
tuning, prompt tuning, and trust-boundary validation — without requiring
live provider credentials.

The harness has five layers:

1. **Scenario format** — ``ValidationScenario`` describes a PR situation
   and its expected reviewer behavior, with optional metadata (tags,
   security focus, provider-value expectations).
2. **Curated corpus** — ``SCENARIOS`` is a readable set of representative
   PR scenarios covering key review paths.
3. **Realistic corpus** — ``REALISTIC_SCENARIOS`` loads more
   representative, file-backed fixtures for evaluation and tuning
   (ADR-039).
4. **Validation runner** — ``run_scenario`` executes a scenario through
   the reviewer pipeline and returns a ``ValidationResult`` with
   structured pass/fail assertions.
5. **Comparison runner** — ``run_comparison`` runs the same scenario
   across provider modes and produces a ``ComparisonResult`` with
   cross-mode diffs.
6. **Scorecard** — ``build_scorecard`` produces a lightweight evaluation
   summary capturing stability, gate accuracy, quietness, noise, and
   provider value-add across a corpus (ADR-039).

See ADR-032 for the original decision record, ADR-038 for the
evaluation and benchmarking layer, and ADR-039 for the realistic
evaluation corpus and scorecard.
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
from reviewer.validation.realistic import (
    REALISTIC_SCENARIOS,
    get_realistic_scenario,
    list_realistic_ids,
)
from reviewer.validation.scorecard import (
    ScenarioScore,
    EvaluationScorecard,
    build_scorecard,
    format_scorecard,
)

__all__ = [
    "Assertion",
    "ExpectedBehavior",
    "ValidationScenario",
    "ValidationResult",
    "ModeResult",
    "ComparisonResult",
    "ScenarioScore",
    "EvaluationScorecard",
    "SCENARIOS",
    "REALISTIC_SCENARIOS",
    "get_scenario",
    "list_scenario_ids",
    "get_scenarios_by_tag",
    "list_tags",
    "get_realistic_scenario",
    "list_realistic_ids",
    "run_scenario",
    "run_comparison",
    "format_comparison_summary",
    "build_scorecard",
    "format_scorecard",
]
