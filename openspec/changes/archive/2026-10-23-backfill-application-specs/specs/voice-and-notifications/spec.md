## Purpose

Describe optional microphone transcription and browser-local PWA notifications at application revision `b8c911c9dda83a7920171916ace32681c0c38ba0`. This baseline inspects client capture, the authenticated transcription route/provider assembly, notification state and the service-worker click handler. It does not promise a server push service, subscription endpoint, closed-app scheduled delivery, or persisted audio. Coach turn sending and safe shell interaction are in `web-pwa-and-accessibility`; session/cache invalidation is in `view-refresh-and-client-state`. Named browser tests are inspected evidence, not an executed permission/device matrix.

## ADDED Requirements

### Requirement: Microphone access is optional and explicitly started
The client SHALL request microphone capture only after the athlete activates voice input and only when a secure context and recording APIs are available. Unsupported or denied access SHALL leave typed chat usable and report a specific failure state.

#### Scenario: Start recording
- **WHEN** the athlete activates voice input in a supported secure browser and grants access
- **THEN** the client requests audio capture, selects a supported recording MIME type when advertised, and displays recording state and a stop control.

#### Scenario: Insecure or unsupported context
- **WHEN** the secure-context, microphone, or recording API prerequisite is absent
- **THEN** the client explains the requirement without requesting capture or disabling ordinary text chat.

#### Scenario: Permission denied or duplicate start
- **WHEN** access is denied, acquisition fails, or the athlete activates voice while capture acquisition/transcription is already pending
- **THEN** denied/failed capture reports its state and releases resources, while duplicate acquisition/transcription is not started.

Evidence: `public/coach.js::toggleVoiceInput`, `public/coach.js::updateVoiceButton`, `public/coach.js::VOICE_MIME_TYPES`; `e2e/contracts.spec.js::voice input records a follow-up while the Coach is working`, `e2e/audit-remediation.spec.js::late microphone permission after logout stops and discards capture`. Unsupported/denied-permission branches are source-inspected evidence; no dedicated permission-denial browser run was performed here.

### Requirement: Recording is bounded and session-scoped
The client SHALL stop voice recording when its periodic duration check reaches sixty seconds, stop tracks when capture ends, and discard late capture/transcription work after a session change. Captured audio SHALL remain transient in browser memory rather than being written to device storage.

#### Scenario: Stop manually or at the duration cap
- **WHEN** the athlete stops recording or the elapsed duration reaches sixty seconds
- **THEN** the recorder stops, captured chunks form one transient audio blob, and capture timers/tracks are released before transcription proceeds.

#### Scenario: Empty or failed recording
- **WHEN** recording produces no bytes or emits a recorder error
- **THEN** an empty/failed recording message is shown and the microphone resources are released without submitting an empty Coach message.

#### Scenario: Logout while acquiring capture
- **WHEN** microphone permission resolves after login/session state has changed
- **THEN** the returned stream's tracks are stopped and no previous-session recording or transcript enters the new session.

Evidence: `public/coach.js::VOICE_MAX_DURATION_MS`, `public/coach.js::stopVoiceCapture`, `public/coach.js::toggleVoiceInput`, `public/auth.js::showLogin`; `e2e/audit-remediation.spec.js::late microphone permission after logout stops and discards capture`, `e2e/contracts.spec.js::delayed receipt and transcription cannot alter a new session`. The sixty-second timer, empty/error branches, and absence of audio storage were statically inspected; wall-clock capture was not exercised.

### Requirement: Voice transcript is an editable unsent draft
The client SHALL insert a successful transcription into the current draft for review and SHALL not send it automatically. Voice input SHALL remain available for preparing a follow-up while a Coach turn is working.

#### Scenario: Existing text draft
- **WHEN** transcription returns nonempty text while a typed draft already exists
- **THEN** the transcript is appended on a new line, draft state is updated, and the athlete is asked to review and send it.

