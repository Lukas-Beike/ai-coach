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
- **THEN** the catalog distinguishes canonical-only `apply_training_changes`, dialogue-only atomic `apply_training_patch`, clarification/cancellation, and tools shared by both surfaces.

Evidence: `backend/coach/capabilities.py:build_capability_catalog`, `backend/coach/tool_specs.py:TOOL_SPECS`; `backend/coach/tool_registry.py:build_tool_contracts`; `backend/coach/tool_schemas.py:build_structured_tool_schemas`; `backend/coach/tool_call_metadata.py:structured_tool_call_metadata`; `tests/test_coach_tool_coverage.py:test_capability_catalog_covers_each_schema_dispatch_owner_and_effect_policy`, `tests/test_coach_tool_coverage.py:test_matrix_has_observed_success_case_for_every_available_tool_and_variant`; `tests/test_coach_dialogue.py:test_unknown_tool_and_malformed_arguments_have_no_effect`. `openspec/COACH_TOOLS.md` (generated from the registry) lists every tool with its surface, effect, gate domain, owner, requirements, parameters, receipt label and turn-undo flag, including the session tools `confirm_activity_session`, `split_activity_session` and `merge_activity_sessions` and `push_strength_to_garmin`; catalog test inspection is not a claim of live model coverage.

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

#### Scenario: Request envelope bounds
- **WHEN** a mutating dialogue step carries its `_request` envelope (fields and schema bounds in `openspec/COACH_TOOLS.md`, generated)
- **THEN** the validator also rejects a field set other than the eight required fields (`request_fields`), `source_message_ids` that are not 1 to 24 stored athlete message ids including the current one (`request_provenance`), an unknown `target` (`request_target`), a blank `summary` or one over 2000 characters (`request_summary`), a blank `scope` item or one over 160 characters (`request_scope`), a blank `constraints` item or one over 1000 characters (`request_constraints`), a non-boolean `remote_write` or unknown `sync_scope` (`request_sync`), and a `period` whose ISO dates are not 0 to 730 days apart (`request_period`)

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
- **THEN** the impact verdict must confirm the bulk request for that domain, including effects resumed from prior receipts. Only calls that did not fail count: a failed write saved nothing, so its records go back to the turn and a corrected retry stays within the original authority (it still counts toward the per-turn write cap).

#### Scenario: Classifier failure or cross-domain approval
- **WHEN** the classifier is unavailable, errors, emits invalid output or confirms only another domain
- **THEN** the server denies the destructive/bulk call without opening its write transaction, adding a durable effect receipt or claiming a save.

Evidence: `backend/coach/write_gate.py:call_impact`, `backend/coach/write_gate.py:record_count`, `backend/coach/write_gate.py:check_write`; `backend/coach/turn_write_gate.py:CoachTurnWriteGate`; `tests/test_coach_write_gate.py:test_delete_confirmation_is_bound_to_its_domain`, `tests/test_coach_write_gate.py:test_whole_plan_tools_need_a_confirmed_bulk_change`, `tests/test_coach_write_gate.py:test_many_records_in_one_turn_need_a_confirmed_bulk_change`, `tests/test_coach_write_gate.py:test_no_classifier_and_failures_fail_closed`; `tests/test_coach_turn_write_gate.py:test_denied_write_does_not_execute_record_or_open_a_transaction`, `tests/test_coach_turn_write_gate.py:test_a_failed_write_refunds_its_bulk_records_to_the_retry`, `tests/test_coach_turn_write_gate.py:test_a_failed_write_leaves_the_bulk_budget_to_its_retry`, `tests/test_coach_turn_write_gate.py:test_resumed_budget_adds_up_the_gates_own_record_counts`; `backend/coach/turn_write_gate.py:CoachTurnWriteGate.settle`.

### Requirement: CA5 Named remote synchronization and explicit proposals
The system SHALL require the athlete's named sync request for the step's own provider before a remote-write step (the Intervals.icu name or a sync verb for Intervals.icu, Garmin or watch wording for a Garmin push), preserve a separate per-step remote target/scope, and run a named remote write without an approval card, bound to stored state as a card would bind it; only an explicit Garmin removal still goes through the explicit approval proposal.

#### Scenario: Local save only
- **WHEN** the athlete requests local plan, competition or meal saving without naming remote synchronization
- **THEN** no Intervals.icu write is authorized by that request; provider refresh remains a provider read rather than a workout push.

#### Scenario: Explicit named sync
- **WHEN** the athlete names an unnegated Intervals.icu synchronization, uses an unnegated sync verb (such as synchronisieren, abgleichen, hochladen or reparieren), or accepts the directly preceding concrete sync offer
- **THEN** the step still needs the matching provider target, sync scope and remote-write declaration; it is bound to the current stored units, payload hashes and manifests and queued in the same turn without a card; the request's own unit tokens bound the units it may push, and only orphan leftovers the server adds gain a token. The turn receipt lists the queued sync and each remote deletion it carries (orphaned Intervals.icu events, deleted competitions, orphaned Garmin workouts), and the turn has no whole-turn undo.

#### Scenario: Unclear sync request
- **WHEN** the wording gate finds no named sync for the step's provider
- **THEN** nothing is written or queued and the Coach offers the sync in its answer; the athlete's yes to that closing offer is a named sync.

#### Scenario: Negated sync or classifier-only approval
- **WHEN** sync is negated or kept by the athlete ("Synchronisieren mache ich selbst"), merely discussed, or supplied only by an impact-classifier verdict
- **THEN** the remote write is denied; a negated sync blocks the whole message until a later contrast word ("Nicht synchronisieren! Der Sync kommt später." asks nothing); a local or bulk confirmation cannot grant remote permission.

#### Scenario: Training term Intervals
- **WHEN** a message names "Intervals" without ".icu" and without a sync or push verb ("Mach mir 5x4 min Intervals am Dienstag")
- **THEN** it names no Intervals.icu sync.

#### Scenario: Another provider or a past sync
- **WHEN** a sentence part names Garmin or Wahoo but not Intervals.icu ("Sync meine Garmin-Daten"), or describes a past sync with an auxiliary and only past participles ("Ich habe gestern synchronisiert", "Ich habe mit Intervals gesynct")
- **THEN** that part names no Intervals.icu sync; generic sync verbs in a request ("Synchronisiere den Plan") still do.

#### Scenario: Information question or "without"
- **WHEN** a sentence is a question that starts with an interrogative ("Wie synchronisiere ich?") and has no second-person request verb (kannst, könntest, würdest, solltest, willst, "can you"), or a phrase starts with "ohne"/"without"
- **THEN** the question asks nothing ("Kannst du das syncen?" does ask), and the "ohne" phrase negates only when it names the sync or the calendar ("Sync mit Intervals ohne die Ruhetage" still asks).

#### Scenario: Accepting an offer
- **WHEN** the athlete's whole message is a bare yes (an anchor such as ja, ok, gerne or mach with filler words, at most 5 words) or a yes followed only by transfer or scope words (at most 15 words), without negation or question mark
- **THEN** it accepts only the sync that the closing question of the Coach's previous message (its last 1,200 characters) offers; a pending request that is retried or answered contributes its original athlete text to the wording check.

#### Scenario: Garmin strength push
- **WHEN** the athlete's own message names Garmin or the watch with a transfer verb, or accepts the directly preceding Garmin offer
- **THEN** `push_strength_to_garmin` queues the selected strength or run units with target `garmin` and scope `garmin_sync` without a card, each bound to its stored payload hash; a call with an explicit removal entry, or a retry of a Garmin job that has one, asks on a card, and only its approval queues that job. A refusal blocks the Garmin wording of the whole message as it does for Intervals.icu. Intervals.icu wording never grants it, a Garmin push or removal request never grants an Intervals.icu write, an upload entry needs the athlete's own push wording and a removal entry the athlete's own Garmin removal wording (no classifier is asked).

