## MODIFIED Requirements

### Requirement: CA5 Named remote synchronization and explicit proposals
The system SHALL require the athlete's named sync request for the step's own provider before a remote-write step (the Intervals.icu name or a sync verb for Intervals.icu, Garmin or watch wording for a Garmin push), preserve a separate per-step remote target/scope, and run a named remote write without an approval card, bound to stored state as a card would bind it; only an explicit Garmin removal still goes through the explicit approval proposal.

#### Scenario: Local save only
- **WHEN** the athlete requests local plan, competition or meal saving without naming remote synchronization
- **THEN** no Intervals.icu write is authorized by that request; provider refresh remains a provider read rather than a workout push.

#### Scenario: Explicit named sync
- **WHEN** the athlete names an unnegated Intervals.icu synchronization, uses an unnegated sync verb (such as synchronisieren, abgleichen, hochladen or reparieren), or accepts the directly preceding concrete sync offer
- **THEN** the step still needs the matching provider target, sync scope and remote-write declaration; it is bound to the current stored units, payload hashes and manifests and queued in the same turn without a card. The turn receipt lists the queued sync and each remote deletion it carries (orphaned Intervals.icu events, deleted competitions, orphaned Garmin workouts), and the turn has no whole-turn undo.

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

#### Scenario: Garmin strength push
- **WHEN** the athlete's own message names Garmin or the watch with a transfer verb, or accepts the directly preceding Garmin offer
- **THEN** `push_strength_to_garmin` queues the selected strength units with target `garmin` and scope `garmin_sync` without a card, each bound to its stored payload hash; a call with an explicit removal entry asks on a card, and only its approval queues that job. A refusal blocks the Garmin wording of the whole message as it does for Intervals.icu. Intervals.icu wording never grants it, a Garmin push or removal request never grants an Intervals.icu write, an upload entry needs the athlete's own push wording and a removal entry the athlete's own Garmin removal wording (no classifier is asked).

Evidence: `backend/coach/write_gate.py:remote_requested`, `backend/coach/write_gate.py:build_turn_authority`, `backend/coach/write_gate.py:check_write`; `backend/coach/tool_execution_service.py:CoachStructuredToolExecutionService.execute`; `backend/coach/proposal_creation.py:CoachProposalCreationService.prepare_remote_write`, `backend/coach/proposal_creation.py:CoachProposalCreationService.create_remote_write`, `backend/coach/proposal_creation.py:remote_removal_lines`; `tests/test_coach_plan_sync_card_flow.py:test_a_named_sync_queues_the_same_job_without_a_card`, `tests/test_coach_plan_sync_card_flow.py:test_an_explicit_garmin_removal_still_asks_on_a_card`, `tests/test_coach_change_receipts.py:test_a_card_free_sync_lists_its_remote_removals_without_turn_undo`; `tests/test_coach_write_gate.py:test_named_sync_requests_allow_remote_tools_without_the_classifier`, `tests/test_coach_write_gate.py:test_unnamed_negated_or_asked_syncs_are_denied`, `tests/test_coach_write_gate.py:test_negation_covers_its_sentence_up_to_a_contrast_word`, `tests/test_coach_write_gate.py:test_the_classifier_never_grants_the_illness_sync_to_intervals`, `tests/test_coach_write_gate.py:GarminTierTests`; `backend/coach/write_gate.py:requested_providers`, `backend/coach/write_gate.py:garmin_removal_requested`, `backend/coach/proposal_creation.py:_approved_garmin_arguments`, `backend/coach/sync_tools.py:CoachSyncToolService._push_strength_to_garmin`; `tests/test_coach_tool_coverage.py:test_garmin_strength_push_is_bound_to_the_stored_units`, `tests/test_coach_sync_tools.py:test_garmin_push_needs_the_garmin_target_scope_and_approved_entries`; `tests/test_coach_tool_coverage.py:test_competition_lifecycle_syncs_only_after_explicit_followup`.

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

Evidence: `backend/coach/proposal_execution.py:CoachProposalExecutionService._load_ready_action`, `backend/coach/proposal_execution.py:CoachProposalExecutionService._consume_action`, `backend/coach/proposal_execution.py:CoachProposalExecutionService._validate_remote_write_provenance`; `backend/coach/proposal_creation.py:_approved_remote_arguments`, `backend/coach/proposal_creation.py:_card_authorized_intent`; `tests/test_coach_plan_sync_card_flow.py:ApprovedCardAuthorizesItsUnitsTests`; `tests/test_coach_proposal_execution.py:test_foreign_session_wrong_hash_and_expiry_cannot_consume_or_dispatch`, `tests/test_coach_proposal_execution.py:test_competing_execution_dispatches_only_once`; `public/coach.js:reconcileCoachActionProposal`; `tests/frontend-write-safety.test.cjs:a lost execute response keeps the action locked and is not reported as a failed confirmation`, `tests/frontend-write-safety.test.cjs:reconcile re-enables a proposal the server still reports as confirmable`; `tests/test_coach_tool_coverage.py:test_all_pending_sync_binds_the_units_pending_at_the_request`; `tests/test_coach_dialogue.py:test_sync_followup_failure_distinguishes_coach_interruption_and_keeps_job`.
