## Purpose

Describe local plan drafts, commits, membership/metadata, optimistic edits and replacements, authenticated planning commands and separately approved adaptive changes. This documents existing behavior without authorizing a new plan, remote write or database change.

## ADDED Requirements

### Requirement: TP1 Validated durable local plan drafts
The system SHALL stage normalized local plan artifacts with their creating conversation/turn and current planning revision, bounded to 366 workouts over at most 730 days, without committing or remotely exporting the plan.

#### Scenario: Valid draft
- **WHEN** an authorized stage request contains a nonempty valid workout payload
- **THEN** calendar validation completes before a draft is persisted and the result returns artifact ID and base revision.

#### Scenario: Invalid draft
- **WHEN** workouts are malformed, exceed size/span bounds or conflict with the calendar
- **THEN** the draft is rejected without inserting an artifact or scheduled units.

#### Scenario: Draft persistence
- **WHEN** an accepted draft survives a later turn or process restart
- **THEN** it remains a local artifact reference distinct from committed planned units and remote events.

Evidence: `backend/planning/artifacts.py:validate_structured_plan_limits`; `backend/planning/training_plan_artifact_service.py:TrainingPlanArtifactService.stage`; `tests/test_training_plan_artifact_service.py:test_stage_normalizes_workouts_and_captures_current_revision`, `tests/test_training_plan_artifact_service.py:test_calendar_conflict_creates_no_artifact_row`; `tests/test_planning_artifacts.py:test_accepts_date_span_of_exactly_730_days`, `tests/test_planning_artifacts.py:test_rejects_more_than_366_workouts_before_item_validation`. Restart persistence is storage-inspected; no restart runtime was launched.

### Requirement: TP2 Atomic revision-checked plan commit
The system SHALL commit an available draft into local plan metadata and units atomically, require its current base revision and permitted conversation binding, and make repeated committed-artifact application idempotent.

#### Scenario: Current draft commit
- **WHEN** an authorized commit selects a current available draft
- **THEN** all units/metadata and artifact committed state persist together and the result returns created local unit IDs.

#### Scenario: Repeated or stale artifact
- **WHEN** the artifact is already committed
- **THEN** it returns already-applied without creating duplicates; a missing/unavailable artifact or stale planning revision returns an explicit failure.

#### Scenario: Conversation changed or late failure
- **WHEN** the artifact belongs to another conversation without explicit artifact rebinding, or local plan/status persistence fails late
- **THEN** the operation conflicts or rolls back all local plan writes; explicit artifact selection can use the implemented rebind path while retaining revision validation.

Evidence: `backend/planning/training_plan_artifact_service.py:TrainingPlanArtifactService.commit`, `backend/planning/training_plan_artifact_service.py:TrainingPlanArtifactService._validate_committed_artifact`; `tests/test_training_plan_artifact_service.py:test_successful_commit_is_atomic_and_replay_is_idempotent`, `tests/test_training_plan_artifact_service.py:test_revision_conflict_rejects_stale_draft`, `tests/test_training_plan_artifact_service.py:test_conversation_conflict_and_explicit_rebind`, `tests/test_training_plan_artifact_service.py:test_conditional_status_update_conflict_rolls_back_local_plan_writes`, `tests/test_training_plan_artifact_service.py:test_late_local_plan_failure_rolls_back_all_writes`.

### Requirement: TP3 Local plan creation and reusable-template matching
The system SHALL save a requested plan's sessions locally, optionally create named plan metadata, link created units to that plan and reuse only validated conservative library matches without a remote call.

#### Scenario: Named local plan
- **WHEN** normalized sessions are saved with a plan name
- **THEN** plan metadata spans the created sessions, units carry its plan ID/name and the transaction advances planning state with audit records.

#### Scenario: Matching template
- **WHEN** a saved template satisfies the implemented sport, content, duration and conservative similarity checks
- **THEN** its supported workout content can be copied into the planned unit with library source while retaining the requested local date and plan membership.

