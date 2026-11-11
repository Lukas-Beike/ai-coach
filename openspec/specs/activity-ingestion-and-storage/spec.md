# activity-ingestion-and-storage Specification

## Purpose

Describe durable provider activity ingestion, identity and session bundling, detail acquisition, pagination, corrections, and explicit deletion behavior. Garmin and Wahoo are the activity sources. Intervals.icu is an output target only (#1728): it is no longer read, and statements about Intervals.icu records describe copies stored by earlier releases. The one-time purge of release 2.0.0 ran in production and its code was removed (#1848): the current build contains no code that deletes stored Intervals.icu rows, and the production database holds none (athlete count-only check, 2026-11-10).

## Requirements

### Requirement: Provider reads preserve complete and partial outcomes
The system SHALL fetch Garmin through bounded provider collections with source outcomes, and Wahoo through paged workout summaries. Wahoo SHALL bound a run to 20 pages of 50 workouts and report truncation as partial. Missing optional Wahoo scopes or refused optional sources SHALL not invalidate fetched activities. Provider imports SHALL not upload workouts as a side effect of reading them.

#### Scenario: Truncated Wahoo collection
- **WHEN** workout pagination reaches its cap before establishing complete coverage
- **THEN** collected valid activities are persisted and the result is partial rather than claiming complete history.

#### Scenario: Optional source refusal
- **WHEN** workouts are readable but Wahoo refuses power zones with 403 or 404
- **THEN** workouts are imported and the optional source is reported skipped.

Evidence: `backend/providers/garmin.py:collect_garmin_data`, `backend/providers/wahoo_client.py:WahooClient`, `backend/sync/wahoo_sync.py:WahooSyncService._sync_locked`; `tests/test_wahoo_sync.py:test_truncated_fetch_reports_partial`, `tests/test_wahoo_runtime_acceptance.py:test_the_owner_never_writes_to_wahoo`.

### Requirement: Garmin transports per data family
The system SHALL read Garmin through the official read-only Personal API when its key is configured, and through the unofficial SDK login when that is connected. Every family the Personal API serves with the SDK's content SHALL use the Personal API when its key is configured. A family the configured transports do not serve SHALL be skipped as unsupported rather than reported as a failure. Both transports SHALL write the same records.

#### Scenario: Personal API key only
- **WHEN** only the Personal API key is configured
- **THEN** activities, activity details, sleep, HRV, daily summaries, resting heart rate, Body Battery, weight and heart-rate zones sync, and SDK-only families are absent without errors.

#### Scenario: SDK-only families
- **WHEN** a Personal API key is configured
- **THEN** readiness, training status, training load, load balance, VO2 max, FTP, lactate threshold, race predictions, endurance score, running tolerance, gear, activity splits and per-activity zone times stay on the SDK.

#### Scenario: Both transports
- **WHEN** the same Garmin activity or night was stored through one transport and is read through the other
- **THEN** it exists once, keyed by Garmin `activityId` or by the night's calendar date.

#### Scenario: SDK login unavailable with a Personal API key
- **WHEN** the SDK login fails or requires MFA while a Personal API key is configured
- **THEN** the Personal API families still sync and only the SDK-only families are skipped.

Detailed contract: The Personal API key SHALL be stored server-side like the other provider credentials and exchanged for a bearer token on demand; neither SHALL be logged, exported or returned.

Evidence: `backend/providers/garmin_personal.py:GarminTransportClient`, `backend/providers/garmin_personal.py:PERSONAL_METHODS`, `backend/providers/garmin_personal.py:wrap_daily_sleep`, `backend/sync/garmin_service.py:GarminRemoteReader._authenticated_client`; `tests/test_garmin_personal_transport.py`, `tests/test_garmin_personal_transport.py:test_heart_rate_zones_use_the_personal_api_when_a_key_exists`, `tests/test_garmin_personal_transport.py:test_sdk_only_families_stay_on_the_sdk_with_a_key`, `tests/test_garmin_health_mapping.py:test_personal_api_zones_map_like_the_sdk_zones`.

### Requirement: Garmin FIT detail through the Personal API
With the Personal API key, a Garmin activity detail fetch SHALL also download the original FIT file and decode it with the stdlib FIT decoder. Its full-resolution record streams and device laps SHALL replace the downsampled charts and the splits of that activity, which remain the fallback when the file yields no set of that kind.

#### Scenario: FIT detail through the Personal API
- **WHEN** a Garmin activity detail is fetched with the Personal API key and its FIT file decodes
- **THEN** the stored stream set has full resolution and the lap set holds the device laps from the file; an undecodable file keeps the charts and splits and reports one issue.

A FIT stream set SHALL also name what measured its heart rate (chest strap, optical, unknown) and power (power meter, trainer, estimated, unknown) and the external heart rate, power meter and trainer sensors of the recording, read from the file's device information; a serial number SHALL only be kept as a hash.

The stream set of a chest-strap FIT file that carries RR intervals (hrv messages) SHALL also hold the first threshold estimate computed from them (DFA-a1: artifact correction, smoothness-priors detrending, rolling 2-minute windows that never span a sensor dropout, regression of alpha1 on the window heart rate, the heart rate at alpha1 0.75) with its window count, artifact share and quality; the RR intervals themselves SHALL never be stored, logged, exported or sent to the Coach.

Evidence: `backend/providers/garmin_activity_detail_mapping.py:map_garmin_activity_detail`, `backend/providers/fit_file.py:fit_messages`, `backend/providers/fit_sensor_mapping.py:sensor_profile`, `backend/providers/fit_rr_mapping.py:rr_intervals_ms`, `backend/canonical/dfa_alpha1.py:first_threshold`; `tests/test_garmin_activity_detail_mapping.py:GarminFitPartTests`, `tests/test_fit_sensor_mapping.py`, `tests/test_fit_rr_mapping.py`, `tests/test_dfa_alpha1.py`.

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
The system SHALL infer missing-activity deletion only from a completely read Garmin or Wahoo activity list and only inside the safe inner days of the covered window. Edge days, incremental, failed, paused or truncated reads, and absent activity collections SHALL not delete activities merely because a response omits them. Deletion SHALL keep provider tombstone/state evidence through the one canonical delete path.

#### Scenario: Complete interior disappearance
- **WHEN** a complete eligible Garmin or Wahoo activity list omits an existing activity of that provider within the safe covered interior
- **THEN** the activity can be marked deleted through canonical reconciliation.

#### Scenario: Complete Garmin or Wahoo read
- **WHEN** a Garmin activity range (sync, historical chunk or targeted refresh; never a fixture) returns for every date window without failure, rate limit, capability pause or cancel, or a Wahoo listing is fully paged, consistent with its reported total and without unreadable rows, and every listed row carries a usable id
- **THEN** that read may delete, and the sync result reports the deleted count as a number only.

#### Scenario: Incomplete evidence of absence
- **WHEN** an activity is missing from an incremental or historical response, an edge day, a failed, paused or rate-limited Garmin read, or a truncated Wahoo listing
- **THEN** the system retains the stored activity rather than treating omission as deletion authorization.

Evidence: `backend/sync/canonical_ingest.py:fetch_deletion_window`, `backend/sync/canonical_ingest.py:ingest_garmin_payload`, `backend/sync/garmin.py:activity_deletion_window`, `backend/sync/wahoo_sync.py:WahooSyncService._sync_locked`; `tests/test_canonical_ingest.py:test_full_fetch_never_deletes_on_the_edge_days_of_its_window`, `tests/test_canonical_ingest.py:test_a_complete_activity_read_tombstones_a_deleted_activity`, `tests/test_canonical_ingest.py:test_a_failed_or_paused_activity_read_deletes_nothing`, `tests/test_canonical_ingest.py:test_a_row_without_an_activity_id_blocks_the_deletion`, `tests/test_garmin_snapshot_writer.py:ActivityWindowTests`, `tests/test_wahoo_sync.py:test_a_workout_on_the_edge_day_of_the_window_is_never_deleted`, `tests/test_wahoo_sync.py:test_a_complete_listing_tombstones_a_workout_deleted_in_wahoo`, `tests/test_wahoo_sync.py:test_a_truncated_unreadable_or_unidentified_listing_deletes_nothing`.

### Requirement: Deterministic provider-copy session identity
The system SHALL bundle supported provider copies into canonical sessions using deterministic start, sport-family, duration, distance, and recording-origin rules. The matching start window is 30 minutes, with duration tolerance at least 120 seconds or 10 percent and distance tolerance at least 500 metres or 10 percent under each implemented pairing rule. Wahoo leads a session, then Garmin, then a stored Intervals.icu copy (output only, ranked last); Wahoo-recorded rides can retain Garmin copies.

#### Scenario: Exact upstream reference
- **WHEN** a stored Intervals.icu copy with `source=GARMIN_CONNECT` or `WAHOO` names a stored upstream activity by `external_id`, even if trimmed, paused or shifted beyond the tolerances
- **THEN** this exact link is applied before the heuristic rules, which decide only the records left without one: both join one session with link kind `exact`, an earlier heuristic merge of the same pair is upgraded to `exact`, and an unknown upstream id leaves the copy to the heuristic rules.

#### Scenario: Several recordings of one ride
- **WHEN** compatible direct Wahoo and Garmin records, and any stored Intervals.icu copy, represent the same measured session
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

Detailed contract: Garmin elapsed-time fallback SHALL avoid assigning multiple separate walks to one already claimed session. Before linking, the copies of each live, unconfirmed session near the ingested dates are bundled again on their own, and a copy the rules no longer bundle with the session's own record is split off into its own active session (counted as `split` in the ingest counters); confirmed sessions are never split. The diagnostics report lists sessions with several active records of one provider and recording origin as `canonical_session_conflicts`, together with the link-kind counts of active sessions (a session that bundles no other session's record counts as `single`; deleting the last joined copy resets the stored kind to `single`). The external reference is stored in the record details, not in logs or Coach context. Local session references SHALL resolve to the appropriate provider identity at mutation/detail boundaries.

