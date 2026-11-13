# model-selection-and-usage Specification

## Purpose

Describe the application's selected OpenAI Responses model, reasoning and speed settings, compatible endpoint behavior, durable daily token usage and safe provider status. No monetary cost ledger was found in the inspected usage implementation; billing estimation is not asserted.

## Requirements

### Requirement: MU1 Explicit persisted model selection
The system SHALL expose endpoint-appropriate model options, persist a supported explicit selection and otherwise use the configured model, with GPT-6 Luna as the current default configuration.

#### Scenario: Official endpoint selection
- **WHEN** the app uses its default official OpenAI base URL
- **THEN** available options include GPT-6 Luna, GPT-6 Sol, GPT-6.1 Sol and GPT-6 Astra, plus a distinct configured model when needed; a saved valid choice is returned on later reads.

#### Scenario: Ids and stored values
- **WHEN** the athlete saves a model, thinking level or speed (route contracts in `docs/api-routes.md`, generated)
- **THEN** the model ids are `gpt-6-luna` (the default of `OPENAI_MODEL`), `gpt-6-sol`, `gpt-6.1-sol` and `gpt-6-astra` for the official endpoint, plus the configured model when it is none of these, and `claude-opus`, `claude-sonnet` and `claude-haiku`; the model id is trimmed and case-sensitive, the thinking level and speed are lower-cased before the check, and the three values are stored under `selected_model_openai` (for both providers), `selected_thinking_level` and `selected_service_tier` for the conversation task (MU17 adds the other tasks); when a model change leaves a stored speed that the new model does not offer, the stored value stays and requests use `fast` where the model offers it, else no tier

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

#### Scenario: Chat reset beside the model
- **WHEN** the athlete opens "Coach-Modell & Thinking" with an OpenAI model or a Claude family selected
- **THEN** "Chat zurücksetzen" sits below the model selection, no provider connection card offers it, and it asks for confirmation before it posts the confirmed reset with the CSRF token.

Evidence: `backend/settings.py:SettingsService._available_model_options`, `backend/settings.py:SettingsService._selected_model`, `backend/settings.py:SettingsService.save_model`, `backend/settings.py:SettingsService.selected_provider`; `backend/config.py:load_config`; `backend/http_api/settings_put.py:SettingsPutRoutes.routes`; `public/settings.js:saveModel`, `public/views.js:renderModel`, `public/coach.js:resetCoachChat`; `tests/test_settings.py:test_model_is_persisted_and_save_returns_state`, `tests/test_settings.py:test_invalid_model_is_rejected_without_writes`, `tests/test_settings.py:test_compatible_endpoint_keeps_only_configured_model_and_omits_tier`, `tests/test_settings.py:test_claude_families_follow_the_resolver_and_need_their_key`, `tests/settings-hub.test.cjs`, `e2e/contracts.spec.js::chat reset sits with the Coach model and resets with openai selected` and `… with anthropic selected`. Configuration default is source-inspected, not a read of the live environment.

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

Evidence: `backend/settings.py:supported_service_tiers`, `backend/settings.py:SettingsService.service_tier`, `backend/settings.py:SettingsService.save_service_tier`; `backend/providers/openai_requests.py:responses_payload`; `backend/providers/model_wiring.py:build_model_transport`; `tests/test_settings.py:test_speed_defaults_and_model_capabilities`, `tests/test_settings.py:test_compatible_endpoint_keeps_only_configured_model_and_omits_tier`; `tests/test_provider_openai.py:test_responses_payload_applies_speed_to_stream_and_background`, `tests/test_provider_openai.py:test_responses_client_applies_selected_speed_for_payload_model`.

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

Evidence:
- `backend/coach/response_transport.py:CoachResponseTransport`
- `backend/config.py:validated_base_url`
- `backend/nutrition/photo.py:NutritionPhotoExtractionService`
- `backend/nutrition/web_search.py:NutritionWebSearchService`
- `backend/providers/claude_messages_adapter.py`
- `backend/providers/http.py:endpoint`
- `backend/providers/model_seam.py:ModelRequest`
- `backend/providers/model_wiring.py:build_model_transport`
- `backend/providers/openai_requests.py:OpenAIResponsesClient._require_api_key`
- `backend/providers/openai_responses_adapter.py`
- `public/coach.js:coachConfigured`
- `tests/test_coach_attachments.py:test_outgoing_wire_payloads_of_representative_turns_are_unchanged`
- `tests/test_coach_response_transport.py`
- `tests/test_model_transport_wiring.py:test_claude_families_resolve_their_model_without_an_openai_fallback`
- `tests/test_model_transport_wiring.py:test_openai_models_use_the_responses_adapter`
- `tests/test_nutrition_photo_extraction.py`
- `tests/test_nutrition_web_search.py`
- `tests/test_provider_openai.py:test_endpoint_uses_default_for_empty_base_and_rejects_unsafe_base_urls`
- `tests/test_provider_openai.py:test_responses_client_requires_api_key`

