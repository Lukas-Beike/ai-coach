## MODIFIED Requirements

### Requirement: Baseline schema upgrades

The database SHALL recognize the version-and-shape pair of the baseline, the schema production runs (v26, release 2.0.5, frozen as one fixture and one digest), and of the current schema, executing the versioned steps from the baseline within one rollback-capable migration transaction. A schema that never reached production SHALL get no frozen shape of its own.

#### Scenario: Baseline database
- **WHEN** a populated baseline database is opened by this build
- **THEN** the steps from the baseline run to the exact current schema while preserving existing rows.

#### Scenario: One step from the previous shape
- **WHEN** a previous shape with one registered step is opened
- **THEN** the step runs in one transaction to the exact current schema and keeps every row.

#### Scenario: Baseline food mirror becomes canonical products
- **WHEN** a v26 database with own products and mirrored foods is upgraded
- **THEN** every own product keeps its row as origin `own`, every mirrored food becomes a product of its database's origin with its fetch time and all fields, a mirrored food with an own product's EAN only fills that product's empty fields, and the mirror table is gone.

#### Scenario: Failing baseline upgrade
- **WHEN** the baseline upgrade fails after moving some rows
- **THEN** the database, its rows and its version stay exactly as before, and a later attempt succeeds.

Evidence: `backend/db/migrations.py`, `backend/db/schema_history.py`; `tests/test_db_migrations.py::test_populated_baseline_reaches_the_live_schema_with_its_rows`, `tests/test_db_migrations.py::test_baseline_mirror_rows_become_canonical_products_without_loss`, `tests/test_db_migrations.py::test_failing_baseline_upgrade_rolls_back_and_a_retry_succeeds`, `tests/test_db_migrations.py::test_upgraded_database_restarts_with_the_same_build_unchanged`, `tests/test_db_migrations.py::test_frozen_baseline_fixture_is_the_recorded_production_shape`, `tests/test_db_migrations.py::test_a_previous_shape_upgrades_in_one_step_with_its_rows`, `tests/test_db_encrypted_upgrade_matrix.py`.
