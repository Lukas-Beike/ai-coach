# change-history-and-undo Specification

## Purpose

Describe bounded local audit history and optimistic undo for profile, workout-library, planned-unit, competition, training-plan, zone-configuration, activity-feedback, activity-session, nutrition-entry, nutrition-template, nutrition-product, check-in, equipment, equipment-assignment and equipment-maintenance records, the listed-but-never-undone metric export entries, together with receipt visibility and the narrower complete-turn undo surface.

## Requirements

### Requirement: HU1 Bounded local audit projections
The system SHALL record supported local creates, updates, deletes and undos using allowlisted bounded fields, stable before/after hashes and private diffs, skipping unchanged ordinary mutations.

#### Scenario: Supported changed record
- **WHEN** a supported local record changes within its owning transaction
- **THEN** history stores its entity/action/source/time, before/after hashes and restorable changed-field values without copying arbitrary raw provider or credential fields.

#### Scenario: Unchanged record
- **WHEN** normalized before and after projections hash identically for an ordinary create/update/delete
- **THEN** no redundant change row is created; an undo action remains recorded under its distinct policy.

#### Scenario: Unknown or oversized fields
- **WHEN** input contains nonallowlisted or oversized field values
- **THEN** those fields are excluded from the audit projection rather than widening the persisted history surface.

Evidence: `backend/change_history.py:audit_projection`, `backend/change_history.py:audit_hash`, `backend/change_history.py:audit_diff`, `backend/change_history.py:record_change`; `tests/test_change_history.py:test_projection_keeps_allowlisted_bounded_fields_only`, `tests/test_change_history.py:test_record_change_persists_hashes_and_private_diff`, `tests/test_change_history.py:test_unchanged_record_is_skipped_but_undo_is_retained`, `tests/test_change_history.py:test_every_persisted_profile_field_is_audited`.

### Requirement: HU2 Retention and private public history
The system SHALL expose bounded newest-first history for the 180-day retention window, cap retained rows at one thousand and keep actual before/after values out of the public history representation.

#### Scenario: Public list
- **WHEN** authenticated history is read
- **THEN** entries expose identity, type/action/source/time, hashes, field-changed markers and sync scope (`local_only`, or `remote` for metric exports), without retained athlete values.

#### Scenario: Old or excessive rows
- **WHEN** history contains expired or excessive entries
- **THEN** reads hide entries older than the retention cutoff and clamp limits; normal history recording performs retention cleanup and makes room for its own row first, so at most one thousand rows remain after it.

#### Scenario: Atomic operation exceeds capacity
- **WHEN** a replacement reserves more than one thousand audit rows
- **THEN** it is rejected instead of silently pruning part of its own audit evidence or claiming complete undo coverage.

Evidence: `backend/history/service.py:ChangeHistoryService.list`; `backend/change_history.py:public_view`, `backend/change_history.py:cleanup`, `backend/change_history.py:reserve_capacity`; `tests/test_history_service.py:test_list_clamps_limits_orders_rows_and_returns_private_projection`, `tests/test_history_service.py:test_list_hides_expired_and_caps_rows_without_deleting`; `tests/test_change_history.py:test_public_view_never_exposes_diff_values`, `tests/test_change_history.py:test_cleanup_and_capacity_preserve_bounds`.

### Requirement: HU3 Read-only undo previews bound to current state
The system SHALL preview undo only for an existing supported create/update/delete whose recorded after-state still matches the current local projection, returning a safe proposal with the expected current hash.

#### Scenario: Eligible undo preview
- **WHEN** a valid history ID still describes the record's latest supported local state
- **THEN** preview returns public change metadata, target hash and a local undo proposal without restoring the record.

#### Scenario: Invalid, missing or changed target
- **WHEN** the history ID is malformed/missing, the current projection differs, or the history row cannot reconstruct a supported target
- **THEN** preview fails with the applicable validation/not-found/conflict response rather than proposing an overwrite of newer state.

