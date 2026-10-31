# training-library Specification

## Purpose

Describe locally authoritative reusable workout templates and their dated planned copies, browsing, mutation, export validation and explicit synchronization boundary. Full-plan transactions and adaptive previews belong to training-plans-and-adaptation.

## Requirements

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
The system SHALL support authorized template update, archive, restore and deletion of unlinked templates as local operations, preserve identity and derived metadata according to changed content, and execute a bounded template batch atomically.

#### Scenario: Edit or archive template
- **WHEN** a resolved template is updated, archived or restored
- **THEN** its local ID is preserved, content is validated, applicable derived data is retained or reconciled and sync state becomes local.

#### Scenario: Delete unlinked template
- **WHEN** an authorized delete targets an existing reusable template whose stored external_id is empty
- **THEN** only that local template and any local remote-link record are removed and its history is recorded; independently scheduled copies and remote provider state remain unchanged.

#### Scenario: Linked template deletion is refused
- **WHEN** an authorized delete targets a reusable template with a stored external_id
- **THEN** deletion fails with HTTP 409 and directs the athlete to archive it instead; supported archival retains its identity/link, marks it archived and locally pending, and performs no immediate provider write or scheduled-copy mutation.

#### Scenario: Batch failure
- **WHEN** one of up to twenty-eight requested template changes fails after an earlier write
- **THEN** the entire batch rolls back on the currently active database manager rather than committing earlier changes.

Evidence: `backend/coach/training_template_tools.py:TrainingTemplateToolService.execute`; `backend/planning/library_service.py:WorkoutLibraryService.update`, `backend/planning/library_service.py:WorkoutLibraryService._delete_local_workout_library_entry`; `tests/test_library_service.py:test_delete_is_physical_and_records_before_history_after_commit`, `tests/test_library_service.py:test_synchronized_entry_cannot_be_deleted_but_can_be_archived`; `backend/planning/library.py:updated_workout_library_entry`; `tests/test_coach_training_template_tools.py:test_restore_batch_uses_current_manager_and_rolls_back_prior_write`; `tests/test_planning_library_mutations.py:test_derived_fields_are_retained_when_only_name_changes`; `tests/test_coach_tool_coverage.py:test_template_lifecycle_and_scheduling_preserve_the_scheduled_copy`.

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
The system SHALL preserve the local template UUID across explicit exports, reuse a usable existing or recovered remote identity, and replace a missing remote identity only through the supported recovery path within an explicitly authorized library sync. It SHALL store a usable returned identity before readback validation and mark only unchanged local content synced after validation.

#### Scenario: Known or recovered remote template
- **WHEN** a local library record has a stored remote link whose update succeeds, or supported recovery finds an exact remote match
- **THEN** explicit export updates/adopts that usable identity rather than creating another remote entry.

#### Scenario: Update reports remote not found
- **WHEN** an explicitly authorized library sync receives HTTP 404 while updating the stored remote identity, through either AppError.upstream_status or ProviderHTTPError.status
- **THEN** it marks the entry remote_missing while retaining dirty local content and its local UUID, lists the remote library and adopts an exact recoverable match if present; otherwise it creates a replacement. The recovered or replacement identity is stored and its response verified through the normal state path before unchanged local content is marked synced.

#### Scenario: Other remote update failure
- **WHEN** updating the stored remote identity fails with an error other than HTTP 404
- **THEN** the error propagates, the existing slot/link identity and dirty local content are retained with sync_error, and no remote-library listing or replacement create is attempted.

#### Scenario: Failed readback or persistence
- **WHEN** readback or local identity/sync persistence fails after a remote write
- **THEN** no verified sync is reported; local slot and link writes commit or roll back together, already persisted identity remains available for an update retry, and a later explicit retry without a usable identity searches for an exact recoverable remote match before creating another entry.

#### Scenario: Provider refresh only
- **WHEN** library refresh is requested while local entries are pending
- **THEN** it reads through the target's cancellation-aware library path without implicitly uploading pending local entries or overwriting preserved dirty local content.

