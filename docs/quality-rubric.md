# Reviewer Quality Rubric

This document describes the practical quality expectations that parity-zero enforces through its evaluation layer. These are heuristic expectations — they encode what "good reviewer behavior" means today and will evolve as the pipeline improves.

See ADR-038, ADR-039, and ADR-040 for context. These expectations are enforced in `tests/test_evaluation.py`, `tests/test_realistic_evaluation.py`, and `tests/test_quality_tuning.py`.

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
- The markdown for these scenarios should be short (< 500 chars) and contain only the pass verdict.
- Provider notes that merely restate pipeline metadata (file counts, focus areas, baseline frameworks, memory categories) are suppressed.

### 2. No Duplicated Output

- No finding should duplicate another finding for the same title + file combination.
- Concerns, observations, and provider notes should cover distinct aspects.
- Provider notes that overlap with existing observations are suppressed (60% keyword threshold).
- Metadata restatement notes are filtered (content-quality filter).
- Notes with very short summaries (< 15 chars) are filtered.
- Concerns targeting the same paths are deduplicated in markdown output (max 2 per path group, max 5 total).

### 3. Observations Tied to Changed Paths

Every `ReviewObservation` must reference a file that is actually part of the PR's changed files. Observations about files not in the diff are incorrect.

### 4. Observation Titles Are File-Specific

Observation titles include the actual file basename (e.g., "Auth-sensitive boundary: users.py" rather than a generic "Security boundary in auth-sensitive area"). This helps developers quickly identify which file an observation relates to.

### 5. Weak-Signal Scenarios Stay Quiet

When the PR context has no security-relevant signals:

- The provider gate should **not** invoke the provider.
- No provider notes should be generated.
- No concerns or observations should appear.
- The output should say "No security findings" and nothing else of substance.
- The markdown should have no concern, observation, or provider note sections.

### 6. Provider Notes Do Not Become Findings

This is the core trust boundary. Provider output is candidate material — it may be useful context, but it must never:

- Create a `Finding` (which affects scoring)
- Change the `decision` (pass/warn/block)
- Change the `risk_score`

### 7. Provider-Enriched Observations Remain Non-Authoritative

When provider notes enrich existing observations, the enriched observations:

- Are marked with `+provider_enriched` in their basis
- Use hedged language ("may", "consider", "worth verifying")
- Do not change their trust level
- Remain non-scoring
- Each observation is enriched at most once (no double-enrichment)
- Enrichment is rejected when provider detail is too short (< 30 chars) or overlaps heavily with existing summary (> 60% keyword overlap)

### 8. Provider Notes Are Non-Generic

Provider notes should add file-specific security insight, not restate pipeline metadata. The following patterns are filtered:

- File count summaries ("Analysed N changed file(s)")
- Focus area restatements ("Review plan focuses on X")
- Baseline context restatements ("Repository baseline context: Y")
- Memory category restatements ("Review memory categories: Z")

### 9. Markdown Structure Is Correct

- The "Security Review" header is always present.
- The "Provider Notes" section is absent when there are no provider notes.
- Sections are clearly separated (findings vs concerns vs observations vs provider notes).
- Recommendations are shown inline per finding (💡 marker), not in a separate section.
- Concern display is capped when multiple concerns target the same paths.
- Provider notes display is capped at 3 notes for conciseness.
- The output is readable and sectioned correctly.

### 10. Deterministic Findings Are Stable

Running the same scenario twice should produce identical findings. Running with disabled vs mock provider should produce the same deterministic findings (deterministic checks are provider-independent).

### 11. Provider Gate Behaves Correctly

- Auth-sensitive, memory-influenced, and high-context PRs should invoke the gate.
- Low-signal PRs (docs, tests, refactoring) should skip the gate.
- The gate should not invoke on context-free PRs even when provider mode is "mock".

### 12. Provider Notes Are Bounded

- No scenario should produce more than 5 provider notes after suppression (capped by the system).
- When the gate skips, zero provider notes should appear.

## What Remains Subjective

Some quality aspects are intentionally **not** encoded as automated checks:

- **Usefulness of individual findings** — whether a specific finding is actually helpful to a developer depends on context that automated checks cannot fully evaluate.
- **Concern relevance** — whether a concern is useful context or unnecessary noise is partially subjective.
- **Observation depth** — whether an observation provides enough detail without being verbose is a judgment call.
- **Provider note quality** — whether a mock provider note is realistic enough to test against is inherently limited by the mock's simplicity.

These may be addressed in future phases through manual review, human evaluation, or more sophisticated automated quality metrics.

## Evaluation Scorecard

The `EvaluationScorecard` (ADR-039) provides aggregate quality rates across the realistic scenario corpus:

| Metric | What it captures |
|---|---|
| Findings stability | Whether deterministic findings are consistent across provider modes |
| Decision stability | Whether pass/warn/block decisions are consistent |
| Provider value | Whether provider reasoning adds meaningful observations or notes |
| Gate accuracy | Whether the provider gate invokes correctly (invoke on signal, skip on noise) |
| Trust boundaries | Whether provider output never pollutes findings or scoring |
| Quietness | Whether low-signal scenarios produce no unnecessary output |
| Noise | Whether any scenario produces duplicate or untethered output |

The scorecard is **a practical tuning aid, not a scientific benchmark**. It captures aggregate percentages across the realistic corpus, not per-scenario grades.

```bash
# Generate the scorecard
python -m reviewer.validation --scorecard
```

## How to Use This Rubric

1. **Before changing the pipeline**: Run `python -m reviewer.validation --summary` to see current behavior across all scenarios.
2. **After changing the pipeline**: Run `python -m pytest tests/test_evaluation.py tests/test_realistic_evaluation.py tests/test_quality_tuning.py -v` to verify quality expectations still hold.
3. **When tuning**: Use `python -m reviewer.validation --compare <scenario>` to see how changes affect disabled vs mock behavior.
4. **When evaluating overall quality**: Run `python -m reviewer.validation --scorecard` to see aggregate quality rates across the realistic corpus.
5. **When testing realistic scenarios**: Run `python -m reviewer.validation --realistic` to exercise file-backed corpus scenarios.
6. **When adding scenarios**: Follow the existing corpus patterns and add appropriate tags, security_focus, and expected behavior assertions.