#### Scenario: No valid match or storage conflict
- **WHEN** no suitable template exists
- **THEN** the requested validated Coach content is stored locally; a calendar or persistence failure aborts the owning plan transaction rather than leaving partial units.

Evidence: `backend/planning/local_plan_creation_service.py:LocalTrainingPlanCreationService.save`, `backend/planning/local_plan_creation_service.py:LocalTrainingPlanCreationService._save_in_db`, `backend/planning/local_plan_creation_service.py:LocalTrainingPlanCreationService._planned_workout_for_storage`; `backend/planning/library.py:find_similar_library_workout`; `tests/test_planning_library.py:test_exact_and_conservative_near_matches`, `tests/test_planning_library.py:test_no_match_for_unrelated_or_invalid_candidates`; `tests/test_training_plan_artifact_service.py:test_late_local_plan_failure_rolls_back_all_writes`; `tests/test_coach_tool_coverage.py:test_requested_draft_commit_and_metadata_lifecycle`.

### Requirement: TP4 Plan membership, metadata and persistent constraints
The system SHALL expose saved plan constraints and validated metadata, preserve eligible membership during scoped unit changes, update affected date bounds and keep plan-metadata deletion distinct from deleting its scheduled units.

#### Scenario: Metadata edit
- **WHEN** a valid local plan name, goal, date bounds or supported status is updated
- **THEN** the change, audit and planning revision commit together; invalid IDs/status/date order or datetime bounds fail explicitly.

#### Scenario: Membership and constraints
- **WHEN** a change has one unambiguous eligible active plan or explicitly authorized plan membership
- **THEN** membership is derived or validated, affected bounds are updated, and plan-specific constraints stay with the plan rather than becoming permanent profile preferences.

#### Scenario: Metadata removal
- **WHEN** the athlete authorizes deleting plan metadata
- **THEN** only the metadata row is removed; existing scheduled local units remain, and archived/missing or ambiguous memberships are not silently chosen as the current plan.

Evidence: `backend/planning/training_plans.py:TrainingPlanService.update`, `backend/planning/training_plans.py:TrainingPlanService.update_bounds`, `backend/planning/training_plans.py:TrainingPlanService.list`; `backend/planning/changes.py:StructuredTrainingPlanResolver`; `backend/coach/training_patch.py:CoachTrainingPatchService._store_constraints`; `tests/test_training_plans.py:test_update_commits_history_revision_and_event`, `tests/test_training_plans.py:test_delete_and_public_validation_errors_match_server_contract`, `tests/test_training_plans.py:test_update_rejects_datetime_bounds`, `tests/test_training_plans.py:test_list_includes_persisted_constraints`; `tests/test_planning_change_plan_resolution.py:test_multiple_memberships_are_ambiguous_and_archived_or_missing_plans_are_ignored`; `tests/test_coach_training_patch.py:test_approved_constraints_are_attached_to_created_plan`.

### Requirement: TP5 Atomic scoped training changes and patches
The system SHALL apply related moves/edits/archive/restore/delete and additions in one local transaction with final schedule validation, current revision and required per-unit hashes, preserving existing unit identity.

#### Scenario: Valid mixed patch
- **WHEN** the athlete authorizes a bounded patch with current revision, hashes and local-plan scope for additions
- **THEN** all validated changes and additions commit together, existing moved units keep their IDs and the result returns the resulting revision and local unit references.

#### Scenario: Stale or malformed state
- **WHEN** revision or required hash is missing/stale, IDs repeat, the batch is empty/oversized or a requested target escapes scope
- **THEN** no part of the patch is applied and the Coach can reread current state before retrying within original authority.

#### Scenario: Final schedule or late failure
- **WHEN** the final batch overlaps an explicit time window, violates a current marker/calendar constraint or fails during a later addition/revision/bounds write
- **THEN** the whole transaction rolls back; valid same-day sessions are assessed by the implemented overlap policy rather than an unconditional one-per-date promise.

