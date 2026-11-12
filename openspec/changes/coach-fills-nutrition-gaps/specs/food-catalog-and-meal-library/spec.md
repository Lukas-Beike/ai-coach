## ADDED Requirements

### Requirement: Coach fills empty product fields
The Coach SHALL list own products and stored database foods with empty core fields, and SHALL write values into named products only where the field is empty at write time, per the product's own basis, each with its origin, source page and time. Known values SHALL never be replaced. Every write SHALL be in the change history so the turn receipt names product, field, value and origin and whole-turn undo restores the empty fields.

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
