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

Detailed contract: The Personal API key SHALL be stored server-side like the other provider credentials and exchanged for a bearer token on demand; neither SHALL be logged, exported or returned. Every Personal API path and SDK call of each family, with its arguments, timeout and error mapping, is in `docs/provider-endpoints.md`; the app sets no timeout or retry of its own around an SDK call, and one failing family does not stop the others.

Evidence: `backend/providers/garmin_personal.py:GarminTransportClient`, `backend/providers/garmin_personal.py:PERSONAL_METHODS`, `backend/providers/garmin_personal.py:wrap_daily_sleep`, `backend/sync/garmin_service.py:GarminRemoteReader._authenticated_client`; `tests/test_garmin_personal_transport.py`, `tests/test_garmin_personal_transport.py:test_heart_rate_zones_use_the_personal_api_when_a_key_exists`, `tests/test_garmin_personal_transport.py:test_sdk_only_families_stay_on_the_sdk_with_a_key`, `tests/test_garmin_health_mapping.py:test_personal_api_zones_map_like_the_sdk_zones`.

### Requirement: Garmin FIT detail through the Personal API
With the Personal API key, a Garmin activity detail fetch SHALL also download the original FIT file and decode it with the stdlib FIT decoder. Its full-resolution record streams and device laps SHALL replace the downsampled charts and the splits of that activity, which remain the fallback when the file yields no set of that kind.

#### Scenario: FIT detail through the Personal API
- **WHEN** a Garmin activity detail is fetched with the Personal API key and its FIT file decodes
- **THEN** the stored stream set has full resolution and the lap set holds the device laps from the file; an undecodable file keeps the charts and splits and reports one issue.

A FIT stream set SHALL also name what measured its heart rate (chest strap, optical, unknown) and power (power meter, trainer, estimated, unknown) and the external heart rate, power meter and trainer sensors of the recording, read from the file's device information; a serial number SHALL only be kept as a hash.

The stream set of a chest-strap FIT file that carries RR intervals (hrv messages) SHALL also hold the first threshold estimate computed from them (DFA-a1: artifact correction, smoothness-priors detrending, rolling 2-minute windows that never span a sensor dropout, regression of alpha1 on the window heart rate, the heart rate at alpha1 0.75) with its window count, artifact share and quality; the RR intervals themselves SHALL never be stored, logged, exported or sent to the Coach. Parameters, procedure, quality rule and stop rules are in `docs/performance-methods/m10-dfa-alpha1-first-threshold.md`.

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

#### Scenario: Size of the safe interior
- **WHEN** a complete activity read covers the days `start` to `end`
- **THEN** only stored activities whose local date lies from `start + 1 day` to `end - 1 day` can be marked deleted; a read of two days or less, such as the hourly read of yesterday and today, deletes nothing.

#### Scenario: Unmappable but listed activity
- **WHEN** the provider lists an activity whose row cannot be mapped
- **THEN** its id still counts as present and its stored copy is not deleted.

#### Scenario: Other providers
- **WHEN** one provider's complete read applies its deletion window
- **THEN** records of other providers are never touched.

Evidence: `backend/sync/canonical_ingest.py:fetch_deletion_window`, `backend/sync/canonical_ingest.py:ingest_garmin_payload`, `backend/sync/garmin.py:activity_deletion_window`, `backend/sync/wahoo_sync.py:WahooSyncService._sync_locked`; `tests/test_canonical_ingest.py:test_full_fetch_never_deletes_on_the_edge_days_of_its_window`, `tests/test_canonical_ingest.py:test_a_complete_activity_read_tombstones_a_deleted_activity`, `tests/test_canonical_ingest.py:test_a_failed_or_paused_activity_read_deletes_nothing`, `tests/test_canonical_ingest.py:test_a_row_without_an_activity_id_blocks_the_deletion`, `tests/test_garmin_snapshot_writer.py:ActivityWindowTests`, `tests/test_wahoo_sync.py:test_a_workout_on_the_edge_day_of_the_window_is_never_deleted`, `tests/test_wahoo_sync.py:test_a_complete_listing_tombstones_a_workout_deleted_in_wahoo`, `tests/test_wahoo_sync.py:test_a_truncated_unreadable_or_unidentified_listing_deletes_nothing`.

Added evidence:
- `backend/db/canonical_store.py:mark_missing_deleted`
- `backend/providers/canonical_plans.py:_activity_batch`
- `tests/test_canonical_ingest.py:test_one_or_zero_days_leave_an_empty_window`
- `tests/test_canonical_ingest.py:test_partial_fetch_excludes_both_edge_days`
- `tests/test_canonical_store.py:test_other_providers_are_never_touched`