Evidence: `backend/coach/training_patch.py:CoachTrainingPatchService.apply`; `backend/planning/changes.py:StructuredTrainingChangeValidator.validate`, `backend/planning/changes.py:StructuredTrainingChangeService.apply_in_db`; `tests/test_coach_dialogue.py:test_screenshot_followup_moves_and_adds_atomically_without_literal_name`, `tests/test_coach_dialogue.py:test_failed_addition_rolls_back_move_and_revision`, `tests/test_coach_dialogue.py:test_stale_hash_rolls_back_whole_patch`; `tests/test_planning_change_validation.py:test_required_hash_validates_current_payload`, `tests/test_planning_change_validation.py:test_duplicate_final_dates_are_allowed_for_untimed_or_non_overlapping_workouts`; `tests/test_coach_training_patch.py:test_multiple_workouts_on_same_calendar_day_are_applied`.

### Requirement: TP6 Inclusive bounded local plan replacement
The system SHALL replace only selected active local units within the authorized inclusive future period, preserve sessions outside it, retain applicable plan constraints and reserve complete audit capacity before mutation.

#### Scenario: Bounded replacement
- **WHEN** an authorized whole-plan/period replacement has a current revision and valid new sessions
- **THEN** selected old units are locally archived/deleted, replacement units and metadata are created atomically, and later/outside-period sessions remain.

#### Scenario: Shared old plan or constraints
- **WHEN** an old plan still has active units outside the replacement period
- **THEN** its metadata is not archived merely because some units were replaced; explicit new constraints or the implemented inherited constraint set is persisted for the new plan.

#### Scenario: Stale, conflicting or too-large replacement
- **WHEN** revision is stale, a session is past/outside period, time windows/calendar conflict, existing payload is corrupt or the operation cannot fit complete history capacity
- **THEN** replacement aborts without partial archival, plan creation or remote writes.

Evidence: `backend/planning/replacement.py:prepare_structured_plan_replacement`; `backend/planning/replacement_service.py:StructuredTrainingPlanReplacementService.replace`, `backend/planning/replacement_service.py:StructuredTrainingPlanReplacementService._archive_superseded_plans`, `backend/planning/replacement_service.py:StructuredTrainingPlanReplacementService._copy_constraints`; `backend/change_history.py:reserve_capacity`; `tests/test_coach_tool_coverage.py:test_replacement_changes_only_requested_period`; `tests/test_coach_dialogue.py:test_bounded_giro_rebuild_preserves_later_units_and_plan_constraints`; `tests/test_planning_replacement.py:test_rejects_past_and_out_of_period_workouts`, `tests/test_planning_replacement.py:test_rejects_overlapping_time_windows_in_replacement`.

### Requirement: TP7 Authenticated idempotent planning commands
The system SHALL support the allowed explicit planning API commands with a bounded client turn ID, session/conversation ownership and stable effect identity, storing their final receipt transactionally with the effect.

#### Scenario: Explicit command success and replay
- **WHEN** an authenticated planning command succeeds and is resubmitted unchanged by its owning session/conversation
- **THEN** the stored receipt is returned without executing its effect twice.

#### Scenario: Changed or active command identity
- **WHEN** the ID already belongs to different arguments, a foreign session/conversation or a running command
- **THEN** the command is rejected without repeating or replacing its effect.

#### Scenario: Invalid command or domain failure
- **WHEN** the operation/arguments/ID are invalid, the draft revision is stale or the domain write fails
- **THEN** invalid input does not claim a new turn, and a claimed tool failure rolls back its local effect while persisting an honest failure receipt.