#### Scenario: Already an undo action
- **WHEN** the selected history row is itself an undo
- **THEN** it cannot be undone recursively through this surface.

Evidence: `backend/history/undo_service.py:HistoryUndoService.preview`, `backend/history/undo_service.py:HistoryUndoService._load_history`; `backend/history/service.py:ChangeHistoryService.target`; `tests/test_history_undo_service.py:test_preview_returns_safe_proposal_and_opens_one_uow`, `tests/test_history_undo_service.py:test_preview_rejects_changed_current_hash`, `tests/test_history_undo_service.py:test_invalid_missing_and_repeated_change_ids_are_rejected`; `tests/test_history_service.py:test_target_preserves_action_diff_and_error_semantics`.

### Requirement: HU3a Supported entities and never-undone entries
The system SHALL audit and restore the entity types profile, workout_library, planned_unit, competition, training_plan, zone_configuration, activity_feedback, activity_session, nutrition_entry, nutrition_template, nutrition_product, checkin, equipment, equipment_assignment and equipment_maintenance through their owning services, and SHALL record confirmed metric exports to a provider as `metric_export` entries that stay listed with remote sync scope but are never undone; entries whose diff carries `undoable: false` stay listed and are never undone either.

#### Scenario: Metric export entry
- **WHEN** a confirmed or automatic metric export writes values to the provider
- **THEN** an update entry for `<provider>:<remote record>` with the allowlisted field names is recorded, shows `remote_sync` remote and `undoable` false, and a preview or apply for it fails with HTTP 400

#### Scenario: Entry marked not undoable
- **WHEN** an entry's diff carries `undoable: false`, as set by the Intervals.icu purge of release 2.0.0 for the feedback rows it re-keyed (no current code sets the marker)
- **THEN** the entry stays listed but preview and apply fail with HTTP 400 instead of restoring a record the purge moved

Evidence: `backend/change_history.py:ENTITY_TYPES`, `backend/change_history.py:NOT_UNDOABLE_ENTITY_TYPES`, `backend/change_history.py:undoable` (the unused `mark_not_undoable` is the only writer of the marker), `backend/history/undo_service.py:HistoryUndoService._restore`, `backend/history/undo_service.py:HistoryUndoService._load_history`, `backend/sync/metric_export.py`; `tests/test_metric_export.py:test_writes_are_in_the_change_history_without_undo`.

### Requirement: HU4 Atomic hash-checked domain restore
The system SHALL revalidate both recorded after-hash and supplied expected current hash during apply, restore through the owning domain transaction, audit the undo and leave remote state untouched.

#### Scenario: Apply eligible undo
- **WHEN** a valid undo request carries the previewed current hash
- **THEN** the prior local state is restored for the supported entity, planned-unit/plan changes advance planning revision, one undo row is written and the result reports remote_untouched.

#### Scenario: Concurrent edit
- **WHEN** current local state changed after preview or the supplied expected hash is absent/wrong
- **THEN** apply aborts before restore instead of overwriting that newer edit.

#### Scenario: Failure during restore/revision/history
- **WHEN** domain restoration, revision update or undo audit persistence fails
- **THEN** the complete transaction rolls back and no partial restored state remains.

Evidence: `backend/history/undo_service.py:HistoryUndoService.apply`, `backend/history/undo_service.py:HistoryUndoService._apply_one`, `backend/history/undo_service.py:HistoryUndoService._restore`; `tests/test_history_undo_service.py:test_apply_dispatches_all_entity_restores_and_records_once`, `tests/test_history_undo_service.py:test_apply_requires_preview_hash_even_when_current_is_unchanged`, `tests/test_history_undo_service.py:test_apply_rejects_stale_hash_before_domain_restore`, `tests/test_history_undo_service.py:test_domain_restore_failure_rolls_back_effects`, `tests/test_history_undo_service.py:test_revision_failure_rolls_back_restore_and_revision`, `tests/test_history_undo_service.py:test_history_failure_rolls_back_restore_and_revision`.

