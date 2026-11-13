# coach-conversation Specification

## Purpose

Describe the athlete-started Coach dialogue, durable background execution, local history, clarification, cancellation and attachment lifecycle as currently implemented.

## Requirements

### Requirement: CC1 Durable bounded chat submission
The system SHALL persist a valid athlete message and its background command before accepting the chat request, and SHALL expose its operation identity and queued state.

#### Scenario: Valid authenticated submission
- **WHEN** an authenticated athlete submits a message with a nonempty client turn ID through `/api/chat/stream`
- **THEN** the system stores the message, session-bound command, selected model and thinking level, sends a `started` event with the operation ID, and wakes the worker.

#### Scenario: Invalid submission
- **WHEN** the message exceeds 12000 characters, the turn ID is absent or exceeds 120 characters, or the quick-action kind is unsupported
- **THEN** the system rejects the submission without starting model execution.

#### Scenario: Already active session
- **WHEN** the same session submits another turn while its different background turn is queued or running
- **THEN** the system rejects it with a conflict rather than starting concurrent work for that session.

Evidence: `backend/http_api/chat_stream.py:CoachChatStreamTransport.handle`; `backend/coach/job_submission.py:CoachJobSubmissionService.enqueue`, `backend/coach/job_submission.py:CoachJobSubmissionService._persist`; `tests/test_http_chat_stream.py:test_invalid_turn_rejects_before_registration_or_response`; `tests/test_coach_chat_turn.py:test_new_turn_validates_and_forwards_exact_session`. Source/test inspection; not a claim that these tests ran.

### Requirement: CC2 Session ownership and durable turn replay
The system SHALL bind command and receipt access to the creating session, return a finished turn's stored receipt without executing it again, and reject conflicting in-progress execution.

#### Scenario: Completed retry
- **WHEN** the owning session requests an already completed client turn ID
- **THEN** the system returns its durable receipt without invoking the Coach or repeating effects.

#### Scenario: Foreign session
- **WHEN** a different session attempts to resume or read the command
- **THEN** access is denied before provider access or turn execution.

#### Scenario: Reusing a synchronous turn for different text
- **WHEN** opening an existing synchronous turn whose stored athlete text differs from the submitted trimmed message
- **THEN** the system reports a turn-text conflict rather than binding new text to the old request.

Evidence: `backend/coach/chat_turn.py:CoachChatTurnService._command_state`, `backend/coach/chat_turn.py:CoachChatTurnService._run`; `backend/coach/turn_opening.py:CoachTurnOpeningService._require_same_message`; `tests/test_coach_chat_turn.py:test_completed_turn_is_read_idempotently_without_second_execution`, `tests/test_coach_chat_turn.py:test_foreign_turn_is_denied_before_resume_or_provider_access`; `tests/test_coach_turn_opening.py:test_same_turn_id_with_different_text_is_rejected_without_writes`. Background enqueue text equivalence is an evidence limitation recorded separately.

### Requirement: CC3 Recoverable background progress and bounded failure
The system SHALL retain background turn checkpoints, request unfinished work again under the stored model and conversation, and distinguish retryable contention from terminal failure.

#### Scenario: Re-request after interruption
- **WHEN** a durable turn is requeued after a worker or process restart, including a job that an earlier release left with a provider response ID, response input or checkpointed tool outputs
- **THEN** the model request is built again from the turn's original input and its journaled tool results, stateless with `store: false` and without a previous response ID; journaled tool effects are replayed and not executed again, the original model selection is kept, and the earlier release's resume state is dropped on startup.

#### Scenario: Queue contention
- **WHEN** execution cannot acquire the conversation queue or times out waiting for its slot
- **THEN** the job is requeued with observable background status rather than reported as a completed answer.

#### Scenario: Repeated escaped failure or invalid generation
- **WHEN** a job repeatedly fails outside handled turn processing, or belongs to a reset generation
- **THEN** repeated failures eventually become terminal, while an invalidated job cannot restore its session or recreate deleted dialogue.

#### Scenario: Worker and conversation slots
- **WHEN** Coach turns are queued
- **THEN** one daemon worker wakes on a signal or every 5 seconds and claims the oldest due turn among the 20 oldest queued rows (a turn with a stored cancel is due at once); at most 3 turns hold or wait for the conversation lock, a further one fails with 429 `chat_queue_full`, and a lock not free within 30 seconds fails with 409 `chat_request_timeout`

#### Scenario: Backoff and terminal failure
- **WHEN** a turn is requeued for `chat_queue_full` or `chat_request_timeout`, or fails outside its own error handling
- **THEN** a requeue sets the phase `waiting_for_coach_slot` and a delay of min(60, 2^min(n, 5)) seconds for the n-th contention and never ends the turn; the third failure outside turn handling ends it with reason `background_job_exhausted` and "Der Coach-Auftrag ist mehrfach fehlgeschlagen und wurde beendet."

#### Scenario: Restart and stale release
- **WHEN** the process starts with open commands, or a turn that is not a background job has been running for more than 15 minutes when its id is requested again
- **THEN** a running command that is not a background job ends with reason `process_interrupted`, background turns return to `queued` with phase `queued`, and the stale turn is released as `failed` ("Die vorherige Coach-Verarbeitung wurde nach einem Prozessabbruch wieder freigegeben."); a tool call of a released turn is not executed (CA8)

Evidence:
- `backend/coach/background_job.py:CoachBackgroundJobRunner`
- `backend/coach/chat_turn.py:CoachChatTurnService._recover_stale_command`
- `backend/coach/conversation_gate.py:CoachConversationGate.operation`
- `backend/coach/job_store.py:CoachJobStore.claim`
- `backend/coach/job_store.py:CoachJobStore.requeue`
- `backend/coach/job_store.py:CoachJobStore.resume_interrupted`
- `backend/coach/job_store.py:CoachJobStore`
- `backend/coach/job_worker.py:CoachJobWorker.run_forever`
- `backend/coach/job_worker.py:CoachJobWorker`
- `tests/test_coach_background_job.py:test_invalidated_generation_never_restores_session_or_writes_failure`
- `tests/test_coach_background_job.py:test_job_that_keeps_failing_is_ended_with_a_terminal_failure`
- `tests/test_coach_background_job.py:test_queue_contention_requeues_and_emits_background_status`
- `tests/test_coach_conversation_gate.py:test_full_queue_returns_429_and_queue_full_reason`
- `tests/test_coach_dialogue.py:test_interrupted_job_is_requeued_rerequested_and_runs_its_tool_once`
- `tests/test_coach_dialogue.py:test_job_of_an_older_release_is_requested_again_without_its_resume_state`
- `tests/test_coach_job_store.py:test_claim_preserves_the_twenty_row_candidate_limit`
- `tests/test_coach_job_store.py:test_requeue_persists_contention_backoff_and_wakes_worker`
- `tests/test_coach_job_store.py:test_restart_requeues_all_background_jobs`

