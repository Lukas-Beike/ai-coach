# Tasks

## 1. Garmin request paths

- [x] 1.1 In `backend/providers/garmin.py:_collect_historic_metrics`, call `get_endurance_score(start, end, aggregation="daily")` and record `"daily"` as its pagination aggregation; update `tests/test_provider_garmin_metric_history.py:test_known_sdk_methods_get_bounded_dates_and_explicit_aggregation` (fake client accepts `aggregation`, expected call and metadata are `daily`) and verify it passes.
- [x] 1.2 In `targeted_analysis_sources()`, give `endurance_score` an explicit daily-aggregation call shape like `running_tolerance`; add or extend a focused test asserting the targeted call passes `aggregation="daily"` and verify it passes.

## 2. History projection metadata

- [x] 2.1 Change the endurance-score aggregation label to `"daily"` in `backend/performance/chart_history.py:_provider_metrics` and `backend/performance/history.py:_provider_metrics`; verify with a test that a daily `groupMap` (e.g. 2026-10-19 … 2026-10-23) projects dated points whose last `observed_at` is 2026-10-23 and aggregation is `daily`.
- [x] 2.2 Verify the existing weekly-payload test `tests/test_performance_chart_history.py:test_saved_endurance_group_map_repairs_previously_empty_projection` and the DTO unwrap test still pass unchanged (stored weekly data stays readable).

## 3. Running tolerance (retro R1)

- [x] 3.1 Request `get_running_tolerance(..., aggregation="daily")` in `_collect_historic_metrics` and `targeted_analysis_sources()`, label it `daily` in both `_provider_metrics` projections, and verify with `test_known_sdk_methods_get_bounded_dates_and_explicit_aggregation`, `test_targeted_weekly_view_metrics_request_daily_readings`, and `test_daily_weekly_view_metrics_reach_the_newest_measurement`; weekly training status stays weekly.

## 4. Integration checks

- [x] 4.1 Run `python -m unittest discover -s tests -v`, `python -m compileall -q server.py backend tests`, and the repo-wide mypy ratchet check; all pass.
- [x] 4.2 Review the complete diff for scope (no frontend, schema, canonical-mapping, or weekly-training-status changes) and run `npm run openspec -- validate fix-garmin-endurance-score-currency --strict --no-interactive`; it passes.
- [x] 4.3 Record in the handoff that the daily live payload shape is unverified until the next real Garmin sync, and how to confirm it (analysis view shows the running week's endurance score dated on its latest Garmin measurement).

## Workflow follow-up

- After merge and a real Garmin sync, confirm in the app that the endurance score advances past 2026-10-18.
- Sync the delta into `openspec/specs/performance-and-readiness/spec.md` and archive the change after review requirements are satisfied.