#### Scenario: Coach is busy
- **WHEN** the athlete records a follow-up during an active Coach turn
- **THEN** the transcript remains editable and the normal explicit send/queue control governs sending it.

#### Scenario: Empty, failed, or superseded transcription
- **WHEN** transcription returns no text, fails, times out, or resolves for an old session
- **THEN** the client shows a current-session error or ignores the obsolete result; it does not insert an invented transcript or overwrite a new session's draft.

Evidence: `public/coach.js::transcribeVoice`, `public/shared.js::apiAudio`, `public/api.js::audio`; `e2e/contracts.spec.js::voice input records a follow-up while the Coach is working`, `e2e/contracts.spec.js::delayed receipt and transcription cannot alter a new session`, `tests/test_provider_audio.py::AudioProviderTests.test_empty_or_invalid_provider_responses_are_rejected`.

### Requirement: Transcription uploads use the protected bounded HTTP path
The system SHALL process transcription through the authenticated CSRF-protected POST boundary, reject unsupported or incomplete audio uploads before provider dispatch, and enforce the configured audio body limit of eight million bytes.

#### Scenario: Valid audio upload
- **WHEN** an authenticated, CSRF-valid caller submits supported audio with a valid declared body length
- **THEN** the route reads the bounded bytes once and returns the transcription client's result.

#### Scenario: Invalid upload
- **WHEN** the body is empty, oversized, truncated, has invalid length, or has an unsupported audio MIME type
- **THEN** request validation fails before provider dispatch with the corresponding validation/size/type error.

#### Scenario: Missing session, CSRF, or maintenance availability
- **WHEN** transcription lacks the required authorization or occurs during a blocked maintenance operation
- **THEN** the shared request boundary rejects/pauses the operation before accepting a durable effect; transcription does not bypass the common boundary.

Evidence: `backend/http_api/handler.py::RequestHandler.do_POST`, `backend/http_api/requests.py::read_audio_body`, `backend/http_api/transcribe_post.py::TranscribePostRoutes.handle`, `server.py::MAX_AUDIO_BODY_BYTES`; `tests/test_http_transcribe_post.py::TranscribePostRoutesTests.test_success_dispatches_audio_to_transcription_client`, `tests/test_http_transcribe_post.py::TranscribePostRoutesTests.test_body_validation_error_stops_before_provider_dispatch`, `tests/test_provider_audio.py::AudioProviderTests.test_validation_precedes_provider_io_and_keeps_order`. Shared auth/maintenance behavior is source-inspected; the route-unit tests do not exercise socket authentication.

### Requirement: Audio provider requests retain only validated transcript output
The system SHALL validate nonempty bounded audio and supported type before contacting the configured transcription provider, use the configured model and compatible base endpoint, and return only trimmed nonempty transcript text. It SHALL not persist audio or expose the raw provider payload through this use case.

#### Scenario: Configured compatible endpoint
- **WHEN** a valid recording is transcribed
- **THEN** the request uses the configured transcription model, German language hint, MIME-appropriate file suffix, multipart audio body, configured timeout, and server-side authorization.

#### Scenario: Missing provider configuration
- **WHEN** valid audio is supplied without the configured provider key
- **THEN** the service returns a not-configured failure and performs no provider request; invalid local audio still fails local validation first.

#### Scenario: Invalid provider output
- **WHEN** provider output is missing text, nonobject, or contains only whitespace
- **THEN** the service returns a transcription failure instead of claiming success; valid text is trimmed and returned as `transcript`.

Evidence: `backend/providers/audio.py::AudioTranscriptionClient.transcribe`, `backend/providers/audio.py::normalized_audio_type`, `server.py` (provider assembly with `AudioTranscriptionSettings`); `tests/test_provider_audio.py::AudioProviderTests.test_openai_transcription_preserves_input_and_wire_contract`, `tests/test_provider_audio.py::AudioProviderTests.test_key_errors_are_checked_after_local_validation`, `tests/test_provider_audio.py::AudioProviderTests.test_empty_or_invalid_provider_responses_are_rejected`.

