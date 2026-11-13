# sync-jobs-and-scheduling Specification

## Purpose

Describe the implemented durable synchronization control plane, provider-specific refresh cadence, bounded historical work, and observable recovery behavior.

## Requirements

### Requirement: Registered provider job contracts
The system SHALL validate provider and job type together using the configured registry, accept only the fields supported by that operation, and reject invalid periods, dates, flags, identifiers, and approval manifests before persisting work.

#### Scenario: Supported manual import
- **WHEN** an authenticated athlete submits a supported refresh request
- **THEN** the system persists the normalized provider, operation, bounded payload, requester, and item operations and returns a job identity.

#### Scenario: Unsupported operation
- **WHEN** a request assigns historical backfill to Wahoo or supplies an unsupported field or non-boolean force flag
- **THEN** validation rejects it before creating a job.

#### Scenario: Stored job outlives a limit
- **WHEN** a stored refresh job carries more days than the provider maximum of today
- **THEN** it still runs, because the provider maximum applies at enqueue only; a stored job accepts at most 3660 days.

Detailed contract: Intervals supports plan push, competition push, and nutrition sync; Garmin supports refresh, activity details, plan push, historical backfill, wellness backfill, and stream backfill; Wahoo supports refresh, plan push, and stream backfill; weather and calendar support refresh. Nutrition approval semantics belong to the nutrition capability.

Detailed contract (payload bounds): a payload is an object of at most 32 fields. A refresh takes only the fields of its provider (`days`, `force`, `reason`, `end_date`): `days` is -1 (whole history) or 1 to the provider maximum (90 for Garmin and Wahoo), `force` is a boolean, `end_date` an ISO day, `reason` is clipped to 80 characters; the backfill types also take `empty_chunks` from 0 to 100. `activity_details` takes exactly `activity_id` (1 to 200 letters, digits, `_` or `-`). `plan_push` takes 1 to 28 `entries`, each a 36-character local id with either a 64-hex `expected_payload_hash` or `remove: true` (Garmin and Wahoo only), plus an optional boolean `repair`. `competition_push` requires an `approval_manifest` of at most 1000 `{type: competition|tombstone, id, sha256}` entries. `nutrition_sync` takes a `date`, a `pending_limit` of 1 to 31, or an `approval_manifest` of at most 31 days. A job has 1 to 1000 items with unique keys of at most 160 characters.

Evidence: `backend/sync/jobs.py:normalize_sync_job_request`, `backend/sync/jobs.py:validate_job_request`, `backend/sync/jobs.py:SyncJobStore._normalize_operations`, `backend/sync/provider_table.py:DEFAULT_PROVIDER_DESCRIPTORS`; `tests/test_sync_jobs.py:test_every_provider_and_job_type_pair_matches_the_live_validator`, `tests/test_sync_jobs.py:test_boolean_fields_require_actual_booleans`, `tests/test_sync_jobs.py:test_plan_push_rejects_provider_fields_count_uuid_hash_and_booleans`, `tests/test_sync_jobs.py:test_enforced_period_limit_follows_the_provider_descriptor`.

### Requirement: Sync job requests over HTTP
The system SHALL queue a job from an authenticated, CSRF-protected request only after checking that its provider is set up, with requester `user`. The request and answer fields, status codes and error texts of the job routes, the manual provider routes and the sync status are the contract of `docs/api-routes.md`, generated from the route handlers.

#### Scenario: Provider not set up
- **WHEN** a job or manual refresh is requested for Intervals.icu without a key, Garmin without a Personal API key or a usable login, or Wahoo that is not connected
- **THEN** the answer is 409 `not_configured` with the provider's setup text before any job is stored and before the Garmin route stores a sync period; weather and calendar are not checked here and are only skipped by the scheduler.

#### Scenario: Plan push items
- **WHEN** a `plan_push` job is requested
- **THEN** the job stores one item per distinct `library_workout_id`, keyed by that id and carrying the entry's expected payload hash.

#### Scenario: Nutrition export is not a route
- **WHEN** a request over this route asks for a `nutrition_sync` job
- **THEN** it is refused with 400 `invalid_job_request`, because only an approved Coach card exports nutrition.

#### Scenario: No retry route
- **WHEN** a job failed or ended partial
- **THEN** it is retried only by the explicit `action=retry` of the queue, which the Coach's authorised retry uses; no HTTP route starts it.

Evidence: `backend/http_api/sync_commands.py:SyncCommandEndpoint`, `backend/http_api/sync_commands.py:_plan_push_item_operations`, `backend/sync/queue.py:SyncJobQueueService.resolve`, `backend/sync/conflict_commands.py:SyncConflictCommandService.retry_job`; `tests/test_sync_job_admission.py:test_unconfigured_providers_get_409_before_any_job_is_stored`, `tests/test_sync_wiring_matrix.py:test_an_unconfigured_provider_gets_409_before_any_job_is_stored`, `tests/test_sync_wiring_matrix.py:test_an_unconfigured_provider_gets_409_before_its_manual_route_stores_a_job`, `tests/test_http_sync_commands.py:test_manual_period_validation_precedes_queue_mutation`, `tests/test_http_sync_commands.py:test_a_ui_plan_push_stores_one_job_item_per_entry`, `tests/test_api_routes_doc.py`.

### Requirement: Durable jobs and duplicate suppression
The system SHALL persist jobs and ordered items atomically, expose bounded progress and safe errors, and atomically coalesce active refresh and backfill jobs requested by `scheduler`, `startup` or `connection`. Coalescing SHALL preserve the existing job identity and avoid a second created event or worker wake. Requests by `user`, `coach` or `backfill` (the continuation of a chain, which carries its own cursor) always create their own job.

#### Scenario: Concurrent automatic enqueue
- **WHEN** concurrent eligible automatic requests target the same provider and operation while one job is queued or running
- **THEN** callers receive the same active job rather than parallel duplicate jobs.

