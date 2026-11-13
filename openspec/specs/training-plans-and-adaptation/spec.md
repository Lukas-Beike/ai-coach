# training-plans-and-adaptation Specification

## Purpose

Describe local plan drafts, commits, membership/metadata, optimistic edits and replacements, authenticated planning commands and separately approved adaptive changes. This documents existing behavior without authorizing a new plan, remote write or database change. Requirement numbers are stable ids: TP7 was retired and is not reused.

## Requirements

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

#### Scenario: Draft rejection reasons
- **WHEN** a draft has no payload, no workout, more than 366 workouts or a span above 730 days, or a workout is not an object or has no valid date
- **THEN** staging fails with 400 and the reason `plan_limit` (count or span) or `invalid_plan` (shape, date or missing payload).

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

#### Scenario: Artifact states and commit reasons
- **WHEN** an artifact is committed
- **THEN** its status is `draft`, `committed` or `superseded`; an unknown id answers 404 `artifact_not_found`, a `superseded` one 409 `artifact_not_available`, another conversation without explicit artifact selection 409 `artifact_conversation_conflict`, a changed planning revision 409 `planning_revision_conflict` and a concurrent commit 409 `artifact_revision_conflict`; success returns `status: committed` with `library_entry_ids` and names the plan "Coach-Plan" when the draft has none.

#### Scenario: Conversation reset
- **WHEN** the Coach conversation is reset
- **THEN** every draft becomes `superseded` and can no longer be committed.

Evidence: `backend/coach/conversation.py` (reset), `backend/planning/training_plan_artifact_service.py:TrainingPlanArtifactService.commit`, `backend/planning/training_plan_artifact_service.py:TrainingPlanArtifactService._validate_committed_artifact`; `tests/test_server_coach.py:test_reset_coach_chat_discards_outstanding_plan_drafts`; `tests/test_training_plan_artifact_service.py:test_successful_commit_is_atomic_and_replay_is_idempotent`, `tests/test_training_plan_artifact_service.py:test_revision_conflict_rejects_stale_draft`, `tests/test_training_plan_artifact_service.py:test_conversation_conflict_and_explicit_rebind`, `tests/test_training_plan_artifact_service.py:test_conditional_status_update_conflict_rolls_back_local_plan_writes`, `tests/test_training_plan_artifact_service.py:test_late_local_plan_failure_rolls_back_all_writes`.

### Requirement: TP3 Local plan creation and reusable-template matching
The system SHALL save a requested plan's sessions locally, optionally create named plan metadata, link created units to that plan and create a unit only from a library template (`template_id`) without a remote call.

#### Scenario: Named local plan
- **WHEN** normalized sessions are saved with a plan name
- **THEN** plan metadata spans the created sessions, units carry its plan ID/name and the transaction advances planning state with audit records.

#### Scenario: Matching template
- **WHEN** a saved template satisfies the implemented sport, content, duration and conservative similarity checks
- **THEN** its supported workout content is copied into the planned unit with library source and its `template_id`, while retaining the requested local date and plan membership.

#### Scenario: No valid match or storage conflict
- **WHEN** no suitable template exists and the session names none
- **THEN** the Coach plan write is rolled back with `template_missing` (training-library: Planned units come from library templates) instead of storing free Coach content; a calendar or persistence failure aborts the owning plan transaction rather than leaving partial units.

#### Scenario: Template match thresholds
- **WHEN** a requested session names no `template_id` and a saved undated template is compared with it
- **THEN** the template must have the same Intervals.icu type, a description, a valid workout text and a duration within the larger of 10 minutes and 20 % of the requested one; texts are lower-cased with every run of other characters than a-z, 0-9 and % as one space, and the template matches with an equal description, a description similarity of at least 0.82, or a name similarity of at least 0.90 together with a description similarity of at least 0.55; the highest score wins.

#### Scenario: Stored result of a match
- **WHEN** a template matches
- **THEN** sport, name, description, duration (at least 5 minutes) and target (`AUTO`, `POWER`, `HR` or `PACE`, else `AUTO`) come from it with `source` `library` and its `template_id`; a session that names a `template_id` keeps it and is not matched; an empty session list fails with 400 "Mindestens eine Einheit ist erforderlich." and a calendar or time-window conflict with 409 `plan_date_conflict`.

