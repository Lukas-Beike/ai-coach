# activity-ingestion-and-storage Specification

## Purpose

Describe durable provider activity ingestion, identity and session bundling, detail acquisition, pagination, corrections, and explicit deletion behavior.

## Requirements

### Requirement: Provider reads preserve complete and partial outcomes
The system SHALL fetch Intervals activities/wellness/events through bounded date windows and pagination, Garmin through bounded provider collections with source outcomes, and Wahoo through paged workout summaries. Wahoo SHALL bound a run to 20 pages of 50 workouts and report truncation as partial. Missing optional Wahoo scopes or refused optional sources SHALL not invalidate fetched activities. Provider imports SHALL not upload workouts as a side effect of reading them.

#### Scenario: Truncated Wahoo collection
- **WHEN** workout pagination reaches its cap before establishing complete coverage
- **THEN** collected valid activities are persisted and the result is partial rather than claiming complete history.

#### Scenario: Optional source refusal
- **WHEN** workouts are readable but Wahoo refuses power zones with 403 or 404
- **THEN** workouts are imported and the optional source is reported skipped.

Evidence: `backend/sync/intervals.py:IntervalsSnapshotReader.fetch_snapshot`, `backend/providers/garmin.py:collect_garmin_data`, `backend/providers/wahoo_client.py:WahooClient`, `backend/sync/wahoo_sync.py:WahooSyncService._sync_locked`; `tests/test_wahoo_sync.py:test_truncated_fetch_reports_partial`, `tests/test_wahoo_runtime_acceptance.py:test_the_owner_never_writes_to_wahoo`, `tests/test_sync_intervals_reader.py:test_incremental_merge_and_full_sync_behavior`, `tests/test_sync_intervals_reader.py:test_historical_date_windows_and_calendar_window`.

### Requirement: Atomic canonical import and correction
The system SHALL atomically store sanitized provider records and canonical projections within the owning ingest transaction. Repeated natural identities SHALL update or retain records without duplicate activities. Wahoo SHALL commit coverage and success markers with its ingest; Garmin SHALL commit canonical payload/state together, with later metadata, equipment, and cursor operations retaining their separate persistence boundaries.

#### Scenario: Corrected repeat import
- **WHEN** the same provider activity arrives again with revised measurements
- **THEN** the owned record is updated under the same natural identity and consumers see the correction without a second activity.

#### Scenario: Wahoo success-marker failure
- **WHEN** storing a Wahoo marker or coverage summary fails inside its ingest transaction
- **THEN** canonical writes and success freshness roll back together.

Detailed contract: Fresh payloads replace their owned corrected values while retained sections preserve their own fetch time. A failed Wahoo canonical/coverage/marker write rolls back that transaction. Garmin's later persistence failure can leave an earlier payload commit intact; this baseline does not claim one transaction covers its entire lifecycle.

Evidence: `backend/sync/canonical_ingest.py:ingest_plan`, `backend/sync/garmin_snapshot_writer.py:GarminSnapshotWriter`, `backend/sync/wahoo_sync.py:WahooSyncService._sync_locked`; `tests/test_wahoo_sync.py:test_resync_is_idempotent`, `tests/test_wahoo_sync.py:test_coverage_failure_rolls_the_whole_ingest_back`, `tests/test_canonical_ingest.py:test_a_partial_refresh_keeps_the_fetch_time_of_retained_sections`.

### Requirement: Conservative disappearance reconciliation
The system SHALL infer missing-activity deletion only for eligible complete Intervals fetches and only inside the safe inner days of the covered window. Edge days, historical chunks, incremental reads, and absent activity collections SHALL not delete activities merely because a fetched response omits them. Garmin absence in a later payload SHALL not delete its earlier activities. Deletion SHALL retain provider tombstone/state evidence rather than erasing identity.