Evidence: `backend/planning/library.py:library_workout_matches`; `backend/sync/library.py:WorkoutLibrarySyncService.sync_entry`, `backend/sync/library.py:WorkoutLibrarySyncService._upsert_remote`, `backend/sync/library.py:WorkoutLibrarySyncService._sync_entry_unlocked`, `backend/sync/library.py:WorkoutLibrarySyncStateService.mark_remote_missing`, `backend/sync/library.py:WorkoutLibrarySyncStateService.store_remote_identity`, `backend/sync/library.py:WorkoutLibrarySyncStateService.finish`, `backend/sync/library.py:WorkoutLibraryRemoteReconciler.reconcile`, `backend/sync/library.py:WorkoutLibraryRemoteReconciler._preserved_dirty_library_workout`; `backend/db/remote_links.py:RemoteLinkRepository.refresh_from_slots`; `tests/test_sync_library.py:test_update_upstream_not_found_recreates_remote_workout`, `tests/test_sync_library.py:test_update_provider_http_not_found_recreates_remote_workout`, `tests/test_sync_library.py:test_update_upstream_failure_other_than_not_found_keeps_sync_error`, `tests/test_sync_library.py:test_update_provider_http_failure_other_than_not_found_keeps_sync_error`, `tests/test_sync_library.py:test_sync_entry_recovers_remote_missing_before_creating`, `tests/test_sync_library.py:test_retry_after_lost_identity_adopts_the_created_remote_workout`, `tests/test_sync_library.py:test_create_response_keeps_a_local_edit_made_during_upload`, `tests/test_sync_library.py:test_update_response_keeps_a_local_edit_made_during_upload`; `tests/test_workout_library_export.py:test_known_entry_is_updated_by_the_link_identity`, `tests/test_workout_library_export.py:test_recovered_remote_entry_is_adopted_without_creating`, `tests/test_workout_library_export.py:test_failed_readback_keeps_identity_in_slot_and_link_together`, `tests/test_workout_library_export.py:test_finish_failure_rolls_back_slot_and_link_in_one_transaction`; `tests/test_server_planning.py:test_unparsed_library_export_keeps_identity_and_retries_as_update`, `tests/test_server_planning.py:test_library_refresh_is_read_only_even_with_pending_local_entries`. Slot/link atomicity is local; these checks do not provide remote compare-and-swap or rollback of a completed provider write.

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

Evidence: `backend/coach/tool_preparation.py:CoachStructuredToolPreparationService._prepare_plan_sync`; `backend/coach/proposal_creation.py:_approved_plan_sync_arguments`; `backend/sync/plan_selection.py:StructuredPlanSyncService`; `backend/sync/plan_repair.py:PlanRepairManifestService`; `backend/sync/plan_commands.py:PlanPushCommandService.enqueue`; `backend/coach/sync_tools.py:CoachSyncToolService._resolve_conflict`; `tests/test_coach_tool_preparation.py:test_created_plan_sync_projects_exact_ids_and_scopes`, `tests/test_coach_tool_preparation.py:test_all_pending_captures_a_concrete_manifest_for_approval`, `tests/test_coach_tool_preparation.py:test_selected_sync_requires_entries_unless_repairing`; `tests/test_coach_sync_tools.py:test_plan_repair_checks_object_scopes_before_mutation`, `tests/test_coach_sync_tools.py:test_retry_requires_matching_provider_and_remote_write_intent`; `tests/test_coach_tool_coverage.py:test_all_pending_approval_does_not_expand_to_units_added_after_preview`. Intervals planned-calendar execution and recovery are specified in TL11-TL15; no real remote sync was exercised here. The local-choice tool's catalog/write-gate mismatch is recorded separately rather than promised as universally available through chat.


### Requirement: TL11 Planned-calendar upsert identity and in-flight local changes
The system SHALL use stable Intervals planned-event identity for explicit dated-unit pushes, validate the returned event before marking the unchanged local unit synced, and preserve newer local content and recoverable remote identity when the upload races with local changes or result validation fails.