Evidence: `backend/activities/canonical_sessions.py:bundle_sessions`, `backend/activities/session_linking.py:link_activity_sessions`, `backend/activities/activity_reference.py:ActivityReferences`; `tests/test_canonical_sessions.py:test_order_is_deterministic_regardless_of_input_order`, `tests/test_canonical_sessions.py:test_garmin_record_joins_the_wahoo_session_through_a_garmin_copy`, `tests/test_canonical_sessions.py:OneToOneAssignmentTests`, `tests/test_canonical_sessions.py:ExactLinkTests`, `tests/test_session_linking.py:ExactLinkTests`, `tests/test_diagnostic_session_conflicts.py`, `tests/test_garmin_activity_detail_job.py:test_session_alias_resolves_to_the_garmin_record`.

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

### Requirement: Stream history backfill
The system SHALL re-fetch the original FIT files of past Garmin (Personal API) and Wahoo (workout list download links) activities that have no full-resolution stream set, newest first back to the history floor, and store their stream and device-lap sets exactly like the regular detail fetch, with the provider's provenance and the current summary hash. Manual and strength records SHALL be skipped, strength sets of a file SHALL never be stored, and nothing SHALL be written to a provider.

#### Scenario: Missing streams are filled once
- **WHEN** a live session's active Garmin or Wahoo record has no full-resolution stream set
- **THEN** its file is downloaded, paced, and stored; a repeated run finds no candidate and downloads nothing.

