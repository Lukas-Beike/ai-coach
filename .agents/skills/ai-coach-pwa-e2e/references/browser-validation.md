# Disposable browser validation

Run from the repository root. Follow the current isolated runtime commands in
`.github/workflows/publish-container.yml`, especially the `e2e` job. Never use
`--env-file .env`, an existing data directory, or a connected application.

1. Build `ai-coach:e2e` from the current source. Choose a unique disposable
   container name and an unused loopback port; do not stop an existing app.
2. Run `python /app/e2e/fixture_runtime.py` with the read-only `e2e/` mount,
   writable ephemeral `/data` and `/tmp`, and the image user's UID/GID as in CI.
   Use the fake fixture password, not a production password. Preserve non-root,
   read-only-rootfs, dropped capabilities, and no-new-privileges settings.
3. Wait for `/api/health` with a bounded timeout. Set `E2E_BASE_URL` to the
   observed loopback endpoint and `E2E_APP_PASSWORD` to the fixture password.
4. Install the locked Node dependencies with `npm ci` and Chromium with
   `npx playwright install chromium` when needed. Run
   `npm run test:e2e -- --project=mobile-small` or the affected project.
5. The configured projects are `mobile-small`, `mobile`, `tablet`,
   `tablet-landscape`, and `desktop`. Run `npm run test:e2e` for a normal full
   matrix, or run the CI-equivalent isolated loop when a spec mutates state:
   execute every `e2e/*.spec.js` on desktop and only files containing
   `@responsive` on the other projects, recreating the disposable fixture runtime
   before every pair. The non-desktop projects select only `@responsive` tests.
   Keep the configured single worker within each run; the CI loop provides
   isolation across runs, not parallel safety.
6. Use the product-native preview for manual inspection when available. Inspect
   DOM, console/network failures, screenshot-level alignment, reduced motion,
   login, fresh PWA/offline assets, safe Markdown, keyboard behavior, opt-in
   microphone/notifications, and the affected flow. Fixtures do not prove live
   provider behavior or permissions on a real mobile device.
7. In `finally`, stop/remove only the observed disposable container, never with
   `docker rm -v`. Restore previous E2E environment values. Keep artifact and
   authentication-state cleanup inside verified generated directories.

Never attach Playwright authenticated storage state to a report. Preserve only
sanitized fixture screenshots, traces, or video. A failed or unavailable runtime
check must remain failed, blocked, or not run, not silently replaced by static
source inspection.