#### Scenario: Create and later update
- **WHEN** an explicit normal push exports an active planned unit and a later push retries or updates it
- **THEN** the initial external_id is derived from its local UUID as `intervals-coach-<local_id>`; a stored remote external_id is reused and a known remote_event_id is included on subsequent upserts.

#### Scenario: Returned event fails validation
- **WHEN** an upsert returns a concrete event identity but its sport or applicable parsed endurance content fails readback validation
- **THEN** the service raises the validation error and persists sync_error with the returned remote identity and external identity for recovery; it does not mark that payload synced.

#### Scenario: No usable returned identity
- **WHEN** the normal upsert response has no first event object with a nonempty event ID
- **THEN** the push fails rather than inventing an ID or reporting synchronization; a remote write may already have occurred and the stable external identity remains the retry basis.

#### Scenario: Local edit, move, archive or deletion during upload
- **WHEN** the local payload changes or the row disappears while an earlier payload is uploaded
- **THEN** persistence retains the newer content and returned remote identity, leaves the changed unit locally dirty and pending instead of syncing the newer payload, or recreates a hidden deletion tombstone for later explicit remote cleanup; a later push uses the retained identity.

#### Scenario: Same-unit pushes overlap
- **WHEN** normal sync or repair is already running for the same local ID
- **THEN** another push for that ID is rejected with a running-sync conflict and the guard is released when the active operation exits.

Evidence: `backend/sync/planned_calendar.py:PlannedCalendarSyncService._event_payload`, `backend/sync/planned_calendar.py:PlannedCalendarSyncService._remote_event`, `backend/sync/planned_calendar.py:planned_unit_sync_guard`; `backend/sync/reconcile.py:PlannedUnitSyncStateWriter._state_values`; `backend/providers/intervals_workouts.py:intervals_external_id`; `tests/test_sync_planned_calendar.py:test_create_and_retry_use_stable_external_identity`, `tests/test_sync_planned_calendar.py:test_readback_validation_failure_persists_identity_and_sync_error`, `tests/test_sync_planned_calendar.py:test_malformed_provider_result_is_rejected`, `tests/test_sync_planned_calendar.py:test_edit_during_upload_keeps_new_payload_pending_and_retries_it`, `tests/test_sync_planned_calendar.py:test_reschedule_during_upload_stays_pending_and_retries_new_date`, `tests/test_sync_planned_calendar.py:test_archive_during_upload_keeps_identity_until_remote_cleanup`, `tests/test_sync_planned_calendar.py:test_delete_during_upload_becomes_remote_cleanup_tombstone`, `tests/test_sync_planned_calendar.py:test_concurrent_edit_survives_upload_validation_error`, `tests/test_sync_planned_calendar.py:test_repair_and_normal_sync_share_per_id_guard`. Normal push validates the returned event through the export port; TL14 separately requires repair collection readback.

### Requirement: TL12 Guarded explicit removal of a linked planned event
The system SHALL reconcile an archived or locally deleted planned unit through the explicit sync path, checking the stored remote event ID and its current eligibility before deletion and rechecking local content before recording removal.

#### Scenario: Remove a known eligible event
- **WHEN** normal explicit sync removes an inactive unit with a remote_event_id and reading that ID returns the same ID as an unpaired WORKOUT dated today or later
- **THEN** the service rechecks the local payload, deletes that concrete remote event and marks local removal synced only after another local-payload check.

#### Scenario: No remote ID or already absent
- **WHEN** an inactive unit has no remote event ID, or reading its linked event reports HTTP 404 directly or through the wrapped HTTP error cause
- **THEN** removal is treated as already satisfied without a remote delete and local removal is recorded subject to the final local-payload check.

#### Scenario: Linked event is no longer eligible
- **WHEN** the remote read is not an event object with the expected ID, is not a planned WORKOUT, is past, or is paired with an activity or event
- **THEN** normal removal fails with an identity conflict and issues no delete.

#### Scenario: Local payload changes after the remote read
- **WHEN** the unit changes before the pre-delete payload recheck
- **THEN** deletion is blocked with a planning revision conflict; a change detected after a remote delete also blocks the final local success record without undoing that remote delete.

