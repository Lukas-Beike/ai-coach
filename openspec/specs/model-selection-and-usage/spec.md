# model-selection-and-usage Specification

## Purpose

Describe the application's selected OpenAI Responses model, reasoning and speed settings, compatible endpoint behavior, durable daily token usage and safe provider status. No monetary cost ledger was found in the inspected usage implementation; billing estimation is not asserted.

## Requirements

### Requirement: MU1 Explicit persisted model selection
The system SHALL expose endpoint-appropriate model options, persist a supported explicit selection and otherwise use the configured model, with GPT-6 Luna as the current default configuration.

#### Scenario: Official endpoint selection
- **WHEN** the app uses its default official OpenAI base URL
- **THEN** available options include GPT-6 Luna, GPT-6 Sol, GPT-6.1 Sol and GPT-6 Astra, plus a distinct configured model when needed; a saved valid choice is returned on later reads.

#### Scenario: Compatible endpoint
- **WHEN** a nondefault compatible base URL is configured
- **THEN** only its configured model is offered among the OpenAI options and a stored official-model choice no longer overrides that configured endpoint model.

#### Scenario: Unsupported model or failed settings save
- **WHEN** the athlete submits an unsupported selection
- **THEN** the settings API rejects it without persisting a new model; the client reports save errors rather than silently switching providers.

#### Scenario: Claude families
- **WHEN** the athlete opens Coach & Modell
- **THEN** one grouped list offers the OpenAI models and the Claude families Opus, Sonnet and Haiku, each named with the model it currently resolves to, a family with a rejected newer model shows a short notice, entries whose provider has no key are disabled, and the speed selector is hidden for Claude.

#### Scenario: Claude without a key
- **WHEN** a Claude family is saved while no Anthropic key is configured
- **THEN** the save is rejected without writing.

Evidence: `backend/settings.py:SettingsService._available_model_options`, `backend/settings.py:SettingsService._selected_model`, `backend/settings.py:SettingsService.save_model`, `backend/settings.py:SettingsService.selected_provider`; `backend/config.py:load_config`; `backend/http_api/settings_put.py:SettingsPutRoutes.routes`; `public/settings.js:saveModel`, `public/views.js:renderModel`; `tests/test_settings.py:test_model_is_persisted_and_save_returns_state`, `tests/test_settings.py:test_invalid_model_is_rejected_without_writes`, `tests/test_settings.py:test_compatible_endpoint_keeps_only_configured_model_and_omits_tier`, `tests/test_settings.py:test_claude_families_follow_the_resolver_and_need_their_key`, `tests/settings-hub.test.cjs`. Configuration default is source-inspected, not a read of the live environment.

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
- **THEN** it persists and is included in subsequent supported Responses and stream payloads unless the caller explicitly supplied a tier.

#### Scenario: Unsupported or compatible tier
- **WHEN** ultrafast is requested for a model without that capability or a nondefault endpoint is used
- **THEN** unsupported saves fail, compatible endpoint state exposes default only, and transport omits the service-tier parameter.

Evidence: `backend/settings.py:supported_service_tiers`, `backend/settings.py:SettingsService.service_tier`, `backend/settings.py:SettingsService.save_service_tier`; `backend/providers/openai_requests.py:responses_payload`; `backend/providers/model_assembly.py:ModelTransportAssembly`; `tests/test_settings.py:test_speed_defaults_and_model_capabilities`, `tests/test_settings.py:test_compatible_endpoint_keeps_only_configured_model_and_omits_tier`; `tests/test_provider_openai.py:test_responses_payload_applies_speed_to_stream_and_background`, `tests/test_provider_openai.py:test_responses_client_applies_selected_speed_for_payload_model`.

### Requirement: MU4 Selected-provider transport without cross-provider fallback
The system SHALL send every model request to the provider of the selected model, OpenAI Responses (including a validated compatible base path) or the Anthropic Messages API, reject missing credentials and unsafe base URLs, and never fall back from one provider to the other or to Chat Completions.

#### Scenario: Configured endpoint
- **WHEN** a request is sent for an OpenAI model with a valid configured endpoint and server-side credential
- **THEN** the model request uses `/responses` under that base path and the selected model rather than an alternate provider protocol.

#### Scenario: Claude family selected
- **WHEN** a Coach turn, the write-intent check, a photo analysis or a web search runs with a Claude family selected
- **THEN** the request goes to the Messages API with the family's resolved model, and a failing Claude request is never sent to OpenAI.

