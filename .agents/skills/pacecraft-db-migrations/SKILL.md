---
name: pacecraft-db-migrations
description: Plan, implement, or review SQLCipher schema migrations and released-schema compatibility in Pacecraft. Use for schema, migration, or restore-compatibility changes; not ordinary queries or a request to reset a database.
---

# Data-preserving schema changes

1. Read root and `backend/AGENTS.md`, then locate the schema owner in
   `backend/db/schema.py`, `schema_history.py`, and `migrations.py`. Trace changed
   readers, writers, restore validation, and startup before choosing a migration.
   Record the current version and the baseline from code: the frozen fixture
   is v26 (release 2.0.5), the oldest schema the code opens. Production runs
   v27 (releases 2.1.2 to 2.1.9, the only production instance), accepted by its
   frozen digest. New changes need evidence from both: populated upgrade,
   rollback and restart from the v26 fixture and from a v27 database. Move the
   baseline only after the athlete confirms a newer production schema from the
   diagnostics report.
   Before choosing a number, fetch `develop` and record its `CURRENT_SCHEMA_VERSION`
   and any open schema PRs; take the next free version and rebase on conflict.
2. Plan the before/after records, version transition, transaction boundary,
   constraints/indexes, defaults, and the chain from the baseline. Preserve
   every athlete record class, snapshots, tombstones, settings, and sync state.
   Never rewrite the frozen baseline fixture to make a migration pass, and add
   no fixture for a schema that never reached production.
3. Put migration logic in its cohesive database owner. Reject unknown/newer
   versions or unrecognized shapes before modifying anything. Keep SQLCipher
   enabled; neither an empty data directory nor plaintext startup is an upgrade.
4. Populate a temporary database from the baseline fixture. Assert preserved
   identities, values, relationships, and sync markers, plus new defaults and
   constraints. Inject a failure partway through the migration and verify
   rollback to the unchanged prior schema and rows. Verify same-build restarts
   and the whole chain from the baseline to the current version.
5. Trace backup/restore compatibility and existing-record edits after upgrade.
   Use existing tests such as `tests/test_db_migrations.py` and restore-validation
   tests; select checks with [validation](../pacecraft-validation/SKILL.md).
   Run encrypted integration evidence through the repository Docker/SQLCipher
   workflow. Plain SQLite unit tests alone do not prove encrypted startup.

Report a supported-schema matrix: starting release/version, populated upgrade,
rollback, restart, and encrypted-runtime evidence, each passed/failed/not run.
Missing required upgrade evidence means the schema change is not release-ready.
Update compatibility documentation when behavior changes; never touch live data,
backups, credentials, or token stores. This skill does not authorize a release,
restore, database reset, or removal of older supported upgrade paths.
