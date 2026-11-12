## ADDED Requirements

### Requirement: Claude turns keep the dialogue local
The system SHALL create, bind or rotate no remote conversation for a turn whose model is a Claude family; such a turn SHALL send the bounded local dialogue and its own attachments, and resend its earlier tool rounds within the turn.

#### Scenario: Attachment turn with Claude
- **WHEN** a Claude turn carries an image or file, or follows one within the attachment window
- **THEN** no OpenAI conversation is created, bound or rotated, the attachments of this turn are sent with it, and later turns rely on the local summaries.

Evidence: `backend/coach/structured_turn.py:CoachStructuredTurnService._open_and_request`, `backend/coach/request_payload.py:CoachRequestPayloadService.keeps_remote_conversation`; `tests/test_coach_structured_turn.py:test_a_claude_turn_keeps_attachments_local_and_never_goes_remote`, `tests/test_coach_request_payload.py:test_only_openai_models_keep_a_remote_conversation`.