Evidence:
- `backend/coach/proposal_creation.py:_approved_garmin_arguments`
- `backend/coach/proposal_creation.py:CoachProposalCreationService.create_remote_write`
- `backend/coach/proposal_creation.py:CoachProposalCreationService.prepare_remote_write`
- `backend/coach/proposal_creation.py:remote_removal_lines`
- `backend/coach/sync_tools.py:CoachSyncToolService._push_strength_to_garmin`
- `backend/coach/tool_execution_service.py:CoachStructuredToolExecutionService.execute`
- `backend/coach/write_gate.py:build_turn_authority`
- `backend/coach/write_gate.py:check_write`
- `backend/coach/write_gate.py:garmin_removal_requested`
- `backend/coach/write_gate.py:is_bare_affirmation`
- `backend/coach/write_gate.py:is_contextual_affirmation`
- `backend/coach/write_gate.py:remote_requested`
- `backend/coach/write_gate.py:requested_providers`
- `tests/test_coach_change_receipts.py:test_a_card_free_sync_lists_its_remote_removals_without_turn_undo`
- `tests/test_coach_plan_sync_card_flow.py:test_a_named_push_retry_runs_without_a_card_unless_it_removes_from_garmin`
- `tests/test_coach_plan_sync_card_flow.py:test_a_named_sync_queues_the_same_job_without_a_card`
- `tests/test_coach_plan_sync_card_flow.py:test_an_explicit_garmin_removal_still_asks_on_a_card`
- `tests/test_coach_plan_sync_card_flow.py:test_without_a_card_the_request_scope_bounds_the_units`
- `tests/test_coach_sync_tools.py:test_garmin_push_needs_the_garmin_target_scope_and_approved_entries`
- `tests/test_coach_tool_coverage.py:test_competition_lifecycle_syncs_only_after_explicit_followup`
- `tests/test_coach_tool_coverage.py:test_garmin_strength_push_is_bound_to_the_stored_units`
- `tests/test_coach_tool_execution_service.py:test_a_named_illness_sync_runs_the_bound_payload_with_accepted_findings`
- `tests/test_coach_write_gate.py:GarminTierTests`
- `tests/test_coach_write_gate.py:test_contextual_affirmation_accepts_a_detailed_yes_to_a_sync_offer`
- `tests/test_coach_write_gate.py:test_named_sync_requests_allow_remote_tools_without_the_classifier`
- `tests/test_coach_write_gate.py:test_negation_covers_its_sentence_up_to_a_contrast_word`
- `tests/test_coach_write_gate.py:test_pending_origin_carries_a_sync_request`
- `tests/test_coach_write_gate.py:test_the_classifier_never_grants_the_illness_sync_to_intervals`
- `tests/test_coach_write_gate.py:test_unnamed_negated_or_asked_syncs_are_denied`
- `tests/test_coach_write_gate.py:test_without_negates_only_a_phrase_that_names_the_sync`

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

#### Scenario: Selected Intervals.icu plan sync card
- **WHEN** the Coach proposes an Intervals.icu plan sync for selected units
- **THEN** the card is rejected unless every listed unit exists locally, and the stored intent grants the object scope of exactly those units, so approving the card authorizes what the athlete saw; a card-free named sync runs the same binding (CA5), and a model call that skips it grants nothing.

#### Scenario: Unknown execution outcome in the client
- **WHEN** execute was sent but no definite response arrives
- **THEN** the client blocks blind repeat execution and rereads proposal status before offering another attempt; a consumed token is treated as an outcome to inspect rather than proof of failure.

#### Scenario: Proposal lifecycle
- **WHEN** a proposal is created, confirmed, executed or cancelled (request fields, responses and errors are the route contracts of `/api/coach/actions/*` in `docs/api-routes.md`, generated)
- **THEN** it lives 600 seconds as `preview`, becomes `ready` when the owning session confirms it (a new 32-byte token whose SHA-256 alone is stored; confirming again replaces the unused token), `used` when executed and `cancelled` when cancelled, which clears the token; its public view holds `id`, `action_type` (`undo_change`, `remote_coach_write`, or `local_coach_write` for a meal or product card created before the direct save), `target_system`, `object_ids`, `diff`, `payload_hash`, `expires_at` and `status`, never the payload or the token

#### Scenario: Listing and housekeeping
- **WHEN** open proposals are listed or a new one is written
- **THEN** the chat history lists at most 30 unexpired `preview` or `ready` proposals of the session, newest first, and a turn receipt shows an expired open one as expired; expired rows are deleted only when the next proposal is written, and a chat reset cancels the open remote and local write proposals

Evidence:
- `backend/coach/conversation.py:CoachConversationResetService._reset_local`
- `backend/coach/proposal_creation.py:_approved_remote_arguments`
- `backend/coach/proposal_creation.py:_card_authorized_intent`
- `backend/coach/proposal_creation.py:CoachProposalCreationService.create`
- `backend/coach/proposal_execution.py:CoachProposalExecutionService._consume_action`
- `backend/coach/proposal_execution.py:CoachProposalExecutionService._load_ready_action`
- `backend/coach/proposal_execution.py:CoachProposalExecutionService._validate_remote_write_provenance`
- `backend/coach/proposal_models.py:COACH_ACTION_TTL_SECONDS`
- `backend/coach/proposal_models.py:coach_action_view`
- `backend/coach/proposal_read.py:CoachProposalConfirmationService`
- `public/coach.js:reconcileCoachActionProposal`
- `tests/frontend-write-safety.test.cjs:a lost execute response keeps the action locked and is not reported as a failed confirmation`
- `tests/frontend-write-safety.test.cjs:reconcile re-enables a proposal the server still reports as confirmable`
- `tests/test_coach_dialogue.py:test_sync_followup_failure_distinguishes_coach_interruption_and_keeps_job`
- `tests/test_coach_plan_sync_card_flow.py:ApprovedCardAuthorizesItsUnitsTests`
- `tests/test_coach_proposal_confirmation.py:test_reconfirm_rotates_unused_token`
- `tests/test_coach_proposal_confirmation.py:test_ttl_boundary_is_expired_and_does_not_mutate`
- `tests/test_coach_proposal_execution.py:test_competing_execution_dispatches_only_once`
- `tests/test_coach_proposal_execution.py:test_foreign_session_wrong_hash_and_expiry_cannot_consume_or_dispatch`
- `tests/test_coach_proposal_read_service.py:test_returns_newest_30_and_never_exposes_payload_or_action_token`
- `tests/test_coach_tool_coverage.py:test_all_pending_sync_binds_the_units_pending_at_the_request`

### Requirement: CA7 Idempotent calls and checkpointed rounds
The system SHALL return cached receipts for repeated identical calls/effects, reject a reused call ID with changed effect, and checkpoint tool-round progress so a turn that is requested again after an interruption does not repeat successful durable writes.

#### Scenario: Same effect with another call ID
- **WHEN** a non-read tool repeats a successful effect in the same durable turn
- **THEN** the stored result is replayed rather than executing the write again, marked `replayed: true` with a notice that nothing new was saved, so the Coach reports the change once.

#### Scenario: Changed call or current read
- **WHEN** the same call ID carries a different effect, or a new call ID reads mutable local state
- **THEN** the changed call conflicts, while the new read obtains current state rather than an earlier effect-cache result.

#### Scenario: Stale draft or failed effect
- **WHEN** a cached draft is missing or based on an older planning revision, or an earlier effect failed
- **THEN** successful-effect replay is not used as proof of a valid current result and the permitted repair path can run.

#### Scenario: Step keys
- **WHEN** a tool call is executed or fails
- **THEN** its step in the turn's receipt holds `call_id`, `tool`, `effect_key`, `step_key`, `repair_key`, `scope_repair_key`, `request_binding_key`, `plan_effect_key`, `request` and `result`, and for an executed call `changes`, `record_count` and `record_ids`; `effect_key` hashes the tool, its arguments without `_request`, and the envelope's target, period, constraints, `remote_write`, `sync_scope` and sorted scope, so a reworded summary or other source message ids repeat nothing, and a changed effect under a recorded call id fails with 409 `tool_call_conflict`.

#### Scenario: Round checkpoints
- **WHEN** a tool round runs
- **THEN** the receipt gets phase `executing_tools` with `pending_tool_calls` (call id and tool) at the start, the step list and the shrinking pending list after each call, phase `waiting_final_response` once none is pending, and `tool_rounds` after the round; no provider response or tool output is kept for resuming, so an interrupted turn is rebuilt from its original input and these steps (CC3).

Evidence:
- `backend/coach/service.py:dialogue_effect_key`
- `backend/coach/structured_tool_round.py:CoachStructuredToolRoundService._execute_and_record`
- `backend/coach/structured_tool_round.py:CoachStructuredToolRoundService._execute_tool_call`
- `backend/coach/tool_call_metadata.py:structured_tool_call_metadata`
- `backend/coach/tool_replay.py:CoachStructuredToolReplayService.lookup`
- `backend/coach/tool_round_journal.py:CoachStructuredToolRoundJournal`
- `tests/test_coach_dialogue.py:test_interrupted_job_is_requeued_rerequested_and_runs_its_tool_once`
- `tests/test_coach_dialogue.py:test_rephrasing_request_metadata_does_not_duplicate_same_write`
- `tests/test_coach_tool_coverage.py:test_nutrition_entries_can_be_saved_read_and_deleted`
- `tests/test_coach_tool_replay.py:test_does_not_replay_effect_for_read_only_tool`
- `tests/test_coach_tool_replay.py:test_does_not_replay_failed_effect`
- `tests/test_coach_tool_replay.py:test_does_not_replay_missing_or_stale_draft`
- `tests/test_coach_tool_replay.py:test_replays_matching_call_id_and_rejects_changed_effect`
- `tests/test_coach_tool_replay.py:test_replays_successful_mutating_effect_with_different_call_id`
- `tests/test_coach_tool_round_journal.py`

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

