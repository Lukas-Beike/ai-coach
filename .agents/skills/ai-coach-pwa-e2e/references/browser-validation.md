# Disposable browser validation

Run from the repository root. Never use
`--env-file .env`, an existing data directory, or a connected application.

Use the shared runner commands in
[README testing](../../../../README.md#playwright-browser-e2e-tests) as the
maintained setup and operational runbook. Build current source, prepare the
locked native browser once, and use explicit `--project`/`--spec` selections or
`--project all` for the complete five-project set. `--list` starts no fixtures.
The runner preserves fresh SQLCipher state per spec, bounded readiness, stable
prewarm-slot networking, one Playwright worker, unique resources/private auth,
and incremental manifests. Default to one process; trial `--jobs 2` explicitly.
Keep the final manifest and distinguish listed, passed, failed and interrupted
results. Prepared-image execution is Linux-only; Windows uses native Chromium.

Use the product-native preview for manual inspection when available. Inspect
DOM, console/network failures, screenshot-level alignment, reduced motion,
login, fresh PWA/offline assets, safe Markdown, keyboard behavior, opt-in
microphone/notifications, and the affected flow. Fixtures do not prove live
provider behavior or permissions on a real mobile device. Reproduce failed
and stale-data states by routing `/api/**` to an error response in
Playwright. Shrinking the viewport does not trigger the chat keyboard
detection, which follows `visualViewport`; verify keyboard-open on a device.
Confirm automated touch-target and label flags in the rendered state:
controls inside closed `<details>` and `::before` hit areas are false positives.

For manual fixtures, in `finally`, stop/remove only the observed disposable
container, never with
`docker rm -v`. Restore previous E2E environment values. Keep artifact and
authentication-state cleanup inside verified generated directories.

Never attach Playwright authenticated storage state to a report. Preserve only
sanitized fixture screenshots or video; traces embed the session and stay local.
CI artifacts exclude traces (`trace` is off when `CI` is set) and never include
`playwright/.auth`. A failed or unavailable runtime
check must remain failed, blocked, or not run, not silently replaced by static
source inspection.