#### Scenario: One model seam
- **WHEN** the Coach or the nutrition services ask a model for an answer
- **THEN** they send a neutral `ModelRequest` and receive a `ModelTurn` (text, tool calls, opaque state to replay, usage, stop reason, final text, sources) through the one model transport; only the provider adapters turn them into and out of wire payloads, and no Coach or nutrition code reads provider item types.

#### Scenario: Unsafe URL
- **WHEN** configuration supplies a non-HTTPS nonloopback URL, embedded credentials, query/fragment or prohibited path traversal segments
- **THEN** configuration rejects it; low-level endpoint joining also rejects credential/query/fragment bases.

#### Scenario: Missing credential
- **WHEN** the selected model's provider has no credential
- **THEN** the request fails as not configured with a safe message naming that provider and no other provider is called; the chat shows the missing key instead of accepting a message.

Evidence: `backend/providers/model_assembly.py:ModelTransportAssembly.complete`, `backend/providers/model_assembly.py:ModelTransportAssembly.stream`; `backend/coach/response_transport.py:CoachResponseTransport`; `backend/config.py:validated_base_url`; `backend/providers/openai_requests.py:OpenAIResponsesClient._require_api_key`, `backend/providers/http.py:endpoint`; `backend/providers/model_seam.py:ModelRequest`, `backend/providers/openai_responses_adapter.py`, `backend/providers/claude_messages_adapter.py`, `backend/nutrition/photo.py:NutritionPhotoExtractionService`, `backend/nutrition/web_search.py:NutritionWebSearchService`; `public/coach.js:coachConfigured`; `tests/test_model_transport_assembly.py:test_openai_models_use_the_responses_adapter`, `tests/test_model_transport_assembly.py:test_claude_families_resolve_their_model_without_an_openai_fallback`, `tests/test_coach_response_transport.py`, `tests/test_coach_attachments.py:test_outgoing_wire_payloads_of_representative_turns_are_unchanged`, `tests/test_nutrition_photo_extraction.py`, `tests/test_nutrition_web_search.py`; `tests/test_provider_openai.py:test_responses_client_requires_api_key`, `tests/test_provider_openai.py:test_endpoint_uses_default_for_empty_base_and_rejects_unsafe_base_urls`. This documents code routing, not an external provider parity probe.

### Requirement: MU5 Durable per-turn model and reasoning identity
The system SHALL store the selected model and thinking level with an accepted background turn and reuse those stored values when it is requested again, independently from later model-setting changes.

#### Scenario: Accepted background turn
- **WHEN** a turn is enqueued
- **THEN** its durable receipt records model and thinking level alongside its stored athlete message/session identity.

#### Scenario: Request an existing turn again
- **WHEN** the turn is requested again after interruption
- **THEN** its existing conversation, stored model and valid stored thinking level are passed into execution rather than silently taking a newly selected model.

#### Scenario: Invalid stored thinking level
- **WHEN** a legacy/malformed stored thinking level is outside low/medium/high
- **THEN** the implemented selected-level fallback is used while preserving a valid stored model and conversation.

Evidence: `backend/coach/job_submission.py:CoachJobSubmissionService._persist`; `backend/coach/chat_turn.py:CoachChatTurnService._model_settings`, `backend/coach/chat_turn.py:CoachChatTurnService._run`; `tests/test_coach_chat_turn.py:test_background_resume_preserves_openai_model_and_conversation`; `tests/test_coach_request_payload.py:test_settings_fallback_and_output_limit`. Service-tier selection is resolved by the current settings adapter and is not asserted to be frozen with the queued turn.

### Requirement: MU6 One bounded streaming response lifecycle
The system SHALL send every Coach model request through one streaming transport with bounded payload/response sizes and timeouts, and cancellation that stops the active provider request; turn requests are stateless (`store: false`) and are never created in OpenAI background mode, polled, or resumed by response ID.

#### Scenario: Durable job without an attached client stream
- **WHEN** a durable Coach job requests a response and no client stream is attached
- **THEN** the same streaming transport is used and the text deltas are dropped; when a client stream is attached, the deltas are published to it, and a turn that already reached OpenAI in an earlier attempt publishes none.

#### Scenario: Cancellation
- **WHEN** cancellation is signalled before or during a streamed request
- **THEN** the request stops with the public cancelled error; a cancelled stream without a terminal body records one request with empty usage, and a completed body that arrives after the cancel is still billed.

