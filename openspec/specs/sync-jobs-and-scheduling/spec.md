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

Detailed contract: Intervals supports refresh, performance refresh, activity details, plan push, competition push, nutrition sync, and historical backfill; Garmin supports refresh, activity details, and historical backfill; Wahoo supports refresh and plan push; weather and calendar support refresh. Nutrition approval semantics belong to the nutrition capability.

Evidence: `backend/sync/jobs.py:normalize_sync_job_request`, `backend/providers/descriptors.py:DEFAULT_PROVIDER_DESCRIPTORS`; `tests/test_sync_jobs.py:test_every_provider_and_job_type_pair_matches_the_live_validator`, `tests/test_sync_jobs.py:test_boolean_fields_require_actual_booleans`.

### Requirement: Durable jobs and duplicate suppression
The system SHALL persist jobs and ordered items atomically, expose bounded progress and safe errors, and atomically coalesce active performance-refresh jobs and eligible automatically requested refresh/backfill jobs. Coalescing SHALL preserve the existing job identity and avoid a second created event or worker wake. User requests are not covered by a blanket exactly-once guarantee.

#### Scenario: Concurrent automatic enqueue
- **WHEN** concurrent eligible automatic requests target the same provider and operation while one job is queued or running
- **THEN** callers receive the same active job rather than parallel duplicate jobs.

#### Scenario: Atomic creation fails
- **WHEN** storing an item or validating its bounded operation list fails
- **THEN** the request creates no partially populated job.

Evidence: `backend/sync/jobs.py:SyncJobStore.enqueue`, `backend/sync/queue.py:SyncJobQueueService.enqueue`; `tests/test_sync_jobs.py:test_concurrent_automatic_enqueues_create_exactly_one_job`, `tests/test_sync_queue.py:test_deduplicated_performance_job_does_not_publish_or_wake_again`.

### Requirement: Startup scheduling
The system SHALL schedule configured startup refreshes in calendar, Intervals, Garmin, weather, Wahoo order, skip an already active refresh, and enqueue historical backfill only for providers declaring it. Weather startup requests are forced. Intervals and Garmin default sync periods are 84 days; ordinary selectable periods are limited to 365 days for Intervals and 90 days for Garmin/Wahoo, with the separate all-history sentinel interpreted by each provider owner.

#### Scenario: Configured startup
- **WHEN** startup scheduling runs with configured and connected providers
- **THEN** refresh work uses registry order, provider policy payloads, and requester `startup`.

#### Scenario: Restart with active work
- **WHEN** a provider already has an active refresh or historical-backfill job
- **THEN** startup does not duplicate that operation; disabled or unconnected providers are skipped.

Evidence: `backend/sync/scheduler.py:StartupSyncScheduler.schedule`, `backend/providers/descriptors.py:DEFAULT_PROVIDER_DESCRIPTORS`; `tests/test_startup_sync_scheduler.py:test_enqueues_all_provider_jobs_in_contract_order_with_exact_payloads`, `tests/test_wahoo_runtime_acceptance.py:test_connected_account_flows_from_the_scheduler_to_the_status`.

### Requirement: Automatic cadence and eligibility
The system SHALL wait 300 seconds before each automatic loop pass, schedule eligible providers in weather, calendar, Garmin, Intervals, Wahoo order, and then attempt the morning Body Battery refresh. Calendar, Garmin, Intervals, and Wahoo SHALL use the latest parseable attempt or success marker with a 3600-second due interval. Weather SHALL use forecast cache expiry and retry backoff instead of a daily marker.

#### Scenario: Due automatic pass
- **WHEN** a configured provider has no recent valid attempt or success marker and is not blocked
- **THEN** its refresh is queued and a scheduled refresh attempt marker is recorded.

#### Scenario: Loop failure and shutdown
- **WHEN** scheduling raises an error or the stop event is set during its wait
- **THEN** errors are safely classified and the loop can recover on a later pass, while stopping interrupts the wait without scheduling another pass.

Detailed contract: Maintenance, provider-specific blocking, active refresh jobs, and missing configuration SHALL prevent enqueueing where applicable.

