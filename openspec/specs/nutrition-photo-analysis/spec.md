# nutrition-photo-analysis Specification

## Purpose

Describe bounded packaging-label extraction and nutrition-related image intake at application revision `b8c911c9dda83a7920171916ace32681c0c38ba0`. A label extraction is a review candidate, not a durable product or meal. The product and consumption contracts are in `food-catalog-and-meal-library` and `nutrition-diary-and-targets`; general Coach attachment delivery and UI behavior are in `web-pwa-and-accessibility`. Evidence is inspected source and tests unless execution is explicitly recorded in the handoff.

## Requirements

### Requirement: Bounded image preparation precedes client state mutation
The client SHALL validate supported image type and size, decode and bound image dimensions/payload when preparing nutrition images, and release temporary decoding resources. A failed preparation SHALL not leave a partially added attachment or saved product.

#### Scenario: Large valid photo
- **WHEN** a supported JPEG, PNG, or WebP file within the input limit is too large for the outgoing preparation bounds
- **THEN** the client attempts a longest-edge bound of 1600 pixels and successive JPEG qualities to fit 1200000 bytes, or reports that the photo cannot be reduced sufficiently.

#### Scenario: Invalid or unsupported photo
- **WHEN** a file is empty, over fifteen million input bytes, unsupported, or cannot be decoded for label extraction
- **THEN** the client reports a preparation error before applying a label candidate; temporary bitmaps and object URLs are released.

#### Scenario: Small image attachment fallback
- **WHEN** a small image cannot be decoded by the browser but is selected as a general Coach attachment
- **THEN** the existing bounded attachment fallback can retain it for server validation, and a later valid selection remains usable.

Evidence: `public/nutrition.js::prepareNutritionImage`, `public/nutrition.js::resizeNutritionImage`, `public/coach.js::prepareChatAttachment`; `tests/test_nutrition_frontend_contract.py::NutritionFrontendContractTests.test_camera_processing_is_bounded_and_rejects_before_state_mutation`, `e2e/nutrition.spec.js::@responsive a small undecodable image falls back to attachment and allows a valid image afterwards`. Browser decoding behavior is inspected, not executed here.

### Requirement: Server image validation rejects unsupported content before provider I/O
The system SHALL accept packaging-photo data only as supported base64 JPEG, PNG, or WebP data URLs whose decoded nonempty bytes fit five MiB and match the declared image signature.

#### Scenario: Supported image
- **WHEN** the submitted data URL has a valid supported MIME type, base64 encoding, byte size, and file signature
- **THEN** the image can proceed to configured label extraction.

#### Scenario: Remote URL or forged MIME
- **WHEN** the caller supplies a remote image URL, SVG, malformed base64, or bytes inconsistent with the declared MIME type
- **THEN** the request fails before a model request is made.

#### Scenario: Oversized image
- **WHEN** the encoded string or decoded image exceeds the bound
- **THEN** the service reports an image-size error without saving or forwarding the oversized image.

Evidence: `backend/nutrition/photo.py::_image_data`, `backend/nutrition/photo.py::NutritionPhotoExtractionService.extract`; `tests/test_nutrition_photo_extraction.py::NutritionPhotoExtractionTests.test_invalid_photo_and_missing_model_are_rejected_before_network`. Signature and maximum-size branches are also source-inspected; that focused test does not execute every size/signature boundary.

### Requirement: Label extraction uses the selected Responses provider
The system SHALL request packaging-label recognition through the configured selected model and Responses endpoint, ask for structured label values, and return a validated candidate. Missing provider configuration or invalid model output SHALL fail without exposing raw provider text or images.

#### Scenario: Read a nutrition label
- **WHEN** a valid image is submitted and the selected model/provider is available
- **THEN** one Responses request includes the text instruction and transient image, and a JSON candidate is validated before being returned.

#### Scenario: Provider unavailable
- **WHEN** the selected-model or request dependency is unavailable
- **THEN** the service returns a provider-unavailable error rather than choosing a fallback model or persisting the photo.

#### Scenario: Invalid response
- **WHEN** the provider response cannot be read as candidate JSON
- **THEN** the service returns a bounded invalid-response error without echoing the provider's raw response.

Evidence: `backend/nutrition/photo.py::NutritionPhotoExtractionService.extract`, `backend/nutrition/photo.py::NutritionPhotoExtractionService._request_text`, `backend/nutrition/assembly.py::NutritionAssembly._photo_extractor`; `tests/test_nutrition_photo_extraction.py::NutritionPhotoExtractionTests.test_openai_request_uses_selected_model_transient_image_and_json_candidate`, `tests/test_nutrition_photo_extraction.py::NutritionPhotoExtractionTests.test_invalid_provider_response_fails_without_returning_provider_text_or_image`.