### Requirement: Deterministic provider-copy session identity
The system SHALL bundle supported provider copies into canonical sessions using deterministic start, sport-family, duration, distance, and recording-origin rules. The matching start window is 30 minutes, with duration tolerance at least 120 seconds or 10 percent and distance tolerance at least 500 metres or 10 percent under each implemented pairing rule. Wahoo leads a session, then Garmin; Wahoo rides can retain a Garmin watch recording and a relayed Garmin copy.

#### Scenario: Several recordings of one ride
- **WHEN** compatible direct Wahoo and Garmin records represent the same measured session
- **THEN** each input belongs to exactly one canonical session with deterministic primary and duplicate-link metadata; the Wahoo record leads, else the Garmin record.

#### Scenario: Stored Intervals.icu activity copy
- **WHEN** a stored Intervals.icu activity record exists (Intervals.icu is output only; the copies were purged, #1848)
- **THEN** session linking leaves it out (it joins no session, no linking write or split touches it), no canonical activity reader serves it, so no list, detail, summary or calculation reads it, and it stays stored, exported and purgeable (#2148).

#### Scenario: Ambiguous nearby activity
- **WHEN** candidates lack enough comparable data or conflict with matching tolerances
- **THEN** they remain separate instead of being merged merely because their timestamps are close.

#### Scenario: A copy no longer matches its session
- **WHEN** a provider edit or a mapper change moves a copy of an unconfirmed session outside the matching rules
- **THEN** the next ingest or reprojection of that date splits it off into its own active session, while a confirmed session keeps all its copies.

#### Scenario: Two separate sessions close together
- **WHEN** two recordings from each of two providers start within 30 minutes of each other and each could match either copy
- **THEN** each pairing rule assigns one to one: a session takes at most one active record per provider and recording origin, each pass joins as many records as possible and, among those assignments, takes the lowest total pair cost (mean of the start gap and the measurement gaps, each relative to its tolerance), a merge that would put two records of one provider and origin in one persisted session is refused, and equal costs fall back to start, provider and activity id.

#### Scenario: Garmin copy of a Wahoo record without a corroborating distance
- **WHEN** a Garmin record and a Wahoo record do not both carry a positive distance
- **THEN** they bundle only when their starts are at most 10 minutes apart; with two positive distances that agree within max(500 m, 10 % of the larger) the 30-minute window applies, and two positive distances that disagree never bundle.

#### Scenario: Sport and duration of a Garmin and Wahoo pair
- **WHEN** a Garmin record is compared with a Wahoo record
- **THEN** their canonical sports must be equal or one must be `other`, and some duration pair must agree within max(120 s, 10 % of the larger value): activity duration or moving duration on either side, or elapsed against elapsed; zero and missing durations are not compared.

#### Scenario: Watch recording and relayed copy
- **WHEN** Garmin Connect holds a watch recording and a relayed Wahoo copy of one Wahoo ride
- **THEN** both join the Wahoo session, because a session takes one Garmin record per recording origin.

#### Scenario: Starts around a daylight-saving change
- **WHEN** two records start around a daylight-saving change of the athlete zone
- **THEN** their starts are compared as wall-clock times in the athlete zone, not as instants, and the 30-minute window is inclusive.

Detailed contract: Garmin elapsed-time fallback SHALL avoid assigning multiple separate walks to one already claimed session. Before linking, the copies of each live, unconfirmed session near the ingested dates are bundled again on their own, and a copy the rules no longer bundle with the session's own record is split off into its own active session (counted as `split` in the ingest counters); confirmed sessions are never split. The diagnostics report lists sessions with several active records of one provider and recording origin as `canonical_session_conflicts`, together with the link-kind counts of active sessions (a session that bundles no other session's record counts as `single`; deleting the last joined copy resets the stored kind to `single`). A stored external reference stays in the record details and is not read by linking; it never reaches logs or Coach context. Local session references SHALL resolve to the appropriate provider identity at mutation/detail boundaries.

Evidence: `backend/activities/canonical_sessions.py:bundle_sessions`, `backend/activities/session_linking.py:link_activity_sessions`, `backend/activities/activity_reference.py:ActivityReferences`; `tests/test_canonical_sessions.py:test_order_is_deterministic_regardless_of_input_order`, `tests/test_canonical_sessions.py:test_garmin_and_wahoo_records_bundle_as_recorded`, `tests/test_canonical_sessions.py:OneToOneAssignmentTests`, `tests/test_session_linking.py:IgnoredIntervalsCopyTests`, `tests/test_diagnostic_session_conflicts.py`, `tests/test_garmin_activity_detail_job.py:test_session_alias_resolves_to_the_garmin_record`.

Added evidence:
- `backend/activities/canonical_sessions.py:_assign_duplicates`
- `backend/activities/canonical_sessions.py:_provider_copy_cost`
- `backend/activities/canonical_sessions.py:_WallWindow`
- `tests/test_canonical_sessions.py:test_copies_compare_wall_clocks_across_the_autumn_overlap`
- `tests/test_canonical_sessions.py:test_copies_compare_wall_clocks_across_the_spring_gap`
- `tests/test_canonical_wahoo_sessions.py:test_a_distance_disagreement_blocks_copies_of_any_sport`
- `tests/test_canonical_wahoo_sessions.py:test_a_watch_recording_and_a_relayed_copy_both_join_the_wahoo_session`
- `tests/test_canonical_wahoo_sessions.py:test_copies_of_other_sports_bundle_on_duration`
- `tests/test_session_linking.py:test_a_run_and_a_yoga_session_stay_two_sessions`
- `tests/test_session_linking.py:test_an_indoor_ride_without_garmin_distance_is_one_session`

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

#### Scenario: Time budget and host
- **WHEN** a Wahoo detail import pass runs
- **THEN** it starts no further download once 120 seconds have passed, and it downloads only from `cdn.wahooligan.com` over HTTPS without an Authorization header.

#### Scenario: Which workouts are downloaded
- **WHEN** a workout has an active record and a download link
- **THEN** it is skipped when a stored set carries the current summary hash and the current FIT mapper version, when its file was marked empty for that hash, or after 3 failed attempts for that hash; duplicate rows of one workout download once.

Detailed contract: download failures are classified `untrusted_url`, `rate_limited`, `rejected`, `too_large` or `unavailable`; the state is the key-value record `wahoo_activity_detail_state`, pruned to the workouts of the current listing. Signed links SHALL be absent from stored raw rows, errors, and logs. Detail import failure SHALL not retroactively fail a successful summary import.

Evidence: `backend/sync/wahoo_activity_details.py:WahooActivityDetailImport.import_details`, `backend/providers/wahoo_fit_download.py:download_wahoo_fit`, `backend/providers/fit_file.py:fit_messages`, `backend/providers/fit_activity_detail_mapping.py:map_fit_activity_detail`; `tests/test_wahoo_activity_details.py:test_at_most_ten_downloads_run_per_sync`, `tests/test_wahoo_activity_details.py:test_download_link_is_absent_from_storage_and_logs`, `tests/test_wahoo_sync.py:test_a_failing_detail_import_keeps_the_sync_ok`.

Added evidence:
- `backend/providers/wahoo_fit_download.py:WAHOO_FIT_HOSTS`
- `tests/test_wahoo_activity_details.py:test_duplicate_rows_are_downloaded_once`
- `tests/test_wahoo_activity_details.py:test_state_is_pruned_to_the_current_workouts`
- `tests/test_wahoo_activity_details.py:test_time_budget_stops_the_run_before_the_next_download`
- `tests/test_wahoo_fit_download.py`

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

#### Scenario: Batch size and pacing
- **WHEN** a stream backfill job runs
- **THEN** Garmin reads at most 30 files, 2 seconds apart; Wahoo reads at most 100 files, 1 second apart (the first without delay), after listing the workouts back to the batch's oldest session (at most 200 pages of 50); the whole last day of a batch is included even beyond the limit.

#### Scenario: Truncated Wahoo listing
- **WHEN** the Wahoo listing is truncated
- **THEN** a workout missing from it is not marked as having no file.

#### Scenario: Record changes while the batch runs
- **WHEN** a record is deleted while its file downloads
- **THEN** nothing is written for it.

Detailed contract: the state is the key-value record `stream_backfill_state:<provider>`; each downloaded file is stored in its own transaction, so a later failure loses nothing; a fixture-mode provider neither reads nor moves the cursor. Wahoo download links SHALL never be stored or logged. The backfill counts per provider (`candidates`, `with_streams`, `stored`, `no_file`, `no_streams`, `skipped_by_error`, `blocked`, `cursor`) SHALL appear in the diagnostic report without ids.

Evidence: `backend/sync/stream_backfill.py:StreamBackfillService.backfill`, `backend/providers/garmin_fit_history.py:collect_activity_fit_files`, `backend/sync/wahoo_stream_backfill.py:WahooStreamSource.fetch`, `backend/diagnostics/stream_backfill.py:summarize_stream_backfill`; `tests/test_stream_backfill.py`.

Added evidence:
- `backend/sync/garmin_stream_backfill.py:STREAM_BATCH_LIMIT`
- `backend/sync/stream_backfill.py:StreamSelection.batch`
- `backend/sync/wahoo_stream_backfill.py:DOWNLOAD_DELAY_SECONDS`
- `backend/sync/wahoo_stream_backfill.py:WAHOO_BATCH_LIMIT`
- `tests/test_stream_backfill.py:test_a_batch_takes_whole_days_newest_first_up_to_the_end_day`
- `tests/test_stream_backfill.py:test_a_record_deleted_while_the_batch_ran_is_not_written`
- `tests/test_stream_backfill.py:test_a_truncated_listing_does_not_vouch_that_a_workout_is_gone`
- `tests/test_stream_backfill.py:test_downloads_are_paced_but_the_first_one_is_not_delayed`

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

#### Scenario: Day filter of the activity list
- **WHEN** `GET /api/activities` carries `days`
- **THEN** only sessions from `today - (days - 1)` on are listed; the value is clamped to 1 through 3650, `-1` or an unreadable value lists the whole history, and the response repeats the effective `days` and `limit`. The request and response contract is in `docs/api-routes.md`.

#### Scenario: Recent sessions for the Coach
- **WHEN** the Coach reads the recent sessions
- **THEN** at most 500 are returned (default 250), newest first, with the same sync time and feedback attachment.

Detailed contract: The sync time reported with the activity list (`snapshot_synced_at`) SHALL be the activity sync time (the oldest current activity fetch of Garmin and Wahoo in the canonical provider coverage; a provider fetched more than 14 days before the newest one is left out; Intervals.icu never counts) and SHALL be null when none is stored. A Garmin write moves its activity fetch time only for a complete activity list read that reaches today; a truncated or row-skipping Wahoo listing keeps the last one. Activity freshness SHALL remain independent of unrelated performance refresh timestamps. Production activity, detail, report and calendar reads SHALL NOT read `activity_detail:<sha>` kv records, and no production module does. The key `snapshot_synced_at` keeps its name.

Evidence: `backend/activities/read_service.py:ActivityReadService.page`, `backend/activities/read_service.py:ActivityReadService.recent`, `backend/activities/sync_time.py:activities_synced_at`; `tests/test_activity_read_service.py:test_page_filters_orders_attaches_feedback_and_uses_cursor`, `tests/test_activity_read_service.py:test_activity_sync_time_comes_from_canonical_coverage`, `tests/test_activity_read_service.py:test_activity_sync_time_is_unknown_without_stored_coverage`, `tests/test_activity_detail_kv_guard.py:test_production_code_does_not_touch_kv_detail_records`.

Added evidence:
- `tests/test_activity_read_service.py:test_page_clamps_oversized_days_instead_of_overflowing`
- `tests/test_activity_read_service.py:test_recent_filters_by_explicit_today_without_mutating_snapshot`

### Requirement: Garmin status compares against canonical sessions
The system SHALL compute the Garmin status count `activities` from the canonical sessions of the recent window only: each session with a Garmin Connect record counts once, also when its Wahoo recording leads it.

#### Scenario: Canonical source
- **WHEN** the Garmin public state is built
- **THEN** the count comes from the canonical activity summaries and neither the stored snapshot nor the raw Garmin view is read for activities.

#### Scenario: Window of the Garmin status counts
- **WHEN** the Garmin public state counts activities
- **THEN** it counts the canonical sessions whose local date lies in the last 90 days including today.

Evidence: `backend/sync/garmin_projection_service.py:GarminProjectionService._canonical_read`, `backend/sync/garmin_projection_service.py:_garmin_sessions`; `tests/test_garmin_canonical_reads.py`, `tests/test_sync_garmin_projection_service.py:test_public_state_preserves_status_metrics_dedup_and_redacted_core_errors`, `tests/test_sync_garmin_projection_service.py:test_activities_count_the_canonical_sessions_with_a_garmin_record`. `tests/test_sync_garmin_projection_service.py:test_the_projection_requires_the_canonical_sources`.

Added evidence:
- `backend/sync/garmin.py:RECENT_VIEW_DAYS`

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

Detailed contract: the activity detail response carries `session_bundle` with the live session id, link kind, confirmation, the provider copies (`session_id`, provider label, recording origin, start, duration, and the provider's `native_type` with the terrain and assist it maps to) and the live sessions of the same local date as merge candidates. A correction touching more than 16 session rows is refused so its receipt stays restorable. The route's request, response and error texts are in `docs/api-routes.md`. Every correction publishes the provider state event `sessions_corrected` and requests a local load pass; its receipt has the entity `activity_session`. An undo that would restore a session as active that no longer owns an active record is refused with 409.

Evidence: `backend/activities/session_corrections.py:SessionCorrectionService`, `backend/http_api/feedback_post.py:FeedbackPostRoutes`, `public/activity-details.js:renderBundle`; `tests/test_session_corrections.py`, `tests/test_session_linking.py:test_a_session_the_athlete_deleted_stays_deleted_on_redelivery`, `tests/test_session_rebundle.py:test_confirmed_and_deleted_sessions_stay_untouched`.

Added evidence:
- `tests/test_session_corrections.py:test_correction_and_its_undo_request_a_local_load_pass`
- `tests/test_session_corrections.py:test_undo_is_refused_once_the_provider_deleted_the_primary`
- `tests/test_session_corrections.py:test_undoing_the_delete_brings_a_later_copy_back`

### Requirement: Activity record lifecycle
A provider activity SHALL be identified by provider and provider activity id and belong to the session `act_<32 hex>` created with it. Its record state SHALL be `active`, `deleted` (the provider removed it or it was withdrawn) or `invalid` (the current mapper no longer emits it). An ingest that delivers a deleted record again SHALL make it active again; a re-projection SHALL never revive a deleted record or a record of a deleted session.

#### Scenario: Unchanged repeat import
- **WHEN** an activity arrives again with identical projected values
- **THEN** only its fetch time is refreshed and the outcome is `unchanged`.

#### Scenario: Provider-deleted activity is delivered again
- **WHEN** an ingest delivers an activity whose record and session a provider deletion tombstoned
- **THEN** the record is active again; its session returns as an alias of the live survivor it retained, unless that survivor already holds an active record of the same provider and recording origin, in which case the session becomes active on its own; a session the athlete deleted stays deleted.

#### Scenario: Re-projection meets a tombstone
- **WHEN** a re-projection maps a raw record whose activity is deleted or whose session is deleted
- **THEN** the row is left untouched (`preserved`).

#### Scenario: Mapper no longer emits an activity
- **WHEN** a re-projection of a raw record, or an unusable stored payload, emits no activity for the record it owns
- **THEN** the record becomes `invalid`, its session keeps its state, readers stop serving it, and a later mapper version that emits it again makes it active with the same session id.

Evidence:
- `backend/db/canonical_store.py:_revival_survivor`
- `backend/db/canonical_store.py:reproject_activity_record`
- `backend/db/canonical_store.py:retire_unemitted_activity`
- `backend/db/canonical_store.py:upsert_activity_record`
- `tests/test_canonical_backfill.py:test_an_unusable_payload_marks_the_owned_activity_invalid`
- `tests/test_canonical_backfill.py:test_reprojection_keeps_a_deleted_activity_and_its_session_deleted`
- `tests/test_canonical_store.py:test_deleted_activity_seen_again_is_reactivated_with_its_session`
- `tests/test_canonical_store.py:test_identical_resync_refreshes_the_fetch_time`
- `tests/test_session_linking.py:test_a_confirmed_survivor_deleted_and_redelivered_stays_one_session`
- `tests/test_session_linking.py:test_a_session_the_athlete_deleted_stays_deleted_on_redelivery`

### Requirement: Provider deletion keeps the bundle and its athlete data resolvable
A provider deletion SHALL mark the activity record and its raw record `deleted`, and the session `deleted` only when the record is that session's primary record. A deleted alias SHALL keep its survivor in `merged_into_retained`. When a surviving session is deleted, its oldest alias (by creation time, then id) SHALL become the active survivor, inherit the athlete confirmation, and take over the other aliases and every retained reference.

#### Scenario: Primary copy of a bundle is deleted at the provider
- **WHEN** the provider removes the primary copy of a session that has aliases
- **THEN** the oldest alias is the live session, the other aliases merge into it, and feedback written for the deleted session resolves to it.

#### Scenario: Last joined copy is deleted
- **WHEN** the last other copy of a session is deleted
- **THEN** the remaining session's stored link kind falls back to `single`, while `confirmed` is kept.

#### Scenario: Athlete-deleted session
- **WHEN** a provider deletion reaches a session the athlete already deleted
- **THEN** the session row is left as it is and hands over no aliases.

Evidence:
- `backend/db/canonical_store.py:_delete_activity`
- `backend/db/canonical_store.py:_repoint_aliases`
- `backend/db/canonical_store.py:reset_unbundled_link_kinds`
- `tests/test_canonical_store.py:test_deleting_a_merged_alias_clears_its_merge_link`
- `tests/test_canonical_store.py:test_deleting_the_last_merged_alias_leaves_the_survivor_single`
- `tests/test_feedback_session_identity.py`
- `tests/test_session_linking.py:test_deleting_the_surviving_activity_leaves_the_alias_readable`

### Requirement: Persisted session linking
After an ingest or a re-projection wrote activities, the system SHALL bundle the linkable records whose local date lies within one day of the written dates and persist each match by making the younger session (creation time, then id) a `duplicate` alias of the older one. Records keep their session id and sessions keep their primary provider. Linking SHALL be idempotent and SHALL run after deletions, with the split of non-matching copies first.

#### Scenario: Which records are linkable
- **WHEN** records are selected for linking
- **THEN** only active records of sessions that are active or aliases and not athlete-confirmed take part, plus those of sessions the athlete deleted, which only delete a new copy with them; hidden, provider-deleted and confirmed sessions are never merged or reopened, and a stored row with a provider or vocabulary value this build does not know is skipped without failing the ingest.

#### Scenario: Link kind strength
- **WHEN** a merge or a later match names a link kind
- **THEN** the survivor keeps the strongest of `single` < `heuristic` < `exact` < `confirmed`; a kind is never downgraded by linking.

#### Scenario: Alias chains
- **WHEN** a session id is resolved through its merges
- **THEN** the chain follows `merged_into` (for a deleted alias the retained survivor) for at most 64 hops and stops at a cycle.

Detailed contract: the ingest counters are `written`, `updated`, `unchanged`, `skipped_invalid`, `deleted`, `linked`, `split` and `retired`.

Evidence:
- `backend/activities/session_linking.py:_Sessions.merge`
- `backend/activities/session_linking.py:link_activity_sessions`
- `backend/db/canonical_store.py:effective_session_ids`
- `backend/db/canonical_store.py:linkable_activity_rows`
- `backend/sync/canonical_ingest.py:CanonicalIngestCounters`
- `tests/test_session_linking.py:test_a_confirmed_link_kind_is_never_downgraded`
- `tests/test_session_linking.py:test_a_ride_on_the_next_local_day_links_across_midnight`
- `tests/test_session_linking.py:test_a_stored_row_of_an_unknown_provider_is_skipped`
- `tests/test_session_linking.py:test_linking_directly_a_second_time_is_a_no_op`
- `tests/test_session_linking.py:test_the_older_session_survives_whatever_the_ingest_order`

### Requirement: Garmin detail refresh and backfill outcomes
An on-demand Garmin detail refresh SHALL accept a local session id or a Garmin activity id matching `[A-Za-z0-9_-]{1,200}` and answer with `status` `completed`, `partial`, `unchanged` or `skipped` (`reason: manual_activity`), the Garmin `activity_id` and the stored `kinds`. The automatic backfill SHALL cover active non-manual records of the last 90 days, at most 10 per sync, and SHALL return counts only (`status`, `fetched`, `empty`, `remaining`).

#### Scenario: Refresh errors
- **WHEN** the activity is unknown locally, Garmin is not configured (or runs in fixture mode), or every requested part failed or was malformed
- **THEN** the answers are 404 `activity_details_not_found`, 503 `not_configured` and 502 `activity_details_unavailable`; stored sets are kept.

#### Scenario: Refresh cooldown
- **WHEN** every stored set of the activity matches the current summary hash and the newest was fetched less than 10 minutes ago
- **THEN** the refresh answers `unchanged` without a provider call; a changed summary bypasses the cooldown.

#### Scenario: Backfill retries and marks
- **WHEN** a backfill fetch is incomplete (a part failed, was rate limited or malformed)
- **THEN** the activity is fetched again on later syncs, at most 3 times per summary hash, then passed over; an activity that returned nothing without a failure is marked empty for that summary hash; a part skipped while paused costs no attempt; the retry state commits with the detail rows.

#### Scenario: Backfill pause
- **WHEN** Garmin rate-limits a backfill
- **THEN** arrived parts are stored, the batch stops with status `rate_limited` and the backfill is paused for 24 hours; only the `activity_details` capability gates the backfill, a paused splits, zone, exercise-set or FIT part pauses only itself.

Detailed contract: backfill statuses are `completed`, `paused`, `rate_limited`, `failed`, `cancelled` and `not_configured`. A record qualifies when it has no detail set, only sets whose summary hash differs from the current raw record, or a set stored by an older Garmin detail mapper version. The state is the key-value record `garmin_activity_detail_backfill` (`paused_until`, empty marks, retries), pruned to the 90-day window. A record deleted or merged during the provider call is not written.

Evidence:
- `backend/db/activity_detail_store.py:activity_detail_backfill_candidates`
- `backend/sync/garmin_activity_details.py:GarminActivityDetailService.backfill`
- `backend/sync/garmin_activity_details.py:GarminActivityDetailService.refresh`
- `backend/sync/garmin_activity_details.py:_within_cooldown`
- `tests/test_garmin_activity_detail_backfill.py:test_empty_activity_is_marked_and_not_refetched_for_the_same_summary`
- `tests/test_garmin_activity_detail_backfill.py:test_partial_fetch_retries_are_bounded_per_summary`
- `tests/test_garmin_activity_detail_backfill.py:test_paused_sdk_only_parts_do_not_pause_the_backfill`
- `tests/test_garmin_activity_detail_job.py:test_changed_summary_bypasses_the_cooldown`
- `tests/test_garmin_activity_detail_job.py:test_cooldown_skips_reader_until_it_expires`
- `tests/test_garmin_activity_detail_job.py:test_every_part_failing_gives_502_and_keeps_stored_sets`
- `tests/test_garmin_activity_detail_job.py:test_unconfigured_garmin_gives_503_without_reader_call`

### Requirement: Detail set storage contract
Each provider activity SHALL keep at most one detail set per kind (`streams`, `laps`, `heart_rate_zones`, `power_zones`, `strength_sets`), stored with the mapper version, the summary hash it was fetched for, its fetch time and a content hash. Writing equal content SHALL only refresh the bookkeeping. Sets of tombstoned records and deleted sessions SHALL be kept but not served. A stored set that no longer validates SHALL be skipped and logged without content.

#### Scenario: Limits of a set
- **WHEN** a mapper builds a detail set
- **THEN** a stream set has at most 172,800 points on a strictly increasing time axis spanning at most 172,800 s and at least one channel besides time; a lap set 1 to 200 laps with consecutive indexes; a zone distribution 1 to 20 buckets; a strength set list 1 to 500 sets (repetitions up to 1,000, weight above 0 up to 1,000 kg, step index up to 999); a stream set names at most 16 sensors.

#### Scenario: Unusable stream points
- **WHEN** a channel point is no number, not finite or outside the channel bound
- **THEN** it is stored as a gap and counted, never clamped.

#### Scenario: Stored channel
- **WHEN** a channel is stored and read
- **THEN** it is a zlib-compressed little-endian float64 series with gaps as NaN, at most 4 MiB compressed; a blob whose size or valid count disagrees with its declared point count is rejected.

#### Scenario: Offsets
- **WHEN** laps, sets and stream points are stored
- **THEN** their times are seconds from the start of that provider recording; no absolute or local time is stored in a set.

Evidence:
- `backend/canonical/activity_detail.py:MAX_STREAM_POINTS`
- `backend/canonical/activity_detail.py:clean_series`
- `backend/db/activity_detail_store.py:MAX_CHANNEL_BLOB_BYTES`
- `backend/db/activity_detail_store.py:replace_detail_set`
- `tests/test_activity_detail_store.py:test_decode_rejects_mismatched_corrupt_or_oversized_data`
- `tests/test_activity_detail_store.py:test_equal_content_only_refreshes_fetch_bookkeeping`
- `tests/test_activity_detail_store.py:test_stream_set_requires_a_strict_complete_time_axis`
- `tests/test_activity_detail_store.py:test_tombstoned_records_and_sessions_hide_details_without_deleting`
- `tests/test_activity_detail_store.py:test_unreadable_stored_set_is_skipped`

### Requirement: Detail mapper upgrades fetch the source again
Activity files and detail responses SHALL NOT be stored raw, so a higher detail mapper version SHALL be applied by fetching again: Garmin records of the 90-day detail window become backfill candidates, Wahoo workouts of a sync become download candidates, and the Wahoo stream backfill SHALL re-download once the files of sessions of the last 365 days whose full stream set an older mapper stored. Older sessions keep the sets they have.

#### Scenario: Wahoo replay after a mapper upgrade
- **WHEN** the FIT detail mapper version is higher than the one the finished Wahoo stream chain last replayed
- **THEN** the first finished Wahoo refresh clears the chain's cursor and its skipped and failed records once for that version, and the chain reads the outdated sessions of the last 365 days again.

#### Scenario: Replay download fails or is empty
- **WHEN** the re-download fails or the file holds no sensor records
- **THEN** the stored streams stay unchanged.

#### Scenario: Chain still walking
- **WHEN** the chain has not reached the history floor
- **THEN** it is not rearmed until it has.

Detailed contract: Garmin has no replay window; a Garmin detail set older than 90 days keeps the projection of the mapper that stored it.

Evidence:
- `backend/db/activity_detail_store.py:activity_detail_backfill_candidates`
- `backend/sync/stream_backfill.py:StreamBackfillService.rearm`
- `backend/sync/wahoo_activity_details.py:WahooActivityDetailImport`
- `backend/sync/wahoo_stream_backfill.py:WAHOO_REPLAY_DAYS`
- `tests/test_garmin_activity_detail_backfill.py:test_sets_from_an_older_mapper_version_are_candidates_again`
- `tests/test_stream_backfill.py:test_a_failed_download_keeps_the_old_streams`
- `tests/test_stream_backfill.py:test_a_session_older_than_the_window_keeps_its_streams`
- `tests/test_stream_backfill.py:test_rearm_leaves_a_walking_chain_until_it_reaches_the_floor`
- `tests/test_stream_backfill.py:test_rearm_restarts_a_finished_chain_once_per_mapper_version`

### Requirement: Hardened FIT decoding
FIT bytes SHALL be treated as untrusted. The decoder SHALL verify the header and file CRCs, reject an unsupported signature or header size, a truncated file or record and an unknown base type, bound a file to 200,000 data messages, decode invalid sentinels to absent values, and fail only with a value error. It SHALL NOT import application domains.

#### Scenario: Enhanced fields
- **WHEN** a record or lap carries an enhanced speed or altitude field with a usable value
- **THEN** it is used; an invalid sentinel falls back to the base field.

#### Scenario: Compressed timestamps
- **WHEN** a record uses a compressed timestamp header
- **THEN** its time is restored from the last full timestamp and its fields are read.

#### Scenario: RR intervals
- **WHEN** a file carries `hrv` messages (78)
- **THEN** at most 150,000 intervals are read as gap-free segments; an invalid slot between valid ones, or a file clock more than 10 seconds ahead of the intervals, starts a new segment.

Detailed contract: the byte-level decoder rules, the record and lap fields and the sensor roles are in `docs/canonical-field-map.md`.

Evidence:
- `backend/providers/fit_file.py:fit_messages`
- `backend/providers/fit_rr_mapping.py:rr_intervals_ms`
- `tests/test_fit_file.py:test_compressed_timestamps_restore_the_last_full_timestamp`
- `tests/test_fit_file.py:test_decoder_module_has_no_application_imports`
- `tests/test_fit_file.py:test_enhanced_field_sentinel_falls_back_to_base_end_to_end`
- `tests/test_fit_file.py:test_header_crc_mismatch_is_rejected`
- `tests/test_fit_file.py:test_message_count_is_bounded`
- `tests/test_fit_file.py:test_random_and_mutated_inputs_raise_only_value_error`
- `tests/test_fit_file.py:test_unknown_base_type_is_rejected`
- `tests/test_fit_rr_mapping.py`

### Requirement: One-time session rebundle
A follow-up stage of the canonical backfill worker SHALL run the regular session linking once per rebundle version (currently 2) on every local date that holds a linkable Garmin and a linkable Wahoo record on that day or a neighbouring day, in one transaction. It SHALL never split a session and never touch hidden or athlete-confirmed sessions; a copy of a session the athlete deleted is deleted with it.

#### Scenario: Second start
- **WHEN** the stage already completed for the current version
- **THEN** it does nothing.

#### Scenario: Failure
- **WHEN** the pass fails
- **THEN** no data changes, the state is `failed`, and the next worker pass retries it.

Detailed contract: the state is the key-value record `session_rebundle_state` (`version`, `status`, `completed_at`, `counts.days`, `counts.linked`); the log event `session_rebundle_completed` and the diagnostics entry `session_rebundle` carry counts only.

Evidence:
- `backend/db/canonical_store.py:linkable_dates_with_providers`
- `backend/sync/session_rebundle.py:SessionRebundle.run_batch`
- `tests/test_session_rebundle.py:test_a_failure_leaves_the_data_unchanged_and_is_retried`
- `tests/test_session_rebundle.py:test_a_second_startup_does_nothing`
- `tests/test_session_rebundle.py:test_the_log_line_carries_counts_only`

### Requirement: Raw provider record storage
The system SHALL store each provider row as one raw record identified by provider, record kind (`activity`, `health`, `power_zones`, `user`) and source record id, as sanitized canonical JSON (sorted keys) with its SHA-256, the mapper version it was projected with, its fetch time and its day. A record whose hash, mapped version, state and day are unchanged SHALL NOT be rewritten.

#### Scenario: Usable identifiers
- **WHEN** a row's id is a boolean, empty, longer than 256 characters or absent
- **THEN** the row has no usable id, is counted as invalid, and blocks deletion for that read; the per-provider id rules are in `docs/canonical-field-map.md`.

#### Scenario: Deleted record seen again
- **WHEN** a deleted raw record is delivered again
- **THEN** it is active again with the new payload.

#### Scenario: Payload without a fetch time
- **WHEN** a payload carries no usable fetch time
- **THEN** no canonical row is written, so no row is stamped with an invented time.

#### Scenario: Key of a stored Garmin element
- **WHEN** a Garmin section that is a list is stored
- **THEN** each element is one raw record `<section>/<key>`, the key being its first non-empty `id`, `activityId`, `gearUUID`, `calendarDate`, `summaryDate`, `date` or `startTime` (at most 160 characters), else `~` and the first 32 hex characters of the SHA-256 of its JSON with sorted keys; a key that repeats in the list gets `#1`, `#2` and so on; any other value is one item named by the section alone.

#### Scenario: Day of an element
- **WHEN** an element is stored
- **THEN** its day is the first ten characters of the first of `calendarDate`, `summaryDate`, `date`, `startTimeLocal`, `startTimeGMT` and `startTime` whose first ten characters are a valid date.

Detailed contract: the key of an element decides the raw record id and through it the owner of observations and domain rows, so another key rule would store every element a second time over an existing database.

Evidence:
- `backend/canonical/section_items.py:record_day`
- `backend/canonical/section_items.py:split_section`
- `backend/db/canonical_store.py:upsert_provider_record`
- `backend/providers/canonical_plans.py:_row_id`
- `backend/sync/canonical_ingest.py:ingest_garmin_payload`
- `tests/test_canonical_ingest.py:test_payload_without_a_sync_time_writes_nothing`
- `tests/test_canonical_ingest.py:test_secrets_are_not_stored_in_raw_records`
- `tests/test_canonical_store.py:test_a_deleted_record_seen_again_is_reactivated`
- `tests/test_canonical_store.py:test_same_payload_and_version_is_unchanged_and_not_rewritten`
- `tests/test_garmin_store.py:test_duplicate_keys_stay_separate_elements`
- `tests/test_garmin_store.py:test_identity_prefers_the_provider_id_and_falls_back_to_a_digest`