#### Scenario: Atomic creation fails
- **WHEN** storing an item or validating its bounded operation list fails
- **THEN** the request creates no partially populated job.

Evidence: `backend/sync/jobs.py:SyncJobStore.enqueue`, `backend/sync/queue.py:SyncJobQueueService.enqueue`; `tests/test_sync_jobs.py:test_concurrent_automatic_enqueues_create_exactly_one_job`, `tests/test_sync_jobs.py:test_automatic_refresh_and_backfill_requests_coalesce_atomically`.

### Requirement: Startup scheduling
The system SHALL schedule configured startup refreshes in calendar, Garmin, weather, Wahoo order, skip an already active refresh, and enqueue historical backfill only for providers declaring it. Intervals.icu SHALL never be scheduled. Weather startup requests are forced. Garmin and Wahoo default sync periods are 84 days; ordinary selectable periods are limited to 90 days, with the separate all-history sentinel interpreted by each provider owner.

#### Scenario: Configured startup
- **WHEN** startup scheduling runs with configured and connected providers
- **THEN** refresh work uses registry order, provider policy payloads, and requester `startup`.

#### Scenario: Restart with active work
- **WHEN** a provider already has an active refresh or historical-backfill job
- **THEN** startup does not duplicate that operation; disabled or unconnected providers are skipped.

Evidence: `backend/sync/scheduler.py:StartupSyncScheduler.schedule`, `backend/sync/provider_table.py:DEFAULT_PROVIDER_DESCRIPTORS`; `tests/test_startup_sync_scheduler.py:test_enqueues_all_provider_jobs_in_contract_order_with_exact_payloads`, `tests/test_wahoo_runtime_acceptance.py:test_connected_account_flows_from_the_scheduler_to_the_status`.

### Requirement: Automatic cadence and eligibility
The system SHALL wait 300 seconds before each automatic loop pass, schedule eligible providers in weather, calendar, Garmin, Wahoo order, and then attempt the morning Body Battery refresh. Calendar, Wahoo, and Garmin without a Personal API key SHALL use the latest parseable attempt or success marker with a 3600-second due interval. With a key, Garmin SHALL follow its change check. Weather SHALL use forecast cache expiry and retry backoff instead of a daily marker.

#### Scenario: Due automatic pass
- **WHEN** a configured provider has no recent valid attempt or success marker and is not blocked
- **THEN** its refresh is queued and a scheduled refresh attempt marker is recorded.

#### Scenario: Garmin change check
- **WHEN** a Personal API key is configured and Garmin is neither blocked, active nor held by a retry
- **THEN** Garmin is due when the check finds a new activity or a newly published night, or, at most hourly, from 12:00 athlete-local time when no Garmin refresh succeeded that day
- **AND** the check reads the newest activity ids of today and yesterday and, until today's night is stored, today's sleep entry through the Personal API, every 10 minutes and every 30 minutes between 23:00 and 05:00 athlete-local time; an unchanged result queues nothing and, by day, stores today's daily summary and Body Battery report only when they differ from the stored values (no sync job, skipped while another Garmin read runs), a change a successful refresh did not store is held back for an hour, a failure doubles the wait up to eight times and never undercuts a `Retry-After` wait, a rejected key or endpoint makes the refresh due at that pace so its failure surfaces, and the morning reading waits for the stored night or 12:00.

#### Scenario: Loop failure and shutdown
- **WHEN** scheduling raises an error or the stop event is set during its wait
- **THEN** errors are safely classified and the loop can recover on a later pass, while stopping interrupts the wait without scheduling another pass.

#### Scenario: Upkeep in each pass
- **WHEN** a loop pass starts
- **THEN** it first prunes finished jobs and truncates the idle write-ahead log, and a failure of either is logged and never skips the scheduling.

#### Scenario: One provider fails
- **WHEN** scheduling one provider raises an error other than the maintenance refusal
- **THEN** the event `daily_sync_provider_failed` is logged and the providers after it are still scheduled; a maintenance refusal ends the pass.

#### Scenario: Marker time zones
- **WHEN** a marker carries another UTC offset than the current athlete-local time, for example across a daylight-saving change
- **THEN** both are compared as instants, and a marker without an offset takes the current offset.

Detailed contract: Maintenance, provider-specific blocking, active refresh jobs, and missing configuration SHALL prevent enqueueing where applicable.

Evidence: `backend/sync/scheduler.py:DailySyncLoop.run`, `backend/sync/scheduler.py:DailySyncScheduler._schedule_provider_safely`, `backend/sync/scheduler.py:DailySyncScheduler._schedule_provider`, `backend/sync/daily.py:daily_sync_is_due`, `backend/sync/garmin_change_check.py:GarminChangeCheck`; `tests/test_daily_sync_loop.py:test_sleeps_before_scheduling_then_refreshes_each_iteration`, `tests/test_daily_sync_scheduler.py:test_skips_active_jobs_and_not_due_markers`, `tests/test_daily_sync_scheduler.py:test_housekeeping_failure_never_skips_the_scheduling`, `tests/test_sync_daily.py:test_timezone_aware_marker_uses_the_same_instant_across_zones`, `tests/test_wahoo_runtime_acceptance.py:test_daily_scheduler_honours_the_marker_interval`, `tests/test_garmin_change_check.py`.

### Requirement: Scheduler retry hold
Every provider refresh SHALL write a refresh-history row with its trigger, status and, after an error, the time of the next allowed retry. The scheduler SHALL NOT queue a refresh for a provider whose latest non-skipped row is an error with a retry time in the future. Manual, Coach and startup refreshes SHALL ignore the hold.

#### Scenario: Backoff
- **WHEN** a provider failed n times in a row within its last 20 rows
- **THEN** its next scheduled refresh waits min(21600 s, 900 s x 2^min(n-1, 5)), or longer when the provider named a wait, never above 21600 s.

