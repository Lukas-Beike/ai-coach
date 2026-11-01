# coach-conversation Specification

## Purpose

Describe the athlete-started Coach dialogue, durable background execution, local history, clarification, cancellation and attachment lifecycle observed at application revision b8c911c9dda83a7920171916ace32681c0c38ba0.

## Requirements

### Requirement: CC1 Durable bounded chat submission
The system SHALL persist a valid athlete message and its background command before accepting the chat request, and SHALL expose its operation identity and queued state.

#### Scenario: Valid authenticated submission
- **WHEN** an authenticated athlete submits a message with a nonempty client turn ID through `/api/chat`
- **THEN** the system stores the message, session-bound command, selected model and thinking level, returns HTTP 202 with the operation ID, and wakes the worker.

#### Scenario: Invalid submission
- **WHEN** the message exceeds 12000 characters, the turn ID is absent or exceeds 120 characters, or the quick-action kind is unsupported
- **THEN** the system rejects the submission without starting model execution.

#### Scenario: Already active session
- **WHEN** the same session submits another turn while its different background turn is queued or running
- **THEN** the system rejects it with a conflict rather than starting concurrent work for that session.

Evidence: `backend/http_api/chat_post.py:ChatPostRoutes.handle`; `backend/coach/job_submission.py:CoachJobSubmissionService.enqueue`, `backend/coach/job_submission.py:CoachJobSubmissionService._persist`; `tests/test_http_chat_post_routes.py:test_chat_submission_uses_bounded_body_and_expected_service_arguments`; `tests/test_coach_chat_turn.py:test_new_turn_validates_and_forwards_exact_session`. Source/test inspection; not a claim that these tests ran.

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
The system SHALL retain background turn checkpoints, resume unfinished work under the stored model and conversation, and distinguish retryable contention from terminal failure.

#### Scenario: Resume after interruption
- **WHEN** a durable turn has a provider response ID or checkpointed tool outputs after worker restart
- **THEN** execution resumes the response or submits the checkpointed outputs, preserving completed tool effects and the original model selection.

#### Scenario: Queue contention
- **WHEN** execution cannot acquire the conversation queue or times out waiting for its slot
- **THEN** the job is requeued with observable background status rather than reported as a completed answer.

#### Scenario: Repeated escaped failure or invalid generation
- **WHEN** a job repeatedly fails outside handled turn processing, or belongs to a reset generation
- **THEN** repeated failures eventually become terminal, while an invalidated job cannot restore its session or recreate deleted dialogue.

Evidence: `backend/coach/background_job.py:CoachBackgroundJobRunner`; `backend/coach/job_worker.py:CoachJobWorker`; `backend/coach/job_store.py:CoachJobStore`; `tests/test_coach_background_job.py:test_queue_contention_requeues_and_emits_background_status`, `tests/test_coach_background_job.py:test_job_that_keeps_failing_is_ended_with_a_terminal_failure`, `tests/test_coach_background_job.py:test_invalidated_generation_never_restores_session_or_writes_failure`; `tests/test_coach_dialogue.py:test_background_resumes_response_and_committed_effect_without_replaying`, `tests/test_coach_dialogue.py:test_background_replays_checkpointed_outputs_before_new_response`.

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

Evidence: `backend/http_api/chat_page.py:ChatHistoryPageService.page`; `backend/coach/conversation.py:CoachConversationHistoryService.page`, `backend/coach/conversation.py:CoachMessageService.list`; `backend/coach/job_submission.py:CoachJobSubmissionService.stream_status`; `tests/test_coach_message_service.py:test_list_preserves_repository_order_limit_and_attachment_names`, `tests/test_coach_message_service.py:test_list_is_read_only_and_does_not_publish_events`; `tests/test_http_coach_get_routes.py:test_history_preserves_decoded_query_values`, `tests/test_http_coach_get_routes.py:test_status_uses_authenticated_csrf_scope`. Cursor/search behavior is implementation-inspected; no paging test was executed in this worker.

### Requirement: CC5 Durable cancellation and truthful partial outcomes
The system SHALL cancel only the session's matching operation, persist cancellation for durable jobs, and retain already committed changes and their receipts when a turn is cancelled or interrupted.

#### Scenario: Active operation cancellation
- **WHEN** the owning session cancels its attached or durable operation
- **THEN** the system records durable cancellation before signalling the background event, closes any provider response handle, and reports cancelling.

#### Scenario: Unknown or mismatched operation
- **WHEN** there is no active operation or the supplied operation ID conflicts with the attached operation
- **THEN** the system reports not-running or a conflict without cancelling another operation.

#### Scenario: Failure after a local write
- **WHEN** a provider summary fails after a tool has committed a local effect
- **THEN** the final failure receipt and answer retain that successful effect and any supported undo references rather than claiming that nothing changed.