Evidence: `backend/planning/local_plan_creation_service.py:LocalTrainingPlanCreationService.save`, `backend/planning/local_plan_creation_service.py:LocalTrainingPlanCreationService._save_in_db`, `backend/planning/local_plan_creation_service.py:LocalTrainingPlanCreationService._planned_workout_for_storage`; `backend/planning/library.py:compatible_workout_duration`, `backend/planning/library.py:find_similar_library_workout`; `tests/test_planning_library.py:test_duration_tolerance_and_exact_remote_match`, `tests/test_planning_library.py:test_exact_and_conservative_near_matches`, `tests/test_planning_library.py:test_no_match_for_unrelated_or_invalid_candidates`; `tests/test_training_plan_artifact_service.py:test_late_local_plan_failure_rolls_back_all_writes`; `tests/test_coach_tool_coverage.py:test_requested_draft_commit_and_metadata_lifecycle`.

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

#### Scenario: Plan fields and status vocabulary
- **WHEN** plan metadata is saved
- **THEN** the name has at most 200 characters, the goal at most 2000, start and end are ISO dates (a timestamp is refused) and the status is `draft`, `planned`, `active`, `completed`, `archived`, `cancelled` or `paused`; the German words "entwurf", "geplant", "aktiv", "abgeschlossen", "archiviert", "abgebrochen" and "pausiert" are accepted in any case and stored as the English value, any other status fails with 400 "Ungültiger Trainingsplanstatus.".

#### Scenario: Update and delete actions
- **WHEN** the `action` is `update` (default) or `delete`
- **THEN** an update keeps omitted fields, a delete removes only the metadata row, both record change history, bump the planning revision and publish a Coach state event; another action is 400, an unknown plan 404 and an id that is no UUID 400.

#### Scenario: Bounds follow the active units
- **WHEN** units of a plan are moved, archived or added
- **THEN** the plan's start and end become the earliest and latest date of its active units (not archived, not deleted), recorded with source `coach_apply`; a plan without active units keeps its dates.

#### Scenario: Constraint storage
- **WHEN** plans are listed (at most 30)
- **THEN** each carries `constraints`, the list stored under the key `coach_plan_constraints:<plan id>`, or an empty list.

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

#### Scenario: Fields of a created unit
- **WHEN** a patch creates a unit
- **THEN** it carries `date`, `sport`, `name`, `description`, `duration_minutes`, `target` and `rationale` (optionally `starts_at_local`, `template_id` and the focus fields) and no `local_id`, else the patch fails with 400 `invalid_change`; the result is `status: applied` with `planning_revision`, `changes` (`local_id`, `status`) and `library_entry_ids`.

#### Scenario: Plan membership of created units
- **WHEN** all changed existing units of the batch belong to one non-archived plan and a created unit names no `plan_id`
- **THEN** it joins that plan; an explicit empty `plan_id` keeps it standalone and another `plan_id` fails with 403 `intent_scope_denied`.

#### Scenario: Which calendar checks run
- **WHEN** the final batch is validated
- **THEN** calendar markers are checked for every final date of an active unit, and the ordinary conflict check runs only for created, date-moved or restored units and units whose time window changed.

#### Scenario: Patch rejection reasons
- **WHEN** a patch is rejected
- **THEN** the reason is `planning_revision_required` (400), `planning_revision_conflict` (409), `payload_hash_required` (400), `payload_hash_conflict` (409), `change_limit` (400, more than 366 changes), `invalid_change` (400), `plan_date_conflict` (409), `plan_not_available` (409) or `intent_scope_denied` (403).

Evidence: `backend/coach/limits.py:TRAINING_CHANGE_LIMIT`, `backend/coach/training_patch.py:CoachTrainingPatchService.apply`, `backend/planning/changes.py:prepare_structured_training_change`; `backend/planning/changes.py:StructuredTrainingChangeValidator.validate`, `backend/planning/changes.py:StructuredTrainingChangeService.apply_in_db`; `tests/test_server_planning.py:test_structured_training_create_can_explicitly_stay_standalone`; `tests/test_coach_dialogue.py:test_screenshot_followup_moves_and_adds_atomically_without_literal_name`, `tests/test_coach_dialogue.py:test_failed_addition_rolls_back_move_and_revision`, `tests/test_coach_dialogue.py:test_stale_hash_rolls_back_whole_patch`; `tests/test_planning_change_validation.py:test_required_hash_validates_current_payload`, `tests/test_planning_change_validation.py:test_duplicate_final_dates_are_allowed_for_untimed_or_non_overlapping_workouts`; `tests/test_coach_training_patch.py:test_multiple_workouts_on_same_calendar_day_are_applied`.

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

