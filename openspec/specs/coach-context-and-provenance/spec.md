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

Evidence: `backend/coach/context_selection.py:select_coach_context`, `backend/coach/context_selection.py:compact_coach_dialogue`; `tests/test_coach_context_selection.py:test_explicit_dates_without_planning_keywords_use_full_context`, `tests/test_coach_context_selection.py:test_long_range_planning_uses_complete_context`, `tests/test_coach_context_selection.py:test_dialogue_compaction_does_not_mutate_authorization_context`; `tests/test_coach_context_reduction.py:test_scoped_assembly_skips_unnecessary_reads`.

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

Evidence: `backend/coach/context.py:bounded_coach_context_sections`, `backend/coach/context.py:coach_context_projection_meta`, `backend/coach/context.py:CoachTrainingContextService.build`; `tests/test_coach_training_context.py:test_section_and_total_truncation_keep_valid_bounded_context`; `tests/test_coach_context_reduction.py:test_oversized_single_section_retains_useful_prefix`, `tests/test_coach_context_reduction.py:test_pending_data_marker_survives_scoped_planning_projection`; `tests/test_coach_context_selection.py:test_date_window_and_activity_limits_preserve_provenance`; `tests/test_coach_context_budget.py:CoachContextBudgetTests.test_sections_and_budget_per_kind`, `tests/test_coach_context_budget.py:CoachContextBudgetTests.test_size_diagnostics_name_the_selection_and_sections_for_every_kind`.

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
The system SHALL build ordinary Coach context from saved provider observations and local planning, retain available source/sync metadata, and read cached weather without causing an unconditional provider refresh. The `activities` section SHALL report its sync time (`synced_at` and `source.synced_at`) from the Intervals.icu activity fetch time of the canonical provider coverage, read in the same read snapshot as the activity rows, and SHALL report null when no coverage is stored.

#### Scenario: Ordinary context read
- **WHEN** the athlete sends an ordinary Coach message
- **THEN** context assembly reads saved data and weather with refresh disabled rather than issuing provider calls for every message.

#### Scenario: Missing Intervals snapshot
- **WHEN** the saved Intervals snapshot is empty
- **THEN** the context permits the implemented Garmin performance fallback while keeping provider recovery separate and unavailable evidence explicit.

