# Spec Delta

## MODIFIED Requirements

### Requirement: Supported released-schema upgrades

The database SHALL recognize supported version-and-shape pairs from schema v9 through released v14 and the extended current schema v15, executing required versioned steps within one rollback-capable migration transaction.

#### Scenario: Skipped-release upgrade
- **WHEN** a populated released v9 database is opened by this build
- **THEN** all intermediate migrations run to the exact current schema while preserving existing rows.

#### Scenario: Later supported release
- **WHEN** a populated v10, v11, v12, v13 or v14 database is opened
- **THEN** only remaining upgrade steps run and existing data remains intact.

Evidence baseline: `backend/db/migrations.py`, `backend/db/schema_history.py`; `tests/test_db_migrations.py`. The outgoing v14 fixture must be frozen before changing the live shape.

## ADDED Requirements

### Requirement: Canonical extension upgrade preservation
The extended schema SHALL preserve all athlete records, feedback, snapshots, tombstones, plans, sessions, settings, conversations, usage and sync state. Supported populated upgrades, injected-failure rollback, same-build restart and encrypted backup/restore SHALL be verified from v9 and every later released schema.

#### Scenario: Populated released schemas
- **WHEN** each frozen released schema from v9 through v14 is upgraded
- **THEN** existing identities, values, relationships and sync markers survive and new canonical structures satisfy their validation rules.

#### Scenario: Upgrade fails partway
- **WHEN** an injected failure interrupts extension migration
- **THEN** schema and rows return to the unchanged released state and a later valid attempt remains possible.

#### Scenario: Encrypted restart and backup
- **WHEN** an upgraded temporary SQLCipher database is restarted and restored through the supported backup workflow
- **THEN** encryption stays enabled and old plus new canonical records and relationships remain available.

#### Scenario: Unknown or newer shape
- **WHEN** a database has an unsupported version, unrecognized shape or mismatched version/shape pair
- **THEN** initialization rejects it without deleting, resetting or partially modifying it.
