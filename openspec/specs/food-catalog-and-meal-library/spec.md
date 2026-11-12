# food-catalog-and-meal-library Specification

## Purpose

Describe food lookup, permanent lookup mirrors, athlete-confirmed local products, trusted component calculations, and reusable meals. Re-validated against application revision `d1beefd77`; cited tests are inspected unless listed as executed in the handoff. Consumption is governed by `nutrition-diary-and-targets`, label extraction by `nutrition-photo-analysis`, and remote diary export by `nutrition-provider-sync`.

## Requirements

### Requirement: Local-first product and barcode lookup
The system SHALL search active saved products before fallback food lookup, return source information, and leave diary totals unchanged by searching. Text lookup SHALL require a meaningful search term and distinguish no match from a failed lookup.

#### Scenario: Known local barcode
- **WHEN** a barcode belongs to an active saved product
- **THEN** the local product is returned with local provenance and no remote food lookup occurs.

#### Scenario: Unknown barcode
- **WHEN** the barcode has no active local match
- **THEN** the database lookup result identifies its source (Yazio when configured and matched, otherwise Open Food Facts), and the result remains a candidate rather than a saved product or consumed meal.

#### Scenario: Flexible text search
- **WHEN** saved name/brand words match in a different order, with supported plural, umlaut, separator, or typo normalization
- **THEN** matching local products are returned while every search term must fit; SQL wildcard characters do not broaden the match.

Evidence: `backend/nutrition/catalog.py::ProductCatalogService.lookup_product`, `backend/nutrition/catalog.py::ProductCatalogService.list_products`, `backend/db/repositories.py::NutritionProductRepository.list`; `tests/test_nutrition_products.py::NutritionProductContractTests.test_barcode_lookup_prefers_local_product_and_never_calls_remote`, `tests/test_nutrition_products.py::NutritionProductContractTests.test_search_tolerates_plurals_umlauts_and_typos_but_needs_every_word`, `tests/test_nutrition_products.py::NutritionProductContractTests.test_unknown_barcode_falls_back_to_food_database_and_labels_source`.

### Requirement: Database foods preserve units and missing values
The system SHALL support the bundled BLS database, Open Food Facts and, when configured, Yazio, preserve food identity and source, and calculate only from known quantities in the food's stated unit. Missing nutrients SHALL remain unknown.

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
The system SHALL keep fetched external foods (Open Food Facts and Yazio) as canonical products whose origin names their database, with its fetch time, separate from diary entries; the athlete's own products carry the origin `own`. Fresh stored foods SHALL avoid unnecessary provider reads; stale fallback SHALL remain visibly stale when a provider recheck fails.

#### Scenario: Fresh cached barcode
- **WHEN** a usable stored record is younger than ninety days and its per-100 values include sugar, fibre and salt
- **THEN** lookup uses the local database entry without a provider request and returns its stored-time provenance.

#### Scenario: Fresh older entry without sugar, fibre and salt
- **WHEN** a barcode lookup finds a usable record younger than ninety days that lacks those keys
- **THEN** the providers are read once; if that fails the stored record is returned as a local hit and no new read starts for 900 seconds.

#### Scenario: Stale record during outage
- **WHEN** a stale barcode record exists and the provider recheck fails
- **THEN** the stored food remains usable with stale-origin notice rather than being marked freshly fetched.

#### Scenario: Forget a mirrored food
- **WHEN** the athlete explicitly confirms removal of a database entry
- **THEN** only that stored food is removed; own products and consumed snapshots remain independent, and a missing record produces a not-found error.

#### Scenario: Repeated mirrored food
- **WHEN** another successful lookup stores the same external food identity
- **THEN** its stored record and fetched time are refreshed without creating a second food identity or consumed meal.

#### Scenario: Stored food reads back unchanged
- **WHEN** a stored food is read again
- **THEN** it returns every field it was stored with, including fields the product columns do not hold and the absence of nutrient keys it never had.

Evidence: `backend/nutrition/food_mirror.py::FoodDatabaseMirror.is_fresh`, `backend/nutrition/food_database.py::FoodDatabaseService._off_product`, `backend/nutrition/food_database.py::FoodDatabaseService._barcode_product`, `backend/nutrition/food_database.py::FoodDatabaseService.forget`, `backend/db/repositories.py::FoodDatabaseEntryRepository`, `backend/http_api/nutrition.py::NutritionPostRoutes._forget_database_food`; `tests/test_food_database_mirror.py::FoodMirrorTests.test_entries_expire_after_ninety_days`, `tests/test_food_database_mirror.py::FoodMirrorTests.test_an_entry_reads_back_as_the_food_it_stored`, `tests/test_food_lookup_chain.py::LookupChainTests.test_fresh_legacy_yazio_fallback_does_not_retry_each_scan`, `tests/test_food_database_mirror.py::FoodDatabaseServiceMirrorTests.test_offline_lookup_falls_back_to_the_stale_entry_with_a_notice`, `tests/test_nutrition_product_http_contract.py::NutritionProductHttpContractTests.test_database_entry_removal_requires_confirmation`. Storage failures are suppressed so a successful lookup can still return its result.

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