### Requirement: CC4 Local history and current execution status
The system SHALL provide authenticated bounded local history pages, chronological display within each page, pagination/search metadata and session-scoped execution status.

#### Scenario: Older messages and search
- **WHEN** the athlete requests a bounded history page with an earlier-message cursor or search term
- **THEN** matching local messages are returned in chronological order with generation, limit, search and next-cursor metadata.

#### Scenario: No active turn
- **WHEN** the session has neither an attached stream nor an active durable background job
- **THEN** status reports idle with no operation ID.

#### Scenario: Attachments in history
- **WHEN** a stored message includes attachments
- **THEN** history exposes the attachment names for display without returning inline file data as chat message contents.

Evidence: `backend/http_api/chat_page.py:ChatHistoryPageService.page`; `backend/coach/conversation.py:CoachConversationHistoryService.page`, `backend/coach/conversation.py:CoachMessageService.list`; `backend/coach/job_submission.py:CoachJobSubmissionService.stream_status`; `tests/test_coach_message_service.py:test_list_preserves_repository_order_limit_and_attachment_names`, `tests/test_coach_message_service.py:test_list_is_read_only_and_does_not_publish_events`; `tests/test_http_coach_get_routes.py:test_history_preserves_decoded_query_values`, `tests/test_http_coach_get_routes.py:test_status_uses_the_session_csrf_scope`. Cursor/search behavior is implementation-inspected; no paging test was executed in this worker.

### Requirement: CC5 Durable cancellation and truthful partial outcomes
The system SHALL cancel only the session's matching operation, persist cancellation for durable jobs, and retain already committed changes and their receipts when a turn is cancelled or interrupted.

#### Scenario: Active operation cancellation
- **WHEN** the owning session cancels its attached or durable operation
- **THEN** the system records durable cancellation before signalling the attached stream or the background event, closes any provider response handle, and reports cancelling.

#### Scenario: Unknown or mismatched operation
- **WHEN** there is no active operation or the supplied operation ID conflicts with the attached operation
- **THEN** the system reports not-running or a conflict without cancelling another operation.

#### Scenario: Failure after a local write
- **WHEN** a provider summary fails after a tool has committed a local effect
- **THEN** the final failure receipt and answer retain that successful effect and any supported undo references rather than claiming that nothing changed.

Evidence: `backend/coach/cancellation.py:CoachCancellationService.cancel`; `backend/coach/turn_failures.py:CoachTurnFailureService.persist`; `tests/test_coach_cancellation.py:test_background_cancel_persists_before_signalling_and_does_not_recreate_event`, `tests/test_coach_cancellation.py:test_attached_cancel_closes_provider_and_rejects_wrong_operation`, `tests/test_coach_cancellation.py:test_attached_cancel_persists_cancel_on_the_matching_durable_job_only`, `tests/test_coach_cancellation.py:test_no_active_job_does_not_create_or_write_cancel_state`; `tests/test_coach_dialogue.py:test_summary_failure_preserves_effect_and_replays_receipt`.

### Requirement: CC6 Persisted clarification and conversational continuation
The system SHALL bind clarification to stored athlete messages, persist unresolved constraints for a relevant follow-up, and close a cancelled pending request without undoing completed effects.

#### Scenario: Concrete clarification
- **WHEN** the Coach asks a valid bounded question whose source IDs include the current stored athlete message
- **THEN** the system persists the summary, question, source IDs, status and inferred domain as the pending request.

#### Scenario: Short answer or new topic
- **WHEN** the athlete answers an active clarification concisely or explicitly retries its original request
- **THEN** the original athlete-message provenance and constraints are retained; an unrelated new-domain request does not inherit stale pending authority.

#### Scenario: Invalid provenance or cancellation
- **WHEN** a clarification references an assistant message or missing current user ID, or the athlete cancels the pending request
- **THEN** invalid provenance is rejected without saving a question, and cancellation closes pending state without changing athlete records.

#### Scenario: Clarification limits and stored shape
- **WHEN** the Coach calls `clarify_coach_request` (`source_message_ids`, `summary`, `question`; no `_request`, no write gate)
- **THEN** it needs 1 to 24 integer ids of stored athlete messages of the current dialogue that include the current message (else 400 `request_provenance` "Die Rückfrage benötigt den zugehörigen Nutzerauftrag."), a summary of 1 to 4,000 and a question of 1 to 1,000 characters (else 400 `request_question` "Bitte formuliere eine konkrete Rückfrage zum Auftrag."); the pending request `{summary, question, source_message_ids, origin_message_ids, status, domain}` is stored with status `needs_clarification`, the result is `{ok, status: needs_clarification, question}`, and the turn ends `completed` with `awaiting_clarification: true` and the question as its answer; `cancel_coach_request` takes no parameters and returns `{ok, status: cancelled}`

#### Scenario: Kept or dropped
- **WHEN** the next athlete message arrives
- **THEN** a clarification is kept for a retry or continuation word, a message of the same domain, a typical answer pattern, or a reply of at most three words without a question mark and without a topic of its own; a failed request is kept only for a retry or continuation and only with stored source ids; a message of another domain drops both, and a kept failed request is shown to the model as the athlete's stored words, never as a model summary

