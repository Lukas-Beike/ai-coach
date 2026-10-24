# coach-tool-authority Specification

## Purpose

Describe the executable Coach tool catalog, stored-message authorization, effect boundaries, explicit approvals and durable replay/receipt contracts. This brownfield baseline distinguishes server-enforced checks from model interpretation of natural language.

## Requirements

### Requirement: CA1 Complete owned tool capability catalog
The system SHALL classify every offered Coach tool by its schema, concrete owner, effect, authorization policy and receipt kind, and SHALL reject calls to tools unavailable in the current turn.

#### Scenario: Registered local and read capabilities
- **WHEN** Coach contracts are built
- **THEN** profile, feedback, competitions, equipment, nutrition, planning, library, analysis, history, refresh, sync and dialogue-control tools each have an owner and effect policy; a mutation requiring an effect receipt has a receipt label.

#### Scenario: Unavailable or unknown tool
- **WHEN** a model emits an unknown name or a tool absent from the current offered set
- **THEN** the call fails before domain dispatch and cannot introduce an unregistered write path.

#### Scenario: Catalog surface variants
- **WHEN** dialogue tools are assembled
- **THEN** the catalog distinguishes canonical-only `apply_training_changes`, dialogue-only atomic `apply_training_patch`, clarification/cancellation/duplicate inspection, and tools shared by both surfaces.

Evidence: `backend/coach/capabilities.py:build_capability_catalog`, `backend/coach/capabilities.py:OWNER_TOOLS`; `backend/coach/tool_registry.py:build_tool_contracts`; `backend/coach/tool_schemas.py:build_structured_tool_schemas`; `backend/coach/tool_call_metadata.py:structured_tool_call_metadata`; `tests/test_coach_tool_coverage.py:test_capability_catalog_covers_each_schema_dispatch_owner_and_effect_policy`, `tests/test_coach_tool_coverage.py:test_matrix_has_observed_success_case_for_every_available_tool_and_variant`; `tests/test_coach_dialogue.py:test_unknown_tool_and_malformed_arguments_have_no_effect`. The handoff includes an exhaustive name-to-requirement map; catalog test inspection is not a claim of live model coverage.

### Requirement: CA2 Athlete-message provenance and exact effect scope
The system SHALL require each mutating dialogue step to reference stored athlete messages including the current message and carry validated target, object/domain scope, bounded period, constraints and remote-write declaration.

#### Scenario: Grounded local action
- **WHEN** an athlete-started turn selects a local write with valid user-message IDs and live object scope
- **THEN** the server binds that operation to its authorized local targets and passes the validated scope to its domain service.

#### Scenario: Forged or absent provenance
- **WHEN** the action references assistant/provider content, omits the current stored message, or runs with mutations withheld
- **THEN** the server denies the mutation and preserves athlete records.

#### Scenario: Out-of-scope object or period
- **WHEN** a requested edit names a different target ID or affects dates outside its inclusive authorized period
- **THEN** scope validation rejects it rather than widening authority from the model's summary.

Evidence: `backend/coach/authorization.py:validate_request`, `backend/coach/authorization.py:require_coach_scope`, `backend/coach/authorization.py:dialogue_tools`; `backend/coach/dialogue_action.py:CoachDialogueActionService.classify`; `backend/coach/chat_turn.py:CoachChatTurnService._background_may_write`; `tests/test_coach_dialogue.py:test_request_provenance_rejects_assistant_or_missing_current_message`, `tests/test_coach_dialogue.py:test_different_target_id_cannot_escape_action_scope`, `tests/test_coach_dialogue.py:test_out_of_period_change_is_rejected`; `tests/test_coach_chat_turn.py:test_background_resume_without_stored_athlete_message_is_read_only`.

### Requirement: CA3 Direct local writes with impact checks
The system SHALL permit ordinary bounded local changes from a stored athlete-started turn without an extra UI confirmation, while retaining provenance, scope, domain validation and the distinct preview/approval flows.

#### Scenario: Reversible local create or edit
- **WHEN** an authorized Coach step makes an ordinary local profile, check-in, competition, equipment, nutrition-diary, template or workout change
- **THEN** it executes the corresponding local service and returns its actual local result rather than requiring a general save-confirmation button.

#### Scenario: Unattended or explicitly read-only turn
- **WHEN** no stored athlete message authorizes the turn, or its persisted intent withholds mutations
- **THEN** local writes remain denied even if the model emits a valid tool call.

#### Scenario: Natural-language interpretation boundary
- **WHEN** the athlete gives a paraphrase, correction, pronoun or hypothetical question
- **THEN** the model receives instructions to resolve meaning, ask consequential ambiguities and keep advice read-only; server provenance and impact checks still apply rather than treating an instruction prompt as an independent proof of intent.