Evidence: `backend/sync/planned_calendar.py:PlannedCalendarSyncService._delete_remote_event`, `backend/sync/planned_calendar.py:PlannedCalendarSyncService._mark_removed`, `backend/sync/planned_calendar.py:PlannedCalendarSyncService._remove_event`; `backend/sync/intervals_workout_export.py:IntervalsWorkoutExport.is_unpaired_future_planned`; `tests/test_sync_planned_calendar.py:test_delete_success_rechecks_and_persists_removed_state`, `tests/test_sync_planned_calendar.py:test_archived_or_deleted_without_remote_id_only_marks_local_sync`, `tests/test_sync_planned_calendar.py:test_delete_404_is_already_removed`, `tests/test_sync_planned_calendar.py:test_delete_treats_http_error_404_cause_as_already_removed`, `tests/test_sync_planned_calendar.py:test_delete_identity_conflicts`, `tests/test_sync_planned_calendar.py:test_payload_change_after_remote_read_blocks_delete`. The post-delete concurrent-edit branch is implementation-inspected; these cited tests do not inject an edit after deletion. Normal removal has no final collection readback; repair verification is covered by TL14.

### Requirement: TL13 Exact repair ownership and bounded duplicate cleanup
The system SHALL repair selected planned units dated today or later using current local hashes and concrete remote identities, refuse identified unsafe or ambiguous candidates, and limit cleanup to identity-checked related events in the repair window.

#### Scenario: Invalid local repair target
- **WHEN** the unit is missing, its expected payload hash is stale, its payload/date is invalid, or its date is before today
- **THEN** repair fails before performing a remote write.

#### Scenario: Identify related events and refuse foreign ownership
- **WHEN** the repair window contains an event with a concrete ID matching the unit's stored remote ID or a generated/stored external identity
- **THEN** it is related only if it is an unpaired planned WORKOUT dated today or later and neither its ID nor external identity belongs to another local planned unit; an identified event failing those checks causes an identity conflict.

#### Scenario: Known ID is absent from the window
- **WHEN** the stored remote ID is not among the related events read from the repair window
- **THEN** repair reads that ID directly: a 404 permits reconciliation as absent, another read failure propagates, and an event still present outside the window causes an identity conflict rather than being moved or deleted automatically.

#### Scenario: Ambiguous namesake during active repair
- **WHEN** an active unit has an otherwise unassigned planned event on the same day with the same name after case/edge-space normalization but without a matching identity
- **THEN** repair refuses automatic adoption, copy creation and deletion with an ambiguity conflict; unrelated events belonging to other local units remain outside cleanup, and removal does not adopt or delete an unlinked namesake.

#### Scenario: Create or keep one identity and remove only concrete related duplicates
- **WHEN** an active repair has passed the identity and ambiguity checks
- **THEN** it creates with the stable generated external identity if no related event remains, or prefers the stored remote ID as keeper when present and otherwise adopts a related event; an existing keeper ID/external identity is reused for upsert, and only other concrete related IDs are deleted after local-hash rechecks. An inactive repair performs no upsert and removes its concrete related IDs; an empty ID is never a delete target.

Evidence: `backend/sync/planned_calendar.py:PlannedCalendarRepairService._context`, `backend/sync/planned_calendar.py:PlannedCalendarRepairService._related_event`, `backend/sync/planned_calendar.py:PlannedCalendarRepairService._check_remote_identity`, `backend/sync/planned_calendar.py:PlannedCalendarRepairService.repair_entry`, `backend/sync/planned_calendar.py:PlannedCalendarRepairService._delete_duplicates`; `tests/test_sync_planned_calendar.py:test_repair_create_update_and_remove`, `tests/test_sync_planned_calendar.py:test_repair_rejects_corrupt_stored_payload_as_conflict`, `tests/test_sync_planned_calendar.py:test_repair_rejects_invalid_paired_foreign_and_ambiguous_events`, `tests/test_sync_planned_calendar.py:test_repair_deletes_only_identity_checked_duplicates`, `tests/test_sync_planned_calendar.py:test_delete_duplicates_never_deletes_an_empty_identity`. The known-ID-outside-window and local-past-date branches are implementation-inspected rather than demonstrated by those cited tests.

