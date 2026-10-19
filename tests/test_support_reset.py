"""Regression tests for the shared test reset helper and its table discovery."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import server_test_support as fixtures
from support import application_tables, isolated_server, reset_application_state

server = fixtures.server

TIMESTAMP = "2026-10-01T08:00:00+00:00"
SHA256 = "a" * 64


class ResetApplicationStateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.enterContext(isolated_server(server, Path(temporary.name)))

    def _seed_populated_state(self):
        """Insert one row per table family, including a parent-child chain.

        activity_detail_sets -> activity_records -> activity_sessions and
        activity_laps -> activity_detail_sets form FK chains that the
        alphabetical delete order cannot satisfy without deferred checks.
        """
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "INSERT INTO messages(role, content, created_at) VALUES ('user', 'synthetic question', ?)",
                (TIMESTAMP,),
            )
            db.execute(
                "INSERT INTO provider_records(provider, record_kind, source_record_id, payload, payload_hash, fetched_at, state, created_at, updated_at) "
                "VALUES ('intervals', 'activity', 'i1', '{}', ?, ?, 'active', ?, ?)",
                (SHA256, TIMESTAMP, TIMESTAMP, TIMESTAMP),
            )
            db.execute(
                "INSERT INTO observations(natural_key, metric, value, unit, source_kind, recorded_by, observed_on, mapper_version, created_at, updated_at) "
                "VALUES ('synthetic-observation', 'load', 1.0, 'tss', 'provider', 'sync', '2026-10-01', 1, '2026-10-01T08:00:00+00:00', '2026-10-01T08:00:00+00:00')"
            )
            db.execute(
                "INSERT INTO nutrition_logs(id, meal_date, logged_at, meal_type, description, kcal, created_at, updated_at) "
                "VALUES ('synthetic-meal', '2026-10-01', ?, 'lunch', 'synthetic meal', 500, ?, ?)",
                (TIMESTAMP, TIMESTAMP, TIMESTAMP),
            )
            db.execute(
                "INSERT INTO activity_sessions(activity_id, primary_provider, primary_provider_activity_id, started_at, created_at, updated_at) "
                "VALUES ('act_synthetic1', 'intervals', 'i1', ?, ?, ?)",
                (TIMESTAMP, TIMESTAMP, TIMESTAMP),
            )
            db.execute(
                "INSERT INTO activity_records(provider, provider_activity_id, activity_id, mapper_version, source_kind, recorded_by, "
                "sport, environment, started_at, load_model, fetched_at, created_at, updated_at) "
                "VALUES ('intervals', 'i1', 'act_synthetic1', 1, 'provider', 'sync', 'Ride', 'outdoor', ?, 'synthetic', ?, ?, ?)",
                (TIMESTAMP, TIMESTAMP, TIMESTAMP, TIMESTAMP),
            )
            db.execute(
                "INSERT INTO activity_detail_sets(provider, provider_activity_id, detail_kind, mapper_version, origin, source_kind, "
                "recorded_by, lap_source, content_sha256, fetched_at, created_at, updated_at) "
                "VALUES ('intervals', 'i1', 'laps', 1, 'fetch', 'provider', 'sync', 'provider', ?, ?, ?, ?)",
                (SHA256, TIMESTAMP, TIMESTAMP, TIMESTAMP),
            )
            db.execute(
                "INSERT INTO activity_laps(provider, provider_activity_id, lap_index, kind, start_offset_s, end_offset_s) "
                "VALUES ('intervals', 'i1', 0, 'lap', 0, 60)"
            )
            db.execute(
                "INSERT INTO activity_detail_analysis(activity_id, analysis_version, input_sha256, payload, computed_at, created_at, updated_at) "
                "VALUES ('act_synthetic1', 1, ?, '{}', ?, ?, ?)",
                (SHA256, TIMESTAMP, TIMESTAMP, TIMESTAMP),
            )
            db.execute(
                "INSERT OR REPLACE INTO planning_state(id, revision, updated_at) VALUES (1, 7, ?)",
                (TIMESTAMP,),
            )
            db.execute(
                "INSERT INTO kv(key, value, updated_at) VALUES ('synthetic-key', 'synthetic-value', ?)",
                (TIMESTAMP,),
            )

    def _non_empty_tables(self):
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            non_empty = []
            for table in application_tables(db):
                count = db.execute(f'SELECT COUNT(*) AS n FROM "{table}"').fetchone()["n"]
                if count:
                    non_empty.append(table)
            return set(non_empty)

    def test_discovery_matches_raw_schema_tables_without_internal_tables(self):
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            raw = {
                row["name"]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            discovered = application_tables(db)

        self.assertEqual(set(discovered), {name for name in raw if not name.startswith("sqlite_")})
        self.assertNotIn("sqlite_sequence", discovered)
        self.assertEqual(discovered, sorted(discovered))
        for table in ("activity_laps", "activity_detail_analysis", "planning_state", "kv"):
            self.assertIn(table, discovered)

    def test_reset_clears_populated_state_across_every_table_family(self):
        self._seed_populated_state()
        self.assertIn("activity_laps", self._non_empty_tables())

        reset_application_state(server)

        self.assertEqual(self._non_empty_tables(), {"kv", "planning_state"})

    def test_reset_keeps_foreign_keys_consistent_after_populated_state(self):
        self._seed_populated_state()

        reset_application_state(server)

        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            violations = db.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(violations, [])

    def test_reset_reseeds_planning_state_at_revision_zero(self):
        self._seed_populated_state()

        reset_application_state(server)

        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            rows = db.execute("SELECT id, revision FROM planning_state").fetchall()
        self.assertEqual([(row["id"], row["revision"]) for row in rows], [(1, 0)])

    def test_reset_removes_synthetic_kv_rows_but_writes_profile(self):
        self._seed_populated_state()

        reset_application_state(server)

        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            marker = db.execute(
                "SELECT COUNT(*) AS n FROM kv WHERE key = 'synthetic-key'"
            ).fetchone()["n"]
        self.assertEqual(marker, 0)
        self.assertIn("kv", self._non_empty_tables())

    def test_reset_is_repeatable_on_an_already_empty_database(self):
        reset_application_state(server)
        reset_application_state(server)

        self.assertEqual(self._non_empty_tables(), {"kv", "planning_state"})


if __name__ == "__main__":
    unittest.main()