Evidence: `backend/coach/write_gate.py:build_turn_authority`, `backend/coach/write_gate.py:check_write`; `backend/coach/dialogue.py:INSTRUCTIONS`; `backend/coach/turn_write_gate.py:CoachTurnWriteGate.denial`; `tests/test_coach_write_gate.py:test_reversible_local_writes_need_no_domain_wording`, `tests/test_coach_write_gate.py:test_a_turn_without_a_stored_athlete_message_writes_nothing`; `tests/test_coach_tool_coverage.py:test_advice_and_negation_scripts_leave_state_unchanged`. Scripted tests exercise execution mechanics; they do not establish universal natural-language intent accuracy.

### Requirement: CA4 Domain-confirmed destructive and bulk effects
The system SHALL require a successful domain-specific impact confirmation for local deletes/archives, whole-plan commit/replacement, and a turn touching more than seven counted records; classifier absence, failure or unrelated-domain confirmation SHALL fail closed.

#### Scenario: Small edit versus delete
- **WHEN** a stored athlete-started turn updates a few local records
- **THEN** ordinary edits can proceed; changing an action/status into deletion or archival additionally requires confirmed deletion intent in that record's domain.

#### Scenario: Whole plan or accumulated bulk
- **WHEN** committing/replacing a whole plan, or accumulated counted records exceed seven
- **THEN** the impact verdict must confirm the bulk request for that domain, including effects resumed from prior receipts.

#### Scenario: Classifier failure or cross-domain approval
- **WHEN** the classifier is unavailable, errors, emits invalid output or confirms only another domain
- **THEN** the server denies the destructive/bulk call without opening its write transaction, adding a durable effect receipt or claiming a save.

Evidence: `backend/coach/write_gate.py:call_impact`, `backend/coach/write_gate.py:record_count`, `backend/coach/write_gate.py:check_write`; `backend/coach/turn_write_gate.py:CoachTurnWriteGate`; `tests/test_coach_write_gate.py:test_delete_confirmation_is_bound_to_its_domain`, `tests/test_coach_write_gate.py:test_whole_plan_tools_need_a_confirmed_bulk_change`, `tests/test_coach_write_gate.py:test_many_records_in_one_turn_need_a_confirmed_bulk_change`, `tests/test_coach_write_gate.py:test_no_classifier_and_failures_fail_closed`; `tests/test_coach_turn_write_gate.py:test_denied_write_does_not_execute_record_or_open_a_transaction`.

### Requirement: CA5 Named remote synchronization and explicit proposals
The system SHALL require the athlete's named Intervals.icu sync request before a remote-write step, preserve a separate per-step remote target/scope, and route remote changes through the implemented explicit approval proposal.

#### Scenario: Local save only
- **WHEN** the athlete requests local plan, competition or meal saving without naming remote synchronization
- **THEN** no Intervals.icu write is authorized by that request; provider refresh remains a provider read rather than a workout push.

#### Scenario: Explicit named sync
- **WHEN** the athlete names an unnegated Intervals.icu synchronization or accepts the directly preceding concrete sync offer
- **THEN** the step still needs the matching provider target, sync scope and remote-write declaration; its proposed effect is shown for explicit approval before dispatch.

#### Scenario: Negated sync or classifier-only approval
- **WHEN** sync is negated, merely discussed, or supplied only by an impact-classifier verdict
- **THEN** the remote write is denied; a local or bulk confirmation cannot grant remote permission.

#### Scenario: Duplicate activity removal
- **WHEN** a supported duplicate inspection identifies a Garmin cycling copy and a canonical Wahoo recording
- **THEN** inspection itself is read-only; explicit approved deletion revalidates the pair, removes only the selected duplicate and retains the canonical activity, then updates the local deletion projection.

Evidence: `backend/coach/write_gate.py:remote_requested`, `backend/coach/write_gate.py:build_turn_authority`, `backend/coach/write_gate.py:check_write`; `backend/coach/tool_execution_service.py:CoachStructuredToolExecutionService.execute`; `backend/coach/proposal_creation.py:CoachProposalCreationService.create_remote_write`; `tests/test_coach_write_gate.py:test_named_sync_requests_allow_remote_tools_without_the_classifier`, `tests/test_coach_write_gate.py:test_unnamed_negated_or_asked_syncs_are_denied`, `tests/test_coach_write_gate.py:test_the_classifier_never_grants_the_illness_sync_to_intervals`; `tests/test_coach_tool_coverage.py:test_competition_lifecycle_syncs_only_after_explicit_followup`; `backend/activities/duplicate_inspection.py:DuplicateInspector.latest`; `backend/activities/duplicate_service.py:DuplicateActivityService.delete`; `tests/test_coach_tool_coverage.py:test_duplicate_inspection_returns_preview_without_deleting_provider_data`, `tests/test_coach_tool_coverage.py:test_delete_duplicate_intervals_activity`.

