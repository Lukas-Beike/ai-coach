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
The system SHALL require the athlete's named sync request for the step's own provider before a remote-write step (Intervals.icu wording for Intervals.icu, Garmin or watch wording for a Garmin push), preserve a separate per-step remote target/scope, and route remote changes through the implemented explicit approval proposal.

#### Scenario: Local save only
- **WHEN** the athlete requests local plan, competition or meal saving without naming remote synchronization
- **THEN** no Intervals.icu write is authorized by that request; provider refresh remains a provider read rather than a workout push.

#### Scenario: Explicit named sync
- **WHEN** the athlete names an unnegated Intervals.icu synchronization or accepts the directly preceding concrete sync offer
- **THEN** the step still needs the matching provider target, sync scope and remote-write declaration; its proposed effect is shown for explicit approval before dispatch.

#### Scenario: Negated sync or classifier-only approval
- **WHEN** sync is negated, merely discussed, or supplied only by an impact-classifier verdict
- **THEN** the remote write is denied; a local or bulk confirmation cannot grant remote permission.

#### Scenario: Garmin strength push
- **WHEN** the athlete's own message names Garmin or the watch with a transfer verb, or accepts the directly preceding Garmin offer
- **THEN** `push_strength_to_garmin` may propose the selected strength units with target `garmin` and scope `garmin_sync`; the card binds each unit's stored payload hash, and only its approval queues the Garmin `plan_push` job. Intervals.icu wording never grants it, a Garmin push or removal request never grants an Intervals.icu write, an upload entry needs the athlete's own push wording and a removal entry the athlete's own Garmin removal wording (no classifier is asked).

Evidence: `backend/coach/write_gate.py:remote_requested`, `backend/coach/write_gate.py:build_turn_authority`, `backend/coach/write_gate.py:check_write`; `backend/coach/tool_execution_service.py:CoachStructuredToolExecutionService.execute`; `backend/coach/proposal_creation.py:CoachProposalCreationService.create_remote_write`; `tests/test_coach_write_gate.py:test_named_sync_requests_allow_remote_tools_without_the_classifier`, `tests/test_coach_write_gate.py:test_unnamed_negated_or_asked_syncs_are_denied`, `tests/test_coach_write_gate.py:test_the_classifier_never_grants_the_illness_sync_to_intervals`, `tests/test_coach_write_gate.py:GarminTierTests`; `backend/coach/write_gate.py:garmin_requested`, `backend/coach/proposal_creation.py:_approved_garmin_arguments`, `backend/coach/sync_tools.py:CoachSyncToolService._push_strength_to_garmin`; `tests/test_coach_tool_coverage.py:test_garmin_strength_push_is_bound_to_the_stored_units`, `tests/test_coach_sync_tools.py:test_garmin_push_needs_the_garmin_target_scope_and_approved_entries`; `tests/test_coach_tool_coverage.py:test_competition_lifecycle_syncs_only_after_explicit_followup`.

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
- **THEN** the card is rejected unless every listed unit exists locally, and the stored intent grants the object scope of exactly those units, so approving the card authorizes what the athlete saw; a model call without an approved card grants nothing.

#### Scenario: Unknown execution outcome in the client
- **WHEN** execute was sent but no definite response arrives
- **THEN** the client blocks blind repeat execution and rereads proposal status before offering another attempt; a consumed token is treated as an outcome to inspect rather than proof of failure.

Evidence: `backend/coach/proposal_execution.py:CoachProposalExecutionService._load_ready_action`, `backend/coach/proposal_execution.py:CoachProposalExecutionService._consume_action`, `backend/coach/proposal_execution.py:CoachProposalExecutionService._validate_remote_write_provenance`; `backend/coach/proposal_creation.py:_approved_remote_arguments`, `backend/coach/proposal_creation.py:_card_authorized_intent`; `tests/test_coach_plan_sync_card_flow.py:ApprovedCardAuthorizesItsUnitsTests`; `tests/test_coach_proposal_execution.py:test_foreign_session_wrong_hash_and_expiry_cannot_consume_or_dispatch`, `tests/test_coach_proposal_execution.py:test_competing_execution_dispatches_only_once`; `public/coach.js:reconcileCoachActionProposal`; `tests/frontend-write-safety.test.cjs:a lost execute response keeps the action locked and is not reported as a failed confirmation`, `tests/frontend-write-safety.test.cjs:reconcile re-enables a proposal the server still reports as confirmable`; `tests/test_coach_tool_coverage.py:test_all_pending_approval_does_not_expand_to_units_added_after_preview`; `tests/test_coach_dialogue.py:test_sync_followup_failure_distinguishes_coach_interruption_and_keeps_job`.

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

