---
name: pacecraft-prod-logs
description: Base skill. Count warning and error log entries by event name from saved container logs or the app's redacted log endpoint, never log text. Use in the post-release check, for the Garmin cleanup count, or after a restart.
---

# Production logs as counts

Prefer the app's own redacted entries with the secret-file login. A container
log saved from the Unraid MCP to the session scratchpad also works, but that
call ignores `level=` and truncates at about 40 KB, so it covers only the
latest window; name that window with the counts.

```powershell
python scripts/prod_logs.py --log-file <scratchpad>/container.log [--since <container start, ISO>]
python scripts/prod_logs.py --url <app address> --password-file <secret file>
```

It prints counts per level and per event name, the number of removed past
app-created Garmin workouts (`garmin_past_workouts_removed`), and the number of
plan-sync error events. Event names that are not plain identifiers are counted
as `unnamed`. Exit 0 no error entry, 1 error entries, 2 unreadable input.

Never copy log lines into output, issues or notes: they can hold payload
fragments. Delete the saved log file when the check ends.