### Requirement: CA6 Session-bound immutable approval contents
The system SHALL bind a proposal to its session, bounded lifetime and stored payload identity, reject a supplied mismatching payload hash, consume its approval token once, and validate original athlete provenance and frozen remote selections before dispatch.

#### Scenario: Valid approval
- **WHEN** the owning authenticated session submits a ready unexpired token and matching payload hash
- **THEN** the system consumes that token once and dispatches the approved action under the original conversation and turn binding.

#### Scenario: Stale, reused or foreign approval
- **WHEN** a token is expired, consumed, belongs to another session or its payload hash differs
- **THEN** execution is rejected without silently replacing the proposal with a new effect.

#### Scenario: Selection changed after preview
- **WHEN** new pending units appear after an all-pending preview, or selected source records changed
- **THEN** approval remains bound to the previewed manifest and hashes; it does not expand to later additions or overwrite intervening edits.

#### Scenario: Unknown execution outcome in the client
- **WHEN** execute was sent but no definite response arrives
- **THEN** the client blocks blind repeat execution and rereads proposal status before offering another attempt; a consumed token is treated as an outcome to inspect rather than proof of failure.

Evidence: `backend/coach/proposal_execution.py:CoachProposalExecutionService._load_ready_action`, `backend/coach/proposal_execution.py:CoachProposalExecutionService._consume_action`, `backend/coach/proposal_execution.py:CoachProposalExecutionService._validate_remote_write_provenance`; `backend/coach/proposal_creation.py:_approved_remote_arguments`; `tests/test_coach_proposal_execution.py:test_foreign_session_wrong_hash_and_expiry_cannot_consume_or_dispatch`, `tests/test_coach_proposal_execution.py:test_competing_execution_dispatches_only_once`; `public/coach.js:reconcileCoachActionProposal`; `tests/frontend-write-safety.test.cjs:a lost execute response keeps the action locked and is not reported as a failed confirmation`, `tests/frontend-write-safety.test.cjs:reconcile re-enables a proposal the server still reports as confirmable`; `tests/test_coach_tool_coverage.py:test_all_pending_approval_does_not_expand_to_units_added_after_preview`; `tests/test_coach_dialogue.py:test_sync_followup_failure_distinguishes_coach_interruption_and_keeps_job`.

### Requirement: CA7 Idempotent calls and checkpointed rounds
The system SHALL return cached receipts for repeated identical calls/effects, reject a reused call ID with changed effect, and checkpoint tool-round progress so resumed execution does not repeat successful durable writes.

#### Scenario: Same effect with another call ID
- **WHEN** a non-read tool repeats a successful effect in the same durable turn
- **THEN** the stored result is replayed rather than executing the write again.

#### Scenario: Changed call or current read
- **WHEN** the same call ID carries a different effect, or a new call ID reads mutable local state
- **THEN** the changed call conflicts, while the new read obtains current state rather than an earlier effect-cache result.

#### Scenario: Stale draft or failed effect
- **WHEN** a cached draft is missing or based on an older planning revision, or an earlier effect failed
- **THEN** successful-effect replay is not used as proof of a valid current result and the permitted repair path can run.

Evidence: `backend/coach/tool_replay.py:CoachStructuredToolReplayService.lookup`; `backend/coach/tool_round_journal.py:CoachStructuredToolRoundJournal`; `tests/test_coach_tool_replay.py:test_replays_matching_call_id_and_rejects_changed_effect`, `tests/test_coach_tool_replay.py:test_replays_successful_mutating_effect_with_different_call_id`, `tests/test_coach_tool_replay.py:test_does_not_replay_effect_for_read_only_tool`, `tests/test_coach_tool_replay.py:test_does_not_replay_failed_effect`, `tests/test_coach_tool_replay.py:test_does_not_replay_missing_or_stale_draft`; `tests/test_coach_dialogue.py:test_background_replays_checkpointed_outputs_before_new_response`.

### Requirement: CA8 Bounded execution and cancellation boundaries
The system SHALL bound tool calls and rounds, count allowed mutations across resumed receipts, stop further writes on clarification/cancellation, and preserve completed effects when stopping.

#### Scenario: Per-turn mutation cap
- **WHEN** twenty-five allowed gated writes have been spent in a turn including resumed receipts
- **THEN** additional writes return not-performed with cap guidance; denied calls do not consume that budget.

