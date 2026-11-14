---
name: pacecraft-pwa-e2e
description: Validate browser and PWA behavior with the isolated SQLCipher fixture runtime and Playwright projects, and host fixture screenshots for UI PRs. Use for frontend, HTTP contract, streaming, responsive layout, or PWA changes.
---

- Read scoped instructions and follow [browser-validation.md](references/browser-validation.md); never use the real environment, data mount, or browser profile.
- Run affected projects first, then the full matrix for shared contracts, authentication, cache, or chat lifecycle changes.
- Check login, Enter versus Shift+Enter, voice transcript editing, streaming/cancel/error/reload, accessibility, reduced motion, and the affected journey.
- Check the stamped asset versions and service-worker cache/assets served by the image (rebuild `$(python scripts/run_browser_tests.py --print-image)`); verify fresh installation and offline assets.
- Keep screenshots, traces, and videos fixture-only; never expose authenticated storage state.
- UI PR screenshots go to a public repository: they come from the browser
  fixture, and you look at each image for fixture-only content before committing.
  After the PR exists, commit them in a temporary worktree outside the checkout on
  an orphan `assets/pr-<n>-<topic>` branch, remove that worktree, and push the
  branch from the task worktree (`git push origin assets/pr-<n>-<topic>`): the hooks
  need its scripts and must run, never bypassed. The PR body shows each image
  through its `blob/assets/pr-<n>-<topic>/<file>?raw=true` URL. Never merge an
  assets branch; deleting it later is optional, but delete it at once if an image
  shows anything but fixture data.
- Run a deliberate mutation check (a source change made to prove a test fails)
  only in a separate temporary worktree, built under that worktree's own
  `--print-image` tag, and remove it afterwards: a concurrent build of the task
  worktree or a shared tag would pick up the mutated file (#2628).
- Report passed, failed, blocked, and not run separately. Missing Docker, SQLCipher, browser, or provider access is not success.