#### Scenario: Which units a replacement selects
- **WHEN** a replacement runs
- **THEN** it archives and deletes only active units dated inside its period (default today onward) that belong to the named plan or, without a named plan, whose `source` is `coach`, `library`, `intervals` or absent; the named plan, the plans of the replaced units and, without a named plan and period, every non-archived plan ending today or later are archived only when no active unit of them remains.

#### Scenario: Inherited constraints and result
- **WHEN** a replacement passes no constraints
- **THEN** the new plan takes the union of the superseded plans' constraints without duplicates; success returns `ok`, `status: replaced`, `planning_revision`, `archived_count`, `created_count`, `plan_id` and `library_entry_ids`; a request without revision or name fails with 400 `planning_revision_required` or `invalid_plan`, as does an invalid, past or out-of-period unit; a corrupt stored unit fails with 409 `invalid_plan` and a stale revision with 409 `planning_revision_conflict`.

Evidence: `backend/planning/replacement.py:prepare_structured_plan_replacement`; `backend/planning/replacement_service.py:StructuredTrainingPlanReplacementService.replace`, `backend/planning/replacement_service.py:StructuredTrainingPlanReplacementService._archive_superseded_plans`, `backend/planning/replacement_service.py:StructuredTrainingPlanReplacementService._copy_constraints`; `backend/change_history.py:reserve_capacity`; `tests/test_coach_tool_coverage.py:test_replacement_changes_only_requested_period`; `tests/test_server_planning.py:test_broad_plan_replace_archives_future_plan_metadata_without_active_units`; `tests/test_coach_dialogue.py:test_bounded_giro_rebuild_preserves_later_units_and_plan_constraints`; `tests/test_planning_replacement.py:test_rejects_past_and_out_of_period_workouts`, `tests/test_planning_replacement.py:test_rejects_overlapping_time_windows_in_replacement`.

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

#### Scenario: Check-in limits bind one day
- **WHEN** today's check-in reports pain, soreness of 8 or more, stress of 8 or more, motivation of 2 or less, or fewer available minutes than a unit lasts
- **THEN** only units dated on the check-in day are changed for these reasons; stress and motivation change only hard units (the hard-session rule of training-library) and later days are untouched.

#### Scenario: Illness forecast
- **WHEN** today's check-in has an illness text that reports a complaint (not empty, "-", "keine", "kein", "nein", "nichts", "gesund", "none", "no" or "n/a", ignoring case and trailing punctuation)
- **THEN** the preview carries `illness_pause` with `start_date` today, `end_date` today plus 4 days, `recommended_pause_days` 5, the illness text and a German forecast sentence that calls the duration a Coach proposal and no diagnosis, and every unit inside the window is proposed for archiving until the pause is approved.

#### Scenario: Calendar days
- **WHEN** a unit's day has training-relevant calendar events
- **THEN** a hard unit or one longer than the day limit (45 minutes with an all-day event or 240 or more event minutes, 60 from 120 minutes, else 75, never above 60 on a `[SHORT_ONLY]` day) is replaced; `[NO_TRAINING]` archives the unit; a unit that breaks `[NO_INTENSITY]` is replaced and named "Lockere Einheit" when the replacement is not explicitly easy by its text; a replacement that would still break a marker of its day is not proposed.