This documents code routing, not an external provider parity probe.

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

#### Scenario: Follow-up inside an attachment conversation
- **WHEN** an OpenAI turn follows an upload within the retention window and carries no attachment of its own
- **THEN** its `input` holds only `current_message`, `confirmed_steps`, `current_user_message_id`, `local_date`, `timezone` and `pending_request`, because the retained conversation supplies the dialogue; a turn with attachments sends the full local dialogue as well

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

Evidence:
- `backend/providers/openai_stream.py:OpenAIStreamClient`
- `backend/providers/state.py:ProviderStateService.record_usage`
- `backend/providers/usage.py:daily_summary`
- `backend/providers/usage.py:recorded_usage`
- `backend/providers/usage.py:usage_counts`
- `public/views.js:renderSettingsUsage`
- `tests/test_provider_openai.py:test_stream_client_failed_response_records_its_usage_before_raising`
- `tests/test_provider_openai.py:test_stream_client_requires_final_response_and_records_usage_once_on_success`
- `tests/test_provider_state.py:test_usage_accumulates_atomically_and_logs_only_operation_and_counts`
- `tests/test_provider_usage.py:test_daily_summary_decodes_valid_state_and_resets_stale_state`
- `tests/test_provider_usage.py:test_recorded_usage_is_non_mutating_and_returns_only_safe_delta`
- `tests/test_provider_usage.py:test_usage_counts_supports_openai_wire_shape_and_safe_fallbacks`

This is a daily aggregate, not a per-model cost ledger or global exactly-once billing guarantee across process crashes; MU16 keeps the per-turn usage per model.

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

### Requirement: MU13 Retry, timeout and output limits of Coach requests
The system SHALL apply the retry, timeout and output limits of the scenarios to every streamed Coach model request, and SHALL stop every wait on cancellation.

#### Scenario: Transient failure before any output
- **WHEN** a request fails with `provider_unavailable`, `network_error`, `provider_timeout`, or `response_failed` with the provider code `server_error`, no text was shown and the turn keeps no remote conversation
- **THEN** it is repeated after about 2 and then 5 seconds (plus up to 1 second), at most 3 attempts in total

#### Scenario: Rate limit
- **WHEN** the provider reports `rate_limit_exceeded` before any text
- **THEN** the request waits for the given retry-after when it is at most 60 seconds, else 5 seconds times the attempt number, for at most 2 retries, and a longer retry-after ends the turn; a `Retry-After` header counts only as a number, rounded up and limited to 1 to 86,400 seconds

#### Scenario: Reasoning used the whole output budget
- **WHEN** a response ends incomplete for the output limit with neither text nor a tool call, nothing was shown, no provider-side conversation holds the turn and the request allowed fewer than 32,000 tokens
- **THEN** it is repeated once with 32,000 tokens, which consumes no transport retry; the default limit is 16,000 output tokens

#### Scenario: Timeouts, sizes and locked conversations
- **WHEN** a request waits, streams or meets a locked remote conversation
- **THEN** a streamed response may be silent for at most 600 seconds between two parts (else 504 `provider_timeout`) and is limited to 10,000,000 bytes (else 502 `response_too_large`), a plain request (the impact classifier, remote conversation create and delete) times out after 180 seconds, and a locked remote conversation is tried again after 1 and 2 seconds, 3 attempts in all

Evidence: `backend/coach/response_retry.py:CoachResponseRetryPolicy`, `backend/coach/structured_response.py:CoachStructuredResponseService.respond`, `backend/coach/limits.py:COACH_DEFAULT_MAX_OUTPUT_TOKENS`, `backend/coach/limits.py:COACH_LONG_PLAN_MAX_OUTPUT_TOKENS`, `backend/providers/openai_errors.py:retry_after_seconds`, `backend/providers/openai_requests.py:request_with_conversation_retry`, `backend/providers/model_wiring.py:build_model_transport`, `server.py:OPENAI_RESPONSE_TIMEOUT_SECONDS`, `server.py:OPENAI_REQUEST_TIMEOUT_SECONDS`; `tests/test_coach_structured_response.py:test_retries_stay_within_three_attempts`, `tests/test_coach_structured_response.py:test_reasoning_only_token_exhaustion_repeats_with_the_larger_budget`, `tests/test_coach_response_retry.py:test_integer_retry_after_is_used_and_over_budget_is_rejected`, `tests/test_provider_openai.py:test_request_with_conversation_retry_retries_lock_with_delays_and_notification`.