Evidence: `backend/sync/scheduler.py:DailySyncLoop.run`, `backend/sync/scheduler.py:DailySyncScheduler._schedule_provider`, `backend/sync/daily.py:daily_sync_is_due`; `tests/test_daily_sync_loop.py:test_sleeps_before_scheduling_then_refreshes_each_iteration`, `tests/test_daily_sync_scheduler.py:test_skips_active_jobs_and_not_due_markers`, `tests/test_wahoo_runtime_acceptance.py:test_daily_scheduler_honours_the_marker_interval`.

### Requirement: Provider-specific current refresh windows
The system SHALL keep automatic provider windows distinct. Intervals SHALL read the selected full period once per athlete-local day and then refresh yesterday and today, retaining the selected wellness history; a manual full-period read also satisfies that daily marker. Garmin SHALL initially cover 84 days, catch up from the oldest required collection coverage in contiguous windows of at most 90 days, and widen the first daily read to at least seven days for late corrections.

#### Scenario: Second automatic Intervals read today
- **WHEN** the selected full period has already been read on the current local day
- **THEN** a subsequent automatic read requests two days with retention of the selected period and does not repeat the full-read performance follow-up.

#### Scenario: Garmin coverage lag
- **WHEN** a required Garmin collection is over 90 days behind
- **THEN** the next window starts from the oldest coverage and ends before today if necessary, preserving a contiguous catch-up path rather than skipping the gap.

Detailed contract: Garmin's slowly changing metric sources SHALL be reread when due, after a new activity, or when retry state requires it. Wahoo SHALL clamp its stored automatic period, including the all sentinel, to its maximum 90-day window.

Evidence: `backend/sync/intervals.py:IntervalsSyncService`, `backend/sync/garmin.py:GarminPayloadService.automatic_sync_window`, `backend/providers/garmin.py:GarminCollectionOptions`, `backend/sync/wahoo_sync.py:sync_window_days`; `tests/test_sync_intervals_flow.py:test_automatic_refresh_reads_full_period_once_per_day`, `tests/test_sync_garmin_service.py:test_current_refresh_reads_daily_metrics_only_when_due`, `tests/test_wahoo_sync.py:test_all_sentinel_and_zero_mean_the_descriptor_maximum`.

### Requirement: Bounded resumable historical backfill
The system SHALL walk Intervals and Garmin history in inclusive chunks of at most 90 days down to the configured history floor. A restart SHALL resume before the persisted historical cursor. Complete chunks may schedule their next chunk after 15 seconds; partial chunks SHALL stop continuation. Two consecutive completely empty chunks SHALL end the walk and persist the floor.

#### Scenario: Complete historical chunk
- **WHEN** a complete nonterminal chunk finishes and no continuation from that parent exists
- **THEN** a delayed next chunk is persisted with the preceding end date and bounded empty-chunk count.

#### Scenario: Partial or exhausted history
- **WHEN** a chunk is partial, reaches the floor, or is the second consecutive complete empty chunk
- **THEN** no next chunk is queued; incomplete history is not silently skipped.

Detailed contract: Historical work SHALL yield to non-backfill jobs and active foreground Coach work, and repeated completion SHALL not fork a second continuation chain.

Evidence: `backend/sync/executor.py:HistoricalSyncJobOwner`, `backend/sync/windows.py:split_date_windows`, `backend/sync/jobs.py:SyncJobStore.claim`; `tests/test_startup_sync_scheduler.py:test_cursor_date_and_earliest_boundary_contract`, `tests/test_sync_jobs.py:test_claim_holds_backfill_while_foreground_work_runs`, `tests/test_sync_jobs.py:test_backfill_continuation_keeps_its_cursor_while_a_chunk_runs`.

### Requirement: Worker retries and restart recovery
The system SHALL conditionally claim due queued jobs and increment attempts once, enforce declared job-state transitions, preserve completed items across retry, and classify complete, partial, failed, and skipped item outcomes. Retryable failures SHALL use bounded backoff and at most three attempts. Restart recovery SHALL requeue interrupted running work and clear a stale performance-running marker. Explicit resolution SHALL accept only `action=retry` for failed or partial jobs.

#### Scenario: Temporary provider failure
- **WHEN** a claimed job fails with a retryable class below its attempt limit
- **THEN** it is requeued for a future eligible instant while already completed items remain complete.

