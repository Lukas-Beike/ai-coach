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

### Requirement: Garmin transports per data family
The system SHALL read Garmin through the official read-only Personal API when its key is configured, and through the unofficial SDK login when that is connected. Every family the Personal API serves with the SDK's content SHALL use the Personal API when its key is configured: activity lists, activity details, sleep, HRV, daily summaries, resting heart rate, Body Battery, weight and heart-rate zones. Families the Personal API does not serve (readiness, training status, training load, load balance, VO2 max, FTP, lactate threshold, race predictions, endurance score, running tolerance, gear, activity splits and per-activity zone times) SHALL stay on the SDK. A family the configured transports do not serve SHALL be skipped as unsupported rather than reported as a failure. The Personal API key SHALL be stored server-side like the other provider credentials and exchanged for a bearer token on demand; neither SHALL be logged, exported or returned. Both transports SHALL write the same records: activities keyed by Garmin `activityId`, sleep nights keyed by their calendar date. With the Personal API key, a Garmin activity detail fetch SHALL also download the original FIT file and decode it with the stdlib FIT decoder; its full-resolution record streams and device laps SHALL replace the downsampled charts and the splits of that activity, which remain the fallback when the file yields no set of that kind.

#### Scenario: Personal API key only
- **WHEN** only the Personal API key is configured
- **THEN** activities, sleep, HRV, daily summaries, resting heart rate, Body Battery, weight and heart-rate zones sync, and SDK-only families are absent without errors.

#### Scenario: Both transports
- **WHEN** the same Garmin activity or night was stored through one transport and is read through the other
- **THEN** it exists once.

#### Scenario: FIT detail through the Personal API
- **WHEN** a Garmin activity detail is fetched with the Personal API key and its FIT file decodes
- **THEN** the stored stream set has full resolution and the lap set holds the device laps from the file; an undecodable file keeps the charts and splits and reports one issue.

#### Scenario: SDK login unavailable with a Personal API key
- **WHEN** the SDK login fails or requires MFA while a Personal API key is configured
- **THEN** the Personal API families still sync and only the SDK-only families are skipped.

Evidence: `backend/providers/garmin_personal.py:GarminTransportClient`, `backend/providers/garmin_personal.py:wrap_daily_sleep`, `backend/sync/garmin_service.py:GarminRemoteReader._authenticated_client`, `backend/providers/garmin_activity_detail_mapping.py:map_garmin_activity_detail`; `tests/test_garmin_personal_transport.py`, `tests/test_garmin_personal_transport.py:test_heart_rate_zones_use_the_personal_api_when_a_key_exists`, `tests/test_garmin_personal_transport.py:test_sdk_only_families_stay_on_the_sdk_with_a_key`, `tests/test_garmin_health_mapping.py:test_personal_api_zones_map_like_the_sdk_zones`, `tests/test_garmin_activity_detail_mapping.py:GarminFitPartTests`.

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
The system SHALL infer missing-activity deletion only from a completely read Intervals, Garmin or Wahoo activity list and only inside the safe inner days of the covered window. Edge days, historical Intervals chunks, incremental, failed, paused or truncated reads, and absent activity collections SHALL not delete activities merely because a response omits them. Deletion SHALL keep provider tombstone/state evidence through the one canonical delete path.

#### Scenario: Complete interior disappearance
- **WHEN** a complete eligible Intervals, Garmin or Wahoo activity list omits an existing activity of that provider within the safe covered interior
- **THEN** the activity can be marked deleted through canonical reconciliation.

#### Scenario: Complete Garmin or Wahoo read
- **WHEN** a Garmin activity range (sync, historical chunk or targeted refresh; never a fixture) returns for every date window without failure, rate limit, capability pause or cancel, or a Wahoo listing is fully paged, consistent with its reported total and without unreadable rows, and every listed row carries a usable id
- **THEN** that read may delete, and the sync result reports the deleted count as a number only.

#### Scenario: Incomplete evidence of absence
- **WHEN** an activity is missing from an incremental or historical response, an edge day, a failed, paused or rate-limited Garmin read, or a truncated Wahoo listing
- **THEN** the system retains the stored activity rather than treating omission as deletion authorization.

