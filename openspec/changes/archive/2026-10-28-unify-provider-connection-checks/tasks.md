# Tasks

## 1. Backend

- [x] 1.1 Add the check service with identity-bound in-memory results, failure classification and single-flight; verify unit tests cover unconfigured, success, each failure category, credential change, in-flight change, concurrency and redaction.
- [x] 1.2 Add the OpenAI, Intervals.icu, Wahoo and Open-Meteo probes and a token-only Garmin check; verify tests cover each single read, the unsupported endpoint case and that Garmin never uses credentials.
- [x] 1.3 Add the authenticated status route and CSRF-protected check route and wire them; verify route tests cover auth, unknown provider and no passive provider call.

## 2. Frontend and docs

- [x] 2.1 Add the check line and button to the five cards and a shared module with invalidation on credential change; verify JavaScript tests cover all states, pending, failed requests and stale results, and update asset versions and the service worker together.
- [x] 2.2 Document the checks, limits and providers without a check in the README and API routes.

## 3. Validation

- [x] 3.1 Run focused and full Python and JavaScript tests, compileall, ruff and the repository-wide mypy ratchet.
- [x] 3.2 Run the affected Playwright project and validate PWA assets.
- [x] 3.3 Run `npm run openspec -- validate unify-provider-connection-checks --strict --no-interactive`.
