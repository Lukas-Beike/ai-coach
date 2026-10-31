## 1. Canonical summary

- [x] 1.1 Activity records carry the summary values in their details; Intervals.icu mapper v6 and Garmin mapper v7 fill them (`tests/test_intervals_activity_mapping.py:SummaryValueTests`, `tests/test_garmin_activity_mapping.py:SummaryValueTests`).
- [x] 1.2 One neutral summary per live session from all providers, with per-value sources, TSS-like load only and the stored-key rule (`tests/test_activity_summary.py`).
- [x] 1.3 The table reader groups records by effective session and the read selector serves summaries; the first backfill links provider copies (`tests/test_canonical_table_reader.py:ActivitySessionReadTests`, `tests/test_canonical_backfill.py`).

## 2. Consumers

- [x] 2.1 Performance inputs, load rollups, eFTP, activity validation, training focus zones, charts and body history read summaries.
- [x] 2.2 Training report, records, tag impact, power profile and season preparation read summaries with canonical sports; raw duplicate matching moves to sync.
- [x] 2.3 Calendar, matching, frozen detail targets, plan/bootstrap state, diagnostics and the Coach context read summaries (`tests/test_coach_activity_summary_parity.py`, `tests/test_target_snapshot_summaries.py`).
- [x] 2.4 Session analysis uses canonical sports; the raw detail projection lives in the Intervals.icu adapter.
- [x] 2.5 PWA label maps cover canonical sports; asset versions and the service-worker cache are bumped.

## 3. Guard and validation

- [x] 3.1 The provider-coupling guard has no activity-rows allowlist entries left (`tests/test_provider_coupling_guard.py`).
- [x] 3.2 Run the full unit suite, compileall, ruff, repo-wide mypy, `node --test tests/*.cjs` and the affected Playwright projects where available; record unavailable checks as gaps.
- [x] 3.3 Scoped evidence review and `npm run openspec -- validate neutral-activity-summary --strict`.
