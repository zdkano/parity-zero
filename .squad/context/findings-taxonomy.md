
# parity-zero Findings Taxonomy

## Purpose

This file defines the initial findings categories for parity-zero.

The taxonomy exists to keep reviewer behaviour consistent, keep findings explainable, and support structured aggregation later.

This is the initial MVP taxonomy only.
It should stay narrow and useful.

---

## Category: Authentication

### Definition
Issues where the code fails to properly establish or verify identity before protected actions occur.

### Example issue types
- missing authentication checks on protected routes
- routes intended to be protected but exposed without auth middleware
- insecure assumptions about authenticated user identity
- token handling logic that appears obviously unsafe

### Severity guidance
- **High** when protected actions appear reachable without authentication
- **Medium** when authentication handling is weak or incomplete but impact is less direct
- **Low** only when the issue is minor and unlikely to expose meaningful risk

### Reviewer expectations
Findings in this category should be specific about:
- what action appears exposed
- what authentication control appears absent or weak
- why the changed code increases risk

Do not confuse authentication with authorization.

---

## Category: Authorization

### Definition
Issues where identity may be established, but the code fails to enforce whether the actor is allowed to perform the requested action.

### Example issue types
- missing ownership checks
- missing role or permission checks
- update/delete operations that do not constrain access to permitted resources
- business logic paths where authenticated users may access other users' data or actions

### Severity guidance
- **High** when changed logic may enable cross-user or privilege escalation behaviour
- **Medium** when authorization appears incomplete or weak but impact is narrower
- **Low** only when the issue is limited and low impact

### Reviewer expectations
This is likely to be one of the most valuable and most context-sensitive categories.
Findings should be careful, concrete, and avoid pretending certainty when context is limited.

---

## Category: Input Validation

### Definition
Issues where changed code accepts or processes input in ways that may enable abuse, unsafe execution, or broken assumptions.

### Example issue types
- missing validation on request parameters
- unsafe deserialisation or parsing paths
- untrusted input flowing into sensitive operations without checks
- unsafe command, query, or template composition patterns
- weak file upload or path handling

### Severity guidance
- **High** when the pattern may directly enable code execution, injection, or major data access issues
- **Medium** when validation is weak and the path is security-relevant
- **Low** when the issue is real but lower impact or less directly exploitable

### Reviewer expectations
Findings should be tied to the sensitive sink or operation, not just “validation seems weak.”

---

## Category: Secrets

### Definition
Issues involving exposure, unsafe handling, or poor control of secrets and sensitive data.

### Example issue types
- hardcoded credentials
- committed tokens or keys
- unsafe secret logging
- sensitive values passed or stored in clearly unsafe ways
- insecure handling of configuration secrets

### Severity guidance
- **High** when credentials or sensitive secrets are directly exposed
- **Medium** when handling is unsafe but full exposure is less clear
- **Low** when the issue is minor but still worth correcting

### Reviewer expectations
Prefer high-confidence findings here.
Do not overflag generic configuration unless the risk is clear.

---

## Category: Insecure Configuration

### Definition
Issues where changed code or configuration introduces unsafe defaults, weak protections, or exposed capabilities.

### Example issue types
- permissive CORS settings in sensitive contexts
- disabled security checks
- unsafe debug or development settings in production-bound code
- public exposure of internal interfaces
- weak default access controls in config

### Severity guidance
- **High** when the changed configuration materially expands attack surface or weakens protection
- **Medium** when the config is concerning but context is partially missing
- **Low** for weaker hygiene issues with limited direct impact

### Reviewer expectations
The reviewer should identify why the configuration is risky, not just that it is “not best practice.”

---

## Category: Dependency Risk

### Definition
Issues where changed code introduces or depends on packages, components, or reachable paths that materially increase security risk.

### Example issue types
- introducing packages with known severe risk indicators
- using vulnerable functionality in a reachable path
- enabling dangerous dependency behaviour in changed code
- increasing dependency exposure in sensitive components

### Severity guidance
- **High** when changed code creates clear reachable risk or adds high-risk dependency usage to sensitive paths
- **Medium** when dependency-related exposure is meaningful but less direct
- **Low** when the issue is useful context but not a major blocker

### Reviewer expectations
Do not try to replace a full dependency scanner.
Focus on code-change relevance and practical review value.

---

## Taxonomy rules

### Keep categories distinct
Do not collapse authentication and authorization into one bucket.

### Prefer narrow interpretation
If a finding cannot clearly be placed, it may not yet be ready.

### Avoid category sprawl in MVP
New categories should be added only when there is a strong practical need.

### Severity and confidence are separate
A finding can be high severity but medium confidence.
Do not conflate impact with certainty.