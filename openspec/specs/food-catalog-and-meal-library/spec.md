# food-catalog-and-meal-library Specification

## Purpose

Describe food lookup, permanent lookup mirrors, athlete-confirmed local products, trusted component calculations, and reusable meals. This documentation baseline inspects application revision `b8c911c9dda83a7920171916ace32681c0c38ba0`; cited tests are inspected unless listed as executed in the handoff. Consumption is governed by `nutrition-diary-and-targets`, label extraction by `nutrition-photo-analysis`, and remote diary export by `nutrition-provider-sync`.

## Requirements

### Requirement: Local-first product and barcode lookup
The system SHALL search active saved products before fallback food lookup, return source information, and leave diary totals unchanged by searching. Text lookup SHALL require a meaningful search term and distinguish no match from a failed lookup.

#### Scenario: Known local barcode
- **WHEN** a barcode belongs to an active saved product
- **THEN** the local product is returned with local provenance and no remote food lookup occurs.

#### Scenario: Unknown barcode
- **WHEN** the barcode has no active local match
- **THEN** the database lookup result identifies Open Food Facts, and the result remains a candidate rather than a saved product or consumed meal.

#### Scenario: Flexible text search
- **WHEN** saved name/brand words match in a different order, with supported plural, umlaut, separator, or typo normalization
- **THEN** matching local products are returned while every search term must fit; SQL wildcard characters do not broaden the match.

Evidence: `backend/nutrition/catalog.py::ProductCatalogService.lookup_product`, `backend/nutrition/catalog.py::ProductCatalogService.list_products`, `backend/db/repositories.py::NutritionProductRepository.list`; `tests/test_nutrition_products.py::NutritionProductContractTests.test_barcode_lookup_prefers_local_product_and_never_calls_remote`, `tests/test_nutrition_products.py::NutritionProductContractTests.test_search_tolerates_plurals_umlauts_and_typos_but_needs_every_word`, `tests/test_nutrition_products.py::NutritionProductContractTests.test_unknown_barcode_falls_back_to_food_database_and_labels_source`.

### Requirement: Database foods preserve units and missing values
The system SHALL support the bundled BLS database and explicit Open Food Facts lookup, preserve food identity and source, and calculate only from known quantities in the food's stated unit. Missing nutrients SHALL remain unknown.

#### Scenario: Offline BLS search
- **WHEN** the athlete requests a supported BLS food query
- **THEN** the bundled foods are searchable without a provider call and retain their per-100-unit nutrient values and identity.

#### Scenario: Ambiguous units or missing energy
- **WHEN** calculation uses an incompatible gram/milliliter unit, an unknown basis unit, or a food without calories
- **THEN** calculation is rejected with a specific unit or energy error rather than guessing density or calories.

#### Scenario: Valid recipe calculation
- **WHEN** one through twenty valid ingredient references supply finite positive quantities within the ingredient bound
- **THEN** nutrients are scaled server-side, unknown macros propagate as null, and the result carries frozen food records, quantities, and units.

Evidence: `backend/nutrition/food_database.py::FoodDatabaseService.lookup`, `backend/nutrition/food_database.py::FoodDatabaseService.calculate`, `backend/nutrition/food_database.py::FoodDatabaseService._resolve_ingredient`; `tests/test_food_database.py::FoodDatabaseTests.test_bls_is_complete_offline_and_calculates_edible_grams`, `tests/test_food_database.py::FoodDatabaseTests.test_unknown_macros_are_not_zero_and_units_are_not_guessed`, `tests/test_food_database.py::FoodDatabaseTests.test_untrusted_numbers_and_ingredient_bounds`.

### Requirement: Permanent external-food mirror with honest fallback
The system SHALL keep fetched external foods separately from athlete products and diary entries. Fresh mirrored barcode records SHALL avoid unnecessary provider reads; stale fallback SHALL remain visibly stale when a provider recheck fails.

#### Scenario: Fresh cached barcode
- **WHEN** a stored barcode record is younger than ninety days
- **THEN** lookup uses the local database entry and returns its stored-time provenance.

#### Scenario: Stale record during outage
- **WHEN** a stale barcode record exists and the provider recheck fails
- **THEN** the stored food remains usable with stale-origin notice rather than being marked freshly fetched.

#### Scenario: Forget a mirrored food
- **WHEN** the athlete explicitly confirms removal of a database entry
- **THEN** only that mirrored record is removed; product definitions and consumed snapshots remain independent, and a missing record produces a not-found error.