#### Scenario: Athlete action needed
- **WHEN** the latest failure is `auth_required`
- **THEN** no retry time is set and the scheduler holds the provider until a newer attempt exists or a stored credential of that provider was written after the failure; `invalid_configuration` sets no retry time and holds nothing.

#### Scenario: Skipped rows
- **WHEN** an operation was cancelled, held by a full resync, found the provider busy or was not configured
- **THEN** its row is `skipped` and neither ends nor extends a failure streak.

Evidence: `backend/sync/retry_hold.py:ProviderRetryHold`, `backend/sync/refresh.py:retry_at`, `backend/sync/refresh.py:finish_refresh_record`, `backend/sync/scheduler.py:DailySyncScheduler._schedule_provider`; `tests/test_provider_retry_hold.py`, `tests/test_sync_refresh.py`, `tests/test_daily_sync_scheduler.py:test_a_held_provider_gets_no_refresh_until_its_retry_is_due`.

### Requirement: Provider-specific current refresh windows
The system SHALL keep automatic provider windows distinct. Garmin SHALL initially cover 84 days, catch up from the oldest required collection coverage in contiguous windows of at most 90 days, and widen the first daily read to at least seven days for late corrections.

#### Scenario: Garmin coverage lag
- **WHEN** a required Garmin collection is over 90 days behind
- **THEN** the next window starts from the oldest coverage and ends before today if necessary, preserving a contiguous catch-up path rather than skipping the gap.

#### Scenario: Collections that set the window
- **WHEN** the automatic Garmin window is computed
- **THEN** it follows the oldest coverage end of activities, sleep and HRV, and of daily stats, resting heart rate and training status only while they are stored and the last recovery read still served them; a collection without coverage, or with less than 84 days, yields the initial 84 days.

#### Scenario: Wahoo listing bound
- **WHEN** a Wahoo run lists workouts
- **THEN** it reads pages of 50, newest first, stops at the first page that reaches before the window start, and reads at most 20 pages; a listing that ends at that bound or short of the total Wahoo reports makes the run `partial`, moves no activity fetch time and marks no stored workout as deleted.

#### Scenario: One Wahoo read at a time
- **WHEN** a second Wahoo run starts while one holds the lock
- **THEN** it returns `already_running`; only a waiting Coach refresh waits, up to 120 seconds, for the lock.

Detailed contract: Garmin's slowly changing metric sources SHALL be reread when due, after a new activity, or when retry state requires it. Wahoo SHALL clamp its stored automatic period, including the all sentinel, to its maximum 90-day window.

Evidence: `backend/sync/garmin.py:GarminPayloadService.automatic_sync_window`, `backend/providers/garmin.py:GarminCollectionOptions`, `backend/sync/wahoo_sync.py:sync_window_days`, `backend/sync/wahoo_sync.py:WahooSyncService.sync`, `backend/providers/wahoo_client.py:WahooClient.list_workouts`; `tests/test_sync_garmin_service.py:test_current_refresh_reads_daily_metrics_only_when_due`, `tests/test_sync_garmin_payload.py:test_sdk_only_source_that_stopped_advancing_does_not_freeze_the_window`, `tests/test_wahoo_sync.py:test_all_sentinel_and_zero_mean_the_descriptor_maximum`, `tests/test_wahoo_client.py`.

### Requirement: Garmin collection limits
A Garmin read SHALL send at most two range requests at a time. The first current sync of an athlete-local day SHALL re-read the Body Battery reports of the last 7 days in requests of at most 31 days; this read is optional and SHALL NOT make the sync partial. Watch ratings SHALL be read per activity for non-manual activities of the last 3 days (again on each sync) and of the last 14 days without a stored rating, newest first, at most 30 per sync.

#### Scenario: Rating read fails
- **WHEN** one rating read fails
- **THEN** the remaining rating reads of this sync are skipped, the failure is only logged and the sync stays complete.

#### Scenario: Rate limit inside one activity detail
- **WHEN** a detail part of an activity answers 429
- **THEN** no further part of that activity is requested and its payload carries `rate_limited: true`.

Detailed contract: current and historic metric ranges cover today-89 to today. The gear inventory is refused above 100 items; the activities of a gear item are read up to 1000 (`activity_ids_truncated` at the limit). A failed Body Battery read leaves the day due.

Evidence: `backend/providers/garmin.py:_collect_ranges`, `backend/providers/garmin.py:_collect_body_battery`, `backend/providers/garmin.py:_collect_activity_ratings`, `backend/providers/garmin.py:_rating_candidates`, `backend/providers/garmin.py:_gear_inventory`, `backend/sync/garmin_service.py:GarminRemoteReader.fetch_activity_details`, `backend/sync/garmin.py:GARMIN_RECONCILIATION_DAYS`; `tests/test_server_sync.py:test_garmin_range_collector_never_exceeds_two_parallel_calls`, `tests/test_garmin_body_battery_reconciliation.py:test_the_recent_week_is_read_once_and_marks_the_day`, `tests/test_garmin_body_battery_reconciliation.py:test_a_failed_read_keeps_the_sync_complete_and_the_day_open`.

### Requirement: Garmin fixture mode
With `GARMIN_FIXTURE_PATH` set, a Garmin sync SHALL read that JSON file instead of Garmin and send no provider request. It SHALL never wait for another run, run the metric export or the activity-detail backfill, or mark an activity as deleted. The wellness and stream backfills SHALL do nothing, and the historical chain SHALL end with its cursor at the history floor. The newest sleep night of the file SHALL be shifted to today.

#### Scenario: Broken fixture
- **WHEN** the path is missing, the file cannot be read or is no JSON object
- **THEN** the sync fails with 503 `not_configured` and is not retried.