#### Scenario: Complete interior disappearance
- **WHEN** a complete eligible Intervals collection omits an existing activity within the safe covered interior
- **THEN** the activity can be marked deleted through canonical reconciliation.

#### Scenario: Incomplete evidence of absence
- **WHEN** an activity is missing from an incremental or historical response, an edge day, or a Garmin refresh
- **THEN** the system retains the stored activity rather than treating omission as deletion authorization.

Evidence: `backend/sync/canonical_ingest.py:intervals_deletion_window`, `backend/sync/canonical_ingest.py:ingest_intervals_snapshot`, `backend/sync/canonical_ingest.py:ingest_garmin_payload`; `tests/test_canonical_ingest.py:test_full_fetch_never_deletes_on_the_edge_days_of_its_window`, `tests/test_canonical_ingest.py:test_historical_fetch_never_deletes`, `tests/test_canonical_ingest.py:test_garmin_never_deletes_an_activity_missing_from_a_later_payload`.

### Requirement: Deterministic provider-copy session identity
The system SHALL bundle supported provider copies into canonical sessions using deterministic start, sport-family, duration, distance, and recording-origin rules. The matching start window is 30 minutes, with duration tolerance at least 120 seconds or 10 percent and distance tolerance at least 500 metres or 10 percent under each implemented pairing rule. Intervals remains primary over direct Wahoo and Garmin; Wahoo-recorded rides can retain Garmin copies as alternatives.

#### Scenario: Several recordings of one ride
- **WHEN** compatible Intervals, direct Wahoo, and Garmin records represent the same measured session
- **THEN** each input belongs to exactly one canonical session with deterministic primary and duplicate-link metadata.

#### Scenario: Ambiguous nearby activity
- **WHEN** candidates lack enough comparable data or conflict with matching tolerances
- **THEN** they remain separate instead of being merged merely because their timestamps are close.

Detailed contract: Garmin elapsed-time fallback SHALL avoid assigning multiple separate walks to one already claimed session. Local session references SHALL resolve to the appropriate provider identity at mutation/detail boundaries.

Evidence: `backend/activities/canonical_sessions.py:bundle_sessions`, `backend/activities/session_linking.py:link_activity_sessions`, `backend/activities/activity_reference.py:ActivityReferences`; `tests/test_canonical_sessions.py:test_order_is_deterministic_regardless_of_input_order`, `tests/test_canonical_sessions.py:test_garmin_record_joins_the_wahoo_session_through_a_garmin_copy`, `tests/test_garmin_activity_detail_job.py:test_session_alias_resolves_to_the_garmin_record`.

### Requirement: Durable Intervals detail cache and prefetch
The system SHALL fetch full-resolution Intervals detail only for a valid locally known activity, verify returned identity, normalize supported streams, laps, and zones, and store canonical detail sets and the canonical analysis payload atomically, without writing a kv detail document. Automatic prefetch SHALL initially establish its floor from the ten newest activities, thereafter load new activities at or above that fixed floor, and limit each pass to 25 provider loads.

#### Scenario: Failed second detail request
- **WHEN** an activity's previous canonical detail exists and its next provider stream request fails
- **THEN** the previous canonical sets and analysis payload remain readable and no half-written new detail replaces them.

#### Scenario: Old known activity requested
- **WHEN** the athlete requests a valid known activity before the prefetch floor
- **THEN** explicit loading can populate its detail even though automatic prefetch leaves it alone.

#### Scenario: Successful refresh writes only canonical state
- **WHEN** an explicit or automatic Intervals.icu detail load succeeds
- **THEN** the canonical sets and analysis payload are written, the failure note of that activity is deleted in the same transaction, and no `activity_detail:<sha>` kv row is created or updated.

#### Scenario: Canonical write fails
- **WHEN** the canonical detail write raises inside the refresh transaction
- **THEN** no canonical set, analysis payload or failure-note deletion is committed.