### Requirement: HU5 Data-preserving domain undo semantics
The system SHALL preserve supported current metadata while restoring audited local fields, support legacy audit-hash generations, and recheck visibility/date conflicts when restoring planned records.

#### Scenario: Legacy profile history
- **WHEN** an older history row predates added profile audit fields but still describes the same supported local state
- **THEN** its accepted legacy hash remains matchable, while an actual later edit still causes a conflict.

#### Scenario: Recreate or remove local object
- **WHEN** undo targets a deleted record or reverses a creation
- **THEN** the owning restore path recreates or removes the local record with its supported identity/link policy rather than deleting a corresponding remote record.

#### Scenario: Planning conflicts or location changes
- **WHEN** planned restoration would collide with newer calendar state, or profile restoration changes location
- **THEN** the planning restore rejects the collision and location restoration uses the existing cache invalidation hook.

Evidence: `backend/change_history.py:accepted_audit_hashes`; `backend/athlete/profile.py:ProfileService.restore_in_transaction`; `backend/planning/planned_unit_service.py:PlannedUnitService.restore_in_transaction`; `tests/test_history_undo_service.py:test_legacy_profile_row_stays_undoable_and_later_edits_still_conflict`, `tests/test_history_undo_service.py:test_legacy_row_accepts_batch_after_hash_and_rejects_wrong_expected_hash`; `tests/test_server_planning.py:test_planned_unit_undo_rejects_a_new_date_conflict`, `tests/test_server_planning.py:test_deleted_local_library_entry_can_be_undone_without_provider_write`; `tests/test_athlete_profile_service.py:test_restore_of_location_change_invokes_location_hook_and_clears_weather`.

### Requirement: HU6 Scoped Coach undo and explicit proposal path
The system SHALL require matching operation/change scope for the Coach undo tool, support direct local apply of an update or deletion when explicitly requested by that tool path, and return a session-bound proposal for previews and creation undo requiring explicit approval.

#### Scenario: Coach preview or creation undo
- **WHEN** `undo_training_change` requests preview for an authorized change ID, or requests apply for a change whose action is create
- **THEN** the current-state preview is converted to a session-bound local proposal without applying the restore; creation undo returns confirmation_required and deletes the created record only after the athlete confirms the card.

#### Scenario: Direct authorized apply
- **WHEN** the Coach requests apply to undo an update or deletion for that scoped change under the current athlete-started turn
- **THEN** the server creates a fresh preview hash and uses the same conflict-checked local undo service; no remote reversal is implied.

#### Scenario: Proposal confirmation or replay
- **WHEN** the owning session confirms and executes an eligible undo proposal
- **THEN** the token/hash/session checks apply and only one execution consumes it; foreign, expired or used approvals cannot dispatch another restore.

Evidence: `backend/coach/planning_action_tools.py:CoachPlanningActionToolService.execute`; `backend/http_api/history_undo_post.py:HistoryUndoPostRoutes.handle`; `backend/coach/proposal_execution.py:CoachProposalExecutionService.execute`; `tests/test_coach_tool_coverage.py:test_undo_is_a_bound_preview_until_explicit_confirmation`; `tests/test_coach_planning_action_tools.py` (preview/apply/scoped undo contracts); `tests/test_coach_planning_action_tools.py:test_create_undo_with_apply_is_only_offered_as_a_card`, `tests/test_coach_planning_action_tools.py:test_create_undo_deletes_only_after_the_athlete_confirms_the_card`, `tests/test_coach_planning_action_tools.py:test_update_undo_with_apply_still_runs_directly`; `tests/test_coach_proposal_execution.py:test_valid_undo_consumes_token_and_replay_is_rejected`, `tests/test_coach_proposal_execution.py:test_foreign_session_wrong_hash_and_expiry_cannot_consume_or_dispatch`.

### Requirement: HU7 Complete-effect receipt undo eligibility
The system SHALL summarize applied Coach record changes on receipts/answers and expose whole-turn undo only when every applied effect is fully tracked with history references.

