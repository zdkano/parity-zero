"""CLI entrypoint for the evaluation harness (ADR-038, ADR-039).

Usage::

    # Run all synthetic scenarios
    python -m reviewer.validation

    # Run a single scenario
    python -m reviewer.validation auth-sensitive

    # Compare one scenario across provider modes
    python -m reviewer.validation --compare auth-sensitive

    # List all scenarios
    python -m reviewer.validation --list

    # List by tag
    python -m reviewer.validation --tag auth

    # Print concise evaluation summary for all
    python -m reviewer.validation --summary

    # Run realistic corpus
    python -m reviewer.validation --realistic

    # Run realistic corpus with scorecard
    python -m reviewer.validation --scorecard

    # Compare a realistic scenario
    python -m reviewer.validation --compare realistic-missing-auth-route
"""

from __future__ import annotations

import sys

from reviewer.validation.scenario import (
    SCENARIOS,
    get_scenario,
    get_scenarios_by_tag,
    list_scenario_ids,
    list_tags,
)
from reviewer.validation.realistic import (
    REALISTIC_SCENARIOS,
    get_realistic_scenario,
    list_realistic_ids,
)
from reviewer.validation.runner import run_scenario
from reviewer.validation.comparison import run_comparison, format_comparison_summary
from reviewer.validation.scorecard import build_scorecard, format_scorecard


def _print_result(result) -> bool:
    """Print a single scenario result.  Returns True if passed."""
    status = "PASS" if result.passed else "FAIL"
    print(f"  [{status}] {result.scenario_id}")
    for a in result.assertions:
        mark = "✓" if a.passed else "✗"
        line = f"    {mark} {a.name}"
        if a.detail:
            line += f" — {a.detail}"
        print(line)
    return result.passed


def _run_all() -> bool:
    """Run all scenarios and print results.  Returns True if all passed."""
    print(f"Running {len(SCENARIOS)} evaluation scenarios...\n")
    all_passed = True
    for scenario in SCENARIOS:
        result = run_scenario(scenario)
        if not _print_result(result):
            all_passed = False
        print()
    return all_passed


def _compare_one(scenario_id: str) -> bool:
    """Compare a scenario across disabled/mock modes."""
    scenario = get_scenario(scenario_id) or get_realistic_scenario(scenario_id)
    if scenario is None:
        all_ids = list_scenario_ids() + list_realistic_ids()
        print(f"Unknown scenario: {scenario_id}")
        print(f"Available: {', '.join(all_ids)}")
        return False
    comp = run_comparison(scenario)
    print(format_comparison_summary(comp))
    return comp.trust_boundaries_held


def _list_scenarios():
    """List all scenarios with metadata."""
    print(f"Evaluation corpus: {len(SCENARIOS)} scenarios\n")
    for s in SCENARIOS:
        tags = ", ".join(s.tags) if s.tags else "(none)"
        focus = ", ".join(s.security_focus) if s.security_focus else "(none)"
        pv = {True: "yes", False: "no", None: "n/a"}[s.provider_value_expected]
        print(f"  {s.id}")
        print(f"    {s.description[:80]}")
        print(f"    mode={s.provider_mode}  tags=[{tags}]  focus=[{focus}]  provider-value={pv}")
        print()
    print(f"Tags: {', '.join(list_tags())}")


def _list_by_tag(tag: str):
    """List scenarios with a specific tag."""
    matches = get_scenarios_by_tag(tag)
    if not matches:
        print(f"No scenarios with tag '{tag}'")
        print(f"Available tags: {', '.join(list_tags())}")
        return
    print(f"Scenarios tagged '{tag}': {len(matches)}\n")
    for s in matches:
        print(f"  {s.id} — {s.description[:60]}")


def _print_summary() -> bool:
    """Run all scenarios and print a concise summary table."""
    print(f"Evaluation summary ({len(SCENARIOS)} scenarios)\n")
    print(f"{'ID':<25} {'Mode':<10} {'Status':<6} {'Findings':<9} {'Concerns':<9} {'Obs':<5} {'Notes':<6} {'Gate':<12}")
    print("-" * 90)
    all_passed = True
    for scenario in SCENARIOS:
        result = run_scenario(scenario)
        a = result.analysis
        status = "PASS" if result.passed else "FAIL"
        if not result.passed:
            all_passed = False
        gate = a.trace.provider_gate_decision
        print(
            f"{scenario.id:<25} {scenario.provider_mode:<10} {status:<6} "
            f"{len(a.findings):<9} {len(a.concerns):<9} {len(a.observations):<5} "
            f"{len(a.provider_notes):<6} {gate:<12}"
        )
    print()
    return all_passed


def _run_realistic() -> bool:
    """Run all realistic scenarios and print results."""
    print(f"Running {len(REALISTIC_SCENARIOS)} realistic scenarios...\n")
    all_passed = True
    for scenario in REALISTIC_SCENARIOS:
        result = run_scenario(scenario)
        if not _print_result(result):
            all_passed = False
        print()
    return all_passed


def _print_scorecard(scenarios: list | None = None) -> bool:
    """Build and print an evaluation scorecard."""
    corpus = scenarios if scenarios is not None else REALISTIC_SCENARIOS
    label = "realistic" if scenarios is None else "custom"
    print(f"Building scorecard for {len(corpus)} {label} scenarios...\n")
    scorecard = build_scorecard(corpus)
    print(format_scorecard(scorecard))
    return scorecard.all_passed


def _run_one(scenario_id: str) -> bool:
    """Run a single scenario.  Returns True if passed."""
    scenario = get_scenario(scenario_id) or get_realistic_scenario(scenario_id)
    if scenario is None:
        all_ids = list_scenario_ids() + list_realistic_ids()
        print(f"Unknown scenario: {scenario_id}")
        print(f"Available: {', '.join(all_ids)}")
        return False
    result = run_scenario(scenario)
    return _print_result(result)


def main():
    """CLI entrypoint."""
    args = sys.argv[1:]

    if not args:
        ok = _run_all()
        sys.exit(0 if ok else 1)

    if args[0] == "--list":
        _list_scenarios()
        return

    if args[0] == "--tag" and len(args) >= 2:
        _list_by_tag(args[1])
        return

    if args[0] == "--summary":
        ok = _print_summary()
        sys.exit(0 if ok else 1)

    if args[0] == "--compare" and len(args) >= 2:
        ok = _compare_one(args[1])
        sys.exit(0 if ok else 1)

    if args[0] == "--realistic":
        ok = _run_realistic()
        sys.exit(0 if ok else 1)

    if args[0] == "--scorecard":
        ok = _print_scorecard()
        sys.exit(0 if ok else 1)

    # Single scenario by id (searches both synthetic and realistic)
    ok = _run_one(args[0])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
