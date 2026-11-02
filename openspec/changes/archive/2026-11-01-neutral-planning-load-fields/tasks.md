# Tasks

## 1. Planning fields

- [x] 1.1 Map provider load and intensity to neutral local names, update planning consumers and verify provider import/export and local API tests.
- [x] 1.2 Normalize frozen target FTP and verify target snapshot and analysis tests.
- [x] 1.3 Preserve sync and audit hashes and verify pre-upgrade history and undo cases.

## 2. Schema and restore

- [x] 2.1 Freeze v18, add the transactional v19 rewrite, and verify populated v16, v17 and v18 upgrades, failure rollback and restart.
- [x] 2.2 Retire pre-v16 upgrade paths, document the minimum version, and verify old databases and backups are rejected unchanged.
- [x] 2.3 Run encrypted SQLCipher upgrade and restore tests where available and record unavailable evidence.

## 3. Integration

- [x] 3.1 Review all acceptance criteria against source and test evidence, run applicable repository checks, and record any environment gaps.
- [x] 3.2 Validate this change and the current specifications strictly using the OpenSpec CLI.

## Workflow follow-up

- Archive the completed change and validate the resulting specifications before committing.

## Evidence

- Native Python suite: four complete shards passed (7,856 tests, 41 skips); changed focused tests were rerun after fixture and formatting adjustments.
- SQLCipher suite: 7,858 tests, 14 skips, zero failures, with partition coverage verified. Populated v16–v18 upgrades, rollback, restart, encrypted restore and batched metric rewrites passed.
- JavaScript unit tests: 306 passed. Mobile planning and calendar checks, mobile and desktop login/composer/contract checks, and text reflow in all five projects passed with disposable fixtures.
- Ruff/mypy quality ratchet: no new findings. Change and current specifications passed strict OpenSpec validation.

## Evidence gaps

- No live provider account was used; remote compatibility is established with mocked provider fixtures. Notification permission behavior was not exercised manually in a browser.