### Requirement: Candidate validation preserves uncertainty and label provenance
The system SHALL normalize label candidate fields, retain unreadable nutrient/basis values as null, validate finite nonnegative numbers and supported units, and return label provenance plus a requirement for confirmation.

#### Scenario: Incomplete readable label
- **WHEN** only a nutrition table is readable and the product name or basis is unknown
- **THEN** extraction can return incomplete editable candidate fields without guessing the missing values; saving still requires a valid product name and basis.

#### Scenario: Known nutrient values
- **WHEN** the label supplies calories, macros, sugar, fiber, or salt
- **THEN** valid values are normalized, missing values remain null, and recognized barcode/confidence metadata is bounded.

#### Scenario: Invalid candidate or spoofed persistence fields
- **WHEN** nutrient data is nonfinite, negative, otherwise invalid, or submitted with an image field
- **THEN** invalid values fail and image fields are excluded from the accepted candidate rather than becoming persisted product data.

Evidence: `backend/nutrition/photo.py::validate_packaging_extraction`, `backend/nutrition/photo.py::_validated_number`, `backend/nutrition/catalog.py::ProductCatalogService.normalize_product`; `tests/test_nutrition_products.py::NutritionProductContractTests.test_packaging_extraction_returns_candidate_only_until_confirmation`, `tests/test_nutrition_products.py::NutritionProductContractTests.test_packaging_extraction_rejects_invalid_or_estimated_values`, `e2e/nutrition.spec.js::@responsive packaging extraction requires editable basis values before explicit local save`.

### Requirement: Extraction and review have no implicit durable nutrition effect
The system SHALL return packaging recognition as an editable review candidate without saving a local product, recording a diary entry, or synchronizing to Intervals. Durable product creation SHALL use the separately confirmed product-save action.

#### Scenario: Candidate displayed
- **WHEN** extraction succeeds
- **THEN** the UI displays editable recognized product and basis fields and indicates that confirmation is required.

#### Scenario: Athlete cancels or never saves
- **WHEN** the athlete closes or abandons candidate review
- **THEN** no product or consumption record is created by extraction alone.

#### Scenario: Explicit local save
- **WHEN** the athlete corrects required fields and confirms saving
- **THEN** the client sends the reviewed product definition through the product API without the image payload; diary totals are unaffected.

Evidence: `backend/nutrition/photo_service.py::PhotoExtractionService.extract_packaging_photo`, `backend/http_api/nutrition.py::NutritionPostRoutes._extract_product`, `public/nutrition.js::extractNutritionProduct`, `public/nutrition.js::saveNutritionProduct`; `tests/test_nutrition_products.py::NutritionProductContractTests.test_photo_candidate_is_not_saved_until_explicit_save`, `tests/test_nutrition_product_http_contract.py::NutritionProductHttpContractTests.test_save_product_is_explicit_and_does_not_accept_image_payload`, `e2e/nutrition.spec.js::@responsive packaging extraction requires editable basis values before explicit local save`.

### Requirement: Barcode capture is opt-in and releasable
The client SHALL request barcode camera access only after an explicit scan action, offer a typed-code alternative when unavailable, and stop camera tracks and pending detection when capture closes or the session ends.

#### Scenario: Supported scanner
- **WHEN** a secure context supports barcode detection and camera access is allowed
- **THEN** the client scans supported EAN/UPC formats and performs a product lookup on a detected code without auto-saving it.

#### Scenario: Unsupported or denied camera
- **WHEN** camera/scanner prerequisites are absent or capture fails
- **THEN** the UI explains the failure and retains typed barcode lookup as the alternative.

#### Scenario: Late camera permission after close
- **WHEN** the camera promise resolves after the scan dialog closed or its session was superseded
- **THEN** the newly returned stream is stopped and cannot restart the closed scanner.

Evidence: `public/nutrition.js::scanNutritionBarcode`, `public/nutrition.js::stopNutritionBarcode`, `public/nutrition.js::resetNutritionView`; `tests/test_nutrition_frontend_contract.py::NutritionFrontendContractTests.test_barcode_camera_stops_tracks_on_close_and_start_failure`, `e2e/nutrition.spec.js::@responsive closing the barcode dialog stops a late Android Chromium camera stream`.