Evidence: `backend/http_api/nutrition.py::NutritionPostRoutes._save_product`, `backend/http_api/nutrition.py::NutritionPutRoutes.routes`, `backend/nutrition/catalog.py::ProductCatalogService.save_product`, `backend/nutrition/catalog.py::ProductCatalogService.archive_product`; `tests/test_nutrition_products.py::NutritionProductContractTests.test_confirmed_product_is_persistent_and_can_be_archived`, `tests/test_nutrition_product_http_contract.py::NutritionProductHttpContractTests.test_unconfirmed_product_save_is_rejected_before_persistence`, `tests/test_nutrition_review_regressions.py::NutritionReviewRegressionTests.test_archived_products_cannot_be_calculated_or_logged`.

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
The client SHALL present product and label candidates for review and explicit local save, and prepare editable Coach drafts for consumption. The athlete SHALL be able to mark any product as favorite, and to add a product with a quantity directly to a logged meal of the selected day without a Coach turn. Browsing, candidate review, and draft preparation SHALL not automatically send a Coach turn or export nutrition.

#### Scenario: Use a saved product
- **WHEN** the athlete selects a product and consumed quantity
- **THEN** a Coach draft names the product/quantity for review before the athlete sends it.

#### Scenario: Preserve an existing draft
- **WHEN** a product is added to the Coach message while an unsent draft exists
- **THEN** the draft stays intact and gains one line naming the quantity and product id, never the product name.

#### Scenario: Favorite products
- **WHEN** the athlete marks a product, own or from a database, as a favorite
- **THEN** it is listed under "Favoriten" and still under "Alle Produkte", and saving, editing or re-checking the product keeps the mark.

#### Scenario: Add a product to a logged meal
- **WHEN** the athlete adds a saved product and quantity to a logged meal
- **THEN** the meal becomes a composite of its earlier values and the product's nutrients frozen at that time, with at most 20 components.

#### Scenario: Product without a chosen meal
- **WHEN** the athlete adds a saved product and quantity without choosing a meal
- **THEN** a new local snack entry for the selected day records the product.

#### Scenario: Safe ingredient details
- **WHEN** the diary displays a composite meal
- **THEN** expandable details display escaped frozen ingredient names, amounts, origins, and unknown values rather than live catalog recalculations, and a component from a database product is labelled as such.

Evidence: `public/nutrition.js::useNutritionProduct`, `public/nutrition.js::addNutritionProductToCoachDraft`, `public/nutrition.js::addNutritionProductToMeal`, `backend/nutrition/diary.py::NutritionDiaryService.add_product_to_meal`, `backend/nutrition/catalog.py::ProductCatalogService.set_favorite`, `tests/test_nutrition_favorites_and_meal_additions.py::FavoritesAndMealAdditionTests.test_adding_a_product_turns_a_single_product_meal_into_a_composite`, `tests/test_nutrition_favorites_and_meal_additions.py::FavoritesAndMealAdditionTests.test_favorites_are_listed_first_and_survive_edits`, `public/nutrition.js::nutritionComponentDetails`, `public/nutrition.js::saveNutritionProduct`; `e2e/nutrition.spec.js::@responsive nutrition product library supports review, local save, favorites, and extending an existing Coach draft`, `e2e/nutrition.spec.js::@responsive composite meal shows immutable ingredient snapshots and provenance`, `e2e/nutrition.spec.js::@responsive nutrition diary and saved meals remain read-only and preserve confirmed consumption`.

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

