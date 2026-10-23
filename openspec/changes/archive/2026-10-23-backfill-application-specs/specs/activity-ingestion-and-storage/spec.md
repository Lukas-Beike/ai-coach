## Purpose

Describe durable provider activity ingestion, identity and session bundling, detail acquisition, pagination, corrections, and explicit deletion behavior.

## ADDED Requirements

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
The system SHALL fetch full-resolution Intervals detail only for a valid locally known activity, verify returned identity, normalize supported streams, laps, and zones, and store detail/analysis and canonical sets atomically. Automatic prefetch SHALL initially establish its floor from the ten newest activities, thereafter load new activities at or above that fixed floor, and limit each pass to 25 provider loads.

#### Scenario: Failed second detail request
- **WHEN** an activity's previous cached detail exists and its next provider stream request fails
- **THEN** the previous durable record remains readable and no half-written new detail replaces it.

#### Scenario: Old known activity requested
- **WHEN** the athlete requests a valid known activity before the prefetch floor
- **THEN** explicit loading can populate its detail even though automatic prefetch leaves it alone.

Detailed contract: Summary fingerprints and projection state SHALL prevent redundant loads and invalidate stale data/failure notes after corrections. Older activities SHALL remain available for explicit detail loading.

Evidence: `backend/sync/activity_details.py:ActivityDetailRefreshService.refresh`, `backend/sync/activity_details.py:INITIAL_PREFETCH_ACTIVITIES`, `backend/activities/detail_store.py:ActivityDetailStore`; `tests/test_activity_detail_refresh.py:test_first_run_loads_the_ten_newest_activities_once`, `tests/test_activity_detail_refresh.py:test_changed_summary_is_loaded_again`, `tests/test_activity_detail_refresh.py:test_failed_canonical_write_leaves_neither_record_nor_rows`.

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

Detailed contract: Activity freshness SHALL remain independent of unrelated performance refresh timestamps.

Evidence: `backend/activities/read_service.py:ActivityReadService.page`, `backend/activities/read_service.py:ActivityReadService._read`; `tests/test_activity_read_service.py:test_page_filters_orders_attaches_feedback_and_uses_cursor`, `tests/test_activity_read_service.py:test_page_keeps_activities_with_failed_details_and_names_the_error`, `tests/test_activity_read_service.py:test_activity_refresh_timestamp_is_independent_of_performance_refresh`.

### Requirement: Explicit duplicate deletion
The system SHALL delete a remotely stored duplicate only after validating the current detected Wahoo/Garmin duplicate pair and the explicit delete confirmation. The duplicate service SHALL retain the Wahoo activity, delete the selected Garmin copy through Intervals first, then update the local snapshot and canonical deletion state in one transaction and publish the resulting state change. A stale confirmation or remote-delete error SHALL not mutate local data.

#### Scenario: Confirmed current duplicate
- **WHEN** the submitted pair still matches the current duplicate and confirmation is valid
- **THEN** only the duplicate is remotely deleted and local canonical readers cease serving it after the local commit.

#### Scenario: Stale or rejected delete
- **WHEN** the submitted pair has changed or the provider delete fails
- **THEN** no local snapshot deletion or success event occurs.

Detailed contract: This flow does not promise distributed rollback if remote deletion succeeds and a later local write fails.

Evidence: `backend/activities/duplicates.py:validate_duplicate_delete`, `backend/activities/duplicate_service.py:DuplicateActivityService.delete`; `tests/test_activity_duplicate_service.py:test_stale_confirmation_has_no_side_effects`, `tests/test_activity_duplicate_service.py:test_remote_failure_does_not_mutate_snapshot_or_publish`, `tests/test_activity_duplicate_service.py:test_delete_tombstones_the_canonical_records_in_the_snapshot_transaction`.
