---
name: pacecraft-ui-walk
description: Base skill. Headless read-only walk through the running app at phone and desktop width with the secret-file login, screenshots, load times, calendar week/month/paging and the served service-worker cache name. Use in the post-release check or after a restart.
---

# UI walk

Needs the repository's Playwright install (`npm ci` and
`npx playwright install chromium` once). The app address and the secret file
come from the session at run time. The secret file must lie in the T3 secret
folder (`~/.t3/userdata/secrets`) or the system temp directory, and is only
read; the output directory and the previous walk must lie in the system temp
directory (the session scratchpad). The script refuses any other path.

```powershell
node scripts/ui_walk.mjs --url <app address> --password-file <secret file> --out-dir <scratchpad>/walk [--compare <previous walk>/ui-walk.json]
```

At 412 px and 1280 px it logs in through the login dialog with the password
read from the file, opens Coach, Kalender, Analyse, Ernährung and Mehr, opens
one calendar unit (the detail pane at desktop width), switches to the month and
pages it, pages the week, and logs out with the CSRF token. One line per view
with its time until ready and error count (console errors, page errors,
5xx responses), the calendar steps done, and the service-worker cache name and
asset-version count. A view is ready once its active panel shows no visible
loading marker and no request it started has been open for 300 ms (the state
event stream excepted); after 15 s an `info <view> not ready` line names the
method and path of that view's requests still open. `ui-walk.json` keeps the
numbers and the measuring method for `--compare`, which skips load times of a
walk measured another way; keep the load times in the session notes, not in
the repository.

Look at every screenshot yourself; a view can render an error state without a
console error. Screenshots stay in the scratchpad and are never committed.

It presses no control that saves, synchronizes, deletes or sends. Exit 0 no
error, 1 a view logged errors or logout failed, 2 bad input or the walk
stopped.
