# Before-Write Checklist

Before generating code, schema, or workflow changes, answer these questions:

1. **Is this change actually needed for the current phase?**
   - If it does not help the reviewer wedge or its ingestion-ready contract, defer it.

2. **Am I adding abstraction earlier than needed?**
   - Avoid framework layers, plugin systems, or dashboard scaffolding without an immediate reviewer need.

3. **Is the design drifting toward dashboard-first thinking?**
   - The dashboard is a second surface. Do not let reporting concerns reshape the primary reviewer workflow too early.

4. **Will this produce concrete findings instead of vague warnings?**
   - Findings should point to changed code, explain the security issue, and justify severity or risk.

5. **Does this preserve the JSON findings contract?**
   - Do not break required fields, schemas, or ingestion expectations without explicit contract updates.

6. **Are deterministic checks and reasoning both being used appropriately?**
   - Prefer rules to narrow the search space and reasoning to explain material risk.

7. **Will this increase reviewer noise?**
   - If likely false positives rise, tighten the logic before writing code.

8. **Am I changing policy, scoring, taxonomy, or architecture?**
   - If yes, route for Security Lead review first.

9. **Am I changing outputs, schemas, comment formats, or metrics?**
   - If yes, require Tester review before completion.

10. **Do repo docs or decisions need updates?**
    - Update `.squad/decisions.md` and relevant context files when scope, contracts, or assumptions change.
