---
name: ai-coach-pwa-e2e
description: Validate browser and PWA behavior with the isolated SQLCipher fixture runtime and Playwright projects.
---

Use for frontend, HTTP contracts, streaming, responsive layout, or PWA changes.

- Read scoped instructions and follow [browser-validation.md](references/browser-validation.md); never use the real environment, data mount, or browser profile.
- Run affected projects first, then the full matrix for shared contracts, authentication, cache, or chat lifecycle changes.
- Check login, Enter versus Shift+Enter, voice transcript editing, streaming/cancel/error/reload, accessibility, reduced motion, and the affected journey.
- Match asset query versions, service-worker cache/assets, and frontend regression assertions; verify fresh installation and offline assets.
- Keep screenshots, traces, and videos fixture-only; never expose authenticated storage state.
- Report passed, failed, blocked, and not run separately. Missing Docker, SQLCipher, browser, or provider access is not success.
