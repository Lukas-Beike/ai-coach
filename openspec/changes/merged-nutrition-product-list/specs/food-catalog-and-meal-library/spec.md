## ADDED Requirements

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
- **THEN** the edited value stays, is marked as the athlete's own, and the edit can be undone from the change history.

#### Scenario: Re-check of an own product
- **WHEN** the athlete re-checks an own product with an EAN
- **THEN** the database lookup fills only its empty fields; without an EAN the re-check is refused with a message that an EAN is needed.

#### Scenario: Using a database entry
- **WHEN** the athlete uses a stored database food for a meal
- **THEN** it is recorded like an own product with its values at that time.
