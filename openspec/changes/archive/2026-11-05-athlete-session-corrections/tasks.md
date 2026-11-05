# Tasks

## 1. Corrections

- [x] 1.1 Implement confirm, split and merge with change-history receipts and undo; verify with `tests/test_session_corrections.py`.
- [x] 1.2 Show the bundle with its actions and undo in the activity detail view; update PWA asset versions.
- [x] 1.3 Add local Coach tools for the same corrections; verify the Coach tool tests.

## 2. Integration

- [x] 2.1 Run the selected checks and strict OpenSpec validation, recording unavailable checks as evidence gaps.

## Evidence gaps

- The Windows Python suite skipped 37 tests, including SQLCipher-dependent cases. Playwright ran `e2e/activity-details.spec.js` locally on the desktop and mobile-small projects only; CI runs the other projects.
