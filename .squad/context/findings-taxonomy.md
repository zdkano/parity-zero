# Initial Findings Taxonomy

The reviewer should start with a narrow, defensible set of categories tied to changed code.

## Authentication
- **Definition:** Issues that weaken identity verification or session establishment.
- **Example issue types:** missing auth checks on sensitive entry points, unsafe token handling, bypassable login flows.
- **Severity guidance:** Higher severity when the issue allows unauthenticated access or credential compromise; lower when it weakens hardening but does not bypass auth by itself.
- **Reviewer expectations:** Explain what identity boundary is affected and why the current change weakens it.

## Authorization
- **Definition:** Issues where authenticated actors may access actions or data beyond intended permissions.
- **Example issue types:** missing ownership checks, role bypass, trust in client-supplied access decisions.
- **Severity guidance:** Higher severity when privilege escalation or cross-tenant access is plausible.
- **Reviewer expectations:** Identify the protected resource, the missing control, and the actor who could abuse it.

## Input Validation
- **Definition:** Issues caused by untrusted input reaching sensitive operations without adequate validation or encoding.
- **Example issue types:** injection paths, unsafe deserialization, unbounded file handling, missing server-side validation.
- **Severity guidance:** Higher severity when input can directly reach code execution, database queries, or sensitive storage.
- **Reviewer expectations:** Point to the untrusted input, the sink, and the missing validation or sanitization step.

## Secrets
- **Definition:** Exposure, misuse, or insecure handling of credentials, tokens, keys, or other sensitive material.
- **Example issue types:** committed secrets, logging secrets, long-lived credentials, secret material in insecure config.
- **Severity guidance:** Higher severity for active credentials or broadly reusable secrets.
- **Reviewer expectations:** Be explicit about why the value appears sensitive and avoid speculative secret claims without evidence.

## Insecure Configuration
- **Definition:** Changes that weaken security-relevant runtime, deployment, or service configuration.
- **Example issue types:** disabled TLS verification, overly permissive CORS, debug mode in production paths, unsafe defaults.
- **Severity guidance:** Severity depends on exploitability and environment reach; production-exposed weakening is higher risk.
- **Reviewer expectations:** Explain which control is weakened, where it applies, and the likely impact.

## Dependency Risk
- **Definition:** Security risk introduced by dependency changes, including vulnerable, untrusted, or unsafe dependency usage.
- **Example issue types:** known-vulnerable package version, risky package addition, unsafe post-install behavior, unpinned critical dependency.
- **Severity guidance:** Higher severity when a dependency introduces known exploitable risk or privileged execution paths.
- **Reviewer expectations:** Tie the finding to the changed dependency and explain why it materially increases risk.