Evidence: `backend/http_api/planning_commands_post.py:PlanningCommandsPostRoutes.handle`; `backend/coach/planning_commands.py:CoachPlanningCommandService.execute`, `backend/coach/planning_commands.py:CoachPlanningCommandService._claim`, `backend/coach/planning_commands.py:CoachPlanningCommandService._execute_claimed`; `tests/test_coach_planning_commands.py:test_success_replays_without_second_effect_and_binds_session_and_conversation`, `tests/test_coach_planning_commands.py:test_invalid_command_never_claims_turn`, `tests/test_coach_planning_commands.py:test_existing_running_claim_does_not_execute_again`, `tests/test_coach_planning_commands.py:test_tool_failure_rolls_back_effect_and_persists_failure_receipt`.

### Requirement: TP8 Persisted adaptive previews with trigger evidence
The system SHALL create local adaptive proposals from current saved feedback, future local units, read-only calendar signals and cached forecast evidence, persist their source fingerprints and freshness, and leave units unchanged until apply.

#### Scenario: Combined constraints
- **WHEN** current feedback/calendar/weather indicates illness, pain/high soreness, reduced recovery/availability, calendar markers or relevant outdoor forecast constraints
- **THEN** the proposal lists eligible future unit changes with before/after, rationale, blocking triggers, calendar evidence and source fingerprints, plus forecast state/fetched-at/stale metadata.

#### Scenario: No needed changes
- **WHEN** no future unit needs adjustment
- **THEN** the saved preview explicitly has no changes and status reflects whether an illness pause still needs approval, without creating fake workouts.

#### Scenario: Too many future units or stale weather
- **WHEN** more than five hundred future units exist
- **THEN** preview refuses incomplete enumeration; a usable stale forecast retains its stale metadata and is not relabeled as freshly fetched evidence.

Evidence: `backend/planning/adaptive_preview_service.py:AdaptiveReplanPreviewService.preview`, `backend/planning/adaptive_preview_service.py:AdaptiveReplanPreviewService.status`, `backend/planning/adaptive_preview_service.py:_change`, `backend/planning/adaptive_preview_service.py:_forecast_freshness`; `tests/test_adaptive_preview_service.py:test_combined_illness_calendar_weather_preview_keeps_triggers_and_fingerprint`, `tests/test_adaptive_preview_service.py:test_preview_without_changes_only_includes_future_local_drafts`, `tests/test_adaptive_preview_service.py:test_preview_refuses_instead_of_silently_truncating_future_units`, `tests/test_adaptive_preview_service.py:test_stale_cache_freshness_is_saved_and_still_drives_weather_change`, `tests/test_adaptive_preview_service.py:test_preview_persists_once_and_reads_back`.

### Requirement: TP9 Separate approval of the latest published adaptive preview
The system SHALL apply a Coach adaptive preview only when the latest preview is published and the athlete's very next stored message explicitly accepts it under matching operation/scope and impact approval.

#### Scenario: Immediate explicit acceptance
- **WHEN** the athlete's next message after a published current preview clearly asks to apply it
- **THEN** authorized local adaptive apply can run with that preview ID and request provenance.

#### Scenario: Same-turn or later-message acceptance
- **WHEN** the model tries to preview and apply in the same turn, publication is absent, an intervening athlete message exists or the requested preview is no longer latest
- **THEN** apply fails and a fresh preview is required.

#### Scenario: Acknowledgement or remote addition
- **WHEN** the reply only thanks/acknowledges the proposal or tries to add illness sync without a named matching Intervals target/scope
- **THEN** it does not authorize that apply/remote effect.

Evidence: `backend/coach/adaptive_apply.py:CoachAdaptiveApplyService.apply`; `backend/coach/write_gate.py:check_write`; `tests/test_coach_adaptive_apply.py:test_later_turn_apply_succeeds_without_remote_sync`, `tests/test_coach_adaptive_apply.py:test_same_turn_or_missing_provenance_cannot_apply`, `tests/test_coach_adaptive_apply.py:test_only_the_first_athlete_message_after_the_preview_can_approve`, `tests/test_coach_adaptive_apply.py:test_remote_sync_requires_target_and_explicit_scope_before_db_read`; `tests/test_coach_tool_coverage.py:test_acknowledgement_after_a_preview_does_not_apply_it`.