#### Scenario: Recovery section from canonical records
- **WHEN** the Coach recovery section is built
- **THEN** sleep, HRV, resting HR and readiness each show the latest canonical Garmin record of the last 14 days (`date` plus neutral fields such as `sleep_seconds`, `sleep_score`, the night values `avg_spo2_pct`, `lowest_spo2_pct`, `avg_respiration_brpm` and `avg_sleeping_hr_bpm`, `last_night_avg_ms`, `weekly_avg_ms`, `resting_hr_bpm`, `score`, and the provider status codes `status` and `level`; the sleep record adds `night_means` with each night value's mean and night count over those 14 days), Body Battery the stored morning record, and the sync time, window, freshness and errors come from the Garmin sync status, read in the same read transaction as the records; the raw Garmin view is not read, and the Garmin performance fallback is requested only when the canonical provider coverage holds no Intervals.icu sync.

#### Scenario: Local calendar planning
- **WHEN** context combines planned units, competitions and external calendar entries
- **THEN** calendar items identify their local-plan, competition or external-calendar origin; external calendar context is read-only.

#### Scenario: Activities freshness from canonical coverage
- **WHEN** the context includes the activities section and canonical coverage stores an Intervals.icu activity fetch time
- **THEN** the section's `synced_at` and `source.synced_at` equal that time regardless of the stored snapshot's `synced_at` or of a duplicate deletion, and are null when no coverage is stored.

Evidence: `backend/coach/context.py:CoachStructuredContextService.build`, `backend/coach/context.py:CoachPlanningContextReader.calendar`, `backend/coach/context.py:CoachPlanningContextReader.external_calendar`, `backend/coach/context.py:CoachPerformanceContextReader.current_performance`, `backend/coach/context.py:CoachIntervalsContextService.project`; `tests/test_coach_structured_context.py:test_build_uses_snapshot_fallback_and_projects_safe_provider_context`, `tests/test_coach_structured_context.py:test_explicit_snapshot_is_used_without_fallback_and_empty_snapshot_enables_garmin_fallback`. Per-metric provenance is owned by performance/provider capabilities; this requirement does not assert that every legacy section label identifies every canonical provider correctly. Missing evidence (planned in this change): activities section `synced_at` from coverage and null without coverage.

### Requirement: CP6 Explicit provider refresh and current results
The system SHALL route a requested provider update through the existing provider refresh owners, distinguish queued work from completed refreshed data, and use refreshed local context before the subsequent model response where the provider contract waits for completion.

#### Scenario: Explicit current-data refresh
- **WHEN** a supported explicit refresh is selected in an athlete-started turn
- **THEN** the existing provider-specific refresh path is used and refreshed local context is available before the next model response on waiting refresh paths.

#### Scenario: Queued refresh
- **WHEN** the provider refresh is queued
- **THEN** the tool returns a sync-job reference whose current status can be read with `get_sync_job`; queuing alone is not proof that data is current.

#### Scenario: Refresh failure
- **WHEN** a refresh fails or its job remains pending
- **THEN** that tool result remains distinguishable from a successful refresh, and saved context remains saved evidence rather than a new provider measurement.

Evidence: `backend/coach/sync_tools.py:CoachSyncToolService.execute`; `backend/coach/tool_preparation.py:CoachStructuredToolPreparationService._waits_for_completion`; `tests/test_coach_dialogue.py:test_current_refresh_runs_before_next_model_response_without_trigger_gate`, `tests/test_coach_dialogue.py:test_garmin_refresh_waits_for_completion_without_queueing`, `tests/test_coach_dialogue.py:test_queued_refresh_and_job_read_use_current_tool_results`; `tests/test_coach_tool_coverage.py:test_provider_reads_and_job_status_use_correct_provider`.

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

#### Scenario: Weekly progress over 6 or 12 weeks
- **WHEN** `get_training_report` requests the `progress` section alone, for `days` 7, 28, 42 or 84
- **THEN** it receives per-ISO-week run, ride and strength buckets (sessions, duration, load, session-RPE AU, 3-zone approximation, plan compliance) with the local fitness (M7, key `ctl`), eFTP and mean-max ride power and run speed change per environment (canonical full-resolution curves); the running week and weeks without records are incomplete or unknown, never rest, and window metrics follow the sport filter.

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
- **THEN** it receives a read-only, descriptive comparison of planned and completed volume and compliance per sport, the completed intensity distribution against `training_model`, key sessions by session focus (threshold, vo2max, long, leg strength; derived focus counted), the CTL/eFTP/mean-max trend, pace at a fixed 10 bpm heart-rate band (steady runs after a 10-minute warm-up, flat samples within 3 % slope, grade-adjusted where a slope or altitude stream exists, earlier versus later half per environment; hilly, trail, no-heart-rate or terrain-unknown runs and fewer than two usable sessions in the block or a half without one stay `not_covered`, never zero), session-RPE per week, check-in score shifts, bounded athlete feedback notes as untrusted text and at most four deterministic `lessons` with evidence strength; unknown data adds no lesson and `planning_brief.lessons` carries the same lessons for plan requests.

Evidence: `backend/planning/block_review.py:block_review`; `tests/test_block_review.py`; `backend/performance/comparable_sessions.py:equal_effort_trend`, `tests/test_comparable_sessions.py:EqualEffortTrendTests`; `backend/performance/pace_at_hr.py:pace_at_heart_rate_trend`; `tests/test_pace_at_hr.py`; `backend/coach/activity_read_tools.py:CoachActivityReadToolService.execute`; `backend/coach/read_tools.py:CoachReadToolService._execute_domain_read`; `backend/coach/tool_schemas.py` (`get_training_report`); `backend/coach/context.py:coach_performance_projection`; `tests/test_coach_read_tools.py:test_dispatches_every_read_tool_and_projects_existing_shapes`, `tests/test_coach_read_tools.py:test_invalid_limits_keep_bad_request_reason`; `tests/test_coach_tool_coverage.py:test_training_report_returns_same_local_facts_without_mutation`; `tests/test_coach_activity_read_tools.py:test_detail_uses_local_sources_and_keeps_sanitized_detail_projection`, `tests/test_coach_activity_read_tools.py:test_report_can_select_comparisons_and_rejects_unknown_section`, `tests/test_coach_activity_read_tools.py:test_report_can_select_body_history_and_sleep_timing_variability`; `backend/performance/progress_report.py:weekly_progress`; `tests/test_weekly_progress.py`; `tests/test_personal_recovery_coach_cases.py`, `tests/test_performance_coach_ui_parity.py`.

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
The system SHALL expose an authenticated bounded preview of the Coach context and conversation continuity information without credentials or inline attachment file data.

#### Scenario: Preview current evidence
- **WHEN** the athlete opens `/api/context-preview`
- **THEN** the response includes the current context layout, local snapshot timing, last-message information and relevant bounded projections for inspection.

#### Scenario: Long or private input
- **WHEN** source sections or messages exceed preview limits or contain transport-only fields
- **THEN** the response is bounded and excludes prohibited credential/session/raw data while retaining useful source information.

#### Scenario: Conversation explanation
- **WHEN** preview describes the Responses conversation chain
- **THEN** it explains dialogue continuity independently from authoritative local profile and competition facts.

Evidence: `backend/http_api/athlete_get.py:AthleteGetRoutes.handle`; `backend/coach/context.py:CoachContextPreviewService.preview`; `tests/test_coach_context_preview.py:test_preview_layout_snapshot_last_message_and_read_calls`, `tests/test_coach_context_preview.py:test_projection_bounds_and_privacy`, `tests/test_coach_context_preview.py:test_conversation_preview_documents_responses_chain`.

### Requirement: Coach activity context uses neutral activity summaries
The Coach context SHALL list recent activities from the neutral activity summaries of every provider, one per session, with the local session id, canonical sport and environment, neutral value keys, `load_model` and source labels, and SHALL NOT expose provider field names or type names. For Intervals.icu-only data the values and source labels SHALL stay as before.

#### Scenario: Intervals.icu-only parity
- **WHEN** the Coach context is built from Intervals.icu-only synthetic activities
- **THEN** each activity's values, the per-sport rollups and the source labels equal the former context, under the neutral keys.

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
The system SHALL give the Coach context the same current FTP, threshold heart rate and maximum heart rate that plan zones and planned loads use on that day, resolved by one source policy. The Coach thresholds SHALL name the FTP source and, when another source holds a different current FTP, list it as an alternative with a conflict flag.

#### Scenario: Garmin and Intervals.icu FTP differ
- **WHEN** Garmin reports 280 W, the Intervals.icu setting is 265 W and no local zone configuration applies
- **THEN** `thresholds.ftp_w` is 265 with `ftp_source` Intervals.icu, `ftp_alternatives` lists Garmin 280 W, `ftp_conflict` is true, and planned loads and zones use 265 W.

#### Scenario: Local zone configuration
- **WHEN** the athlete has a confirmed local power zone configuration in effect today
- **THEN** both the Coach thresholds and the plan use its FTP, labelled as local.

Detailed contract: the plan playbook tells the Coach to use these thresholds for targets and to name a flagged conflict once. Each current metric with other current sources carries `alternatives` (value, source label, provider id) and `conflict`.

Evidence: `backend/performance/current_metrics.py:coach_thresholds`, `backend/performance/canonical_current.py:read_current_inputs`, `backend/planning/load_checks.py:load_thresholds`, `backend/coach/playbooks.py:_THRESHOLDS`; `tests/test_current_thresholds.py:CoachAndPlanParityTests`.

### Requirement: Subjective ratings carry scale, direction and source
The system SHALL give every subjective rating that reaches the Coach (Intervals.icu wellness fatigue, soreness, stress and mood, activity RPE and feel, check-in and activity feedback scores) with its scale, direction and athlete-entered source. Same-named ratings of different scales SHALL never be presented as comparable numbers.

#### Scenario: Same-named soreness from two scales
- **WHEN** the context carries Intervals.icu soreness 3 in `current_performance.recovery` and check-in soreness 3 in `local_feedback`
- **THEN** Coach rule 8h names 1–4 (higher is worse, Intervals.icu, athlete-entered) for the first and 0–10 (higher is worse, local check-in) for the second and forbids comparing or averaging them.

#### Scenario: Activity detail ratings
- **WHEN** `get_activity_details` returns Intervals.icu RPE or feel
- **THEN** the metric source kind is `athlete_entered`, not `measured`, and the metric carries its scale text, a named value's `rating_label` (feel 1 stark … 5 schwach) and `normalized_0_1` (0 best or lowest strain, 1 worst or highest).

Detailed contract: ratings keep the entered number; each field's scale is fixed by where it was entered and resolved at read time from `backend/canonical/rating_scales.py`, so stored rows need no replay. The legend is constant, so it is rule 8h of the fixed Coach prompt instead of per-turn context; tests check the rule against those scales. Session-RPE load entries name their `rpe_scale` (local 0–10 or Intervals.icu 1–10) and keep their values.

Evidence: `backend/canonical/rating_scales.py:RatingScale`, `backend/activities/detail_summary_metrics.py:intervals_summary_metrics`, `backend/performance/session_rpe_load.py:session_load`, `backend/coach/prompt.py:COACH_PROMPT`; `tests/test_subjective_rating_scales.py`.