### Requirement: MU14 OpenAI failure classification and provider status
The system SHALL classify an OpenAI HTTP error into one safe reason with a fixed German message, in a fixed order and without echoing provider text, and SHALL keep one safe status record per provider.

#### Scenario: Classification order
- **WHEN** an OpenAI request answers with an error
- **THEN** the reason is chosen in this order: `conversation_locked`; `conversation_state_invalid` (an invalid continuation or tool-output state); the billing reasons `credit_balance_exhausted`, the spend and usage limit codes and `insufficient_quota`, before any rate limit; `rate_limit_exceeded` (HTTP 429 or the rate-limit code or type); `authentication_or_permission` (401, 403, invalid key, organization or permission); `not_found` (404 or an unknown model); `provider_unavailable` (500 and above); else `http_error` with "OpenAI konnte die Anfrage nicht verarbeiten (HTTP <n>)."; the fixed messages are normative in `_openai_error_reason`, and the explanation shown for a failed turn is the mapping of CC11

#### Scenario: Status record
- **WHEN** a request succeeds or fails
- **THEN** the key `openai_status` (`anthropic_status` for Claude) holds `{state, reason, message (at most 300 characters), http_status, updated_at}` and, for OpenAI only from an allowlist, `provider_error_code`; a success writes `state: ok`, `reason: ok` and "OpenAI ist verfügbar." ("Claude ist verfügbar."); state, reason and operation names must match `[a-z0-9][a-z0-9_.:/-]{0,79}`, else they read `unknown`; daily usage lives under `openai_usage` and `anthropic_usage` and the rate-limit snapshot under `openai_rate_limits`

Evidence: `backend/providers/openai_errors.py:_openai_error_reason`, `backend/providers/openai_errors.py:error_details`, `backend/providers/state.py:ProviderStateService.record_status`, `backend/providers/state.py:ProviderStateService.record_success`; `tests/test_provider_state.py:test_status_is_normalized_and_provider_code_is_allowlisted`, `tests/test_provider_state.py:test_openai_response_validation_surfaces_and_persists_billing_failure`, `tests/test_coach_turn_failures.py:test_openai_billing_failure_is_a_persisted_actionable_chat_message`.

### Requirement: MU15 OpenAI stream events, transport errors and usage operations
The system SHALL read a streamed Responses answer as server-sent events up to the byte limit, map transport failures to fixed reasons and count every OpenAI request in the daily usage under an operation name.

#### Scenario: Events
- **WHEN** a stream is read
- **THEN** an event ends at a blank line and takes its kind from the `event:` line or the JSON `type`; `response.created` and `response.in_progress` report the response id, `response.output_text.delta` with a non-empty string reports answer text, and `error`, `response.completed`, `response.incomplete` and `response.failed` end the stream with the event's response (the event itself for `error`); `[DONE]` is ignored; data that is no JSON object fails with 502 `invalid_response` "OpenAI hat ein ungültiges Streaming-Ereignis zurückgegeben."

#### Scenario: Transport failures
- **WHEN** a stream request fails
- **THEN** a missing key is 503 `not_configured`, a stream without a final event 502 `invalid_response` "OpenAI hat keine vollständige Streaming-Antwort zurückgegeben.", more bytes than the limit 502 `response_too_large` "Die Streaming-Antwort von OpenAI ist zu groß.", a timeout 504 `provider_timeout` "OpenAI hat nicht rechtzeitig geantwortet.", a network error 503 `provider_unavailable` "OpenAI ist vorübergehend nicht verfügbar." and any of them after a cancel 499 `chat_cancelled`; a busy local database is passed on unchanged

#### Scenario: Usage operations
- **WHEN** usage is recorded
- **THEN** the operation is `responses_stream` for a stream that ended completed or incomplete, `responses_stream_failed` for one that ended with a failed body, `responses_stream_cancelled` for a cancelled or disconnected stream (one request with zero tokens when no body arrived), `responses` for a plain request such as the impact classifier, and `transcription` for a voice note

Evidence: `backend/providers/openai_events.py:consume_sse_event`, `backend/providers/openai_events.py:_decode_sse_event`, `backend/providers/openai_stream.py:OpenAIStreamClient`, `backend/providers/openai_stream.py:OpenAIStreamTelemetry`, `backend/providers/openai_requests.py:OpenAIResponsesClient`, `backend/providers/usage.py`; `tests/test_provider_openai.py:test_consume_sse_event_returns_all_final_response_states`, `tests/test_provider_openai.py:test_stream_client_timeout_network_and_client_disconnect_contracts`, `tests/test_provider_openai.py:test_read_stream_response_rejects_oversized_stream`, `tests/test_provider_openai.py:test_stream_client_requires_final_response_and_records_usage_once_on_success`.

