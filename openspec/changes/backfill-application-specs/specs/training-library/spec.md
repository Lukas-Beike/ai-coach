## Purpose

Describe locally authoritative reusable workout templates and their dated planned copies, browsing, mutation, export validation and explicit synchronization boundary. Full-plan transactions and adaptive previews belong to training-plans-and-adaptation.

## ADDED Requirements

### Requirement: TL1 Undated local training templates
The system SHALL create reusable local templates independently from dated plans, with stable local UUIDs, validated sport/description/duration and local sync state.

#### Scenario: Valid template
- **WHEN** an authorized template create supplies valid workout content without a planning date
- **THEN** an undated local template is stored, audited and returned with local identity; creating it schedules no session and performs no provider write.

#### Scenario: Dated or invalid template
- **WHEN** a template has a planning date, invalid sport, invalid duration or invalid executable endurance content
- **THEN** creation fails rather than treating it as a scheduled workout.

#### Scenario: Duration boundary
- **WHEN** template duration is provided
- **THEN** creation accepts the implemented 5-to-1440-minute template range independently from the narrower dated export range.

Evidence: `backend/planning/library_service.py:WorkoutLibraryService.create_template`, `backend/planning/library_service.py:WorkoutLibraryService.create_local_entry`; `backend/coach/training_template_tools.py:TrainingTemplateToolService.execute`; `tests/test_coach_tool_coverage.py:test_template_lifecycle_and_scheduling_preserve_the_scheduled_copy`; `tests/test_coach_training_template_tools.py:test_requires_operation_and_template_scope_before_manager_resolution`.

### Requirement: TL2 Atomic template lifecycle
The system SHALL support authorized template update, archive, restore and delete as local operations, preserve identity and derived metadata according to changed content, and execute a bounded template batch atomically.

#### Scenario: Edit or archive template
- **WHEN** a resolved template is updated, archived or restored
- **THEN** its local ID is preserved, content is validated, applicable derived data is retained or reconciled and sync state becomes local.

#### Scenario: Delete template
- **WHEN** an authorized delete targets an existing reusable template
- **THEN** only that local template and its local remote-link record are removed and its history is recorded; independently scheduled copies remain.

#### Scenario: Batch failure
- **WHEN** one of up to twenty-eight requested template changes fails after an earlier write
- **THEN** the entire batch rolls back on the currently active database manager rather than committing earlier changes.

Evidence: `backend/coach/training_template_tools.py:TrainingTemplateToolService.execute`; `backend/planning/library_service.py:WorkoutLibraryService.update`; `backend/planning/library.py:updated_workout_library_entry`; `tests/test_coach_training_template_tools.py:test_restore_batch_uses_current_manager_and_rolls_back_prior_write`; `tests/test_planning_library_mutations.py:test_derived_fields_are_retained_when_only_name_changes`; `tests/test_coach_tool_coverage.py:test_template_lifecycle_and_scheduling_preserve_the_scheduled_copy`.

### Requirement: TL3 Independent local scheduling from the library
The system SHALL apply selected saved library entries to local dates as an atomic batch of at most fourteen entries, creating independent planned-unit identities without remote writes.

#### Scenario: Schedule templates
- **WHEN** the athlete selects valid library UUID/date pairs with no conflicts
- **THEN** the system copies their supported workout content into locally scheduled planned units and returns local-planned counts and references.

#### Scenario: Later template edit
- **WHEN** the original template is subsequently edited or deleted
- **THEN** the scheduled copy retains its content and identity rather than following live template changes.

#### Scenario: Invalid selection
- **WHEN** the batch is empty, exceeds fourteen, has malformed IDs/dates, references missing/corrupt library data or consists of two copies of the same template/date selection
- **THEN** it fails without scheduling an earlier part of the batch.

Evidence: `backend/planning/library_plan_service.py:WorkoutLibraryPlanService.apply`, `backend/planning/library_plan_service.py:WorkoutLibraryPlanService._library_plan_request`, `backend/planning/library_plan_service.py:WorkoutLibraryPlanService._apply_request`; `tests/test_server_planning.py:test_saved_library_plan_can_be_applied_locally_as_a_batch`, `tests/test_server_planning.py:test_library_plan_rejects_duplicate_source_on_same_date`, `tests/test_server_planning.py:test_library_plan_is_local_only`; `tests/test_coach_tool_coverage.py:test_template_lifecycle_and_scheduling_preserve_the_scheduled_copy`.