Detailed contract: a relative path is resolved against the application root; the window starts at the history floor for the whole-history value, else it is the last min(days, 90) days ending today. The wellness and stream backfill jobs answer `{status: "ok", reason: "not_configured", window_records: 0}`.

Evidence: `backend/sync/garmin.py:GarminFixtureLoader`, `backend/sync/garmin_service.py:GarminSyncService._sync_inner`, `backend/sync/garmin_service.py:GarminSyncService._execute`, `backend/sync/executor.py:run_end_date_backfill`; `tests/test_sync_garmin.py:test_broken_fixture_failures_are_non_retryable_configuration_errors`, `tests/test_sync_garmin_service.py:test_fixture_mode_never_reaches_the_sdk`, `tests/test_garmin_wellness_history.py:test_fixture_mode_skips_without_cursor_or_continuation`.

### Requirement: Coach-requested refresh
A Coach refresh SHALL be queued with requester `coach` and answer `{ok, status: "queued", sync_job_id}`, unless the Coach marked it to wait. A waiting refresh SHALL run inline for Garmin and Wahoo only, wait up to 120 seconds for a running read of that provider, and answer `{ok, status: "completed", provider, partial, synchronous_refresh: true}`.

#### Scenario: Window of a waiting refresh
- **WHEN** a waiting refresh names no `days` or the whole-history value
- **THEN** Garmin reads its automatic catch-up window and flags `history_limited` for a narrowed whole-history request, and Wahoo reads 7 days, bounded by the stored Wahoo period; an explicit window is kept.

#### Scenario: Not usable
- **WHEN** the provider stays busy, the run is neither `ok` nor `partial`, Wahoo is not connected, or the request was cancelled
- **THEN** the refresh fails with 503 `provider_busy`, 503 `provider_refresh_failed`, 503 `not_configured` or 499 `chat_cancelled`; a provider without an inline refresh answers 400 `invalid_refresh_request`.

#### Scenario: Partial result
- **WHEN** the Garmin window ended before today, a source failed, or the morning Body Battery refresh failed, was busy or was cancelled
- **THEN** `partial` is true; for Wahoo it is true when the listing was cut off.

#### Scenario: Run awaited by the Coach
- **WHEN** a waiting Garmin refresh found another run in progress and that run finished
- **THEN** its result counts only when it is the latest stored run, its own read window covers the requested days, and activities, sleep and HRV were read completely (`ok` when every collection was complete, else `partial`); otherwise the refresh reads the window itself.

Evidence: `backend/sync/commands.py:ProviderRefreshCommandService.start`, `backend/sync/commands.py:GarminSynchronousRefresh`, `backend/sync/commands.py:WahooSynchronousRefresh`, `backend/sync/garmin_service.py:GarminSyncService._wait_for_existing`, `backend/sync/garmin.py:GarminPayloadService.awaited_run_status`; `tests/test_sync_commands.py`, `tests/test_current_data_refresh.py`, `tests/test_sync_garmin_payload.py:test_awaited_run_status_requires_the_latest_complete_read_of_the_window`.

### Requirement: Output-only Intervals.icu
The system SHALL NOT read Intervals.icu activities, wellness history, athlete record or activity details in any sync, and reads its calendar events only inside an explicit export. Intervals.icu SHALL accept only plan push, competition push and nutrition sync jobs plus the explicit library, metric and calendar writes with their read-backs. A refresh, historical backfill, activity-details or performance-refresh job, manual sync route or full resync for Intervals.icu SHALL be rejected.

#### Scenario: Refresh for Intervals.icu
- **WHEN** a request queues a `refresh` job for Intervals.icu
- **THEN** validation rejects it before creating a job and no Intervals.icu read endpoint is called.

#### Scenario: Coach current-data request
- **WHEN** the athlete explicitly asks the Coach for current data
- **THEN** the Coach waits for the Garmin and Wahoo refreshes where configured and calls no Intervals.icu ingest endpoint.

#### Scenario: Stored ingest job from an earlier release
- **WHEN** the worker claims a stored Intervals.icu job of type `refresh`, `performance_refresh`, `activity_details` or `historical_backfill`
- **THEN** it is completed without validation, without running and without a provider request, with the result reason `intervals_ingest_removed`; a stored one that is `failed` or `partial` stays listed until the athlete retries it, and the retry completes it unrun.

Detailed contract: The explicit connection check requests the athlete endpoint once and stores nothing. Stored Intervals.icu records of a database restored from a release before 2.0.0 are not read. The competition push reconciles linked events and never imports new competitions from Intervals.icu. A metric export reads the wellness record of one day and the sport settings of Ride or Run for the values it offers; every call is in docs/provider-endpoints.md.

Evidence: `backend/sync/provider_table.py:DEFAULT_PROVIDER_DESCRIPTORS`, `backend/sync/commands.py:WahooSynchronousRefresh`, `backend/sync/executor.py:IntervalsSyncJobOwner`, `backend/sync/executor.py:is_retired_intervals_ingest_job`, `backend/sync/executor.py:SyncJobExecutor.run`; `tests/test_current_data_refresh.py`, `tests/test_server_sync.py:test_persisted_intervals_ingest_jobs_are_retired_unrun`.

### Requirement: Bounded resumable historical backfill
The system SHALL walk Garmin history in inclusive chunks of at most 90 days down to the configured history floor. A restart SHALL resume before the persisted historical cursor. Complete chunks may schedule their next chunk after 15 seconds; partial chunks SHALL stop continuation. Two consecutive completely empty chunks SHALL end the walk and persist the floor.

#### Scenario: Complete historical chunk
- **WHEN** a complete nonterminal chunk finishes and no continuation from that parent exists
- **THEN** a delayed next chunk is persisted with the preceding end date and bounded empty-chunk count.