#### Scenario: Prefetch settledness
- **WHEN** prefetch decides whether an activity still needs loading
- **THEN** it uses only the summary fingerprints stored with canonical detail sets and analysis payloads, plus failure notes for the same fingerprint. A remaining kv detail record does not mark an activity settled.

#### Scenario: Target reuse after reload
- **WHEN** a session already has a canonical analysis payload with a `target_snapshot` and its detail is reloaded
- **THEN** that frozen snapshot is reused instead of re-freezing targets from the current plan.

Detailed contract: Summary fingerprints SHALL prevent redundant loads and invalidate stale data/failure notes after corrections. Failure notes and the prefetch floor remain small kv keys. Older activities SHALL remain available for explicit detail loading. The refresh use case SHALL require a canonical detail writer. Frozen planned targets SHALL be reused from the stored canonical analysis payload of the session.

Evidence: `backend/sync/activity_details.py:ActivityDetailRefreshService.refresh`, `backend/sync/activity_details.py:INITIAL_PREFETCH_ACTIVITIES`, `backend/activities/detail_store.py:ActivityDetailStore`, `backend/db/activity_detail_fingerprints.py:intervals_detail_fingerprints`; `tests/test_activity_detail_refresh.py:test_first_run_loads_the_ten_newest_activities_once`, `tests/test_activity_detail_refresh.py:test_changed_summary_is_loaded_again`, `tests/test_activity_detail_refresh.py:test_failed_canonical_write_commits_nothing`. `tests/test_activity_detail_refresh.py:test_refresh_writes_canonical_rows_without_a_kv_record`, `tests/test_activity_detail_refresh.py:test_frozen_targets_are_reused_from_the_canonical_analysis`, `tests/test_activity_detail_refresh.py:test_leftover_kv_record_does_not_settle_prefetch`, `tests/test_activity_detail_refresh.py:test_unstored_write_fails_and_keeps_the_failure_note`.

### Requirement: Garmin detail acquisition and recovery
The system SHALL fetch Garmin detail kinds independently for locally known active nonmanual Garmin records, persist returned valid sets without erasing omitted kinds, and report partial outcomes when only some kinds arrive.

#### Scenario: Partially returned detail
- **WHEN** Garmin supplies streams but fails or skips another requested kind
- **THEN** valid arrived sets can be stored with partial status and existing omitted sets are retained.

#### Scenario: Rate limit with no stored part
- **WHEN** Garmin rate-limits before any part can be stored
- **THEN** the batch pauses without consuming an ordinary per-summary failed attempt and can resume after the cooldown.

Detailed contract: Automatic detail backfill SHALL work newest first in bounded batches of ten, retain summary/version-aware empty and retry state, pause on rate limiting, bound retries for a failing summary, and continue to older candidates when one activity exhausts its retries. Cancellation SHALL stop between activities; token cleanup SHALL still run.

Evidence: `backend/sync/garmin_activity_details.py:GarminActivityDetailService.refresh`, `backend/sync/garmin_activity_details.py:GarminActivityDetailService.backfill`; `tests/test_garmin_activity_detail_job.py:test_partial_payload_writes_returned_kinds_and_keeps_stored_laps`, `tests/test_garmin_activity_detail_backfill.py:test_batch_is_limited_to_ten_and_reports_remaining`, `tests/test_garmin_activity_detail_backfill.py:test_failing_activity_stops_holding_back_older_ones`.

### Requirement: Wahoo FIT detail import
The system SHALL import available Wahoo FIT details after the summary ingest commits, use a plain allowlisted HTTPS download bounded to 16 MiB and 30 seconds, parse supported FIT stream/lap data, and attach Wahoo provenance plus the summary hash. It SHALL run at most ten downloads per pass within its time budget, skip already-current or marked-empty summaries, bound failed attempts to three per summary, and stop on rate limits without counting them as ordinary failures.

#### Scenario: Repeat unchanged FIT import
- **WHEN** current detail sets or an empty-file marker already match the Wahoo summary
- **THEN** that summary is not downloaded again; a changed summary can become eligible again.