### Requirement: TL4 Calendar-constrained local planning
The system SHALL validate supported calendar conflicts and markers before activating, restoring, moving or scheduling local workouts, returning a conflict without changing unrelated sessions.

#### Scenario: Occupied date or blocking marker
- **WHEN** a requested active workout conflicts with existing planning, competition or applicable external-calendar constraints
- **THEN** the system rejects the relevant create/schedule/move operation with actionable conflict information.

#### Scenario: Move with explicit time
- **WHEN** a dated unit moves to a valid date without conflict
- **THEN** its existing local time suffix is retained unless a valid new local start time is supplied; the start date must agree with the workout date.

#### Scenario: Undo would create a new conflict
- **WHEN** restoring a hidden/deleted unit would collide with newer planning
- **THEN** restore is rejected instead of overwriting the newer session.

Evidence: `backend/planning/library_plan_service.py:WorkoutLibraryPlanService._library_plan_conflicts`; `backend/planning/planned_unit_service.py:PlannedUnitService._update_in_db`, `backend/planning/planned_unit_service.py:PlannedUnitService._reject_restore_conflict`; `backend/planning/planned_units.py:prepare_planned_workout_date`; `tests/test_planning_planned_units.py:test_candidate_moves_existing_start_time_and_accepts_a_new_valid_time`; `tests/test_server_planning.py:test_planned_unit_undo_rejects_a_new_date_conflict`; `tests/test_planning_workouts.py:test_normalize_requires_start_timestamp_to_match_workout_date`.

### Requirement: TL5 Stable dated planned-unit edits and soft deletion
The system SHALL keep dated local planned units distinct from templates, preserve their IDs on edits/moves/archive/restore, and represent deletion as local hidden/deleted state pending explicit remote reconciliation.

#### Scenario: Edit or move a planned workout
- **WHEN** an authorized local action changes content, sport or date
- **THEN** the existing planned-unit identity and supported metadata are retained, content is normalized, its revision advances and the record is locally dirty.

#### Scenario: Archive, restore or delete
- **WHEN** the athlete authorizes a visibility change
- **THEN** archive/restore changes visibility; delete marks archived/local_deleted with audit history rather than issuing an immediate provider delete.

#### Scenario: Missing or corrupt planning row
- **WHEN** the ID is missing, payload is corrupt, or the target is not a dated planned unit
- **THEN** mutation fails with the applicable not-found, corrupt-data or forbidden-target response.

Evidence: `backend/planning/planned_unit_service.py:PlannedUnitService.update`, `backend/planning/planned_unit_service.py:PlannedUnitService._load_for_update`, `backend/planning/planned_unit_service.py:PlannedUnitService._save_update`; `backend/planning/planned_units.py:planned_workout_update_candidate`; `tests/test_coach_tool_coverage.py:test_planned_unit_lifecycle_keeps_identity_until_deleted`; `tests/test_planning_planned_units.py:test_candidate_supports_update_archive_and_restore`, `tests/test_planning_planned_units.py:test_restore_candidate_clears_local_deleted_but_current_metadata_is_preserved`; `tests/test_planning_planned_mutations.py:test_corrupt_json_and_non_object_payloads_are_rejected`.

### Requirement: TL6 Bounded library browsing and revision-bound plan enumeration
The system SHALL expose active undated library pages and separately enumerate future planned-unit references with current hashes, inactive flags and revision-bound cursors.

#### Scenario: Library browsing
- **WHEN** the authenticated athlete browses `/api/library`
- **THEN** active undated templates are sorted by sport/name/ID, bounded to the page limit and accompanied by a next cursor when more remain; Coach listing can explicitly include archived templates.

#### Scenario: Complete planning repair read
- **WHEN** `read_training_state` enumerates future planned units with include_inactive enabled
- **THEN** each reference includes local ID, date, visibility, sync state and expected payload hash, with has_more and next_cursor for complete enumeration.

#### Scenario: Enumeration drifts
- **WHEN** the planning revision, local day or include-inactive choice changes between pages
- **THEN** the cursor is rejected with a revision conflict requiring enumeration to restart rather than silently mixing snapshots.

