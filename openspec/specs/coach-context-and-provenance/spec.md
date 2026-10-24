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

Evidence: `backend/coach/context.py:bounded_coach_context_sections`, `backend/coach/context.py:coach_context_projection_meta`, `backend/coach/context.py:CoachTrainingContextService.build`; `tests/test_coach_training_context.py:test_section_and_total_truncation_keep_valid_bounded_context`; `tests/test_coach_context_reduction.py:test_oversized_single_section_retains_useful_prefix`; `tests/test_coach_context_selection.py:test_date_window_and_activity_limits_preserve_provenance`.

### Requirement: CP4 On-demand omitted context
The system SHALL support read-only loading of named local Coach context sections, report whether the bounded result is complete, and reject invalid section requests.

#### Scenario: Load omitted recovery or planning
- **WHEN** the Coach calls `read_coach_context` for valid omitted sections
- **THEN** the system reads those sections locally and returns requested-section and completeness metadata while retaining the turn's offered tool availability without refreshing providers or authorizing mutations.

#### Scenario: Result exceeds detail budget
- **WHEN** the requested sections exceed the 40000-character result budget
- **THEN** the result is bounded and `projection.complete` is false so narrower reads can be requested.

#### Scenario: Invalid or unavailable sections
- **WHEN** the request contains no sections, more than fifteen, an unknown section, or the context service is unavailable
- **THEN** it fails explicitly rather than returning invented or raw snapshot data.

Evidence: `backend/coach/read_tools.py:CoachReadToolService._read_coach_context`; `backend/coach/structured_tool_round.py:CoachStructuredToolRoundService`; `tests/test_coach_context_reduction.py:test_detail_read_bounds_output_and_rejects_unknown_sections`; `tests/test_coach_context_selection.py:test_rephrased_requests_offer_required_registered_tools`.

### Requirement: CP5 Saved provider evidence and honest freshness
The system SHALL build ordinary Coach context from saved provider observations and local planning, retain available source/sync metadata, and read cached weather without causing an unconditional provider refresh.

#### Scenario: Ordinary context read
- **WHEN** the athlete sends an ordinary Coach message
- **THEN** context assembly reads saved data and weather with refresh disabled rather than issuing provider calls for every message.

#### Scenario: Missing Intervals snapshot
- **WHEN** the saved Intervals snapshot is empty
- **THEN** the context permits the implemented Garmin performance fallback while keeping provider recovery separate and unavailable evidence explicit.

#### Scenario: Local calendar planning
- **WHEN** context combines planned units, competitions and external calendar entries
- **THEN** calendar items identify their local-plan, competition or external-calendar origin; external calendar context is read-only.

Evidence: `backend/coach/context.py:CoachStructuredContextService.build`, `backend/coach/context.py:CoachPlanningContextReader.calendar`, `backend/coach/context.py:CoachPlanningContextReader.external_calendar`, `backend/coach/context.py:CoachPerformanceContextReader.current_performance`; `tests/test_coach_structured_context.py:test_build_uses_snapshot_fallback_and_projects_safe_provider_context`, `tests/test_coach_structured_context.py:test_explicit_snapshot_is_used_without_fallback_and_empty_snapshot_enables_garmin_fallback`. Per-metric provenance is owned by performance/provider capabilities; this requirement does not assert that every legacy section label identifies every canonical provider correctly.

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
- **WHEN** `get_training_report` requests supported report, endurance, power-profile, tag-impact, season, comparison, body-history or sleep-regularity sections
- **THEN** the tool uses the corresponding local analysis owners, bounds the combined result and reports completeness.

#### Scenario: Invalid report or missing owner
- **WHEN** unsupported sections, invalid list parameters or unavailable report services are requested
- **THEN** the system returns a validation/unavailable error rather than a misleading empty successful report.

Evidence: `backend/coach/activity_read_tools.py:CoachActivityReadToolService.execute`; `backend/coach/read_tools.py:CoachReadToolService._execute_domain_read`; `tests/test_coach_read_tools.py:test_dispatches_every_read_tool_and_projects_existing_shapes`, `tests/test_coach_read_tools.py:test_invalid_limits_keep_bad_request_reason`; `tests/test_coach_tool_coverage.py:test_training_report_returns_same_local_facts_without_mutation`; `tests/test_coach_activity_read_tools.py:test_detail_uses_local_sources_and_keeps_sanitized_detail_projection`, `tests/test_coach_activity_read_tools.py:test_report_can_select_comparisons_and_rejects_unknown_section`.

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