#### Scenario: Fully tracked turn
- **WHEN** all applied changes in a turn come from fully tracked tools (profile, competition save, training-template management, activity feedback and sessions, nutrition entries, templates and products, check-ins and equipment), each with history references
- **THEN** the receipt/assistant message exposes distinct change labels, an undoable flag and no undone timestamp before undo.

#### Scenario: Mixed untracked effects
- **WHEN** any applied write lacks history or also changes untracked state such as plan constraints, sync flags or other records
- **THEN** its changes can be listed but whole-turn undo is false, preventing a misleading partial rollback.

#### Scenario: Applied single-change undo in a turn
- **WHEN** `undo_training_change` applied an undo in the turn (its result status is `undone`)
- **THEN** the receipt lists "Lokale Änderung zurückgenommen" and whole-turn undo is false.

#### Scenario: Plan-check notes
- **WHEN** an applied Coach plan write has plan-check notes
- **THEN** its receipt includes safe structured notes, and the answer shows their labels, dates, evidence strength and severity alongside the change summary.

#### Scenario: Read, failed or pending action
- **WHEN** a turn only reads, fails before applying, stages/previews or waits for approval
- **THEN** those steps do not appear as applied record changes, and model input does not receive private undo references.

Evidence: `backend/coach/change_receipts.py:change_summary`, `backend/coach/change_receipts.py:_FULLY_TRACKED_TOOLS`, `backend/coach/change_receipts.py:turn_changes`; `backend/coach/final_receipt.py:CoachFinalReceiptService.persist`; `public/coach.js:appendMessageChanges`; `tests/test_coach_change_receipts.py:test_applied_tracked_writes_are_listed_once_and_undoable`, `tests/test_coach_change_receipts.py:test_a_write_with_untracked_effects_is_listed_without_turn_undo`, `tests/test_coach_change_receipts.py:test_an_applied_history_undo_is_listed_and_blocks_turn_undo`, `tests/test_coach_planning_action_tools.py:test_undo_applies_directly_when_apply_is_true`, `tests/test_coach_change_receipts.py:test_reads_failures_proposals_and_previews_are_not_changes`, `tests/test_coach_change_receipts.py:test_the_model_never_receives_undo_references`; `tests/test_server_coach_turn_undo.py:test_turn_changes_show_on_the_answer_and_undo_together`.

### Requirement: HU8 All-or-none whole-turn undo
The system SHALL undo an eligible completed turn's collected local changes newest-first in one transaction and update its durable receipt once, refusing repeated or stale/ineligible turn undo.

#### Scenario: Whole turn restored
- **WHEN** an authenticated explicit undo-turn request selects an eligible finished turn
- **THEN** changes restore in reverse recording order, the receipt gains an undone timestamp, the UI updates the change summary and remote state remains untouched.

#### Scenario: One record changed later
- **WHEN** any collected change no longer matches current state
- **THEN** the whole undo rolls back rather than restoring only the unaffected records.

#### Scenario: Invalid or repeated turn
- **WHEN** the ID is invalid/missing, the turn is not completed, it has untracked/no changes or it was already undone
- **THEN** the request fails explicitly and cannot apply the turn twice.

Evidence: `backend/coach/turn_undo.py:CoachTurnUndoService.undo`; `backend/history/undo_service.py:HistoryUndoService.apply_many`; `public/coach.js:undoCoachTurn`; `tests/test_server_coach_turn_undo.py:test_turn_changes_show_on_the_answer_and_undo_together`, `tests/test_server_coach_turn_undo.py:test_a_record_changed_after_the_turn_aborts_the_whole_undo`, `tests/test_server_coach_turn_undo.py:test_a_turn_with_untracked_writes_cannot_be_undone`, `tests/test_server_coach_turn_undo.py:test_unknown_and_invalid_turns_are_rejected`; `tests/coach-turn-undo.test.cjs` (UI receipt refresh contracts). Whole-turn undo is an authenticated single-athlete API action; per-session ownership is not asserted beyond the implemented route.