### Requirement: TP10 Adaptive stale-state protection and repeat behavior
The system SHALL recheck fingerprints, current dates/visibility and calendar constraints during apply, update only supported replacement fields, report stale/partial outcomes and preserve atomic local persistence.

#### Scenario: Intervening edit or changed blocker
- **WHEN** a previewed unit is missing, changed, hidden, now past or has a changed applicable calendar constraint
- **THEN** that unit is skipped with a reason and newer state is preserved; the result distinguishes fully stale from partially applied changes.

#### Scenario: Nonreplacement field changed
- **WHEN** start time, plan membership or remote identity changes outside the fields replaced by adaptation
- **THEN** apply overlays only its permitted replacement fields and retains those independent current values.

#### Scenario: Repeated apply or late failure
- **WHEN** an applied/stale/partial preview is applied again
- **THEN** it returns an already status without repeating effects; failure while finalizing local apply rolls back unit, history, revision and check-in changes together.

Evidence: `backend/planning/adaptive.py:AdaptiveReplanApplyService.apply`, `backend/planning/adaptive.py:AdaptiveReplanApplyService._calendar_changes`, `backend/planning/adaptive.py:AdaptiveReplanApplyService._apply_change`; `tests/test_adaptive_replan_apply_service.py:test_stale_partial_and_past_reasons_are_idempotent`, `tests/test_adaptive_replan_apply_service.py:test_apply_rechecks_current_calendar_constraints_and_keeps_evidence`, `tests/test_adaptive_replan_apply_service.py:test_apply_keeps_athlete_edits_outside_the_replaced_fields`, `tests/test_adaptive_replan_apply_service.py:test_late_mark_applied_failure_rolls_back_all_tables`; `tests/test_coach_tool_coverage.py:test_stale_adaptive_preview_preserves_intervening_edit`.

### Requirement: TP11 Illness pause local records and optional remote sync
The system SHALL keep illness-pause forecasts explicitly proposed rather than diagnosed, apply approved local pause/check-in effects without implicit remote workout edits, and retain local success when separately requested illness-event synchronization fails.

#### Scenario: Approve local illness pause
- **WHEN** an eligible preview's illness pause is approved
- **THEN** applicable future local units are archived/adapted, forecast-day illness check-ins preserve other saved feedback, and the pause is marked approved locally.

#### Scenario: Optional named illness-event sync
- **WHEN** the athlete explicitly names and approves Intervals.icu illness synchronization
- **THEN** the existing illness sync writes its bounded SICK calendar-event payloads with stable day identities; this is distinct from silently rescheduling/deleting remote workout events.

#### Scenario: Remote error or repeated apply
- **WHEN** optional remote illness sync fails after local commit
- **THEN** the local result remains and the error is reported safely; an already-applied preview does not silently repeat the remote sync.

Evidence: `backend/planning/adaptive.py:illness_pause_forecast`, `backend/planning/adaptive.py:AdaptiveReplanApplyService._fill_illness_checkins`, `backend/planning/adaptive.py:illness_calendar_events`; `backend/sync/adaptive.py:IllnessPauseSyncService.apply`, `backend/sync/adaptive.py:IllnessPauseSyncService.sync`; `tests/test_adaptive_replan_apply_service.py:test_applies_replacement_audit_revision_and_illness_checkins_atomically`; `tests/test_sync_adaptive.py:test_apply_keeps_local_result_and_status_without_explicit_remote_approval`, `tests/test_sync_adaptive.py:test_apply_writes_remote_pause_only_when_explicitly_requested`, `tests/test_sync_adaptive.py:test_apply_redacts_remote_failure_and_keeps_local_apply_result`, `tests/test_sync_adaptive.py:test_apply_returns_already_applied_status_without_remote_sync`.