#### Scenario: A file is missing, empty or fails
- **WHEN** the provider holds no file, the file holds no sensor records, a download fails three runs or answers with a client error
- **THEN** only that record is counted and kept out of later runs, the rest of the batch goes on, and queuing a finished chain again without `end_date` lets failed records retry.

#### Scenario: Rate limit or rejected key
- **WHEN** the provider limits the requests or Garmin rejects the Personal API key
- **THEN** the job fails with the cursor unchanged and the files stored before stay; a rejected key shows the key hint, and Garmin without a Personal API key stays blocked with the state in diagnostics.

Detailed contract: Wahoo download links SHALL never be stored or logged. The backfill counts per provider (`candidates`, `with_streams`, `stored`, `no_file`, `no_streams`, `skipped_by_error`, `blocked`, `cursor`) SHALL appear in the diagnostic report without ids.

Evidence: `backend/sync/stream_backfill.py:StreamBackfillService.backfill`, `backend/providers/garmin_fit_history.py:collect_activity_fit_files`, `backend/sync/wahoo_stream_backfill.py:WahooStreamSource.fetch`, `backend/diagnostics/stream_backfill.py:summarize_stream_backfill`; `tests/test_stream_backfill.py`.

### Requirement: Local activity reads and pagination
The system SHALL read activity rows and sync metadata from one local read snapshot without refreshing providers, expose local activity references with feedback, and offer descending keyset pagination with versioned cursors. Page limits SHALL default to 100 and clamp to 1 through 250. Reads SHALL be independent of detail acquisition: a session whose detail failed or is missing stays listed.

#### Scenario: Next activity page
- **WHEN** the athlete requests a page after a valid cursor
- **THEN** results follow the stable descending local-time/id boundary and include a next cursor only when more rows remain.

#### Scenario: Detail failure or invalid cursor
- **WHEN** detail is unavailable or a cursor cannot be decoded
- **THEN** summary reading remains usable, no stored detail failure note marks a listed session, and an invalid or older-version cursor falls back to the first page.

#### Scenario: Guarded kv detail access
- **WHEN** the repository test suite runs
- **THEN** a guard test fails if any production module references the `activity_detail:` kv record prefix or the legacy detail record reader.

#### Scenario: Activity list freshness from canonical coverage
- **WHEN** the activity list is read and canonical coverage stores a current Garmin or Wahoo activity fetch time
- **THEN** `snapshot_synced_at` equals that time in the same read snapshot as the rows, independent of the stored snapshot's `synced_at`, of unrelated performance refreshes and of a duplicate deletion.

#### Scenario: No stored coverage
- **WHEN** no current Garmin or Wahoo activity fetch is stored
- **THEN** `snapshot_synced_at` is null, the list still renders, and no snapshot timestamp is substituted.