#### Scenario: Repeated mirrored food
- **WHEN** another successful lookup stores the same external food identity
- **THEN** its mirror record and fetched time are refreshed without creating a second food identity or consumed meal.

Evidence: `backend/nutrition/food_mirror.py::FoodDatabaseMirror.is_fresh`, `backend/nutrition/food_database.py::FoodDatabaseService._off_product`, `backend/nutrition/food_database.py::FoodDatabaseService.forget`, `backend/http_api/nutrition.py::NutritionPostRoutes._forget_database_food`; `tests/test_food_database_mirror.py::FoodMirrorTests.test_entries_expire_after_ninety_days`, `tests/test_food_database_mirror.py::FoodDatabaseServiceMirrorTests.test_offline_lookup_falls_back_to_the_stale_entry_with_a_notice`, `tests/test_nutrition_product_http_contract.py::NutritionProductHttpContractTests.test_database_entry_removal_requires_confirmation`. Mirror storage failures are suppressed so a successful lookup can still return its result.

### Requirement: Confirmed product persistence and explicit archival
The system SHALL require explicit confirmation at product HTTP save, update, archive, and mirror-removal boundaries. Products SHALL retain basis amount/unit, validated nutrient values, source, and provenance without retaining submitted image fields.

#### Scenario: Save and read a confirmed product
- **WHEN** the athlete confirms a valid product definition
- **THEN** it becomes a persistent local product available to later lookup and consumption, with unknown nutrients retained as null.

#### Scenario: Unconfirmed or conflicting save
- **WHEN** confirmation is absent or an EAN is already assigned to another product, including an archived one
- **THEN** saving fails before creating the conflicting product.

#### Scenario: Archive by identity
- **WHEN** the athlete confirms archival of an existing product
- **THEN** it is excluded from normal active listings and cannot be consumed anew; historical meals keep their prior snapshots.

Evidence: `backend/http_api/nutrition.py::NutritionPostRoutes._save_product`, `backend/http_api/nutrition.py::NutritionPutRoutes.handle`, `backend/nutrition/catalog.py::ProductCatalogService.save_product`, `backend/nutrition/catalog.py::ProductCatalogService.archive_product`; `tests/test_nutrition_products.py::NutritionProductContractTests.test_confirmed_product_is_persistent_and_can_be_archived`, `tests/test_nutrition_product_http_contract.py::NutritionProductHttpContractTests.test_unconfirmed_product_save_is_rejected_before_persistence`, `tests/test_nutrition_review_regressions.py::NutritionReviewRegressionTests.test_archived_products_cannot_be_calculated_or_logged`.

### Requirement: Product portions freeze consumed definitions
The system SHALL scale a product portion against its saved basis amount in the same unit and freeze the definition and consumed quantity with the meal. Later catalog edits SHALL not recalculate historical intake.

#### Scenario: Scaled portion
- **WHEN** fifty grams are consumed from a product defined per hundred grams
- **THEN** the meal uses half its known calories/macros and retains the consumed product definition and quantity.

#### Scenario: Unit mismatch
- **WHEN** a product is defined in milliliters and consumption is supplied in grams without density
- **THEN** the request fails instead of converting between units.

#### Scenario: Later definition change
- **WHEN** the saved product is edited after consumption
- **THEN** the old entry's values and source snapshot remain unchanged.

Evidence: `backend/nutrition/catalog.py::ProductCatalogService.calculate_product`, `backend/nutrition/diary.py::NutritionDiaryService.log_product`; `tests/test_nutrition_products.py::NutritionProductContractTests.test_product_nutrients_are_snapshotted_when_consumed`, `tests/test_nutrition_products.py::NutritionProductContractTests.test_product_calculation_preserves_unknown_nutrients_and_does_not_convert_units`.

### Requirement: Trusted mixed-origin meal components
The system SHALL calculate composite meals from one through twenty validated local-product, database, manual, estimate, or packaging components. Authoritative references SHALL be resolved server-side and SHALL reject forged totals or provenance supplied alongside components.

#### Scenario: Mixed recipe
- **WHEN** a meal combines active local products, resolved database foods, and explicit manual or estimated components
- **THEN** the server returns totals and a frozen per-component basis identifying each origin, quantity, and unit.

