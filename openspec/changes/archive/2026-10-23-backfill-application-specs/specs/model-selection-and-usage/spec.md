## Purpose

Describe the application's selected OpenAI Responses model, reasoning and speed settings, compatible endpoint behavior, durable daily token usage and safe provider status. No monetary cost ledger was found in the inspected usage implementation; billing estimation is not asserted.

## ADDED Requirements

### Requirement: MU1 Explicit persisted model selection
The system SHALL expose endpoint-appropriate model options, persist a supported explicit selection and otherwise use the configured model, with GPT-6 Luna as the current default configuration.

#### Scenario: Official endpoint selection
- **WHEN** the app uses its default official OpenAI base URL
- **THEN** available options include GPT-6 Luna, GPT-6 Sol, GPT-6.1 Sol and GPT-6 Astra, plus a distinct configured model when needed; a saved valid choice is returned on later reads.

#### Scenario: Compatible endpoint
- **WHEN** a nondefault compatible base URL is configured
- **THEN** only its configured model is offered and a stored official-model choice no longer overrides that configured endpoint model.

#### Scenario: Unsupported model or failed settings save
- **WHEN** the athlete submits an unsupported selection
- **THEN** the settings API rejects it without persisting a new model; the client reports save errors rather than silently switching providers.

Evidence: `backend/settings.py:SettingsService._available_model_options`, `backend/settings.py:SettingsService._selected_model`, `backend/settings.py:SettingsService.save_model`; `backend/config.py:load_config`; `backend/http_api/settings_put.py:SettingsPutRoutes.handle`; `public/settings.js:saveModel`; `tests/test_settings.py:test_model_is_persisted_and_save_returns_state`, `tests/test_settings.py:test_invalid_model_is_rejected_without_writes`, `tests/test_settings.py:test_compatible_endpoint_keeps_only_configured_model_and_omits_tier`. Configuration default is source-inspected, not a read of the live environment.

### Requirement: MU2 Validated reasoning settings
The system SHALL expose low, medium and high thinking levels, default to medium when stored state is absent/invalid, normalize explicit saves and propagate reasoning settings to Responses payloads without overwriting explicitly provided reasoning.

#### Scenario: Default or explicit reasoning
- **WHEN** the athlete reads settings without a valid saved thinking level or saves a supported level
- **THEN** medium is the default and a trimmed case-normalized supported value is persisted for future turns.

#### Scenario: Unsupported value
- **WHEN** a level outside low/medium/high is submitted
- **THEN** it is rejected without changing the persisted selection.

#### Scenario: Payload already specifies reasoning
- **WHEN** a Responses request supplies its own reasoning object
- **THEN** payload preparation preserves it; otherwise it supplies the selected effort without mutating the caller's payload.

Evidence: `backend/settings.py:SettingsService.selected_thinking_level`, `backend/settings.py:SettingsService.save_thinking_level`; `backend/providers/openai_requests.py:responses_payload`; `tests/test_settings.py:test_thinking_level_defaults_validates_and_returns_copies`; `tests/test_provider_openai.py:test_responses_payload_defaults_reasoning_and_preserves_explicit_reasoning`, `tests/test_provider_openai.py:test_responses_payload_copies_mapping_without_mutating_it`.

### Requirement: MU3 Model-specific speed selection
The system SHALL expose only service tiers supported by the selected official model, default to fast where supported, persist a valid explicit choice and omit service-tier parameters for compatible/custom models without supported tiers.

#### Scenario: Model capabilities
- **WHEN** GPT-6 Luna or Sol is selected
- **THEN** default/fast are available; GPT-6.1 Sol or Astra additionally expose ultrafast, and invalid saved tiers fall back to the implemented supported default.

#### Scenario: Explicit tier selection
- **WHEN** the athlete saves an offered speed mode
- **THEN** it persists and is included in subsequent supported Responses, stream and background payloads unless the caller explicitly supplied a tier.

#### Scenario: Unsupported or compatible tier
- **WHEN** ultrafast is requested for a model without that capability or a nondefault endpoint is used
- **THEN** unsupported saves fail, compatible endpoint state exposes default only, and transport omits the service-tier parameter.