#### Scenario: Replacement content
- **WHEN** a unit is replaced
- **THEN** its duration is the smallest applicable limit (available minutes, calendar day, weather 90, return stage 60), at least 15 and at most 90 minutes, the target is `AUTO`, the description is one easy step of its sport, `source` is `adaptive` without `template_id`, a run or ride gets the focus `easy` (a run also the athlete's easy heart-rate cap), and a strength unit keeps its exercises, sets and weights and only gets the strength intensity `light` (a time limit only shortens its duration, to at least 15 minutes).

Detailed contract: the preview holds `generated_at`, `checkin_date`, `signals`, `changes`, `illness_pause`, `illness_return`, `weather_forecast` (`state`, `provider`, `fetched_at`, `stale`), `message` and `scope`; each change holds `library_workout_id`, `date`, `name`, `blocking_triggers` (`illness`, `injury`, `calendar`, `weather`), `external_events`, `before`, `after`, `source_fingerprint` and `payload`.

Evidence: `backend/athlete/checkins.py:reports_complaint`, `backend/planning/adaptive.py:adaptive_recovery_replacement`, `backend/planning/adaptive.py:illness_pause_forecast`, `backend/planning/adaptive_preview_service.py:AdaptiveReplanPreviewService.preview`, `backend/planning/adaptive_preview_service.py:AdaptiveReplanPreviewService.status`, `backend/planning/adaptive_preview_service.py:_calendar_limits`, `backend/planning/adaptive_preview_service.py:_change`, `backend/planning/adaptive_preview_service.py:_change_state`, `backend/planning/adaptive_preview_service.py:_forecast_freshness`, `backend/planning/adaptive_preview_service.py:_replacement`; `tests/test_adaptive_preview_service.py:test_available_minutes_apply_only_to_the_checkin_day`, `tests/test_adaptive_preview_service.py:test_combined_illness_calendar_weather_preview_keeps_triggers_and_fingerprint`, `tests/test_adaptive_preview_service.py:test_preview_without_changes_only_includes_future_local_drafts`, `tests/test_adaptive_preview_service.py:test_preview_refuses_instead_of_silently_truncating_future_units`, `tests/test_adaptive_preview_service.py:test_stale_cache_freshness_is_saved_and_still_drives_weather_change`, `tests/test_adaptive_preview_service.py:test_preview_persists_once_and_reads_back`.

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

Evidence: `backend/coach/adaptive_apply.py:CoachAdaptiveApplyService.apply`, `backend/coach/adaptive_apply.py:CoachAdaptiveApplyService._apply_checked`; `backend/coach/write_gate.py:check_write`; `tests/test_coach_adaptive_apply.py:test_later_turn_apply_succeeds_without_remote_sync`, `tests/test_coach_adaptive_apply.py:test_same_turn_or_missing_provenance_cannot_apply`, `tests/test_coach_adaptive_apply.py:test_only_the_first_athlete_message_after_the_preview_can_approve`, `tests/test_coach_adaptive_apply.py:test_remote_sync_requires_target_and_explicit_scope_before_db_read`; `tests/test_coach_tool_coverage.py:test_acknowledgement_after_a_preview_does_not_apply_it`.

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

#### Scenario: Identity and supersession
- **WHEN** an adjustment is applied by an id that is no UUID, is unknown or is not the newest stored adjustment (newest by `created_at`, then insertion order)
- **THEN** the answer is 400 "Ungültige Plananpassung.", 404 "Plananpassung nicht gefunden." or 409 "Diese Plananpassung wurde durch eine neuere Vorschau ersetzt. Bitte die aktuelle Vorschau verwenden."; an adjustment already `applied`, `stale` or `partial` answers `already_<status>` before the newest check, and a preview never expires by time.

#### Scenario: Skip reasons and replaceable fields
- **WHEN** a change is applied
- **THEN** a unit that is gone, archived or deleted is skipped with reason `missing`, one whose fingerprint (type, date, name, duration, description, target, rationale, calendar adjustment) changed with `changed`, one with an unreadable date with `invalid_date`, one before today with `past` and one whose calendar blockers changed with `calendar_constraint_changed`; otherwise only `name`, `duration_minutes`, `description`, `target`, `rationale`, `archived`, `private_calendar_adjustment`, `source`, `template_id`, `session_focus`, `strength_intensity`, `strength_structure` and `hr_cap` are taken from the preview (a null removes the field), `planned_duration_s` follows the duration, the sync state becomes `local` and the change is recorded with source `adaptive_replan`.

#### Scenario: Result status
- **WHEN** apply finishes
- **THEN** the status is `applied` (nothing skipped), `partial` (changes skipped while a unit was updated or a return stage change is pending) or `stale` (changes skipped, nothing updated and no stage change); the planning revision is bumped only when a unit changed and the result carries `id`, `updated`, `updated_checkins`, `stale` and `illness_pause`.

#### Scenario: Approved pause carries over
- **WHEN** a later preview sees the same illness text while today is inside the window of the newest applied or partial pause
- **THEN** it reuses that window as already approved, neither asks again nor extends it; after the window a new report asks again.

Detailed contract: the status projection is `needs_replan`, `replan_changes`, `illness_pause_pending` and `illness_return_pending`; the quick-action blockers are the changes dated today to today plus 2 days whose triggers include calendar, illness, injury or weather.

Evidence: `backend/planning/adaptive.py:ADAPTIVE_REPLACEMENT_KEYS`, `backend/planning/adaptive.py:adaptive_quick_action_blockers`, `backend/planning/adaptive.py:adaptive_workout_fingerprint`, `backend/planning/adaptive_preview_service.py:_approve_existing_pause`, `backend/planning/adaptive_preview_service.py:AdaptiveReplanPreviewService.status`, `backend/planning/adaptive.py:AdaptiveReplanApplyService.apply`, `backend/planning/adaptive.py:AdaptiveReplanApplyService._calendar_changes`, `backend/planning/adaptive.py:AdaptiveReplanApplyService._apply_change`; `tests/test_adaptive_preview_service.py:test_second_day_report_does_not_extend_the_approved_pause`; `tests/test_adaptive_replan_apply_service.py:test_only_the_latest_preview_can_be_applied`, `tests/test_adaptive_replan_apply_service.py:test_stale_partial_and_past_reasons_are_idempotent`, `tests/test_adaptive_replan_apply_service.py:test_apply_rechecks_current_calendar_constraints_and_keeps_evidence`, `tests/test_adaptive_replan_apply_service.py:test_apply_keeps_athlete_edits_outside_the_replaced_fields`, `tests/test_adaptive_replan_apply_service.py:test_late_mark_applied_failure_rolls_back_all_tables`; `tests/test_coach_tool_coverage.py:test_stale_adaptive_preview_preserves_intervening_edit`.

### Requirement: TP11 Illness pause local records and optional remote sync
The system SHALL keep illness-pause forecasts explicitly proposed rather than diagnosed, apply approved local pause/check-in effects without implicit remote workout edits, and retain local success when separately requested illness-event synchronization fails.

#### Scenario: Approve local illness pause
- **WHEN** an eligible preview's illness pause is approved
- **THEN** applicable future local units are archived/adapted, only today's check-in (when today is inside the pause window) gains the illness text and the note "Krankheitspause prognostiziert ab <start>" while other saved feedback is preserved, no future check-in is written, and the pause is marked approved locally.

#### Scenario: Optional named illness-event sync
- **WHEN** the athlete explicitly names and approves Intervals.icu illness synchronization
- **THEN** the existing illness sync writes its bounded SICK calendar-event payloads with stable day identities; this is distinct from silently rescheduling/deleting remote workout events.

#### Scenario: Remote error or repeated apply
- **WHEN** optional remote illness sync fails after local commit
- **THEN** the local result remains and the error is reported safely; an already-applied preview does not silently repeat the remote sync.

#### Scenario: Result of the apply tool
- **WHEN** the Coach applies an adjustment
- **THEN** the result holds `status`, `id`, `updated`, `updated_checkins`, `illness_pause`, `intervals_sync` and `planning`; with stale entries `status` is the stored status instead of `ok` and `stale` and the message "Die Vorschau war teilweise oder vollständig veraltet; die betroffenen Einheiten wurden nicht überschrieben." are added; a repeated apply returns the `already_*` answer unchanged.

#### Scenario: Illness sync outcome
- **WHEN** illness synchronization was requested and the pause was not approved before
- **THEN** one `SICK` event per day is upserted and `intervals_sync` is `{status: ok, synced, category}`; a failure becomes `{status: error, error}` with a redacted text and the local result stays.

#### Scenario: Follow-up check after a provider refresh
- **WHEN** a provider refresh finishes
- **THEN** the preview is recomputed and `needs_replan` is true for any proposed change or a pending return stage; when the recomputation fails the stored status is used.

Evidence: `backend/planning/adaptive.py:illness_pause_forecast`, `backend/planning/adaptive.py:AdaptiveReplanApplyService._fill_illness_checkin`, `backend/planning/adaptive.py:illness_calendar_events`; `backend/sync/adaptive.py:AdaptivePreviewFollowupService.check`, `backend/sync/adaptive.py:IllnessPauseSyncService.apply`, `backend/sync/adaptive.py:IllnessPauseSyncService.complete`, `backend/sync/adaptive.py:IllnessPauseSyncService.sync`; `tests/test_adaptive_replan_apply_service.py:test_applies_replacement_audit_revision_and_illness_checkins_atomically`; `tests/test_sync_adaptive.py:test_apply_keeps_local_result_and_status_without_explicit_remote_approval`, `tests/test_sync_adaptive.py:test_apply_writes_remote_pause_only_when_explicitly_requested`, `tests/test_sync_adaptive.py:test_apply_redacts_remote_failure_and_keeps_local_apply_result`, `tests/test_sync_adaptive.py:test_apply_returns_already_applied_status_without_remote_sync`.

### Requirement: TP12 Calendar markers constrain planned workouts
The system SHALL check every planned-workout change against the external events of its day: a NO_TRAINING event SHALL block everything but a rest entry, a NO_INTENSITY event SHALL block a hard unit and any strength unit that is not explicitly easy, and a SHORT_ONLY event SHALL block a workout longer than 60 minutes. A blocked change SHALL carry the reason `no_training`, `no_intensity` or `short_only`.

#### Scenario: Exactly 60 minutes
- **WHEN** a 60-minute workout meets a SHORT_ONLY event
- **THEN** it is allowed; 61 minutes are blocked with reason `short_only`.

#### Scenario: Unknown duration
- **WHEN** a workout has no usable duration and meets a SHORT_ONLY event
- **THEN** it is not blocked by that marker.

#### Scenario: No-intensity day
- **WHEN** a NO_INTENSITY event meets an endurance unit of easy or zone-two effort, a hard unit, a light strength unit or a heavy strength unit
- **THEN** only the hard unit and the heavy strength unit are blocked.

Detailed contract: the duration is `duration_minutes`, else `planned_duration_s / 60`. An event carries a constraint through its stored flag or through the marker in its title or description. Markers and their detection belong to `external-calendars`.

Evidence: `backend/planning/calendar.py::calendar_constraint_decision`, `backend/planning/calendar.py::breaks_no_intensity`, `backend/planning/calendar.py::workout_is_explicitly_easy`, `backend/planning/calendar.py::calendar_event_has_constraint`; `tests/test_planning_calendar.py::test_set_easy_focus_is_explicitly_easy_despite_zone_two_text`, `tests/test_planning_calendar.py::test_light_or_mobility_strength_is_explicitly_easy`, `tests/test_adaptive_preview_service.py::test_short_only_day_caps_every_proposed_duration_at_the_marker_limit`, `tests/test_server_weather_calendar.py::test_ical_no_intensity_marker_requires_easy_replacement`, `tests/test_server_weather_calendar.py::test_ical_no_training_marker_is_excluded_from_adaptive_constraints`.

### Requirement: TP13 Stepwise return after an approved illness pause
After an approved illness pause the system SHALL run a three-stage return (stage 1 easy sessions only, stage 2 easy and moderate, stage 3 the normal plan). Each morning's adaptive preview SHALL propose at most one stage change, a stage SHALL change only when that preview is applied, and the plan check `illness_hard` SHALL block Coach writes above the approved stage. Nothing is written to a provider.

#### Scenario: Start and end of a return
- **WHEN** the newest applied or partial adjustment holds an approved pause and today lies 1 to 28 days after its end date
- **THEN** a return runs, starting at stage 1 on the day after the pause; a stored stage state is used only when it belongs to the same pause end, and after 28 days or at stage 3 nothing is enforced.

#### Scenario: Advance
- **WHEN** today's check-in exists, reports no pain or illness complaint, its soreness (if given) is at most 5, the overnight HRV position is not `below`, the resting heart rate is at most 5 bpm above the usual value and the stage is at least 2 days old
- **THEN** the preview proposes the next stage (`action: advance`, `pending: true`).

#### Scenario: Hold or step back
- **WHEN** there is no check-in of today, a sign is poor or the stage is younger than 2 days
- **THEN** the stage holds with the reason `no_checkin`, `body_feel`, `hrv_below_range`, `resting_hr_high` or `stage_days`; a pain or illness complaint proposes one stage back with the reason `complaint` (stage 1 holds); a missing overnight value does not block and leaves the check-in to decide.

#### Scenario: New illness report
- **WHEN** today's check-in reports an illness that produces a pause forecast
- **THEN** the forecast outranks the return and no return block is computed.

#### Scenario: Sessions above the stage
- **WHEN** a future unit of today or tomorrow has a level above the stage (level 0 easy: a set or derived focus `recovery`, `easy`, `mobility` or `core`, light strength or explicitly easy text, and shorter than 90 minutes; level 2: hard or heavy strength; else level 1)
- **THEN** the preview proposes a local easy replacement of at most 60 minutes with blocking trigger `illness`, and a Coach write of such a unit fails the `illness_hard` check with `return_stage` and `session_level` in its details.

Detailed contract: the preview block `illness_return` carries `action` (`advance`, `hold`, `step_back`), `from_stage`, `stage`, `reasons`, `evidence[]` (`source` "Check-in (lokal)" or the Garmin daily-health label, `label` complaint, soreness, hrv or resting_hr, `value`, `ok`, and where known `missing`, `unit`, `lower`, `usual`, `observed_at`), `pending`, `state_after` (`pause_end`, `stage`, `since`, `history` of at most 20 entries) and `stage_label` ("nur lockere Einheiten", "lockere und moderate Einheiten", "normaler Plan"). The state lives only in the payload of the applied adjustment. Overnight values are today's personal recovery baselines with status `ok` or `provisional`.

Evidence:
- `backend/planning/adaptive_preview_service.py:AdaptiveReplanPreviewService._illness_return_block`
- `backend/planning/adaptive_preview_service.py:_return_limited`
- `backend/planning/illness_return.py:current_state`
- `backend/planning/illness_return.py:decide`
- `backend/planning/illness_return_signals.py:overnight_signals`
- `backend/planning/plan_checks.py:session_level`
- `tests/test_illness_return.py:test_new_complaint_steps_back_one_stage`
- `tests/test_illness_return.py:test_two_days_per_stage_with_good_signals`
- `tests/test_illness_return.py:test_return_expires_after_four_weeks`
- `tests/test_illness_return_preview.py:test_good_signals_after_two_days_propose_stage_two`
- `tests/test_illness_return_preview.py:test_new_illness_report_outranks_the_return`
- `tests/test_illness_return_preview.py:test_preview_stays_local_and_leaves_drafts_untouched`

### Requirement: TP14 Planning revision and payload hashes
The system SHALL keep one planning revision counter and SHALL identify a unit's content by a SHA-256 hash that does not change when only local-only or sync-written fields change.

#### Scenario: Revision
- **WHEN** a local planning write commits
- **THEN** the single `planning_state` row is incremented; a missing row is a 500 `database_corrupt` error ("Die lokale Planrevision fehlt; die Datenbank muss repariert werden.") unless a confirmed local data purge announced a reset, in which case the row is recreated once.

#### Scenario: Unit payload hash
- **WHEN** the hash of a planned unit is computed
- **THEN** the keys `id`, `sync_status`, `sync_conflict`, `origin`, `local_marked`, `session_focus`, `strength_intensity`, `strength_structure` and `template_id` are left out (`hr_cap` stays in, because it reaches the watch), sport and environment are replaced by the provider sport token, start and duration are named as on the Intervals.icu wire, and the sorted compact JSON is hashed, so a hash recorded by an earlier schema stays valid.

#### Scenario: Plan-push hash
- **WHEN** a plan push or a patch records or checks a hash
- **THEN** the keys a sync writes (`remote_event_id`, `remote_event_external_id`, `remote_event_category`, `external_id`, `sync_error`, `workout_doc`, planned load and intensity) are also left out; a hash recorded over the raw stored payload is still accepted while that payload is unchanged.

Evidence:
- `backend/planning/planned_units.py:plan_push_hash_matches`
- `backend/planning/planned_units.py:plan_push_payload_hash`
- `backend/planning/planned_units.py:planned_unit_payload_hash`
- `backend/planning/revision.py:PlanningRevisionService.bump`
- `tests/test_plan_push_hash.py:test_legacy_raw_hash_is_accepted_while_the_payload_is_unchanged`
- `tests/test_plan_push_hash.py:test_sync_written_fields_do_not_move_the_hash`
- `tests/test_planning_revision.py:test_explicit_privacy_reset_recreates_singleton_once`
- `tests/test_planning_revision.py:test_missing_revision_is_corruption_without_explicit_reset`