#### Scenario: Partial or exhausted history
- **WHEN** a chunk is partial, reaches the floor, or is the second consecutive complete empty chunk
- **THEN** no next chunk is queued; incomplete history is not silently skipped.

#### Scenario: Garmin wellness history
- **WHEN** Garmin is configured and its `wellness_history` cursor has not reached the floor
- **THEN** startup queues one `wellness_backfill` chain that walks the same chunks and reads only sleep (one full night element per night, with SpO2, respiration and sleeping heart rate), HRV, daily summaries with their resting heart rate, Body Battery daily reports (an optional source: its pause or failure skips it for the chunk), and weigh-ins, through the Personal API or the SDK; it adds only days not stored yet, replaces a stored night only when it has no night values, replaces a stored Body Battery report only when the read one differs, merges weigh-ins with the stored readings winning, and never prunes or deletes. A client error or an unreadable answer skips only that night or source; a paused source, rate limit or other provider error fails the chunk for a retry and keeps the cursor.

#### Scenario: Stream history
- **WHEN** Garmin or Wahoo is configured and its `stream_history` cursor has not reached the floor
- **THEN** startup queues one `stream_backfill` chain per provider; each job downloads the original FIT files of at most 30 (Garmin, Personal API, 2 s apart, one token) or 100 (Wahoo, from the workout list, 1 s apart) active non-manual non-strength records without a full-resolution stream set, newest first, and stores their stream and device-lap sets like the regular detail fetch. A rate limit or transient error fails the job and keeps the cursor; a rejected key shows the key hint; a record without a file or without sensor data, or one failing three runs, is counted and not read again; without a Personal API key Garmin stays blocked and the state says so. Queuing a finished chain again without `end_date` lets failed records retry.

#### Scenario: Chain resumed while the app runs
- **WHEN** a backfill chain has no queued or running job, its cursor is above the floor, and its provider is configured and not under resync
- **THEN** the scheduler pass queues it again below its cursor with requester `scheduler`, each chain at most once per 6 hours.

#### Scenario: Provider connected
- **WHEN** the athlete completes a Garmin login or a Wahoo connection
- **THEN** every chain of that provider is queued at once with requester `connection`, unless one is already active.

#### Scenario: First chunk
- **WHEN** a Garmin activity or wellness chain has no cursor and no `end_date`
- **THEN** its first chunk ends on the athlete-local today minus 2 days, the automatic Garmin refresh span.

#### Scenario: Follow-ups of a Garmin job
- **WHEN** a current Garmin refresh that is neither a backfill nor the whole history ends `ok` or `partial`
- **THEN** the morning Body Battery refresh runs; a historical chunk reads no recovery data and triggers none, and the completion hook is skipped while a chain continues and runs once when it ends.

#### Scenario: Wahoo refresh re-arms the stream chain
- **WHEN** a Wahoo refresh job finished
- **THEN** the Wahoo stream chain is started again once per FIT mapper version.

#### Scenario: Job without an owner
- **WHEN** a `plan_push` job reaches a provider without a push service
- **THEN** it fails with 409 `unsupported_job` and is not retried.

#### Scenario: Retired rating backfill
- **WHEN** the canonical backfill worker reaches its `rating_backfill_removal` stage
- **THEN** it deletes, once per version, the `garmin_rating_backfill_state` key and the `rating_history` cursor, and nothing else; stored jobs of the retired `rating_backfill` type stay as job history and the queue settles a leftover one

Detailed contract: Historical work SHALL yield to non-backfill jobs and active foreground Coach work, and repeated completion SHALL not fork a second continuation chain. Each backfill chain keeps its own cursor (`historical` for activities, `wellness_history` for the Garmin wellness walk, `stream_history` for the FIT stream walk of Garmin and Wahoo).

Evidence:
- `backend/providers/garmin_wellness_history.py:collect_wellness_history`
- `backend/sync/backfill_resume.py:BackfillChainResumer`
- `backend/sync/executor.py:GarminJobAdapter`
- `backend/sync/executor.py:HistoricalSyncJobOwner.window`
- `backend/sync/executor.py:HistoricalSyncJobOwner`
- `backend/sync/executor.py:WahooJobAdapter`
- `backend/sync/garmin_wellness_history.py:GarminWellnessHistoryService`
- `backend/sync/jobs.py:SyncJobStore.claim`
- `backend/sync/rating_backfill_removal.py:RatingBackfillRemoval`
- `backend/sync/stream_backfill.py:StreamBackfillService`
- `backend/sync/windows.py:split_date_windows`
- `tests/test_backfill_resume.py:test_a_chain_is_queued_at_most_once_per_interval`
- `tests/test_backfill_resume.py:test_connecting_wahoo_queues_its_stream_backfill_at_once`
- `tests/test_garmin_wellness_history.py`
- `tests/test_rating_backfill_removal.py`
- `tests/test_startup_sync_scheduler.py:test_cursor_date_and_earliest_boundary_contract`
- `tests/test_stream_backfill.py`
- `tests/test_sync_executor.py:test_a_chunk_that_hands_over_to_a_next_chunk_skips_the_hook`
- `tests/test_sync_executor.py:test_garmin_morning_refresh_is_limited_to_regular_success_or_partial`
- `tests/test_sync_jobs.py:test_backfill_continuation_keeps_its_cursor_while_a_chunk_runs`
- `tests/test_sync_jobs.py:test_claim_holds_backfill_while_foreground_work_runs`

### Requirement: Worker retries and restart recovery
The system SHALL conditionally claim due queued jobs and increment attempts once, enforce declared job-state transitions, preserve completed items across retry, and classify complete, partial, failed, and skipped item outcomes. Retryable failures SHALL use bounded backoff and at most three attempts. Restart recovery SHALL treat interrupted work as a lost outcome. Explicit resolution SHALL accept only `action=retry` for failed or partial jobs.