Evidence: `backend/settings.py:supported_service_tiers`, `backend/settings.py:SettingsService.service_tier`, `backend/settings.py:SettingsService.save_service_tier`; `backend/providers/openai_requests.py:responses_payload`; `backend/providers/model_assembly.py:ModelTransportAssembly`; `tests/test_settings.py:test_speed_defaults_and_model_capabilities`, `tests/test_settings.py:test_compatible_endpoint_keeps_only_configured_model_and_omits_tier`; `tests/test_provider_openai.py:test_responses_payload_applies_speed_to_stream_and_background`, `tests/test_provider_openai.py:test_responses_client_applies_selected_speed_for_payload_model`.

### Requirement: MU4 Responses-only configured transport
The system SHALL send Coach model traffic through the configured Responses API adapter, support a validated compatible base path and reject missing credentials/unsafe base URLs without a provider or Chat Completions fallback.

#### Scenario: Configured endpoint
- **WHEN** a Coach request is sent with a valid configured endpoint and server-side credential
- **THEN** the model request uses `/responses` under that base path and the selected model rather than an alternate provider protocol.

#### Scenario: Unsafe URL
- **WHEN** configuration supplies a non-HTTPS nonloopback URL, embedded credentials, query/fragment or prohibited path traversal segments
- **THEN** configuration rejects it; low-level endpoint joining also rejects credential/query/fragment bases.

#### Scenario: Missing credential
- **WHEN** no model credential is configured
- **THEN** the request fails as unavailable/not-configured with a safe message and no alternative provider call.

Evidence: `backend/coach/response_transport.py:CoachResponseTransport`; `backend/providers/model_assembly.py:ModelTransportAssembly.openai_responses_client`; `backend/config.py:validated_openai_base_url`; `backend/providers/openai_requests.py:OpenAIResponsesClient._require_api_key`, `backend/providers/openai_requests.py:endpoint`; `tests/test_coach_response_transport.py:test_transport_uses_openai_responses_adapter`; `tests/test_provider_openai.py:test_responses_client_requires_api_key`, `tests/test_provider_openai.py:test_endpoint_uses_default_for_empty_base_and_rejects_unsafe_base_urls`. This documents code routing, not an external provider parity probe.

### Requirement: MU5 Durable per-turn model and reasoning identity
The system SHALL store the selected model and thinking level with an accepted background turn and reuse those stored values when resuming it, independently from later model-setting changes.

#### Scenario: Accepted background turn
- **WHEN** a turn is enqueued
- **THEN** its durable receipt records model and thinking level alongside its stored athlete message/session identity.

#### Scenario: Resume existing turn
- **WHEN** the turn resumes after interruption
- **THEN** its existing conversation, stored model and valid stored thinking level are passed into execution rather than silently taking a newly selected model.

#### Scenario: Invalid stored thinking level
- **WHEN** a legacy/malformed stored thinking level is outside low/medium/high
- **THEN** the implemented selected-level fallback is used while preserving a valid stored model and conversation.

Evidence: `backend/coach/job_submission.py:CoachJobSubmissionService._persist`; `backend/coach/chat_turn.py:CoachChatTurnService._model_settings`, `backend/coach/chat_turn.py:CoachChatTurnService._run`; `tests/test_coach_chat_turn.py:test_background_resume_preserves_openai_model_and_conversation`; `tests/test_coach_request_payload.py:test_settings_fallback_and_output_limit`. Service-tier selection is resolved by the current settings adapter and is not asserted to be frozen with the queued turn.

### Requirement: MU6 Bounded stream/background response lifecycle
The system SHALL support streaming and resumable background Responses with validated response IDs, bounded payload/response sizes and deadlines, and cancellation that attempts to stop active provider work.

#### Scenario: New or resumed background response
- **WHEN** background execution starts or resumes a valid stored response ID
- **THEN** it creates with background/store flags or retrieves that response, checkpoints its identity and polls queued/in-progress states with bounded backoff/deadline.

#### Scenario: Cancellation or timeout
- **WHEN** cancellation is signalled or the total background deadline expires
- **THEN** the system attempts provider cancellation and reports cancelled/timeout while preserving the original failure if cancellation itself fails.

#### Scenario: Transient poll failure or oversized stream
- **WHEN** retrieval has a resumable timeout/unavailable/invalid-response failure
- **THEN** the active response remains recoverable; oversized streams fail at the byte bound instead of accepting unbounded provider output.

