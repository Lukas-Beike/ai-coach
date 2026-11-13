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

#### Scenario: Copied fields and result
- **WHEN** the batch succeeds
- **THEN** each new unit copies sport, name, description, duration, target, the focus fields and the strength structure of its template and carries `source` `library`, the template's `template_id` and the rationale "Aus der lokalen Trainingsbibliothek übernommen."; the result is `status: local`, `planned` (per entry `library_workout_id`, `date`, `status`, `library_entry`) and `local_planned`, and several different templates may share one date.

#### Scenario: Conflicts with the calendar of a date
- **WHEN** a requested date holds a competition, an ordinary training-relevant calendar event or a calendar marker that blocks the day
- **THEN** the batch answers 409 "Planung wegen bestehender Kalendereinheiten nicht möglich: …" naming at most 8 conflicts; a dated legacy template planned on its own date is returned with the status `already_planned` instead of a copy.

Evidence: `backend/planning/library_plan_service.py:WorkoutLibraryPlanService.apply`, `backend/planning/library_plan_service.py:WorkoutLibraryPlanService._library_plan_request`, `backend/planning/library_plan_service.py:WorkoutLibraryPlanService._apply_request`, `backend/planning/library_plan_service.py:WorkoutLibraryPlanService._raise_conflicts`; `tests/test_library_plan_service.py:test_already_planned_entry_is_unchanged_and_skips_calendar_check`, `tests/test_library_plan_service.py:test_duplicate_conflicts_are_complete_and_limited_to_eight_descriptions`, `tests/test_library_plan_service.py:test_multiple_different_templates_on_same_date_are_allowed`; `tests/test_server_planning.py:test_saved_library_plan_can_be_applied_locally_as_a_batch`, `tests/test_server_planning.py:test_library_plan_rejects_duplicate_source_on_same_date`, `tests/test_server_planning.py:test_library_plan_is_local_only`; `tests/test_coach_tool_coverage.py:test_template_lifecycle_and_scheduling_preserve_the_scheduled_copy`.

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

#### Scenario: Local units conflict by time window
- **WHEN** two local units share a date
- **THEN** they conflict only when both have a start time and their windows overlap (start plus duration, 60 minutes when unknown and at least 1 minute, compared as local wall time with any offset dropped; windows that only touch do not conflict); a unit without a start time never conflicts with another unit, and archived or deleted units never conflict.

#### Scenario: Competitions and ordinary calendar events
- **WHEN** a unit meets a competition or an unmarked training-relevant external calendar event
- **THEN** they conflict by time window when both are timed, otherwise by date.

#### Scenario: Marker refusal
- **WHEN** an external event on any local day the unit touches blocks it by a calendar marker (rules in TP12 of training-plans-and-adaptation)
- **THEN** the write fails with 409 `plan_date_conflict` and the text "Am <TT.MM.JJJJ> ist „<Kein Training|Keine Intensität|Nur kurze Einheiten>“ eingetragen. Die lokale Einheit verletzt diese Kalenderbeschränkung."

Detailed contract: conflicts are listed in the order markers, local units, competitions, ordinary events; a conflict record holds `id`, `name`, `date`, `source` (`local_library`, `local_competition`, `external_calendar`), `match` (`date`, `time_window`, `calendar_constraint`), `start_local` and `end_local`; a marker record adds `constraint`, `reason` and `updated_at`.

Evidence: `backend/planning/calendar.py:marker_conflict_message`, `backend/planning/calendar_service.py:CalendarConflictService.conflicts`, `backend/planning/calendar_service.py:CalendarConflictService.constraints`, `backend/planning/conflicts.py:calendar_items_conflict`, `backend/planning/library_plan_service.py:WorkoutLibraryPlanService._library_plan_conflicts`; `backend/planning/planned_unit_service.py:PlannedUnitService._update_in_db`, `backend/planning/planned_unit_service.py:PlannedUnitService._reject_restore_conflict`; `backend/planning/planned_units.py:prepare_planned_workout_date`; `tests/test_planning_planned_units.py:test_candidate_moves_existing_start_time_and_accepts_a_new_valid_time`; `tests/test_server_planning.py:test_planned_unit_undo_rejects_a_new_date_conflict`; `tests/test_planned_unit_service.py:test_marker_conflict_on_create_names_the_planned_day_and_marker`; `tests/test_planning_calendar.py:test_local_library_date_only_is_not_a_conflict`, `tests/test_planning_calendar.py:test_timed_boundary_touch_is_not_a_conflict`; `tests/test_planning_calendar_service.py:test_conflicts_keep_source_order_and_exclude_archived_or_deleted_units`, `tests/test_planning_calendar_service.py:test_multi_day_no_training_event_blocks_each_overlapped_day`, `tests/test_planning_calendar_service.py:test_untimed_local_units_do_not_conflict_on_same_date`; `tests/test_planning_workouts.py:test_normalize_requires_start_timestamp_to_match_workout_date`.

### Requirement: TL5 Stable dated planned-unit edits and soft deletion
The system SHALL keep dated local planned units distinct from templates, preserve their IDs on edits/moves/archive/restore, and represent deletion as local hidden/deleted state pending explicit remote reconciliation.

#### Scenario: Edit or move a planned workout
- **WHEN** an authorized local action changes content, sport or date
- **THEN** the existing planned-unit identity and supported metadata are retained, content is normalized, its revision advances and the record is locally dirty.

#### Scenario: Athlete moves a planned unit to another day
- **WHEN** the athlete moves a planned unit with `POST /api/planned-units/{id}/date` and the content hash of the read the move was made on
- **THEN** a day from today on is applied through the same edit and conflict checks, the start keeps its time of day, the response carries the undo reference, a sent unit shows its pending sync and no provider is written; a past day, an invalid date or an outdated hash leaves the unit unchanged.

#### Scenario: Archive, restore or delete
- **WHEN** the athlete authorizes a visibility change
- **THEN** archive/restore changes visibility; delete marks archived/local_deleted with audit history rather than issuing an immediate provider delete.

#### Scenario: Missing or corrupt planning row
- **WHEN** the ID is missing, payload is corrupt, or the target is not a dated planned unit
- **THEN** mutation fails with the applicable not-found, corrupt-data or forbidden-target response.

#### Scenario: Normalised fields of a unit
- **WHEN** a unit is created or edited
- **THEN** the name has at most 200 characters (default "Coach-Einheit"), the description at most 12000 and is required, the rationale at most 2000 (default "Manuell geplante Einheit"), the target is `AUTO`, `POWER`, `HR` or `PACE` (another value becomes `AUTO`, a Coach create with another value fails), the duration is a whole number of 5 to 600 minutes and `starts_at_local` is an ISO timestamp on the unit's date, cut to 40 characters.

#### Scenario: Move into the past
- **WHEN** a unit moves to a date older than yesterday
- **THEN** it fails with 400 "Eine Einheit in der Vergangenheit wird nicht geplant." unless the unit already was that old.

#### Scenario: Edit targets and actions
- **WHEN** an edit names an id that is no UUID, an unknown id, an undated row or a corrupt payload
- **THEN** it fails with 400, 404 "Lokale Planung nicht gefunden.", 403 "Nur lokale geplante Einheiten können bearbeitet werden." or 500 respectively; the actions are `update`, `archive`, `restore` and `delete`, another action is 400 "Unbekannte Aktion für lokale Planung.".

Evidence:
- `backend/http_api/planned_unit_focus_post.py`
- `backend/planning/planned_unit_service.py:PlannedUnitService._load_for_update`
- `backend/planning/planned_unit_service.py:PlannedUnitService._save_update`
- `backend/planning/planned_unit_service.py:PlannedUnitService.move`
- `backend/planning/planned_unit_service.py:PlannedUnitService.update`
- `backend/planning/planned_units.py:planned_workout_update_candidate`
- `backend/planning/planned_units.py:prepare_planned_workout_date`
- `backend/planning/workouts.py:normalize_workout`
- `tests/test_coach_tool_coverage.py:test_planned_unit_lifecycle_keeps_identity_until_deleted`
- `tests/test_http_planned_unit_focus_post.py:test_date_route_moves_the_unit_and_returns_the_undo_reference`
- `tests/test_planned_unit_service.py:test_athlete_moves_a_sent_unit_to_another_day_from_today_on`
- `tests/test_planned_unit_service.py:test_missing_corrupt_and_undated_rows_keep_their_error_contracts`
- `tests/test_planning_planned_mutations.py:test_strips_date_and_preserves_existing_time_suffix_on_change`
- `tests/test_planning_planned_units.py:test_candidate_supports_update_archive_and_restore`
- `tests/test_planning_planned_units.py:test_restore_candidate_clears_local_deleted_but_current_metadata_is_preserved`

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

#### Scenario: Which sports need steps
- **WHEN** a unit's Intervals.icu type is one of the 28 endurance types (the ride variants, the run, walk, hike and wheelchair types, the swim, rowing and paddling types, the ski, skate and snowshoe types, Elliptical and StairStepper; the set is `INTERVALS_ENDURANCE_WORKOUT_TYPES`)
- **THEN** its description is validated as quantity-first steps; every other sport keeps free text.

#### Scenario: Export type of a sport
- **WHEN** a unit is exported
- **THEN** an indoor environment uses the virtual type, a kept original type name is used again while it still names the stored sport and environment, and a sport without a type becomes `Other`.