#### Scenario: Twelve rounds and forty steps
- **WHEN** the model still requests tools after the 12th round
- **THEN** those calls are answered with `{"ok": false, "reason": "tool_step_limit_reached", "executed": false}`, the final request is sent with `tool_choice: none` and a notice that nothing further was saved or sent, and the answer ends with "Hinweis: Das Schrittlimit dieser Antwort wurde erreicht; möglicherweise ist nicht alles erledigt. Antworte mit „weiter“, um den Auftrag fortzusetzen."; the pending request stays resumable, and a model that answers after saving in the last round is not marked exhausted

#### Scenario: Invalid, surplus or unoffered call
- **WHEN** a call id is empty or longer than 200 characters, a new call id arrives when the turn already holds 40 steps, or the tool is not offered in this turn
- **THEN** the call fails with `invalid_tool_call` (400), `command_limit` (400) or `tool_scope_denied` (403) and has no effect; calls run one at a time in the order received

#### Scenario: Released turn
- **WHEN** a tool is called after the turn's command was closed by a stale release or by recovery
- **THEN** it is not executed and returns `{"ok": false, "status": "not_performed", "reason": "turn_released"}`, checked under the same lock as the release

Evidence:
- `backend/coach/structured_tool_round.py:COACH_TOOL_MAX_ROUNDS`
- `backend/coach/structured_tool_round.py:CoachStructuredToolRoundService`
- `backend/coach/tool_call_metadata.py:structured_tool_call_metadata`
- `backend/coach/tool_preparation.py:CoachStructuredToolPreparationService._request_is_paused`
- `backend/coach/turn_outcome.py:_BUDGET_EXHAUSTED_NOTE`
- `tests/test_coach_dialogue.py:test_clarification_blocks_writes_in_either_tool_order`
- `tests/test_coach_dialogue.py:test_tool_round_limit_submits_outputs_and_keeps_provider_selection`
- `tests/test_coach_structured_tool_round.py:test_exhausted_budget_tells_model_and_logs_only_counts`
- `tests/test_coach_structured_tool_round.py:test_released_turn_cannot_execute_tools_or_record_receipts`
- `tests/test_coach_tool_call_metadata.py:test_command_limit_allows_only_existing_replay_id`
- `tests/test_coach_turn_write_gate.py:test_resumed_turn_seeds_cap_from_existing_receipts`
- `tests/test_coach_write_gate.py:test_cap_is_25_and_counts_allowed_writes`
- `tests/test_coach_write_gate.py:test_denied_calls_do_not_count`

### Requirement: CA9 Truthful durable receipts and supported undo
The system SHALL persist actual tool outcomes and confirmed change references, distinguish local effects, approval-pending actions and sync jobs, and expose whole-turn undo only when every applied effect is fully tracked.

#### Scenario: Successful local change
- **WHEN** an authorized local write commits
- **THEN** the final receipt includes its effect and change summary, and the answer reflects the stored result rather than only the model's claim.

#### Scenario: Mixed effect or preview only
- **WHEN** a turn only stages/previews, awaits approval, or includes effects not fully tracked by history
- **THEN** its receipt row appears without a whole-turn undo: that undo is offered only when every applied write belongs to the fully tracked tools, which no plan write and not `delete_competition` do; supported individual undo/proposal flows remain distinct.

#### Scenario: Partial failure
- **WHEN** one effect succeeds and another unresolved step or final provider response fails
- **THEN** receipts retain successful effects, unresolved failures and queued job identities without treating unrelated success as repair of the failed step.

#### Scenario: Change summary
- **WHEN** a turn applied writes that changed records
- **THEN** the assistant message carries `change_summary` `{labels, undoable, undone_at, plan_check_notes?}`: `labels` holds each effect label once in order (plus a line per filled product and the remote deletions of a card-free sync), `undoable` is true only when every applied write is a fully tracked tool (flagged per tool in `openspec/COACH_TOOLS.md`) with change-history references, and `undone_at` stays null until the whole-turn undo restores the changes in one transaction or none; a staged draft, a preview, a call waiting for approval, a cancelled or failed call and an undo that is only proposed add no label

#### Scenario: Plan check notes in the receipt
- **WHEN** a plan write returned `plan_check_notes`
- **THEN** the summary keeps for each known finding code only `{code, dates, severity}` (`warning` for a blocking code or evidence severity `warning`, else `notice`) and the client shows "Warnung" or "Hinweis", a German label and an evidence text per code

Evidence: `backend/coach/change_receipts.py:change_summary`, `backend/coach/change_receipts.py:turn_changes`, `backend/coach/change_receipts.py:_FULLY_TRACKED_TOOLS`; `backend/coach/final_receipt.py:CoachFinalReceiptService`; `backend/coach/turn_failures.py:CoachTurnFailureService.persist`; `tests/test_coach_final_receipt.py:test_turn_changes_are_summarized_on_the_receipt_and_the_answer`; `tests/test_coach_dialogue.py:test_success_on_other_object_does_not_hide_failed_step`, `tests/test_coach_dialogue.py:test_summary_failure_preserves_effect_and_replays_receipt`; `tests/test_coach_change_receipts.py` (complete-effect undo eligibility contracts); `backend/coach/change_receipts.py:_plan_notes`, `public/coach.js:appendMessageChanges`, `public/coach.js:appendPlanNotes`; `tests/test_coach_change_receipts.py:test_a_card_free_sync_lists_its_remote_removals_without_turn_undo`, `tests/coach-turn-undo.test.cjs`.

### Requirement: CA10 Validated repair dependencies and exceptional approvals
The system SHALL reject malformed tools without partial effects, permit repairs within original authority, prevent remote steps from overtaking unresolved local failures, save meal/product definitions directly with a receipt, and retain the separate undo-preview flow.

#### Scenario: Repairable local validation failure
- **WHEN** a model corrects invalid arguments or stale local state after rereading current references
- **THEN** it can retry within the same authorized scope; a successful unrelated object or period does not erase an unresolved failure.

#### Scenario: Local prerequisite failed
- **WHEN** a requested local plan has not committed successfully
- **THEN** a dependent created/all-pending push is blocked instead of synchronizing a partial or unintended plan.

#### Scenario: Same tool repairs its failure
- **WHEN** a later call of the same tool succeeds in the turn
- **THEN** it repairs an earlier failure when target, period and the set of scope tokens are equal; or when the failure was `request_scope` or `request_object_missing` and both calls agree on arguments (without `expected_revision` and per-change payload hashes) and on target, period, constraints, `remote_write` and `sync_scope`; or when the failed step had no validated request and failed with `request_invalid`, `tool_arguments_invalid` or `plan_check_failed`; a `profile_conflict` is repaired only by a success on the same profile fields, and a successful `all_pending` plan sync repairs an earlier failed `selected` or `all_pending` plan sync of the same target

#### Scenario: Patch and replacement
- **WHEN** `apply_training_patch` failed with `request_invalid`, `tool_arguments_invalid` or `plan_check_failed` and `replace_training_plan` succeeds, or the reverse
- **THEN** the failure is repaired only when both calls have the same request binding (target, sorted scope, period, sorted constraints, `remote_write`, `sync_scope`) and the same new units (date, sport, name, description, duration, target, rationale and session-focus fields); a patch that edits existing units never matches

#### Scenario: Remote step after a failed local step
- **WHEN** a call with `remote_write: true` arrives while the turn holds an unresolved failed step of another non-read tool
- **THEN** it fails with 409 `request_dependency`; a `created` plan sync without a successfully created unit fails with 409 `plan_commit_required`, one whose created units changed since with 409 `planning_revision_conflict`, and an `all_pending` sync without pending units with 409 `no_pending_plan_entries`

