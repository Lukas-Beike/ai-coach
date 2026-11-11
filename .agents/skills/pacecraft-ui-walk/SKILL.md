---
name: pacecraft-ui-walk
description: Base skill. Headless read-only walk through the running app at phone and desktop width with the secret-file login, screenshots, load times, calendar week/month/paging and the served service-worker cache name. Use in the post-release check or after a restart.
---

# UI walk

Needs the repository's Playwright install (`npm ci` and
`npx playwright install chromium` once). The app address and the secret file
come from the session at run time; the output directory lies outside the
repository (the session scratchpad).

```powershell
node scripts/ui_walk.mjs --url <app address> --password-file <secret file> --out-dir <scratchpad>/walk [--compare <previous walk>/ui-walk.json]
```

At 412 px and 1280 px it logs in through the login dialog with the password
read from the file, opens Coach, Kalender, Analyse, Ernährung and Mehr, opens
one calendar unit (the detail pane at desktop width), switches to the month and
pages it, pages the week, and logs out with the CSRF token. One line per view
with its time to rendered content and error count (console errors, page errors,
5xx responses), the calendar steps done, and the service-worker cache name and
asset-version count. `ui-walk.json` keeps the numbers for `--compare`; keep the
load times in the session notes, not in the repository.

Look at every screenshot yourself; a view can render an error state without a
console error. Screenshots stay in the scratchpad and are never committed.

It presses no control that saves, synchronizes, deletes or sends. Exit 0 no
error, 1 a view logged errors or logout failed, 2 bad input or the walk
stopped.