Evidence: `backend/providers/intervals_workouts.py:INTERVALS_ENDURANCE_WORKOUT_TYPES`, `backend/providers/intervals_workouts.py:intervals_workout_type`, `backend/planning/workout_validation.py:validate_workout_description`, `backend/planning/workout_validation.py:_validate_endurance_workout_steps`, `backend/planning/workout_validation.py:_validate_workout_duration_match`; `backend/planning/workouts.py:normalize_workout`; `tests/test_canonical_workout_sports.py`, `tests/test_workout_text.py:test_all_endurance_families_still_require_executable_steps`, `tests/test_planning_workouts.py:test_ambiguous_steps_keep_german_message_and_reason`, `tests/test_planning_workouts.py:test_endurance_parser_preserves_missing_step_and_target_reasons`, `tests/test_planning_workouts.py:test_composite_time_and_thirty_second_tolerance`, `tests/test_planning_workouts.py:test_distance_steps_allow_estimated_total_but_preserve_timed_subtotal`, `tests/test_planning_workouts.py:test_normalize_canonicalizes_endurance_zones_and_keeps_non_endurance_prose`.

### Requirement: TL8 Local export preparation and explicit provider write boundary
The system SHALL build validated provider-neutral planned workout exports and provider payloads without contacting providers, and SHALL reach outbound create/update/plan/delete (Intervals.icu) and plan pushes (Wahoo, Garmin strength) only through an explicit synchronization use case or job. Intervals.icu is an output target: nothing in the library or the plan is read back from it.

#### Scenario: Local payload preparation
- **WHEN** export serialization or readback validation is requested locally
- **THEN** it checks date, sport, target and duration and produces the payload without opening transport or mutating remote state.

#### Scenario: Export date/duration invalid
- **WHEN** a planned export is older than the implemented yesterday boundary or outside the five-to-six-hundred-minute dated range
- **THEN** payload preparation rejects it with no remote call.

#### Scenario: Explicit library export
- **WHEN** an athlete explicitly initiates an authorized export to a target supporting library/planned events
- **THEN** the appropriate target operation is used; simply creating a local template, committing a local plan or applying a library entry does not perform that export.

#### Scenario: Export defaults
- **WHEN** a unit is exported
- **THEN** the start is `starts_at_local` or `<date>T00:00:00`, the name has at most 200 characters (default "Coach workout"), the description at most 12000, and the duration is the sum of the structured steps when the workout has no distance step, else the stated minutes times 60.

#### Scenario: Readback criteria
- **WHEN** the returned event or workout is checked
- **THEN** its type equals the exported sport (a note without a type passes), a calendar event is a `NOTE` for strength and a `WORKOUT` otherwise, and for endurance sports the returned workout document has the same number of steps with matching quantity, ramp flag and target, positive step durations, a document duration and a reported duration within max(1, number of steps) seconds of the step sum, and a positive training load.

#### Scenario: Failure reasons
- **WHEN** a check fails
- **THEN** the error is 502 with the reason `intervals_workout_sport_mismatch`, `intervals_workout_category_mismatch` or the workout-text reason; local validation errors are 400 with `ambiguous_workout_step`, `workout_duration_mismatch` or `invalid_workout_start_date`.

Detailed contract: the text grammar and the tolerances are documented in docs/workout-export-format.md.

Evidence: `backend/activities/workout_text.py:verify_workout_readback`, `backend/planning/workout_export.py:build_planned_workout_export`, `backend/planning/workouts.py:validate_intervals_workout_result`; `backend/sync/workout_export.py:WorkoutExportPort`, `backend/sync/workout_export.py:WorkoutLibraryExportPort`; `tests/test_workout_library_export.py:test_serialize_and_readback_never_open_the_transport`, `tests/test_workout_library_export.py:test_serialize_library_matches_the_planning_payload`; `tests/test_workout_export_parity.py:test_export_port_payload_matches_golden_for_every_payload_case`; `tests/test_planning_workouts.py:test_event_date_boundary_and_duration_limits`.

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

#### Scenario: No remote library import
- **WHEN** local entries are pending or the remote library holds other workouts
- **THEN** nothing is imported into the local library and nothing is uploaded implicitly; the remote library is listed only inside an explicitly authorized library sync, to find an exact match for a lost remote identity.

#### Scenario: Synced entry is a no-op
- **WHEN** an explicit export names a template that is `synced` and holds a remote identity
- **THEN** nothing is sent; any other entry stores `syncing` before the remote call and `sync_error` with the redacted text (at most 1000 characters) after any failure.

#### Scenario: Pending preview
- **WHEN** the preview of an explicit sync is read
- **THEN** it lists templates and planned units in the states `local`, `sync_error`, `remote_missing` or `conflict` (units Intervals.icu takes no part in are left out), each with `local_id`, `status`, `category` (`new`, `changed`, `missing`, `error_retry`, `planned`, `conflict`), `has_remote_id`, `planned_date`, `syncs_calendar`, `entity` and `payload_hash`, a count per category and a SHA-256 fingerprint of counts and entries.

#### Scenario: Export errors
- **WHEN** the id is invalid, the entry is missing or corrupt, the key is missing or the reply has no id
- **THEN** the answers are 400, 404 "Lokale Bibliothekseinheit nicht gefunden.", 500, 503 `not_configured` and 502 "Die Bibliothekseinheit konnte nicht zu Intervals.icu übertragen werden.".

Detailed contract: a successful export stores `last_library_push_at` and clears `last_library_sync_error`; a dated legacy template reaches the calendar only after the marker check (409 `plan_date_conflict`) and needs an external id (502); the summary counts the states per table and adds `planned_pending` (`local`, `sync_error`, `remote_missing`) and `planned_conflicts`.

Evidence:
- `backend/db/remote_links.py:RemoteLinkRepository.refresh_from_slots`
- `backend/planning/library.py:library_workout_matches`
- `backend/sync/library.py:WorkoutLibrarySyncService._sync_entry_unlocked`
- `backend/sync/library.py:WorkoutLibrarySyncService._upsert_remote`
- `backend/sync/library.py:WorkoutLibrarySyncService.sync_entry`
- `backend/sync/library.py:WorkoutLibrarySyncStateService.finish`
- `backend/sync/library.py:WorkoutLibrarySyncStateService.mark_remote_missing`
- `backend/sync/library.py:WorkoutLibrarySyncStateService.preview`
- `backend/sync/library.py:WorkoutLibrarySyncStateService.store_remote_identity`
- `backend/sync/library.py:WorkoutLibrarySyncStateService.summary`
- `tests/test_server_planning.py:test_unparsed_library_export_keeps_identity_and_retries_as_update`
- `tests/test_sync_library.py:test_create_response_keeps_a_local_edit_made_during_upload`
- `tests/test_sync_library.py:test_preview_categories_counts_order_hash_and_fingerprint`
- `tests/test_sync_library.py:test_retry_after_lost_identity_adopts_the_created_remote_workout`
- `tests/test_sync_library.py:test_sync_entry_already_synced_is_idempotent`
- `tests/test_sync_library.py:test_sync_entry_recovers_remote_missing_before_creating`
- `tests/test_sync_library.py:test_update_provider_http_failure_other_than_not_found_keeps_sync_error`
- `tests/test_sync_library.py:test_update_provider_http_not_found_recreates_remote_workout`
- `tests/test_sync_library.py:test_update_response_keeps_a_local_edit_made_during_upload`
- `tests/test_sync_library.py:test_update_upstream_failure_other_than_not_found_keeps_sync_error`
- `tests/test_sync_library.py:test_update_upstream_not_found_recreates_remote_workout`
- `tests/test_workout_library_export.py:test_failed_readback_keeps_identity_in_slot_and_link_together`
- `tests/test_workout_library_export.py:test_finish_failure_rolls_back_slot_and_link_in_one_transaction`
- `tests/test_workout_library_export.py:test_known_entry_is_updated_by_the_link_identity`
- `tests/test_workout_library_export.py:test_recovered_remote_entry_is_adopted_without_creating`

Slot/link atomicity is local; these checks do not provide remote compare-and-swap or rollback of a completed provider write.

### Requirement: TL10 Exact explicit sync selection and complete repair manifests
The system SHALL bind explicit plan pushes to concrete local IDs/current hashes, resolve created/all-pending selections on the server, and require a complete future-period manifest for repair rather than widening a partial model selection.

#### Scenario: Selected, created or all-pending push
- **WHEN** a named plan sync selects existing units, this turn's successfully created units or all pending units
- **THEN** selected entries require exact current IDs/hashes, created resolves only successful additions from this turn, and all-pending freezes the server-resolved concrete selection; later additions do not expand it.

#### Scenario: Complete repair request
- **WHEN** an explicit repair requests a future period with current revision and no entries
- **THEN** the server includes active, already-synced and superseded inactive units in that period, validates the complete current manifest, and queues bounded provider jobs; an explicit incomplete selection conflicts.

#### Scenario: Failed prerequisite or stale manifest
- **WHEN** local creation failed, current hashes/revision changed or approval no longer matches
- **THEN** no dependent push is queued and the caller must repair/reread the actual local state rather than sync partially created data.