Evidence: `backend/sync/canonical_ingest.py:intervals_deletion_window`, `backend/sync/canonical_ingest.py:ingest_intervals_snapshot`, `backend/sync/canonical_ingest.py:ingest_garmin_payload`, `backend/sync/garmin.py:activity_deletion_window`, `backend/sync/wahoo_sync.py:WahooSyncService._sync_locked`; `tests/test_canonical_ingest.py:test_full_fetch_never_deletes_on_the_edge_days_of_its_window`, `tests/test_canonical_ingest.py:test_historical_fetch_never_deletes`, `tests/test_canonical_ingest.py:test_a_complete_activity_read_tombstones_a_deleted_activity`, `tests/test_canonical_ingest.py:test_a_failed_or_paused_activity_read_deletes_nothing`, `tests/test_canonical_ingest.py:test_a_row_without_an_activity_id_blocks_the_deletion`, `tests/test_garmin_snapshot_writer.py:ActivityWindowTests`, `tests/test_wahoo_sync.py:test_a_complete_listing_tombstones_a_workout_deleted_in_wahoo`, `tests/test_wahoo_sync.py:test_a_truncated_unreadable_or_unidentified_listing_deletes_nothing`.

### Requirement: Deterministic provider-copy session identity
The system SHALL bundle supported provider copies into canonical sessions using deterministic start, sport-family, duration, distance, and recording-origin rules. The matching start window is 30 minutes, with duration tolerance at least 120 seconds or 10 percent and distance tolerance at least 500 metres or 10 percent under each implemented pairing rule. Intervals.icu is output only and ranks last: Wahoo leads a session, then Garmin; Wahoo-recorded rides can retain Garmin copies.

#### Scenario: Exact upstream reference
- **WHEN** an Intervals copy with `source=GARMIN_CONNECT` or `WAHOO` names a stored upstream activity by `external_id`, even if trimmed, paused or shifted beyond the tolerances
- **THEN** this exact link is applied before the heuristic rules, which decide only the records left without one: both join one session with link kind `exact`, an earlier heuristic merge of the same pair is upgraded to `exact`, and an unknown upstream id leaves the copy to the heuristic rules.

#### Scenario: Several recordings of one ride
- **WHEN** compatible Intervals, direct Wahoo, and Garmin records represent the same measured session
- **THEN** each input belongs to exactly one canonical session with deterministic primary and duplicate-link metadata; the Wahoo record leads, else the Garmin record, else the Intervals.icu record.

#### Scenario: Ambiguous nearby activity
- **WHEN** candidates lack enough comparable data or conflict with matching tolerances
- **THEN** they remain separate instead of being merged merely because their timestamps are close.

#### Scenario: A copy no longer matches its session
- **WHEN** a provider edit or a mapper change moves a copy of an unconfirmed session outside the matching rules
- **THEN** the next ingest or reprojection of that date splits it off into its own active session, while a confirmed session keeps all its copies.

#### Scenario: Two separate sessions close together
- **WHEN** two recordings from each of two providers start within 30 minutes of each other and each could match either copy
- **THEN** each pairing rule assigns one to one: a session takes at most one active record per provider and recording origin, each pass joins as many records as possible and, among those assignments, takes the lowest total pair cost (mean of the start gap and the measurement gaps, each relative to its tolerance), a merge that would put two records of one provider and origin in one persisted session is refused, and equal costs fall back to start, provider and activity id.

Detailed contract: Garmin elapsed-time fallback SHALL avoid assigning multiple separate walks to one already claimed session. Before linking, the copies of each live, unconfirmed session near the ingested dates are bundled again on their own, and a copy the rules no longer bundle with the session's own record is split off into its own active session (counted as `split` in the ingest counters); confirmed sessions are never split. The diagnostics report lists sessions with several active records of one provider and recording origin as `canonical_session_conflicts`, together with exact references whose records stay in different sessions (`exact_link_mismatches`, never re-merged automatically) and the link-kind counts of active sessions. The external reference is stored in the record details, not in logs or Coach context. Local session references SHALL resolve to the appropriate provider identity at mutation/detail boundaries.

