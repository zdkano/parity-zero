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

Provider requests now include bounded code evidence from `ReviewBundle` items (ADR-043). This means the provider sees actual changed code for the most security-relevant files, not just file paths and metadata. Observations should be grounded in the code evidence provided.

### 9. Markdown Structure Is Correct

- The "Security Review" header is always present.
- The "Provider Notes" section is absent when there are no provider notes.
- **Provider-first hierarchy (ADR-045):** When structured provider review items are present, the "🤖 Provider Security Review" section is the primary non-authoritative review body. Heuristic concerns and observations sections are **suppressed** — they appear only as a fallback when no provider review exists.
- The output hierarchy is: (1) deterministic findings, (2) provider security review, (3) heuristic concerns/observations (fallback).
- Sections are clearly separated (findings vs provider review vs concerns vs observations vs provider notes).
- Recommendations are shown inline per finding (💡 marker), not in a separate section.
- Concern display is capped when multiple concerns target the same paths.
- Provider notes display is capped at 3 notes for conciseness.
- The output is readable and sectioned correctly.

### 10. Deterministic Findings Are Stable

Running the same scenario twice should produce identical findings. Running with disabled vs mock provider should produce the same deterministic findings (deterministic checks are provider-independent).

### 11. Provider Gate Behaves Correctly

- Auth-sensitive, memory-influenced, and high-context PRs should invoke the gate.
- **API surface expansion PRs** (new routes, endpoints, controllers, CRUD resources) should invoke the gate.
- Low-signal PRs (docs, tests, refactoring) should skip the gate.
- The gate should not invoke on context-free PRs even when provider mode is "mock".

### 12. Provider Notes Are Bounded

- No scenario should produce more than 5 provider notes after suppression (capped by the system).
- When the gate skips, zero provider notes should appear.

### 13. API Surface Expansion Triggers Review

PRs that introduce or modify API surface (new routes, endpoints, controllers, or CRUD resources) should:

- Set the `api_surface_expansion` review flag in the ReviewPlan.
- Add authentication and authorization to the plan's focus areas.
- Generate at least one concern about access control and object-level authorization.
- Generate per-file observations for route/controller/handler files.
- Trigger provider invocation when a provider is available.

This does **not** produce findings or affect scoring. It increases review attention for security-relevant code-shape changes while keeping the trust boundary intact.

Detection uses:
- Path-based signals: files in `routes/`, `controllers/`, `handlers/`, `endpoints/`, `views/`, `api/`, `routers/`, `resources/` directories.
- Content-based signals: route registration decorators, API router instantiation, versioned API paths, CRUD function patterns, auth middleware references, resource controller classes.
- Non-code files (markdown, JSON, YAML, lockfiles, images) are excluded from content scanning.

### 14. Structured Provider Review Output Is Non-Authoritative (ADR-044, ADR-045)

When structured provider review items (`ProviderReviewItem`) are present, they:

- Are validated against a bounded vocabulary of kinds (`candidate_finding`, `candidate_observation`, `review_attention`) and the findings taxonomy categories.
- Have confidence capped at `medium` — provider output never claims `high` confidence.
- Are normalised, deduplicated (by title+paths), and bounded (max 8 per invocation).
- Require code-level evidence (`evidence` field) — items without evidence context are less useful.
- Are tied to specific changed file paths where possible.
- Appear in the markdown summary under "🤖 Provider Security Review" but do **not** create findings, affect scoring, or influence the decision.
- **Are the primary non-authoritative review surface (ADR-045).** Up to 8 items are shown. When present, heuristic concerns and observations sections are suppressed from the markdown output — provider review replaces them as the main review body below findings.

When structured review items are present, legacy provider candidate notes are also **suppressed** in markdown output to avoid redundancy. The legacy "Additional Review Notes" section is replaced by the structured review section.

### 16. Evidence Discipline for Provider Review (ADR-046)

Provider review items are now held to stronger evidence-discipline expectations:

- **Speculative missing-control claims** (e.g. "missing authorization") are suppressed when no code evidence supports the assertion. If evidence is provided, the item is softened to `review_attention` kind with `low` confidence.
- **Filename-only category guesses** (category assigned based only on file path, not code content) are suppressed.
- **Test/fixture noise** — items targeting only test or fixture files are suppressed unless they contain concrete security evidence (e.g. hardcoded production credentials).
- **Non-security commentary** (code quality, documentation, performance) is suppressed.
- **Confidence bounding** — items with no code evidence are capped at `low` confidence regardless of provider assertion.
- **Weak duplicate collapse** — overlapping `review_attention`/low-confidence items on the same category and path are collapsed to the strongest item.
- **Bounded review units** — provider requests now include larger code excerpts (up to 2500 chars per target with natural boundary detection) and related code context (route/controller groupings), providing the provider with more complete review units instead of tiny snippets.
- Provider prompting explicitly requires evidence discipline: no speculative claims about unseen code, prefer "verify" language over "missing" assertions, no commentary on tests/fixtures without concrete security evidence.

### 15. Provider-First Review Model (ADR-045)

The markdown output follows a **provider-first** hierarchy:

1. **Deterministic findings** — authoritative, drive scoring and decision. Always shown.
2. **Deterministic change summary** — short factual "what changed" section (ADR-047). Shown when meaningful changes are detected.
3. **Provider security review** — primary non-authoritative review surface. Shown when structured provider review items exist (up to 8 items).
4. **Heuristic concerns and observations** — fallback non-authoritative sections. Shown **only** when no provider review is present.

This ensures the highest-quality review surface (structured provider reasoning with evidence, kind, category, and confidence) takes precedence over heuristic plan-level and file-level notes. Internal generation of concerns and observations is unchanged — they remain available on `AnalysisResult` and are still generated for traceability and fallback. Only their markdown display is conditional.

### 17. Deterministic Change Summary (ADR-047)

Reviews now include a short factual **"What Changed"** section near the top:

- Generated deterministically from changed file paths, review bundle metadata, and review plan signals.
- Factual, not judgmental — describes what changed (e.g. "route/endpoint changed", "auth file changed"), not what is risky.
- Compact bulleted format. Does not add verbosity.
- Does not appear in `ScanResult` JSON — markdown-only.
- Absent when there are no meaningful changes to summarize.

### 18. Fuller Bounded Changed-File Provider Context (ADR-047)

Provider review prompts now include fuller bounded changed-file context:

- Small relevant files (under 3000 chars) included in full for high-priority review targets.
- File-level context annotations describe file role and focus areas.
- Related code context (route+controller, auth+validation groupings) included for review units.
- Prompt size remains bounded — max 8 targets, max 2500 chars per excerpt.
- Provider output remains non-authoritative regardless of context quality.

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