Evidence: `backend/providers/openai_requests.py:OpenAIResponsesClient.background`, `backend/providers/openai_requests.py:poll_background_response`, `backend/providers/openai_requests.py:response_id`; `backend/providers/openai_stream.py:OpenAIStreamClient`; `tests/test_provider_openai.py:test_poll_background_response_polls_until_terminal_with_casefold_status`, `tests/test_provider_openai.py:test_poll_background_response_keeps_resumable_failures_running`, `tests/test_provider_openai.py:test_poll_background_response_preserves_timeout_when_cancel_fails`, `tests/test_provider_openai.py:test_responses_client_background_deadline_includes_resume_retrieve`, `tests/test_provider_openai.py:test_read_stream_response_rejects_oversized_stream`; `tests/test_coach_response_transport.py:test_background_forwards_resume_id_checkpoint_and_cancel_event`.

### Requirement: MU7 Durable normalized daily token usage
The system SHALL persist daily OpenAI request/input/output/total-token counters and last-operation/time metadata atomically, normalize malformed counters safely and present them as usage counts rather than a monetary bill.

#### Scenario: Successful usage record
- **WHEN** a validated response is accounted
- **THEN** safe nonnegative token counts are added to today's state with one request increment and bounded operation/time metadata, without copying model text or arbitrary response fields.

#### Scenario: New day or malformed state
- **WHEN** stored usage is malformed or belongs to another day
- **THEN** the daily counters start at zero while safe status/rate-limit state remains separately available; an absent total falls back to input plus output.

#### Scenario: Background polling
- **WHEN** a background response is retrieved repeatedly before its terminal result
- **THEN** retrieval alone does not increment usage; the background path records usage after terminal validation, and the UI exposes requests, tokens and last request rather than fabricated monetary costs.

Evidence: `backend/providers/usage.py:daily_summary`, `backend/providers/usage.py:usage_counts`, `backend/providers/usage.py:recorded_usage`; `backend/providers/state.py:ProviderStateService.record_usage`; `backend/providers/openai_requests.py:OpenAIResponsesClient.retrieve`, `backend/providers/openai_requests.py:OpenAIResponsesClient.background`; `public/views.js:renderSettingsUsage`; `tests/test_provider_usage.py:test_daily_summary_decodes_valid_state_and_resets_stale_state`, `tests/test_provider_usage.py:test_usage_counts_supports_openai_wire_shape_and_safe_fallbacks`, `tests/test_provider_usage.py:test_recorded_usage_is_non_mutating_and_returns_only_safe_delta`; `tests/test_provider_state.py:test_usage_accumulates_atomically_and_logs_only_operation_and_counts`; `tests/test_provider_openai.py:test_responses_client_retrieve_validates_without_recording_usage`. This is a daily aggregate, not a per-model cost ledger or global exactly-once billing guarantee across process crashes.

### Requirement: MU8 Safe provider status, error classification and bounded retries
The system SHALL persist safe provider availability/rate-limit state, distinguish actionable protocol/authentication/quota/billing/timeout failures and keep raw provider error text out of user-facing failures and diagnostic markers.

#### Scenario: Valid rate-limit headers
- **WHEN** provider responses include recognized limit/remaining/reset/retry headers
- **THEN** only the allowlisted snapshot is persisted with its update time and unknown remaining values remain unknown in the settings UI.

#### Scenario: Terminal provider failure
- **WHEN** a response reports a failed/cancelled/error state or a recognized authentication/quota/billing failure
- **THEN** safe classified status and an actionable static message are used, with only allowlisted bounded codes/markers rather than echoed raw provider text.

#### Scenario: Retry policy
- **WHEN** a request has a transient conversation lock or an eligible bounded rate-limit retry
- **THEN** only the implemented bounded retry/backoff path runs, cancellation remains effective during waits and a quota/billing error is not silently converted into a provider fallback.

Evidence: `backend/providers/state.py:ProviderStateService.record_status`, `backend/providers/state.py:ProviderStateService.record_rate_limits`, `backend/providers/state.py:ProviderStateService.validate_openai_response`; `backend/providers/openai_responses.py:validate_response`, `backend/providers/openai_responses.py:response_diagnostic_details`; `backend/providers/openai_requests.py:request_with_conversation_retry`; `backend/coach/response_retry.py:CoachResponseRetryPolicy`; `tests/test_provider_state.py:test_rate_limits_are_allowlisted`, `tests/test_provider_state.py:test_openai_response_validation_surfaces_and_persists_billing_failure`; `tests/test_provider_openai.py:test_response_validation_does_not_classify_billing_from_untrusted_text`, `tests/test_provider_openai.py:test_request_with_conversation_retry_retries_lock_with_delays_and_notification`; `tests/test_coach_response_retry.py:test_integer_retry_after_is_used_and_over_budget_is_rejected`.