Evidence: `backend/coach/cancellation.py:CoachCancellationService.cancel`; `backend/coach/turn_failures.py:CoachTurnFailureService.persist`; `tests/test_coach_cancellation.py:test_background_cancel_persists_before_signalling_and_does_not_recreate_event`, `tests/test_coach_cancellation.py:test_attached_cancel_closes_provider_and_rejects_wrong_operation`, `tests/test_coach_cancellation.py:test_no_active_job_does_not_create_or_write_cancel_state`; `tests/test_coach_dialogue.py:test_summary_failure_preserves_effect_and_replays_receipt`.

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

Evidence: `backend/coach/clarification.py:CoachClarificationService.save_question`; `backend/coach/context_selection.py:_pending_request_is_active`, `backend/coach/context_selection.py:pending_origin_messages`; `backend/coach/tool_execution_service.py:CoachStructuredToolExecutionService.execute`; `tests/test_coach_dialogue.py:test_clarification_service_persists_valid_user_provenance_and_limits`, `tests/test_coach_dialogue.py:test_clarification_service_rejects_unbound_message_ids_without_writing`, `tests/test_coach_dialogue.py:test_cancel_and_chat_reset_close_pending_request`; `tests/test_coach_context_selection.py:test_concise_freeform_answer_retains_an_active_clarification`.

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

Evidence: `backend/coach/attachments.py:validate_attachments`, `backend/coach/attachments.py:model_input`; `backend/coach/job_submission.py:CoachJobSubmissionService._validate_submission`, `backend/coach/job_submission.py:CoachJobSubmissionService._persist`; `backend/coach/conversation.py:CoachConversationProvisionService`; `tests/test_coach_attachments.py:test_attachment_persists_for_worker_without_leaking_into_history`, `tests/test_coach_attachments.py:test_invalid_upload_does_not_create_a_command`, `tests/test_coach_attachments.py:test_attachment_storage_quota_prevents_backup_growth`, `tests/test_coach_attachments.py:test_invalid_attachment_conversation_recovers_gpx_and_future_turns`.

### Requirement: CC9 Athlete-started morning check-in completion
The system SHALL treat the morning quick action as a stored athlete-started turn, prepare configured Garmin sleep and morning battery data before coaching, and mark it ready for the local day only after a completed answer without clarification.

#### Scenario: Configured Garmin and fresh sleep
- **WHEN** the athlete starts the morning quick action with configured Garmin
- **THEN** the system attempts the existing Garmin refresh, verifies today's sleep readiness, refreshes morning Body Battery and then runs the Coach.

#### Scenario: Missing sleep or unconfigured Garmin
- **WHEN** current sleep is unavailable after refresh, or Garmin is unconfigured
- **THEN** missing sleep blocks preparation with an explicit error, while unconfigured Garmin skips that provider preparation.

#### Scenario: Completion versus pending clarification
- **WHEN** the morning turn finishes with a message and no pending clarification
- **THEN** its local-day ready marker and quick-action receipt are persisted; a clarification or yesterday's ready marker does not count as today's completed check-in.

Evidence: `backend/coach/morning.py:ManualMorningCheckinService.prepare`, `backend/coach/morning.py:MorningCheckinStateService.state`; `backend/coach/background_job.py:CoachBackgroundJobRunner._execute`; `backend/coach/morning_completion.py:MorningCoachJobCompletionService.complete`; `tests/test_coach_manual_morning.py:test_fresh_sleep_syncs_then_refreshes_battery`, `tests/test_coach_manual_morning.py:test_missing_or_stale_sleep_raises_without_refreshing_battery`, `tests/test_coach_manual_morning.py:test_unconfigured_garmin_returns_without_reading_or_refreshing`, `tests/test_coach_manual_morning.py:test_yesterday_ready_state_is_projected_as_waiting`; `tests/test_coach_dialogue.py:test_morning_quick_action_stays_pending_while_coach_awaits_clarification`.

### Requirement: CC9a Analysis and planning quick actions
The system SHALL accept only the quick-action kinds `morning_checkin`, `session_analysis`, `progress_review`, `plan_week` and `plan_block`, store the athlete's visible message with the chosen period, select the context sections the kind needs, and append the kind's playbook to the instructions of that turn only. A playbook never authorizes a write.

#### Scenario: Playbook only on its own turn
- **WHEN** a turn carries one of the four analysis or planning kinds
- **THEN** its instructions end with that kind's playbook, while morning check-in and ordinary turns carry none.

#### Scenario: Unknown kind
- **WHEN** a submission names another kind
- **THEN** it is rejected as an unsupported quick action before any turn is stored.

Evidence: `backend/coach/playbooks.py:playbook_for`; `backend/coach/job_submission.py:CoachJobSubmissionService._validate_submission`; `backend/coach/context_selection.py:select_coach_context`; `backend/coach/request_payload.py:compose_model_instructions`; `tests/test_coach_playbooks.py:PlaybookInjectionTests.test_other_turns_carry_no_playbook`, `tests/test_coach_playbooks.py:RequestKindAllowlistTests.test_unknown_kind_is_rejected`.

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