Evidence: `backend/http_api/library_page.py:LibraryPageService.page`; `backend/planning/library_service.py:WorkoutLibraryService.page_in_transaction`; `backend/planning/state_service.py:StructuredTrainingStateService.read`, `backend/planning/state_service.py:StructuredTrainingStateService._after_key`; `tests/test_planning_state_service.py` (cursor/page contracts); `tests/test_coach_read_tools.py:test_dispatches_every_read_tool_and_projects_existing_shapes`; `tests/test_planning_library_selection.py:test_required_hash_rejects_missing_or_malformed_hash`. Library browser pagination is implementation-inspected; this worker did not execute its HTTP/browser path.

### Requirement: TL7 Executable endurance workout validation
The system SHALL validate quantity-first machine-readable endurance steps, consistent target types and total duration before local storage/export, while allowing supported non-endurance prose.

#### Scenario: Valid structured workout
- **WHEN** an endurance workout contains parseable duration/distance steps with valid targets, repeats and warmup/cooldown
- **THEN** it is normalized using the implemented zone syntax and timed totals include repeats and rests; non-distance duration disagreement beyond thirty seconds is rejected.

#### Scenario: Ambiguous extension or missing target
- **WHEN** a dash step contains multiple quantities, starts with conditional prose before a quantity, lacks executable steps or omits a required target
- **THEN** validation returns its specific error instead of inventing missing minutes, intensities or optional distance.

#### Scenario: Distance and non-endurance content
- **WHEN** a distance-based workout includes an estimated overall duration, or a supported non-endurance workout uses prose
- **THEN** distance sessions retain the timed-subtotal constraint and non-endurance prose uses its implemented validation policy.

Evidence: `backend/planning/workout_validation.py:validate_workout_description`, `backend/planning/workout_validation.py:_validate_endurance_workout_steps`, `backend/planning/workout_validation.py:_validate_workout_duration_match`; `backend/planning/workouts.py:normalize_workout`; `tests/test_planning_workouts.py:test_ambiguous_steps_keep_german_message_and_reason`, `tests/test_planning_workouts.py:test_endurance_parser_preserves_missing_step_and_target_reasons`, `tests/test_planning_workouts.py:test_composite_time_and_thirty_second_tolerance`, `tests/test_planning_workouts.py:test_distance_steps_allow_estimated_total_but_preserve_timed_subtotal`, `tests/test_planning_workouts.py:test_normalize_canonicalizes_endurance_zones_and_keeps_non_endurance_prose`.

### Requirement: TL8 Local export preparation and explicit provider write boundary
The system SHALL build validated provider-neutral planned workout exports and provider payloads without contacting providers, and SHALL reach outbound create/update/plan/delete only through the explicit synchronization use case.

#### Scenario: Local payload preparation
- **WHEN** export serialization or readback validation is requested locally
- **THEN** it checks date, sport, target and duration and produces the payload without opening transport or mutating remote state.

#### Scenario: Export date/duration invalid
- **WHEN** a planned export is older than the implemented yesterday boundary or outside the five-to-six-hundred-minute dated range
- **THEN** payload preparation rejects it with no remote call.

#### Scenario: Explicit library export
- **WHEN** an athlete explicitly initiates an authorized export to a target supporting library/planned events
- **THEN** the appropriate target operation is used; simply creating a local template, committing a local plan or applying a library entry does not perform that export.

Evidence: `backend/planning/workout_export.py:build_planned_workout_export`; `backend/sync/workout_export.py:WorkoutExportPort`, `backend/sync/workout_export.py:WorkoutLibraryExportPort`; `tests/test_workout_library_export.py:test_serialize_and_readback_never_open_the_transport`, `tests/test_workout_library_export.py:test_serialize_library_matches_the_planning_payload`; `tests/test_workout_export_parity.py:test_export_port_payload_matches_golden_for_every_payload_case`; `tests/test_planning_workouts.py:test_event_date_boundary_and_duration_limits`.

### Requirement: TL9 Library export identity and failure recovery
The system SHALL preserve local-to-remote workout identities across explicit exports, verify readback before reporting synchronization, and retain recoverable identity when a remote create succeeded but parsing/readback failed.

