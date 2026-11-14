# coach-context-and-provenance Specification

## Purpose

Describe the bounded local evidence supplied to the Coach, its source and freshness metadata, and the read/refresh surfaces observed in the current application. Evidence citations describe inspected code and tests, not complete runtime conformance.

## Requirements

### Requirement: CP1 Durable local athlete authority
The system SHALL assemble saved profile, target competitions, training-plan metadata, local planned units and athlete feedback from local domain state; dialogue continuity SHALL NOT replace those authoritative records.

#### Scenario: Existing saved facts
- **WHEN** a Coach turn includes profile or competition context
- **THEN** it uses the current locally saved records even when a remote conversation contains earlier dialogue about those facts.

#### Scenario: Different evidence kinds
- **WHEN** daily check-ins, completed-activity feedback and provider recovery are available
- **THEN** they remain separate sections with athlete-entered feedback distinguished from wearable observations.

#### Scenario: No athlete feedback
- **WHEN** a requested local feedback section has no saved observations
- **THEN** the system returns its empty local projection rather than manufacturing subjective scores from provider metrics.

Evidence: `backend/coach/context.py:CoachStructuredContextService._selected_sections`, `backend/coach/context.py:CoachPlanningContextReader`, `backend/coach/context.py:CoachPerformanceContextReader.profile`; `backend/athlete/checkins.py:CheckinService.context`; `tests/test_coach_structured_context.py:test_build_uses_snapshot_fallback_and_projects_safe_provider_context`; `tests/test_coach_tool_coverage.py:test_daily_feedback_and_activity_feedback_are_separate_from_profile`.

### Requirement: CP2 Request-appropriate context selection
The system SHALL select context sections, date horizon and recent-activity limits for the current request while retaining conservative fallback context for unresolved or ambiguous continuations.

#### Scenario: Narrow request
- **WHEN** the athlete asks about a recognized compact topic
- **THEN** only selected domain sections and bounded dialogue are assembled, with omitted-section metadata and access to on-demand context reads.

#### Scenario: Planning or long history
- **WHEN** the request requires a long-range plan, explicit dates, provider sync context or historical comparison
- **THEN** selection expands to the corresponding complete context rather than presenting a short projection as full coverage.

#### Scenario: Pronoun or relevant clarification
- **WHEN** a short continuation depends on an active request or referenced dialogue
- **THEN** necessary original messages are retained without granting write authority from context selection.

#### Scenario: Sections and base set
- **WHEN** a selection is made
- **THEN** it chooses among the sections named in `CONTEXT_SECTIONS` (`backend/coach/context_selection.py`, normative): the base set is durable_profile, target_competitions, local_feedback, activity_feedback, local_planned_workouts, activities, current_performance and source_policy; the full set is every section except nutrition_products and planning_brief; the quick-action kinds use the fixed sets of CC9a

#### Scenario: Routine topic
- **WHEN** a message matches one topic without explicit dates, history words, a past week, an active pending request or a provider refresh
- **THEN** the base set is sent, plus planning and training_plans for planning topics, the day view (`daily_planning_context`) for planning, today-training and weekday messages, recovery for recovery words, weather for weather words, the external calendar for full-calendar words and saved products for food, with a window of 2 past and 3 future days (14 future days for planning topics, at least 7 for a weather question that names a day) and the newest activity of each sport (5 per sport for planning and activity analysis)

#### Scenario: Full or fallback context
- **WHEN** the message names an explicit date, history or a past week without a planning verb, plans over months or several weeks, or asks for a provider refresh or sync without planning
- **THEN** the full set is sent without a day window; an active pending request, or a continuation or pronoun reference that is ambiguous (no topic, at most three words or several topics), gets the fallback set (base, day view, planning, training_plans) and every other section stays loadable through `read_coach_context`

#### Scenario: Dialogue window
- **WHEN** a turn is built
- **THEN** the last 24 messages (each cut to 4,000 characters, plus the athlete messages a pending request cites) and the last 12 completed results are loaded and the current message is sent once, separately; a routine turn carries only the last 8 loaded messages and 3 results, while a continuation, a pronoun reference, a resumed turn and a full-context turn keep all loaded entries

Evidence: `backend/coach/context_selection.py:select_coach_context`, `backend/coach/context_selection.py:compact_coach_dialogue`; `tests/test_coach_context_selection.py:test_explicit_dates_without_planning_keywords_use_full_context`, `tests/test_coach_context_selection.py:test_long_range_planning_uses_complete_context`, `tests/test_coach_context_selection.py:test_dialogue_compaction_does_not_mutate_authorization_context`; `tests/test_coach_context_reduction.py:test_scoped_assembly_skips_unnecessary_reads`; `backend/coach/context_selection.py:CONTEXT_SECTIONS`, `backend/coach/context_selection.py:CoachContextSelection`, `backend/coach/dialogue.py:CoachDialogueReadService.context`; `tests/test_coach_context_selection.py`, `tests/test_coach_context_scenarios.py` (scenario catalogue `tests/fixtures/coach_context_scenarios.json`), `tests/test_coach_dialogue_read.py:test_context_limits_messages_and_projects_only_bounded_fields`.