#### Scenario: Unreadable FIT or missing link
- **WHEN** the file is unreadable, absent, too large, or untrusted
- **THEN** only the appropriate bounded detail failure/skip is recorded and committed summary activities remain available.

Detailed contract: Signed links SHALL be absent from stored raw rows, errors, and logs. Detail import failure SHALL not retroactively fail a successful summary import.

Evidence: `backend/sync/wahoo_activity_details.py:WahooActivityDetailImport.import_details`, `backend/providers/wahoo_fit_download.py:download_wahoo_fit`, `backend/providers/fit_file.py:fit_messages`, `backend/providers/fit_activity_detail_mapping.py:map_fit_activity_detail`; `tests/test_wahoo_activity_details.py:test_at_most_ten_downloads_run_per_sync`, `tests/test_wahoo_activity_details.py:test_download_link_is_absent_from_storage_and_logs`, `tests/test_wahoo_sync.py:test_a_failing_detail_import_keeps_the_sync_ok`.

### Requirement: Local activity reads and pagination
The system SHALL read activity rows and sync metadata from one local read snapshot without refreshing providers, expose local activity references with feedback, and offer descending keyset pagination with versioned cursors and legacy cursor compatibility. Page limits SHALL default to 100 and clamp to 1 through 250. Reads SHALL retain summary rows whose detail failed and show only failure notes matching the current summary fingerprint.

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

Detailed contract: The sync time reported with the activity list (`snapshot_synced_at`) SHALL be the Intervals.icu activity fetch time of the canonical provider coverage and SHALL be null when no coverage is stored. Activity freshness SHALL remain independent of unrelated performance refresh timestamps. Production activity, detail, report and calendar reads SHALL NOT read `activity_detail:<sha>` kv records; only the backfill and retirement maintenance modules may read them. The key `snapshot_synced_at` keeps its name.

Evidence: `backend/activities/read_service.py:ActivityReadService.page`, `backend/activities/read_service.py:ActivityReadService._read`; `tests/test_activity_read_service.py:test_page_filters_orders_attaches_feedback_and_uses_cursor`, `tests/test_activity_read_service.py:test_page_keeps_activities_with_failed_details_and_names_the_error`, `tests/test_activity_read_service.py:test_activity_refresh_timestamp_is_independent_of_performance_refresh`. `tests/test_activity_detail_kv_guard.py:test_production_code_does_not_touch_kv_detail_records`. Missing evidence (planned in this change): tests that `snapshot_synced_at` comes from coverage, is null without coverage and is unchanged by a duplicate deletion; `public/activity-analysis.js:load` consumes the key unchanged (no frontend change planned).

### Requirement: Explicit duplicate deletion
The system SHALL delete a remotely stored duplicate only after validating the current detected Wahoo/Garmin duplicate pair and the explicit delete confirmation. The duplicate service SHALL retain the Wahoo activity, delete the selected Garmin copy through Intervals first, then tombstone the canonical records and session in one local transaction and publish the resulting state change. It SHALL NOT read, rewrite or save the Intervals.icu snapshot.

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

#### Scenario: Deleted copy was the surviving session
- **WHEN** the deleted copy's session was the survivor of a heuristic merge and the Wahoo session an alias of it
- **THEN** in the same transaction the Wahoo session becomes the active survivor (the oldest live alias takes over, any other alias merges into it), the deleted session retains it for feedback, no live session stays merged into a deleted one, and the Wahoo ride's detail lookup, lists and feedback keep resolving. The same repair applies when a provider's activity disappears.

Detailed contract: A stale confirmation or remote-delete error SHALL not mutate local data. This flow does not promise distributed rollback if remote deletion succeeds and a later local write fails. Merging or undoing duplicates, athlete-confirmed sessions and any other remote write are outside this flow.