#### Scenario: Temporary provider failure
- **WHEN** a claimed job fails with a retryable class below its attempt limit
- **THEN** it is requeued for a future eligible instant while already completed items remain complete.

#### Scenario: Restart during a remote write
- **WHEN** the process stops while a plan push, competition push or nutrition export is running, or while a job runs its last attempt
- **THEN** after the restart that job is failed with `outcome_not_persisted` and its open items with it, never replayed, until the athlete retries it; interrupted read-only jobs are requeued.

#### Scenario: Lost outcome in a running process
- **WHEN** the worker finds a job still `running` between two claims because the database refused its outcome
- **THEN** a job that only reads a provider (`refresh`, `activity_details`, the backfill types) is queued again, while a `plan_push`, `competition_push` or `nutrition_sync` job, or one that used three attempts, fails with `outcome_not_persisted` and runs again only after an explicit retry.

#### Scenario: Invalid manual retry
- **WHEN** a caller retries a completed job, an unknown job, or a payload without the explicit retry action
- **THEN** the system returns its appropriate validation, conflict, or not-found error without resetting successful work.

Evidence: `backend/sync/jobs.py:SyncJobStore.claim`, `backend/sync/jobs.py:SyncJobStore.resume_interrupted`, `backend/sync/jobs.py:SyncJobStore.requeue_unowned_running`, `backend/sync/jobs.py:REPLAYABLE_JOB_TYPES`, `backend/sync/worker.py:SyncJobWorker.run_loop`, `backend/sync/job_outcomes.py:SyncJobOutcomeService`, `backend/sync/queue.py:SyncJobQueueService.resolve`; `tests/test_sync_jobs.py:test_resume_interrupted_resets_running_records_and_claims_again`, `tests/test_sync_jobs.py:test_requeue_unowned_running_never_replays_a_job_with_remote_effects`, `tests/test_sync_jobs.py:test_requeue_unowned_running_fails_a_job_without_attempts_left`, `tests/test_sync_jobs.py:test_failure_and_requeue_never_overwrite_completed_items`, `tests/test_sync_worker.py:test_a_job_with_remote_effects_is_not_replayed_after_a_lost_outcome`, `tests/test_sync_job_outcomes.py:test_exhausted_retry_updates_and_publishes_final_failure`.

### Requirement: Job states and derived status
A job SHALL be `queued`, `running`, `completed`, `partial` or `failed`, and an item additionally `skipped`. A job SHALL move only from queued to running, from running to queued or to a final state, and from partial or failed to queued; each move SHALL apply only if the job still has the status it expected. The job status SHALL follow from its items.

#### Scenario: Derived status
- **WHEN** all items are final
- **THEN** the job is `completed` when every item is completed or skipped, `failed` when every item failed, and `partial` for any other mix; a job without items is `completed`.

#### Scenario: Lost race
- **WHEN** a move finds another status than the expected one
- **THEN** it is rejected and nothing is written.

Evidence: `backend/sync/jobs.py:ALLOWED_JOB_TRANSITIONS`, `backend/sync/jobs.py:aggregate_job_status`, `backend/sync/jobs.py:SyncJobStore._transition`; `tests/test_sync_jobs.py:test_job_status_transition_table_allows_only_declared_edges`, `tests/test_sync_jobs.py:test_status_aggregation_distinguishes_partial_and_running`.

### Requirement: Retry classes and backoff
A failed claim SHALL be queued again only when its error class is retryable and the job has used fewer than three attempts, after min(21600 s, 900 s x 2^(attempt-1)); a wait the provider named raises that delay, never above 21600 s. Any other failure SHALL end the job as `failed` with its class and a redacted detail of at most 500 characters.

#### Scenario: Retryable classes
- **WHEN** the class is `network_error`, `database_busy`, `timeout`, `provider_unavailable`, `rate_limited`, `temporary_error` or `process_interrupted`
- **THEN** the job is retried after 900 s (first failure) and 1800 s (second failure), and fails on the third.

#### Scenario: Final classes
- **WHEN** the class is `auth_required`, `invalid_configuration`, `client_error`, `unsupported_job`, `invalid_job_request`, `invalid_job_resolution` or `garmin_sdk_required`
- **THEN** the job fails at once and is never queued again automatically.

Detailed contract: HTTP 429 or a rate-limit reason maps to `rate_limited`; 401, 403 or an auth or reconnect reason to `auth_required`; 400 or a not-configured reason to `invalid_configuration`; a network reason or timeout to `network_error`; a busy local database to `database_busy`; a provider HTTP error to `temporary_error`; an unreadable provider answer to `client_error`; every other provider error to `temporary_error`.

Evidence: `backend/sync/jobs.py:retry_delay`, `backend/sync/jobs.py:RETRYABLE_ERROR_CLASSES`, `backend/sync/jobs.py:SyncJobStore.requeue`, `backend/sync/job_outcomes.py:SyncJobOutcomeService.record_failure`, `backend/sync/refresh.py:sync_job_error_class`, `backend/sync/refresh.py:ProviderRefreshTracker.error_code`; `tests/test_sync_jobs.py:test_retry_backoff_is_bounded_and_classified`, `tests/test_sync_job_outcomes.py:test_a_provider_named_wait_delays_the_retry_up_to_the_cap`, `tests/test_sync_job_outcomes.py:test_a_garmin_sdk_requirement_is_final_and_never_requeued`.

### Requirement: Busy provider deferral
A claimed job whose provider run reports `already_running` SHALL be queued again for 30 seconds later without charging the attempt of that claim. The deferral SHALL end 30 minutes after the first collision of that job in this process; after that the job SHALL take the normal retry path as a temporary error.

#### Scenario: Lock held briefly
- **WHEN** a job meets a running Garmin or Wahoo read three times in a row
- **THEN** it is still queued with its former attempt count.

