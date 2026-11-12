## MODIFIED Requirements

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

## ADDED Requirements

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
