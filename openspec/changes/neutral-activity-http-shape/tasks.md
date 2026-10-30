# Tasks

## 1. Boundary translation

- [x] 1.1 Extend `backend/canonical/public_metrics.py` with the full activity map (design D1). Apply it to list rows, to `is_completed_activity` entries and to `compliance.actual_activity`. Every other entry gets only the metric renames. Verify in `tests/test_canonical_public_metrics.py` that:
  - every key in the map is translated;
  - a neutral key that is already present wins;
  - the VO2max aliases collapse;
  - a planned unit keeps `start_date_local` and `moving_time`;
  - nested laps are translated;
  - no key from `ACTIVITY_FIELDS` outside the generic set survives.
- [x] 1.2 Apply `neutral_calendar_entries` to `calendar` and `planning_view.items` in `backend/http_api/bootstrap_calendar.py` and `public_plan.py` (D2). Verify in `tests/test_public_plan.py`, `tests/test_http_sync_get_routes.py`, `tests/test_server_planning.py` and `tests/test_server_weather_calendar.py`, with the key assertions updated.

## 2. PWA

- [ ] 2.1 Move `public/activity-analysis.js` (the list item and `rowMetrics`) and `public/plan-views.js` to the neutral keys, on activity objects only (D3). In `plan-views.js` this covers the actual-activity duration, pace, facts, start time, week totals and sort. Bump the `public/index.html` query versions and the `public/service-worker.js` cache name and assets together. Verify with `node --test tests/*.cjs` and with the e2e fixtures and specs updated to the neutral keys.

## 3. Guard

- [x] 3.1 Add the `field_module_import` rule to `tests/provider_coupling.py` (D4) with scanner tests, and record the current importers, each with its owning issue (#1415, #1416, #1507, #1510). Done as an owner-read rule with an explained allowlist, because the ratchet baseline must stay empty (`test_owner_allowlist_is_explained_and_the_baseline_stays_empty`); a stale allowlist entry fails the guard, so the list can only shrink. Verify with `python -m unittest tests.test_provider_coupling_guard`.

## 4. Validation and follow-up

- [x] 4.1 File the follow-up issue for the backend activity consumers and the Coach context activity keys, and cite it in the baseline description and the PR. Verify that the issue URL is recorded. Done: https://github.com/Lukas-Beike/ai-coach/issues/1510 is cited in `tests/provider_coupling.py` (`_ACTIVITY_ROWS`).
- [ ] 4.2 Run the full unit suite, `compileall`, the quality ratchet, `node --test tests/*.cjs`, `npm run openspec -- validate --all --strict --no-interactive`, and Playwright on all five projects for the analysis, activity-details, contracts and plan/calendar specs. Verify with the command output in the PR body.
