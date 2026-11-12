## ADDED Requirements

### Requirement: Tool-specific bulk threshold
A Coach write tool MAY declare that it counts as a bulk change from a lower number of records than the general threshold; a call reaching that number SHALL need the athlete's confirmed bulk request in the tool's domain, failing closed like any bulk change. Filling product gaps counts as bulk from two products.

#### Scenario: Several products filled
- **WHEN** the Coach fills gaps of two or more products in one turn without a confirmed bulk request in the nutrition domain
- **THEN** the call is denied before any write, and the Coach asks the athlete first.

#### Scenario: One product filled
- **WHEN** the Coach fills gaps of one product
- **THEN** no bulk confirmation is needed; the write still needs the athlete's own request and shows a receipt.
