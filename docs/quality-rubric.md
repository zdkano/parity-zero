# Reviewer Quality Rubric

This document describes the practical quality expectations that parity-zero enforces through its evaluation layer. These are heuristic expectations — they encode what "good reviewer behavior" means today and will evolve as the pipeline improves.

See ADR-038 for context. These expectations are enforced in `tests/test_evaluation.py`.

## What This Is

This is **not** a scientific benchmark or precision/recall scorecard. It is a practical rubric that helps answer:

- Is the reviewer useful on representative PRs?
- Is it quiet when it should be?
- Are trust boundaries holding?
- Is provider reasoning adding value or just noise?

## Core Quality Expectations

### 1. No Generic Filler

The reviewer should not produce output for the sake of producing output.

- Low-signal scenarios (docs, tests, refactoring, lockfiles) should produce **zero** findings, concerns, observations, and provider notes.
- The markdown for these scenarios should be short (< 2000 chars) and contain only the pass verdict.

### 2. No Duplicated Output

- No finding should duplicate another finding for the same title + file combination.
- Concerns, observations, and provider notes should cover distinct aspects.
- Provider notes that overlap with existing observations are suppressed (60% keyword threshold).

### 3. Observations Tied to Changed Paths

Every `ReviewObservation` must reference a file that is actually part of the PR's changed files. Observations about files not in the diff are incorrect.

### 4. Weak-Signal Scenarios Stay Quiet

When the PR context has no security-relevant signals:

- The provider gate should **not** invoke the provider.
- No provider notes should be generated.
- No concerns or observations should appear.
- The output should say "No security findings" and nothing else of substance.

### 5. Provider Notes Do Not Become Findings

This is the core trust boundary. Provider output is candidate material — it may be useful context, but it must never:

- Create a `Finding` (which affects scoring)
- Change the `decision` (pass/warn/block)
- Change the `risk_score`

### 6. Provider-Enriched Observations Remain Non-Authoritative

When provider notes enrich existing observations, the enriched observations:

- Are marked with `+provider_enriched` in their basis
- Use hedged language ("may", "consider", "worth verifying")
- Do not change their trust level
- Remain non-scoring

### 7. Markdown Structure Is Correct

- The "Security Review" header is always present.
- The "Provider Notes" section is absent when there are no provider notes.
- Sections are clearly separated (findings vs concerns vs observations vs provider notes).
- The output is readable and sectioned correctly.

### 8. Deterministic Findings Are Stable

Running the same scenario twice should produce identical findings. Running with disabled vs mock provider should produce the same deterministic findings (deterministic checks are provider-independent).

### 9. Provider Gate Behaves Correctly

- Auth-sensitive, memory-influenced, and high-context PRs should invoke the gate.
- Low-signal PRs (docs, tests, refactoring) should skip the gate.
- The gate should not invoke on context-free PRs even when provider mode is "mock".

### 10. Provider Notes Are Bounded

- No scenario should produce more than 10 provider notes (capped by the system).
- When the gate skips, zero provider notes should appear.

## What Remains Subjective

Some quality aspects are intentionally **not** encoded as automated checks:

- **Usefulness of individual findings** — whether a specific finding is actually helpful to a developer depends on context that automated checks cannot fully evaluate.
- **Concern relevance** — whether a concern is useful context or unnecessary noise is partially subjective.
- **Observation depth** — whether an observation provides enough detail without being verbose is a judgment call.
- **Provider note quality** — whether a mock provider note is realistic enough to test against is inherently limited by the mock's simplicity.

These may be addressed in future phases through manual review, human evaluation, or more sophisticated automated quality metrics.

## How to Use This Rubric

1. **Before changing the pipeline**: Run `python -m reviewer.validation --summary` to see current behavior.
2. **After changing the pipeline**: Run `python -m pytest tests/test_evaluation.py -v` to verify quality expectations still hold.
3. **When tuning**: Use `python -m reviewer.validation --compare <scenario>` to see how changes affect disabled vs mock behavior.
4. **When adding scenarios**: Follow the existing corpus patterns and add appropriate tags, security_focus, and expected behavior assertions.