### Requirement: TL14 Repair identity retention and final collection verification
The system SHALL retain a usable repair response identity before subsequent verification, recheck local payload hashes around repair writes and completion, and mark a repair synced only after final collection readback confirms the required remote result and unchanged local content.

#### Scenario: Repair response or readback fails
- **WHEN** repair upsert returns exactly one event with a concrete ID but later schedule or workout-content validation fails
- **THEN** the returned remote ID and requested external identity have already been persisted for recovery with non-synced state; an unusable or ambiguous upsert response instead raises verification failure without inventing a remote ID.

#### Scenario: Local revision changes during repair
- **WHEN** the local payload hash changes before upsert, before a duplicate delete, after upsert or before final persistence
- **THEN** the applicable recheck refuses further success/progress with a planning revision conflict; while the local row remains, a usable identity from an already completed upsert is retained and newer local content is preserved rather than overwritten.

#### Scenario: Active repair final state
- **WHEN** final collection readback verifies an active repair
- **THEN** exactly one related eligible event must remain, its ID must equal the keeper, its day and exact name must match the local workout and its sport/applicable parsed content must pass export readback validation before the local unit becomes synced.

#### Scenario: Removal final state
- **WHEN** final collection readback verifies an inactive-unit repair
- **THEN** no related events may remain in the repair window and the current local hash must still match before local removal is marked synced.

#### Scenario: Verification is unavailable or mismatched
- **WHEN** final collection read fails, related events are missing/duplicated or still present after removal, schedule/content validation fails, or the completion hash changed
- **THEN** repair does not record verified local success; selected-batch execution records the affected error as described in TL15 and retains any already persisted remote identity.

Evidence: `backend/sync/planned_calendar.py:PlannedCalendarRepairService._upsert`, `backend/sync/planned_calendar.py:PlannedCalendarRepairService._recheck`, `backend/sync/planned_calendar.py:PlannedCalendarRepairService._completion`, `backend/sync/planned_calendar.py:PlannedCalendarRepairBatch.verify`; `tests/test_sync_planned_calendar.py:test_repair_hash_conflict_before_write`, `tests/test_sync_planned_calendar.py:test_repair_hash_conflict_before_final_persist_preserves_written_remote_id`, `tests/test_sync_planned_calendar.py:test_repair_readback_failure_keeps_remote_identity`, `tests/test_sync_planned_calendar.py:test_repair_preserves_requested_external_id_from_provider_response`, `tests/test_sync_planned_calendar.py:test_repair_batch_verify_failure_and_collection_error_are_propagated`, `tests/test_sync_planned_calendar.py:test_repair_batch_shares_two_reads_and_deferred_verification`. These local checks and collection snapshots are not remote compare-and-swap: an external edit can race with a write, and local failure cannot roll back an already completed remote upsert/delete. The cited tests exercise representative failures; not every final-read mismatch branch is separately executed.

### Requirement: TL15 Selected execution reports mixed outcomes and failed-object retry scope
The system SHALL execute the exact selected sync entries with per-entry outcomes, defer repair success until shared collection verification, and report failures without implying an atomic transaction across remote operations.

#### Scenario: Route the frozen selection
- **WHEN** an Intervals plan_push job executes
- **THEN** its concrete entries and repair flag are passed to selected synchronization; each entry is checked for existence and current payload hash, and planned units route to normal push or repair without widening the selection.

#### Scenario: Shared repair snapshots and lock
- **WHEN** a selected repair batch executes
- **THEN** it waits for the Intervals sync lock or fails temporarily, shares its initial remote window snapshot and final collection read across deferred completions, and releases the lock on exit; final-read failures apply to each deferred completion instead of accepting its provisional result.

#### Scenario: Verification overrides a provisional result
- **WHEN** an entry's repair operation or deferred verification fails
- **THEN** selected execution records its sync_error, returns a redacted bounded per-entry error, and changes a provisional calendar_synced result to error with calendar_synced false when final verification fails.