Evidence: `backend/activities/duplicates.py:validate_duplicate_delete`, `backend/activities/duplicate_service.py:DuplicateActivityService.delete`; `tests/test_activity_duplicate_service.py:test_stale_confirmation_has_no_side_effects`, `tests/test_activity_duplicate_service.py:test_remote_failure_does_not_mutate_snapshot_or_publish`, `tests/test_activity_duplicate_service.py:test_delete_tombstones_the_canonical_records_in_the_snapshot_transaction`, `tests/test_activity_duplicate_service.py:MergedDuplicateDeleteTests.test_confirmed_delete_tombstones_the_merged_duplicate_session`. Missing evidence (planned in this change): tests that no snapshot is read or saved and that the snapshot `synced_at` is unchanged, and restart and backup/restore tests of tombstones and merged state.

### Requirement: Verified kv detail retirement
The canonical backfill runner SHALL run a retirement stage after the activity detail backfill. Per kv detail record it SHALL map the record with the legacy mapper, refill canonical lap metrics that are missing, compare the defined fields with the canonical rows, and delete the kv record in the same transaction only when every comparison passes. It SHALL NOT request provider data, and unverifiable records SHALL stay unchanged and be counted.

#### Scenario: Verified record retired
- **WHEN** a kv record maps to canonical sets and an analysis payload that match on every compared field
- **THEN** the kv record is deleted in the batch transaction and the stage state counts it as retired.

#### Scenario: Missing lap metric refilled
- **WHEN** a canonical Intervals.icu lap set written before schema v13 has a NULL `max_speed_mps` or another NULL lap metric that the matching kv lap carries
- **THEN** that NULL is filled from the kv lap before the comparison, and non-NULL canonical values are never overwritten.

#### Scenario: Unverifiable record kept
- **WHEN** a record has no active Intervals.icu activity record, has no canonical set, fails a compared field, or holds downsampled streams that cannot be proven against the canonical streams
- **THEN** the kv record and its canonical rows are unchanged and the stage state counts it under its reason.

#### Scenario: Interrupted batch
- **WHEN** a retirement batch fails after some refills or deletions
- **THEN** the whole batch transaction rolls back, the stage is marked failed in its own transaction, and no kv record is lost without its verified canonical copy.

#### Scenario: Same-build restart
- **WHEN** the application restarts after a completed or interrupted retirement
- **THEN** the stage resumes from its stored cursor or reports completion, and repeating it changes no further rows.

#### Scenario: Upgrade from supported released schemas
- **WHEN** populated databases built from the frozen fixtures for schema v9 through v13 with seeded kv detail records are upgraded and the backfill and retirement stages run
- **THEN** every seeded detail remains readable as `activity_detail.v1`, verified kv records are retired, and unverifiable ones remain stored.

#### Scenario: Backup, restore and privacy export
- **WHEN** a database is backed up, restored or privacy-exported after retirement
- **THEN** the canonical detail sets, stream channels, laps, zone times and analysis payloads are present, and retired kv records are absent from the exported application state.

Evidence: `backend/sync/activity_detail_retirement.py:ActivityDetailRetirement`, `backend/db/activity_detail_store.py:refill_lap_metrics`, `backend/sync/canonical_backfill_assembly.py`; `tests/test_activity_detail_retirement.py:test_proven_record_is_deleted_and_other_keys_are_kept`, `tests/test_activity_detail_retirement.py:test_missing_lap_speed_is_refilled_before_the_record_is_retired`, `tests/test_activity_detail_retirement.py:test_lap_metric_that_differs`, `tests/test_activity_detail_retirement.py:test_failed_batch_rolls_back_refills_and_deletions`, `tests/test_activity_detail_retirement.py:test_restart_resumes_from_the_cursor_and_repeats_nothing`, `tests/test_activity_detail_retirement_upgrade.py:test_released_schemas_upgrade_and_retire_proven_records` (the SQLCipher variant is skipped without SQLCipher), `tests/test_activity_detail_retirement_backup.py:test_restored_backup_serves_the_same_document`, `tests/test_activity_detail_retirement_backup.py:test_privacy_export_holds_the_retired_detail_in_the_canonical_files`. Related existing behavior: `backend/sync/activity_detail_backfill.py:ActivityDetailBackfill`, `backend/sync/canonical_backfill_worker.py`.