#### Scenario: Transient failure or oversized stream
- **WHEN** a streamed request fails with a transient timeout, unavailability or network error before any text was shown
- **THEN** the same request is sent again within the bounded retry policy; oversized streams fail at the byte bound instead of accepting unbounded provider output.

#### Scenario: Responses request fields
- **WHEN** the first request of a Coach turn goes to OpenAI
- **THEN** the payload has `model`, `reasoning.effort` when a level is set, `conversation` only for a retained attachment conversation, `instructions`, `input` (the JSON of `dialogue`, `current_message` and `confirmed_steps`, with attachment parts), `tools`, `tool_choice: auto`, `max_output_tokens`, `truncation: auto`, `store` (false unless an attachment conversation is retained), `include: ["reasoning.encrypted_content"]` when stateless, `parallel_tool_calls: false`, `stream: true` and `service_tier` when one applies; follow-up tool rounds send `tool_choice: none` after a question, a cancel or an exhausted tool budget, and their `input` carries the tool outputs (with the earlier items replayed when stateless)

Evidence: `backend/coach/structured_response.py:CoachStructuredResponseService.respond`; `backend/coach/response_transport.py:CoachResponseTransport.stream_request`; `backend/providers/openai_stream.py:OpenAIStreamClient`; `tests/test_coach_structured_response.py:test_request_streams_and_drops_deltas_when_no_stream_is_attached`, `tests/test_coach_structured_response.py:test_job_failure_after_the_response_started_is_requested_again`; `tests/test_coach_background_job.py:test_attached_stream_gets_deltas_until_the_turn_was_requested_once`; `tests/test_server_providers.py:test_responses_stream_request_cancel_before_provider_call_records_cancelled_usage`;, `tests/test_provider_openai.py:test_stream_client_saves_final_response_before_post_read_cancellation` `tests/test_provider_openai.py:test_read_stream_response_rejects_oversized_stream`.

### Requirement: MU7 Durable normalized daily token usage
The system SHALL persist daily OpenAI request/input/output/total-token counters and last-operation/time metadata atomically, normalize malformed counters safely and present them as usage counts rather than a monetary bill.

#### Scenario: Successful usage record
- **WHEN** a validated response is accounted
- **THEN** safe nonnegative token counts are added to today's state with one request increment and bounded operation/time metadata, without copying model text or arbitrary response fields.

#### Scenario: New day or malformed state
- **WHEN** stored usage is malformed or belongs to another day
- **THEN** the daily counters start at zero while safe status/rate-limit state remains separately available; an absent total falls back to input plus output.

#### Scenario: Streamed or failed response
- **WHEN** a streamed response ends completed or failed
- **THEN** its usage is recorded once from the final response (MU6 covers a cancelled stream); the UI exposes requests, tokens and last request rather than fabricated monetary costs.

Evidence: `backend/providers/usage.py:daily_summary`, `backend/providers/usage.py:usage_counts`, `backend/providers/usage.py:recorded_usage`; `backend/providers/state.py:ProviderStateService.record_usage`; `backend/providers/openai_stream.py:OpenAIStreamClient`; `public/views.js:renderSettingsUsage`; `tests/test_provider_usage.py:test_daily_summary_decodes_valid_state_and_resets_stale_state`, `tests/test_provider_usage.py:test_usage_counts_supports_openai_wire_shape_and_safe_fallbacks`, `tests/test_provider_usage.py:test_recorded_usage_is_non_mutating_and_returns_only_safe_delta`; `tests/test_provider_state.py:test_usage_accumulates_atomically_and_logs_only_operation_and_counts`; `tests/test_provider_openai.py:test_stream_client_requires_final_response_and_records_usage_once_on_success`, `tests/test_provider_openai.py:test_stream_client_failed_response_records_its_usage_before_raising`. This is a daily aggregate, not a per-model cost ledger or global exactly-once billing guarantee across process crashes.

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

### Requirement: MU9 Claude Messages adapter behind the model seam
The system SHALL translate a neutral model request into one Anthropic Messages request and its reply into a neutral model turn in a single adapter, so no other code reads Claude's content block types. Tool use SHALL be automatic with at most one call per response, effort SHALL follow the requested reasoning level, and the stable tool list and instructions SHALL be marked for prompt caching.

#### Scenario: Tool round
- **WHEN** a turn continues after a tool call
- **THEN** the request resends the first user message, the earlier assistant content unchanged (thinking signatures included) and all tool results of that round in one user message.

