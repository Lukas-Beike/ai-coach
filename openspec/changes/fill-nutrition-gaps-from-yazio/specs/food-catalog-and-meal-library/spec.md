## ADDED Requirements

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
