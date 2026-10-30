## ADDED Requirements

### Requirement: Completed-activity summaries use provider-neutral keys over HTTP
Every completed-activity object that the HTTP API returns SHALL carry provider-neutral keys produced by one translation, and SHALL NOT carry the former Intervals.icu activity keys. Values SHALL be unchanged. Local planning records keep their stored keys until #1507 and receive only the metric renames.

#### Scenario: Activity list row
- **WHEN** `/api/activities` or `/api/bootstrap` returns an activity with start, duration, distance, heart-rate, power, speed, load, threshold and VO2max values
- **THEN** they appear as `started_at_local`, `moving_duration_s`, `elapsed_duration_s`, `distance_m`, `avg_hr`, `max_hr`, `avg_power`, `weighted_avg_power`, `normalized_power`, `avg_speed_mps`, `elevation_gain_m`, `training_load`, `intensity`, `rpe`, `ctl`, `atl`, `ftp_w`, `eftp_w` and `vo2max` with the stored values, and none of `start_date_local`, `moving_time`, `distance`, `average_heartrate`, `average_watts` or `icu_*` is present.

#### Scenario: Calendar actual activity
- **WHEN** `/api/bootstrap` or `/api/plan` returns, in `training_calendar`, `planned`, `calendar` or `planning_view.items`, a completed-activity calendar entry or a planned unit matched to an activity
- **THEN** the completed entry and `compliance.actual_activity` use the neutral keys. The planned unit keeps its own `start_date_local` and `moving_time` unchanged, and its `icu_training_load` appears as `training_load`.

#### Scenario: Neutral value already present
- **WHEN** a stored row carries both a provider key and its neutral counterpart, such as `icu_weighted_avg_watts` and `normalized_power`
- **THEN** the neutral value wins and the provider key is dropped.

#### Scenario: Browser shows unchanged values
- **WHEN** the activity analysis list, the analysis row summary before the detail loads, and the calendar's completed and matched entries render the same synthetic data as before
- **THEN** they show the same dates, durations, distances, heart rate, power and load.

Detailed contract: the key map is listed in this change's design (D1). A neutral key that is already present wins. `weighted_average_watts` stays separate from `normalized_power`. The activity detail document (`/api/activities/{id}`) is already neutral and stays unchanged. The provider-coupling ratchet records every module outside the provider, sync and canonical packages that imports a provider field-name module, and that record may only shrink.

Evidence: `backend/canonical/public_metrics.py:neutral_activity`, `backend/canonical/public_metrics.py:neutral_calendar_state`, `backend/http_api/bootstrap_calendar.py`, `backend/http_api/public_plan.py:PublicPlanStateService.read_public`, `backend/http_api/bootstrap_state.py`, `public/activity-analysis.js`, `public/plan-views.js`; `tests/test_canonical_public_metrics.py:NeutralPublicMetricsTests`, `tests/test_http_sync_get_routes.py:test_activity_page_uses_neutral_names_and_detail_is_passed_through`, `tests/test_public_plan.py:test_internal_read_keeps_stored_metrics_and_public_read_translates`, `tests/plan-views-week-distance.test.cjs`, `tests/test_provider_coupling_guard.py:OwnerReadGuardTests.test_consumers_cannot_import_provider_field_name_modules`; `e2e/contracts.spec.js`, `e2e/activity-details.spec.js`.
