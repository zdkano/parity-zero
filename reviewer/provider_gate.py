"""Provider invocation gating for parity-zero (ADR-029).

Determines whether live provider reasoning should run for a given PR
review based on context richness and security relevance signals from
the ``ReviewPlan`` and ``ReviewBundle``.

The gate is:
- **lightweight**: a pure function over existing pipeline structures
- **explicit**: returns a decision with explainable reasons
- **heuristic**: intentionally simple, not a scoring engine
- **phase-appropriate**: uses signals already available in Phase 1

The gate does **not** affect:
- ``DisabledProvider`` behavior (gate only applies when a provider is
  available)
- ``ScanResult`` JSON contract
- risk scoring or decision derivation
- trust boundaries around provider output

See ADR-029 for the decision record.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from reviewer.models import ReviewBundle, ReviewPlan


@dataclass(frozen=True)
class ProviderGateResult:
    """Result of provider invocation gating.

    Attributes:
        should_invoke: Whether provider reasoning should run.
        reasons: Explainable reasons for the gating decision.
            Always populated regardless of decision direction.
    """

    should_invoke: bool = False
    reasons: list[str] = field(default_factory=list)


def evaluate_provider_gate(
    plan: ReviewPlan | None,
    bundle: ReviewBundle | None,
) -> ProviderGateResult:
    """Evaluate whether live provider reasoning is justified.

    Examines context signals from the ``ReviewPlan`` and
    ``ReviewBundle`` to decide whether the PR context is rich enough
    or security-relevant enough to warrant a provider call.

    This is intentionally heuristic — it favours explicit reasons over
    opaque scoring.  The threshold is deliberately conservative: at
    least one meaningful signal must be present.

    Args:
        plan: The structured review plan (may be None in legacy path).
        bundle: The assembled review bundle (may be None).

    Returns:
        A ``ProviderGateResult`` with a decision and reasons.
    """
    if plan is None:
        return ProviderGateResult(
            should_invoke=False,
            reasons=["no review plan available — legacy path, skipping provider"],
        )

    invoke_reasons: list[str] = []
    skip_reasons: list[str] = []

    # -- Signal: sensitive paths touched --
    if plan.sensitive_paths_touched:
        invoke_reasons.append(
            f"sensitive paths touched: {len(plan.sensitive_paths_touched)}"
        )
    else:
        skip_reasons.append("no sensitive paths touched")

    # -- Signal: auth-related paths touched --
    if plan.auth_paths_touched:
        invoke_reasons.append(
            f"auth-related paths touched: {len(plan.auth_paths_touched)}"
        )
    else:
        skip_reasons.append("no auth-related paths touched")

    # -- Signal: meaningful focus areas --
    if plan.focus_areas:
        invoke_reasons.append(
            f"focus areas identified: {', '.join(plan.focus_areas)}"
        )
    else:
        skip_reasons.append("no focus areas identified")

    # -- Signal: relevant memory context --
    if plan.relevant_memory_categories:
        invoke_reasons.append(
            f"relevant memory categories: {', '.join(plan.relevant_memory_categories)}"
        )

    # -- Signal: bundle has high-focus items --
    if bundle is not None and bundle.has_high_focus_items:
        invoke_reasons.append("bundle contains items with elevated review focus")
    elif bundle is not None:
        skip_reasons.append("bundle items are all low-focus (changed_file only)")

    # -- Decision: at least one invoke reason required --
    should_invoke = len(invoke_reasons) > 0

    if should_invoke:
        reasons = [f"invoke: {r}" for r in invoke_reasons]
    else:
        reasons = [f"skip: {r}" for r in skip_reasons]

    return ProviderGateResult(
        should_invoke=should_invoke,
        reasons=reasons,
    )
