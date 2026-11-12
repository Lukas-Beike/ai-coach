---
name: pacecraft-post-release-check
description: Check production after every deployment, or on request after a restart - version, schema, record counts, guards, logs, server health, backup age and a UI walk - by sequencing the prod base skills; read-only apart from a few immediately undone local actions. Do not use to deploy, repair or change production.
---

# Post-release check

Run after every deployment (step 5 of
[release-unraid](../pacecraft-release-unraid/SKILL.md)) and on request after a
restart. Report one short line per step: `ok` or the finding.

**Inputs at run time only:** the app address (the athlete's private notes) and
the app password as a secret file delivered to the session (`request_secret`
with file delivery). Never write either into the repository, a tracked file,
a command line, a tool argument, or output. The secret file, result files,
saved logs and screenshots stay in the session scratchpad (the system temp
directory; the scripts refuse other paths) and are never committed. The
previous release's results come from the session notes.

**Stop rule:** on an unexpected effect (a dropped record count, a failed
guard, an undo that does not fully restore, any remote write, an error state),
stop, report it, and do not try to repair production.

## Steps

1. **Container:** healthy and running the verified release digest:
   [image-verify](../pacecraft-image-verify/SKILL.md) with `--running` (after a
   restart without a release, the running digest equals the current tag).
2. **Diagnostics and no data lost:** [prod-diagnostics](../pacecraft-prod-diagnostics/SKILL.md)
   with `--expect-version <tag> --expect-schema <current schema> --compare <previous result>`.
   Any unexplained drop in a record count stops the check. Judge the plan-sync
   error kinds against the previous result: whether they persist after the
   athlete's week sync; never press a sync control to find out.
3. **Protection:** [prod-guards](../pacecraft-prod-guards/SKILL.md): 401 without
   a session, 403 without the CSRF token, TLS days to expiry. A failed guard
   stops the check.
4. **Logs:** save the `pacecraft` container logs since its start from the
   Unraid MCP to the scratchpad and run [prod-logs](../pacecraft-prod-logs/SKILL.md)
   with `--since <container start>`: counts and event names only, the number of
   removed past app-created Garmin workouts after the first Garmin refresh since
   the deploy, and plan-sync error events. Delete the saved log afterwards.
5. **Server health (Unraid MCP, read-only):** container memory, appdata disk use
   and database file size, compared with the previous release; the automatic
   database recovery copy exists and is recent - report only its age and size,
   never open or copy it.
6. **UI walk:** [ui-walk](../pacecraft-ui-walk/SKILL.md) with `--compare
   <previous walk>`. Look at every screenshot: Coach, Kalender (week, month,
   paging, detail pane at desktop width), Analyse, Ernährung, Mehr. After a
   deploy the service-worker cache name must differ from the previous walk
   (new asset versions served). Keep the load times per view in the session
   notes for the next comparison.

## Allowed actions

Only after steps 1-6 passed, and only through a local headless Playwright
script in the scratchpad that logs in from the secret file the way `ui-walk`
does (the password never passes through a tool argument or the agent's
context). Each effect must stay local and be undone at once:

- operate views: switch week and month, page weeks, open units and analyses;
- plan one local test unit about three weeks ahead, check it in the calendar,
  then undo it at once;
- ask the Coach one question without a change (for example what is planned
  tomorrow); it stays in the conversation history and uses a little model usage;
- let the Coach move one future local unit, then undo the whole turn; check
  the receipt and the undo.

**Never:** any control that synchronizes or sends to Garmin, Intervals.icu or
Wahoo (including "Woche synchronisieren"), deletes, data export, privacy
actions, settings, check-in or nutrition entries. Never call the athlete's
Garmin, Wahoo, Intervals.icu or OpenAI accounts directly, and never read
`.env`, tokens, database keys, `/data`, or backup contents.
