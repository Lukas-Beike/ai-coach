---
name: pacecraft-pwa-e2e
description: Validate browser and PWA behavior with the isolated SQLCipher fixture runtime and Playwright projects, and host fixture screenshots for UI PRs.
---

Use for frontend, HTTP contracts, streaming, responsive layout, or PWA changes.

- Read scoped instructions and follow [browser-validation.md](references/browser-validation.md); never use the real environment, data mount, or browser profile.
- Run affected projects first, then the full matrix for shared contracts, authentication, cache, or chat lifecycle changes.
- Check login, Enter versus Shift+Enter, voice transcript editing, streaming/cancel/error/reload, accessibility, reduced motion, and the affected journey.
- Check the stamped asset versions and service-worker cache/assets served by the image (rebuild `$(python scripts/run_browser_tests.py --print-image)`); verify fresh installation and offline assets.
- Keep screenshots, traces, and videos fixture-only; never expose authenticated storage state.
- UI PR screenshots come from the browser fixture. Commit them in a temporary
  worktree on an orphan `assets/pr-<n>-<topic>` branch and push that branch from
  the task worktree (`git push origin assets/pr-<n>-<topic>`): the hooks need its
  scripts and must run, never bypassed. The PR shows each image through its
  `blob/assets/pr-<n>-<topic>/<file>?raw=true` URL. Never merge an assets branch;
  deleting it later is optional.
- Report passed, failed, blocked, and not run separately. Missing Docker, SQLCipher, browser, or provider access is not success.