Evidence: `backend/coach/read_tools.py::CoachReadToolService._lookup_food`, `backend/coach/read_tools.py::CoachReadToolService._lookup_one_food`; `tests/test_nutrition_review_regressions.py::NutritionReviewRegressionTests.test_batched_queries_return_each_term_and_isolate_failures`, `tests/test_nutrition_review_regressions.py::NutritionReviewRegressionTests.test_explicit_text_source_still_returns_matching_saved_products`, `tests/test_nutrition_review_regressions.py::NutritionReviewRegressionTests.test_explicit_source_outage_still_returns_saved_products`.

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
When Yazio is configured and a text or barcode lookup names no source, the system SHALL search saved products first, then fresh mirrored foods, then Yazio, then Open Food Facts, then BLS for text queries and Yazio then Open Food Facts for barcodes. It SHALL advance to the next source when a source has no suitable match or is unavailable. A saved-product or fresh mirror match SHALL prevent every external request. Without Yazio configuration the previous default SHALL apply unchanged.

#### Scenario: Local match
- **WHEN** a saved product matches the lookup
- **THEN** it is returned and no Yazio, Open Food Facts or BLS lookup runs.

#### Scenario: Fresh mirrored match
- **WHEN** no saved product matches but a mirrored food of any source younger than ninety days contains every query word with a known energy value
- **THEN** it is returned with local-database provenance, Yazio entries first, and no external request runs.

#### Scenario: Yazio match
- **WHEN** no saved product or fresh mirrored food matches and Yazio returns a food containing every query word with a known energy value
- **THEN** the Yazio foods are returned with source attribution and Open Food Facts is not queried.

#### Scenario: Fallthrough
- **WHEN** Yazio returns nothing suitable or fails, or Open Food Facts then does the same
- **THEN** the next source in order is used, and BLS is the final fallback.

#### Scenario: Explicit Yazio source
- **WHEN** a lookup names Yazio without Yazio configuration
- **THEN** it fails with a clear not-configured error and no fallback source is queried.

#### Scenario: Yazio not configured
- **WHEN** no Yazio credentials are configured
- **THEN** no Yazio request is made and lookup behaves as before this change.

Evidence: `backend/nutrition/food_database.py::FoodDatabaseService._search`, `backend/nutrition/food_database.py::FoodDatabaseService._chain_search`, `backend/nutrition/food_database.py::FoodDatabaseService._barcode_product`; `tests/test_food_lookup_chain.py::LookupChainTests.test_yazio_answers_first_with_source_and_origin`, `tests/test_food_lookup_chain.py::LookupChainTests.test_fresh_mirror_hit_prevents_every_external_request`, `tests/test_food_lookup_chain.py::LookupChainTests.test_empty_or_unsuitable_yazio_falls_through_to_open_food_facts`, `tests/test_food_lookup_chain.py::LookupChainTests.test_without_yazio_the_default_stays_bls_only`, `tests/test_food_lookup_chain.py::LookupChainTests.test_explicit_yazio_without_configuration_is_a_clear_error`, `tests/test_food_lookup_chain.py::LookupChainTests.test_barcode_prefers_mirror_then_yazio_then_open_food_facts`.

### Requirement: Yazio foods map into the existing food contract
The system SHALL project each Yazio result to the existing food record with a stable `yazio:` id, name, producer, source attribution, a 100-unit basis in grams or millilitres, and kcal, carbohydrate, protein and fat values. Unknown, implausible or unsupported-unit values SHALL stay unknown. Reported serving options SHALL be kept in the record. Results SHALL be untrusted data and stored in the local mirror like other online foods.

#### Scenario: Normalized result
- **WHEN** Yazio reports per-unit nutrients and a gram or millilitre base unit
- **THEN** the record states per-100 values in that unit with the source "Yazio".

#### Scenario: Unusable record
- **WHEN** a result lacks a name, reports an unsupported base unit, or has non-finite or implausible nutrient values
- **THEN** the unit or value is unknown, or the record is dropped when it has no name, an invalid id, is deleted or private, has neither energy nor a macro, or has macros summing above 110 g per 100 g, and it is never guessed.

#### Scenario: Use in meals
- **WHEN** a Yazio food id is used as a meal component or ingredient with an amount in its basis unit
- **THEN** nutrition is calculated and frozen in the entry with the Yazio source, and a Yazio outage does not alter existing entries.

Evidence: `backend/providers/yazio.py::project_product`, `backend/nutrition/food_database.py::FoodDatabaseService.resolve`; `tests/test_yazio.py::YazioProjectionTests.test_per_unit_values_become_per_100_with_source`, `tests/test_yazio.py::YazioProjectionTests.test_unusable_records_are_dropped`, `tests/test_yazio.py::YazioProjectionTests.test_implausible_scale_is_dropped_instead_of_guessed`, `tests/test_food_lookup_chain.py::LookupChainTests.test_yazio_food_resolves_for_calculation_and_survives_an_outage`.

