---
name: pacecraft-prod-diagnostics
description: Base skill. Read named health and diagnostics fields and record counts from the running app, read-only, optionally compared with a previous result. Use in the post-release check or after a restart; never to change production.
---

# Production diagnostics

The app address and the secret file come from the session at run time (the
athlete's private notes and a secret delivered with file delivery); never write
either into the repository, a tracked file, or output. Result files go to the
session scratchpad or another place outside the repository.

```powershell
python scripts/prod_diagnostics.py --url <app address> --password-file <secret file> --expect-version <tag> --expect-schema <current schema> --out <scratchpad>/diagnostics.json [--compare <previous result>]
```

It checks health, logs in with the password read from the file, reads
`/api/diagnostics`, and logs out with the CSRF token. One line per check:
version and schema against the expected values, whether `sync.last_error` is
set (never its text), provider and calendar refresh ages, stuck plan-sync
jobs, unsynced plan units with error kinds (never error text), record counts,
and process memory. With `--compare`, a lower record count is a `FAIL`: an
unexplained drop stops the check.

Exit 0 all ok, 1 a check failed, 2 unreachable or login refused. The script
prints no response body, cookie, or password; do not add a mode that does.
