## MODIFIED Requirements

### Requirement: Local activity reads and pagination
The system SHALL read activity rows and sync metadata from one local read snapshot without refreshing providers, expose local activity references with feedback, and offer descending keyset pagination with versioned cursors and legacy cursor compatibility. Page limits SHALL default to 100 and clamp to 1 through 250. Reads SHALL retain summary rows whose detail failed and show only failure notes matching the current summary fingerprint. The sync time reported with the activity list (`snapshot_synced_at`) SHALL be the Intervals.icu activity fetch time of the canonical provider coverage and SHALL be null when no coverage is stored.

#### Scenario: Next activity page
- **WHEN** the athlete requests a page after a valid cursor
- **THEN** results follow the stable descending local-time/id boundary and include a next cursor only when more rows remain.

#### Scenario: Detail failure or invalid cursor
- **WHEN** detail is unavailable or a cursor cannot be decoded
- **THEN** summary reading remains usable; a matching detail error is shown and an invalid cursor falls back to the first-page boundary.

#### Scenario: Guarded kv detail access
- **WHEN** the repository test suite runs
- **THEN** a guard test fails if any production module outside the backfill and retirement modules references the `activity_detail:` kv record prefix or the legacy detail record reader.

#### Scenario: Activity list freshness from canonical coverage
- **WHEN** the activity list is read and canonical coverage stores an Intervals.icu activity fetch time
- **THEN** `snapshot_synced_at` equals that time in the same read snapshot as the rows, independent of the stored snapshot's `synced_at`, of unrelated performance refreshes and of a duplicate deletion.

#### Scenario: No stored coverage
- **WHEN** no Intervals.icu coverage is stored
- **THEN** `snapshot_synced_at` is null, the list still renders, and no snapshot timestamp is substituted.

Detailed contract: Activity freshness SHALL remain independent of unrelated performance refresh timestamps. Production activity, detail, report and calendar reads SHALL NOT read `activity_detail:<sha>` kv records; only the backfill and retirement maintenance modules may read them. The key `snapshot_synced_at` keeps its name.

Evidence: `backend/activities/read_service.py:ActivityReadService.page`, `backend/activities/read_service.py:ActivityReadService._read`; `tests/test_activity_read_service.py:test_page_filters_orders_attaches_feedback_and_uses_cursor`, `tests/test_activity_read_service.py:test_page_keeps_activities_with_failed_details_and_names_the_error`, `tests/test_activity_read_service.py:test_activity_refresh_timestamp_is_independent_of_performance_refresh`. `tests/test_activity_detail_kv_guard.py:test_production_code_does_not_touch_kv_detail_records`. Missing evidence (planned in this change): tests that `snapshot_synced_at` comes from coverage, is null without coverage and is unchanged by a duplicate deletion; `public/activity-analysis.js:load` consumes the key unchanged (no frontend change planned).

### Requirement: Explicit duplicate deletion
The system SHALL delete a remotely stored duplicate only after validating the current detected Wahoo/Garmin duplicate pair and the explicit delete confirmation. The duplicate service SHALL retain the Wahoo activity, delete the selected Garmin copy through Intervals first, then tombstone the canonical records and session in one local transaction and publish the resulting state change. It SHALL NOT read, rewrite or save the Intervals.icu snapshot. A stale confirmation or remote-delete error SHALL not mutate local data.

#### Scenario: Confirmed current duplicate
- **WHEN** the submitted pair still matches the current duplicate and confirmation is valid
- **THEN** exactly one Intervals.icu delete request names only the duplicate, and local canonical readers cease serving it after the local commit.

#### Scenario: Stale or rejected delete
- **WHEN** the submitted pair or its confirmation token has changed or the provider delete fails
- **THEN** no provider delete (for a stale pair), no local deletion and no success event occur.

#### Scenario: Snapshot untouched by a delete
- **WHEN** a duplicate is deleted
- **THEN** no snapshot row is written and the stored Intervals.icu snapshot `synced_at` and the coverage fetch time are unchanged.

