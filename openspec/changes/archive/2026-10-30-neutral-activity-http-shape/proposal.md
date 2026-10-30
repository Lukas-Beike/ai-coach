# Proposal

## Why

Issue #1413 (Epic A #1407), slice 2. The daily wellness view became provider-neutral in #1505. Activity summaries still cross the HTTP boundary in Intervals.icu shape. `backend/canonical/public_metrics.py` renames only six `icu_*` metrics, so `/api/activities`, `/api/bootstrap` and `/api/plan` still send keys such as `start_date_local`, `moving_time`, `average_watts`, `average_heartrate`, `icu_ctl` and `icu_ftp`, and the PWA reads them directly.

The user decided on 2026-10-30 to take the boundary first. Backend activity internals keep their raw rows for now. Matching, grouping, calendar projection and conflicts share their keys with local planning records, and those records move together with #1507.

## What Changes

- `public_metrics` becomes the single HTTP translation of completed-activity objects. These are:
  - the list rows of `/api/activities` and `/api/bootstrap` `activities`;
  - completed-activity calendar entries;
  - `compliance.actual_activity` in `training_calendar`, `planned`, `calendar` and `planning_view.items` of `/api/bootstrap` and `/api/plan`.

  Every Intervals.icu activity key is renamed to the vocabulary of the existing detail document (`started_at_local`, `moving_duration_s`, `distance_m`, `avg_hr`, `avg_power`, `normalized_power`, `elevation_gain_m`, `avg_speed_mps` and so on). The five VO2max aliases collapse to `vo2max`.
- Planned units, competitions and external events keep their stored keys until #1507. They get only the existing metric renames (`training_load`, `intensity`, `rpe` and the like), which now also apply in `calendar` and `planning_view.items`.
- **BREAKING (HTTP JSON):** activity objects no longer carry the former keys, and no dual keys are emitted. The PWA activity list, the analysis row summary and the calendar's actual-activity views move to the neutral keys in the same change. `public/index.html` query versions and the `public/service-worker.js` cache name and assets are bumped.
- The provider-coupling ratchet gains a rule that records every module outside `backend/providers/`, `backend/sync/` and `backend/canonical/` that imports a field-name module (`intervals_activity_fields`, `intervals_performance_fields`, `garmin_fields`, `garmin_performance_fields`, `garmin_gear_fields`). It is an owner-read rule: the remaining readers are listed in its explained allowlist with their owning issue (#1415, #1416, #1507, #1510), and a stale entry fails the guard, so the list can only shrink.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `activity-analysis-and-feedback`: completed-activity summaries over HTTP use provider-neutral keys.

## Impact

- Code:
  - `backend/canonical/public_metrics.py`;
  - `backend/http_api/bootstrap_calendar.py` and `public_plan.py`, which translate `calendar` and `planning_view.items`;
  - `public/activity-analysis.js`, `public/plan-views.js`, `public/index.html` and `public/service-worker.js`;
  - `tests/provider_coupling.py` and its baseline.
- Tests: `tests/test_canonical_public_metrics.py`, the HTTP route and plan tests, and the e2e fixtures and specs for analysis, calendar and contracts.
- No schema, provider, sync or Coach-context change, and no remote write. The new follow-up issue covers the Coach context activity keys and the backend activity consumers.