#### Scenario: Invalid component
- **WHEN** a component has extra authoritative fields, an unsupported kind, invalid reference or quantity, unit mismatch, missing energy, or excessive totals
- **THEN** validation fails without partially writing the meal or template.

#### Scenario: Unknown macro in a component
- **WHEN** one component lacks a macro
- **THEN** the full composite macro remains unknown while known component values and provenance stay inspectable.

Evidence: `backend/nutrition/components.py::MealComponentCalculator.calculate`, `backend/nutrition/meal_library.py::validate_component_payload`; `tests/test_nutrition_composition.py::NutritionCompositionTests.test_composite_components_resolve_and_freeze_mixed_sources`, `tests/test_nutrition_composition.py::NutritionCompositionTests.test_composite_rejects_forged_authoritative_values_and_unknown_macros_propagate`, `tests/test_nutrition_composition.py::NutritionCompositionTests.test_composite_limits_validate_before_any_write_and_metadata_preserves_archived_snapshot`.

### Requirement: Reusable meals are independent from consumption
The system SHALL store saved meals separately from diary entries. Saving, changing, or deleting a reusable meal SHALL not itself record consumption or alter historical diary totals.

#### Scenario: Save a reusable definition
- **WHEN** a valid uniquely named meal is saved
- **THEN** it becomes available for later portion logging while the diary remains unchanged.

#### Scenario: Metadata-only update
- **WHEN** the athlete edits a saved meal name or description without changing nutrients or ingredients
- **THEN** omitted values and its existing trusted nutrient basis remain intact.

#### Scenario: Invalid or stale save
- **WHEN** the name is empty, over 120 characters, duplicates another meal case-insensitively, exceeds the 200-meal limit, or an expected calculation changed
- **THEN** the save fails and preserves the existing library.

Evidence: `backend/nutrition/meal_library.py::NutritionMealLibraryService.save_template`, `backend/nutrition/meal_library.py::NutritionMealLibraryService._build_template`, `backend/nutrition/meal_library.py::NutritionMealLibraryService._validate_template_name`; `tests/test_nutrition.py::NutritionRepositoryAndServiceTests.test_template_validation_preserves_state`, `tests/test_nutrition_composition.py::NutritionCompositionTests.test_composite_template_expected_calculation_covers_snapshot`.

### Requirement: Logging saved meals creates independent portion snapshots
The system SHALL create a new diary entry when a saved meal is consumed, scale its values and frozen ingredient quantities by finite positive portions up to twenty, and preserve unknown values and consumption-time semantics.

#### Scenario: Consume multiple portions
- **WHEN** the athlete logs a saved composite meal for two portions
- **THEN** the new entry has independent identity, scaled totals and component quantities, and the selected date.

#### Scenario: No consumption time given
- **WHEN** a saved meal is logged without a time
- **THEN** it retains the template's meal type, records time as unknown, and does not invent a clock-time observation.

#### Scenario: Template changes later
- **WHEN** the saved meal is edited or deleted after logging
- **THEN** previously consumed entries and their nutrient provenance remain unchanged.

Evidence: `backend/nutrition/diary.py::NutritionDiaryService.log_template`, `backend/nutrition/diary.py::NutritionDiaryService._scale_composite_basis`; `tests/test_nutrition.py::NutritionRepositoryAndServiceTests.test_template_without_meal_time_stores_unknown_time_and_keeps_meal_type`, `tests/test_nutrition_composition.py::NutritionCompositionTests.test_component_replacement_metadata_and_template_portion_snapshots`, `tests/test_nutrition_composition.py::NutritionCompositionTests.test_restart_and_database_backup_keep_composite_entries_and_templates`.

### Requirement: Product UI separates review from recording consumption
The client SHALL present product and label candidates for review and explicit local save, and prepare editable Coach drafts for consumption or saved-meal actions. Browsing, candidate review, and draft preparation SHALL not automatically send a Coach turn or export nutrition.

#### Scenario: Use a saved product
- **WHEN** the athlete selects a product and consumed quantity
- **THEN** a Coach draft names the product/quantity for review before the athlete sends it.

#### Scenario: Preserve an existing draft
- **WHEN** a product action would replace an unsent Coach draft
- **THEN** the client asks before discarding that draft and leaves it intact on cancellation.

#### Scenario: Safe ingredient details
- **WHEN** the diary displays a composite meal
- **THEN** expandable details display escaped frozen ingredient names, amounts, origins, and unknown values rather than live catalog recalculations.

