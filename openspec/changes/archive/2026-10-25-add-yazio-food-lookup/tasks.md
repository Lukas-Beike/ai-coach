# Tasks

## 1. Schema v14

- [x] 1.1 Freeze the v13 shape in schema history, bump `CURRENT_SCHEMA_VERSION` to 14, allow `yazio:*` mirror ids and the `yazio` product source in the live DDL, and add the transactional table-rebuild upgrade; verify `tests/test_db_migrations.py` populated v9 to v13 upgrades keep every row, an injected failure rolls back, and a same-build restart reopens.
- [x] 1.2 Cover backup/restore validation and an existing-record edit after upgrade; verify the restore and export tests pass and the encrypted Docker migration run succeeds.

## 2. Configuration and credentials

- [x] 2.1 Add `YAZIO_*` config fields and `yazio_*` credential fields (masked/secret), `yazio_configured` status, and redaction keys; verify `tests/test_provider_credentials.py` covers precedence, clearing, incomplete configuration and absence of values in status.
- [x] 2.2 Add the credential inputs to the Anbindungen form, bump `public/index.html` query versions and the service-worker cache together; verify the Node tests.

## 3. Yazio client and lookup chain

- [x] 3.1 Implement `backend/providers/yazio.py` (auth, refresh, search, detail, normalization, limits, backoff, sanitized errors); verify mocked-HTTP tests for token refresh, rejected login backoff, 429, version block, oversize, malformed shape, plausibility guard and no secret in errors.
- [x] 3.2 Extend the mirror, repository and `FoodDatabaseService` with the Yazio source, prefix-filtered mirror reads, `yazio:` resolve, barcode path and the local-Yazio-OFF-BLS chain; verify tests for local short-circuit, Yazio hit, empty/failing fallthrough, unconfigured default unchanged, mirror reuse and stale fallback.
- [x] 3.3 Allow `yazio` in the Coach lookup source, tool schema text and product/component source validation, and map it in `public/nutrition.js`; verify explicit-source, batch and meal-component tests and the nutrition Node test.

## 4. Documentation and integration

- [x] 4.1 Document setup, lookup priority, privacy and the unofficial-API limits in README; verify consistency with the lookup behavior.
- [x] 4.2 Run full validation: unit suite, compileall, repo-wide mypy ratchet and the Docker build (browser e2e runs in CI).

## Workflow follow-up

- Review the final range, sync specs and archive the change, then publish the PR.