### Requirement: Yazio transport is bounded and credential-safe
The system SHALL authenticate with the configured account email and password and the Yazio app's public client pair, hold tokens only in memory, and refresh or renew them before searching. It SHALL send only the food search term or barcode, the search region and locale, the profile sex when it is male or female, and account authentication, and bound timeouts (10 seconds), response size (500,000 bytes), request rate (20 per minute) and cache lifetime (24 hours).

#### Scenario: Token expiry
- **WHEN** the access token has expired
- **THEN** it is refreshed, or a new login is made when refresh is rejected, before the search.

#### Scenario: Profile sex in the search
- **WHEN** a search runs and the athlete profile sex is male or female
- **THEN** the search request carries that value as its sex parameter; when the sex is unset no sex parameter is sent.

#### Scenario: Search region
- **WHEN** a search runs
- **THEN** the region is the configured two-letter country code, else DE, and the locale is derived from it.

Evidence: `backend/providers/yazio.py::YazioClient.search`, `backend/providers/yazio.py::YazioClient._token`, `backend/nutrition/assembly.py::NutritionAssembly`; `tests/test_yazio.py::YazioClientTests.test_search_sends_the_profile_sex_and_none_when_unset`, `tests/test_yazio.py::YazioClientTests.test_country_is_configurable_and_validated`, `tests/test_yazio.py::YazioClientTests.test_expired_token_is_refreshed_then_login_is_the_fallback`.

### Requirement: Yazio failures are sanitized and isolated
The system SHALL cache successful Yazio responses, back off after rate limits and rejected logins, and map every failure to a sanitized error disclosing neither credentials, tokens, queries nor response bodies. A Yazio failure SHALL NOT fail saved-product search, BLS or Open Food Facts lookup.

#### Scenario: Rejected credentials
- **WHEN** Yazio rejects the login
- **THEN** further login attempts are paused for a backoff period, the lookup continues with the next source, and no credential appears in errors or logs.

#### Scenario: Rate limit or API change
- **WHEN** Yazio returns 429, a version block, a server error, or a response of an unexpected shape
- **THEN** the request fails safely, 429 starts a local backoff, and the chain continues.

Evidence: `backend/providers/yazio.py::YazioClient._grant_rejected`, `backend/providers/yazio.py::YazioClient._raise_http_error`; `tests/test_yazio.py::YazioClientTests.test_rejected_login_pauses_further_attempts_without_leaking`, `tests/test_yazio.py::YazioClientTests.test_rate_limit_backs_off_locally`, `tests/test_yazio.py::YazioClientTests.test_version_block_server_error_and_bad_shape_are_sanitized`, `tests/test_food_lookup_chain.py::LookupChainTests.test_yazio_failure_does_not_block_barcode_lookup`.

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

### Requirement: Yazio authentication failure is honestly classified
The system SHALL classify Yazio authentication and compatibility failures only as precisely as supported by safe evidence, and SHALL avoid presenting ambiguous rejection as a proven incorrect password or client version.

#### Scenario: Ambiguous authentication rejection
- **WHEN** an upstream rejection could result from account credentials, application credentials, or an unsupported client
- **THEN** the athlete receives an actionable ambiguous authentication failure and no unsupported cause is asserted.

#### Scenario: Reliably identified client version rejection
- **WHEN** a supported, safely recognized response establishes a client version rejection
- **THEN** the athlete is told that the client version needs attention without exposing the provider response.

#### Scenario: Working authentication and lookup
- **WHEN** a compatible provider accepts the configured credentials and returns a valid food response
- **THEN** Yazio lookup can return the normalized food with its existing source provenance and no remote write.

#### Scenario: Failed check or lookup
- **WHEN** authentication fails or the provider is unavailable
- **THEN** existing local and alternative food sources remain usable and retry/backoff limits remain effective.

Evidence: `backend/providers/yazio.py::YazioClient._grant_rejected` (login 400/401/403 stays one ambiguous `food_database_auth_failed`), `backend/providers/yazio.py::YazioClient._raise_http_error` (only a bounded `version_blocked` body on a product request becomes `food_database_version_blocked`), `backend/nutrition/food_database.py::FoodDatabaseService._chain_search` (notices, fallback); `tests/test_yazio.py::YazioClientTests.test_rejected_login_pauses_further_attempts_without_leaking`, `tests/test_yazio.py::YazioClientTests.test_recognized_version_block_is_safe_and_distinct`, `tests/test_yazio.py::YazioClientTests.test_truncated_forbidden_response_is_sanitized`, `tests/test_food_lookup_chain.py::LookupChainTests.test_version_block_is_reported_while_fallback_remains_available`, `tests/test_food_lookup_chain.py::LookupChainTests.test_text_chain_names_rejected_yazio_credentials`. The incident's upstream response and actual cause stay unverified; no live account was used.

