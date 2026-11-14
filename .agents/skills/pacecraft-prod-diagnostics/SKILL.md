---
name: pacecraft-prod-diagnostics
description: Base skill. Read named health and diagnostics fields and record counts from the running app, read-only, optionally compared with a previous result. Use in the post-release check or after a restart; never to change production.
---

# Production diagnostics

The app address and the secret file come from the session at run time (the
athlete's private notes and a secret delivered with file delivery); never write
either into the repository, a tracked file, or output. The secret file must
lie in the T3 secret folder (`~/.t3/userdata/secrets`) or the system temp
directory, and is only read; result files must lie in the system temp
directory (the session scratchpad). The scripts refuse any other path.

```powershell
python scripts/prod_diagnostics.py --url <app address> --password-file <secret file> --expect-version <tag> --expect-schema <current schema> --out <scratchpad>/diagnostics.json [--compare <previous result>]
```

It checks health, logs in with the password read from the file, reads
`/api/diagnostics`, and logs out with the CSRF token. One line per check:
version and schema against the expected values, whether `sync.last_error` is
set (never its text), provider and calendar refresh ages, stuck plan-sync
jobs, unsynced plan units with error kinds (never error text), record counts,
and process memory. With `--compare`, a lower record count is a `FAIL`: an
unexplained drop stops the check. `external_calendar_events` is only `info`:
the calendar sync refills it from today on every refresh.

Exit 0 all ok, 1 a check failed, 2 unreachable or login refused. The script
prints no response body, cookie, or password; do not add a mode that does.

## Sections

```powershell
python scripts/prod_diagnostics.py --url <app address> --password-file <secret file> --section <name> [--section <name> ...]
```

Prints, instead of the checks, only the fields of those sections that
`SECTION_FIELDS` in the script allows: numbers and flags by dotted path, state
words from `STATES`, and a `*_at` time as its age `*_hours`, sorted by path. A
state word in `FAIL_STATES` (`failed`, `unavailable`, `blocked`) and a missing
section print as `FAIL`; an empty section is `info`. Free text, ids and any
field not on the allow-list are never printed. Sections with an allow-list:
`decoupling_eligibility` (temporary, #2779), `database`, `runtime`,
`recovery_copies`, `garmin_past_workout_removal`, `stream_backfill` and
`fit_inventory`. A section without an allow-list entry is
refused; add the entry and its test in `tests/test_prod_checks.py` together
with the section.

## Temporary production probe

When a verification would need the production database or the athlete, add a
probe instead (#2779):

1. Add a counts-only diagnostics section that computes the numbers in the
   background, one session per read snapshot with a pause after each (duty
   cycle, #2761), `pending` until the first result; a test pins that it holds
   no ids, names, dates or single values. Open its removal issue at the same time.
2. Add the section's allow-list to `SECTION_FIELDS` with its test.
3. After the release, read it with `--section <name>`; while it is `pending`,
   read again later.
4. Present the counts, then remove the section and its allow-list through the
   removal issue.
