## MODIFIED Requirements

### Requirement: Label extraction uses the selected model provider
The system SHALL request packaging-label recognition through the selected model and its provider (OpenAI Responses or the Anthropic Messages API), ask for structured label values, and return a validated candidate. Missing provider configuration or invalid model output SHALL fail without exposing raw provider text or images.

#### Scenario: Read a nutrition label
- **WHEN** a valid image is submitted and the selected model/provider is available
- **THEN** one request to that provider includes the text instruction and transient image, and a JSON candidate is validated before being returned.

#### Scenario: Provider unavailable
- **WHEN** the selected-model or request dependency is unavailable
- **THEN** the service returns a provider-unavailable error rather than choosing a fallback model or provider or persisting the photo.

#### Scenario: Invalid response
- **WHEN** the provider response cannot be read as candidate JSON
- **THEN** the service returns a bounded invalid-response error without echoing the provider's raw response.

Evidence: `backend/nutrition/photo.py::NutritionPhotoExtractionService.extract`, `backend/nutrition/photo.py::NutritionPhotoExtractionService._request_text`, `backend/nutrition/assembly.py::NutritionAssembly._photo_extractor`, `backend/providers/model_assembly.py::ModelTransportAssembly.complete`, `backend/providers/claude_messages_adapter.py::request_payload`; `tests/test_nutrition_photo_extraction.py::NutritionPhotoExtractionTests.test_openai_request_uses_selected_model_transient_image_and_json_candidate`, `tests/test_nutrition_photo_extraction.py::NutritionPhotoExtractionTests.test_invalid_provider_response_fails_without_returning_provider_text_or_image`, `tests/test_claude_provider.py::ClaudeRequestPayloadTests.test_images_and_attachments_become_image_and_document_blocks`.

## RENAMED Requirements

- FROM: `### Requirement: Label extraction uses the selected Responses provider`
- TO: `### Requirement: Label extraction uses the selected model provider`