#### Scenario: Meal/product definition save
- **WHEN** the athlete's own message asks the Coach to save a reusable meal or product definition
- **THEN** it is saved directly without an approval card, shown as a receipt with whole-turn undo (athlete decision on #2339); an unclear request gets a clarification question instead. A card created before this change can still be confirmed until it expires.

#### Scenario: Undo of a change
- **WHEN** the Coach calls `undo_training_change`
- **THEN** an undo of a creation, or one requested without `apply`, returns the preview with an `undo_change` proposal card (`confirmation_required` for a creation) and executes nothing; an undo of an update or delete with `apply: true` is applied at once without a card.

Evidence:
- `backend/coach/outcomes.py:unresolved_coach_steps`
- `backend/coach/planning_action_tools.py:CoachPlanningActionToolService._undo_training_change`
- `backend/coach/service.py:dialogue_plan_effect_key`
- `backend/coach/service.py:dialogue_request_binding_key`
- `backend/coach/service.py:dialogue_scope_repair_key`
- `backend/coach/tool_execution_service.py:CoachStructuredToolExecutionService.execute`
- `backend/coach/tool_preparation.py:CoachStructuredToolPreparationService._has_unresolved_steps_before_remote_write`
- `backend/coach/tool_preparation.py:CoachStructuredToolPreparationService._prepare_plan_sync`
- `backend/coach/tool_preparation.py:CoachStructuredToolPreparationService.prepare`
- `tests/test_coach_dialogue.py:test_failed_local_step_blocks_following_all_pending_push`
- `tests/test_coach_dialogue.py:test_invalid_arguments_can_be_repaired_in_same_dialogue`
- `tests/test_coach_dialogue.py:test_plan_replacement_does_not_resolve_different_workout_with_same_request`
- `tests/test_coach_dialogue.py:test_plan_replacement_does_not_resolve_invalid_patch_for_other_period`
- `tests/test_coach_dialogue.py:test_profile_conflict_repair_does_not_hide_an_independent_field_failure`
- `tests/test_coach_planning_action_tools.py:CoachPlanningActionToolServiceTests.test_create_undo_with_apply_is_only_offered_as_a_card`
- `tests/test_coach_planning_action_tools.py:CoachUndoToolPersistenceTests.test_update_undo_with_apply_still_runs_directly`
- `tests/test_coach_repair_outcomes.py:test_same_tool_success_only_repairs_same_target_scope_and_period`
- `tests/test_coach_tool_coverage.py:test_confirmed_product_is_saved_locally_through_authorized_coach_receipt`
- `tests/test_coach_tool_coverage.py:test_saved_meals_run_through_authorized_coach_and_receipts`
- `tests/test_coach_tool_coverage.py:test_undo_is_a_bound_preview_until_explicit_confirmation`
- `tests/test_coach_tool_preparation.py:test_remote_write_is_blocked_by_unresolved_local_failure`

### Requirement: CA11 Server-side plan checks before Coach plan writes
The system SHALL check the resulting future plan of every Coach tool write that creates or moves planned units against the plan rules, roll back a write that adds a new or riskier illness_hard finding the athlete did not accept, or a new strength_incomplete, focus_missing, hr_cap_invalid, template_missing or template_mismatch finding (which can never be accepted), and return the other new findings as notes with their evidence strength. Explicit athlete UI/API edits are not checked.

#### Scenario: Checked tools and rules
- **WHEN** `apply_training_patch`, `apply_training_changes`, `replace_training_plan`, `apply_workout_library_plan`, `commit_training_plan` or the approved `apply_adaptive_replan` writes planned units
- **THEN** the resulting plan is checked for run_spike (planned distance against the longest run of 30 days), load_spike and weekly_load_rise (planned load = duration x intensity^2 per sport, run and ride, against the stored M6 load of completed sessions), load_unknown, back_to_back_hard, strength_hard_same_day, missing_taper, illness_hard, intensity_distribution, leg_strength_before_key_session and leg_strength_frequency.

#### Scenario: Blocking violation
- **WHEN** a Coach plan write would add an unaccepted illness_hard finding, or a strength_incomplete, focus_missing, hr_cap_invalid, template_missing or template_mismatch finding
- **THEN** the transaction is rolled back, the tool result is a failure with the findings, and the model may correct the plan and call again in the same turn. For `apply_adaptive_replan` the check wraps only the local apply (its preview and next-message approval rules are unchanged); a block rolls the whole apply back, nothing is applied, the optional Intervals.icu illness sync does not run and the Coach tells the athlete; new notes come back as `plan_check_notes`.

#### Scenario: Missing required fields
- **WHEN** a Coach plan write creates, moves or changes a unit and adds a strength_incomplete, focus_missing, hr_cap_invalid, template_missing or template_mismatch finding
- **THEN** the transaction is rolled back and the tool result is a failure with the findings; `accept_plan_findings` cannot waive them. For `apply_adaptive_replan` such a gap passes only on a unit that already had it before the write.

#### Scenario: Notes
- **WHEN** a Coach plan write adds only run_spike, load_spike, weekly_load_rise, load_unknown, back_to_back_hard, strength_hard_same_day, missing_taper, intensity_distribution, leg_strength_before_key_session, leg_strength_frequency, calendar_load, all_day_event or template_scaled findings
- **THEN** the write is saved and the result carries them as `plan_check_notes` with evidence strength; a run_spike or load_spike is a notice up to 30 % and a warning beyond.

#### Scenario: All-day events
- **WHEN** a hard or long planned unit lies on a day with an all-day calendar event
- **THEN** a soft `all_day_event` note is returned (calendar markers still apply); the `planning_brief` lists all-day events per date with name and training-impact flags (`all_day_events`), and they are never subtracted from any time.

#### Scenario: Load notes
- **WHEN** a planned run or ride has a computed load (workout steps against the thresholds in the Coach precedence: locally confirmed zone configurations first, then the source-policy provider winners, Garmin values at most 180 days and Wahoo values at most 90 days old; Intervals.icu is never a threshold source; local values do not age)
- **THEN** it is compared with the highest-load session of its sport in 30 days (the stored card M6 session load that the charts and the Coach context show, a heart-rate based value marked less precise; a session without a stored value has an unknown load), and the planned weekly load per sport with the mean of the previous 3-4 weeks (notice above 20 %); "hard" is the one rule that adaptive replanning and race-proximity and [NO_INTENSITY] calendar checks share ([NO_INTENSITY] also blocks strength that is not explicitly easy) (`session_focus.is_hard`, #2083): a set session focus, then a hard step field, then at least 5 minutes of steps in zone 4+, then a planned intensity of at least 0.85, then only without readable steps a non-negated Z4-Z7 target or a hard word (interval, VO2, threshold/Schwelle, sweet spot, race/Rennen, test, HIIT, Tabata; tempo and sprints are not hard); heavy strength uses a set strength intensity first; missing or stale thresholds (no current provider value and no local configuration) or unparsed steps give a load_unknown note, never a number; all are non-blocking and labelled as extrapolated from distance/volume studies, not directly validated.

#### Scenario: Intensity distribution
- **WHEN** the planned run and ride time of a week (low/moderate/high from the workout steps, else for a unit without parseable steps from its numeric planned intensity with the progress-report zone mapping, else from its session focus (recovery, easy, endurance, long low; tempo, sweet_spot, threshold moderate; vo2max, anaerobic, race high) labelled approximate; steps always win; strength excluded, other unknown time reported as uncovered, never as low) lies more than 5 percentage points outside the reference range of the profile's `training_model`
- **THEN** a non-blocking `intensity_distribution` note with the shares, ranges, evidence and the time per basis (`basis_seconds`: steps, planned_intensity, session_focus) is returned; the intensity or focus fallback gives band time only, never a load number; weeks with less than 2 h or 60 % covered time are not judged, and the `planning_brief` carries the planned distribution. The running week combines its completed run and ride days (zone times of the weekly progress report; completed time without zone times is uncovered) with the remaining planned days, labelled "running week: completed + planned", under the same coverage minimums.

#### Scenario: Leg strength notes
- **WHEN** a planned strength unit has a leg session focus (`legs`, `full_body`, `plyometrics`, set or keyword-derived), or a completed one has executed strength sets (any leg exercise category is leg, only known non-leg categories are not, which wins over its focus), graded by strength intensity, else planned intensity (heavy from 0.85, moderate from 0.70), else RPE (8, 6), else text, else unknown
- **THEN** only the number and intensity of leg sessions count (no tonnage, no strength load; strength stays out of the endurance distribution), and non-blocking notes cover moderate or heavy leg strength less than about 24 h before a hard or long run/ride (heavy within 6 h of a hard session stays `strength_hard_same_day`), more than 3 leg or more than 2 heavy leg sessions in a week (the running week counts its completed strength days with the planned ones, labelled "running week: completed + planned"), and no leg session in 2+ full planned weeks when the profile or season phase expects strength; the `planning_brief` carries `strength` (sessions, leg sessions, leg sessions by intensity) per planned week and the same counts in completed strength weeks, plus `strength_progress` (per exercise the last six completed sessions with sets and top set, no estimated 1RM, trimmed first among the strength entries). The `planning_brief` also carries `season_phase` (base, build, peak, taper or transition, with weeks to the next A/B race), derived read-only from competition dates and priority by `backend/planning/season.py:target_phase` (the same derivation the strength expectation uses) and `unknown` without an A/B race; the plan playbook chooses volume, intensity, strength frequency and taper emphasis per phase for plan_week, plan_block and adjust_week (`tests/test_planning_season.py:TargetPhaseTests`).

#### Scenario: Planning brief budget and precedence
- **WHEN** the `planning_brief` would exceed 20,000 characters
- **THEN** whole entries are dropped in this order: the latest all-day-event days, the latest busy-minute days, planned sessions from the end, planned distribution weeks from the end, strength-progress exercises from the end, planned strength weeks from the end, and the oldest completed weeks last, never the JSON text; `lessons` and `season_phase` stay, an `omitted` note names the dropped counts, and its size appears in the context diagnostics. The plan playbook states the precedence illness, competitions and calendar markers, then science defaults, then the athlete's stated availability, and a deviation needs a reason.

#### Scenario: Acknowledged deviation
- **WHEN** the model resubmits with `accept_plan_findings` listing illness_hard, the write actually produced a blocking illness_hard finding, and the write gate's classifier confirms that the athlete's current message, or a short confirmation of the Coach's question about exactly this, explicitly asks to train despite the illness
- **THEN** the write is saved and the result carries the finding in `plan_check_notes`; the receipt persists only its safe structured summary.

#### Scenario: Unconfirmed deviation
- **WHEN** the write produced a blocking illness_hard finding that `accept_plan_findings` lists, but the classifier does not confirm an explicit athlete request, or fails or is unavailable
- **THEN** nothing is saved, the tool result is a failure with reason `illness_not_confirmed`, and the Coach asks one clarification question.

#### Scenario: Listing without a finding
- **WHEN** the model lists illness_hard in `accept_plan_findings` but the write produced no blocking illness_hard finding
- **THEN** the classifier is not asked and the write is saved normally.

#### Scenario: Visible plan notes
- **WHEN** a successful Coach plan write produces notes
- **THEN** its change receipt shows their dates, severity and evidence strength without provider text, and the Coach is instructed to justify rather than repeat or contradict them.

Evidence:
- `backend/coach/adaptive_apply.py:CoachAdaptiveApplyService._apply_checked`
- `backend/coach/change_receipts.py:change_summary`
- `backend/coach/tool_execution_service.py:CoachStructuredToolExecutionService.execute`
- `backend/coach/write_gate.py:illness_override_confirmed`
- `backend/planning/brief_budget.py:fit_brief`
- `backend/planning/intensity_distribution.py:distribution_findings`
- `backend/planning/leg_strength.py`
- `backend/planning/load_checks.py:completed_load`
- `backend/planning/load_checks.py:session_spikes`
- `backend/planning/load_checks.py:unknown_load`
- `backend/planning/load_checks.py:weekly_rises`
- `backend/planning/plan_checks.py:check_plan`
- `backend/planning/plan_guard_service.py:PlanGuardService.verify`
- `backend/planning/running_week.py`
- `backend/planning/session_focus.py:is_hard`
- `backend/planning/unit_intensity.py:unit_band`
- `public/coach.js:appendMessageChanges`
- `tests/coach-turn-undo.test.cjs`
- `tests/test_coach_adaptive_apply.py:AdaptiveApplyPlanGuardTests`
- `tests/test_coach_change_receipts.py:test_plan_notes_are_safe_and_only_attached_to_successful_writes`
- `tests/test_coach_write_gate.py:IllnessOverrideTests`
- `tests/test_intensity_distribution.py:RunningWeekTests`
- `tests/test_intensity_distribution.py:UnitFallbackTests`
- `tests/test_intensity_distribution.py`
- `tests/test_leg_strength.py:RunningWeekTests`
- `tests/test_leg_strength.py`
- `tests/test_load_checks.py:LocalThresholdPrecedenceTests`
- `tests/test_load_checks.py:SessionSpikeTests.test_reference_is_the_stored_m6_load_not_the_raw_power`
- `tests/test_load_checks.py`
- `tests/test_plan_guard_service.py:PlanGuardWriteTests.test_finding_without_confirmation_rolls_back`
- `tests/test_plan_guard_service.py:PlanGuardWriteTests.test_listing_without_a_finding_does_not_ask`
- `tests/test_plan_guard_service.py:PlanGuardWriteTests.test_violation_rolls_back_and_returns_findings`
- `tests/test_plan_guard_service.py:test_all_day_events_are_listed_per_date_and_trimmed_last_day_first`
- `tests/test_session_focus.py:HardRuleTests`

### Requirement: Coach sets the session focus
The Coach plan and template tools SHALL accept `session_focus` and `strength_intensity`, require them in strict plan payloads, validate them per sport on the server and list upcoming units' focus with its origin in `planning_brief.planned_sessions`.

#### Scenario: Plan write with focus
- **WHEN** the Coach stages, replaces or changes units with a focus valid for their sport
- **THEN** the focus is stored and an invalid one rejects the write.

Evidence: `backend/coach/tool_schemas.py`, `backend/planning/plan_guard_service.py`; `tests/test_coach_tool_schemas.py`, `tests/test_session_focus.py`.

### Requirement: Calendar plan notes
Coach plan writes SHALL report a non-blocking note for a long or hard unit on a heavily occupied day or overlapping an external event. Explicit calendar markers retain their existing enforcement.

#### Scenario: Calendar conflict
- **WHEN** a Coach plan write introduces a qualifying calendar conflict
- **THEN** the receipt includes a non-blocking note with safe evidence.

Evidence: `backend/planning/plan_checks.py:check_plan`, `backend/coach/change_receipts.py:change_summary`, `public/coach.js:appendPlanNotes`; `tests/test_plan_guard_service.py:test_calendar_conflict_is_saved_as_note`, `tests/coach-turn-undo.test.cjs`, `e2e/coach-plan-notes.spec.js`.

### Requirement: Coach structures strength sessions
The Coach plan and template tools SHALL accept `strength_structure` (strict plan payloads require it, null for free text), validate it on the server, and the plan playbook SHALL give progression rules: heavy strength 2 times per week in base and build, 1 in the competition phase, load or reps rising across weeks, a deload in the lighter week. Heavy and leg checks read the structure-derived intensity before words; only count and intensity of leg sessions are checked, never tonnage.

#### Scenario: Structured strength block
- **WHEN** the Coach plans weekly strength units with rising %1RM
- **THEN** each week's `strength_intensity` is derived from its structure and the plan checks use it.

Evidence: `backend/coach/tool_schemas.py`, `backend/coach/playbooks.py`; `tests/test_strength_structure.py`, `tests/test_coach_playbooks.py`.

### Requirement: Tool-specific bulk threshold
A Coach write tool MAY declare that it counts as a bulk change from a lower number of records than the general threshold; a call reaching that number SHALL need the athlete's confirmed bulk request in the tool's domain, failing closed like any bulk change. Filling product gaps counts as bulk from two products.

#### Scenario: Several products filled
- **WHEN** the Coach fills gaps of two or more products in one turn without a confirmed bulk request in the nutrition domain
- **THEN** the call is denied before any write, and the Coach asks the athlete first.

#### Scenario: One product filled
- **WHEN** the Coach fills gaps of one product, also with values from several origins or in a second attempt within the turn
- **THEN** no bulk confirmation is needed, because products count by id; the write still needs the athlete's own request and shows a receipt.

Evidence: `backend/coach/tool_specs.py:ToolSpec.bulk_from`, `backend/coach/tool_specs.py:ToolSpec.distinct_records`, `backend/coach/write_gate.py:record_ids`, `backend/coach/write_gate.py:call_impact`, `backend/coach/turn_write_gate.py:CoachTurnWriteGate`, `backend/coach/dialogue_action.py` (`local_nutrition_gaps`); `tests/test_coach_write_gate.py:test_many_records_in_one_turn_need_a_confirmed_bulk_change`, `tests/test_coach_dialogue.py` (gap scope cases).

### Requirement: CA12 Gate decision order and denial result
The write gate SHALL decide every non-read tool call in one fixed order and SHALL answer a denied call with a not-performed result that is neither executed nor recorded as a step.

#### Scenario: Decision order
- **WHEN** a call reaches the gate (after replay lookup and request classification)
- **THEN** the gate checks in this order: an ungated tool (`clarify_coach_request`, `cancel_coach_request`, `start_provider_refresh`) is allowed; a tool without a gate domain is `unknown_tool`; 25 allowed gated writes, counting those of the turn's stored receipts, end in `cap_exceeded`; a turn not started by a stored athlete message is `no_athlete_message`; a Garmin push follows its own wording rules (CA5); a retry of a Garmin or Wahoo job is judged by that job; an Intervals.icu write (an Intervals.icu domain tool, `remote_write: true` or the illness sync) needs the named sync (`remote_not_requested`); a delete, a whole-plan or bulk change and the approval of a previewed change need the classifier verdict of their domain (`impact_not_confirmed`, `approval_not_confirmed`); only then the call counts as a write with its records (counts per tool are in `openspec/COACH_TOOLS.md`)

#### Scenario: Denial result
- **WHEN** the gate denies a call
- **THEN** the model receives `{"ok": false, "status": "not_performed", "reason": "write_not_authorized", "gate_reason": <reason>, "message": <guidance>}` (`reason` is `write_cap_exceeded` for the cap) with fixed English guidance that nothing was saved or sent and the call must be neither repeated nor claimed, naming the provider for a remote denial; no step is recorded, so the denial becomes neither a failure nor a pending request, and a `coach_write_denied` warning with the tool (or `unknown`), domain and reason is logged

#### Scenario: Retry of a provider job
- **WHEN** `resolve_training_sync_conflict` names a `job_id` and its validated target is Garmin or Wahoo
- **THEN** a retry with `remote_write` not true (a read job) is allowed without sync wording and counts no write; a push job needs the athlete's own text to ask to send workouts to that provider, else it is denied with `remote_garmin_not_requested` or `remote_wahoo_not_requested`, and an allowed push retry counts one write and one record; a retry whose target is Intervals.icu keeps the Intervals.icu rule

Evidence:
- `backend/coach/structured_tool_round.py:CoachStructuredToolRoundService._execute_tool_call`
- `backend/coach/turn_write_gate.py:CoachTurnWriteGate.__init__`
- `backend/coach/turn_write_gate.py:CoachTurnWriteGate.denial`
- `backend/coach/write_gate.py:_check_garmin_write`
- `backend/coach/write_gate.py:_check_job_retry`
- `backend/coach/write_gate.py:check_write`
- `backend/coach/write_gate.py:record_count`
- `tests/test_coach_turn_write_gate.py:test_denied_write_does_not_execute_record_or_open_a_transaction`
- `tests/test_coach_turn_write_gate.py:test_resumed_turn_seeds_cap_from_existing_receipts`
- `tests/test_coach_write_gate.py:JobRetryTierTests.test_a_garmin_plan_push_retry_needs_garmin_to_be_named`
- `tests/test_coach_write_gate.py:JobRetryTierTests.test_a_read_retry_needs_no_sync_wording`
- `tests/test_coach_write_gate.py:JobRetryTierTests.test_a_wahoo_plan_push_retry_needs_wahoo_to_be_named`
- `tests/test_coach_write_gate.py:JobRetryTierTests.test_an_intervals_retry_keeps_the_intervals_gate`
- `tests/test_coach_write_gate.py:RegistryCoverageTests.test_every_non_read_registry_tool_is_gated_or_explicitly_ungated`
- `tests/test_coach_write_gate.py:WriteCapTests.test_cap_is_25_and_counts_allowed_writes`

### Requirement: CA13 Impact classifier request
The impact classifier SHALL be one stateless model request with a strict JSON schema, fed only the athlete's text, the tail of the previous Coach message and the original text of a retried request, and its verdict SHALL never grant a remote write or an Intervals.icu sync.

#### Scenario: Classifier request
- **WHEN** a delete, whole-plan, bulk or approval call, or an `illness_hard` finding the athlete is said to accept, needs a verdict
- **THEN** one request goes to the turn's own model on its own transport (OpenAI or Claude) with reasoning effort `low`, at most 1,024 output tokens and nothing stored at the provider; its input is compact JSON of `athlete_message` (at most 2,000 characters), `previous_assistant_message` (its last 1,200 characters) and, when a pending request has one, `original_athlete_request` (at most 2,000 characters); the schema `write_impact` is `{requests: [{domain, delete, bulk}], accepts_proposal, accepts_illness_override}` with the domains planning, profile, competition, checkin, nutrition and undo; the instruction text is `CLASSIFIER_INSTRUCTIONS`, normative like the modules of CC9c

#### Scenario: Verdict use
- **WHEN** the verdict is read
- **THEN** it is requested at most once per turn and reused; domains outside the six are dropped; only a boolean `true` accepts a proposal or the illness override; a delete or bulk confirmation holds only for its own domain

#### Scenario: Failure
- **WHEN** no model is set, the request fails or its output is no valid JSON of that shape
- **THEN** nothing is confirmed and the gate denies the call

Evidence: `backend/coach/turn_write_gate.py:build_impact_classifier`, `backend/coach/write_gate.py:CLASSIFIER_INSTRUCTIONS`, `backend/coach/write_gate.py:CLASSIFIER_SCHEMA`, `backend/coach/write_gate.py:classifier_input`, `backend/coach/write_gate.py:parse_verdict`, `backend/coach/structured_tool_round_assembly.py:CoachStructuredToolRoundAssembly.write_gate_service`; `tests/test_coach_write_gate.py:OpenAIClassifierTests.test_payload_uses_strict_schema_without_remote_domain`, `tests/test_coach_write_gate.py:OpenAIClassifierTests.test_input_is_bounded`, `tests/test_coach_write_gate.py:OpenAIClassifierTests.test_invalid_output_confirms_nothing`, `tests/test_coach_write_gate.py:OpenAIClassifierTests.test_only_a_boolean_true_accepts_the_proposal`, `tests/test_coach_write_gate.py:OpenAIClassifierTests.test_transport_error_fails_closed_through_the_gate`, `tests/test_coach_write_gate.py:DestructiveTierTests.test_classifier_runs_once_per_turn_and_only_for_high_impact`.

### Requirement: CA14 Request classification before the write gate
The system SHALL classify every non-read dialogue call from its validated `_request` and live local state before the gate runs: it decides whether the step is a local action, a remote write or a provider refresh, checks target, sync scope, scope tokens and period, and refuses a mismatch without executing the tool.

#### Scenario: Step kinds
- **WHEN** a call is classified
- **THEN** it is a remote write for `start_intervals_plan_sync`, `push_strength_to_garmin`, `sync_competitions`, `sync_nutrition`, `apply_adaptive_replan` with `sync_illness_to_intervals`, and `resolve_training_sync_conflict` retrying a `plan_push`, `competition_push` or `nutrition_sync` job; a provider refresh for `start_provider_refresh` and a retry of any other job; otherwise a local action; a turn with mutations withheld fails every one with 403 `intent_scope_denied`, and a retry naming both `local_id` and `job_id` fails with 400 `tool_arguments_invalid`

#### Scenario: Target and remote declaration
- **WHEN** the envelope does not fit the step kind
- **THEN** a remote write without `remote_write: true`, without the writing provider as `target` (Garmin for the Garmin push, the retried job's provider for a retry, else Intervals.icu) or without the scope token `<provider>_sync` fails with 403 `remote_scope_denied` "Für diesen Schritt fehlt der <Provider>-Synchronisierungsauftrag."; `remote_write` that disagrees with the step kind, or a `target` other than `local` on a local action, fails with 403 `request_target` "Das Ziel passt nicht zu diesem Auftragsschritt."; a refresh whose target is no refresh provider or whose scope lacks `<target>_refresh` fails with 403 `request_target` "Der Datenabruf benötigt ein eindeutiges Anbieterziel."; a retry whose target differs from the job's provider fails with 403 `request_target`

#### Scenario: Object tokens
- **WHEN** the scope tokens are checked
- **THEN** a token `<kind>:<id>` of the kinds planned_unit, library_workout, training_plan, competition, artifact, adaptive_replan, change, sync_job, nutrition_template or nutrition_product must name an existing row (409 `request_object_missing` "Das ausgewählte Objekt ist nicht mehr verfügbar. Lies den aktuellen Stand erneut."; an archived plan named by `replace_training_plan` fails with 409 `request_object_missing` "Dieser Plan ist archiviert. Wähle den aktuellen Plan oder erstelle einen neuen."); any other token must be one of local_profile, local_plan, local_template, local_competitions, local_checkin, activity_feedback, adaptive_replan, intervals_sync, garmin_sync, wahoo_sync, local_nutrition, local_nutrition_product, local_nutrition_gaps, local_equipment, local_activity_session or `<target>_refresh` for a refresh provider (400 `request_scope` "Der Auftrag enthält einen ungültigen Objektbezug."); the server adds `nutrition_template:<id>` from the `id` argument of the two template tools

#### Scenario: Planning period
- **WHEN** `apply_training_patch`, `apply_training_changes`, `replace_training_plan`, `stage_training_plan`, `commit_training_plan` or `apply_workout_library_plan` is called
- **THEN** the envelope needs a period that does not end before today (400 `request_period` "Für die Planung fehlt ein gültiger zukünftiger Zeitraum."), its start is moved to today, every new or moved unit date and every changed unit's current date must lie in it (403 `request_period` "Die Änderung liegt außerhalb des beauftragten Zeitraums."), every changed unit needs its own `planned_unit:<id>` token and must exist (404 `request_object_missing` "Die ausgewählte Einheit fehlt."), and a draft to commit must come from an athlete message among the source ids (409 `artifact_conversation_conflict`)

#### Scenario: Sync scope values
- **WHEN** a plan sync lacks `sync_scope` `created`, `selected` or `all_pending`, a repair is not `selected` with a period, or a Garmin push is not `selected`
- **THEN** it fails with 400 `request_sync` "Der Umfang der Synchronisierung fehlt." or "Reparatur-Sync benötigt eine Auswahl und einen Zeitraum."; a repair entry outside the period fails with 403 `request_period`, a Garmin entry without `local_id` with 400 `request_scope` "Jede Einheit benötigt ihre local_id."

#### Scenario: Envelope cannot be validated
- **WHEN** the `_request` check of CA2 fails
- **THEN** the tool result is 400 `request_invalid` "Der Schritt benötigt einen gültigen Bezug zum aktuellen Auftrag. Prüfe die Werkzeugargumente erneut." with the inner reason as `validation_reason`; the source ids may also name the athlete message that owns a stored plan draft, though it is older than the bounded dialogue

Evidence: `backend/coach/dialogue_action.py:CoachDialogueActionService.classify`, `backend/coach/dialogue_action.py:CoachDialogueActionService._validate_target`, `backend/coach/dialogue_action.py:CoachDialogueActionService._validate_scope_tokens`, `backend/coach/dialogue_action.py:CoachDialogueActionService._apply_planning_scope`, `backend/coach/dialogue_action.py:CoachDialogueActionService._apply_sync_scope`, `backend/coach/dialogue_action.py:broad_scope_tokens`, `backend/coach/dialogue_plan_scope.py:CoachDialoguePlanScopeService.validate`; `tests/test_coach_dialogue.py:test_dialogue_action_service_enforces_live_request_and_remote_boundaries`, `tests/test_coach_dialogue_plan_scope.py`, `tests/test_coach_plan_sync_card_flow.py:test_a_push_retry_declared_as_a_read_is_denied`.

### Requirement: CA15 Scope token each tool requires
The system SHALL execute a non-read tool only when its classified scope holds the token its owner requires, and otherwise fail with 403 `intent_scope_denied` before the domain service runs.

#### Scenario: Required tokens
- **WHEN** a tool executes
- **THEN** one of the listed tokens must be in the scope (`and` means both): `update_profile` local_profile; `save_checkin` local_checkin; `save_activity_feedback` and `delete_activity_feedback` activity_feedback; `save_competition` `competition:<id>` when the payload names a competition, else local_competitions; `delete_competition` `competition:<id>`; `save_equipment`, `assign_activity_equipment` and `log_equipment_maintenance` local_equipment; the three session tools local_activity_session; the diary tools local_nutrition; `log_nutrition_template` and `delete_nutrition_template` local_nutrition and `nutrition_template:<id>`; `save_nutrition_template` `nutrition_template:<id>` for an existing template, else local_nutrition; `save_nutrition_product` `nutrition_product:<id>` for an existing product, else local_nutrition_product; `fill_nutrition_product_gaps` local_nutrition_gaps

#### Scenario: Planning and history tokens
- **WHEN** a planning, adaptive or undo tool executes
- **THEN** `stage_training_plan` needs local_plan; `commit_training_plan` `artifact:<id>`; `replace_training_plan` local_plan or exactly one `training_plan:<id>` (more than one fails with 400 `intent_scope_denied`); `apply_training_patch` `planned_unit:<id>` for each changed unit and local_plan for new units; `manage_training_templates` local_template to create, otherwise `library_workout:<id>` or local_template; `apply_workout_library_plan` `library_workout:<id>` per entry or local_plan; `update_training_plan` `training_plan:<id>`; `preview_adaptive_replan` adaptive_replan; `apply_adaptive_replan` `adaptive_replan:<id>` (and, for the illness sync, target Intervals.icu with intervals_sync); `undo_training_change` `change:<id>`

#### Scenario: Provider tokens
- **WHEN** a sync or refresh tool executes
- **THEN** `start_provider_refresh` needs `<target>_refresh`; `start_intervals_plan_sync` intervals_sync plus the unit groups its plan-sync owner derives from the entries; `push_strength_to_garmin` garmin_sync and `planned_unit:<id>` for each entry; `sync_competitions` intervals_sync and local_competitions; `sync_nutrition` intervals_sync (its owner accepts local_nutrition or intervals_sync, and the remote target needs intervals_sync); `resolve_training_sync_conflict` `competition:<id>` with a `local_id`, or with a `job_id` `sync_job:<id>` and `<provider>_sync` for a push job, else `<provider>_refresh`; `get_sync_job` `sync_job:<id>` unless the job was started in this turn (preparation grants it, see CP6)

Evidence:
- `backend/coach/adaptive_apply.py:CoachAdaptiveApplyService.apply`
- `backend/coach/athlete_record_tools.py:CoachAthleteRecordToolService._nutrition_scope`
- `backend/coach/athlete_record_tools.py:CoachAthleteRecordToolService.execute`
- `backend/coach/authorization.py:require_coach_scope`
- `backend/coach/dialogue_action.py:CoachDialogueActionService._apply_nutrition_object_scope`
- `backend/coach/library_plan_tools.py`
- `backend/coach/plan_artifact_tools.py:CoachPlanArtifactToolService.execute`
- `backend/coach/planning_action_tools.py:CoachPlanningActionToolService.execute`
- `backend/coach/planning_change_tools.py:CoachPlanningChangeToolService._replace_training_plan`
- `backend/coach/profile_update.py:CoachProfileUpdateService.apply`
- `backend/coach/sync_tools.py:CoachSyncToolService.execute`
- `backend/coach/training_patch.py:CoachTrainingPatchService.apply`
- `backend/coach/training_template_tools.py`
- `tests/test_coach_athlete_record_tools.py:test_meal_template_tools_require_operation_and_nutrition_scope`
- `tests/test_coach_athlete_record_tools.py:test_operation_and_scope_denials_block_each_tool`
- `tests/test_coach_planning_change_tools.py:test_apply_rejects_update_outside_planned_unit_scope`
- `tests/test_coach_sync_tools.py:test_garmin_push_needs_the_garmin_target_scope_and_approved_entries`

### Requirement: CA16 What a remote write binds
The system SHALL bind every Coach remote write to stored local state before it runs, whether the athlete's named sync runs it without a card or an explicit Garmin removal asks on a card, and SHALL execute only the stored arguments, never the model's selection.

#### Scenario: Intervals.icu plan sync
- **WHEN** a plan sync is prepared
- **THEN** its entries carry the payload hash of each stored unit; `all_pending` lists the library entries and planned units in sync state local, sync_error, remote_missing or conflict that are not before the export horizon; `created` lists the units created in this turn; a sync of `selected`, `created` or `changed` units also carries, while the sync stays within the library bulk limit of 100 entries, the Intervals.icu events of deleted or replaced units as removals labelled "Wird bei Intervals.icu entfernt"; more than 5,000 rows fail with 409 "Der Plan enthält zu viele Sync-Einheiten für eine Freigabe."; on a card the model's unit tokens are replaced by tokens of exactly the listed units, a card-free run keeps the request's own unit scope and adds tokens only for the server's removals

#### Scenario: Garmin strength push
- **WHEN** a Garmin push is prepared
- **THEN** 1 to 28 distinct existing planned units are required (400 `invalid_job_request` "Wähle 1 bis 28 Einheiten.", 400 "Eine Einheit darf nur einmal ausgewählt werden.", 409 `request_object_missing`), each upload carries its stored payload hash, and Garmin workouts of units that no longer exist are appended as removals up to the 28-entry limit; card rows read "An Garmin", "Von Garmin entfernen" or "Wird bei Garmin entfernt"

#### Scenario: Competition, nutrition and illness-pause syncs
- **WHEN** one of these syncs is prepared
- **THEN** the competition sync stores a manifest with a SHA-256 per stored row and lists name, date and sport, a deletion as "Wird bei Intervals.icu entfernt" or "Remote-Wettkampfeintrag löschen", and a row changed since fails with 409 "Der Wettkampfbestand hat sich vor der Freigabe geändert."; the nutrition sync needs exactly one of `date` and `pending_limit` (400 "Wähle ein Datum oder ausstehende Tage.") and takes its manifest from the stored diary; the illness-pause sync takes only the adjustment id from the model, requires it to name the latest stored preview with an unapproved pause and stores that pause's dates (409 otherwise)

#### Scenario: Execution of an approved card
- **WHEN** an approved card executes
- **THEN** its payload is validated before the token is consumed (every source message is still stored for the same conversation and session and one belongs to the card's turn, else 409); a remote write returns the queue result with `sync_job_ids` and a failure leaves the card `used`, so a new card is needed; a legacy local write returns its result with `status: applied` and a failed validation returns the card to `ready`

Evidence:
- `backend/coach/proposal_creation.py:_adaptive_approval_arguments`
- `backend/coach/proposal_creation.py:_approved_garmin_arguments`
- `backend/coach/proposal_creation.py:_approved_plan_sync_arguments`
- `backend/coach/proposal_creation.py:_check_approval_row_limit`
- `backend/coach/proposal_creation.py:_competition_approval_details`
- `backend/coach/proposal_creation.py:_nutrition_approval_arguments`
- `backend/coach/proposal_creation.py:_with_intervals_leftovers`
- `backend/coach/proposal_creation.py:CoachProposalCreationService.prepare_remote_write`
- `backend/coach/proposal_execution.py:CoachProposalExecutionService._dispatch_action`
- `backend/coach/proposal_execution.py:CoachProposalExecutionService._validate_remote_write_provenance`
- `backend/planning/library.py:LIBRARY_BULK_MAX_ENTRIES`
- `tests/test_coach_plan_sync_card_flow.py:test_unit_tokens_from_the_model_never_widen_the_card`
- `tests/test_coach_proposal_creation.py:test_all_pending_plan_approval_freezes_and_displays_pending_entries`
- `tests/test_coach_proposal_creation.py:test_competition_remote_write_binds_dirty_rows_and_tombstones_to_approval`
- `tests/test_coach_proposal_creation.py:test_illness_sync_proposal_is_built_from_the_stored_preview`
- `tests/test_coach_proposal_execution.py:test_local_write_validation_conflict_keeps_approved_proposal_retryable`

### Requirement: CA17 The answer is corrected against the recorded effects
The system SHALL correct the model's final text when it disagrees with the turn's recorded effects, and SHALL store only a compact final receipt.

#### Scenario: Save claim without a write
- **WHEN** the answer says in the first person that something was saved ("ich habe … erfasst, gespeichert, eingetragen, angelegt, hinzugefügt") and the turn recorded no effect, failure, question, waiting approval or incomplete answer
- **THEN** the text stays and "Hinweis: In dieser Antwort wurde nichts gespeichert. Bitte sende die Anfrage erneut, wenn etwas erfasst werden soll." is appended

#### Scenario: Queued remote job, waiting approval or unresolved failure
- **WHEN** the turn queued a provider job, waits for a card or holds an unresolved failed step
- **THEN** the authoritative lines follow the text: "Synchronisationsauftrag <id>: <status>. Remote-Abschluss ist bestätigt|noch nicht bestätigt." for a remote write, and for a waiting card "Die Remote-Änderung wartet auf deine ausdrückliche Freigabe. Prüfe den Aktionsvorschlag, bevor sie ausgeführt wird."; a remote write that is not confirmed completed replaces the model's prose by "Lokal gespeichert beziehungsweise ausgeführt: …" and these lines; an unresolved failure replaces it by "Ein Teil des Auftrags konnte noch nicht ausgeführt werden." (without effects "Der Auftrag konnte noch nicht ausgeführt werden.") with the failure lines and "Gespeichert beziehungsweise beauftragt: …"; a finished read-only refresh keeps the analysis and adds a note when it was partial or limited to the catch-up window

#### Scenario: Incomplete or empty answer
- **WHEN** the model stopped for length or returned no text
- **THEN** an incomplete answer gets "Die Antwort wurde nicht abgeschlossen. Bitte den Coach um Fortsetzung bitten." and stays resumable; an empty answer becomes "Ergebnis: " plus the effect labels, or "Die Antwort konnte nicht abgeschlossen werden. Bitte versuche es erneut." without effects

#### Scenario: Compact final receipt
- **WHEN** a turn finishes
- **THEN** the stored receipt keeps statuses, identifiers, proposed actions and undo references, cuts text values to 500 characters, id lists to 50 and food lookup results to 24 groups of 3 matches, and holds every full tool result only while the turn is open

Evidence: `backend/coach/turn_outcome.py:CoachStructuredOutcomeService.finalize`, `backend/coach/turn_outcome.py:_unbacked_save_notice`, `backend/coach/turn_outcome.py:_queued_message`, `backend/coach/turn_outcome.py:_approval_message`, `backend/coach/turn_outcome.py:_failure_message`, `backend/coach/turn_outcome.py:_fallback_message`, `backend/coach/receipt_compaction.py:compact_receipt`; `tests/test_coach_turn_outcome.py:test_save_claim_without_a_write_step_is_flagged`, `tests/test_coach_turn_outcome.py:test_queued_remote_job_overrides_false_model_completion_claim`, `tests/test_coach_receipt_compaction.py:test_keeps_status_ids_proposed_action_and_drops_bulk`.

### Requirement: CA18 Tool failure result
The system SHALL turn every failed tool call into a result the model can act on, record it as a failed step, and never pass the text of an unexpected error to the model or the log.

#### Scenario: Result shape
- **WHEN** a tool call fails with an application error
- **THEN** the result is `{"ok": false, "reason", "error"}` with the error's reason and German message, plus `validation_reason` when it matches `request_[a-z_]{1,72}` `findings` when the error carries a list (a `template_mismatch` finding's evidence names the template's and the unit's structure, and both sports when they differ), and `required_scope` (the scope tokens one of which the call's `_request` lacked) after an `intent_scope_denied`, for the model only; an error without a reason gets `tool_arguments_invalid` for status 400, else `tool_failed`; a value, type or key error becomes `{"ok": false, "reason": "tool_arguments_invalid", "error": "Die Werkzeugargumente sind ungültig. Prüfe das Schema und den aktuellen Zustand und korrigiere den Aufruf."}`

#### Scenario: Unknown or unoffered tool
- **WHEN** the tool is not offered in this turn or the dispatcher knows no owner
- **THEN** the result carries `tool_scope_denied` (403 "Dieses Werkzeug steht in diesem Auftrag nicht zur Verfügung.") or `unknown_coach_tool` (400 "Unbekanntes Coach-Werkzeug."); a call denied by the write gate records no step and does not count toward the 40 steps

#### Scenario: Diagnostics
- **WHEN** a step fails
- **THEN** the stored step also holds `diagnostic_error` with the error class and at most the last eight application call frames (file, function, line) without message text, and the `coach_tool_failed` log names the tool only when it is a registered tool, else `unknown`

Evidence: `backend/coach/tool_failures.py:CoachStructuredToolFailureService.project`, `backend/coach/turn_failures.py:coach_error_metadata`, `backend/coach/tool_dispatch.py`, `backend/coach/structured_tool_round.py:CoachStructuredToolRoundService._execute_tool_call`; `tests/test_coach_tool_failures.py:test_non_app_error_uses_generic_text_and_does_not_leak_exception`, `tests/test_coach_tool_dispatch.py:test_unknown_name_has_stable_client_error_without_mutation`.

### Requirement: CA19 Stable reasons of rejected local Coach writes
The system SHALL apply `update_profile`, `apply_training_patch`, `manage_training_templates`, `apply_workout_library_plan`, `apply_adaptive_replan` and `undo_training_change` as all-or-nothing local changes and SHALL answer a rejected call with the stable reason of the listed rule. Parameters are in `openspec/COACH_TOOLS.md`.

#### Scenario: Profile update
- **WHEN** `update_profile` carries no change or more changes than the profile has fields, a change that is not exactly `{field, expected_value, value}`, an unknown or read-only field, a field twice, or a value over 4,000 characters
- **THEN** it fails with 400 `tool_arguments_invalid`; an `expected_value` that differs from the stored value fails with 409 `profile_conflict` "Das Profil wurde inzwischen geändert. Lies es erneut und ergänze den aktuellen Stand." and nothing is applied

#### Scenario: Training patch
- **WHEN** `apply_training_patch` is called
- **THEN** `changes` and `workouts` together must hold 1 to 366 items (400 `change_limit` "Der Änderungssatz ist leer oder zu groß."), no unit may repeat (400 `invalid_change`), at most one plan may be named (400 `intent_scope_denied`), `expected_revision` must equal the planning revision (409 `planning_revision_conflict`) and a new unit must not collide with the calendar (409 `plan_date_conflict` "Für den <Datum> besteht ein Kalenderkonflikt."); new units form a plan named by `plan_name`, or "Coach-Plan" when the request has constraints, and the request constraints are stored for that plan and for the plans of changed units, under a named plan only for that plan

#### Scenario: Templates and scheduling
- **WHEN** `manage_training_templates` or `apply_workout_library_plan` is called
- **THEN** the first needs 1 to 28 items whose action is create (default), update, archive, restore or delete (400 `template_limit`, 400 `invalid_template_action`); the second refuses a template that lacks strength structure, session focus or a readable heart-rate cap with 409 `library_template_incomplete` naming the template, its id and the missing fields

#### Scenario: Adaptive apply and undo
- **WHEN** `apply_adaptive_replan` or `undo_training_change` is called
- **THEN** the adjustment must be the latest stored preview (409 "Bitte zuerst die aktuelle adaptive Planungsvorschau erstellen.") and the current athlete message the first athlete message after the one that published it and among the source ids (403 `adaptive_approval_required`); an illness sync without the named Intervals.icu target and `intervals_sync` fails with 403 `intent_scope_denied`; the plan check wraps only the local apply, where findings a unit already had stay notes; an undo of an update or delete with `apply: true` returns the service result (`status: undone`), the undo of a creation or a call without `apply` returns the preview and an `undo_change` card

Evidence: `backend/coach/profile_update.py:CoachProfileUpdateService.apply`, `backend/coach/training_patch.py:CoachTrainingPatchService.apply`, `backend/coach/training_template_tools.py`, `backend/coach/library_plan_tools.py:require_complete_template`, `backend/coach/adaptive_apply.py:CoachAdaptiveApplyService.apply`, `backend/coach/planning_action_tools.py:CoachPlanningActionToolService._undo_training_change`; `tests/test_coach_dialogue.py:test_profile_patch_conflict_is_atomic_and_can_be_repaired`, `tests/test_coach_training_patch.py:test_named_plan_stores_constraints_only_under_that_plan`, `tests/test_coach_adaptive_apply.py:test_only_the_first_athlete_message_after_the_preview_can_approve`, `tests/test_coach_planning_action_tools.py:CoachPlanningActionToolServiceTests.test_create_undo_with_apply_is_only_offered_as_a_card`.