### Requirement: CA11 Server-side plan checks before Coach plan writes
The system SHALL check the resulting future plan of every Coach tool write that creates or moves planned units against the plan rules, roll back only a new unacknowledged illness_hard finding, and return the other new findings as notes with their evidence strength. Explicit athlete UI/API edits are not checked.

#### Scenario: Checked tools and rules
- **WHEN** `apply_training_patch`, `apply_training_changes`, `replace_training_plan`, `apply_workout_library_plan`, `commit_training_plan` or the approved `apply_adaptive_replan` writes planned units
- **THEN** the resulting plan is checked for run_spike (planned distance against the longest run of 30 days), load_spike and weekly_load_rise (load = duration x intensity^2 per sport, run and ride), load_unknown, back_to_back_hard, strength_hard_same_day, missing_taper, illness_hard, intensity_distribution, leg_strength_before_key_session and leg_strength_frequency.

#### Scenario: Blocking violation
- **WHEN** a Coach plan write would add an illness_hard finding
- **THEN** the transaction is rolled back, the tool result is a failure with the findings, and the model may correct the plan and call again in the same turn. For `apply_adaptive_replan` the check wraps only the local apply (its preview and next-message approval rules are unchanged); a block rolls the whole apply back, nothing is applied, the optional Intervals.icu illness sync does not run and the Coach tells the athlete; new notes come back as `plan_check_notes`.

#### Scenario: Notes
- **WHEN** a Coach plan write adds only run_spike, load_spike, weekly_load_rise, load_unknown, back_to_back_hard, strength_hard_same_day, missing_taper, intensity_distribution, leg_strength_before_key_session, leg_strength_frequency, calendar_load or all_day_event findings
- **THEN** the write is saved and the result carries them as `plan_check_notes` with evidence strength; a run_spike or load_spike is a notice up to 30 % and a warning beyond.

#### Scenario: All-day events
- **WHEN** a hard or long planned unit lies on a day with an all-day calendar event
- **THEN** a soft `all_day_event` note is returned (calendar markers still apply); the `planning_brief` lists all-day events per date with name and training-impact flags (`all_day_events`), and they are never subtracted from any time.

#### Scenario: Load notes
- **WHEN** a planned run or ride has a computed load (workout steps against the thresholds in the Coach precedence: locally confirmed zone configurations first, then the source-policy provider winners, Garmin values at most 180 days and Wahoo values at most 90 days old; Intervals.icu is never a threshold source; local values do not age)
- **THEN** it is compared with the highest-load session of its sport in 30 days (ride Normalized Power over FTP, run grade-adjusted pace over threshold pace, heart-rate fallback marked less precise), and the planned weekly load per sport with the mean of the previous 3-4 weeks (notice above 20 %); "hard" uses a set session focus, then the computed intensity, then text and keyword-derived focus; heavy strength uses a set strength intensity first; missing or stale thresholds (no current provider value and no local configuration) or unparsed steps give a load_unknown note, never a number; all are non-blocking and labelled as extrapolated from distance/volume studies, not directly validated.

#### Scenario: Intensity distribution
- **WHEN** the planned run and ride time of a week (low/moderate/high from the workout steps, else for a unit without parseable steps from its numeric planned intensity with the progress-report zone mapping, else from its session focus (recovery, easy, endurance, long low; tempo, sweet_spot, threshold moderate; vo2max, anaerobic, race high) labelled approximate; steps always win; strength excluded, other unknown time reported as uncovered, never as low) lies more than 5 percentage points outside the reference range of the profile's `training_model`
- **THEN** a non-blocking `intensity_distribution` note with the shares, ranges, evidence and the time per basis (`basis_seconds`: steps, planned_intensity, session_focus) is returned; the intensity or focus fallback gives band time only, never a load number; weeks with less than 2 h or 60 % covered time are not judged, and the `planning_brief` carries the planned distribution. The running week combines its completed run and ride days (zone times of the weekly progress report; completed time without zone times is uncovered) with the remaining planned days, labelled "running week: completed + planned", under the same coverage minimums.

