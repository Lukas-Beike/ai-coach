# nutrition-provider-sync Specification

## Purpose

Describe explicit local-diary export to Intervals.icu and scoped Garmin nutrition refreshes at application revision `b8c911c9dda83a7920171916ace32681c0c38ba0`. Requirements document inspected implementation and tests, not a completed live-provider conformance run. Local diary and totals are specified by `nutrition-diary-and-targets`; client request races by `view-refresh-and-client-state`. Local revision checks do not establish remote compare-and-swap protection against independent Intervals edits.

## Requirements

### Requirement: Nutrition export is an explicit queued operation
The system SHALL start an HTTP nutrition export only from the authenticated, CSRF-protected sync action and return a queued-job receipt. Ordinary diary reads, edits, product lookup, and view refresh SHALL not implicitly export nutrition.

#### Scenario: Export one selected date
- **WHEN** the athlete explicitly submits a nutrition sync with a date
- **THEN** the server enqueues the Intervals nutrition-sync operation for that date and returns HTTP 202 with its `sync_job_id`.

#### Scenario: Export pending dates
- **WHEN** the explicit action selects pending dates rather than one date
- **THEN** the queued payload carries the requested pending limit, defaulting to fourteen; service execution accepts only a limit from one through thirty-one.

#### Scenario: Refresh the diary
- **WHEN** the athlete refreshes a nutrition view
- **THEN** the narrow read-refresh path is used and no nutrition-export job is enqueued.

Evidence: `backend/http_api/nutrition.py::NutritionPostRoutes._sync`, `backend/nutrition/sync.py::IntervalsNutritionSyncService.sync_pending`, `backend/http_api/handler.py::RequestHandler.do_POST`; `tests/test_nutrition_api_and_sync.py::NutritionHttpApiTests.test_post_sync_route`, `tests/test_nutrition_api_and_sync.py::NutritionHttpApiTests.test_post_sync_pending_route_queues_bounded_provider_job`, `tests/test_nutrition_api_and_sync.py::NutritionHttpApiTests.test_nutrition_refresh_diary_reads_local_meals_and_only_daily_energy`.

### Requirement: Approved exports bind exact local snapshots
The system SHALL represent an approved nutrition export as selected dates with local revision, calories, macros, entry count, and a content digest. Approved execution SHALL validate the complete manifest and recheck each date before writing it.

#### Scenario: Local change after approval
- **WHEN** any selected local snapshot differs from the approved manifest before execution
- **THEN** execution fails with a conflict before any provider write begins.

#### Scenario: New pending date appears
- **WHEN** another date becomes pending after approval
- **THEN** approved execution exports only the frozen approved dates rather than expanding its scope.

#### Scenario: Change during a multi-date run
- **WHEN** an earlier date succeeds but a later date no longer matches its approved snapshot
- **THEN** the earlier success remains reported and the later date is a failed result rather than being silently overwritten.

Evidence: `backend/nutrition/contracts.py::nutrition_approval_item`, `backend/nutrition/sync_status.py::NutritionSyncStatusService.approval_manifest`, `backend/nutrition/sync.py::IntervalsNutritionSyncService.sync_approved`; `tests/test_nutrition_api_and_sync.py::IntervalsNutritionSyncServiceTests.test_approved_sync_rejects_changed_manifest_before_provider_write`, `tests/test_nutrition_api_and_sync.py::IntervalsNutritionSyncServiceTests.test_approved_sync_dispatches_only_frozen_dates`, `tests/test_nutrition_api_and_sync.py::IntervalsNutritionSyncServiceTests.test_approved_sync_preserves_prior_results_when_a_later_day_fails`.

### Requirement: Daily export writes only supported wellness totals
The system SHALL export a day's aggregated calories and macros to that day's Intervals wellness record. Unknown or incomplete macros SHALL be explicitly unset rather than leaving a previously exported remote value in place.

#### Scenario: Complete totals
- **WHEN** a selected day has complete local macros
- **THEN** the wellness update contains `kcalConsumed`, `carbohydrates`, `protein`, and `fatTotal` with the day's aggregate values.

#### Scenario: Calories-only or incomplete macros
- **WHEN** a macro total is unknown
- **THEN** that remote field is sent as the provider's unset number, `-1`, while known calories are still sent.

#### Scenario: Empty day after deletion
- **WHEN** the final previously exported entry is deleted and the athlete explicitly exports the pending date
- **THEN** the zero-calorie day and appropriate macro clearing can replace the old daily nutrition totals without requiring a fabricated meal.

#### Scenario: Repeat the selected day's export
- **WHEN** an unchanged day is explicitly exported again
- **THEN** its totals target the same dated wellness resource rather than creating another local diary entry; this does not promise exactly-once network delivery or remote conflict protection.