#### Scenario: Invalid manual retry
- **WHEN** a caller retries a completed job, an unknown job, or a payload without the explicit retry action
- **THEN** the system returns its appropriate validation, conflict, or not-found error without resetting successful work.

Evidence: `backend/sync/jobs.py:SyncJobStore.claim`, `backend/sync/jobs.py:SyncJobStore.resume_interrupted`, `backend/sync/job_outcomes.py:SyncJobOutcomeService`, `backend/sync/queue.py:SyncJobQueueService.resolve`; `tests/test_sync_jobs.py:test_resume_interrupted_resets_running_records_and_claims_again`, `tests/test_sync_jobs.py:test_failure_and_requeue_never_overwrite_completed_items`, `tests/test_sync_job_outcomes.py:test_exhausted_retry_updates_and_publishes_final_failure`.

### Requirement: Explicit full resync and safe status
The system SHALL require `confirm=FULL_RESYNC` on a full-resync route, serialize the operation with a provider reset gate, reject missing configuration before resetting, and release the gate and operation context on success or failure. A full read resync SHALL not imply remote plan or competition writes.

#### Scenario: Concurrent resync
- **WHEN** a confirmed resync is requested while its provider reset gate is held
- **THEN** the service reports already running without provider or durable-state writes.

#### Scenario: Cancelled synchronous refresh
- **WHEN** a supported refresh receives an already-set cancellation event
- **THEN** it exits with the cancellation contract before provider access and avoids successful completion markers for that work.

Detailed contract: Authenticated clients SHALL be able to inspect jobs, freshness, operation progress, and safe last-error state; browser polling SHALL recognize completed, partial, failed, and nonretryable states. Cooperative cancellation on supported synchronous reads SHALL stop provider work without being represented as a successful completion; the generic job contract does not add a cancelled state or arbitrary job-cancel endpoint.

Evidence: `backend/http_api/sync_commands.py:SyncCommandEndpoint._full_resync_command`, `backend/sync/full_resync.py:FullProviderResyncService.resync`, `backend/sync/intervals.py:IntervalsSyncService`, `public/sync-actions.js:waitForSyncJob`; `tests/test_sync_full_resync.py:test_intervals_and_competitions_share_operation_and_never_push`, `tests/test_sync_full_resync.py:test_failure_is_redacted_bounded_and_restores_context_and_gate`, `tests/test_sync_intervals_flow.py:test_cancellation_before_lock_has_no_provider_or_status_side_effect`.

### Requirement: Partial source recovery and freshness projection
The system SHALL preserve last-good optional sources and their own fetch dates when a source fails or is skipped, expose partial status, and advance historical cursors only for complete supported coverage. Garmin capability failures of the same class SHALL pause that capability after three failures for 24 hours; success clears its breaker. Provider freshness SHALL distinguish attempts, successful/partial results, errors, and scheduled retry.

#### Scenario: Optional Garmin source fails
- **WHEN** an optional metric fails while other source reads succeed
- **THEN** successful sources remain usable, retained source fetch time is preserved, and incomplete coverage does not advance historical cursors past the gap.

#### Scenario: Repeated capability error
- **WHEN** the same Garmin capability error class reaches three consecutive failures
- **THEN** that capability is suppressed until its 24-hour pause expires; a changed error class restarts the failure count and a successful read clears it.

#### Scenario: Public freshness after failure
- **WHEN** the latest attempt fails but a last-good refresh exists
- **THEN** freshness can report stale data with a safe error and retry timestamp rather than treating the stored measurement as a new successful read. Registry staleness limits are 48 hours for training/calendar areas and three hours for weather.

Evidence: `backend/sync/garmin.py:GarminSyncStateService.record_capability_failure`, `backend/sync/garmin.py:GarminSyncStateService.persist_payload`, `backend/sync/freshness.py:provider_freshness_state`; `tests/test_sync_garmin.py:test_failure_class_changes_reset_count_and_success_clears_existing_state`, `tests/test_provider_review.py:test_garmin_partial_metrics_and_backfill_keep_last_good_sources_and_cursors`, `tests/test_sync_freshness.py:test_fresh_stale_malformed_and_z_timestamps`.