#### Scenario: Lock held too long
- **WHEN** the first collision is more than 30 minutes old
- **THEN** the job fails this attempt with HTTP 409 "Der Provider ist noch beschäftigt." and class `temporary_error`.

Evidence: `backend/sync/job_outcomes.py:SyncJobOutcomeService._defer_contended`, `backend/sync/jobs.py:SyncJobStore.defer`; `tests/test_sync_job_outcomes.py:test_three_collisions_do_not_fail_the_job`, `tests/test_sync_job_outcomes.py:test_the_age_limit_counts_from_the_first_collision_not_creation`.

### Requirement: Claim order and holds
One worker SHALL run one job at a time and claim the oldest due queued job, taking every non-backfill job before any backfill job. Backfill jobs SHALL stay queued while the Coach has queued or running work. Jobs of a provider whose full resync runs SHALL stay queued and SHALL NOT be charged an attempt.

#### Scenario: Backfill waits
- **WHEN** a backfill job and a refresh are both due
- **THEN** the refresh is claimed first, whichever was created first.

#### Scenario: Provider under resync
- **WHEN** a Wahoo full resync runs and a Wahoo job is due
- **THEN** the job keeps status `queued` and its attempt count, and runs after the resync.

Detailed contract: the worker polls every second and is woken by an enqueue, a retry or a requeue; each claim runs inside the maintenance gate as background database work.

Evidence: `backend/sync/jobs.py:SyncJobStore.claim`, `backend/sync/worker.py:SyncJobWorker.run_loop`; `tests/test_sync_jobs.py:test_claim_orders_backfill_jobs_after_other_queued_jobs`, `tests/test_sync_jobs.py:test_claim_leaves_jobs_of_a_resetting_provider_queued_without_an_attempt`.

### Requirement: Job and refresh-history retention
The system SHALL delete a `completed` job with its items once it finished more than 30 days ago, unless it is among the 200 newest jobs, and never prune a queued, running, failed or partial job. Pruning SHALL run from the scheduler loop at most once per hour. The sync status SHALL list at most 50 jobs, newest first. Refresh history SHALL keep 30 days and at most 200 rows.

#### Scenario: Old failed job
- **WHEN** a failed job is 90 days old
- **THEN** it is still stored and can be retried.

Evidence: `backend/sync/jobs.py:SyncJobStore.prune_finished`, `backend/sync/queue.py:SyncJobQueueService.prune_finished`, `backend/sync/refresh.py:cleanup_refresh_history`, `backend/sync/freshness.py:PROVIDER_REFRESH_RETENTION_DAYS`; `tests/test_sync_jobs.py:test_prune_removes_old_completed_jobs_and_their_items_only`, `tests/test_sync_queue.py:test_prune_runs_at_most_once_per_interval`.

### Requirement: Plan push items
A `plan_push` job SHALL store one item per selected entry, keyed by the local id. A provider result SHALL be mapped to its item by that id; `synced`, `already_synced` and `skipped` complete the item and every other status fails it. An item the result does not report SHALL fail. A retry SHALL send only the entries whose items are not completed.

#### Scenario: Retry after a partial push
- **WHEN** a job with three entries synced two and failed one, and the entry is retried
- **THEN** only the failed entry is sent again and the two completed items stay completed.

#### Scenario: One item for several results
- **WHEN** a job has one stored item and the provider reports several results
- **THEN** a failed result decides the item, otherwise the last result.

Evidence: `backend/http_api/sync_commands.py:_plan_push_item_operations`, `backend/sync/jobs.py:SyncJobStore.update_from_result`, `backend/sync/executor.py:_unsettled_plan_entries`; `tests/test_sync_jobs.py:test_one_stored_item_keeps_a_failure_among_several_results`, `tests/test_sync_jobs.py:test_unkeyed_results_map_by_position_only_when_counts_match`, `tests/test_sync_jobs.py:test_failure_and_requeue_never_overwrite_completed_items`.

### Requirement: Browser wait for a started job
The PWA SHALL poll a job it started once per second for at most 180 polls and stop at once when the job's error class cannot change by waiting (`auth_required`, `invalid_configuration`). The status strip SHALL raise "Anbindung benötigt Aufmerksamkeit" for a configured provider area with a non-retryable error, or in state error, stale or partial without a future retry time, but never for a busy local database.

#### Scenario: Job runs longer
- **WHEN** 180 polls passed without a final state
- **THEN** the PWA shows "Die Synchronisierung läuft länger als erwartet. Der Job kann unter Betrieb & Diagnose weiter verfolgt werden."

#### Scenario: Status polling
- **WHEN** the sync status is polled
- **THEN** the cadence is 1.5 seconds while the status reports `running`, 60 seconds otherwise and 5 seconds after a failed poll, while the tab is visible and online; the event stream and visibility rules are those of the view-refresh capability.

Evidence: `public/sync-actions.js:waitForSyncJob`, `public/sync-status.js:providerRequiresManualAttention`, `public/sync-status.js:renderProviderAttention`, `public/shared.js:SYNC_POLL_ACTIVE_MS`; `tests/sync-actions.test.cjs`.

### Requirement: Explicit full resync and safe status
The system SHALL require `confirm=FULL_RESYNC` on a full-resync route, serialize the operation with a provider reset gate, reject missing configuration before resetting, and release the gate and operation context on success or failure. A full read resync SHALL not imply remote plan or competition writes.

#### Scenario: Concurrent resync
- **WHEN** a confirmed resync is requested while its provider reset gate is held
- **THEN** the service reports already running without provider or durable-state writes.

#### Scenario: Cancelled synchronous refresh
- **WHEN** a supported refresh receives an already-set cancellation event
- **THEN** it exits with the cancellation contract before provider access and avoids successful completion markers for that work.