Evidence: `backend/nutrition/sync.py::IntervalsNutritionSyncService.sync_day`, `backend/nutrition/sync.py::UNSET_REMOTE_NUMBER`; `tests/test_nutrition_api_and_sync.py::IntervalsNutritionSyncServiceTests.test_sync_day_calls_intervals_api_and_marks_synced`, `tests/test_nutrition_api_and_sync.py::IntervalsNutritionSyncServiceTests.test_sync_clears_unknown_macros_remotely_and_marks_date_synced`, `tests/test_nutrition.py::NutritionRepositoryAndServiceTests.test_deleting_last_synced_entry_keeps_empty_date_pending`. The last scenario combines inspected deletion/requeue and export behavior; there was no live empty-day provider write in this backfill.

### Requirement: Export completion is revision-safe and retryable
The system SHALL mark a date synced only if its local revision still matches the sent snapshot. A provider failure or concurrent local edit SHALL retain pending work, and a batch result SHALL distinguish synced, pending, and failed dates.

#### Scenario: Stable successful write
- **WHEN** the provider accepts a day's update and the local revision is unchanged
- **THEN** the date is marked synced at that revision.

#### Scenario: Local edit during provider write
- **WHEN** the local meal changes while the remote request is in flight
- **THEN** the sent snapshot can succeed remotely but the new local revision remains pending and is not reported as fully synced.

#### Scenario: Partial batch failure
- **WHEN** one date fails while others succeed
- **THEN** successes remain acknowledged, failures remain available for retry, and the aggregate `ok` is false when pending or failed dates remain.

Evidence: `backend/nutrition/sync.py::IntervalsNutritionSyncService.sync_day`, `backend/nutrition/sync.py::IntervalsNutritionSyncService.sync_pending`, `backend/nutrition/sync_status.py::NutritionSyncStatusService.mark_date_synced`; `tests/test_nutrition_api_and_sync.py::IntervalsNutritionSyncServiceTests.test_sync_keeps_date_pending_when_meal_changes_during_remote_write`, `tests/test_nutrition_api_and_sync.py::IntervalsNutritionSyncServiceTests.test_sync_pending_keeps_revision_races_out_of_synced_dates`, `tests/test_nutrition_api_and_sync.py::IntervalsNutritionSyncServiceTests.test_sync_pending_processes_all_dates`.

### Requirement: Nutrition refresh reads only its selected source and dates
The system SHALL accept explicit refreshes for diary, week, body, or products and restrict each to its owned data. Week/body refreshes SHALL accept only fourteen or eighty-four days and reject future end dates and unsupported payload fields.

#### Scenario: Diary energy refresh
- **WHEN** the athlete refreshes a selected diary date
- **THEN** local meals are reread and only Garmin daily energy for that date is requested, with local meal status distinguished from provider status.

#### Scenario: Week or body refresh
- **WHEN** a valid period is refreshed
- **THEN** week requests only daily stats for the closed-day range, while body requests only weight for its bounded range ending on the athlete-local day by default.

#### Scenario: Local product refresh or invalid request
- **WHEN** products are refreshed or a period/area/payload is invalid
- **THEN** products return local status without provider I/O; invalid requests fail before provider access.

Evidence: `backend/http_api/nutrition.py::NutritionPostRoutes._refresh`, `backend/http_api/nutrition.py::NutritionPostRoutes._refresh_provider`; `tests/test_nutrition_api_and_sync.py::NutritionHttpApiTests.test_nutrition_refresh_week_uses_requested_range`, `tests/test_nutrition_api_and_sync.py::NutritionHttpApiTests.test_nutrition_refresh_body_uses_bounded_weight_range`, `tests/test_nutrition_api_and_sync.py::NutritionHttpApiTests.test_nutrition_refresh_local_products_never_calls_provider`, `tests/test_nutrition_api_and_sync.py::NutritionHttpApiTests.test_nutrition_refresh_rejects_invalid_range`.

### Requirement: Failed or empty Garmin reads retain honest freshness
The system SHALL preserve previously stored nutrition-related measurements on a failed refresh, return explicit partial/unconfigured/unsupported status, and scope successful freshness to the selected source and dates rather than claiming a complete provider sync.

#### Scenario: Provider unavailable
- **WHEN** a narrow provider refresh fails or is unconfigured
- **THEN** the response is partial with an actionable reason, local meals remain available, and retained data is not persisted as freshly fetched.

#### Scenario: Empty body refresh
- **WHEN** the selected weight read returns no usable measurement
- **THEN** prior measurements remain as stale context and the result is partial.

#### Scenario: Multiple same-day scale observations
- **WHEN** a bounded weight refresh includes distinct readings or timestamped corrections
- **THEN** stored history retains distinct samples and replaces identified corrections while preserving measurements outside the refreshed window.

Evidence: `backend/sync/garmin_service.py::GarminNutritionRefreshService.refresh`, `backend/http_api/nutrition.py::NutritionPostRoutes._refresh_provider`; `tests/test_nutrition_garmin_refresh.py::GarminNutritionRefreshTests.test_provider_failure_returns_partial_without_persisting_stale_as_fresh`, `tests/test_nutrition_garmin_refresh.py::GarminNutritionRefreshTests.test_empty_body_refresh_is_partial_and_retains_prior_measurement_as_stale`, `tests/test_nutrition_garmin_refresh.py::GarminNutritionRefreshTests.test_weight_snapshot_merge_replaces_timestamped_corrections_and_keeps_metadata`.
