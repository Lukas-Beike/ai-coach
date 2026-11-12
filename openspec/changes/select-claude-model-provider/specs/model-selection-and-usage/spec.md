## MODIFIED Requirements

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

## RENAMED Requirements

- FROM: `### Requirement: MU4 Responses-only configured transport`
- TO: `### Requirement: MU4 Selected-provider transport without cross-provider fallback`