#### Scenario: Background run
- **WHEN** `POST /api/garmin/full-resync` or `POST /api/wahoo/full-resync` carries `{"confirm": "FULL_RESYNC"}`
- **THEN** the answer is 202 `{status: "started", source, operation_id}` at once and the read runs in a background thread; without the confirmation the answer is 400, for an unconfigured provider 503 `not_configured`, and while a run is active 200 `{status: "already_running", source, operation_id}`.

#### Scenario: Polled state
- **WHEN** the browser sends `GET` to the same path
- **THEN** it receives `running`, `status`, `last_resync_at`, `last_error` and an `outcome` (`operation_id`, `status` ok, partial or failed, `reason` for a failed run) of the latest run of this process.

#### Scenario: Partial read
- **WHEN** the Garmin read ends partial
- **THEN** `last_resync_at` stays, `last_error` is "Teilweise geladen. Bitte erneut starten." and the derived passes still run; a Wahoo listing cut off at the page limit fails the resync with reason `partial_resync`.

#### Scenario: Garmin operation progress
- **WHEN** a Garmin sync runs
- **THEN** the sync status reports `running` with phase and progress `fetching` 10, `storing` 75, `metric-export` 90 (only while the automatic export runs) and `activity-details` 95, and ends with `completed`/`complete` 100, `error`/`error` 100 with a redacted last error of at most 1000 characters, or `cancelled`/`cancelled` 100; a completed sync clears the stored last error.

#### Scenario: Running flag
- **WHEN** a Garmin sync runs
- **THEN** `status` of the sync status is `running` while `running` stays false, because only the Wahoo read reports its lock there; the browser follows `status`.

Detailed contract: Authenticated clients SHALL be able to inspect jobs, freshness, operation progress, and safe last-error state; browser polling SHALL recognize completed, partial, failed, and nonretryable states. Cooperative cancellation on supported synchronous reads SHALL stop provider work without being represented as a successful completion; the generic job contract does not add a cancelled state or arbitrary job-cancel endpoint.

Evidence: `backend/http_api/sync_commands.py:SyncCommandEndpoint._full_resync_command`, `backend/sync/full_resync.py:FullProviderResyncService.resync`, `backend/sync/resync_wiring.py:GarminFullResync`, `backend/sync/resync_wiring.py:WahooFullResync`, `backend/sync/full_resync.py:FullProviderResyncService.start`, `backend/sync/garmin_service.py:GarminSyncService._execute`, `backend/sync/status.py:persist_sync_operation_state`, `backend/sync/status.py:SyncPublicStateService.state`, `public/sync-actions.js:waitForSyncJob`; `tests/test_sync_full_resync.py:test_gate_and_context_are_restored_when_status_cleanup_fails`, `tests/test_sync_full_resync.py:test_unconfigured_handler_error_is_raised_before_gate_reset`, `tests/test_http_sync_commands.py:test_full_resync_is_accepted_with_its_operation_id_and_runs_in_the_background`, `tests/test_sync_status.py`, `tests/test_sync_resync_wiring.py`.

### Requirement: Partial source recovery and freshness projection
The system SHALL preserve last-good optional sources and their own fetch dates when a source fails or is skipped, expose partial status, and advance historical cursors only for complete supported coverage. Three failures in a row of one Garmin capability class SHALL pause that source for 24 hours; a success clears the count. Provider freshness SHALL distinguish attempts, successful/partial results, errors, and scheduled retry.

#### Scenario: Optional Garmin source fails
- **WHEN** an optional metric fails while other source reads succeed
- **THEN** successful sources remain usable, retained source fetch time is preserved, and incomplete coverage does not advance historical cursors past the gap.

#### Scenario: Repeated capability error
- **WHEN** a Garmin source fails three times in a row with the same capability class: rate limited (HTTP 429), not found (HTTP 404) or unsupported
- **THEN** that source is skipped for 24 hours; a changed class restarts the count, a success clears it, and an expired pause starts the count again.

#### Scenario: Failures that do not count
- **WHEN** a source fails with a network error, a timeout, a server error (5xx), a rejected login (401, 403) or an unreadable answer
- **THEN** the count is unchanged and nothing is paused.

#### Scenario: Pauses cleared
- **WHEN** a new Personal API key or Garmin e-mail address is saved, a stored-login check passes, or a new Garmin login is stored
- **THEN** every pause is removed, including those of the wellness history walk, which are kept under their own names.

#### Scenario: Freshness entry
- **WHEN** the freshness of a provider area is projected
- **THEN** its `state` is `not_configured`; else `syncing` while the latest non-skipped history row runs; `stale` (with a last-good read) or `error` after an error row; `partial` after a partial row; else `fresh` or `stale` by the age of the last good read against the area limit; `error` when only a stored error exists; `never_loaded` otherwise. `next_retry_at` is the start time of a queued refresh job of that provider in the future, never the advisory history value, and an output-only area never becomes stale by age.

#### Scenario: Public freshness after failure
- **WHEN** the latest attempt fails but a last-good refresh exists
- **THEN** freshness can report stale data with a safe error and retry timestamp rather than treating the stored measurement as a new successful read. Registry staleness limits are 48 hours for training/calendar areas and three hours for weather.

Evidence: `backend/sync/garmin.py:GarminSyncStateService.record_capability_failure`, `backend/sync/garmin.py:GarminSyncStateService.persist_payload`, `backend/providers/garmin_capability.py:capability_failure_class`, `backend/sync/freshness.py:provider_freshness_state`, `backend/sync/freshness.py:_provider_freshness_status`; `tests/test_sync_garmin.py:test_failure_class_changes_reset_count_and_success_clears_existing_state`, `tests/test_provider_review.py:test_garmin_partial_metrics_and_backfill_keep_last_good_sources_and_cursors`, `tests/test_provider_runtime_acceptance.py:test_freshness_moves_from_never_loaded_to_fresh_then_stale`.
