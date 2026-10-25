---
name: ai-coach-db-migrations
description: Plan, implement, or review SQLCipher schema migrations and released-schema compatibility in Intervals Coach. Use for schema, migration, or restore-compatibility changes; not ordinary queries or a request to reset a database.
---

# Data-preserving schema changes

1. Read root and `backend/AGENTS.md`, then locate the schema owner in
   `backend/db/schema.py`, `schema_history.py`, and `migrations.py`. Trace changed
   readers, writers, restore validation, and startup before choosing a migration.
   Record the current version and every supported released fixture from code;
   v9 (release 1.13.6) is the oldest supported baseline.
2. Plan the before/after records, version transition, transaction boundary,
   constraints/indexes, defaults, and skipped-release paths. Preserve every
   athlete record class, snapshots, tombstones, settings, and sync state. Never
   rewrite frozen released-schema fixtures to make a migration pass.
3. Put migration logic in its cohesive database owner. Reject unknown/newer
   versions or unrecognized shapes before modifying anything. Keep SQLCipher
   enabled; neither an empty data directory nor plaintext startup is an upgrade.
4. Use populated temporary fixtures for each supported released schema. Assert
   preserved identities, values, relationships, and sync markers, plus new
   defaults and constraints. Inject a failure partway through the migration and
   verify rollback to the unchanged prior schema and rows. Verify same-build
   restarts and direct skipped-release upgrades to the current version.
5. Trace backup/restore compatibility and existing-record edits after upgrade.
   Use existing tests such as `tests/test_db_migrations.py` and restore-validation
   tests; select checks with [validation](../ai-coach-validation/SKILL.md).
   Run encrypted integration evidence through the repository Docker/SQLCipher
   workflow. Plain SQLite unit tests alone do not prove encrypted startup.

Report a supported-schema matrix: starting release/version, populated upgrade,
rollback, restart, and encrypted-runtime evidence, each passed/failed/not run.
Missing required upgrade evidence means the schema change is not release-ready.
Update compatibility documentation when behavior changes; never touch live data,
backups, credentials, or token stores. This skill does not authorize a release,
restore, database reset, or removal of older supported upgrade paths.