### Requirement: CP3 Bounded context with visible coverage
The system SHALL bound per-section and total Coach context, retain valid structured data after clipping, and expose projection metadata describing omitted or truncated sections and item limits.

#### Scenario: Oversized section
- **WHEN** an individual section exceeds its configured character budget
- **THEN** the system retains a bounded useful projection and records original versus projected size.

#### Scenario: Total budget exceeded
- **WHEN** the complete prompt context exceeds its total budget
- **THEN** clipping keeps valid JSON and records total-budget omitted and truncated sections rather than silently claiming full context.

#### Scenario: Bounded activity and library selection
- **WHEN** the app supplies default full training context
- **THEN** recent activities, planned events, local planned units and library templates are bounded and the projection exposes the applicable limits.

#### Scenario: Context sized per task
- **WHEN** a Coach turn is built for an analysis, review, planning, morning check-in, typed planning, general or nutrition request
- **THEN** only the sections that task needs are included, within a deterministic character budget per kind, and the request diagnostics record the selection name, request kind and the characters of each present section so live sizes can be compared.

#### Scenario: Canonical data is not yet available
- **WHEN** the first canonical backfill is pending or failed and a scoped Coach context is built
- **THEN** the context marks the unavailable canonical activity and provider data, preserves that marker through selection, and identifies local plans as still available.

#### Scenario: Section and item limits
- **WHEN** a section is larger than its limit, measured as the length of its compact JSON text
- **THEN** it is cut to activities 32,000, current_performance 24,000, daily_planning_context 24,000, external_calendar 20,000, planning_brief 20,000, recovery 16,000, planning 16,000, weather 16,000, nutrition_products 16,000, local_feedback 12,000 or activity_feedback 12,000 characters; the items are limited to 5 recent activities per sport, 50 planned events, 50 local planned units, 12 library templates (descriptions at most 1,500 characters) and 80 saved products

#### Scenario: Total budget and priority
- **WHEN** the context exceeds 120,000 characters
- **THEN** the sections are fitted in this order and what no longer fits is truncated or omitted: projection, source_policy, canonical_data_status, recovery, current_performance, daily_planning_context, durable_profile, target_competitions, local_planned_workouts, planning, planning_brief, local_feedback, activity_feedback, training_plans, activities, weather, nutrition_products, calendar, external_calendar; losing one of the first six is logged as a warning, any other loss at info level

Evidence:
- `backend/coach/context.py:bounded_coach_context_sections_by_priority`
- `backend/coach/context.py:bounded_coach_context_sections`
- `backend/coach/context.py:coach_context_projection_meta`
- `backend/coach/context.py:COACH_CONTEXT_SECTION_LIMITS`
- `backend/coach/context.py:COACH_CONTEXT_SECTION_PRIORITY`
- `backend/coach/context.py:COACH_CONTEXT_TOTAL_CHAR_LIMIT`
- `backend/coach/context.py:CoachTrainingContextService.build`
- `tests/test_coach_context_budget.py:CoachContextBudgetTests.test_sections_and_budget_per_kind`
- `tests/test_coach_context_budget.py:CoachContextBudgetTests.test_size_diagnostics_name_the_selection_and_sections_for_every_kind`
- `tests/test_coach_context_reduction.py:test_oversized_single_section_retains_useful_prefix`
- `tests/test_coach_context_reduction.py:test_pending_data_marker_survives_scoped_planning_projection`
- `tests/test_coach_context_selection.py:test_date_window_and_activity_limits_preserve_provenance`
- `tests/test_coach_training_context.py:test_section_and_total_truncation_keep_valid_bounded_context`

### Requirement: CP4 On-demand omitted context
The system SHALL support read-only loading of named local Coach context sections, report whether the bounded result is complete, and reject invalid section requests.

#### Scenario: Load omitted recovery or planning
- **WHEN** the Coach calls `read_coach_context` for valid omitted sections
- **THEN** every section a task leaves out, including `daily_planning_context`, `calendar` and `training_plans`, is loadable this way: the system reads those sections locally and returns requested-section and completeness metadata while retaining the turn's offered tool availability without refreshing providers or authorizing mutations.

#### Scenario: Result exceeds detail budget
- **WHEN** the requested sections exceed the 40000-character result budget
- **THEN** the result is bounded and `projection.complete` is false so narrower reads can be requested.

#### Scenario: Invalid or unavailable sections
- **WHEN** the request contains no sections, more than fifteen, an unknown section, or the context service is unavailable
- **THEN** it fails explicitly rather than returning invented or raw snapshot data.

Evidence: `backend/coach/read_tools.py:CoachReadToolService._read_coach_context`; `backend/coach/structured_tool_round.py:CoachStructuredToolRoundService`; `tests/test_coach_context_reduction.py:test_detail_read_bounds_output_and_rejects_unknown_sections`; `tests/test_coach_context_selection.py:test_rephrased_requests_offer_required_registered_tools`.