Detailed contract: The sync time reported with the activity list (`snapshot_synced_at`) SHALL be the activity sync time (the oldest current activity fetch of Garmin and Wahoo in the canonical provider coverage; a provider fetched more than 14 days before the newest one is left out; Intervals.icu never counts) and SHALL be null when none is stored. A Garmin write moves its activity fetch time only for a complete activity list read that reaches today; a truncated or row-skipping Wahoo listing keeps the last one. Activity freshness SHALL remain independent of unrelated performance refresh timestamps. Production activity, detail, report and calendar reads SHALL NOT read `activity_detail:<sha>` kv records, and no production module does. The key `snapshot_synced_at` keeps its name.

Evidence: `backend/activities/read_service.py:ActivityReadService.page`, `backend/activities/read_service.py:ActivityReadService.recent`, `backend/activities/sync_time.py:activities_synced_at`; `tests/test_activity_read_service.py:test_page_filters_orders_attaches_feedback_and_uses_cursor`, `tests/test_activity_read_service.py:test_activity_sync_time_comes_from_canonical_coverage`, `tests/test_activity_read_service.py:test_activity_sync_time_is_unknown_without_stored_coverage`, `tests/test_activity_detail_kv_guard.py:test_production_code_does_not_touch_kv_detail_records`.

### Requirement: Garmin status compares against canonical sessions
The system SHALL compute the Garmin status counts `activities` and `duplicate_activities_skipped` from the canonical sessions of the recent window only: a session with a Garmin Connect record counts as an activity, or as a skipped duplicate when a stored Intervals.icu record shares the session; a Garmin copy beside a Wahoo record alone stays an activity.

#### Scenario: Canonical source
- **WHEN** the Garmin public state is built
- **THEN** the counts come from the canonical activity summaries and neither the stored snapshot nor the raw Garmin view is read for activities.

#### Scenario: No Intervals rows
- **WHEN** no session bundles a Garmin record with an Intervals.icu record, as in a database without stored Intervals.icu rows
- **THEN** no Garmin activity is skipped as a duplicate.

Evidence: `backend/sync/garmin_projection_service.py:GarminProjectionService._canonical_read`, `backend/sync/garmin_projection_service.py:_garmin_sessions`; `tests/test_garmin_canonical_reads.py`, `tests/test_sync_garmin_projection_service.py:test_public_state_preserves_status_metrics_dedup_and_redacted_core_errors`, `tests/test_sync_garmin_projection_service.py:test_duplicates_are_counted_against_the_canonical_sessions_only`. `tests/test_sync_garmin_projection_service.py:test_the_projection_requires_the_canonical_sources`.

### Requirement: Athlete session corrections
The system SHALL let the athlete confirm a canonical session's bundle, split one provider copy into its own session, merge two live sessions, and delete an activity locally, from the activity detail view or through local Coach tools. Confirm, split and merge SHALL mark the resulting sessions athlete-confirmed. Each correction SHALL record a change-history receipt whose undo restores the touched session rows and change no provider record, provider data or feedback row.

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
- **THEN** its session and every merged copy are deleted, the survivor retains itself and its copies retain it, which marks an athlete delete, so no copy revives when a provider later deletes the primary copy or delivers the same copy again, nothing is deleted at a provider, and the receipt's undo restores the session.

#### Scenario: Copy arriving after an athlete delete
- **WHEN** a provider copy arrives for the first time, or was stored separately by an earlier build, and the bundling rules would join it to a session the athlete deleted
- **THEN** it is deleted with that session and retains it, so it never becomes a new live activity; undoing the athlete's delete brings it back into the restored session.

#### Scenario: Undo a correction
- **WHEN** the athlete undoes a correction's receipt while the touched sessions are unchanged since
- **THEN** the recorded session rows are restored; a later change to them makes the undo conflict instead.

#### Scenario: Feedback written before another copy arrives
- **WHEN** feedback is saved on a Garmin-only session and another provider's copy is linked later
- **THEN** the feedback resolves through either id because it stays bound to the session it was written for.

Detailed contract: the activity detail response carries `session_bundle` with the live session id, link kind, confirmation, the provider copies (`session_id`, provider label, recording origin, start, duration, and the provider's `native_type` with the terrain and assist it maps to) and the live sessions of the same local date as merge candidates. A correction touching more than 16 session rows is refused so its receipt stays restorable.

Evidence: `backend/activities/session_corrections.py:SessionCorrectionService`, `backend/http_api/feedback_post.py:FeedbackPostRoutes`, `public/activity-details.js:renderBundle`; `tests/test_session_corrections.py`, `tests/test_session_linking.py:test_a_session_the_athlete_deleted_stays_deleted_on_redelivery`, `tests/test_session_rebundle.py:test_confirmed_and_deleted_sessions_stay_untouched`.