#### Scenario: Leg strength notes
- **WHEN** a planned strength unit has a leg session focus (`legs`, `full_body`, `plyometrics`, set or keyword-derived), or a completed one has executed strength sets (any leg exercise category is leg, only known non-leg categories are not, which wins over its focus), graded by strength intensity, else planned intensity (heavy from 0.85, moderate from 0.70), else RPE (8, 6), else text, else unknown
- **THEN** only the number and intensity of leg sessions count (no tonnage, no strength load; strength stays out of the endurance distribution), and non-blocking notes cover moderate or heavy leg strength less than about 24 h before a hard or long run/ride (heavy within 6 h of a hard session stays `strength_hard_same_day`), more than 3 leg or more than 2 heavy leg sessions in a week (the running week counts its completed strength days with the planned ones, labelled "running week: completed + planned"), and no leg session in 2+ full planned weeks when the profile or season phase expects strength; the `planning_brief` carries `strength` (sessions, leg sessions, leg sessions by intensity) per planned week and the same counts in completed strength weeks, plus `strength_progress` (per exercise the last six completed sessions with sets and top set, no estimated 1RM, trimmed first among the strength entries). The `planning_brief` also carries `season_phase` (base, build, peak, taper or transition, with weeks to the next A/B race), derived read-only from competition dates and priority by `backend/planning/season.py:target_phase` (the same derivation the strength expectation uses) and `unknown` without an A/B race; the plan playbook chooses volume, intensity, strength frequency and taper emphasis per phase for plan_week, plan_block and adjust_week (`tests/test_planning_season.py:TargetPhaseTests`).

#### Scenario: Planning brief budget and precedence
- **WHEN** the `planning_brief` would exceed 20,000 characters
- **THEN** whole entries are dropped (oldest weeks, then planned distribution and strength weeks, planned sessions and latest days), never the JSON text; `lessons` and `season_phase` stay, an `omitted` note names the dropped counts, and its size appears in the context diagnostics. The plan playbook states the precedence illness, competitions and calendar markers, then science defaults, then the athlete's stated availability, and a deviation needs a reason.

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

Evidence: `backend/planning/unit_intensity.py:unit_band`; `tests/test_intensity_distribution.py:UnitFallbackTests`; `backend/planning/plan_checks.py:check_plan`; `backend/planning/load_checks.py:session_spikes`; `backend/planning/load_checks.py:weekly_rises`; `backend/planning/load_checks.py:unknown_load`; `tests/test_load_checks.py`; `backend/planning/plan_guard_service.py:PlanGuardService.verify`; `backend/planning/intensity_distribution.py:distribution_findings`; `tests/test_intensity_distribution.py`; `backend/planning/leg_strength.py`; `tests/test_leg_strength.py`; `backend/coach/tool_execution_service.py:CoachStructuredToolExecutionService.execute`; `backend/coach/change_receipts.py:change_summary`; `public/coach.js:appendMessageChanges`; `tests/test_coach_change_receipts.py:test_plan_notes_are_safe_and_only_attached_to_successful_writes`; `tests/coach-turn-undo.test.cjs`; `tests/test_plan_guard_service.py:PlanGuardWriteTests.test_violation_rolls_back_and_returns_findings`; `backend/coach/write_gate.py:illness_override_confirmed`; `backend/coach/adaptive_apply.py:CoachAdaptiveApplyService._apply_checked`; `backend/planning/running_week.py`; `tests/test_coach_write_gate.py:IllnessOverrideTests`; `tests/test_plan_guard_service.py:PlanGuardWriteTests.test_listing_without_a_finding_does_not_ask`, `tests/test_plan_guard_service.py:PlanGuardWriteTests.test_finding_without_confirmation_rolls_back`; `tests/test_coach_adaptive_apply.py:AdaptiveApplyPlanGuardTests`; `tests/test_load_checks.py:LocalThresholdPrecedenceTests`; `tests/test_intensity_distribution.py:RunningWeekTests`; `tests/test_leg_strength.py:RunningWeekTests`.

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
