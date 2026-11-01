## MODIFIED Requirements

### Requirement: Supported released-schema upgrades

The database SHALL recognize supported version-and-shape pairs from schema v9 through released v17 and the current schema v18, executing required versioned steps within one rollback-capable migration transaction.

#### Scenario: Skipped-release upgrade
- **WHEN** a populated released v9 database is opened by this build
- **THEN** all intermediate migrations run to the exact current schema while preserving existing rows.

#### Scenario: Later supported release
- **WHEN** a populated v10, v11, v12, v13, v14, v15, v16 or v17 database is opened
- **THEN** only remaining upgrade steps run and existing data remains intact.

Evidence baseline: `backend/db/migrations.py`, `backend/db/schema_history.py`; `tests/test_db_migrations.py`. The outgoing v17 fixture is frozen (`tests/test_db_migrations.py::test_frozen_v17_fixture_is_the_recorded_released_shape`); freeze v18 before changing the live shape again.

## ADDED Requirements

### Requirement: Session RPE rating time upgrade
The v17 to v18 upgrade SHALL add the nullable `activity_feedback.session_rpe_rated_at` column in one migration transaction; every existing row SHALL keep its values with an unknown (NULL) rating time.

#### Scenario: Populated upgrade
- **WHEN** a populated v17 database with rated, unrated and session-linked feedback is opened
- **THEN** every table keeps its exact rows and each feedback row gains a NULL rating time.

#### Scenario: Upgrade fails partway
- **WHEN** an injected failure follows the column addition
- **THEN** the database returns to the unchanged v17 or v9 schema and rows.

Evidence: `backend/db/migrations.py::_upgrade_v17_to_v18`; `tests/test_db_feedback_rating_time_migration.py`, `tests/test_db_encrypted_upgrade_matrix.py`.