#### Scenario: Clarification or cancellation in a tool round
- **WHEN** a model requests clarification or cancellation alongside mutation calls
- **THEN** the paused round cannot apply those writes regardless of ordering, while read-only calls remain available.

#### Scenario: Tool-round budget exhausted
- **WHEN** the bounded round budget is reached
- **THEN** tool outputs are still submitted for the final response and unfinished work is reported without resetting the model, losing committed effects or pretending completion.

Evidence: `backend/coach/tool_call_metadata.py:structured_tool_call_metadata`; `backend/coach/structured_tool_round.py:CoachStructuredToolRoundService`; `backend/coach/tool_preparation.py:CoachStructuredToolPreparationService._request_is_paused`; `tests/test_coach_write_gate.py:test_cap_is_25_and_counts_allowed_writes`, `tests/test_coach_write_gate.py:test_denied_calls_do_not_count`; `tests/test_coach_turn_write_gate.py:test_resumed_turn_seeds_cap_from_existing_receipts`; `tests/test_coach_dialogue.py:test_clarification_blocks_writes_in_either_tool_order`, `tests/test_coach_dialogue.py:test_tool_round_limit_submits_outputs_and_keeps_provider_selection`.

### Requirement: CA9 Truthful durable receipts and supported undo
The system SHALL persist actual tool outcomes and confirmed change references, distinguish local effects, approval-pending actions and sync jobs, and expose whole-turn undo only when every applied effect is fully tracked.

#### Scenario: Successful local change
- **WHEN** an authorized local write commits
- **THEN** the final receipt includes its effect and change summary, and the answer reflects the stored result rather than only the model's claim.

#### Scenario: Mixed effect or preview only
- **WHEN** a turn only stages/previews, awaits approval, or includes effects not fully tracked by history
- **THEN** it does not offer a misleading whole-turn undo; supported individual undo/proposal flows remain distinct.

#### Scenario: Partial failure
- **WHEN** one effect succeeds and another unresolved step or final provider response fails
- **THEN** receipts retain successful effects, unresolved failures and queued job identities without treating unrelated success as repair of the failed step.

Evidence: `backend/coach/change_receipts.py:change_summary`, `backend/coach/change_receipts.py:turn_changes`; `backend/coach/final_receipt.py:CoachFinalReceiptService`; `backend/coach/turn_failures.py:CoachTurnFailureService.persist`; `tests/test_coach_final_receipt.py:test_turn_changes_are_summarized_on_the_receipt_and_the_answer`; `tests/test_coach_dialogue.py:test_success_on_other_object_does_not_hide_failed_step`, `tests/test_coach_dialogue.py:test_summary_failure_preserves_effect_and_replays_receipt`; `tests/test_coach_change_receipts.py` (complete-effect undo eligibility contracts).

### Requirement: CA10 Validated repair dependencies and exceptional approvals
The system SHALL reject malformed tools without partial effects, permit repairs within original authority, prevent remote steps from overtaking unresolved local failures, and retain explicit proposals for saved meal/product definitions and the separate undo-preview flow.

#### Scenario: Repairable local validation failure
- **WHEN** a model corrects invalid arguments or stale local state after rereading current references
- **THEN** it can retry within the same authorized scope; a successful unrelated object or period does not erase an unresolved failure.

#### Scenario: Local prerequisite failed
- **WHEN** a requested local plan has not committed successfully
- **THEN** a dependent created/all-pending push is blocked instead of synchronizing a partial or unintended plan.

#### Scenario: Meal/product definition or undo proposal
- **WHEN** the Coach saves a reusable meal/product definition or prepares an undo that requires an approval proposal
- **THEN** it returns approval-required and the explicit proposal path; creating the proposal does not itself execute the athlete-data effect.

Evidence: `backend/coach/tool_preparation.py:CoachStructuredToolPreparationService.prepare`, `backend/coach/tool_preparation.py:CoachStructuredToolPreparationService._has_unresolved_steps_before_remote_write`; `backend/coach/tool_execution_service.py:CoachStructuredToolExecutionService.execute`; `tests/test_coach_dialogue.py:test_invalid_arguments_can_be_repaired_in_same_dialogue`, `tests/test_coach_dialogue.py:test_failed_local_step_blocks_following_all_pending_push`, `tests/test_coach_dialogue.py:test_plan_replacement_does_not_resolve_invalid_patch_for_other_period`; `tests/test_coach_tool_coverage.py:test_saved_meals_run_through_authorized_coach_and_receipts`, `tests/test_coach_tool_coverage.py:test_confirmed_product_is_saved_locally_through_authorized_coach_receipt`, `tests/test_coach_tool_coverage.py:test_undo_is_a_bound_preview_until_explicit_confirmation`.
