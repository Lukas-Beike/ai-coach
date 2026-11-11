## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Own product wins for its EAN
An EAN that an own product holds SHALL have no separate stored database food. A fetched food with that EAN SHALL fill only the own product's empty brand and nutrient fields, scaled to its basis when the unit matches and never into a product of another unit; existing values SHALL stay. Each filled field SHALL record its origin and fetch time.

#### Scenario: Lookup of an own product's EAN
- **WHEN** a lookup stores a food whose EAN an own product holds
- **THEN** no database entry is stored, the own product's empty fields of the same unit are filled with their origin and fetch time, and its existing values are unchanged.

#### Scenario: Own product saved with the EAN of stored foods
- **WHEN** the athlete saves an own product with the EAN of stored database foods
- **THEN** the product's empty fields are filled from those foods, newest first, and the foods no longer exist as separate entries.

#### Scenario: Product counted per portion
- **WHEN** the own product's basis unit differs from the food's
- **THEN** no nutrient value is filled; an empty brand still is.

Evidence: `backend/db/repositories.py::fill_empty_product_fields`, `backend/db/repositories.py::NutritionProductRepository.save`, `backend/db/repositories.py::FoodDatabaseEntryRepository.upsert`; `tests/test_food_database_mirror.py::FoodMirrorTests.test_an_own_product_with_the_ean_wins_and_takes_only_empty_fields`, `tests/test_food_database_mirror.py::FoodMirrorTests.test_saving_an_own_product_absorbs_the_entries_of_its_ean`.