#### Scenario: Mixed success and failure
- **WHEN** the selected entries finish with successes and errors/conflicts
- **THEN** the aggregate status is partial, or error if every entry failed, with failed_object_ids and retry_scope directing selection of only failed objects; an all-success result is ok with no retry scope. Completed remote effects for other entries remain in place even if a later entry fails.

Evidence: `backend/sync/executor.py:IntervalsSyncJobOwner.execute_specific`; `backend/sync/selected.py:SelectedWorkoutSyncService.sync`, `backend/sync/selected.py:SelectedWorkoutSyncService._sync_unlocked`, `backend/sync/selected.py:SelectedWorkoutSyncService._sync_entry`, `backend/sync/selected.py:SelectedWorkoutSyncService._verify_repair`; `backend/sync/planned_calendar.py:PlannedCalendarRepairBatch.snapshot`, `backend/sync/planned_calendar.py:PlannedCalendarRepairBatch.verify`; `tests/test_sync_executor.py:test_dispatches_specific_intervals_jobs_and_preserves_plan_repair`; `tests/test_sync_selected.py:test_planned_normal_and_repair_paths`, `tests/test_sync_selected.py:test_hash_and_not_found_conflicts_are_aggregated`, `tests/test_sync_selected.py:test_partial_and_all_failure_aggregation`, `tests/test_sync_selected.py:test_repair_errors_are_recorded_and_verification_failure_overrides_result`, `tests/test_sync_selected.py:test_repair_lock_timeout_release_and_exception_cleanup`; `tests/test_sync_planned_calendar.py:test_repair_batch_shares_two_reads_and_deferred_verification`. Retry scope here is the selected operation's failed-object guidance; the separately authorized durable job retry in TL10 retains the original job selection. Evidence uses inspected implementation and synthetic/mocked tests, not a live provider or a distributed rollback guarantee.

### Requirement: TL16 Provider-neutral planning record fields
Local planning records (planned units, workout-library entries, competitions, staged plan workouts and adaptive previews) SHALL store and return their local start as `starts_at_local` and their planned duration in seconds as `planned_duration_s`, in the HTTP API, Coach tools and Coach context alike. Only the Intervals.icu adapter SHALL map these fields to and from the Intervals.icu event and workout fields `start_date_local` and `moving_time`, so payloads sent to Intervals.icu stay unchanged.

#### Scenario: Remote workout import
- **WHEN** an Intervals.icu planned event or library workout is imported
- **THEN** the stored local record names its start and duration `starts_at_local` and `planned_duration_s`.

#### Scenario: Explicit export to Intervals.icu
- **WHEN** an athlete explicitly synchronizes planned units, library workouts or competitions
- **THEN** the Intervals.icu payload carries `start_date_local` and `moving_time` exactly as before.

#### Scenario: Coach save of a competition
- **WHEN** an athlete-started Coach turn saves a competition with `starts_at_local` and `planned_duration_s`
- **THEN** the competition is stored with those values.

Evidence: `backend/providers/intervals_workouts.py::planning_fields_from_intervals`, `backend/providers/intervals_workouts.py::intervals_fields_from_planning`, `backend/providers/intervals_workouts.py::intervals_event_payload`; `backend/sync/intervals_workout_export.py::IntervalsWorkoutExport`; `backend/sync/competitions.py::CompetitionSyncService.sync`; `backend/sync/planned_units.py`; `backend/sync/reconcile.py`. Tests: `tests/test_workout_export_parity.py::test_export_port_payload_matches_golden_for_every_payload_case`; `tests/test_workout_export_intervals.py::test_library_workouts_cross_the_adapter_with_planning_field_names`; `tests/test_workout_export_intervals.py::test_library_readback_checks_the_remote_duration_under_its_wire_name`; `tests/test_planning_competitions.py::test_event_payload_fallbacks_limits_and_input_immutability`; `tests/test_sync_adaptive.py::test_sync_sends_the_illness_start_under_the_intervals_wire_name`; `tests/test_server_coach.py`.