#### Scenario: Server-recorded chain
- **WHEN** the write gate reads the original request of a retried or answered pending request
- **THEN** it uses `origin_message_ids`, the chain of athlete message ids the server recorded (the original request plus the athlete's answers), never the ids the model cited

#### Scenario: Other calls beside a control tool
- **WHEN** a tool round holds `clarify_coach_request` or `cancel_coach_request`
- **THEN** every other non-read call of that round fails with 409 `request_paused` "Der Auftrag wartet auf deine Antwort oder wurde abgebrochen.", whatever the order, read tools still run, and the next model request is sent with `tool_choice: none`

Evidence:
- `backend/coach/clarification.py:CoachClarificationService.save_question`
- `backend/coach/context_selection.py:_pending_request_is_active`
- `backend/coach/context_selection.py:compact_coach_dialogue`
- `backend/coach/context_selection.py:pending_origin_messages`
- `backend/coach/context_selection.py:request_chain_ids`
- `backend/coach/tool_execution_service.py:CoachStructuredToolExecutionService.execute`
- `backend/coach/tool_preparation.py:CoachStructuredToolPreparationService._request_is_paused`
- `backend/coach/turn_write_gate.py:_pending_origin`
- `tests/test_coach_context_selection.py:test_concise_freeform_answer_retains_an_active_clarification`
- `tests/test_coach_dialogue.py:test_cancel_and_chat_reset_close_pending_request`
- `tests/test_coach_dialogue.py:test_clarification_service_persists_valid_user_provenance_and_limits`
- `tests/test_coach_dialogue.py:test_clarification_service_rejects_unbound_message_ids_without_writing`
- `tests/test_coach_tool_preparation.py:test_round_pause_blocks_writes_but_allows_reads_and_dialogue_controls`
- `tests/test_coach_turn_outcome.py:test_clarified_request_that_fails_keeps_its_chain_through_a_retry`

### Requirement: CC7 Conversation reset and unavailable remote continuity
The system SHALL reset local dialogue atomically under a bounded conversation lock, invalidate queued work and pending requests, and keep durable athlete records independent of remote conversation continuity.

#### Scenario: Reset while remote deletion is slow or fails
- **WHEN** local reset succeeds but remote conversation deletion is slow or fails
- **THEN** the local messages and conversation reference remain cleared, a new generation is returned promptly, and later chat can provision a new conversation.

#### Scenario: Lock timeout
- **WHEN** an active turn does not release the conversation lock within the reset bound
- **THEN** reset returns a conflict with existing local history and conversation generation preserved for a later retry.

#### Scenario: Invalid provider conversation
- **WHEN** an unfinished response reports invalid conversation state before any new text delta, and the recovery budget remains
- **THEN** the system retries once using bounded local dialogue, current message and confirmed steps without inventing unavailable image details or repeating committed work.

#### Scenario: Recovery contents
- **WHEN** recovery runs (`conversation_state_invalid` before any text delta, once per turn, on the first or second attempt of a request)
- **THEN** the stored provider conversation id is cleared, the request loses its conversation and earlier tool-round items, its input is rebuilt as `{dialogue, current_message, confirmed_steps}` from local data, and its instructions gain the notice "The remote conversation was unavailable. Continue only unfinished work using local dialogue and confirmed_steps. Earlier image pixels may be unavailable; ask for missing evidence only if essential. Never invent attachment details."; a second invalid state in the same turn fails the turn with the fixed explanation of CC11

Evidence: `backend/coach/conversation.py:CoachConversationResetService.reset`; `backend/coach/conversation_recovery.py:CoachConversationRecoveryService.recover_if_invalid`; `tests/test_coach_conversation_reset.py:test_slow_remote_delete_does_not_delay_the_reset_response`, `tests/test_coach_conversation_reset.py:test_failing_remote_delete_is_logged_and_does_not_fail_the_reset`, `tests/test_coach_conversation_reset.py:test_reset_succeeds_after_a_lock_timeout_once_the_turn_released`; `tests/test_coach_dialogue.py:test_invalid_state_recovery_does_not_repeat_committed_effect`, `tests/test_coach_dialogue.py:test_repeated_invalid_state_is_bounded_and_explained_without_raw_error`.

### Requirement: CC8 Validated attachments and bounded continuity
The system SHALL accept only supported bounded image, GPX and FIT attachments, persist validated evidence for the durable worker, and reject invalid or oversized requests before creating their command.

#### Scenario: Supported attachment submission
- **WHEN** up to four valid PNG, JPEG, WebP, GPX or FIT files within the per-file and aggregate limits are submitted
- **THEN** the worker receives the saved attachment evidence; an attachment-only submission receives a default analysis request.

#### Scenario: Malformed or oversized upload
- **WHEN** an attachment has invalid type/encoding, unsafe XML, malformed FIT checksums, excessive request size or exhausted attachment-storage quota
- **THEN** the system rejects it with the applicable invalid-attachment or size/quota error without creating a command.

#### Scenario: Follow-up and recovery
- **WHEN** the athlete follows up on recent attachments or remote continuity is lost
- **THEN** the system uses its bounded attachment-continuity policy and local non-image summaries, marks missing evidence honestly, and does not fabricate image contents.

#### Scenario: Track files leave only measurements
- **WHEN** a GPX or FIT file is attached
- **THEN** the model receives its parsed points and a computed summary, never the original file; positions within 500 m of the start and the end of the track are removed while the other values stay, a track shorter than 1,000 m loses every position, GPX name, description, comment, source, symbol, type, link and fix fields are skipped, and only the session, lap, record and set messages of a FIT file are read, so device, serial-number and user-profile records never leave the server

#### Scenario: Images leave without metadata
- **WHEN** a PNG, JPEG or WebP image is attached
- **THEN** EXIF, XMP, comments and text chunks are removed before it is sent while the pixel data stays; an image that cannot be parsed is rejected at submission; the stored copy is not changed

#### Scenario: Attachment limits
- **WHEN** attachments are validated
- **THEN** at most 4 files are accepted, each at most 5,000,000 decoded bytes with a name of 1 to 160 characters without `/`, backslash or control characters; the payload sent to the provider may hold at most 28,000,000 bytes (413 `attachment_request_too_large`) and all stored attachments at most 40,000,000 bytes (413 `attachment_storage_quota`); the browser accepts images up to 15,000,000 bytes and reduces them before upload; an OpenAI conversation is kept for the next 3 athlete messages after an upload, later turns get local summaries

Evidence:
- `backend/coach/attachment_privacy.py:hidden_position_indexes`
- `backend/coach/attachments.py:MAX_REQUEST_BYTES`
- `backend/coach/attachments.py:model_attachments`
- `backend/coach/attachments.py:validate_attachments`
- `backend/coach/conversation.py:ATTACHMENT_RETENTION_USER_MESSAGES`
- `backend/coach/conversation.py:CoachConversationProvisionService`
- `backend/coach/conversation_recovery.py:CoachConversationRecoveryService.recover_if_invalid`
- `backend/coach/image_metadata.py:strip_image_metadata`
- `backend/coach/job_submission.py:CoachJobSubmissionService._persist`
- `backend/coach/job_submission.py:CoachJobSubmissionService._validate_submission`
- `backend/providers/openai_responses_adapter.py:model_input`
- `public/coach.js:validateChatAttachmentFiles`
- `tests/test_coach_attachment_context.py:test_retention_window_boundary_at_one_and_three_and_outside_at_four`
- `tests/test_coach_attachment_privacy.py:test_first_and_last_500_m_are_hidden`
- `tests/test_coach_attachment_privacy.py:test_unparseable_image_is_rejected_not_passed_through`
- `tests/test_coach_attachments.py:test_attachment_persists_for_worker_without_leaking_into_history`
- `tests/test_coach_attachments.py:test_attachment_storage_quota_prevents_backup_growth`
- `tests/test_coach_attachments.py:test_invalid_attachment_conversation_recovers_gpx_and_future_turns`
- `tests/test_coach_attachments.py:test_invalid_upload_does_not_create_a_command`
- `tests/test_coach_conversation_recovery.py`

### Requirement: CC9 Athlete-started morning check-in completion
The system SHALL treat the morning quick action as a stored athlete-started turn, prepare configured Garmin sleep and morning battery data before coaching, and mark it ready for the local day only after a completed answer without clarification.

#### Scenario: Configured Garmin and fresh sleep
- **WHEN** the athlete starts the morning quick action with configured Garmin
- **THEN** the system attempts the existing Garmin refresh, verifies today's sleep readiness, refreshes morning Body Battery and then runs the Coach; a turn that is requested again after that preparation does not repeat it.

#### Scenario: Missing sleep or unconfigured Garmin
- **WHEN** current sleep is unavailable after refresh, or Garmin is unconfigured
- **THEN** missing sleep requeues the turn (phase `waiting_for_data`) every 15 minutes, at most 8 times, and only then fails with 503 `garmin_sleep_not_ready`; a failed Garmin refresh is only logged. Unconfigured Garmin skips that provider preparation.

#### Scenario: Completion versus pending clarification
- **WHEN** the morning turn finishes with a message and no pending clarification
- **THEN** its ready marker for the local day the turn was prepared for (kept in the job receipt, also when the turn is requested again) and its quick-action receipt are persisted, so a check-in completed after midnight does not mark the next day; a clarification or yesterday's ready marker does not count as today's completed check-in.

Evidence:
- `backend/coach/background_job.py:CoachBackgroundJobRunner._execute`
- `backend/coach/background_job.py:CoachBackgroundJobRunner._handle_app_error`
- `backend/coach/job_store.py:CoachJobStore.requeue`
- `backend/coach/morning.py:ManualMorningCheckinService.prepare`
- `backend/coach/morning.py:MorningCheckinStateService.state`
- `backend/coach/morning_completion.py:MorningCoachJobCompletionService.complete`
- `tests/test_coach_background_job.py:test_morning_completion_requires_final_message_without_clarification`
- `tests/test_coach_background_job.py:test_rerequested_morning_turn_does_not_repeat_the_sync`
- `tests/test_coach_dialogue.py:test_morning_quick_action_stays_pending_while_coach_awaits_clarification`
- `tests/test_coach_job_store.py:CoachJobStoreTests.test_data_wait_requeues_with_fixed_delay_until_its_cap`
- `tests/test_coach_manual_morning.py:test_fresh_sleep_syncs_then_refreshes_battery`
- `tests/test_coach_manual_morning.py:test_missing_or_stale_sleep_raises_without_refreshing_battery`
- `tests/test_coach_manual_morning.py:test_unconfigured_garmin_returns_without_reading_or_refreshing`
- `tests/test_coach_manual_morning.py:test_yesterday_ready_state_is_projected_as_waiting`
- `tests/test_coach_morning_completion.py:test_completed_command_gets_compact_unicode_receipt_in_two_transactions`
- `tests/test_server_coach.py:ServerCoachTests.test_sleep_not_ready_requeues_the_morning_job_with_a_quarter_hour_wait`

### Requirement: CC9a Analysis and planning quick actions
The system SHALL accept only the quick-action kinds `morning_checkin`, `session_analysis`, `progress_review`, `block_review`, `plan_week`, `plan_block` and `adjust_week`, store the athlete's visible message with the chosen period, select the context sections the kind needs, and append the kind's playbook to the instructions of that turn only. A playbook never authorizes a write.

#### Scenario: Playbook only on its own turn
- **WHEN** a turn carries one of the analysis or planning kinds
- **THEN** its instructions end with that kind's playbook, while morning check-in and ordinary turns carry none.

#### Scenario: Playbook blocks
- **WHEN** a playbook is composed
- **THEN** it consists of small topic blocks, each with its own word budget: evidence and labels and the intensity model for every kind; plan kinds add plan structure, strength and legs, tests, season phase, thresholds, precedence, calendar and plan checks; `adjust_week` season phase, precedence, calendar, plan checks and adaptive changes; `session_analysis` session checks, session numbers and the answer block; the review kinds the answer block. A kind carries at most 600 words in total, and the Coach request size diagnostics report `playbook_characters`.

#### Scenario: Kind-specific context
- **WHEN** a turn carries one of the analysis or planning kinds
- **THEN** its context sections come from the kind rather than the message wording, while dialogue and pending-request retention still follow the message as for an ordinary turn. The day-by-day `daily_planning_context` is part of the planning kinds, `morning_checkin` and today-training questions only; the planning kinds carry calendar events once, as `external_calendar` with markers and the omitted count; `morning_checkin` carries the base sections, the day view and recovery for today and tomorrow, without plans, brief or calendars; `progress_review` and `block_review` carry no future planned units, and `progress_review` no `training_plans`. Every omitted section stays loadable through `read_coach_context`.

#### Scenario: Typed planning request
- **WHEN** the athlete types a planning action with a week or block (for example "Plane meine nächste Woche", "Plane die nächsten 4 Wochen", "Passe die Woche an")
- **THEN** the turn uses the matching `plan_week`, `plan_block` or `adjust_week` context and playbook, including `planning_brief`, with explicit dates or long ranges keeping the complete time context plus the brief; a question that merely mentions a week or the noun "Plan" keeps its ordinary context, and dialogue and pending-request retention and the write gate follow the message as before.

#### Scenario: Typed review request
- **WHEN** the athlete types a review action with one session (for example "Wie lief mein Intervalltraining?", "Analysiere meinen Lauf vom 2.11."), asks to see progress ("Zeig mir meinen Fortschritt", "Werde ich fitter?") or names a block review ("Bewerte meinen letzten Block"), without a planning verb
- **THEN** the turn carries the matching `session_analysis`, `progress_review` or `block_review` kind and playbook, adds the kind's sections to the ones the message asked for (such as weather), and keeps the complete time context for explicit dates or past weeks without `planning_brief`; plural sessions ("meine Läufe der Woche"), recovery after a session and advice questions ("Wie werde ich fitter?", "Progressionslauf") keep their ordinary context.

#### Scenario: Review answers
- **WHEN** a turn carries `session_analysis`, `progress_review` or `block_review`
- **THEN** its playbook asks for a one-sentence verdict, findings with concrete numbers (two to four for one session), short coverage and unknowns, and the task's consequence or lessons, in plain words; the session-analysis playbook names per session type what to judge (plan, load and intensity, warm-up and cool-down, steadiness and drift of easy sessions, rep execution, recoveries and their heart-rate drop, heart rate not judged under about two minutes) and the confounders to check first, and the progress and block review are one review: it reads the `block_review` section for 4, 8 or 12 weeks or since the last test, leads with performance at equal effort, names plan execution and subjective signals only as possible causes and states when pace at heart rate is `not_covered`. The quick menu offers progress over 4, 8 and 12 weeks and since the last test, without a separate block review.

#### Scenario: Planned and analysed tests
- **WHEN** a turn carries `plan_week` or `plan_block`
- **THEN** `planning_brief.last_tests` names per sport the day of the last local test unit with a completed activity of its sport that day, or race, of the last 120 days, and the playbook plans a run critical-speed test (3600, 2400 and 1200 m on a track or measured flat route, else a 30-min time trial) or a Zwift FTP ramp test when that day is 6 to 8 weeks old or unknown, run and ride in different weeks, never in the last 2 weeks before an A race or with illness or poor recovery; an optional fixed-heart-rate control run keeps `session_focus` easy.

#### Scenario: Test evaluation
- **WHEN** `get_activity_details` matches a planned unit with `session_focus` test
- **THEN** `focus.test_evaluation` asks to judge the execution first, compare with the previous test of the same protocol, read the ramp test from the session's own best 1-min power and recommend a threshold update without writing it; other sessions carry no test evaluation.

#### Scenario: Adjust the current week
- **WHEN** a turn carries `adjust_week`
- **THEN** its playbook compares plan and actual for the current week, changes only today and later days, moves a missed key session by `session_focus` without back-to-back hard days or leg strength less than 24 h before it, keeps run, ride and strength combinable, leaves adaptive replans to the preview and approval rule, and writes nothing to Intervals.icu without a named sync, while its context holds the plan sections, planning brief, calendars, weather and recovery for the current week, including planned units from earlier days of that week, and the days after it.

#### Scenario: Session analysis context
- **WHEN** a turn carries `session_analysis`
- **THEN** its context holds profile, competitions, feedback, planned units of the last two days and the next two days, activities, recovery and current performance with activity validation, while weather, calendars and plan sections stay requestable through `read_coach_context`. `get_activity_details` returns the local planned units one day around the analysed session's date as `planned_units`, so an older session keeps its plan for the plan-versus-actual comparison.

#### Scenario: Session checks beside the recording
- **WHEN** the Coach calls `get_activity_details` for a known session
- **THEN** the result adds `focus` (the `session_focus` and origin of the one local planned unit of that day and sport, else unknown with a reason), for runs `pace_at_heart_rate` (pace in a shared 10 bpm band against the median of at least three comparable steady runs of the last 42 days with their count, else `not_covered` with the reason, never zero) and for runs and rides `strength_before` (completed, else planned (`planned_not_confirmed`), strength sessions in the 48 h before the start with `legs`, `intensity` and hours before, no load); for runs and rides with a matched local planned unit `planned_targets` (each work lap against its planned step), and for runs and rides `comparable_sessions` (this execution against the median of at least three comparable sessions of 84 days, else `not_covered`); for strength sessions with executed sets and a matched unit's `strength_structure` `strength_plan` (planned against executed sets per exercise, unknown exercises not counted as misses); the `session_analysis` playbook judges the session against its focus, reads laps from `analysis.execution` and targets from `planned_targets` instead of raw streams, names leg strength only as a possible explanation, and provider text stays data.

#### Scenario: Nutrition rules only on nutrition turns
- **WHEN** the selected context includes `nutrition_products`
- **THEN** the instructions append the nutrition playbook (reusable meals, food matching); the base prompt keeps only the core write rules (one complete entry per meal, saved products first, templates by exact ID, no hypothetical or negated saves); a topic-less reply to a recent food exchange keeps the playbook; an upload alone does not add it to plan or analysis turns.

#### Scenario: Unknown kind
- **WHEN** a submission names another kind
- **THEN** it is rejected as an unsupported quick action before any turn is stored.

Evidence:
- `backend/coach/session_checks.py:matched_focus`
- `backend/performance/pace_at_hr.py:session_comparison`
- `backend/planning/leg_strength.py:strength_before`
- `tests/test_coach_session_checks.py`
- `backend/coach/playbooks.py:playbook_for` (`block_review`)
- `backend/coach/playbooks.py:nutrition_playbook`
- `tests/test_coach_playbooks.py:PlaybookBudgetTests`
- `tests/test_coach_activity_read_tools.py:CoachActivityReadToolServiceTests.test_detail_of_an_old_session_carries_its_planned_units`
- `backend/coach/job_submission.py:CoachJobSubmissionService._validate_submission`
- `backend/coach/context_selection.py:select_coach_context`
- `backend/coach/context_selection.py:free_text_review_kind`
- `tests/test_coach_playbooks.py:FreeTextReviewKindTests`
- `tests/test_coach_playbooks.py:PlaybookInjectionTests.test_review_kinds_share_the_answer_format_and_plain_language`
- `backend/coach/request_payload.py:compose_model_instructions`
- `tests/test_coach_context_budget.py:CoachContextBudgetTests`
- `tests/test_coach_playbooks.py:PlaybookInjectionTests.test_other_turns_carry_no_playbook`
- `tests/test_coach_playbooks.py:PlaybookInjectionTests.test_nutrition_rules_only_on_nutrition_turns`
- `tests/test_coach_playbooks.py:RequestKindAllowlistTests.test_unknown_kind_is_rejected`
- `tests/test_coach_playbooks.py:PlaybookInjectionTests.test_adjust_week_playbook_guards_hard_days_and_writes`
- `tests/test_coach_playbooks.py:RequestKindSelectionTests.test_every_kind_has_a_selection_and_keeps_message_retention`; plan_week, plan_block and adjust_week also load the deterministic `planning_brief` section (`backend/planning/plan_guard_service.py:build_planning_brief`; `tests/test_plan_guard_service.py:PlanBriefTests.test_brief_section_only_for_plan_kinds`).

### Requirement: CC9b Chat stream event contract
`POST /api/chat/stream` SHALL answer one finite `text/event-stream` per submitted turn whose events let a client follow the durable turn without owning it. The request fields, event payloads and error reasons are the route contract in `docs/api-routes.md`, generated from the route handler.

#### Scenario: Attached turn
- **WHEN** a valid turn is submitted and its stream stays attached
- **THEN** the stream sends `started` with the operation ID before the submission is validated and enqueued (a missing turn ID is refused earlier as a JSON 400), then `delta` text chunks, a `heartbeat` after every 15 seconds without an event while the turn is queued or running, and ends after `completed` (the stored receipt without its session key) or `error` (`reason` and a redacted message of at most 1000 characters)

#### Scenario: Turn continues without this stream
- **WHEN** the turn ID was already submitted by this session, the turn has no attached relay, a restore or delete is pending, or execution is requeued after queue contention
- **THEN** the stream sends `background` and ends while the turn goes on: with the submitted job (`status`, `mode`, `operation_id`, `plan_scope`) for a known turn ID or a turn without relay, with `status`, `mode` and `operation_id` after a requeue, and with `operation_id` alone while maintenance is pending; a closed connection never cancels the turn

#### Scenario: Relay finds the turn finished
- **WHEN** 15 seconds pass without an event and the turn is no longer active
- **THEN** the stream reads the stored receipt and sends it as `completed`, or an `error` when it cannot be read

#### Scenario: Deltas only on the first attempt
- **WHEN** a turn is requested again after its first attempt reached the model, or no stream is attached
- **THEN** no `delta` events are published, and the final reply arrives in the receipt

#### Scenario: Stored receipt at enqueue
- **WHEN** a turn is accepted
- **THEN** its command receipt holds `status` (`queued`, then `running` in the worker), `mode` (`background`), `phase` (`queued`, then `preparing`, `waiting_openai`, `executing_tools` and `waiting_final_response` in the worker; `waiting_for_coach_slot` on requeue, `cancelling` on cancel), `operation_id`, `session_key` (SHA-256 of the session's CSRF hash), `user_message_id`, `client_turn_id`, `plan_scope`, `ai_provider`, `model`, `thinking_level` and `request_kind`

Evidence:
- `backend/coach/background_job.py:CoachBackgroundJobRunner._delta_callback`
- `backend/coach/background_job.py:CoachBackgroundJobRunner._handle_app_error`
- `backend/coach/job_submission.py:CoachJobSubmissionService._persist`
- `backend/http_api/chat_stream.py:CoachChatStreamTransport._relay_events`
- `backend/http_api/chat_stream.py:CoachChatStreamTransport._stream`
- `tests/test_coach_background_job.py:test_attached_stream_gets_deltas_until_the_turn_was_requested_once`
- `tests/test_coach_background_job.py:test_queue_contention_requeues_and_emits_background_status`
- `tests/test_http_chat_stream.py:test_disconnect_does_not_cancel_or_stop_durable_submission`
- `tests/test_http_chat_stream.py:test_pending_maintenance_detaches_a_queued_turn_relay`
- `tests/test_http_chat_stream.py:test_restart_replay_returns_original_job_as_background`
- `tests/test_http_chat_stream.py:test_stream_relays_events_and_unregisters_after_terminal_event`
- `tests/test_http_chat_stream.py:test_timeout_heartbeats_while_active_then_reads_final_receipt`

### Requirement: CC9c Fixed model instructions as normative source
The fixed Coach instructions SHALL be the normative text of these modules, not restated in specs: the dialogue rules and scope-token vocabulary (`backend/coach/dialogue.py:INSTRUCTIONS`), the coaching rules (`backend/coach/prompt.py:COACH_PROMPT`), the quick-action and nutrition playbooks (`backend/coach/playbooks.py`) and the attachment policy and turn notices (`backend/coach/request_payload.py`).

#### Scenario: Instruction order
- **WHEN** a Coach turn's instructions are composed
- **THEN** they are the dialogue rules, the attachment policy, the training context (the coaching rules, then the athlete context and library marked as untrusted external data), the playbook of the turn's kind and the nutrition playbook when nutrition is selected, then the notices for an earlier attachment summary, requeued confirmed steps and an advisory turn without writes; tool rounds reuse the current composed text (rebuilt only when a context refresh changes it), and the final request after the tool budget is exhausted appends the tool-budget notice

#### Scenario: Changing a rule
- **WHEN** a rule in one of these modules changes
- **THEN** the change is a behaviour change of the Coach contract and needs the same review and evaluation as any other Coach behaviour change; the specs reference the module rather than a copy

Evidence: `backend/coach/request_payload.py:compose_model_instructions`; `backend/coach/context.py` (training context prefix); `backend/coach/dialogue.py:INSTRUCTIONS`; `backend/coach/prompt.py:COACH_PROMPT`; `backend/coach/playbooks.py:playbook_for`, `backend/coach/playbooks.py:nutrition_playbook`; `tests/test_coach_playbooks.py:PlaybookInjectionTests.test_other_turns_carry_no_playbook`, `tests/test_coach_playbooks.py:PlaybookInjectionTests.test_nutrition_rules_only_on_nutrition_turns`.

### Requirement: CC10 Composer continuity and user-controlled input
The system SHALL keep drafts editable while the Coach runs, serialize queued follow-ups, preserve rejected input on session expiry and require the athlete to send editable voice transcripts as chat messages.

#### Scenario: Queue or steer while busy
- **WHEN** the athlete submits another message while a response runs
- **THEN** ordinary follow-ups queue in order and steer places the next message ahead of other queued entries; editing a queued item merges its text/attachments only within the four-attachment limit, otherwise the queue and draft remain intact.

#### Scenario: Keyboard submission
- **WHEN** the athlete presses Enter
- **THEN** desktop Enter sends and Shift+Enter inserts a newline, touch Enter inserts a newline and Ctrl/Cmd+Enter can send; IME composition does not submit.

#### Scenario: Expired session
- **WHEN** a current chat submission receives HTTP 401
- **THEN** the client shows login once and restores its draft/attachments without overwriting newer typed text or replaying a superseded draft.

#### Scenario: Opt-in voice transcript
- **WHEN** the athlete starts supported secure-context microphone input
- **THEN** recording is bounded to sixty seconds, recording resources are stopped after capture, and a successful transcript is appended to the editable draft rather than sent automatically; denied/unsupported recording or empty transcription produces an explicit error.

Evidence: `public/coach.js:queueChatMessage`, `public/coach.js:editQueuedChatMessage`, `public/coach.js:chatEnterAction`, `public/coach.js:rejectChatStreamResponse`, `public/coach.js:toggleVoiceInput`, `public/coach.js:transcribeVoice`; `backend/providers/audio.py:AudioTranscriptionClient.transcribe`; `tests/coach-enter.test.cjs:desktop Enter sends the draft`, `tests/coach-enter.test.cjs:IME composition never triggers an action`; `tests/coach-queue-edit.test.cjs:editing a queued message is refused and leaves the queue untouched when the combined count exceeds the limit`; `tests/coach-session-expiry.test.cjs:a chat 401 keeps newer typed text and parks the rejected message once when the input was edited`; `tests/test_provider_audio.py:test_validation_precedes_provider_io_and_keeps_order`, `tests/test_provider_audio.py:test_empty_or_invalid_provider_responses_are_rejected`. Microphone permissions/recording cleanup are source-inspected; no browser/microphone runtime was exercised.

### Requirement: Clarify uncertain calendar impact
The planning playbook SHALL direct the Coach to ask whether to train and whether to reduce intensity when an event creates material uncertainty, and to use the athlete's answer. An ordinary event alone SHALL not imply a cancellation or reduction.

#### Scenario: Uncertain busy day
- **WHEN** a calendar event leaves a material training decision unclear
- **THEN** the Coach asks before making that decision and groups questions where practical.

Evidence: `backend/coach/playbooks.py:playbook_for`; `tests/test_calendar_planning.py:test_plan_playbook_requests_clarification`; `tests/test_coach_dialogue.py:test_calendar_clarification_then_easy_workout`. The scripted dialogue proves mechanics, not natural-language model reliability.

### Requirement: Claude turns keep the dialogue local
The system SHALL create, bind or rotate no remote conversation for a turn whose model is a Claude family; such a turn SHALL send the bounded local dialogue and its own attachments, and resend its earlier tool rounds within the turn.

#### Scenario: Attachment turn with Claude
- **WHEN** a Claude turn carries an image or file, or follows one within the attachment window
- **THEN** no OpenAI conversation is created, bound or rotated, the attachments of this turn are sent with it, and later turns rely on the local summaries.

Evidence: `backend/coach/structured_turn.py:CoachStructuredTurnService._open_and_request`, `backend/coach/request_payload.py:CoachRequestPayloadService.keeps_remote_conversation`; `tests/test_coach_structured_turn.py:test_a_claude_turn_keeps_attachments_local_and_never_goes_remote`, `tests/test_coach_request_payload.py:test_only_openai_models_keep_a_remote_conversation`.

### Requirement: CC11 Turn receipt status and failure explanation
The system SHALL finish each turn's one durable receipt together with its assistant message in one transaction, choose its status by a fixed rule, and explain a failed turn with a fixed German text per reason while keeping every applied effect.

#### Scenario: Status of a finished turn
- **WHEN** a turn finishes
- **THEN** its status is `completed` when it ends with a clarification question; `partial` when the answer is incomplete, or when a step failed or no answer came although something took effect; `failed` when a step failed or no answer came and nothing took effect; `cancelled` after a cancellation without failure; otherwise `completed`

#### Scenario: Final receipt
- **WHEN** the final receipt is stored
- **THEN** it adds `awaiting_clarification`, `response_status` (`incomplete` when the answer stopped for length, else the provider's stop reason, or null), `tool_rounds`, `tool_budget_exhausted`, `pending_operations`, `proposed_actions`, `change_summary` and `message`, drops the open tool-call list, and is written with the assistant message before the event `coach {message_id, role, client_turn_id}` is published; a turn that is already finished returns its stored receipt, and the receipt keeps the provider of the answer in `ai_provider`

#### Scenario: Failed turn
- **WHEN** a turn ends with an error other than `command_scope_denied`, `client_turn_in_progress` or `client_turn_text_mismatch`
- **THEN** an assistant message with a fixed German explanation is stored, flagged `coach_failed` (with `coach_request_kind` for a quick action) when the status is `failed`; the receipt keeps the steps, `error` (redacted, at most 1,000 characters), `diagnostic_error`, `pending_operations`, `proposed_actions` and the change summary of the applied writes, so applied effects stay visible and undoable; a cancelled turn clears the pending request, any other failure stores the athlete's message as a `failed` pending request with its completed steps, unless a clarification question had been stored in this turn, which then is the answer with status `completed`; with applied effects a failed or cancelled turn is `partial`

#### Scenario: Explanation per reason
- **WHEN** the error has one of the reasons mapped in `CoachTurnFailureService._base_response` (OpenAI or Anthropic not configured, `refused`, `conversation_state_invalid`, `conversation_locked`, `authentication_or_permission`, `insufficient_quota`, `credit_balance_exhausted`, the three spend and usage limit reasons, `database_busy`, `provider_timeout`, `not_found`, `provider_unavailable`, `response_error`, `response_failed`, a rate limit)
- **THEN** the answer is that mapping's fixed text, normative like the modules of CC9c, "Die Coach-Verarbeitung wurde abgebrochen." for a cancellation and for any other reason "Bei der Coach-Verarbeitung ist ein technischer Fehler aufgetreten. Bitte versuche es erneut. Wenn der Fehler wieder auftritt, exportiere die Diagnose in den Einstellungen."; applied effects add "Bereits erfolgreich ausgeführt: <Labels>. Diese Schritte bleiben gespeichert.", a card waiting for approval "Eine Remote-Änderung wurde noch nicht ausgeführt und wartet auf deine Freigabe.", a queued sync "Der Sync-Auftrag bleibt bestehen und wird unabhängig vom Coach verarbeitet. Sein Abschluss ist in dieser Antwort noch nicht bestätigt.", unresolved failures their lines and open steps "Noch offen: <Aktionen>."

Evidence: `backend/coach/service.py:outcome_status`, `backend/coach/final_receipt.py:CoachFinalReceiptService.build`, `backend/coach/final_receipt.py:CoachFinalReceiptService.persist`, `backend/coach/turn_failures.py:CoachTurnFailureService.persist`, `backend/coach/turn_failures.py:CoachTurnFailureService._base_response`, `backend/coach/turn_failures.py:CoachTurnFailureService._effect_text`, `backend/coach/structured_turn.py:CoachStructuredTurnService.run`; `tests/test_coach_final_receipt.py:test_build_projects_outcome_and_removes_open_tool_calls`, `tests/test_coach_turn_failures.py:test_busy_local_database_is_explained_as_a_short_retry`, `tests/test_coach_turn_failures.py:test_provider_timeout_is_a_persisted_actionable_chat_message`, `tests/test_coach_turn_failures.py:test_openai_billing_failure_is_a_persisted_actionable_chat_message`.

### Requirement: CC12 Quick-action state
The system SHALL publish a `coach_quick_actions` object in the bootstrap, state and plan payloads and in the receipt of a completed morning check-in, telling the client which Coach quick actions are useful today.

#### Scenario: State fields
- **WHEN** the state is read
- **THEN** it is `{morning_checkin, analyze_latest_activity, adjust_plan, plan_blockers, horizon_days}`: `morning_checkin` is false only when the stored morning status is `ready` for today's local date; `analyze_latest_activity` is always true; `horizon_days` is 3; `adjust_plan` is true exactly when `plan_blockers` is not empty

#### Scenario: Plan blockers
- **WHEN** the latest adaptive adjustment has status `preview`
- **THEN** `plan_blockers` lists `{date, name, triggers}` for each of its changes dated today up to two days ahead whose blocking triggers include calendar, illness, injury or weather (only these four, sorted), the name cut to 200 characters; without such a preview the list is empty

Evidence: `backend/coach/context.py:coach_quick_actions_state`, `backend/coach/context.py:CoachQuickActionsService.state`, `backend/planning/adaptive.py:adaptive_quick_action_blockers`, `backend/coach/morning_completion.py:MorningCoachJobCompletionService.complete`, `backend/http_api/bootstrap_state.py`, `backend/http_api/public_plan.py`; `tests/test_coach_quick_actions.py:test_blockers_include_today_through_two_days_but_not_day_three`, `tests/test_server_coach.py:ServerCoachTests.test_coach_quick_actions_hide_completed_morning_and_limit_plan_blockers_to_three_days`.

### Requirement: CC13 Durable Coach state
The system SHALL keep Coach dialogue state in the tables `messages`, `coach_commands`, `coach_action_proposals` and `coach_plan_artifacts` and in the key-value entries below, with the meanings of the scenarios. Column definitions are in `docs/schema-reference.md` (generated).

#### Scenario: One command per turn
- **WHEN** a turn is accepted
- **THEN** exactly one `coach_commands` row exists for its `client_turn_id` with status `queued`, `running` or `completed`; its `intent` holds `{"allow_mutations": bool}` and its `receipt` the JSON receipt of CC9b and CC11; a failed or cancelled turn is stored as `completed` with `receipt.status` `failed` or `cancelled`

#### Scenario: Messages, drafts and entries
- **WHEN** Coach state is stored
- **THEN** `messages` holds the chat (`role` user or assistant, `content`, `client_turn_id`, attachments), `coach_plan_artifacts.status` is `draft`, `committed` or `superseded`, and the key-value entries are `coach_pending_request` (CC6), `chat_generation`, `openai_conversation_id`, `last_chat_reset_at`, `last_coach_ai_provider`, `morning_checkin_date`, `morning_checkin_status` and the selections `selected_model_openai`, `selected_thinking_level`, `selected_service_tier` (MU1 to MU3)

#### Scenario: Chat reset
- **WHEN** the chat is reset
- **THEN** in one transaction every message is deleted, open commands become `completed` with receipt status `cancelled` and phase `chat_reset`, open remote and local write proposals are cancelled, draft plan artifacts become `superseded`, the pending request and the provider conversation reference are cleared, and a new `chat_generation` and `last_chat_reset_at` are stored

Evidence: `backend/db/schema.py` (tables `messages`, `coach_commands`, `coach_action_proposals`, `coach_plan_artifacts`), `backend/coach/job_submission.py:CoachJobSubmissionService._persist`, `backend/coach/conversation.py:CoachConversationResetService._reset_local`, `backend/coach/morning_completion.py:MorningCoachJobCompletionService.complete`, `backend/coach/final_receipt.py:CoachFinalReceiptService.persist`, `backend/settings.py:SettingsService`; `tests/test_coach_conversation_reset.py`, `tests/test_coach_job_store.py`.

### Requirement: CC14 Composer states while the Coach works
The client SHALL show the working state of a turn, offer a retry on a failed answer and bound its queue of follow-ups.

#### Scenario: Working labels and polling
- **WHEN** a turn runs
- **THEN** the indicator reads "Coach arbeitet an deiner Antwort…", "Der Coach arbeitet · du kannst die Seite neu laden…" for a background job, "Verbindung unterbrochen · die Antwort wird im Hintergrund fertiggestellt…" after a lost stream and "Antwort wird sicher übernommen…" while the receipt is read; a stream silent for 45 seconds is aborted and the client polls the status, and while a job is active it polls at least every 15 seconds

#### Scenario: Failed answer
- **WHEN** the newest answer belongs to a failed turn whose request had text and no attachments
- **THEN** it offers "Erneut senden", which sends the text with its quick-action kind as a new turn

#### Scenario: Queue limits
- **WHEN** queued follow-ups would hold more than 16,000,000 characters of encoded attachment data, or the athlete resets the chat while messages are queued
- **THEN** the message is refused with "Die Warteschlange enthält bereits zu viele Bilddaten. Warte auf die laufende Coach-Antwort." or the reset with "Bitte warte, bis die wartenden Nachrichten gesendet sind. Danach kannst du den Chat zurücksetzen."

Evidence: `public/coach.js:CHAT_STREAM_SILENCE_MS`, `public/coach.js:CHAT_STATUS_SAFETY_POLL_MS`, `public/coach.js:MAX_QUEUED_ATTACHMENT_BYTES`, `public/coach.js:queueChatMessage`, `public/coach.js:appendFailedTurnRetry`, `public/coach.js:resetCoachChat`; `tests/coach-recovery-queue.test.cjs:a message sent while a chat recovers is queued with its attachments`, `tests/coach-stream-silence.test.cjs:the silence window is three missed heartbeats`, `tests/test_coach_turn_failures.py:test_failed_quick_action_keeps_its_kind_for_the_retry`, `e2e/coach-queue.spec.js`.
