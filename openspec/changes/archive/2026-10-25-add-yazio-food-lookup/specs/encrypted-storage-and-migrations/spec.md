# Spec Delta

## ADDED Requirements

### Requirement: Yazio source constraints migrate without data loss
The v13 to v14 upgrade SHALL allow `yazio:` ids in the food mirror and the `yazio` source in saved products by rebuilding their constraints in the same migration transaction, preserving every row, identifier, timestamp and index, and failing atomically.

#### Scenario: Populated upgrade
- **WHEN** a populated v9 through v13 database is opened
- **THEN** all mirror entries and products are unchanged afterwards, and a `yazio:` mirror entry and a `yazio` product can be stored.

#### Scenario: Failed upgrade
- **WHEN** the rebuild fails partway
- **THEN** the database remains at its prior version with unchanged rows.

## MODIFIED Requirements

### Requirement: Supported released-schema upgrades

The database SHALL recognize supported version-and-shape pairs from schema v9 through the current v14 and execute the required versioned steps within one rollback-capable migration transaction.


#### Scenario: Skipped-release upgrade
- **WHEN** a populated released v9 database is opened by this build
- **THEN** all intermediate migrations run to the exact current schema while preserving existing rows

#### Scenario: Later supported release
- **WHEN** a populated v10, v11, v12 or v13 database is opened
- **THEN** only remaining upgrade steps run and existing data remains intact
