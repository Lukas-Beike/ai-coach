# Dependency security policy

Dependabot is the source of truth for dependency update proposals. There are
currently no active exceptions for dependency findings.

If a future security scanner is introduced, an exception must be a separately
reviewed change that records, at minimum:

- the CVE or scanner identifier and affected image digest/package;
- the reason it cannot yet be fixed and the concrete mitigation;
- the responsible owner and an expiry date;
- the replacement or remediation plan.

Expired exceptions must be removed or renewed in another reviewed change.