Evidence: `backend/activities/canonical_sessions.py:bundle_sessions`, `backend/activities/session_linking.py:link_activity_sessions`, `backend/activities/activity_reference.py:ActivityReferences`; `tests/test_canonical_sessions.py:test_order_is_deterministic_regardless_of_input_order`, `tests/test_canonical_sessions.py:test_garmin_record_joins_the_wahoo_session_through_a_garmin_copy`, `tests/test_canonical_sessions.py:OneToOneAssignmentTests`, `tests/test_canonical_sessions.py:ExactLinkTests`, `tests/test_session_linking.py:ExactLinkTests`, `tests/test_diagnostic_session_conflicts.py`, `tests/test_garmin_activity_detail_job.py:test_session_alias_resolves_to_the_garmin_record`.

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
- **THEN** the canonical detail sets are written (no session analysis, which the canonical stage owns, #1685), the failure note of that activity is deleted in the same transaction, and no `activity_detail:<sha>` kv row is created or updated.

#### Scenario: Canonical write fails
- **WHEN** the canonical detail write raises inside the refresh transaction
- **THEN** no canonical set or failure-note deletion is committed.

#### Scenario: Prefetch settledness
- **WHEN** prefetch decides whether an activity still needs loading
- **THEN** it uses only the summary fingerprints stored with canonical detail sets and analysis payloads, plus failure notes for the same fingerprint. A remaining kv detail record does not mark an activity settled.

#### Scenario: Stored analysis untouched by a reload
- **WHEN** a session already has a stored analysis row with a `target_snapshot` and its Intervals.icu detail is reloaded
- **THEN** the row and its frozen snapshot stay unchanged; targets are frozen only by the canonical session analysis stage.

Detailed contract: Summary fingerprints SHALL prevent redundant loads and invalidate stale data/failure notes after corrections. Failure notes and the prefetch floor remain small kv keys. Older activities SHALL remain available for explicit detail loading. The refresh use case SHALL require a canonical detail writer. The refresh SHALL NOT compute or write a session analysis, calendar profile or target snapshot.

Evidence: `backend/sync/activity_details.py:ActivityDetailRefreshService.refresh`, `backend/sync/activity_details.py:INITIAL_PREFETCH_ACTIVITIES`, `backend/activities/detail_store.py:ActivityDetailStore`, `backend/db/activity_detail_fingerprints.py:intervals_detail_fingerprints`; `tests/test_activity_detail_refresh.py:test_first_run_loads_the_ten_newest_activities_once`, `tests/test_activity_detail_refresh.py:test_changed_summary_is_loaded_again`, `tests/test_activity_detail_refresh.py:test_failed_canonical_write_commits_nothing`. `tests/test_activity_detail_refresh.py:test_refresh_writes_canonical_rows_without_a_kv_record`, `tests/test_activity_detail_refresh.py:test_refresh_leaves_a_stored_analysis_untouched`, `tests/test_activity_detail_refresh.py:test_leftover_kv_record_does_not_settle_prefetch`, `tests/test_activity_detail_refresh.py:test_unstored_write_fails_and_keeps_the_failure_note`.

### Requirement: Garmin detail acquisition and recovery
The system SHALL fetch Garmin detail kinds independently for locally known active nonmanual Garmin records, persist returned valid sets without erasing omitted kinds, and report partial outcomes when only some kinds arrive.

#### Scenario: Partially returned detail
- **WHEN** Garmin supplies streams but fails or skips another requested kind
- **THEN** valid arrived sets can be stored with partial status and existing omitted sets are retained.

#### Scenario: Rate limit with no stored part
- **WHEN** Garmin rate-limits before any part can be stored
- **THEN** the batch pauses without consuming an ordinary per-summary failed attempt and can resume after the cooldown.

#### Scenario: Executed strength sets
- **WHEN** a Garmin strength activity's details are fetched
- **THEN** its exercise sets are requested as their own capability (SDK only) and stored as one strength set list; Garmin's exercise sets, which carry the athlete's Connect corrections, win over the FIT file's set messages, which stay the fallback; non-strength activities never request exercise sets.

Detailed contract: A strength set list SHALL come from one source only, never merged set by set; a later fetch without exercise sets SHALL keep stored exercise sets rather than replace them with the file's set messages, and strength sets SHALL never mark a session's analysis stale. Each set keeps its type (active or rest), the FIT exercise category (unknown codes as `other`), the provider exercise code only as an upper-case identifier, repetitions, weight in kg (absent when no external load was reported, never 0), duration, start offset and the planned workout step it ran. Automatic detail backfill SHALL work newest first in bounded batches of ten, retain summary/version-aware empty and retry state, pause on rate limiting, bound retries for a failing summary, and continue to older candidates when one activity exhausts its retries. Cancellation SHALL stop between activities; token cleanup SHALL still run.

Evidence: `backend/sync/garmin_activity_details.py:GarminActivityDetailService.refresh`, `backend/sync/garmin_activity_details.py:GarminActivityDetailService.backfill`, `backend/providers/fit_activity_detail_mapping.py:_strength_set_set`, `backend/providers/garmin_activity_detail_mapping.py:_strength_set_set`; `tests/test_strength_sets.py`, `tests/test_garmin_activity_detail_job.py:test_partial_payload_writes_returned_kinds_and_keeps_stored_laps`, `tests/test_garmin_activity_detail_backfill.py:test_batch_is_limited_to_ten_and_reports_remaining`, `tests/test_garmin_activity_detail_backfill.py:test_failing_activity_stops_holding_back_older_ones`.

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
- **WHEN** the activity list is read and canonical coverage stores a current Garmin or Wahoo activity fetch time
- **THEN** `snapshot_synced_at` equals that time in the same read snapshot as the rows, independent of the stored snapshot's `synced_at`, of unrelated performance refreshes and of a duplicate deletion.

#### Scenario: No stored coverage
- **WHEN** no current Garmin or Wahoo activity fetch is stored
- **THEN** `snapshot_synced_at` is null, the list still renders, and no snapshot timestamp is substituted.

Detailed contract: The sync time reported with the activity list (`snapshot_synced_at`) SHALL be the activity sync time (the oldest current activity fetch of Garmin and Wahoo in the canonical provider coverage; a provider fetched more than 14 days before the newest one is left out, Intervals.icu copies never count) and SHALL be null when none is stored. A Garmin write moves its activity fetch time only for a complete activity list read that reaches today; a truncated or row-skipping Wahoo listing keeps the last one. Activity freshness SHALL remain independent of unrelated performance refresh timestamps. Production activity, detail, report and calendar reads SHALL NOT read `activity_detail:<sha>` kv records; only the backfill and retirement maintenance modules may read them. The key `snapshot_synced_at` keeps its name.

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

#### Scenario: Deleted copy stays deleted across the next sync
- **WHEN** a duplicate is deleted while the stored snapshot still carries its activity sections (a row the mapper rejects, or a snapshot stored before the backfill finished) and the next incremental Intervals.icu sync runs
- **THEN** the merge base leaves out every activity whose canonical record is tombstoned, so the merged payload does not re-add the deleted copy, its record and session stay deleted, no pair is offered again and a repeated confirmation is rejected with a conflict before any provider call. The snapshot itself is still not rewritten by the delete; only the merge base is filtered. An activity that the provider returns in a later fetch is ingested from that fetch as before, and a full-window sync still tombstones activities the provider no longer returns.

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
- **WHEN** populated databases built from the frozen fixtures for schema v16 through v18 with seeded kv detail records are upgraded and the backfill and retirement stages run
- **THEN** every seeded detail remains readable as `activity_detail.v1`, verified kv records are retired, and unverifiable ones remain stored.

#### Scenario: Legacy target basis
- **WHEN** a preserved kv detail record uses the former FTP key in its frozen target basis
- **THEN** canonical backfill stores the equivalent neutral basis, and retirement compares normalized values without discarding conflicting data.

#### Scenario: Backup, restore and privacy export
- **WHEN** a database is backed up, restored or privacy-exported after retirement
- **THEN** the canonical detail sets, stream channels, laps, zone times and analysis payloads are present, and retired kv records are absent from the exported application state.

Evidence: `backend/sync/activity_detail_retirement.py:ActivityDetailRetirement`, `backend/db/activity_detail_store.py:refill_lap_metrics`, `backend/sync/canonical_backfill_assembly.py`; `tests/test_activity_detail_retirement.py:test_proven_record_is_deleted_and_other_keys_are_kept`, `tests/test_activity_detail_retirement.py:test_missing_lap_speed_is_refilled_before_the_record_is_retired`, `tests/test_activity_detail_retirement.py:test_lap_metric_that_differs`, `tests/test_activity_detail_retirement.py:test_failed_batch_rolls_back_refills_and_deletions`, `tests/test_activity_detail_retirement.py:test_restart_resumes_from_the_cursor_and_repeats_nothing`, `tests/test_activity_detail_retirement_upgrade.py:test_released_schemas_upgrade_and_retire_proven_records` (the SQLCipher variant is skipped without SQLCipher), `tests/test_activity_detail_retirement_backup.py:test_restored_backup_serves_the_same_document`, `tests/test_activity_detail_retirement_backup.py:test_privacy_export_holds_the_retired_detail_in_the_canonical_files`. Related existing behavior: `backend/sync/activity_detail_backfill.py:ActivityDetailBackfill`, `backend/sync/canonical_backfill_worker.py`.

Additional evidence: `tests/test_activity_detail_canonical.py::test_legacy_target_basis_is_normalized_without_changing_source`; `tests/test_activity_detail_retirement.py::test_legacy_target_basis_is_compared_after_normalization`; `tests/test_activity_detail_retirement.py::test_conflicting_legacy_target_basis_is_not_retired`.

### Requirement: Canonical duplicate pair detection
The system SHALL detect and inspect the newest Wahoo/Garmin duplicate ride pair from canonical active Intervals.icu activity records, keeping the Wahoo-recorded activity and offering the Garmin-recorded copy for deletion, without reading the Intervals.icu snapshot. A pair SHALL contain the newest Intervals.icu activity.

#### Scenario: Current pair
- **WHEN** an active Wahoo-recorded and an active Garmin-recorded Intervals.icu ride start within 30 minutes and their durations and distances agree within the duplicate tolerances
- **THEN** inspection returns `canonical_id` and `duplicate_id` (the Intervals.icu activity ids), names, local start, moving time, distance and `snapshot_synced_at`, with Wahoo kept, even when no snapshot exists.

#### Scenario: Newer unrelated or tombstoned activity
- **WHEN** a newer unrelated Intervals.icu activity exists, a record of the pair is deleted, or an id is missing or equal
- **THEN** inspection returns no pair.

#### Scenario: Intervals.icu ingest off
- **WHEN** the Intervals.icu ingest switch is off
- **THEN** inspection returns no pair before reading any record, so no proposal, Coach delete or delete submission can reach Intervals.icu.

#### Scenario: Legacy-state selector
- **WHEN** the canonical read selector still serves the snapshot projection (before the first completed backfill)
- **THEN** no pair is offered at all: inspection returns none, so a Coach proposal cannot be created and `inspect_activity_duplicates` reports none, and a delete submission is rejected with a conflict before any provider call. This holds even for a copy tombstoned earlier whose record a later sync revived from the unchanged snapshot, and a pair that exists only in the snapshot is never offered. Once the tables serve reads, inspection and the delete validation read only the canonical tables, so a tombstoned copy is not offered again and a repeated confirmation is rejected with a conflict. Lists and reports served from the snapshot projection may still show a deleted copy until the backfill completes.

#### Scenario: Confirmation token follows the records
- **WHEN** either record of the pair is fetched again after the proposal was created
- **THEN** `snapshot_synced_at` (the newest canonical fetch time of the two records) differs and the submitted confirmation is rejected with a conflict before any provider call.

Detailed contract: The manifest key `snapshot_synced_at` is kept for contract stability; its value is the newest canonical fetch time of the pair. Persisted session links (`merged_into`) are not consulted for detection.

Evidence: `backend/activities/duplicate_inspection.py:DuplicateInspector.latest`, `backend/activities/canonical_sessions.py` (Wahoo/Garmin ride rule), `tests/test_sync_snapshot_storage.py:LegacyStateDuplicateTests`; `tests/test_activity_duplicates.py:WahooGarminDuplicateTests` (raw-row rule being ported), `tests/test_coach_tool_coverage.py:test_duplicate_inspection_returns_preview_without_deleting_provider_data`. Missing evidence (planned in this change): detection from canonical records with an absent snapshot, token change on refetch, and parity of sport and duration handling.

### Requirement: Garmin status compares against canonical Intervals rows
The system SHALL compute the Garmin status counts `activities` and `duplicate_activities_skipped` from the canonical sessions of the recent window only: a session with a Garmin Connect record counts as an activity, or as a skipped duplicate when an Intervals.icu record shares the session; a Garmin copy beside a Wahoo record alone stays an activity.

#### Scenario: Canonical source
- **WHEN** the Garmin public state is built
- **THEN** the counts come from the canonical activity summaries and neither the stored snapshot nor the raw Garmin view is read for activities.

#### Scenario: No Intervals rows
- **WHEN** no session bundles a Garmin record with an Intervals.icu record
- **THEN** no Garmin activity is skipped as a duplicate.

Evidence: `backend/sync/garmin_projection_service.py:GarminProjectionService._canonical_read`, `backend/sync/garmin_projection_service.py:_garmin_sessions`; `tests/test_garmin_canonical_reads.py`, `tests/test_sync_garmin_projection_service.py:test_public_state_preserves_status_metrics_dedup_and_redacted_core_errors`, `tests/test_sync_garmin_projection_service.py:test_duplicates_are_counted_against_the_canonical_sessions_only`. Missing evidence (planned in this change): construction without canonical sources is rejected and no snapshot activity fallback remains.

### Requirement: Athlete session corrections
The system SHALL let the athlete confirm a canonical session's bundle, split one provider copy into its own session, merge two live sessions, and delete an activity locally, from the activity detail view or through local Coach tools. Each correction SHALL mark the resulting sessions athlete-confirmed, record a change-history receipt whose undo restores the touched session rows, and change no provider record, provider data or feedback row.

#### Scenario: Confirm a bundle
- **WHEN** the athlete confirms a session that bundles several provider copies
- **THEN** it is stored as athlete-confirmed with link kind `confirmed`, and later session linking never merges or splits it.

#### Scenario: Split a provider copy
- **WHEN** the athlete splits one provider copy off a bundle
- **THEN** that copy becomes its own active, athlete-confirmed session, the remaining copies stay bundled under their oldest session, later syncs do not merge them again, and feedback stays with the session it was written for.

#### Scenario: Merge two sessions
- **WHEN** the athlete merges two live sessions of the same local date that hold no two active records of one provider and recording origin
- **THEN** the younger becomes an alias of the older one, which is athlete-confirmed with link kind `confirmed`; a merge across dates or one that would join two records of one provider and origin is refused with a conflict.

#### Scenario: Delete an activity locally
- **WHEN** the athlete deletes an activity in the app after confirming the prompt
- **THEN** its session and every merged copy are deleted and athlete-confirmed, no copy revives when a provider later deletes the primary copy or delivers a copy again, nothing is deleted at a provider, and the receipt's undo restores the session.

#### Scenario: Undo a correction
- **WHEN** the athlete undoes a correction's receipt while the touched sessions are unchanged since
- **THEN** the recorded session rows are restored; a later change to them makes the undo conflict instead.

#### Scenario: Feedback written before another copy arrives
- **WHEN** feedback is saved on a Garmin-only session and the Intervals.icu copy is linked later
- **THEN** the feedback resolves through either id because it stays bound to the session it was written for.

Detailed contract: the activity detail response carries `session_bundle` with the live session id, link kind, confirmation, the provider copies (`session_id`, provider label, recording origin, start, duration, and the provider's `native_type` with the terrain and assist it maps to) and the live sessions of the same local date as merge candidates. A correction touching more than 16 session rows is refused so its receipt stays restorable.

Evidence: `backend/activities/session_corrections.py:SessionCorrectionService`, `backend/http_api/feedback_post.py:FeedbackPostRoutes`, `public/activity-details.js:renderBundle`; `tests/test_session_corrections.py`.