#### Scenario: Conflict recovery and job retry
- **WHEN** a failed/partial sync job is retried, or an explicit conflict choice names a competition (a planned unit has no conflict state to resolve any more)
- **THEN** the original job is retried with its original provider and required read/push authority, or the recorded competition strategy is applied locally; a mismatched provider or remote-write declaration is rejected.

#### Scenario: Repair manifest errors
- **WHEN** the repair period is missing, not two ISO dates in order or combined with an all-pending selection
- **THEN** the answer is 400 `request_sync` "Reparatur-Sync braucht einen vollständigen zukünftigen Zeitraum."; a supplied selection that is not exactly the units of the period is 409 `incomplete_repair_selection`; a revision that is not the current integer revision, or a manifest that changed, is 409 `planning_revision_conflict`.

#### Scenario: Selection errors
- **WHEN** created units are named before they are stored, no changed unit is known or the selection is not exactly the authorized set
- **THEN** the answers are 409 `plan_commit_required`, 409 `plan_changes_required` and 403 `intent_scope_denied`.

Detailed contract: the repair manifest is every planned unit of the period, hidden ones included, ordered by id, and only active ones pass the workout validation; a selection entry needs `library_workout_id` (UUID) and `expected_payload_hash` (64 lower-case hex characters), a malformed or repeated entry is 400, and an explicit selection has at most 100 entries (a turn's units at most 366 plus 20 leftovers, an all-pending selection 5000).

Evidence:
- `backend/coach/proposal_creation.py:_approved_plan_sync_arguments`
- `backend/coach/sync_tools.py:CoachSyncToolService._resolve_conflict`
- `backend/coach/tool_preparation.py:CoachStructuredToolPreparationService._prepare_plan_sync`
- `backend/sync/plan_commands.py:PlanPushCommandService.enqueue`
- `backend/sync/plan_repair.py:PlanRepairManifestService`
- `backend/sync/plan_selection.py:StructuredPlanSyncService`
- `tests/test_sync_plan_repair.py`
- `tests/test_sync_plan_selection.py`
- `tests/test_coach_sync_tools.py:test_plan_repair_checks_object_scopes_before_mutation`
- `tests/test_coach_sync_tools.py:test_retry_requires_matching_provider_and_remote_write_intent`
- `tests/test_coach_tool_coverage.py:test_all_pending_sync_binds_the_units_pending_at_the_request`
- `tests/test_coach_tool_preparation.py:test_all_pending_captures_a_concrete_manifest_for_approval`
- `tests/test_coach_tool_preparation.py:test_created_plan_sync_projects_exact_ids_and_scopes`
- `tests/test_coach_tool_preparation.py:test_selected_sync_requires_entries_unless_repairing`

Intervals planned-calendar execution and recovery are specified in TL11-TL15; no real remote sync was exercised here. The local-choice tool's catalog/write-gate mismatch is recorded separately rather than promised as universally available through chat.

### Requirement: TL11 Planned-calendar upsert identity and in-flight local changes
The system SHALL use stable Intervals planned-event identity for explicit dated-unit pushes, validate the returned event before marking the unchanged local unit synced, and preserve newer local content and recoverable remote identity when the upload races with local changes or result validation fails.

#### Scenario: Only indoor rides go to the calendar
- **WHEN** a planned unit is selected for the Intervals.icu calendar
- **THEN** only an indoor or virtual ride is written; a run, strength or outdoor ride unit is skipped without a remote write, and its earlier event, if any, stays untouched (#2419). Runs and strength reach the watch through the direct Garmin push, outdoor rides the head unit through the Wahoo plan push.

#### Scenario: Create and later update
- **WHEN** an explicit normal push exports an active planned unit and a later push retries or updates it
- **THEN** the initial external_id is derived from its local UUID as `intervals-coach-<local_id>`; a stored remote external_id is reused and a known remote_event_id is included on subsequent upserts.

#### Scenario: Event of another category
- **WHEN** the stored event of an indoor or virtual ride has another category than the ride gets now (an event sent before the category was recorded counts as WORKOUT)
- **THEN** the unit is pending again, and its push deletes that eligible event and creates the event anew under the same external_id; the returned or sent category is stored with the event ids. Since #2419 no strength, run or outdoor ride unit is selected for such a push, so an event they already hold (a strength unit once sent as a WORKOUT event, before strength became a note) stays untouched.

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

#### Scenario: Unit dated before today with an event
- **WHEN** an active unit with a stored `remote_event_id` is dated before today
- **THEN** the push fails with 409 `intervals_workout_identity_conflict` "Die zugeordnete Einheit liegt vor heute und wird nicht überschrieben." without reading the event; a unit before today without an event is not refused by this rule (the export date rule of TL8 still applies).

#### Scenario: Normal push errors
- **WHEN** the id is no UUID, the row is missing or corrupt, the key is missing or another push of the unit runs
- **THEN** the answers are 400, 404 "Lokale Planung nicht gefunden.", 500, 503 `not_configured` (only when a remote call is needed) and 409 `planned_unit_sync_running`; a reply without an event id is 502 "Intervals.icu hat keine geplante Einheit zurückgegeben.".

Detailed contract: the stored `remote_event_id` is sent as `id` (at most 120 characters) and the stored external id replaces the generated one; the readback compares the reply with the description that was sent (a capped run carries its resolved bpm range); an inactive unit without `remote_event_id` is marked synced without a key; the removal conflicts are 409 `intervals_workout_identity_conflict` "Die zugeordnete Einheit ist keine freie zukünftige Planung mehr." and 409 `planning_revision_conflict` "Die Planung wurde während der Synchronisation geändert.".

Evidence:
- `backend/providers/intervals_workouts.py:intervals_external_id`
- `backend/sync/planned_calendar.py:planned_unit_sync_guard`
- `backend/sync/planned_calendar.py:PlannedCalendarSyncService._event_payload`
- `backend/sync/planned_calendar.py:PlannedCalendarSyncService._remote_event`
- `backend/sync/planned_calendar.py:PlannedCalendarSyncService._require_open_linked_event`
- `backend/sync/reconcile.py:PlannedUnitSyncStateWriter._state_values`
- `tests/test_planning_push_state.py:test_only_indoor_and_virtual_rides_wait_for_intervals`
- `tests/test_sync_planned_calendar.py:test_a_workout_event_without_a_recorded_category_is_updated_in_place`
- `tests/test_sync_planned_calendar.py:test_archive_during_upload_keeps_identity_until_remote_cleanup`
- `tests/test_sync_planned_calendar.py:test_concurrent_edit_survives_upload_validation_error`
- `tests/test_sync_planned_calendar.py:test_create_and_retry_use_stable_external_identity`
- `tests/test_sync_planned_calendar.py:test_delete_during_upload_becomes_remote_cleanup_tombstone`
- `tests/test_sync_planned_calendar.py:test_edit_during_upload_keeps_new_payload_pending_and_retries_it`
- `tests/test_sync_planned_calendar.py:test_malformed_provider_result_is_rejected`
- `tests/test_sync_planned_calendar.py:test_missing_api_key_blocks_upsert_before_client_creation`
- `tests/test_sync_planned_calendar.py:test_readback_validation_failure_persists_identity_and_sync_error`
- `tests/test_sync_planned_calendar.py:test_repair_and_normal_sync_share_per_id_guard`
- `tests/test_sync_planned_calendar.py:test_reschedule_during_upload_stays_pending_and_retries_new_date`
- `tests/test_sync_planned_calendar.py:test_strength_sent_as_a_workout_event_is_replaced_by_a_note`
- `tests/test_sync_planned_calendar.py:test_unit_before_today_with_an_event_is_not_overwritten`
- `tests/test_sync_planned_calendar.py:test_unit_before_today_without_an_event_can_still_be_created`

Normal push validates the returned event through the export port; TL14 separately requires repair collection readback.

### Requirement: TL12 Guarded explicit removal of a linked planned event
The system SHALL reconcile an archived or locally deleted planned unit through the explicit sync path, checking the stored remote event ID and its current eligibility before deletion and rechecking local content before recording removal.

#### Scenario: Remove a known eligible event
- **WHEN** normal explicit sync removes an inactive unit with a remote_event_id and reading that ID returns the same ID as an unpaired planned event (a WORKOUT, or this app's strength NOTE) dated today or later
- **THEN** the service rechecks the local payload, deletes that concrete remote event and marks local removal synced only after another local-payload check.

#### Scenario: No remote ID or already absent
- **WHEN** an inactive unit has no remote event ID, or reading its linked event reports HTTP 404 directly or through the wrapped HTTP error cause
- **THEN** removal is treated as already satisfied without a remote delete and local removal is recorded subject to the final local-payload check.

#### Scenario: Linked event is no longer eligible
- **WHEN** the remote read is not an event object with the expected ID, is not a planned event, is past, or is paired with an activity or event
- **THEN** normal removal fails with an identity conflict and issues no delete.

#### Scenario: Local payload changes after the remote read
- **WHEN** the unit changes before the pre-delete payload recheck
- **THEN** deletion is blocked with a planning revision conflict; a change detected after a remote delete also blocks the final local success record without undoing that remote delete.

Evidence:
- `backend/providers/intervals_workouts.py:intervals_event_is_planned`
- `backend/sync/intervals_workout_export.py:IntervalsWorkoutExport.is_unpaired_future_planned`
- `backend/sync/planned_calendar.py:PlannedCalendarSyncService._delete_remote_event`
- `backend/sync/planned_calendar.py:PlannedCalendarSyncService._mark_removed`
- `backend/sync/planned_calendar.py:PlannedCalendarSyncService._remove_event`
- `tests/test_sync_planned_calendar.py:test_archived_or_deleted_without_remote_id_only_marks_local_sync`
- `tests/test_sync_planned_calendar.py:test_delete_404_is_already_removed`
- `tests/test_sync_planned_calendar.py:test_delete_identity_conflicts`
- `tests/test_sync_planned_calendar.py:test_delete_success_rechecks_and_persists_removed_state`
- `tests/test_sync_planned_calendar.py:test_delete_treats_http_error_404_cause_as_already_removed`
- `tests/test_sync_planned_calendar.py:test_payload_change_after_remote_read_blocks_delete`

The post-delete concurrent-edit branch is implementation-inspected; these cited tests do not inject an edit after deletion. Normal removal has no final collection readback; repair verification is covered by TL14.

#### Scenario: Hidden units are removed by the next explicit sync
- **WHEN** a unit that is archived or deleted (a replan archives the replaced unit) still holds a remote event ID in an open sync state and is dated today or later
- **THEN** the week sync button of that day's week removes it (at most 20 events, soonest first), and only the linked event is deleted; events without a stored unit are never touched. The week button sends its units and its leftovers in separate `plan_push` jobs, so a leftover that cannot be removed never fails a unit; a selected Coach sync, and a sync bound to the units of one Coach turn (created, changed or replacement units), add them as further entries of its own job while the job has room, so replacing a unit and sending its successor also removes the replaced unit's event, which Intervals.icu would otherwise keep forwarding to Garmin (#2373). The plan selection accepts beyond the turn's units only such leftovers of hidden units.

#### Scenario: Leftovers no pending unit carries
- **WHEN** hidden units hold an Intervals.icu event but no unit of that week waits for that provider
- **THEN** the week still shows "Woche synchronisieren" and its click removes them; Garmin and Wahoo leftovers use the same button.

Evidence: `backend/planning/intervals_orphans.py`, `backend/planning/leftovers.py:MAX_CLEANUP`, `backend/planning/push_state.py:attach_push_state`, `backend/planning/push_state.py:_carry_unclaimed_cleanup`, `backend/coach/proposal_creation.py:_with_intervals_leftovers`, `public/plan-views.js:plannedLeftoversByWeek`, `public/plan-views.js:plannedWeekSyncJobs`, `public/plan-views.js:runPlannedWeekSync`; `tests/test_intervals_orphans.py`, `tests/test_planning_push_state.py:test_leftovers_ride_on_a_unit_even_when_no_provider_waits`, `tests/test_sync_planned_calendar.py:test_removing_a_replaced_unit_leaves_foreign_events_alone`.

### Requirement: TL13 Exact repair ownership and bounded duplicate cleanup
The system SHALL repair selected planned units dated today or later using current local hashes and concrete remote identities, refuse identified unsafe or ambiguous candidates, and limit cleanup to identity-checked related events in the repair window.

#### Scenario: Invalid local repair target
- **WHEN** the unit is missing, its expected payload hash is stale, its payload/date is invalid, or its date is before today
- **THEN** repair fails before performing a remote write.

#### Scenario: Identify related events and refuse foreign ownership
- **WHEN** the repair window contains an event with a concrete ID matching the unit's stored remote ID or a generated/stored external identity
- **THEN** it is related only if it is an unpaired planned event (WORKOUT or this app's strength NOTE) dated today or later and neither its ID nor external identity belongs to another local planned unit; an identified event failing those checks causes an identity conflict.

#### Scenario: Known ID is absent from the window
- **WHEN** the stored remote ID is not among the related events read from the repair window
- **THEN** repair reads that ID directly: a 404 permits reconciliation as absent, another read failure propagates, and an event still present outside the window causes an identity conflict rather than being moved or deleted automatically.

#### Scenario: Ambiguous namesake during active repair
- **WHEN** an active unit has an otherwise unassigned planned event on the same day with the same name after case/edge-space normalization but without a matching identity
- **THEN** repair refuses automatic adoption, copy creation and deletion with an ambiguity conflict; unrelated events belonging to other local units remain outside cleanup, and removal does not adopt or delete an unlinked namesake.

#### Scenario: Create or keep one identity and remove only concrete related duplicates
- **WHEN** an active repair has passed the identity and ambiguity checks
- **THEN** it creates with the stable generated external identity if no related event remains, or prefers the stored remote ID as keeper when present and otherwise adopts a related event; an existing keeper ID/external identity is reused for upsert, and only other concrete related IDs are deleted after local-hash rechecks. An inactive repair performs no upsert and removes its concrete related IDs; an empty ID is never a delete target.

#### Scenario: Repair window and failure reasons
- **WHEN** a repair reads the calendar
- **THEN** it reads from today to the later of the latest selected unit date and today plus 35 days, without a category filter; a failure carries the reason `planning_revision_conflict` (409: stale or missing hash, unreadable payload or a change during the repair), `invalid_plan` (400: unit before today, "Reparatur-Sync ist nur für zukünftige geplante Einheiten erlaubt."), `intervals_workout_identity_conflict` (409: an identified event is paired, past, foreign or outside the window), `intervals_workout_identity_ambiguous` (409: same name on the same day without identity) or `intervals_workout_verification_failed` (502: no single event returned, date or name not confirmed, events still present after removal or the calendar does not confirm one event).

Evidence:
- `backend/sync/planned_calendar.py:PlannedCalendarRepairService._check_remote_identity`
- `backend/sync/planned_calendar.py:PlannedCalendarRepairService._context`
- `backend/sync/planned_calendar.py:PlannedCalendarRepairService._delete_duplicates`
- `backend/sync/planned_calendar.py:PlannedCalendarRepairService._related_event`
- `backend/sync/planned_calendar.py:PlannedCalendarRepairService.repair_entry`
- `tests/test_sync_planned_calendar.py:test_delete_duplicates_never_deletes_an_empty_identity`
- `tests/test_sync_planned_calendar.py:test_repair_create_update_and_remove`
- `tests/test_sync_planned_calendar.py:test_repair_deletes_only_identity_checked_duplicates`
- `tests/test_sync_planned_calendar.py:test_repair_rejects_corrupt_stored_payload_as_conflict`
- `tests/test_sync_planned_calendar.py:test_repair_rejects_invalid_paired_foreign_and_ambiguous_events`

The known-ID-outside-window and local-past-date branches are implementation-inspected rather than demonstrated by those cited tests.

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

#### Scenario: State between upsert and verification
- **WHEN** the upsert returned one event with an id
- **THEN** the unit is stored in state `syncing` with the returned identity before date, name and content are checked; a payload changed meanwhile is stored as `sync_error` "Planung während der Reparatur geändert." with that identity.

Evidence:
- `backend/sync/planned_calendar.py:PlannedCalendarRepairBatch.verify`
- `backend/sync/planned_calendar.py:PlannedCalendarRepairService._completion`
- `backend/sync/planned_calendar.py:PlannedCalendarRepairService._recheck`
- `backend/sync/planned_calendar.py:PlannedCalendarRepairService._upsert`
- `tests/test_sync_planned_calendar.py:test_repair_batch_shares_two_reads_and_deferred_verification`
- `tests/test_sync_planned_calendar.py:test_repair_batch_verify_failure_and_collection_error_are_propagated`
- `tests/test_sync_planned_calendar.py:test_repair_hash_conflict_before_final_persist_preserves_written_remote_id`
- `tests/test_sync_planned_calendar.py:test_repair_hash_conflict_before_write`
- `tests/test_sync_planned_calendar.py:test_repair_preserves_requested_external_id_from_provider_response`
- `tests/test_sync_planned_calendar.py:test_repair_readback_failure_keeps_remote_identity`

These local checks and collection snapshots are not remote compare-and-swap: an external edit can race with a write, and local failure cannot roll back an already completed remote upsert/delete. The cited tests exercise representative failures; not every final-read mismatch branch is separately executed.

### Requirement: TL15 Selected execution reports mixed outcomes and failed-object retry scope
The system SHALL execute the exact selected sync entries with per-entry outcomes, defer repair success until shared collection verification, and report failures without implying an atomic transaction across remote operations.

#### Scenario: Route the frozen selection
- **WHEN** an Intervals plan_push job executes
- **THEN** its concrete entries and repair flag are passed to selected synchronization; each entry is checked for existence and current payload hash, and planned units route to normal push or repair without widening the selection.

#### Scenario: Shared repair snapshots
- **WHEN** a selected repair batch executes
- **THEN** it shares its initial remote window snapshot and final collection read across deferred completions; final-read failures apply to each deferred completion instead of accepting its provisional result. With no background Intervals.icu ingest left, the batch takes no shared Intervals.icu sync lock; the per-unit guard still rejects overlapping pushes.

#### Scenario: Verification overrides a provisional result
- **WHEN** an entry's repair operation or deferred verification fails
- **THEN** selected execution records its sync_error, returns a redacted bounded per-entry error, and changes a provisional calendar_synced result to error with calendar_synced false when final verification fails.

#### Scenario: Mixed success and failure
- **WHEN** the selected entries finish with successes and errors/conflicts
- **THEN** the aggregate status is partial, or error if every entry failed, with failed_object_ids and retry_scope directing selection of only failed objects; an all-success result is ok with no retry scope. Completed remote effects for other entries remain in place even if a later entry fails.

#### Scenario: Entry results
- **WHEN** an entry is processed
- **THEN** its result has `library_workout_id` and the status `synced`, `already_synced`, `skipped`, `conflict` or `error`: a missing row is `conflict` "Einheit nicht gefunden", a changed hash `conflict` "Seit der Vorschau geändert", a unit Intervals.icu takes no part in (anything but an indoor or virtual ride) is `skipped` with "Geht nicht an Intervals.icu: nur Indoor-Radeinheiten", and a failure is `error` with a redacted text of at most 500 characters; `calendar_synced` tells whether an event was written.

#### Scenario: Aggregate and template entries
- **WHEN** all entries are done
- **THEN** the result is `{ok, status, results, failed_object_ids, retry_scope}` where `conflict` and `error` entries count as failed and `skipped` ones do not; an entry naming a synced template is `already_synced` (a dated legacy row without an event is put on the calendar), and any other template is exported first and reported as `conflict` when it was edited during the export. Without the Intervals.icu key the whole call answers 503 `not_configured`; a failed normal push leaves the unit's state as it was unless its readback failed, while a failed repair stores `sync_error`.

Evidence:
- `backend/sync/executor.py:IntervalsSyncJobOwner.execute_specific`
- `backend/sync/planned_calendar.py:PlannedCalendarRepairBatch.snapshot`
- `backend/sync/planned_calendar.py:PlannedCalendarRepairBatch.verify`
- `backend/sync/selected.py:SelectedWorkoutSyncService._sync_entry`
- `backend/sync/selected.py:SelectedWorkoutSyncService._verify_repair`
- `backend/sync/selected.py:SelectedWorkoutSyncService.sync`
- `tests/test_sync_executor.py:test_dispatches_specific_intervals_jobs_and_preserves_plan_repair`
- `tests/test_sync_planned_calendar.py:test_repair_batch_shares_two_reads_and_deferred_verification`
- `tests/test_sync_selected.py:test_hash_and_not_found_conflicts_are_aggregated`
- `tests/test_sync_selected.py:test_partial_and_all_failure_aggregation`
- `tests/test_sync_selected.py:test_planned_normal_and_repair_paths`
- `tests/test_sync_selected.py:test_repair_errors_are_recorded_and_verification_failure_overrides_result`

Retry scope here is the selected operation's failed-object guidance; the separately authorized durable job retry in TL10 retains the original job selection. Evidence uses inspected implementation and synthetic/mocked tests, not a live provider or a distributed rollback guarantee.

### Requirement: TL16 Provider-neutral planning record fields
Local planning records (planned units, workout-library entries, competitions, staged plan workouts and adaptive previews) SHALL store and return their local start as `starts_at_local` and their planned duration in seconds as `planned_duration_s`, in the HTTP API, Coach tools and Coach context alike. Only the Intervals.icu adapter SHALL map these fields to the Intervals.icu event and workout fields `start_date_local` and `moving_time`, so payloads sent to Intervals.icu stay unchanged.

#### Scenario: Provider response read back
- **WHEN** the adapter reads an Intervals.icu event or library workout returned for an explicit export
- **THEN** it names the start and duration `starts_at_local` and `planned_duration_s` before the readback validation.

#### Scenario: Explicit export to Intervals.icu
- **WHEN** an athlete explicitly synchronizes planned units, library workouts or competitions
- **THEN** the Intervals.icu payload carries `start_date_local` and `moving_time` exactly as before.

#### Scenario: Coach save of a competition
- **WHEN** an athlete-started Coach turn saves a competition with `starts_at_local` and `planned_duration_s`
- **THEN** the competition is stored with those values; an explicit null clears the planned duration and an absent one keeps it.

Evidence: `backend/providers/intervals_workouts.py::planning_fields_from_intervals`, `backend/providers/intervals_workouts.py::intervals_fields_from_planning`, `backend/providers/intervals_workouts.py::intervals_event_payload`; `backend/sync/intervals_workout_export.py::IntervalsWorkoutExport`; `backend/sync/competitions.py::CompetitionSyncService.sync`; `backend/sync/reconcile.py`. Tests: `tests/test_workout_export_parity.py::test_export_port_payload_matches_golden_for_every_payload_case`; `tests/test_workout_export_intervals.py::test_library_workouts_cross_the_adapter_with_planning_field_names`; `tests/test_workout_export_intervals.py::test_library_readback_checks_the_remote_duration_under_its_wire_name`; `tests/test_planning_competitions.py::test_event_payload_fallbacks_limits_and_input_immutability`; `tests/test_sync_adaptive.py::test_sync_sends_the_illness_start_under_the_intervals_wire_name`; `tests/test_server_coach.py`.

### Requirement: Provider-neutral planning metrics

Local planning records SHALL use provider-neutral names for planned load, intensity and frozen target FTP. The Intervals.icu adapter SHALL translate its wire fields at the provider boundary.

#### Scenario: Local planned load and intensity
- **WHEN** a local workout or library entry stores planned load or intensity
- **THEN** it uses the provider-neutral names `planned_load` and `planned_intensity`.

#### Scenario: Workout is exported
- **WHEN** a local workout is explicitly synchronized to Intervals.icu
- **THEN** the adapter emits the corresponding provider fields with unchanged values.

#### Scenario: Frozen target basis
- **WHEN** an activity detail freezes a local workout target
- **THEN** the stored FTP basis uses a provider-neutral name and retains its value.

Evidence: `backend/planning/library.py`, `backend/planning/target_snapshot.py`, `backend/providers/intervals_workouts.py`; `tests/test_workout_export_intervals.py`, `tests/test_target_snapshot_summaries.py`.

### Requirement: Session focus of planned units and templates
Planned units and library templates SHALL carry an optional local session focus, validated per sport, that no provider export writes. A Coach write that creates, moves or changes a strength unit without a strength structure, focus and strength intensity SHALL be blocked by the plan check `strength_incomplete`, which the Coach cannot accept away.

#### Scenario: Valid focus
- **WHEN** a unit or template sets a focus allowed for its sport (run and ride: recovery, easy, endurance, long, tempo, threshold, vo2max, anaerobic, race, test; ride also sweet_spot; strength: legs, upper, full_body, core, plyometrics, mobility with an optional light, moderate or heavy strength intensity)
- **THEN** it is stored in the unit payload, shown as a chip, editable per unit and recorded in change history and backups.

#### Scenario: Focus control in the calendar
- **WHEN** the athlete opens a local planned run, ride or strength unit
- **THEN** the card offers "Art der Einheit" (and "Intensität" for strength) and saves a change at once with `POST /api/planned-units/{id}/focus {session_focus, strength_intensity}`, showing "Gespeichert" and the new chip, or restoring the previous selection with the error; a derived value is prefixed "≈" and a button "≈ <label> übernehmen" sets it

#### Scenario: Invalid focus
- **WHEN** a focus or strength intensity does not exist for the unit's sport
- **THEN** the write fails with `invalid_session_focus`; changing a unit's sport drops its previous focus unless the request sets one.

#### Scenario: Unit without focus
- **WHEN** a unit carries no focus
- **THEN** a derived focus is taken from parsed steps and computed intensity, then from keywords, otherwise it is unknown; a derived focus is labelled `derived` and is never shown as set.

#### Scenario: Export
- **WHEN** a unit with a focus is exported to Intervals.icu
- **THEN** the event payload is unchanged; the focus stays local (a run unit's `hr_cap` is the exception, see the heart-rate cap requirement).

#### Scenario: Required focus
- **WHEN** a Coach write creates, moves or changes a run or ride unit without a focus
- **THEN** the plan check `focus_missing` blocks it like `strength_incomplete`, cannot be accepted away, and never blocks an unrelated write because of an untouched older unit; sports without a focus vocabulary are exempt.

#### Scenario: One-time backfill of future units
- **WHEN** the application starts and the versioned focus backfill has not run
- **THEN** every future, non-archived unit without a focus (and every strength unit without an intensity) receives the derived value only if its sources agree: steps and text do not contradict, exactly one keyword group matches, and the strength intensity comes from the structure or from exactly one named level; contested units, past units and sports without a focus vocabulary stay untouched, no exercise structure is invented, the sync state is kept and no provider is written.
- **AND** the changes are recorded in the change history and in the step's state (counts and change references only, reported by diagnostics); a second run changes nothing.

#### Scenario: Derivation from steps
- **WHEN** a run or ride unit has no set focus and its steps resolve
- **THEN** at least 300 s in zone 4 give `threshold`, in zone 5 `vo2max` and in a higher zone `anaerobic`; else at least 1200 s in zone 3 give `tempo`; else a duration of at least 5400 s gives `long`; else an intensity factor below 0.75 gives `easy`.

#### Scenario: Derivation from keywords
- **WHEN** no step focus exists
- **THEN** the first matching keyword group of name and description decides; for strength a focus word in the name wins, legs plus upper give `full_body`, and negated mentions ("ohne Beine", "Beine schonen", "no legs") do not count.

#### Scenario: Backfill bound and retry
- **WHEN** the backfill runs
- **THEN** it reads at most 1000 future units per pass and keeps its counts, a `truncated` flag and its change references in the stored state `session_focus_backfill_state`; a unit that a calendar check refuses counts as `skipped`, the pass is stored as `incomplete` and the step runs again on the next pass.

Evidence: `backend/planning/session_focus.py`, `backend/sync/session_focus_backfill.py`, `public/plan-views.js:plannedFocusForm`, `public/plan-views.js:focusChipSpec`; `tests/test_session_focus.py`, `tests/test_session_focus_backfill.py`, `tests/test_session_focus_backfill.py:test_a_refused_unit_is_skipped_and_retried_on_the_next_pass`, `e2e/session-focus.spec.js:@responsive session focus chip and select on a planned unit`.

### Requirement: Heart-rate caps of easy run units
A run unit whose focus has a cap in `HR_CAP_PERCENT` (`backend/activities/hr_cap.py`) SHALL carry a local `hr_cap` of percentages only (cap, exported lower bound, source). Bpm SHALL be resolved from the threshold HR on the unit's date wherever it is read, checked or exported, and never stored. A Coach write with a wrong cap SHALL be blocked by the plan check `hr_cap_invalid`; planned units are never rewritten.

#### Scenario: Threshold source
- **WHEN** a bpm is needed
- **THEN** it is resolved from the run threshold HR in effect on the unit's date (local zones, then the dated Garmin watch zone set, then the other resolved thresholds); when none is known only the percent is shown, nothing is estimated, and the plan check does not depend on it.

#### Scenario: Missing, too high or mismatched cap
- **WHEN** the Coach writes a capped run unit without `hr_cap`, with a percent above the effective cap, or with a lower bound or source that does not belong to it
- **THEN** the write fails with `hr_cap_invalid` naming the correct percentages and source, and nothing is saved.

#### Scenario: Threshold change
- **WHEN** the watch's threshold HR changes between two dated Garmin zone sets
- **THEN** the stored percentages stay, the card, the Coach context, the analysis and the exports resolve the new bpm, and no unit is edited.

#### Scenario: Measured first threshold
- **WHEN** the athlete enters a measured first-threshold heart rate in bpm (profile form or API, never by the Coach)
- **THEN** it is stored as percent of the run threshold HR in effect on the measurement date (`first_threshold_pct`), the easy and long cap becomes that percent minus a fixed margin and the recovery cap the lower of its default and the easy cap minus a fixed gap (constants in `backend/activities/hr_cap.py`), the cap source is `measured`, and a cap with another source than the current one is rejected like a wrong value.

#### Scenario: Adopted first threshold estimate
- **WHEN** the athlete adopts the first threshold estimate from chest-strap RR intervals (`POST /api/profile/first-threshold/adopt`, never by the Coach)
- **THEN** it is stored as `first_threshold_pct` with the origin `estimated` (`first_threshold_origin`) through the profile save path with change receipt and undo, the caps follow it like a measured value, the cap source is `estimated` (label `geschätzt`), a stored measured value is replaced only when the request says so, and a later manual entry sets the origin back to `measured`.

#### Scenario: Export to Wahoo
- **WHEN** a run unit with a cap becomes a Wahoo plan
- **THEN** every step with a heart-rate target, warm-up and cool-down included, is one wide range from the lower bound to the cap in percent of the threshold HR (`% LTHR`), resolved by the plan header's `threshold_hr`, which Pacecraft supplies from the current thresholds; a moved threshold changes the exported plan, so the existing push state shows the unit as changed.

#### Scenario: Export to Garmin
- **WHEN** a run unit with a cap is pushed to Garmin
- **THEN** every heart-rate step, warm-up and cool-down included, is written as one wide `low-high` bpm range resolved at push time (a Garmin workout step cannot hold a percent of the lactate threshold HR); steps with a pace or power target keep theirs; the stored text stays as written; without a known threshold HR the push is refused before any write.

#### Scenario: Card and analysis
- **WHEN** a unit has a cap
- **THEN** its card shows the percent first, then the currently resolved bpm and the source (the form "≤ <percent> % LSHF · <bpm> bpm · <source>"), and the post-session analysis judges the run's heart rate against the stored cap resolved for the unit's date (`planned_targets.heart_rate_cap`: mean, time above the cap, verdict within_target, upper_edge or above_cap), not against the zones.

Evidence: `backend/activities/hr_cap.py`, `backend/activities/hr_cap_export.py:capped_description`, `backend/planning/run_hr_cap.py`, `backend/planning/plan_checks.py:hr_cap_invalid`, `backend/planning/run_lthr.py:RunLthr.resync`, `backend/planning/push_state.py:run_document_digest`, `backend/planning/push_state.py:attach_push_state`, `backend/athlete/profile.py:ProfileService`, `backend/performance/planned_targets.py:heart_rate_cap_execution`, `public/plan-views.js:hrCapChipSpec`; `tests/test_run_hr_cap.py`, `tests/test_hr_cap_export.py`, `tests/plan-views-hr-cap.test.cjs`.

### Requirement: Structured strength units
Strength units and templates SHALL carry an optional local `strength_structure` (at most 12 exercises with name, sets, reps, optional kg, %1RM, RPE or RIR (one relative load), rest, up to 5 warm-up sets with reps and optional kg, a short note and an optional Garmin catalogue exercise) in the payload, validated server-side with `invalid_strength_structure`; free text stays the fallback for units that have none.

#### Scenario: Structure given
- **WHEN** a strength unit or template is written with a structure
- **THEN** its description is generated from it, a free-text description edit without a structure drops it, and `strength_intensity` and leg involvement are derived and labelled `derived` (heavy from 80 % 1RM, RPE 8 or 2 RIR) unless a focus or intensity is set.

#### Scenario: Garmin catalogue exercise
- **WHEN** an exercise names a Garmin catalogue exercise, or the athlete picks one of the suggested chips of an exercise without a match
- **THEN** the name is checked against the catalogue and its category and exercise pair is derived on write, never taken from the request; an unknown name is rejected with suggestions; a pick through `POST /api/planned-units/<id>/garmin-exercise` needs the current payload hash, is remembered for the same exercise name in other units and does not change the Intervals.icu sync state.

#### Scenario: Export
- **WHEN** a structured unit is exported to Intervals.icu on an explicit sync
- **THEN** only the readable description is sent, as a note event, and nothing implicit is written.

#### Scenario: Limits and derived intensity
- **WHEN** a structure is validated
- **THEN** it is rejected with `invalid_strength_structure` outside 12 exercises, 1 to 10 sets, 1 to 100 reps, 0 to 1000 kg, 1 to 150 % 1RM, RPE 1 to 10, whole RIR 0 to 10, whole rest 0 to 600 seconds, 1 to 5 warm-up sets or with more than one relative load per exercise; names are cut to 80 characters and notes to 100; the derived intensity is that of the hardest exercise, `heavy` from 80 % 1RM, RPE 8 or at most 2 RIR, `moderate` from 65 % 1RM, RPE 6 or at most 4 RIR, else `light`.

Detailed contract: a structure renders one line per exercise as "<Name>: [Aufwärmen <n>x<r>[ @ <kg> kg], dann ]<Sätze>x<Wdh.>[ @ <Last>][, <s> s Pause][ – <Notiz>]".

Evidence: `backend/planning/strength_structure.py`, `backend/planning/session_focus.py`, `backend/planning/planned_unit_service.py:PlannedUnitService.assign_garmin_exercise`, `backend/http_api/planned_unit_focus_post.py`, `backend/planning/push_state.py:unmapped_exercises`, `backend/planning/plan_checks.py:strength_incomplete`, `backend/planning/plan_checks.py:focus_missing`; `tests/test_strength_structure.py`, `tests/test_planning_push_state.py`, `tests/test_plan_guard_service.py`.

### Requirement: Wahoo sync state of library workouts
The system SHALL show, for each library workout already delivered to Wahoo as a plan, whether Wahoo holds its current content (`synced` or `changed`), by comparing the plan the workout would be sent as now with the baseline stored by the last export. The read SHALL write nothing and contact no provider.

#### Scenario: Meaning of the state
- **WHEN** the workout text or a threshold behind a relative step changed since the last export, or the workout no longer maps to a Wahoo plan
- **THEN** the state is `changed`, otherwise `synced`; workouts never sent get no state and none is returned while Wahoo is not connected.

#### Scenario: Library page carries the state
- **WHEN** the athlete browses `/api/library` with Wahoo connected
- **THEN** each exported workout carries `wahoo_state` with `state` and the `payload_hash` of its stored text, and the PWA labels it "Wahoo: synchron" or "Wahoo: geändert".

#### Scenario: Explicit resend
- **WHEN** the workout is `changed` and the athlete taps the resend button
- **THEN** a `plan_push` job for Wahoo is started with that payload hash, so a workout edited meanwhile is refused instead of pushed; nothing is sent implicitly.

Evidence: `backend/sync/wahoo_library_state.py:WahooLibraryState.states`, `backend/http_api/library_page.py:LibraryPageService.page`, `backend/sync/wahoo_plan_push.py`, `public/plan-views.js:libraryWahooRow`; `tests/test_wahoo_library_state.py`.

### Requirement: Planned units come from library templates
A planned unit that a Coach plan tool creates or whose structure it changes SHALL reference an undated training-library template by `template_id` and keep that template's structure for every sport: the strength exercises in order, the endurance steps in order. A variant SHALL differ from its template only in load and intensity. A Coach write that breaks this SHALL be rolled back with a required plan-check finding the model can act on.

#### Scenario: Unit from a template
- **WHEN** the Coach plans a unit with the `template_id` of an existing undated library template and the template's exercises or steps in the same order
- **THEN** the unit is saved with its `template_id`; strength and endurance exports (Garmin, Intervals.icu, Wahoo) use the unit's stored structure, which is the template's.

#### Scenario: Ad-hoc unit
- **WHEN** a Coach plan write creates a unit without `template_id`, or with an id that names no undated library template
- **THEN** the write is rolled back with a `template_missing` finding that tells the model to plan from `list_workout_library`, or, when no template fits, to create one with `manage_training_templates` before planning: in the same turn for a clearly described unit (athlete decision 2026-11-13, #2512), after asking only when the request leaves the unit unclear; no unit is created without a template.

#### Scenario: Scaled variant
- **WHEN** a unit keeps its template's exercises or steps in order and changes only sets, reps, kg, %1RM, RPE, RIR, rest, warm-up, step durations or targets, or the unit duration
- **THEN** the write is saved and the receipt carries a `template_scaled` note naming the unit and its template.

#### Scenario: Different structure
- **WHEN** a unit adds, drops, swaps or reorders an exercise or a step against its template
- **THEN** the write is rolled back with a `template_mismatch` finding; a different selection of exercises is a separate library template.

#### Scenario: Existing unit without a template
- **WHEN** a Coach write moves an older unit that has no `template_id`, sets its session focus or Garmin exercise, archives or deletes it
- **THEN** it passes; a change of its exercises, steps or loads is rolled back with `template_missing` until the unit is switched to a library template. Older units are never cleaned up automatically.

#### Scenario: Adaptive replacement
- **WHEN** an approved adaptive replan eases a planned unit
- **THEN** a run or ride may become the generic easy replacement (marked `source: adaptive`, exempt from the template check); a strength unit only gets the light strength intensity, its exercises, sets and weights stay unchanged.

#### Scenario: Template label
- **WHEN** the athlete expands a planned unit with a `template_id`
- **THEN** one line "Vorlage: <template name>" appears under its title; the calendar tile is unchanged.

Evidence: `backend/planning/plan_checks.py:template_conformance`, `backend/planning/plan_guard_service.py:PlanGuardService.findings`, `backend/planning/library_plan_service.py`, `backend/planning/adaptive.py:adaptive_recovery_replacement`, `public/plan-views.js`; `tests/test_plan_checks.py`, `tests/test_plan_guard_service.py`, `tests/test_coach_tool_coverage.py`, `tests/test_adaptive_replan_apply_service.py`.

### Requirement: Library view

The Bibliothek SHALL list the undated, non-archived workouts grouped by sport in closed groups with their count, 100 per page with "Weitere Bibliothekseinheiten laden", and SHALL offer no create, edit, move or delete control; such changes go through the Coach. Without a workout it SHALL read "Noch keine Einheiten in der Bibliothek. Der Coach legt hier Einheiten ab, wenn du sie planst."

#### Scenario: Paging
- **WHEN** "Weitere Bibliothekseinheiten laden" is pressed
- **THEN** the next page is appended to the list without duplicates by id

Evidence: `public/plan-views.js:renderLibrary`; `public/coach.js:appendHistoryPageButton`; `e2e/ux-polish.spec.js:the calendar has a refresh button and the library rows show a count and a chevron @responsive`.

### Requirement: Stored rows and sync state of templates and planned units
Templates (`workout_library`) and dated units (`planned_units`) SHALL each be one row with a local UUID, a JSON payload and sync columns, and SHALL move through the sync states `local`, `syncing`, `synced`, `sync_error`, `remote_missing` and `conflict`. The table definitions are in docs/schema-reference.md.

#### Scenario: Local write
- **WHEN** the content of a row changes locally
- **THEN** `sync_dirty` is 1, `sync_state` is `local`, `sync_error` is cleared and, for a unit, `sync_conflict` is emptied; a change of only `session_focus`, `strength_intensity` or `template_id` leaves all sync columns as they are, unless it changes the exported heart-rate cap.

#### Scenario: Open states
- **WHEN** the app decides what an explicit push offers
- **THEN** Intervals.icu is offered a unit in `local` or `sync_error`, the sync preview and summary also list `remote_missing` and `conflict` rows, and `syncing` (written before a library export and between a repair's upsert and its verification) is never offered.

#### Scenario: Interrupted push
- **WHEN** the application starts and a row is still `syncing`
- **THEN** it is set to `sync_error` with the text "Die Übertragung wurde unterbrochen." so that it is offered again.

Detailed contract: a unit row adds `sync_conflict`, `baseline_hash`, `plan_id`, `revision`, `tombstone` and `command_id` to the template columns; the remote identities per provider live in `remote_links` with a unique `(provider, entity_kind, remote_id)`.

Evidence:
- `backend/db/planning_store.py:reset_interrupted_syncs`
- `backend/planning/planned_unit_service.py:_is_focus_only`
- `backend/planning/push_state.py:_intervals_pending`
- `backend/sync/library.py:WorkoutLibrarySyncStateService.reset_interrupted`
- `tests/test_plan_push_hash.py:test_startup_offers_a_stranded_syncing_unit_again`
- `tests/test_planned_unit_service.py:test_focus_only_update_keeps_the_sync_state`

### Requirement: Planned-unit sync state persistence
Every push outcome of a planned unit SHALL be written through one state writer that sets payload, sync columns, remote link and planning revision together.

#### Scenario: Unchanged payload
- **WHEN** the stored payload still equals the uploaded one
- **THEN** the state is stored as given, `sync_dirty` is 0 only for `synced` and `remote_missing`, `sync_error` holds the redacted text (at most 1000 characters), `sync_conflict` is emptied, `last_synced_at` and `baseline_hash` are set only on `synced`, and on `synced` the unit takes `workout_doc`, planned load and planned intensity from the reply (a key missing in the reply is removed, the planned duration is kept).

#### Scenario: Payload changed or row gone
- **WHEN** the payload differs from the uploaded one
- **THEN** only `remote_event_id`, `remote_event_external_id`, `external_id` and the event category are merged into the newer payload, the state is `local` instead of `synced`, `sync_dirty` is 1 and a stored conflict is kept; a missing row is inserted again from the uploaded payload as a hidden, deleted unit.

#### Scenario: Removal
- **WHEN** a removal is recorded
- **THEN** `remote_event_id`, `remote_event_external_id` and the event category are dropped, so a later restore creates a new event.

Detailed contract: a run unit linked at Garmin whose workout steps now resolve differently from the steps recorded at its push (for example after a threshold change) is offered to Garmin again; a unit pushed before the step digest was recorded, or whose document cannot be built now, is not flagged, and this never offers anything to Intervals.icu.

Evidence:
- `backend/planning/run_lthr.py:RunLthr.resync`
- `backend/planning/push_state.py:attach_push_state`
- `backend/sync/reconcile.py:PlannedUnitSyncStateWriter._state_values`
- `backend/sync/reconcile.py:PlannedUnitSyncStateWriter._update_row`
- `backend/sync/reconcile.py:PlannedUnitSyncStateWriter.persist`
- `backend/sync/reconcile.py:_drop_remote_event_ids`
- `tests/test_planning_push_state.py:test_a_resync_id_offers_a_pushed_run_to_garmin_only`
- `tests/test_planning_push_state.py:test_the_run_fingerprint_follows_the_cap_the_push_applies`
- `tests/test_sync_planned_calendar.py:test_removed_unit_restored_sends_no_stale_event_id`

### Requirement: Push state of a planned unit and its leftovers
Every planned unit of the calendar read SHALL carry what an explicit push would still send, per provider, and the remote leftovers of deleted or replaced units SHALL be offered for removal. The week sync button of TL12 uses this state.

#### Scenario: Push state of a unit
- **WHEN** the calendar is read
- **THEN** each unit has `payload_hash` (the plan-push hash), `push_pending` per provider (Intervals.icu: an indoor or virtual ride in `local` or `sync_error`, or whose event has another category than it gets now; Garmin: a strength unit with a mappable structure or a run unit with parseable steps whose Garmin fingerprint differs from the pushed one), `push_blocked` (`{garmin: no_structure}` for free-text strength, `{garmin: unmapped}` for an exercise Garmin does not know) and `push_unmapped` (index, name and suggestions of each unmapped exercise).

#### Scenario: Leftover lists
- **WHEN** hidden units still hold an Intervals.icu event or a Garmin workout, or a Wahoo plan link has no library row (named "Gelöschter Wahoo-Plan")
- **THEN** at most 20 per provider (Intervals.icu and Garmin nearest day first) are listed in `push_cleanup` of every upcoming unit that provider waits for; when no unit waits, the lists go on the visible unit nearest to today, and an archived or deleted unit never carries them.

Evidence:
- `backend/planning/leftovers.py:MAX_CLEANUP`
- `backend/planning/push_state.py:_carry_unclaimed_cleanup`
- `backend/planning/push_state.py:attach_push_state`
- `backend/planning/push_state.py:pushable_fingerprint`
- `backend/planning/wahoo_orphans.py:find_wahoo_orphans`
- `tests/test_planning_push_state.py:test_an_unmapped_exercise_offers_no_garmin_push`
- `tests/test_planning_push_state.py:test_each_unit_carries_its_push_hash_and_pending_targets`
- `tests/test_planning_push_state.py:test_free_text_strength_says_why_garmin_is_blocked`
- `tests/test_planning_push_state.py:test_leftovers_ride_on_a_unit_even_when_no_provider_waits`
- `tests/test_planning_push_state.py:test_only_indoor_and_virtual_rides_wait_for_intervals`

### Requirement: Plan-push job request
An explicit plan push SHALL be a durable `plan_push` job whose payload names every unit with the hash the athlete saw.

#### Scenario: Browser request
- **WHEN** the browser posts a `plan_push` job for Intervals.icu, Wahoo or Garmin to `POST /api/sync/jobs` (route contract in docs/api-routes.md)
- **THEN** the payload holds only `entries` (1 to 28 objects with a `library_workout_id` UUID and an `expected_payload_hash` SHA-256, or with `remove: true` instead of the hash for Garmin and Wahoo), `reason` (default "job", cut to 80 characters) and a boolean `repair`, the answer is 202 with the job and one job item per distinct unit, and anything else answers 400 `invalid_job_request`.

#### Scenario: Coach request
- **WHEN** the Coach queues a selection
- **THEN** it is split into jobs of at most 28 entries in order (payload `entries`, `reason` of at most 200 characters, default "coach", and `repair: true` when repairing); an empty selection queues nothing and returns `status: completed` with a message that nothing was synchronized, and a Garmin push without an SDK login answers 409 `garmin_sdk_required`.

Evidence:
- `backend/http_api/sync_commands.py:_plan_push_item_operations`
- `backend/sync/jobs.py:_normalize_plan_push_job`
- `backend/sync/plan_commands.py:PlanPushCommandService.enqueue`
- `tests/test_http_sync_commands.py:test_a_ui_plan_push_stores_one_job_item_per_entry`
- `tests/test_sync_jobs.py:test_plan_push_normalizes_entries_reason_and_repair`
- `tests/test_sync_jobs.py:test_plan_push_rejects_provider_fields_count_uuid_hash_and_booleans`
- `tests/test_sync_plan_commands.py:test_chunk_boundaries_preserve_entry_and_job_id_order`
- `tests/test_sync_plan_commands.py:test_empty_selection_completes_without_enqueuing`
- `tests/test_sync_plan_commands.py:test_garmin_needs_an_sdk_login_before_anything_is_queued`

### Requirement: Calendar read GET /api/plan
The authenticated route `GET /api/plan` SHALL return the planning calendar from one read-only snapshot and SHALL refresh the weather cache only when the query `local=1` is absent. The response keys are listed in docs/api-routes.md.

#### Scenario: Bounds of the response
- **WHEN** the route is read
- **THEN** it holds at most 30 plans (with their constraints), 500 planned units with push state and the name of their template, 1000 activities with feedback, the competitions, 1000 training-relevant calendar events and the daily planning context with up to 365 check-ins; `planning` carries `season`, `latest_replan`, `needs_replan`, `replan_changes`, `illness_pause_pending` and `illness_return_pending`; metric names are provider-neutral.

#### Scenario: Weather refresh
- **WHEN** `local=1` is absent
- **THEN** the weather state is refreshed before and outside the snapshot and a refreshed forecast triggers the adaptive follow-up check; with `local=1` no provider is contacted and no writer is taken.

Evidence:
- `backend/http_api/planning_get.py:PlanningGetRoutes._plan`
- `backend/http_api/public_plan.py:PublicPlanStateService.read`
- `backend/http_api/public_plan.py:PublicPlanStateService._read`
- `backend/planning/season.py:planning_state`
- `tests/test_public_plan.py:test_a_planned_unit_names_its_library_template`
- `tests/test_public_plan.py:test_local_read_keeps_bounds_calendar_scope_and_skips_weather_refresh`
- `tests/test_public_plan.py:test_refreshing_read_keeps_the_weather_write_outside_the_snapshot`

### Requirement: Undo of planned-unit and template changes
Undo of a planned-unit or template change SHALL restore the recorded state without a provider call and SHALL keep the provider links that are needed to remove what a provider already holds.

#### Scenario: Refused undo
- **WHEN** the old time slot or date is taken by a newer unit, or a calendar marker now blocks it
- **THEN** the undo fails with 409 `plan_date_conflict` and nothing changes.

#### Scenario: Undone creation of a unit
- **WHEN** the creation of a unit that was already sent to Intervals.icu or Garmin is undone
- **THEN** a unit with an Intervals.icu event is hidden like a deleted unit, keeping its event id and links, so the next explicit sync removes the event; any other unit is deleted, and its Garmin link is kept so the Garmin workout can still be removed.

#### Scenario: Template links
- **WHEN** a template that was sent to Wahoo is deleted or its creation is undone, and the deleted template is restored
- **THEN** the Wahoo link is kept, so the Wahoo plan can still be removed, and the restored template adopts it again.

Evidence:
- `backend/planning/library_service.py:WorkoutLibraryService.restore_in_transaction`
- `backend/planning/planned_unit_service.py:PlannedUnitService._hide_intervals_linked`
- `backend/planning/planned_unit_service.py:PlannedUnitService._reject_restore_conflict`
- `backend/planning/planned_unit_service.py:PlannedUnitService.restore_in_transaction`
- `tests/test_library_service.py:test_deleting_an_entry_sent_to_wahoo_keeps_the_wahoo_link`
- `tests/test_library_service.py:test_restoring_a_deleted_wahoo_entry_adopts_its_link_again`
- `tests/test_library_service.py:test_undoing_the_creation_of_a_wahoo_entry_keeps_the_wahoo_link`
- `tests/test_planned_unit_service.py:test_time_only_undo_is_rejected_when_the_old_slot_was_taken`
- `tests/test_planned_unit_service.py:test_undoing_a_creation_keeps_the_links_of_a_pushed_workout`

### Requirement: One hard-session rule
The system SHALL judge whether a run or ride unit is hard by one rule: a set focus decides first, then the workout steps, then a planned intensity factor of at least 0.85, and only without readable steps a non-negated Z4-Z7 target or a hard word. Strength SHALL never be hard by this rule; heavy strength has its own rule.

#### Scenario: Set focus decides
- **WHEN** a unit has a set focus
- **THEN** it is hard exactly for `threshold`, `sweet_spot`, `vo2max`, `anaerobic`, `race` and `test`.

#### Scenario: Steps and intensity decide
- **WHEN** a unit has no set focus
- **THEN** hard text in its separate step fields makes it hard; otherwise at least 5 minutes in steps of zone 4 or higher make it hard and fewer settle it as not hard, while an unknown step intensity gives no answer; then a planned intensity factor of at least 0.85 (a value above 1.5 is read as percent) makes it hard.

#### Scenario: Text without readable steps
- **WHEN** no step and no factor answers
- **THEN** a hard word (interval, vo2, threshold or schwelle, sweet spot, race, rennen or wettkampf, test, hiit, tabata, anaerob) or a Z4 to Z7 target in the name or description makes it hard unless a negation such as "kein", "nicht", "ohne" or "unter" precedes it; tempo and sprints are not hard words.

Evidence:
- `backend/planning/session_focus.py:computed_hard`
- `backend/planning/session_focus.py:is_hard`
- `tests/test_session_focus.py:test_generic_words_do_not_derive_a_hard_focus`
- `tests/test_session_focus.py:test_one_hard_rule_table`
- `tests/test_session_focus.py:test_set_focus_decides_hardness_before_text`

### Requirement: Calendar projection of a planned unit
Each planned unit of the calendar read SHALL carry its effective focus with origin, its resolved heart-rate cap, its workout profile and its read-only conflicts.

#### Scenario: Fields
- **WHEN** a unit is projected
- **THEN** it carries `session_focus`, `strength_intensity`, `focus_origin`, `intensity_origin`, `hr_cap_bpm {low, high}` (only with a known run threshold HR on the unit's date) and `workout_profile` (where its steps parse).

#### Scenario: Conflicts
- **WHEN** a unit is active
- **THEN** `conflicts` lists `{code, label}` for the markers that block its day (`no_training` "Kein Training", `no_intensity` "Keine Intensität", `short_only` "Nur kurze Einheiten") and, for a hard unit, `competition_ab` "Hartes Training am Vortag oder am Tag eines A/B-Wettkampfs" on an A or B race day or the day before and `competition_c` "Hartes Training am Tag eines C-Wettkampfs" on a C race day; an archived or deleted unit has none.

Evidence:
- `backend/planning/calendar_read_model.py:_resolved_hr_cap`
- `backend/planning/calendar_read_model.py:_with_session_focus`
- `backend/planning/calendar_read_model.py:planned_unit_conflicts`
- `tests/test_planning_calendar_read_model.py:test_conflict_rules_follow_marker_and_race_priority_table`