### Requirement: MU16 Usage per Coach turn and monthly view
The system SHALL sum the usage of every provider request recorded during a Coach turn (tool rounds, the impact classifier, the product web search, failed and cancelled requests included) into the turn's receipt next to its model, with the same counts per requested model, and show the current month's answers and tokens per model.

#### Scenario: Turn usage
- **WHEN** a Coach turn completes, fails or is cancelled
- **THEN** its receipt keeps `usage` with `requests`, `input_tokens` (Claude cache reads and writes included), `cached_input_tokens` and `output_tokens`; a resumed background turn continues the usage its receipt kept, and no text or provider payload is copied

#### Scenario: Monthly view
- **WHEN** the bootstrap is read
- **THEN** `usage_month` holds the athlete's local month and, per model, the finished turns started in it that carry usage, with summed tokens and the answers among them (failed and cancelled turns add tokens, no answer); a turn's answer counts under its model and its tokens under the model of each request (`usage.by_model`; a request of unknown model, or a receipt from before that map, counts under the turn's model); older turns without usage are left out, and Mehr › Coach › Verbrauch shows them as a table below today's counters

Evidence: `backend/providers/state.py:metered_turn`, `backend/providers/state.py:ProviderStateService.record_usage`, `backend/coach/final_receipt.py:CoachFinalReceiptService.build`, `backend/coach/turn_failures.py`, `backend/coach/receipt_reads.py:monthly_turn_usage`, `backend/db/coach_store.py:monthly_usage_rows`, `public/views.js:renderUsageMonth`; `tests/test_provider_state.py:test_metered_turn_adds_every_recorded_call_of_both_providers`, `tests/test_coach_final_receipt.py:test_month_sums_turns_with_usage_per_model_in_local_time`, `tests/test_coach_turn_failures.py:test_failed_and_cancelled_turns_keep_the_usage_they_spent`.

### Requirement: MU17 Explicit model and thinking level per task
The system SHALL let the athlete choose one model and one thinking level for each of three tasks, with no automatic routing by detected purpose and no fallback between providers: conversation (free chat, morning check-in, meal photos in chat), planning and analysis (the quick actions `plan_week`, `plan_block`, `adjust_week`, `block_review`, `progress_review`, `session_analysis`), and nutrition (the label photo and the product web search).

#### Scenario: Nothing chosen per task
- **WHEN** no planning or nutrition choice is stored, or the stored model is no longer offered
- **THEN** that task uses the conversation model and thinking level, so an upgrade changes no behavior

#### Scenario: Saving a task choice
- **WHEN** the athlete saves a model or thinking level with `task` `planning` or `nutrition`
- **THEN** it is validated like the conversation choice, a model needs its provider's key, and it is stored under `selected_model_<task>` or `selected_thinking_level_<task>`; an unknown task is rejected with "Unbekannte Coach-Aufgabe." without writing

#### Scenario: Turn and helper routing
- **WHEN** a Coach turn is enqueued or a nutrition helper calls the model
- **THEN** a quick-action turn records the planning model and thinking level in its receipt, every other turn the conversation ones, and the label photo and product web search use the nutrition model, the photo with the nutrition thinking level and the web search with its fixed low effort; the bootstrap and the diagnostic report list each task's choice under `model.tasks` and `configuration.tasks`, the bootstrap with `ready` when that task's provider has its key

#### Scenario: Settings and answers
- **WHEN** the athlete opens "Coach-Modell & Thinking" or reads the chat
- **THEN** one block per task shows a model and a thinking select, the speed select stays below them while any task uses an OpenAI model and offers the speeds those models support (each request keeps only the speeds its own model supports), each task block shows the notice of its own rejected Claude model, a task whose provider has no key disables only its entry points (planning: the "Analyse & Plan" quick actions, which also stay usable while only the conversation lacks its key; nutrition: the label photo; conversation: the chat), and each Coach answer shows the model that wrote it (`coach_model`)

Evidence: `backend/settings.py:SettingsService.task_settings`, `backend/coach/job_submission.py:CoachJobSubmissionService._model_settings`, `backend/nutrition/wiring.py:build_nutrition`, `backend/db/repositories.py:_message_view`, `public/views.js:renderModel`, `public/coach.js:renderMessageNode`; `tests/test_settings.py:test_each_task_has_its_own_choice_and_falls_back_to_the_conversation`, `tests/test_coach_playbooks.py:test_quick_actions_use_the_planning_model_and_the_rest_the_conversation`, `tests/test_nutrition_wiring.py:test_label_photo_uses_the_nutrition_model_and_thinking`, `tests/test_coach_turn_failures.py:test_reloaded_reply_names_the_model_that_wrote_it`, `tests/settings-hub.test.cjs:a quick action needs the planning model's key, the morning check-in the chat's (#2639)`, `e2e/model-settings.spec.js`.
