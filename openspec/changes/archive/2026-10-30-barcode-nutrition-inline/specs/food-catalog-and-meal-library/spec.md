## ADDED Requirements

### Requirement: Barcode result has an adjacent product editor
The system SHALL present the editable product fields immediately alongside an online barcode result and require an explicit save to create a local product.

#### Scenario: Review an online barcode result
- **WHEN** an online barcode match is returned
- **THEN** the product editor appears with that result, with available values prefilled and unknown values left empty.

#### Scenario: Cancel review
- **WHEN** the athlete cancels the editor without saving
- **THEN** no local product is created.

### Requirement: Additional provider label nutrients reach product review
The system SHALL retain supported, valid label sugar, fibre and salt values with their original basis and source in external food records and prefill them during product review. Missing or invalid values SHALL remain unknown.

#### Scenario: Available and missing values
- **WHEN** an external product reports valid additional label values and omits another
- **THEN** the reported values appear in the editor and the omitted value stays empty, including after a supported mirror read.

#### Scenario: Existing athlete product
- **WHEN** an athlete has already saved a matching local product
- **THEN** lookup preserves that authoritative product and does not overwrite it with an external result.

Evidence before change: `backend/providers/open_food_facts.py`, `backend/providers/yazio.py`, `public/nutrition.js`; synthetic coverage to be added. Actual provider field availability is unverified.