#### Scenario: Images, files and JSON answers
- **WHEN** a request carries images or attachment files or asks for a JSON answer
- **THEN** images become image blocks, files become text document blocks, a schema answer uses the output format, and a plain JSON answer is asked for in the instructions.

#### Scenario: Web search with a schema answer
- **WHEN** a request searches the web and expects a schema-bound answer
- **THEN** it adds the web search server tool (the basic version for Haiku), names the schema in the instructions instead of the output format, and the turn reports the final JSON text and every page read or cited.

#### Scenario: Refusal fallback
- **WHEN** an Opus or Sonnet model is requested
- **THEN** the request asks for the server-side refusal fallback to an older Claude model with its beta header; Haiku requests do not.

Evidence: `backend/providers/claude_messages_adapter.py:request_payload`, `backend/providers/claude_messages_adapter.py:model_turn`; `tests/test_claude_provider.py:ClaudeRequestPayloadTests`, `tests/test_claude_provider.py:ClaudeModelTurnTests`.

### Requirement: MU10 Bounded Claude streaming lifecycle
The system SHALL send every Claude request as one bounded stream with the configured key, API version and timeout, forward visible text as it arrives, stop on cancellation, classify provider failures into safe reasons and record the reported usage once per request. Provider error text and refusal explanations SHALL never reach the athlete or the logs.

#### Scenario: Missing key
- **WHEN** no Anthropic key is configured
- **THEN** the request fails as not configured without contacting the provider.

#### Scenario: Paused search
- **WHEN** the provider pauses a server-side search loop
- **THEN** the paused content is resent as is, at most three times in total.

#### Scenario: Refusal
- **WHEN** the reply ends with a refusal after any fallback
- **THEN** the request fails with a short static message, its usage is billed and the log names the model that answered.

#### Scenario: Failure classification
- **WHEN** the provider answers with an HTTP error or an error event
- **THEN** authentication, unknown model, rate limit, overload, billing and invalid request map to safe reasons with the upstream status and retry delay, without the provider's text.

#### Scenario: Bounds and cancellation
- **WHEN** the stream exceeds the byte limit, ends without its stop event, times out or is cancelled
- **THEN** it fails with the matching safe reason, a cancelled stream is billed with the usage it reported, and the cancellation handle is released.

Evidence: `backend/providers/claude_requests.py:ClaudeMessagesClient`, `backend/providers/claude_requests.py:read_sse_events`, `backend/providers/claude_messages_adapter.py:StreamAssembler`; `tests/test_claude_provider.py:ClaudeStreamClientTests`.

### Requirement: MU11 Newest Claude model per family with a step back
The system SHALL resolve each Claude family (Opus, Sonnet, Haiku) to its newest model from the Models API, listed at most once a day, and remember the last model of each family that answered. When a newly resolved model is rejected as an invalid request or unknown model and the last working model then answers, the family SHALL keep using that model and report the rejected one until a newer model appears.

#### Scenario: Newest model
- **WHEN** the Models API lists several models of a family
- **THEN** the newest plain family model is used; dated snapshots, deployment variants and other families are ignored.

#### Scenario: Listing fails
- **WHEN** the Models API cannot be read
- **THEN** the last known models stay in use, or the built-in current models before the first listing.

#### Scenario: Rejected new model
- **WHEN** the newest model is rejected and the last working model answers the same request
- **THEN** the answer is returned, the new model is marked rejected and later requests use the working model directly.

#### Scenario: No blame without proof
- **WHEN** the rejection is of another kind, no different working model exists, or the working model fails too
- **THEN** the error is raised and nothing is marked rejected.

#### Scenario: Status without provider calls
- **WHEN** the settings read the model in use per family
- **THEN** the stored state answers without a provider request.

Evidence: `backend/providers/claude_models.py:ClaudeModelResolver`, `backend/providers/claude_models.py:newest_by_family`; `tests/test_claude_provider.py:ClaudeModelResolverTests`.

### Requirement: MU12 Separate Claude usage counters
The system SHALL count Claude requests and tokens in their own daily counters, with cache reads and writes included in the input tokens, using the same safe normalization as the OpenAI counters.

#### Scenario: Claude usage
- **WHEN** a Claude request reports usage
- **THEN** the Claude counters add one request and its input, output and total tokens, and the OpenAI counters stay unchanged.

Evidence: `backend/providers/usage.py:usage_counts`, `backend/providers/state.py:ProviderStateService.record_usage`, `backend/providers/claude_messages_adapter.py:neutral_usage`; `tests/test_provider_usage.py`, `tests/test_provider_state.py`.