Evidence: `public/nutrition.js::useNutritionProduct`, `public/nutrition.js::nutritionComponentDetails`, `public/nutrition.js::saveNutritionProduct`; `e2e/nutrition.spec.js::@responsive nutrition product library supports review, local save, and preserving an existing Coach draft`, `e2e/nutrition.spec.js::@responsive composite meal shows immutable ingredient snapshots and provenance`, `e2e/nutrition.spec.js::@responsive nutrition diary and saved meals remain read-only and preserve confirmed consumption`. These browser scenarios were inspected, not executed by this worker.

### Requirement: Coach food reads preserve explicit source and batch results
The system SHALL support explicit database source selection and bounded batched ingredient lookup through the Coach read interface. Source selection SHALL retain separately labelled matching saved products rather than hiding them or silently replacing the chosen database.

#### Scenario: Explicit database source
- **WHEN** a Coach food query names BLS, Yazio or Open Food Facts
- **THEN** only that database is queried and matching saved products are returned separately; on a database failure, saved matches can remain available with an outage notice.

#### Scenario: Batched ingredients
- **WHEN** one through twenty distinct nonblank ingredient queries are submitted
- **THEN** case-insensitive duplicates are removed in order and each result identifies its query; a failed term does not discard successful terms, while an all-failed batch raises an error.

#### Scenario: Omitted source or invalid batch
- **WHEN** no text source is named, or a batch is malformed, oversized, empty, or combined with a barcode
- **THEN** ordinary lookup retains local-first behavior, with BLS next when Yazio is not configured and the Yazio, Open Food Facts, BLS chain when it is, and invalid batches fail before unbounded lookup work.

### Requirement: Online food lookup is bounded and privacy-conscious
The system SHALL bound Open Food Facts transport and local request rates, separate search and barcode limits, cache successful responses, and return sanitized provider failures. Provider-estimated or modified aggregate nutrient values SHALL not be treated as authoritative label values.

#### Scenario: Repeated or excessive lookup
- **WHEN** the same successful lookup repeats within twenty-four hours or uncached calls exceed the per-minute category limit
- **THEN** cached responses are reused or that category is rate-limited; limiting search does not independently block barcode lookup.

#### Scenario: Provider failure or invalid response
- **WHEN** the provider is unavailable, returns an oversized/truncated/malformed response, or signals backoff
- **THEN** the client receives a bounded database error without query/response disclosure, and applicable backoff remains local to the request category.

#### Scenario: Project label values
- **WHEN** food data uses the supported aggregate or legacy nutrient schema
- **THEN** recognized valid label values and preparation/unit metadata are projected, unknowns stay null, and aggregate estimates/modifiers are excluded rather than promoted to known nutrients.

Evidence: `backend/providers/open_food_facts.py::OpenFoodFactsClient._get`, `backend/providers/open_food_facts.py::OpenFoodFactsClient._request_response`, `backend/providers/open_food_facts.py::project_product`; `tests/test_food_database.py::OpenFoodFactsTests.test_cache_limits_and_privacy_safe_bounded_transport`, `tests/test_food_database.py::OpenFoodFactsTests.test_search_rate_limit_does_not_block_product_lookups`, `tests/test_food_database.py::OpenFoodFactsTests.test_provider_backoff_and_errors_do_not_expose_query_or_response`, `tests/test_food_database.py::FoodDatabaseTests.test_current_off_schema_uses_label_values_and_excludes_provider_estimates`.

### Requirement: Yazio is an optional prioritized external food source
When Yazio is configured and a text or barcode lookup names no source, the system SHALL search saved products first, then Yazio, then Open Food Facts, then BLS for text queries and Yazio then Open Food Facts for barcodes. It SHALL advance to the next source when a source has no suitable match or is unavailable. A saved-product match SHALL prevent every external request. Without Yazio configuration the previous default SHALL apply unchanged.

#### Scenario: Local match
- **WHEN** a saved product matches the lookup
- **THEN** it is returned and no Yazio, Open Food Facts or BLS lookup runs.

#### Scenario: Yazio match
- **WHEN** no saved product matches and Yazio returns a food containing every query word with a known energy value
- **THEN** the Yazio foods are returned with source attribution and Open Food Facts is not queried.

#### Scenario: Fallthrough
- **WHEN** Yazio returns nothing suitable or fails, or Open Food Facts then does the same
- **THEN** the next source in order is used, and BLS is the final fallback.