### Requirement: Own product wins for its EAN
Stored database foods with an own product's EAN SHALL stay stored for lookups but SHALL NOT be listed as entries of their own. A newly created own product SHALL take only its empty brand and nutrient fields from them, newest first, scaled to its basis when the unit matches; existing values SHALL stay, each filled field SHALL record its origin and fetch time, and the fill SHALL be part of the creation's change record. A lookup SHALL never change an own product.

#### Scenario: Lookup of an own product's EAN
- **WHEN** a lookup stores a food whose EAN an own product holds
- **THEN** the food is stored for later lookups by its id, is not listed as a separate entry, and the own product is unchanged.

#### Scenario: Own product created with the EAN of stored foods
- **WHEN** the athlete creates an own product with the EAN of stored database foods
- **THEN** the product's empty fields are filled from those foods, newest first, with origin and fetch time, and a later edit that empties a field keeps it empty.

#### Scenario: Product counted per portion
- **WHEN** the own product's basis unit differs from the food's
- **THEN** no nutrient value is filled; an empty brand still is.

#### Scenario: Stored food id
- **WHEN** a new own product is submitted with the id of a stored database food
- **THEN** it is saved under a new id and the stored food is unchanged; a Coach scope naming a stored food is no product object.

Evidence: `backend/db/repositories.py::fill_empty_product_fields`, `backend/db/repositories.py::NutritionProductRepository.fill_from_database_entries`, `backend/nutrition/catalog.py::ProductCatalogService.save_product`, `backend/db/repositories.py::FoodDatabaseEntryRepository.search`, `backend/coach/dialogue_action.py`; `tests/test_food_database_mirror.py::FoodMirrorTests.test_an_own_products_ean_lists_no_entry_and_a_lookup_never_changes_it`, `tests/test_food_database_mirror.py::FoodMirrorTests.test_a_new_own_product_takes_only_empty_fields_from_its_eans_foods`, `tests/test_nutrition_products.py::NutritionProductContractTests.test_a_new_product_fills_its_gaps_from_stored_foods_of_its_ean`, `tests/test_coach_dialogue.py::CoachDialogueTests.test_a_stored_database_food_is_no_product_scope_object`.

### Requirement: Re-checks fill gaps of stored foods
A re-check of a stored database food, automatic or manual, SHALL take every value the fresh result has and SHALL keep a stored value where the fresh result has none. Stored foods SHALL name their missing core fields (energy, carbohydrates, protein, fat, sugar, fibre, salt).

#### Scenario: Fresh result fills a gap
- **WHEN** a stored food without salt is re-checked and the fresh result has salt
- **THEN** the stored food has the fresh salt value and salt is no longer listed as missing.

#### Scenario: Fresh result lacks a known value
- **WHEN** a stored food with fibre is re-checked and the fresh result has no fibre
- **THEN** the stored fibre value stays and only the fetch time and the other fresh values change.

#### Scenario: Fresh result on another or unknown basis
- **WHEN** the fresh result has an unknown or different basis unit or amount
- **THEN** no stored nutrient value is carried over and the unit is not guessed; stored fields the fresh result lacks, such as servings, stay.

Evidence: `backend/nutrition/food_mirror.py::FoodDatabaseMirror.refresh`, `backend/nutrition/food_database.py::FoodDatabaseService.stored_foods`; `tests/test_food_database_mirror.py::FoodDatabaseServiceMirrorTests.test_a_re_check_fills_gaps_and_keeps_known_values`, `tests/test_food_database_mirror.py::FoodDatabaseServiceMirrorTests.test_a_re_check_never_guesses_a_basis_and_keeps_further_fields`, `tests/test_food_database_mirror.py::FoodDatabaseServiceMirrorTests.test_legacy_barcode_entry_refreshes_once_and_falls_back_offline`.

### Requirement: Manual re-check of a stored food
The athlete SHALL be able to re-check one stored database food online now through a session- and CSRF-protected action that applies the gap-filling rule and returns the refreshed food. When the database cannot be reached or does not know the food, the action SHALL fail visibly and leave the stored food unchanged.

#### Scenario: Manual re-check succeeds
- **WHEN** the athlete presses "Aktualisieren" on a stored food
- **THEN** the food is fetched online regardless of its age, its gaps are filled, and its fetch time is now.