#### Scenario: Merged duplicate session
- **WHEN** the deleted copy's session is a heuristic alias of the kept session
- **THEN** its record, provider record and session are tombstoned in the same transaction and the kept Wahoo activity stays served.

Detailed contract: This flow does not promise distributed rollback if remote deletion succeeds and a later local write fails. Merging or undoing duplicates, athlete-confirmed sessions and any other remote write are outside this flow.

Evidence: `backend/activities/duplicates.py:validate_duplicate_delete`, `backend/activities/duplicate_service.py:DuplicateActivityService.delete`; `tests/test_activity_duplicate_service.py:test_stale_confirmation_has_no_side_effects`, `tests/test_activity_duplicate_service.py:test_remote_failure_does_not_mutate_snapshot_or_publish`, `tests/test_activity_duplicate_service.py:test_delete_tombstones_the_canonical_records_in_the_snapshot_transaction`, `tests/test_activity_duplicate_service.py:MergedDuplicateDeleteTests.test_confirmed_delete_tombstones_the_merged_duplicate_session`. Missing evidence (planned in this change): tests that no snapshot is read or saved and that the snapshot `synced_at` is unchanged, and restart and backup/restore tests of tombstones and merged state.

## ADDED Requirements

### Requirement: Canonical duplicate pair detection
The system SHALL detect and inspect the newest Wahoo/Garmin duplicate ride pair from canonical active Intervals.icu activity records, keeping the Wahoo-recorded activity and offering the Garmin-recorded copy for deletion, without reading the Intervals.icu snapshot. A pair SHALL contain the newest Intervals.icu activity.

#### Scenario: Current pair
- **WHEN** an active Wahoo-recorded and an active Garmin-recorded Intervals.icu ride start within 30 minutes and their durations and distances agree within the duplicate tolerances
- **THEN** inspection returns `canonical_id` and `duplicate_id` (the Intervals.icu activity ids), names, local start, moving time, distance and `snapshot_synced_at`, with Wahoo kept, even when no snapshot exists.

#### Scenario: Newer unrelated or tombstoned activity
- **WHEN** a newer unrelated Intervals.icu activity exists, a record of the pair is deleted, or an id is missing or equal
- **THEN** inspection returns no pair.

#### Scenario: Confirmation token follows the records
- **WHEN** either record of the pair is fetched again after the proposal was created
- **THEN** `snapshot_synced_at` (the newest canonical fetch time of the two records) differs and the submitted confirmation is rejected with a conflict before any provider call.

Detailed contract: The manifest key `snapshot_synced_at` is kept for contract stability; its value is the newest canonical fetch time of the pair. Persisted session links (`merged_into`) are not consulted for detection.

Evidence: `backend/activities/duplicate_inspection.py:DuplicateInspector.latest`, `backend/activities/canonical_sessions.py` (Wahoo/Garmin ride rule); `tests/test_activity_duplicates.py:WahooGarminDuplicateTests` (raw-row rule being ported), `tests/test_coach_tool_coverage.py:test_duplicate_inspection_returns_preview_without_deleting_provider_data`. Missing evidence (planned in this change): detection from canonical records with an absent snapshot, token change on refetch, and parity of sport and duration handling.

### Requirement: Garmin status compares against canonical Intervals rows
The system SHALL compute the Garmin status counts `activities` and `duplicate_activities_skipped` by comparing the raw Garmin payload activities with the canonical Intervals.icu activity rows only.

#### Scenario: Canonical source
- **WHEN** the Garmin public state is built
- **THEN** the Intervals.icu rows come from the canonical row port and the stored snapshot is not read for activities.

#### Scenario: No Intervals rows
- **WHEN** the canonical row port holds no Intervals.icu activities
- **THEN** no Garmin activity is skipped as a duplicate.

Evidence: `backend/sync/garmin_projection_service.py:GarminProjectionService._canonical_read`, `backend/activities/duplicates.py:filter_garmin_activities`; `tests/test_garmin_canonical_reads.py`, `tests/test_sync_garmin_projection_service.py:test_public_state_preserves_status_metrics_dedup_and_redacted_core_errors`. Missing evidence (planned in this change): construction without canonical sources is rejected and no snapshot activity fallback remains.