### Requirement: Canonical duplicate pair detection
The system SHALL detect and inspect the newest Wahoo/Garmin duplicate ride pair from canonical active Intervals.icu activity records, keeping the Wahoo-recorded activity and offering the Garmin-recorded copy for deletion, without reading the Intervals.icu snapshot. A pair SHALL contain the newest Intervals.icu activity.

#### Scenario: Current pair
- **WHEN** an active Wahoo-recorded and an active Garmin-recorded Intervals.icu ride start within 30 minutes and their durations and distances agree within the duplicate tolerances
- **THEN** inspection returns `canonical_id` and `duplicate_id` (the Intervals.icu activity ids), names, local start, moving time, distance and `snapshot_synced_at`, with Wahoo kept, even when no snapshot exists.

#### Scenario: Newer unrelated or tombstoned activity
- **WHEN** a newer unrelated Intervals.icu activity exists, a record of the pair is deleted, or an id is missing or equal
- **THEN** inspection returns no pair.

#### Scenario: Legacy-state selector
- **WHEN** the canonical read selector still serves the snapshot projection (before the first completed backfill)
- **THEN** inspection and the delete validation read only the canonical tables, so a pair that exists only in the snapshot is not offered, a tombstoned copy is never offered again, and a second submission of an already-executed confirmation is rejected with a conflict before any provider call. Lists and reports served from the snapshot projection may still show the deleted copy until the backfill completes.

#### Scenario: Confirmation token follows the records
- **WHEN** either record of the pair is fetched again after the proposal was created
- **THEN** `snapshot_synced_at` (the newest canonical fetch time of the two records) differs and the submitted confirmation is rejected with a conflict before any provider call.

Detailed contract: The manifest key `snapshot_synced_at` is kept for contract stability; its value is the newest canonical fetch time of the pair. Persisted session links (`merged_into`) are not consulted for detection.

Evidence: `backend/activities/duplicate_inspection.py:DuplicateInspector.latest`, `backend/activities/canonical_sessions.py` (Wahoo/Garmin ride rule), `tests/test_sync_snapshot_storage.py:LegacyStateDuplicateTests`; `tests/test_activity_duplicates.py:WahooGarminDuplicateTests` (raw-row rule being ported), `tests/test_coach_tool_coverage.py:test_duplicate_inspection_returns_preview_without_deleting_provider_data`. Missing evidence (planned in this change): detection from canonical records with an absent snapshot, token change on refetch, and parity of sport and duration handling.

### Requirement: Garmin status compares against canonical Intervals rows
The system SHALL compute the Garmin status counts `activities` and `duplicate_activities_skipped` by comparing the raw Garmin payload activities with the canonical Intervals.icu activity rows only.

#### Scenario: Canonical source
- **WHEN** the Garmin public state is built
- **THEN** the Intervals.icu rows come from the canonical row port and the stored snapshot is not read for activities.

#### Scenario: No Intervals rows
- **WHEN** the canonical row port holds no Intervals.icu activities
- **THEN** no Garmin activity is skipped as a duplicate.

Evidence: `backend/sync/garmin_projection_service.py:GarminProjectionService._canonical_read`, `backend/activities/duplicates.py:filter_garmin_activities`; `tests/test_garmin_canonical_reads.py`, `tests/test_sync_garmin_projection_service.py:test_public_state_preserves_status_metrics_dedup_and_redacted_core_errors`. Missing evidence (planned in this change): construction without canonical sources is rejected and no snapshot activity fallback remains.