#### Scenario: Database unreachable
- **WHEN** the online fetch fails during a manual re-check
- **THEN** an error is returned and the stored food, its values and its fetch time are unchanged.

#### Scenario: Unknown entry
- **WHEN** the request names no stored food
- **THEN** it is rejected without any online request.

#### Scenario: Write fails
- **WHEN** the fresh result cannot be stored
- **THEN** an error is returned instead of a success message.

Evidence: `backend/nutrition/food_database.py::FoodDatabaseService.refresh_stored`, `backend/http_api/nutrition.py::NutritionPostRoutes._refresh_database_food`, `public/nutrition.js::loadNutritionDatabase`; `tests/test_food_database_mirror.py::FoodDatabaseServiceMirrorTests.test_a_failed_or_unknown_re_check_changes_nothing`, `tests/test_food_database_mirror.py::FoodDatabaseServiceMirrorTests.test_a_re_check_whose_write_fails_is_reported`, `tests/test_nutrition_product_http_contract.py::NutritionProductHttpContractTests.test_database_entry_refresh_names_the_entry`, `e2e/nutrition.spec.js` ("a stored database entry is refreshed on request").

### Requirement: Yazio fills remaining gaps by EAN
After a manual re-check of an Open Food Facts entry, still-empty core fields SHALL be looked up in Yazio by the entry's EAN when Yazio is configured. Only empty fields SHALL be filled, only from a Yazio product on the same basis, each with origin `yazio` and its fetch time; known values SHALL stay. Lookups and calculations SHALL make no extra Yazio request.

#### Scenario: Gap filled from Yazio
- **WHEN** a re-checked Open Food Facts entry still lacks salt and Yazio has the same EAN with salt on the same basis
- **THEN** the entry's salt is the Yazio value, its provenance names `yazio` and the fetch time, and its other values are unchanged.

#### Scenario: No Yazio, no match or another basis
- **WHEN** Yazio is not configured, fails, has no product for the EAN, or reports another basis
- **THEN** no field is filled from Yazio, the re-check still succeeds, and a Yazio failure is named in its notice.

#### Scenario: Complete entry
- **WHEN** the re-checked entry has every core field
- **THEN** Yazio is not asked.

#### Scenario: Open Food Facts later has the value or another basis
- **WHEN** a later re-check returns the field from Open Food Facts, or returns the food on another basis
- **THEN** the field no longer names `yazio` as its origin.

#### Scenario: Lookup of a stale entry
- **WHEN** a barcode lookup or a calculation re-checks a stale Open Food Facts entry
- **THEN** Yazio is asked at most once, by the barcode chain itself.

Evidence: `backend/nutrition/food_database.py::FoodDatabaseService._fill_from_yazio`, `backend/nutrition/food_database.py::FoodDatabaseService.refresh_stored`, `backend/nutrition/food_mirror.py::FoodDatabaseMirror.fill_gaps`; `tests/test_food_lookup_chain.py::LookupChainTests.test_a_re_check_fills_remaining_gaps_from_yazio_by_ean`, `tests/test_food_lookup_chain.py::LookupChainTests.test_yazio_fills_nothing_without_a_match_on_the_same_basis`, `tests/test_food_lookup_chain.py::LookupChainTests.test_a_complete_re_check_does_not_ask_yazio`, `tests/test_food_lookup_chain.py::LookupChainTests.test_a_basis_change_ends_a_yazio_fill`, `tests/test_food_lookup_chain.py::LookupChainTests.test_lookups_and_calculations_ask_yazio_at_most_once`.

### Requirement: Coach fills empty product fields
The Coach SHALL list own products and stored database foods with empty core fields, and SHALL write values into named products only where the field is empty at write time, per the product's own basis, each with its origin, source page and time. Known values SHALL never be replaced. Every write SHALL be in the change history so the turn receipt names product, field, value and origin and whole-turn undo restores the empty fields.