#### Scenario: Yazio not configured
- **WHEN** no Yazio credentials are configured
- **THEN** no Yazio request is made and lookup behaves as before this change.

### Requirement: Yazio foods map into the existing food contract
The system SHALL project each Yazio result to the existing food record with a stable `yazio:` id, name, producer, source attribution, a 100-unit basis in grams or millilitres, and kcal, carbohydrate, protein and fat values. Unknown, implausible or unsupported-unit values SHALL stay unknown. Reported serving options SHALL be kept in the record. Results SHALL be untrusted data and stored in the local mirror like other online foods.

#### Scenario: Normalized result
- **WHEN** Yazio reports per-unit nutrients and a gram or millilitre base unit
- **THEN** the record states per-100 values in that unit with the source "Yazio".

#### Scenario: Unusable record
- **WHEN** a result lacks a name, reports an unsupported base unit, or has non-finite or implausible nutrient values
- **THEN** the unit or value is unknown, or the record is dropped when it has no name, and it is never guessed.

#### Scenario: Use in meals
- **WHEN** a Yazio food id is used as a meal component or ingredient with an amount in its basis unit
- **THEN** nutrition is calculated and frozen in the entry with the Yazio source, and a Yazio outage does not alter existing entries.

### Requirement: Yazio transport is bounded and credential-safe
The system SHALL authenticate with the configured account, hold tokens only in memory, and refresh or renew them before searching. It SHALL send only the food search term or barcode plus account authentication, and bound timeouts, response size and request rate.

#### Scenario: Token expiry
- **WHEN** the access token has expired
- **THEN** it is refreshed, or a new login is made when refresh is rejected, before the search.

### Requirement: Yazio failures are sanitized and isolated
The system SHALL cache successful Yazio responses, back off after rate limits and rejected logins, and map every failure to a sanitized error disclosing neither credentials, tokens, queries nor response bodies. A Yazio failure SHALL NOT fail saved-product search, BLS or Open Food Facts lookup.

#### Scenario: Rejected credentials
- **WHEN** Yazio rejects the login
- **THEN** further login attempts are paused for a backoff period, the lookup continues with the next source, and no credential appears in errors or logs.

#### Scenario: Rate limit or API change
- **WHEN** Yazio returns 429, a version block, a server error, or a response of an unexpected shape
- **THEN** the request fails safely, 429 starts a local backoff, and the chain continues.

### Requirement: Barcode result has an adjacent product editor
The system SHALL present the editable product fields immediately alongside an online barcode result and require an explicit save to create a local product.

#### Scenario: Review an online barcode result
- **WHEN** an online barcode match is returned
- **THEN** the product editor appears with that result, with available values prefilled and unknown values left empty.

#### Scenario: Cancel review
- **WHEN** the athlete cancels the editor without saving
- **THEN** no local product is created.

Evidence: `public/nutrition.js`; `tests/nutrition-lookup-status.test.cjs::product editor follows the barcode result before the product lists`.

### Requirement: Additional provider label nutrients reach product review
The system SHALL retain supported, valid label sugar, fibre and salt values with their original basis and source in external food records and prefill them during product review. Missing or invalid values SHALL remain unknown.

#### Scenario: Available and missing values
- **WHEN** an external product reports valid additional label values and omits another
- **THEN** the reported values appear in the editor and the omitted value stays empty, including after a supported mirror read.

#### Scenario: Existing athlete product
- **WHEN** an athlete has already saved a matching local product
- **THEN** lookup preserves that authoritative product and does not overwrite it with an external result.

Evidence: `backend/providers/open_food_facts.py`, `backend/providers/yazio.py`, `public/nutrition.js`; `tests/test_food_database.py::FoodDatabaseTests.test_additional_off_nutrients_preserve_label_values_and_unknowns`, `tests/test_yazio.py::YazioProjectionTests.test_additional_nutrients_are_scaled_and_invalid_values_remain_unknown`, `tests/test_nutrition_products.py::NutritionProductContractTests.test_precise_label_values_survive_save_and_consumption_snapshot`, `tests/test_food_database_mirror.py::FoodDatabaseServiceMirrorTests.test_legacy_barcode_entry_refreshes_once_and_falls_back_offline`, `tests/nutrition-lookup-status.test.cjs::online nutrients fill the product editor without replacing zero or local values`. Gap: actual provider field availability is unverified.
