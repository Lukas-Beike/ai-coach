---
name: pacecraft-prod-guards
description: Base skill. Confirm production still refuses an API request without a session (401) and a state-changing request without the CSRF token (403), and report the TLS certificate's days to expiry. Read-only probes; use in the post-release check.
---

# Production guards

```powershell
python scripts/prod_guards.py --url <app address> --password-file <secret file> [--min-tls-days 14]
```

The probes have no effect even if accepted: a diagnostics read without a
session, and a logout of the probe's own session without the CSRF token. The
script then logs out properly and, for an https address, reads the
certificate's expiry. Exit 0 every guard holds, 1 a guard failed or the
certificate expires within the limit, 2 unreachable.

A failed guard is a security finding: stop the post-release check and report
it at once. Never weaken a guard to make this pass.