#### Scenario: Origin backed by a lookup
- **WHEN** the Coach writes a value with origin Open Food Facts, Yazio, BLS or web
- **THEN** it is accepted only if a database lookup or the web search returned that value (scaled to the product's basis) in the last hour; otherwise the item is rejected, and a value the athlete states is written with origin `manual`.

#### Scenario: Implausible value for the basis
- **WHEN** a value exceeds the product's basis in grams, or its energy exceeds that of pure fat
- **THEN** the item is rejected without a write.

#### Scenario: Incomplete products listed
- **WHEN** the Coach lists incomplete products
- **THEN** own products and stored database foods with empty core fields are returned with id, name, brand, EAN, basis, origin and their missing fields, and complete products are not.

#### Scenario: Only empty fields written
- **WHEN** the Coach writes salt and fat into a product whose fat is already known
- **THEN** salt is written with its origin and source page, fat keeps its value and is reported as skipped.

#### Scenario: Receipt and undo
- **WHEN** a turn fills fields of an own product and a stored database food
- **THEN** its receipt lists each product, field, value and origin, and whole-turn undo empties exactly those fields again.

#### Scenario: Unknown or invalid input
- **WHEN** a named product does not exist, a field is not a core field, or a value is not a finite number in range
- **THEN** that item is rejected without writing it.

Evidence: `backend/nutrition/catalog.py::ProductCatalogService.fill_product_gaps`, `backend/nutrition/catalog.py::ProductCatalogService._gap_rejection`, `backend/nutrition/food_database.py::FoodDatabaseService.found_value`, `backend/nutrition/catalog.py::ProductCatalogService.list_incomplete_products`, `backend/db/repositories.py::fill_empty_nutrients`, `backend/nutrition/food_mirror.py::FoodDatabaseMirror.restore_in_transaction`, `backend/coach/change_receipts.py::change_summary`; `tests/test_nutrition_products.py::NutritionProductContractTests.test_incomplete_products_are_listed_and_only_their_empty_fields_filled`, `tests/test_nutrition_products.py::NutritionProductContractTests.test_invalid_gap_fills_are_rejected_without_a_write`, `tests/test_nutrition_products.py::NutritionProductContractTests.test_a_gap_fill_origin_needs_a_lookup_that_returned_the_value`, `tests/test_food_lookup_chain.py::LookupChainTests.test_returned_values_back_a_gap_fill_origin_for_an_hour`, `tests/test_nutrition_web_search.py::NutritionWebSearchCatalogTests.test_a_web_fill_needs_the_value_of_a_search_from_its_own_page`, `tests/test_server_coach_turn_undo.py::CoachTurnUndoTests.test_a_product_gap_fill_names_its_products_and_undoes_to_empty_fields`, `tests/test_coach_change_receipts.py::ChangeSummaryTests.test_applied_tracked_writes_are_listed_once_and_undoable`, `tests/test_coach_tool_coverage.py::CoachToolCoverageTests.test_incomplete_products_are_listed_and_filled_by_authorized_coach_turn`.

### Requirement: Coach web search for missing product values
The Coach SHALL be able to search the web for the still-empty core values of up to five named products through one Responses API request with the `web_search` tool, sending only product name, brand, EAN, basis and missing field names. Only finite, plausible values whose source page the search read or cited SHALL be returned, with origin `web`, the source page and an untrusted-data notice.

#### Scenario: Value found and cited
- **WHEN** the search returns salt per the product's basis with a source page it cited
- **THEN** the result names the product, salt, the value, origin `web` and the source page, with the untrusted-data notice.

#### Scenario: Uncited or implausible value
- **WHEN** a returned value's source page was neither read nor cited, or is not a finite number in range, or is for a field that is not empty
- **THEN** that value is dropped.

#### Scenario: Only product data leaves the app
- **WHEN** the search request is built
- **THEN** it contains only the products' name, brand, EAN, basis and missing field names, and no athlete record, message or other context.

#### Scenario: Endpoint without web search
- **WHEN** the configured endpoint rejects the `web_search` tool, or the request fails
- **THEN** the result says web search is not available, nothing is written, and the Coach turn continues.

Evidence: `backend/nutrition/web_search.py::NutritionWebSearchService.search`, `backend/nutrition/catalog.py::ProductCatalogService.search_web_values`, `backend/coach/read_tools.py` (`search_web_for_product_values`); `tests/test_nutrition_web_search.py::NutritionWebSearchTests.test_request_carries_only_product_data`, `tests/test_nutrition_web_search.py::NutritionWebSearchTests.test_values_are_kept_only_when_cited_plausible_and_missing`, `tests/test_nutrition_web_search.py::NutritionWebSearchTests.test_a_page_the_search_read_counts_without_an_inline_citation`, `tests/test_nutrition_web_search.py::NutritionWebSearchTests.test_failures_give_unavailable_without_provider_text`, `tests/test_coach_tool_coverage.py` (`search_web_for_product_values:success`).

### Requirement: One product list with equal actions
The product API SHALL list own products and stored database foods together, sorted by name, with origin, fetch date, favourite flag and missing core fields, searchable by name, brand and EAN. Every product SHALL be usable, editable, re-checkable and removable, and SHALL be markable as favourite.

#### Scenario: Merged list
- **WHEN** the athlete lists all products
- **THEN** own products and stored database foods appear together by name, a food whose EAN an own product holds appears only as that product, and each names its origin and missing fields.

#### Scenario: Favourite database entry
- **WHEN** the athlete marks a stored database food as favourite and it is later re-checked
- **THEN** it stays a favourite.

#### Scenario: Edited database entry
- **WHEN** the athlete edits a stored database food's value and the food is later re-checked
- **THEN** the edited value stays, is marked as the athlete's own, and the edit can be undone from the change history with its earlier marks.

#### Scenario: Database-owned fields
- **WHEN** an edit of a stored database food changes its name, brand, EAN, basis or status
- **THEN** it is refused and nothing changes.

#### Scenario: Re-check of an own product
- **WHEN** the athlete re-checks an own product with an EAN
- **THEN** the database lookup fills only its empty fields, falling back to the next stored source when one is unavailable; without an EAN, or for an archived product, the re-check is refused with a clear message.

#### Scenario: Using a database entry
- **WHEN** the athlete uses a stored database food for a meal
- **THEN** it is recorded like an own product with its values at that time.

Evidence: `backend/db/repositories.py::NutritionProductRepository.list_all`, `backend/nutrition/catalog.py::ProductCatalogService.update_product`, `backend/nutrition/catalog.py::ProductCatalogService.refresh_product`, `backend/nutrition/food_database.py::FoodDatabaseService.refresh_barcode`, `backend/nutrition/food_mirror.py::FoodDatabaseMirror.restore_in_transaction`, `backend/nutrition/components.py`, `backend/http_api/nutrition.py` (`scope=all`); `tests/test_nutrition_products.py::NutritionProductContractTests.test_the_merged_list_holds_own_products_and_stored_foods_by_name`, `tests/test_nutrition_products.py::NutritionProductContractTests.test_editing_a_stored_database_food_marks_its_values_as_the_athletes_own`, `tests/test_nutrition_products.py::NutritionProductContractTests.test_invalid_edits_of_a_stored_database_food_change_nothing`, `tests/test_food_database_mirror.py::FoodDatabaseServiceMirrorTests.test_an_own_product_re_check_needs_an_ean_and_a_working_lookup`, `tests/test_food_database_mirror.py::FoodDatabaseServiceMirrorTests.test_a_re_check_by_ean_falls_back_from_an_unavailable_source`, `tests/test_nutrition_product_history.py::NutritionProductHistoryTests.test_undo_of_an_edit_restores_the_food_and_of_a_re_check_the_product`, `tests/test_nutrition_favorites_and_meal_additions.py` (database food used and favourite).

### Requirement: One product list with sections and incomplete markers
The product page SHALL show "Favoriten (n)" and "Alle Produkte (n)" as collapsible sections, both collapsed when the page opens, each total followed by the number of incomplete entries. Every card SHALL show its origin and, when incomplete, the names of its missing fields, and SHALL offer Verwenden, Bearbeiten, Aktualisieren and Löschen.

#### Scenario: Page opens
- **WHEN** the athlete opens Ernährung › Produkte
- **THEN** both sections are collapsed and each heading shows its total and its number of incomplete entries.

#### Scenario: Incomplete product
- **WHEN** a product lacks salt and sugar
- **THEN** its card shows the incomplete symbol with an accessible label naming salt and sugar.

#### Scenario: Search
- **WHEN** the athlete searches by name, brand or EAN
- **THEN** both own products and database entries are searched, and sections with hits open.

#### Scenario: Database entry actions
- **WHEN** the athlete edits a database entry, re-checks it, or deletes it
- **THEN** only its nutrient values are editable, the re-check result is shown, and deleting removes it from the database after confirmation.

#### Scenario: Own product without EAN
- **WHEN** the athlete re-checks an own product without an EAN
- **THEN** the page says an EAN is needed and the editor allows entering one.

Evidence: `public/nutrition.js::renderNutritionProducts`, `public/nutrition.js::nutritionProductSection`, `public/nutrition.js::nutritionProductCard`, `public/nutrition.js::appendNutritionProductActions`, `public/nutrition.js::refreshNutritionProduct`, `public/nutrition.js::deleteNutritionProduct`, `public/nutrition.js::lockNutritionDatabaseFields`; `tests/nutrition-lookup-status.test.cjs` (sections, counters, search, cards, actions, unit and date cases), `e2e/nutrition.spec.js` (product list on mobile, tablet-landscape and desktop).