#### Scenario: Known or recovered remote template
- **WHEN** a local library record has a known remote link or an exact recoverable remote match
- **THEN** explicit export updates/adopts that identity rather than creating another remote entry.

#### Scenario: Failed readback or persistence
- **WHEN** remote response verification fails after identity is known
- **THEN** the identity remains available for a later update retry; local slot and link persistence remain atomic rather than claiming a verified sync.

#### Scenario: Provider refresh only
- **WHEN** library refresh is requested while local entries are pending
- **THEN** it reads through the target's cancellation-aware library path without implicitly uploading pending local entries or overwriting preserved dirty local content.

Evidence: `backend/planning/library.py:library_workout_matches`; `backend/sync/library.py:WorkoutLibraryRemoteReconciler.reconcile`, `backend/sync/library.py:WorkoutLibraryRemoteReconciler._preserved_dirty_library_workout`; `tests/test_workout_library_export.py:test_known_entry_is_updated_by_the_link_identity`, `tests/test_workout_library_export.py:test_recovered_remote_entry_is_adopted_without_creating`, `tests/test_workout_library_export.py:test_failed_readback_keeps_identity_in_slot_and_link_together`, `tests/test_workout_library_export.py:test_finish_failure_rolls_back_slot_and_link_in_one_transaction`; `tests/test_server_planning.py:test_unparsed_library_export_keeps_identity_and_retries_as_update`, `tests/test_server_planning.py:test_library_refresh_is_read_only_even_with_pending_local_entries`.

### Requirement: TL10 Exact explicit sync selection and complete repair manifests
The system SHALL bind explicit plan pushes to concrete local IDs/current hashes, resolve created/all-pending selections on the server, and require a complete future-period manifest for repair rather than widening a partial model selection.

#### Scenario: Selected, created or all-pending push
- **WHEN** an approved named plan sync selects existing units, this turn's successfully created units or all pending units
- **THEN** selected entries require exact current IDs/hashes, created resolves only successful additions from this turn, and all-pending freezes the server-resolved concrete selection; later additions do not expand the approval.

#### Scenario: Complete repair request
- **WHEN** an explicit repair requests a future period with current revision and no entries
- **THEN** the server includes active, already-synced and superseded inactive units in that period, validates the complete current manifest, and queues bounded provider jobs; an explicit incomplete selection conflicts.

#### Scenario: Failed prerequisite or stale manifest
- **WHEN** local creation failed, current hashes/revision changed or approval no longer matches
- **THEN** no dependent push is queued and the caller must repair/reread the actual local state rather than sync partially created data.

#### Scenario: Conflict recovery and job retry
- **WHEN** an explicit conflict choice reaches the authorized conflict service or a failed/partial sync job is retried
- **THEN** the recorded strategy is applied locally or the original job is retried with its original provider and required read/push authority; a mismatched provider or remote-write declaration is rejected.

Evidence: `backend/coach/tool_preparation.py:CoachStructuredToolPreparationService._prepare_plan_sync`; `backend/coach/proposal_creation.py:_approved_plan_sync_arguments`; `backend/sync/plan_selection.py:StructuredPlanSyncService`; `backend/sync/plan_repair.py:PlanRepairManifestService`; `backend/sync/plan_commands.py:PlanPushCommandService.enqueue`; `backend/coach/sync_tools.py:CoachSyncToolService._resolve_conflict`; `tests/test_coach_tool_preparation.py:test_created_plan_sync_projects_exact_ids_and_scopes`, `tests/test_coach_tool_preparation.py:test_all_pending_captures_a_concrete_manifest_for_approval`, `tests/test_coach_tool_preparation.py:test_selected_sync_requires_entries_unless_repairing`; `tests/test_coach_sync_tools.py:test_plan_repair_checks_object_scopes_before_mutation`, `tests/test_coach_sync_tools.py:test_retry_requires_matching_provider_and_remote_write_intent`; `tests/test_coach_tool_coverage.py:test_all_pending_approval_does_not_expand_to_units_added_after_preview`. Complete remote repair execution belongs to provider capabilities; no real remote sync was exercised here. The local-choice tool's catalog/write-gate mismatch is recorded separately rather than promised as universally available through chat.
