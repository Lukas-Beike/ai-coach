# Security scan exceptions

There are currently no active exceptions for image or dependency findings.

An exception is not configured through a scanner ignore file. A proposed
exception must be a separately reviewed change that records, at minimum:

- the CVE or scanner identifier and affected image digest/package;
- the reason it cannot yet be fixed and the concrete mitigation;
- the responsible owner and an expiry date;
- the replacement or remediation plan.

The CI vulnerability scan remains blocking until the exception is explicitly
accepted in review. Expired exceptions must be removed or renewed in another
reviewed change.
