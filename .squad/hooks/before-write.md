# Before Write Checklist

Before generating code, changing schemas, or updating product logic, stop and check the following.

---

## Scope and phase

1. Is this change aligned to the current phase?
2. Does this help the reviewer wedge directly, or is it dashboard-first drift?
3. Am I introducing platform breadth before the core reviewer is trusted?

If the change mainly improves reporting while the reviewer remains weak, stop and re-scope.

---

## Product intent

4. Does this preserve the GitHub-native developer workflow?
5. Does this make the reviewer more useful, more explainable, or more reliable?
6. Am I solving a real control problem, or just adding another layer of abstraction?

If the change makes the system feel more generic and less workflow-native, challenge it.

---

## Findings quality

7. Will this change improve findings quality, not just quantity?
8. Could this create noisy, repetitive, or vague findings?
9. Am I making claims the system cannot support with confidence?

Do not generate findings that sound authoritative but are weakly grounded.

---

## Rules and reasoning balance

10. Is this using deterministic checks where precision matters?
11. Is the LLM being used for reasoning and explanation, not treated as a magic detector?
12. Am I blurring the boundary between high-confidence checks and contextual interpretation?

If yes, document the tradeoff and seek review.

---

## JSON findings contract

13. Does this preserve the structured JSON output contract?
14. If the contract changes, has backward compatibility been considered?
15. Have schema changes been routed for Tester review?
16. Have schema and contract changes been recorded for the Scribe?

The JSON contract is a core system interface.
Do not change it casually.

---

## Engineering discipline

17. Is this the simplest maintainable implementation that works?
18. Am I introducing premature abstractions, frameworks, or layers?
19. Can this be tested cleanly?
20. Does this create hidden coupling between reviewer and control plane?

Prefer boring, clear implementations over clever ones.

---

## Documentation and memory

21. Does this change require an update to `decisions.md`?
22. Does this invalidate or change anything in:
    - `context/product.md`
    - `context/architecture.md`
    - `context/findings-taxonomy.md`
    - `context/roadmap.md`
23. Is there a tradeoff, assumption, or deferred concern that future agents need to know?

If yes, involve the Scribe.

---

## Final challenge

24. If this change landed today, would a future contributor understand:
    - why it exists
    - what problem it solves
    - what contract it affects
    - what tradeoff was accepted

If not, the work is not ready to write.