### Requirement: Notification permission is opt-in and capability-aware
The client SHALL show whether browser notifications are granted, denied, unsupported, or not enabled, and SHALL request permission only after the athlete explicitly activates the enable control.

#### Scenario: Athlete enables notifications
- **WHEN** the athlete selects the enable action in a supporting browser
- **THEN** the browser permission prompt is requested and the UI updates to the returned permission state.

#### Scenario: Unsupported or denied notifications
- **WHEN** notifications are unsupported or blocked by the browser
- **THEN** the UI shows that status and no delivery attempt is made without granted permission; the rest of the app remains usable.

#### Scenario: Ordinary state render
- **WHEN** state is rendered without an enable action
- **THEN** no permission prompt is raised automatically.

Evidence: `public/notifications.js::notificationPermission`, `public/notifications.js::renderNotificationStatus`, `public/notifications.js::enableNotifications`, `public/notifications.js::showPwaNotification`; `tests/notifications-retry.test.cjs::a successful notification is marked delivered and is not sent again` covers granted delivery. Permission prompting/status projection has source evidence only; a dedicated denied/unsupported permission test is an explicit evidence gap.

### Requirement: State notifications contain minimal private information
The client SHALL derive notifications only from freshly loaded eligible application state with granted permission, use generic competition countdown/sync-attention bodies, and avoid competition names and provider error text in lock-screen notification content.

#### Scenario: Upcoming competition
- **WHEN** fresh state contains a competition zero through three days away
- **THEN** a generic countdown notification identifies today, tomorrow, or days remaining without exposing the competition name.

#### Scenario: Sync failure
- **WHEN** eligible state indicates a sync error
- **THEN** a generic attention notification points to details in the app without copying raw provider error text.

#### Scenario: Cached device snapshot
- **WHEN** previously cached state is shown during startup
- **THEN** snapshot display alone does not produce new notifications; fresh loaded state controls notification eligibility.

Evidence: `public/notifications.js::notifyState`, `public/notifications.js::competitionCountdownText`, `public/state-loader.js::render`; `tests/frontend-write-safety.test.cjs::notification bodies omit competition names and provider error text`, `tests/state-loader-startup.test.cjs::loaded state renders as real data, so it may notify`. There is no server push scheduling or guaranteed closed-app delivery in this inspected flow.

### Requirement: Notification delivery retries are bounded per client lifetime
The client SHALL suppress duplicate successfully delivered notification keys, allow retry after a failed attempt only after thirty seconds, and stop after three attempts for a persistently failing key. Clicking a notification SHALL focus an existing app window or open the app root.

#### Scenario: Successful delivery
- **WHEN** the service-worker registration displays a notification successfully
- **THEN** repeated renders with the same key do not display it again in the current client state lifetime.

#### Scenario: Transient or persistent platform failure
- **WHEN** notification display fails
- **THEN** the key can retry after the delay, a later success ends retries, and persistent failure receives at most three attempts without an unhandled application failure.

#### Scenario: Notification clicked
- **WHEN** the athlete clicks a displayed notification
- **THEN** it closes and the worker focuses an existing window when available, otherwise opens `/`.

Evidence: `public/notifications.js::reserveNotificationAttempt`, `public/notifications.js::showPwaNotification`, `public/service-worker.js` (notificationclick listener); `tests/notifications-retry.test.cjs::a persistently rejecting notification is retried at most three times`, `tests/notifications-retry.test.cjs::renders inside the retry delay do not resend a rejected notification`, `tests/notifications-retry.test.cjs::a transient failure followed by success is delivered once`. Click handling is inspected source only; duplicate suppression is in-memory and does not promise cross-tab/restart delivery deduplication.
