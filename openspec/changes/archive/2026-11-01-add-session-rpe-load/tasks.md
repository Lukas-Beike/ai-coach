# Tasks

## 1. Persistence

- [x] 1.1 Freeze schema v17, add the v17 to v18 step for `activity_feedback.session_rpe_rated_at`, the v18 fixture and export format 10; verify populated upgrade, rollback, restart, restore and the encrypted matrix with `tests/test_db_feedback_rating_time_migration.py`, `tests/test_db_migrations.py` and `tests/test_db_encrypted_upgrade_matrix.py`.
- [x] 1.2 Set, keep and clear the rating time with the session RPE and restore it on undo; verify with the migration and feedback history tests.

## 2. Method and consumers

- [x] 2.1 Implement `backend/performance/session_rpe_load.py` with local-first rating, labelled provider fallback, conflict, duration and coverage rules; verify every M1 acceptance case in `tests/test_session_rpe_load.py`, including edits, undo and two provider copies.
- [x] 2.2 Carry the result in the training report, the public performance history, the activity detail envelope and the planning context; state the Coach rules in the prompt and tool description; verify with the report, detail envelope, performance state and prompt tests.
- [x] 2.3 Replace the RPE input with the CR-10 selection, show the session AU in the activity detail and a separate AU chart in Belastung; bump asset versions and the cache name; verify with `node --test tests/*.cjs` and `e2e/activity-details.spec.js`.

## 3. Documentation and validation

- [x] 3.1 Update the M1 evidence card, `docs/performance-methods/inputs.md`, the #1446 fixture pin and README.
- [x] 3.2 Run the full unit suite, compileall, the quality ratchet, node tests and the affected Playwright specs where available; record unavailable checks as gaps.
- [x] 3.3 Run `npm run openspec -- validate add-session-rpe-load --strict` before archiving.