### Requirement: CP5 Saved provider evidence and honest freshness
The system SHALL build ordinary Coach context from saved Garmin, Wahoo and local data, retain available source/sync metadata, and read cached weather without causing an unconditional provider refresh. Intervals.icu is an output target and is never read as a source. The `activities` section SHALL report the activity sync time as `synced_at` and `source.synced_at`, read in the same snapshot as the rows (null without coverage), and SHALL label its source with the providers of its sessions.

#### Scenario: Ordinary context read
- **WHEN** the athlete sends an ordinary Coach message
- **THEN** context assembly reads saved data and weather with refresh disabled rather than issuing provider calls for every message.

#### Scenario: No Intervals.icu input
- **WHEN** the recovery section is built, whatever the stored provider coverage (Intervals.icu is no longer read, #1728)
- **THEN** it requests Garmin's performance values beside the recovery records, keeps provider recovery separate and keeps unavailable evidence explicit.

#### Scenario: Recovery section from canonical records
- **WHEN** the Coach recovery section is built
- **THEN** sleep, HRV, resting HR and readiness each show the latest canonical Garmin record of the last 14 days (`date` plus neutral fields such as `sleep_seconds`, `sleep_score`, the night values `avg_spo2_pct`, `lowest_spo2_pct`, `avg_respiration_brpm` and `avg_sleeping_hr_bpm`, `last_night_avg_ms`, `weekly_avg_ms`, `resting_hr_bpm`, `score`, and the provider status codes `status` and `level`; the sleep record adds `night_means` with each night value's mean and night count over those 14 days), Body Battery the stored morning record, and the sync time, window, freshness and errors come from the Garmin sync status, read in the same read transaction as the records; the raw Garmin view is not read, and the section always carries Garmin's performance values under `performance`.

#### Scenario: Local calendar planning
- **WHEN** context combines planned units, competitions and external calendar entries
- **THEN** calendar items identify their local-plan, competition or external-calendar origin; external calendar context is read-only.

#### Scenario: Activities freshness from canonical coverage
- **WHEN** the context includes the activities section and canonical coverage stores a current Garmin or Wahoo activity fetch time
- **THEN** the section's `synced_at` and `source.synced_at` equal that time regardless of the stored snapshot's `synced_at` or of a duplicate deletion, and are null when no coverage is stored.

Evidence:
- `backend/coach/context.py:CoachStructuredContextService.build`
- `backend/coach/context.py:CoachPlanningContextReader.calendar`
- `backend/coach/context.py:CoachPlanningContextReader.external_calendar`
- `backend/coach/context.py:CoachPerformanceContextReader.current_performance`
- `backend/coach/context.py:CoachIntervalsContextService.project`
- `tests/test_coach_structured_context.py:test_build_uses_snapshot_fallback_and_projects_safe_provider_context`. Per-metric provenance is owned by performance/provider capabilities; this requirement does not assert that every legacy section label identifies every canonical provider correctly. The activity sync time is the activity sync time (the oldest current activity fetch of Garmin and Wahoo in the canonical provider coverage; a provider fetched more than 14 days before the newest one is left out, Intervals.icu copies never count; `backend/activities/sync_time.py:activities_synced_at`)
- `source.providers` lists the providers of the sessions' primary and per-value sources (`tests/test_coach_domain_sections.py:test_activities_source_block_comes_first_and_names_the_session_sources`, `tests/test_activity_sync_time.py`).

### Requirement: CP6 Explicit provider refresh and current results
The system SHALL route a requested provider update through the existing provider refresh owners, distinguish queued work from completed refreshed data, and use refreshed local context before the subsequent model response where the provider contract waits for completion.

#### Scenario: Explicit current-data refresh
- **WHEN** a supported explicit refresh is selected in an athlete-started turn
- **THEN** the existing provider-specific refresh path is used and refreshed local context is available before the next model response on waiting refresh paths.

#### Scenario: Queued refresh
- **WHEN** the provider refresh is queued
- **THEN** the tool returns a sync-job reference whose current status can be read with `get_sync_job`; queuing alone is not proof that data is current.

#### Scenario: Reading a sync job
- **WHEN** the Coach calls `get_sync_job` with a job id
- **THEN** tool preparation grants the matching `sync_job:<id>` scope for every call, so the Coach can read any local sync job by id.

#### Scenario: Refresh failure
- **WHEN** a refresh fails or its job remains pending
- **THEN** that tool result remains distinguishable from a successful refresh, and saved context remains saved evidence rather than a new provider measurement.

#### Scenario: Refresh parameters
- **WHEN** the Coach calls `start_provider_refresh` (parameters in `openspec/COACH_TOOLS.md`)
- **THEN** the provider is the `_request.target` among the Coach refresh targets with the scope `<target>_refresh`, the optional `days` is -1 or 1 to 365, and no sync wording is needed because no athlete-authored record changes; the Coach rules (`COACH_PROMPT`, CC9c) allow it only after an explicit request to update a provider and ask for `days` 30 on a Garmin catch-up

Evidence: `backend/coach/sync_tools.py:CoachSyncToolService.execute`; `backend/coach/tool_preparation.py:CoachStructuredToolPreparationService._waits_for_completion`; `tests/test_coach_dialogue.py:test_current_refresh_runs_before_next_model_response_without_trigger_gate`, `tests/test_coach_dialogue.py:test_garmin_refresh_waits_for_completion_without_queueing`, `tests/test_coach_dialogue.py:test_queued_refresh_and_job_read_use_current_tool_results`; `backend/coach/tool_preparation.py:CoachStructuredToolPreparationService.prepare`; `tests/test_coach_tool_preparation.py:StructuredToolPreparationTests.test_get_sync_job_receives_object_scope_without_reclassification`; `tests/test_coach_tool_coverage.py:test_provider_reads_and_job_status_use_correct_provider`; `backend/coach/tool_specs.py:UNGATED_TOOLS`, `backend/sync/provider_registry.py:ProviderRegistry.coach_refresh_targets`, `backend/coach/prompt.py:COACH_PROMPT`; `tests/test_coach_refresh_targets.py`.

### Requirement: CP7 Bounded local reads and analysis parity
The system SHALL provide read-only tools for exact local records and deterministic analysis without treating tool reads as permission to write.

#### Scenario: Recent and exact activity reads
- **WHEN** the Coach requests recent activities or one exact activity's detail by local or provider ID
- **THEN** it receives the bounded local recent view or sanitized exact-activity analysis; ordinary recent reads do not refresh the provider.

#### Scenario: Selected deterministic report
- **WHEN** `get_training_report` requests supported report, endurance, power-profile, tag-impact, season, comparison, body-history or sleep-timing-variability (`sleep_timing_variability`) sections
- **THEN** the tool uses the corresponding local analysis owners, bounds the combined result and reports completeness.

#### Scenario: Sleep timing section is the context summary
- **WHEN** `get_training_report` selects `sleep_timing_variability`
- **THEN** it returns the Coach context's per-series summary plus each series' last 14 nights, without the UI's 84-night chart points.

#### Scenario: Weekly progress over 4 to 12 weeks
- **WHEN** `get_training_report` requests the `progress` section alone, for `days` 7, 28, 42, 56 or 84
- **THEN** it receives per-ISO-week run, ride and strength buckets (sessions, duration, load, session-RPE AU, 3-zone approximation, plan compliance) with the local fitness (M7, key `ctl`) and mean-max ride power and run speed change per environment (canonical full-resolution curves); the running week and weeks without records are incomplete or unknown, never rest, and window metrics follow the sport filter.

#### Scenario: Week status and zone bands
- **WHEN** a progress week is listed
- **THEN** its status is `future`, `recorded`, `incomplete_current_week`, `incomplete_current_week_no_records` or `no_records_unknown`; a week with sessions lists the buckets `all`, `run`, `ride` and `strength` (or only the filtered sport) and names commutes as `commute_sessions` and `commute_duration_s`; a session's 3-zone approximation uses its power zones, else its heart-rate zones, only in the local zone model, with 6 or more zones Z1-2 low, Z3-4 moderate and Z5 upward high and with up to 5 zones Z1-2, Z3 and Z4 upward.

#### Scenario: Mean-maximal change in progress
- **WHEN** the mean-max change of a progress window is built
- **THEN** it compares the best value at 60, 300 and 1200 s of the earlier and the later half per environment, the halves splitting at the middle of the weeks that have started; with fewer than two started weeks the window metrics are `insufficient_data` and outside the curve window `outside_curve_window`.

#### Scenario: Invalid report or missing owner
- **WHEN** unsupported sections (including the retired section name `sleep_regularity`), invalid list parameters or unavailable report services are requested
- **THEN** the system returns a validation/unavailable error rather than a misleading empty successful report.

#### Scenario: Recovery reads carry their limits
- **WHEN** the Coach receives the personal recovery comparison, sleep goal shortfall or sleep timing variability through the context or `get_training_report`
- **THEN** the supplied note and the tool description state that quartile positions compare the athlete's own earlier values, that sleep timing variability is not the Sleep Regularity Index, and that an isolated deviation gives no diagnosis, training clearance or training change; the Coach prompt needs no additional rule for this.

#### Scenario: Performance at equal effort
- **WHEN** `get_training_report` returns `progress` or `block_review` for at least two started weeks inside the curve window
- **THEN** `equal_effort` reports per sport and indoor or outdoor the median output per heart beat of steady sessions with sound data (rides with power W/bpm, runs m/s per bpm x 100; rides without power stay out) for the requested sports for the earlier and the later half, with median heart rate and temperature, the change in percent and `effort_differs` when the halves' median heart rates differ by more than 8 bpm, with each half's stream sources and `sources_differ` when they change; fewer than three steady sessions in a half stay `not_covered`.

#### Scenario: Block review
- **WHEN** `get_training_report` requests the `block_review` section alone (default: the last 4 whole weeks; `start` and `days` 28, 42, 56 or 84 choose another period; `since_last_test` starts on the Monday of the last completed local test unit's week with the shortest of 28, 56 or 84 days reaching today, else 56 days, and `last_test` names that day or null)
- **THEN** it receives a read-only, descriptive comparison of planned and completed volume and compliance per sport, the completed intensity distribution against `training_model`, key sessions by session focus (threshold, vo2max, long, leg strength; derived focus counted), the CTL/mean-max trend, pace at a fixed 10 bpm heart-rate band (steady runs after a 10-minute warm-up, flat samples within 3 % slope, grade-adjusted where a slope or altitude stream exists, earlier versus later half per environment; hilly, trail, no-heart-rate or terrain-unknown runs and fewer than two usable sessions in the block or a half without one stay `not_covered`, never zero), session-RPE per week, check-in score shifts, bounded athlete feedback notes as untrusted text and at most four deterministic `lessons` with evidence strength; unknown data adds no lesson and `planning_brief.lessons` carries the same lessons for plan requests.

#### Scenario: Block review lessons
- **WHEN** the block review derives its lessons
- **THEN** each lesson has `code`, `text`, `evidence_strength: limited` and `basis`, at most four are kept in this order, and the codes are: `low_compliance` (at least 4 planned units and under 50 % completed), `long_weekday_missed` (at least 2 planned units with the focus `long` on Monday to Friday and under 50 % completed), `distribution_off_model` (a completed intensity band more than 5 percentage points outside the model range in a week that is judged as in CA11), `rpe_rising` (a session-RPE load per rated session that rises over at least 3 consecutive weeks of at least 2 rated sessions each) and `soreness_rising`, `stress_rising` or `motivation_falling` (at least 3 check-ins in each half of the block and a mean shift of at least 2.0 in the concerning direction); the feedback notes are the last 10, cut to 200 characters, under the method `block-review-v1`.

Evidence:
- `backend/coach/activity_read_tools.py:CoachActivityReadToolService.execute`
- `backend/coach/context.py:coach_performance_projection`
- `backend/coach/read_tools.py:CoachReadToolService._execute_domain_read`
- `backend/coach/tool_schemas.py` (`get_training_report`)
- `backend/performance/comparable_sessions.py:equal_effort_trend`
- `backend/performance/pace_at_hr.py:pace_at_heart_rate_trend`
- `backend/performance/progress_report.py:weekly_progress`
- `backend/planning/block_review.py:block_lessons`
- `backend/planning/block_review.py:block_review`
- `tests/test_block_review.py`
- `tests/test_block_review.py:test_falling_motivation_is_the_concern_and_empty_start_is_ignored`
- `tests/test_block_review.py:test_partly_missed_block_yields_lessons`
- `tests/test_block_review.py:test_rising_session_rpe_lesson`
- `tests/test_coach_activity_read_tools.py:test_detail_returns_the_v1_document_with_its_envelope`
- `tests/test_coach_activity_read_tools.py:test_report_can_select_body_history_and_sleep_timing_variability`
- `tests/test_coach_activity_read_tools.py:test_report_can_select_comparisons_and_rejects_unknown_section`
- `tests/test_coach_read_tools.py:test_dispatches_every_read_tool_and_projects_existing_shapes`
- `tests/test_coach_read_tools.py:test_invalid_limits_keep_bad_request_reason`
- `tests/test_coach_tool_coverage.py:test_training_report_returns_same_local_facts_without_mutation`
- `tests/test_comparable_sessions.py:EqualEffortTrendTests`
- `tests/test_pace_at_hr.py`
- `tests/test_performance_coach_ui_parity.py`
- `tests/test_personal_recovery_coach_cases.py`
- `tests/test_weekly_progress.py`
- `tests/test_zone_time_reads.py:test_three_zone_intensity_counts_local_zones_only`

### Requirement: CP8 External text is evidence only
The system SHALL isolate provider, calendar, attachment and stored product text as untrusted context data, prevent it from reproducing context fence delimiters, and keep credentials and raw transport payloads out of the Coach projection.

#### Scenario: Embedded instruction-like calendar text
- **WHEN** external text contains commands or the same words as a context fence delimiter
- **THEN** the emitted context defangs the delimiter and keeps the content inside the untrusted-data boundary; it supplies no athlete-message authorization.

#### Scenario: Raw snapshot fields
- **WHEN** a saved provider snapshot contains fields outside the allowed coaching projection
- **THEN** those raw fields are excluded from the structured Coach sections.

#### Scenario: Request telemetry
- **WHEN** request/context size telemetry is emitted
- **THEN** it contains sizes, counts and selection metadata rather than athlete messages or provider payload bodies.

Evidence: `backend/coach/context.py:_defanged`, `backend/coach/context.py:CoachTrainingContextService.build`, `backend/coach/context.py:CoachIntervalsContextService.project`; `backend/coach/request_payload.py:CoachRequestPayloadService`; `tests/test_coach_training_context.py:test_external_text_cannot_reproduce_the_untrusted_data_fence`; `tests/test_coach_structured_context.py:test_build_uses_snapshot_fallback_and_projects_safe_provider_context`; `tests/test_coach_context_reduction.py:test_request_keeps_tools_and_telemetry_contains_no_athlete_content`. Prompt separation is inspected; resistance to every natural-language injection is not proven by these tests.

### Requirement: CP9 Inspectable context preview
The system SHALL expose an authenticated preview of the full Coach context (not a turn's selection) and conversation continuity information without credentials or inline attachment file data.

#### Scenario: Preview current evidence
- **WHEN** the athlete opens `/api/context-preview`
- **THEN** the response includes the current context layout, local snapshot timing, last-message information and relevant bounded projections for inspection.

#### Scenario: Long or private input
- **WHEN** source sections or messages exceed preview limits or contain transport-only fields
- **THEN** `context_text` (within the total character budget), `projection` and `local_training_library` are bounded; `structured_athlete_context` and `latest_activities` are the full structured context as built, without the section budgets, and the response excludes prohibited credential/session/raw data while retaining useful source information.

#### Scenario: Conversation explanation
- **WHEN** preview describes the Responses conversation chain
- **THEN** it explains dialogue continuity independently from authoritative local profile and competition facts.

Evidence: `backend/http_api/athlete_get.py:AthleteGetRoutes.routes`; `backend/coach/context.py:CoachContextPreviewService.preview`; `tests/test_coach_context_preview.py:test_preview_layout_snapshot_last_message_and_read_calls`, `tests/test_coach_context_preview.py:test_projection_bounds_and_privacy`, `tests/test_coach_context_preview.py:test_conversation_preview_documents_responses_chain`.

### Requirement: Coach activity context uses neutral activity summaries
The Coach context SHALL list recent activities from the neutral activity summaries of every provider, one per session, with the local session id, canonical sport and environment, neutral value keys, `load_model` and source labels, and SHALL NOT expose provider field names or type names.

#### Scenario: Unchanged values and labels
- **WHEN** the Coach context is built from synthetic activity summaries
- **THEN** each activity's values, the per-sport rollups and the source labels equal the former raw-row context, under the neutral keys; summaries of Intervals.icu rows of a database restored from an earlier release keep their values and `Intervals.icu` label.

#### Scenario: Garmin-only session
- **WHEN** a recent session has only a Garmin Connect record
- **THEN** it appears in the Coach context with its Garmin values and source label and without a training load.

Evidence: `backend/coach/context.py:compact_coach_activity`, `backend/coach/context.py:CoachIntervalsContextService`; `tests/test_coach_activity_summary_parity.py`, `tests/test_coach_intervals_context.py`.

### Requirement: Planning calendar horizon
The system SHALL provide planning turns a compact projection of all external events overlapping the planning horizon and count events omitted by the context budget. Event descriptions SHALL not enter this projection, and external event text remains untrusted.

#### Scenario: Planning and ordinary chat
- **WHEN** a week or block planning turn is built
- **THEN** events overlapping 14 or 35 days respectively are considered without a row cap, including events without descriptions; ordinary chat retains its relevance filter.

#### Scenario: Context budget
- **WHEN** events exceed the section budget
- **THEN** the projection states the number omitted.

Evidence: `backend/coach/context.py:CoachPlanningContextReader.external_calendar`; `tests/test_calendar_planning.py:test_horizon_projection_and_budget`; `tests/test_coach_structured_context.py:test_plan_kinds_use_full_calendar_horizons`; `tests/test_coach_context_reduction.py:test_total_budget_reports_omitted_calendar_event_count`.

### Requirement: Calendar busy time in planning brief
The planning brief SHALL summarize daily busy minutes from external events without double-counting overlaps.

#### Scenario: Overlapping events
- **WHEN** two events overlap on a planning day
- **THEN** only their union contributes to that day's busy minutes.

Evidence: `backend/planning/calendar_load.py:busy_minutes`, `backend/planning/plan_guard_service.py:PlanGuardService.brief`; `tests/test_calendar_planning.py:test_busy_minutes_union_and_midnight`.

### Requirement: Coach and plan share the resolved thresholds
The system SHALL give the Coach context the same current FTP, threshold heart rate and maximum heart rate that plan zones and planned loads use on that day, resolved by one source policy (local zone configuration, then Garmin, then Wahoo; Intervals.icu is never a source). The Coach thresholds SHALL name the FTP source and, when another source holds a different current FTP, list it as an alternative with a conflict flag.

#### Scenario: Garmin and Wahoo FTP differ
- **WHEN** Garmin reports 280 W, Wahoo holds 265 W and no local zone configuration applies
- **THEN** `thresholds.ftp_w` is 280 with `ftp_source` Garmin Connect, `ftp_alternatives` lists Wahoo 265 W, `ftp_conflict` is true, and planned loads and zones use 280 W; an Intervals.icu value is ignored.

#### Scenario: Local zone configuration
- **WHEN** the athlete has a confirmed local power zone configuration in effect today
- **THEN** both the Coach thresholds and the plan use its FTP, labelled as local.

Detailed contract: the plan playbook tells the Coach to use these thresholds for targets and to name a flagged conflict once. Each current metric with other current sources carries `alternatives` (value, source label, provider id) and `conflict`.

Evidence: `backend/performance/current_metrics.py:coach_thresholds`, `backend/performance/canonical_current.py:read_current_inputs`, `backend/planning/load_checks.py:load_thresholds`, `backend/coach/playbooks.py:_THRESHOLDS`; `tests/test_current_thresholds.py:CoachAndPlanParityTests`, `tests/test_current_thresholds.py:ResolverTests.test_ftp_conflict_keeps_both_values_visible`.

### Requirement: Subjective ratings carry scale, direction and source
The system SHALL give every subjective rating that reaches the Coach (activity RPE and feel from Garmin rows, check-in and activity feedback scores) with its scale, direction and athlete-entered source. Same-named ratings of different scales SHALL never be presented as comparable numbers. The Intervals.icu 1–4 wellness ratings (fatigue, soreness, stress, mood) are no Coach input any more (#1728).

#### Scenario: Ratings of different scales
- **WHEN** the context carries an activity `feel` (1–5, 1 = best) or `rpe` (1–10) from a provider and check-in soreness or stress (0–10, higher is worse) in `local_feedback`
- **THEN** Coach rule 8h names each field's scale, direction and source and forbids comparing or averaging ratings of different scales; it names no Intervals.icu rating.

#### Scenario: Activity detail ratings
- **WHEN** `get_activity_details` serves a session
- **THEN** it carries no Intervals.icu RPE or feel from the provider summary row (#1685); the athlete's own rating stays in `activity_feedback` with its local scale.

Detailed contract: ratings keep the entered number; each field's scale is fixed by where it was entered and resolved at read time from `backend/canonical/rating_scales.py`, so stored rows need no replay. The legend is constant, so it is rule 8h of the fixed Coach prompt instead of per-turn context; tests check the rule against those scales. Session-RPE load entries name their `rpe_scale` (local 0–10 or a provider scale) and keep their values. The Intervals.icu wellness scale table in `backend/canonical/rating_scales.py` remains for retired rows.

Evidence: `backend/canonical/rating_scales.py:RatingScale`, `backend/performance/session_rpe_load.py:session_load`, `backend/coach/prompt.py:COACH_PROMPT`; `tests/test_subjective_rating_scales.py`.

### Requirement: CP10 Context content, fitting and layout
The system SHALL build each context section from allowlisted fields, measure sizes as the length of the compact JSON text, fit oversized values deterministically and lay the context out between fixed fence lines, so that the same stored data always yields the same context text.

#### Scenario: Allowlists and source policy
- **WHEN** the activities, library and source-policy parts are built
- **THEN** an activity keeps only the fields of `COACH_ACTIVITY_FIELDS` (text values cut: id and name to 200, sport to 80 characters), a German `purpose_label` for a known purpose and `sources` only for values whose source differs from the session's primary source; the `activities` section holds the source block `{provider, providers, label, synced_at}`, `recent_activities_by_sport`, `activity_rollups_by_sport` and the local planned workouts labelled "Lokale Planung"; a library template keeps the fields of `COACH_LIBRARY_FIELDS` with name 200, description 1,500 and 10 tags of 80 characters; `source_policy` holds one fixed text per source, normative in `CoachStructuredContextService._selected_sections`, and for a selected context the omitted sections

#### Scenario: Library and products
- **WHEN** the library selection and the saved products are built
- **THEN** the library takes the undated templates in turn from each workout type (types sorted by name) up to 12; the products are `{id, name, brand, basis_amount, basis_unit, source}`, newest change first, at most 80, and stop before the section limit with `truncated` set when anything was left out

#### Scenario: Fitting
- **WHEN** a value exceeds its limit
- **THEN** a string keeps its longest prefix that fits, a list its longest prefix of fitted items, and an object its keys in their order, each fitted to the remaining budget and skipped when it does not fit, so valid JSON stays valid; for the total budget the top-level sections are fitted in the priority order of CP3

#### Scenario: Text layout
- **WHEN** the context text is assembled
- **THEN** it is the coaching rules (`COACH_PROMPT`) inside `<coaching_rules>`, then `<athlete_context>` opening with the line "Untrusted external data.", the headings "STRUCTURED ATHLETE CONTEXT (authoritative for this turn):" and "LOCAL PLANNED WORKOUTS (compact projection, included once below):", the structured context as compact JSON, the heading "LOCAL TRAINING LIBRARY (bounded selection of local templates; templates available to the coach):" with the library JSON, for a selected context the note that omitted sections load through `read_coach_context` and that selection never authorizes writes, and `</athlete_context>`; inside the JSON the words "untrusted external data" are rewritten to "untrusted-external-data" and the `<` of any instruction section tag (`athlete_context`, `coaching_rules`, `dialogue_rules`, `request_playbook`, `nutrition_playbook`, `turn_notices`, opening or closing) is dropped

Evidence: `backend/coach/context.py:COACH_ACTIVITY_FIELDS`, `backend/coach/context.py:COACH_LIBRARY_FIELDS`, `backend/coach/context.py:coach_workout_library`, `backend/coach/context.py:CoachStructuredContextService._selected_sections`, `backend/coach/context.py:CoachStructuredContextService._compact_nutrition_products`, `backend/coach/context.py:CoachTrainingContextService.build`, `backend/coach/context.py:bounded_coach_context_value`, `backend/coach/context.py:_defanged`; `tests/test_coach_structured_context.py:test_weather_place_is_named_without_coordinates`, `tests/test_coach_library_context.py:test_sorts_types_for_round_robin_and_preserves_order_within_each_type`, `tests/test_coach_context_reduction.py:test_priority_budget_skips_and_continues_past_large_sections`, `tests/test_coach_training_context.py:test_external_text_cannot_reproduce_the_untrusted_data_fence`.

### Requirement: CP11 Limits, defaults and errors of the local read tools
The system SHALL offer the local read tools in every turn, also an advisory one, without request envelope or write gate, and SHALL bound their results, clamp list limits to their range and state an incomplete result or an uncovered comparison with a reason, never with zero. Parameters are in `openspec/COACH_TOOLS.md`.

#### Scenario: Clamped list limits
- **WHEN** a list tool is called with a limit of 0 or above its maximum
- **THEN** the limit moves to the nearest bound and the call succeeds: `list_workout_library` 1 to 100 (default 100), `list_planned_workouts` 1 to 366 (default 100), `list_change_history` 1 to 500 (default 100), `list_recent_activities` `days` 1 to 3,660 (default 30) and `limit` 1 to 500 (default 100); a value that is no integer fails with 400 `invalid_list_request` ("Bibliothekslimit ist ungültig.", "Planungslimit ist ungültig.", "Historienlimit ist ungültig." or "Aktivitätszeitraum oder Limit ist ungültig."); `list_training_plans` returns at most 100 plans and `list_recent_activities` leaves out the per-field sources and zone-time arrays of each session

#### Scenario: Reports and records
- **WHEN** `get_training_report` or `read_training_records` is called
- **THEN** `get_training_report` defaults to the section `report`, or to `progress` for a window of 42, 56 or 84 days, accepts 1 to 10 of its ten sections, allows `progress`, `block_review` and the long windows only alone (400 "progress, block_review und 42, 56 oder 84 Tage nur allein abrufbar."), rejects an unknown section (400 "Unbekannter Analysebereich.") and returns each requested section with `projection {requested_sections, complete}` cut to 30,000 characters; `read_training_records` is cut to 30,000 characters; unwired report services fail with 503 "Trainingsberichte sind nicht verfügbar." or "Trainingsprotokolle sind nicht verfügbar."

#### Scenario: Planned units beside a session
- **WHEN** `get_activity_details` returns a session
- **THEN** `planned_units` holds at most 10 local planned units dated within one day of the session (at most 4,000 characters, null when planned units are unavailable), and `focus` is `{status: matched, ...}` when exactly one planned unit has the session's day and sport, else `{status: unknown, reason}` with "Geplante Einheiten nicht verfügbar.", "Keine geplante Einheit dieses Tages und Sports.", "Mehrere geplante Einheiten dieses Tages und Sports." or "Die geplante Einheit hat kein Ziel."; a comparison that is not covered is `{status: not_covered, reason}`, for example "E-Bike-Einheiten werden nicht verglichen (Motorunterstützung)." or "Pendeln, Einfahren und Ausfahren werden nicht verglichen."

#### Scenario: Nutrition reads
- **WHEN** `read_nutrition`, `lookup_food` or `calculate_food_nutrition` is called
- **THEN** `read_nutrition` returns the day's summary for `date`, the summaries of a range of at most 31 days for `start` and `end` (400 `range_too_large` beyond that) or today's summary, always with the meal templates and saved products, and `{ok: false, error}` when the nutrition service is not wired; `lookup_food` takes `query` and `queries` together (1 to 20 distinct terms, no `barcode` beside `queries`) and returns one result per term, failing as a whole only when every term fails; with an explicit source whose external lookup fails it still returns saved matching products with a notice; `calculate_food_nutrition` refuses `components` combined with `ingredients` or `product_id` (400); a missing food database fails with 503 "Lebensmitteldatenbank ist nicht verfügbar."; none of them saves anything, and the two food-database tools run outside the local transaction

Evidence:
- `backend/coach/activity_read_tools.py:_report_sections`
- `backend/coach/activity_read_tools.py:CoachActivityReadToolService._with_session_context`
- `backend/coach/activity_read_tools.py:CoachActivityReadToolService.execute`
- `backend/coach/read_tools.py:CoachReadToolService._calculate_food`
- `backend/coach/read_tools.py:CoachReadToolService._execute_domain_read`
- `backend/coach/read_tools.py:CoachReadToolService._lookup_food`
- `backend/coach/read_tools.py:CoachReadToolService._read_nutrition`
- `backend/coach/session_checks.py:matched_focus`
- `tests/test_coach_activity_read_tools.py:test_recent_activities_keep_scalars_and_drop_per_field_detail`
- `tests/test_coach_activity_read_tools.py:test_report_can_select_comparisons_and_rejects_unknown_section`
- `tests/test_coach_read_tools.py:test_limit_bounds_saturate_and_optional_filters_are_forwarded`
- `tests/test_coach_read_tools.py:test_nutrition_range_is_validated_and_bounded`
- `tests/test_coach_session_checks.py:test_an_e_bike_session_says_it_is_not_compared`
- `tests/test_coach_tool_coverage.py:test_food_database_read_tools_calculate_without_writing`
- `tests/test_coach_tool_schemas.py:test_read_limits_declare_server_clamp_bounds`
