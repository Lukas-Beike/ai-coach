"""Data-preserving upgrades against supported frozen release schemas."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.canonical.vocabulary import ProviderId
from backend.db import migrations
from backend.db.manager import DatabaseManager
from backend.db.migrations import migrate_schema
from backend.db.schema import (
    CURRENT_DATABASE_SCHEMA,
    CURRENT_SCHEMA_VERSION,
    configure_cipher,
    database_schema_is_current,
    database_schema_signature,
    initialize_schema,
)
from backend.db.schema_history import (
    SHAPE_SCHEMA_V5,
    SHAPE_SCHEMA_V6,
    SHAPE_SCHEMA_V7,
    SHAPE_SCHEMA_V8,
    released_shape,
)

RELEASE_SCHEMA = Path(__file__).with_name("fixtures") / "schema_1_12_19.sql.txt"
PREVIOUS_SCHEMA = Path(__file__).with_name("fixtures") / "schema_v2.sql.txt"
RELEASE_1_12_26_SCHEMA = Path(__file__).with_name("fixtures") / "schema_1_12_26.sql.txt"
SCHEMA_V4 = Path(__file__).with_name("fixtures") / "schema_v4.sql.txt"
SCHEMA_V5 = Path(__file__).with_name("fixtures") / "schema_v5.sql.txt"
SCHEMA_V6 = Path(__file__).with_name("fixtures") / "schema_v6.sql.txt"
SCHEMA_V7 = Path(__file__).with_name("fixtures") / "schema_v7.sql.txt"
SCHEMA_V8 = Path(__file__).with_name("fixtures") / "schema_v8.sql.txt"
# Tables added by schema version 6; absent from every released shape.
PROVIDER_TABLES = (
    "provider_records",
    "activity_records",
    "activity_sessions",
    "observations",
)
# Columns added by schema version 7. Rows keep every other column unchanged, so
# comparisons that predate the column leave it out and check it separately.
ADDED_IN_V7_COLUMNS = {("activity_feedback", "provider")}
# Schema version 8 adds the remote_links table and the tombstone provider column.
# The table is never part of an older database; the column is checked separately.
ADDED_IN_V8_TABLES = ("remote_links",)
ADDED_IN_V8_COLUMNS = {("competition_sync_tombstones", "provider")}
# Schema version 9 stores canonical sport values: the competition sport column
# and the sport members of the JSON payloads are rewritten (asserted by the
# dedicated canonical-sport tests), every other column and member stays equal.
ADDED_IN_V9_COLUMNS = {
    ("competitions", "environment"),
    ("competitions", "sport_detail"),
    ("competitions", "sport"),
}
ADDED_LATER_COLUMNS = ADDED_IN_V7_COLUMNS | ADDED_IN_V8_COLUMNS | ADDED_IN_V9_COLUMNS
SPORT_MEMBERS = (
    "'$.sport', '$.type', '$.environment', '$.sport_detail', '$.sport_pending'"
)
INTERVALS = ProviderId.INTERVALS.value


def comparable_column(table, name):
    if name == "payload" and table in ("workout_library", "planned_units"):
        return f"CASE WHEN json_valid(payload) THEN json_remove(payload, {SPORT_MEMBERS}) ELSE payload END"
    if table == "kv" and name == "value":
        return f"CASE WHEN key LIKE 'equipment:%' AND json_valid(value) THEN json_remove(value, {SPORT_MEMBERS}) ELSE value END"
    return name


def comparable_columns(db, table, excluded=frozenset()):
    return ",".join(
        comparable_column(table, column["name"])
        for column in db.execute(f"PRAGMA table_info({table})")
        if (table, column["name"]) not in excluded
    )


try:
    from sqlcipher3 import dbapi2 as cipher_backend
except ImportError:
    cipher_backend = None


class DatabaseMigrationTests(unittest.TestCase):
    def connect(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        self.addCleanup(db.close)
        return db

    def old_database(self):
        db = self.connect()
        db.executescript(RELEASE_SCHEMA.read_text(encoding="utf-8"))
        return db

    def previous_database(self):
        db = self.connect()
        db.executescript(PREVIOUS_SCHEMA.read_text(encoding="utf-8"))
        # A prior release may have left the v2 schema unversioned.
        db.execute("PRAGMA user_version = 0")
        return db

    def schema_v4_database(self):
        db = self.connect()
        db.executescript(SCHEMA_V4.read_text(encoding="utf-8"))
        return db

    def release_1_12_26_database(self):
        db = self.connect()
        db.executescript(RELEASE_1_12_26_SCHEMA.read_text(encoding="utf-8"))
        return db

    def schema_v5_database(self):
        db = self.connect()
        db.executescript(SCHEMA_V5.read_text(encoding="utf-8"))
        return db

    def existing_tables(self, db):
        # Tables of the live schema that this database actually contains, in
        # schema order. Older released databases lack the newer tables.
        present = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        return [
            table
            for table in CURRENT_DATABASE_SCHEMA
            if table in present and table not in ADDED_IN_V8_TABLES
        ]

    def full_rows(self, db, tables=None):
        # Every column of every table except the schema-v7 column; the default
        # covers the tables present.
        names = self.existing_tables(db) if tables is None else tables
        return {
            table: [
                tuple(row)
                for row in db.execute(
                    f"SELECT {comparable_columns(db, table, ADDED_LATER_COLUMNS)} "
                    f"FROM {table} ORDER BY rowid"
                )
            ]
            for table in names
        }

    def assert_provider_tables_empty(self, db):
        # Schema v6 creates the canonical provider tables without any backfill.
        for table in PROVIDER_TABLES:
            with self.subTest(table=table):
                self.assertEqual(
                    db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
                )

    def seed_provider_tables(self, db):
        # Valid canonical rows for the v6 tables; the CHECKs reject anything else.
        stamp = "2026-10-01T08:00:00+00:00"
        db.execute(
            "INSERT INTO provider_records(provider, record_kind, source_record_id, "
            "payload, payload_hash, fetched_at, created_at, updated_at) "
            "VALUES ('synthetic-provider', 'activity', 'synthetic-record', "
            '\'{"name":"Synthetic"}\', ?, ?, ?, ?)',
            ("a" * 64, stamp, stamp, stamp),
        )
        db.execute(
            "INSERT INTO activity_sessions(activity_id, primary_provider, "
            "primary_provider_activity_id, started_at, created_at, updated_at) "
            "VALUES ('act_synthetic', 'synthetic-provider', 'synthetic-activity', ?, ?, ?)",
            (stamp, stamp, stamp),
        )
        db.execute(
            "INSERT INTO activity_records(provider, provider_activity_id, activity_id, "
            "mapper_version, source_kind, recorded_by, source_record_id, sport, "
            "environment, started_at, duration_s, distance_m, load, load_model, "
            "avg_hr, avg_power, name, fetched_at, created_at, updated_at) "
            "VALUES ('synthetic-provider', 'synthetic-activity', 'act_synthetic', 1, "
            "'provider_reported', 'manual', 'synthetic-source', 'ride', 'outdoor', "
            "?, 3600.0, 30000.0, 55.0, 'unknown', 140.0, 210.0, "
            "'Synthetic ride', ?, ?, ?)",
            (stamp, stamp, stamp, stamp),
        )
        db.execute(
            "INSERT INTO observations(natural_key, metric, value, unit, source_kind, "
            "recorded_by, provider, source_record_id, observed_on, observed_at, "
            "retrieved_at, label, mapper_version, created_at, updated_at) "
            "VALUES ('synthetic-weight', 'weight', 72.5, 'kg', 'provider_reported', "
            "'manual', 'synthetic-provider', 'synthetic-weight', '2026-10-01', ?, ?, "
            "'Synthetic weight', 1, ?, ?)",
            (stamp, stamp, stamp, stamp),
        )
        db.commit()

    def seed_all_tables(self, db):
        # One synthetic row per durable table present, including FK-linked records.
        for table in self.existing_tables(db):
            if table in ("nutrition_products", *PROVIDER_TABLES):
                continue
            columns = list(db.execute(f"PRAGMA table_info({table})"))
            values = []
            for column in columns:
                name = column["name"]
                value = 1 if column["type"] in ("INTEGER", "REAL") else "synthetic-id"
                if name == "payload":
                    value = '{"date":"2026-10-01"}'
                if name in ("role", "meal_type", "status"):
                    value = {"role": "user", "meal_type": "lunch", "status": "draft"}[
                        name
                    ]
                if name == "status" and table == "sync_jobs":
                    value = "completed"
                if name == "sync_state" and table == "nutrition_sync_dates":
                    value = "pending"
                values.append(value)
            db.execute(
                f"INSERT INTO {table}({','.join(column['name'] for column in columns)}) "
                f"VALUES ({','.join('?' for _ in columns)})",
                values,
            )
        db.commit()

    def rows(self, db, tables=None):
        # Columns added by later schema versions are checked separately.
        added_later = {
            ("external_calendar_events", "no_training"),
            ("nutrition_logs", "logged_time_known"),
            *ADDED_LATER_COLUMNS,
        }
        names = self.existing_tables(db) if tables is None else tables
        return {
            table: [
                tuple(row)
                for row in db.execute(
                    f"SELECT {comparable_columns(db, table, added_later)} FROM {table}"
                )
            ]
            for table in names
            if table != "nutrition_products"
        }

    def test_direct_1_12_19_upgrade_preserves_every_table_and_is_restart_safe(self):
        db = self.old_database()
        db.execute("PRAGMA foreign_keys = ON")
        self.seed_all_tables(db)
        before = self.rows(db)

        migrate_schema(db)
        db.commit()
        migrate_schema(db)
        db.commit()

        self.assertEqual(self.rows(db, before), before)
        self.assert_provider_tables_empty(db)
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )
        self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_previous_schema_upgrade_adds_calendar_signal_and_is_restart_safe(self):
        db = self.previous_database()
        db.execute(
            "INSERT INTO external_calendar_events "
            "(id, uid, name, event_date, start_local, end_local, duration_minutes, updated_at) "
            "VALUES ('calendar', 'uid', 'Synthetic event', '2026-10-07', "
            "'2026-10-07T00:00:00', '2026-10-08T00:00:00', 1440, 'before')"
        )
        db.commit()

        migrate_schema(db)
        db.commit()
        migrate_schema(db)
        db.commit()

        row = db.execute(
            "SELECT name, no_training FROM external_calendar_events WHERE id='calendar'"
        ).fetchone()
        self.assertEqual(tuple(row), ("Synthetic event", 0))
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )

    def test_previous_schema_preserves_non_training_signal_from_legacy_flag(self):
        db = self.previous_database()
        db.execute(
            "INSERT INTO external_calendar_events "
            "(id, uid, name, event_date, start_local, end_local, duration_minutes, "
            "training_relevant, updated_at) VALUES "
            "('legacy-marker', 'uid-marker', 'Appointment [NO_TRAINING]', '2026-10-07', "
            "'2026-10-07T00:00:00', '2026-10-08T00:00:00', 1440, 0, 'before')"
        )
        migrate_schema(db)
        self.assertEqual(
            db.execute(
                "SELECT no_training FROM external_calendar_events WHERE id='legacy-marker'"
            ).fetchone()[0],
            1,
        )

    def test_previous_schema_ambiguous_irrelevant_row_requires_refresh_without_blocker(
        self,
    ):
        db = self.previous_database()
        db.execute(
            "INSERT INTO external_calendar_events "
            "(id, uid, name, event_date, start_local, end_local, duration_minutes, "
            "training_relevant, updated_at) VALUES "
            "('ordinary', 'uid-ordinary', 'Private appointment', '2026-10-07', "
            "'2026-10-07T00:00:00', '2026-10-08T00:00:00', 1440, 0, 'before')"
        )
        migrate_schema(db)
        self.assertEqual(
            tuple(
                db.execute(
                    "SELECT no_training, training_relevant "
                    "FROM external_calendar_events WHERE id='ordinary'"
                ).fetchone()
            ),
            (0, 0),
        )
        self.assertEqual(
            db.execute(
                "SELECT value FROM kv WHERE key='external_calendar_constraints_refresh_required'"
            ).fetchone()[0],
            "1",
        )
        db.commit()
        migrate_schema(db)
        self.assertEqual(
            db.execute(
                "SELECT value FROM kv WHERE key='external_calendar_constraints_refresh_required'"
            ).fetchone()[0],
            "1",
        )

    def test_previous_schema_marked_as_current_is_rejected_without_mutation(self):
        db = self.previous_database()
        db.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
        before = db.execute(
            "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"
        ).fetchall()

        with self.assertRaises(RuntimeError):
            migrate_schema(db)

        after = db.execute(
            "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"
        ).fetchall()
        self.assertEqual(after, before)
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )

    def test_unversioned_1_12_20_preserves_existing_products(self):
        db = self.connect()
        initialize_schema(db)
        db.execute("PRAGMA user_version = 0")
        db.execute(
            "INSERT INTO nutrition_products(id, name, basis_amount, basis_unit, source, created_at, updated_at) VALUES ('synthetic', 'Oats', 100, 'g', 'manual', '2026-10-01', '2026-10-01')"
        )
        db.commit()
        before = list(db.execute("SELECT * FROM nutrition_products").fetchone())

        migrate_schema(db)
        db.commit()

        self.assertEqual(
            list(db.execute("SELECT * FROM nutrition_products").fetchone()), before
        )
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )

    def test_version_2_schema_upgrade_is_supported(self):
        db = self.previous_database()
        db.execute("PRAGMA user_version = 2")

        migrate_schema(db)
        db.commit()

        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )

    def test_1_12_26_upgrade_removes_gemini_state_and_preserves_other_data(self):
        db = self.release_1_12_26_database()
        db.execute("PRAGMA foreign_keys = ON")
        db.executemany(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, 'before')",
            [
                ("profile", '{"name":"Synthetic athlete"}'),
                ("selected_ai_provider", "gemini"),
                ("selected_model_openai", "gpt-6-luna"),
                ("selected_model_gemini", "gemini-test-model"),
                ("openai_conversation_id", "openai-conversation"),
                ("openai_status", '{"state":"ok"}'),
                ("openai_usage", '{"2026-10-07":{"requests":1}}'),
                ("openai_rate_limits", '{"remaining":9}'),
                ("last_coach_ai_provider", "gemini"),
                ("gemini_status", '{"state":"error"}'),
                ("gemini_usage", '{"2026-10-07":{"requests":2}}'),
                ("gemini_conversation_id", "gemini-conversation"),
                ("gemini_conversation_history", '[{"role":"user"}]'),
                ("gemini_call_names", '{"call":"private-name"}'),
            ],
        )
        db.executemany(
            "INSERT INTO messages(role, content, client_turn_id, created_at) "
            "VALUES ('user', ?, ?, 'before')",
            [
                ("Gemini queued prompt", "gemini-queued"),
                ("Gemini running prompt", "gemini-running"),
                ("Gemini completed prompt", "gemini-completed"),
                ("OpenAI prompt", "openai-turn"),
                ("Unattributed legacy prompt", None),
                ("Malformed legacy prompt", "malformed-turn"),
                ("Unknown receipt prompt", "unknown-turn"),
            ],
        )
        command_rows = (
            ("gemini-queued", "queued", "gemini"),
            ("gemini-running", "running", "gemini"),
            ("gemini-completed", "completed", "gemini"),
            ("openai-turn", "queued", "openai"),
        )
        for turn_id, status, provider in command_rows:
            receipt = {
                "ai_provider": provider,
                "status": "partial",
                "awaiting_clarification": False,
                "error": "Synthetic safe failure",
                "diagnostic_error": {"type": "SyntheticError", "frames": []},
                "client_turn_id": turn_id,
                "sync_job_ids": [],
                "intent": {
                    "operation": "save_checkin",
                    "request": "Synthetic private athlete dialogue",
                    "follow_up_operations": ["apply_workout_library_plan"],
                },
                "pending_operations": ["apply_workout_library_plan"],
                "pending_tool_calls": [
                    {
                        "tool": "apply_workout_library_plan",
                        "arguments": {"notes": "private"},
                    }
                ],
                "pending_tool_outputs": [{"output": "private"}],
                "user_message_id": turn_id,
                "message": {
                    "id": 41,
                    "role": "assistant",
                    "content": "private response text",
                    "client_turn_id": turn_id,
                },
                "command_receipts": [
                    {
                        "tool": "save_checkin",
                        "arguments": {"checkin_date": "2026-10-07"},
                        "result": {"ok": True, "status": "saved"},
                    }
                ],
                "proposed_actions": [
                    {"action_type": "save_checkin", "proposal_id": "proposal-1"}
                ],
            }
            db.execute(
                "INSERT INTO coach_commands(id, client_turn_id, conversation_id, "
                "intent, target_system, status, receipt, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'local', ?, ?, 'before', 'before')",
                (
                    f"command-{turn_id}",
                    turn_id,
                    f"{provider}-conversation",
                    '{"scope":"synthetic"}',
                    status,
                    json.dumps(receipt),
                ),
            )
        db.execute(
            "INSERT INTO coach_commands(id, client_turn_id, conversation_id, "
            "intent, target_system, status, receipt, created_at, updated_at) "
            "VALUES ('malformed-command', 'malformed-turn', 'legacy-conversation', "
            "'{}', 'local', 'completed', 'not-json', 'before', 'before')"
        )
        db.execute(
            "INSERT INTO coach_commands(id, client_turn_id, conversation_id, "
            "intent, target_system, status, receipt, created_at, updated_at) "
            "VALUES ('unknown-command', 'unknown-turn', 'unknown-conversation', "
            "'{}', 'local', 'completed', '{\"model\":\"legacy\"}', 'before', 'before')"
        )
        db.executemany(
            "INSERT INTO coach_plan_artifacts(id, conversation_id, client_turn_id, "
            "base_revision, status, payload, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, 'draft', '{}', 'before', 'before')",
            [
                ("gemini-artifact", "artifact-gemini-conversation", "gemini-completed"),
                ("openai-artifact", "openai-artifact-conversation", "openai-turn"),
            ],
        )
        db.execute(
            "UPDATE coach_plan_artifacts SET payload=? WHERE id='gemini-artifact'",
            ('{"approved_action":"preserve","plan":"synthetic"}',),
        )
        db.execute(
            "INSERT INTO training_plans(id, name, goal, start_date, end_date, status, created_at, updated_at) "
            "VALUES ('plan', 'Synthetic plan', 'Base', '2026-10-01', '2026-10-31', 'active', 'before', 'before')"
        )
        db.execute(
            "INSERT INTO workout_library(id, local_id, payload, updated_at) "
            "VALUES ('workout', 'local-workout', '{\"date\":\"2026-10-01\"}', 'before')"
        )
        db.commit()

        migrate_schema(db)
        db.commit()
        after_first_run = list(db.iterdump())
        migrate_schema(db)
        db.commit()

        self.assertEqual(list(db.iterdump()), after_first_run)
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )
        values = dict(db.execute("SELECT key, value FROM kv").fetchall())
        self.assertEqual(values["profile"], '{"name":"Synthetic athlete"}')
        self.assertEqual(values["selected_ai_provider"], "openai")
        selected_provider = db.execute(
            "SELECT updated_at FROM kv WHERE key='selected_ai_provider'"
        ).fetchone()[0]
        self.assertNotEqual(selected_provider, "before")
        self.assertEqual(values["selected_model_openai"], "gpt-6-luna")
        self.assertEqual(values["openai_conversation_id"], "openai-conversation")
        self.assertEqual(values["openai_status"], '{"state":"ok"}')
        self.assertEqual(values["openai_usage"], '{"2026-10-07":{"requests":1}}')
        self.assertEqual(values["openai_rate_limits"], '{"remaining":9}')
        self.assertNotIn("last_coach_ai_provider", values)
        self.assertNotIn("selected_model_gemini", values)
        self.assertNotIn("gemini_status", values)
        self.assertNotIn("gemini_usage", values)
        self.assertNotIn("gemini_conversation_id", values)
        self.assertNotIn("gemini_conversation_history", values)
        self.assertNotIn("gemini_call_names", values)
        self.assertEqual(
            [row[0] for row in db.execute("SELECT content FROM messages ORDER BY id")],
            [
                "OpenAI prompt",
                "Unattributed legacy prompt",
                "Malformed legacy prompt",
                "Unknown receipt prompt",
            ],
        )
        self.assertEqual(
            [
                row[0]
                for row in db.execute(
                    "SELECT content FROM messages WHERE client_turn_id IN "
                    "('malformed-turn', 'unknown-turn') ORDER BY id"
                )
            ],
            ["Malformed legacy prompt", "Unknown receipt prompt"],
        )
        commands = {
            row["client_turn_id"]: row
            for row in db.execute(
                "SELECT client_turn_id, conversation_id, intent, status, error_class, receipt "
                "FROM coach_commands"
            )
        }
        for turn_id in ("gemini-queued", "gemini-running"):
            self.assertEqual(commands[turn_id]["status"], "cancelled")
            self.assertEqual(
                commands[turn_id]["error_class"], "gemini_provider_state_removed"
            )
            self.assertIsNone(commands[turn_id]["conversation_id"])
            self.assertEqual(commands[turn_id]["intent"], "{}")
            self.assertEqual(
                json.loads(commands[turn_id]["receipt"]),
                {
                    "status": "cancelled",
                    "phase": "migration_gemini_removed",
                    "error": "gemini_provider_state_removed",
                },
            )
        completed_receipt = json.loads(commands["gemini-completed"]["receipt"])
        self.assertEqual(
            completed_receipt["command_receipts"],
            [
                {
                    "tool": "save_checkin",
                    "arguments": {"checkin_date": "2026-10-07"},
                    "result": {"ok": True, "status": "saved"},
                }
            ],
        )
        self.assertNotIn("message", completed_receipt)
        for key in (
            "intent",
            "pending_operations",
            "pending_tool_calls",
            "pending_tool_outputs",
        ):
            self.assertNotIn(key, completed_receipt)
        self.assertEqual(commands["gemini-completed"]["intent"], "{}")
        self.assertEqual(
            completed_receipt["proposed_actions"],
            [{"action_type": "save_checkin", "proposal_id": "proposal-1"}],
        )
        self.assertEqual(commands["openai-turn"]["status"], "queued")
        self.assertEqual(
            commands["openai-turn"]["conversation_id"], "openai-conversation"
        )
        self.assertEqual(
            commands["malformed-turn"]["conversation_id"], "legacy-conversation"
        )
        self.assertEqual(
            commands["unknown-turn"]["conversation_id"], "unknown-conversation"
        )
        self.assertIsNone(
            db.execute(
                "SELECT conversation_id FROM coach_plan_artifacts "
                "WHERE id='gemini-artifact'"
            ).fetchone()[0]
        )
        self.assertEqual(
            db.execute(
                "SELECT payload FROM coach_plan_artifacts WHERE id='gemini-artifact'"
            ).fetchone()[0],
            '{"approved_action":"preserve","plan":"synthetic"}',
        )
        self.assertEqual(
            db.execute(
                "SELECT conversation_id FROM coach_plan_artifacts "
                "WHERE id='openai-artifact'"
            ).fetchone()[0],
            "openai-artifact-conversation",
        )
        self.assertEqual(
            db.execute("SELECT name FROM training_plans").fetchone()[0],
            "Synthetic plan",
        )
        self.assertEqual(
            db.execute("SELECT local_id FROM workout_library").fetchone()[0],
            "local-workout",
        )

    def test_gemini_cleanup_runs_for_every_supported_schema(self):
        for factory, version in (
            (self.old_database, 0),
            (self.old_database, 1),
            (self.previous_database, 0),
            (self.previous_database, 2),
            (self.release_1_12_26_database, 0),
            (self.release_1_12_26_database, 3),
        ):
            with self.subTest(schema=factory.__name__, version=version):
                db = factory()
                db.execute(f"PRAGMA user_version = {version}")
                self.seed_all_tables(db)
                db.executemany(
                    "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, 'before')",
                    [("selected_ai_provider", "gemini"), ("gemini_usage", "{}")],
                )
                db.commit()
                before = self.rows(db)
                before_kv = dict(db.execute("SELECT key, value FROM kv"))

                migrate_schema(db)
                db.commit()
                self.assertTrue(database_schema_is_current(db))
                values = dict(db.execute("SELECT key, value FROM kv"))
                expected_kv = {
                    key: value
                    for key, value in before_kv.items()
                    if key != "gemini_usage"
                }
                expected_kv["selected_ai_provider"] = "openai"
                self.assertEqual(values, expected_kv)
                after = self.rows(db, before)
                before.pop("kv")
                after.pop("kv")
                self.assertEqual(after, before)
                snapshot = list(db.iterdump())
                migrate_schema(db)
                db.commit()
                self.assertEqual(list(db.iterdump()), snapshot)

    def test_openai_provider_configuration_is_byte_for_byte_preserved(self):
        db = self.release_1_12_26_database()
        db.executemany(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, 'before')",
            [
                ("selected_ai_provider", "openai"),
                ("last_coach_ai_provider", "openai"),
                ("selected_model_openai", "gpt-6-luna"),
                ("openai_conversation_id", "conv_openai"),
                ("openai_usage", "{}"),
                ("openai_status", "{}"),
                ("openai_rate_limits", "{}"),
            ],
        )
        db.commit()
        before = {
            row["key"]: (row["value"], row["updated_at"])
            for row in db.execute("SELECT key, value, updated_at FROM kv")
        }
        migrate_schema(db)
        db.commit()
        self.assertEqual(
            {
                row["key"]: (row["value"], row["updated_at"])
                for row in db.execute("SELECT key, value, updated_at FROM kv")
            },
            before,
        )

    def test_unknown_and_malformed_receipts_never_attribute_messages_to_gemini(self):
        for receipt in (
            None,
            "",
            "not-json",
            "null",
            "[]",
            '"gemini"',
            "{}",
            '{"model":"gemini-legacy"}',
            '{"ai_provider":"openai"}',
            '{"ai_provider":"unknown"}',
            '{"ai_provider":null}',
            '{"ai_provider":["gemini"]}',
            '{"ai_provider":"GEMINI"}',
            '{"provider":"gemini"}',
            '{"ai_provider":"openai","ai_provider":"gemini"}',
            '{"ai_provider":"gemini","usage":NaN}',
        ):
            with self.subTest(receipt=receipt):
                db = self.release_1_12_26_database()
                db.execute(
                    "INSERT INTO kv VALUES ('selected_ai_provider', 'gemini', 'before')"
                )
                db.execute(
                    "INSERT INTO messages(role, content, client_turn_id, created_at) "
                    "VALUES ('user', 'Unknown provenance', 'turn', 'before')"
                )
                db.execute(
                    "INSERT INTO coach_commands(id, client_turn_id, conversation_id, "
                    "intent, target_system, status, receipt, created_at, updated_at) "
                    "VALUES ('command', 'turn', 'conv_unknown', '{}', 'local', "
                    "'queued', ?, 'before', 'before')",
                    (receipt,),
                )
                before_commands = [
                    tuple(row) for row in db.execute("SELECT * FROM coach_commands")
                ]
                before_messages = [
                    tuple(row) for row in db.execute("SELECT * FROM messages")
                ]
                migrate_schema(db)
                db.commit()
                self.assertEqual(
                    [tuple(row) for row in db.execute("SELECT * FROM coach_commands")],
                    before_commands,
                )
                self.assertEqual(
                    [tuple(row) for row in db.execute("SELECT * FROM messages")],
                    before_messages,
                )

    def test_only_explicit_gemini_conversation_references_are_cleared(self):
        db = self.release_1_12_26_database()
        db.executemany(
            "INSERT INTO kv VALUES (?, ?, 'before')",
            [
                ("gemini_conversation_id", "legacy_gemini_id"),
                ("openai_conversation_id", "conv_openai"),
            ],
        )
        for conversation_id in (
            "gemini_explicit",
            "legacy_gemini_id",
            "conv_openai",
            "conv_unknown",
        ):
            db.execute(
                "INSERT INTO coach_commands(id, client_turn_id, conversation_id, "
                "intent, target_system, status, receipt, created_at, updated_at) "
                "VALUES (?, ?, ?, '{}', 'local', 'completed', '{}', 'before', 'before')",
                (conversation_id, conversation_id, conversation_id),
            )
            db.execute(
                "INSERT INTO coach_plan_artifacts(id, conversation_id, base_revision, "
                "status, payload, created_at, updated_at) "
                "VALUES (?, ?, 0, 'committed', '{}', 'before', 'before')",
                (conversation_id, conversation_id),
            )
        migrate_schema(db)
        db.commit()
        for table in ("coach_commands", "coach_plan_artifacts"):
            self.assertEqual(
                dict(db.execute(f"SELECT id, conversation_id FROM {table}")),
                {
                    "gemini_explicit": None,
                    "legacy_gemini_id": None,
                    "conv_openai": "conv_openai",
                    "conv_unknown": "conv_unknown",
                },
            )

    def test_pending_dialogue_erasure_requires_exclusively_proven_gemini_sources(self):
        for source_ids, remove in (
            ([1], True),
            ([1, 1], True),
            ([2], False),
            ([1, 2], False),
            ([999], False),
            ([], False),
            ([True], False),
            (["1"], False),
            (None, False),
        ):
            with self.subTest(source_ids=source_ids):
                db = self.release_1_12_26_database()
                for message_id, provider in ((1, "gemini"), (2, "openai")):
                    db.execute(
                        "INSERT INTO messages(id, role, content, client_turn_id, created_at) "
                        "VALUES (?, 'user', 'Synthetic prompt', ?, 'before')",
                        (message_id, provider),
                    )
                    db.execute(
                        "INSERT INTO coach_commands(id, client_turn_id, intent, "
                        "target_system, status, receipt, created_at, updated_at) "
                        "VALUES (?, ?, '{}', 'local', 'completed', ?, 'before', 'before')",
                        (provider, provider, json.dumps({"ai_provider": provider})),
                    )
                pending = json.dumps(
                    {
                        "summary": "Synthetic pending request",
                        "source_message_ids": source_ids,
                    }
                )
                db.execute(
                    "INSERT INTO kv VALUES ('coach_pending_request', ?, 'before')",
                    (pending,),
                )
                migrate_schema(db)
                db.commit()
                remaining = db.execute(
                    "SELECT value FROM kv WHERE key='coach_pending_request'"
                ).fetchone()
                if remove:
                    self.assertIsNone(remaining)
                else:
                    self.assertEqual(remaining[0], pending)

    def test_gemini_migration_sql_failure_rolls_back_state_messages_and_version(self):
        db = self.release_1_12_26_database()
        db.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES "
            "('gemini_conversation_history', 'synthetic-history', 'before')"
        )
        db.executemany(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, 'before')",
            [("selected_ai_provider", "gemini"), ("gemini_usage", "synthetic-usage")],
        )
        db.execute(
            "INSERT INTO messages(role, content, client_turn_id, created_at) "
            "VALUES ('user', 'synthetic Gemini text', 'turn', 'before')"
        )
        db.execute(
            "INSERT INTO kv VALUES ('coach_pending_request', "
            '\'{"summary":"Synthetic pending request","source_message_ids":[1]}\', \'before\')'
        )
        db.execute(
            "INSERT INTO coach_commands(id, client_turn_id, intent, target_system, status, receipt, created_at, updated_at) "
            "VALUES ('command', 'turn', '{\"private\":true}', 'local', 'running', '{\"ai_provider\":\"gemini\",\"message\":\"private\"}', 'before', 'before')"
        )
        db.commit()
        before = list(db.iterdump())
        db.execute(
            "CREATE TEMP TRIGGER fail_gemini_cleanup BEFORE DELETE ON main.kv "
            "WHEN OLD.key='gemini_usage' BEGIN "
            "SELECT RAISE(ABORT, 'injected cleanup failure'); END"
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "injected cleanup failure"):
            migrate_schema(db)

        self.assertEqual(list(db.iterdump()), before)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
        db.execute("DROP TRIGGER fail_gemini_cleanup")
        migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))

    def test_failure_after_table_creation_rolls_back_and_can_be_retried(self):
        db = self.old_database()
        self.seed_all_tables(db)
        before = self.rows(db)
        with (
            patch(
                "backend.db.migrations.NUTRITION_PRODUCTS_DDL",
                "CREATE TABLE nutrition_products (id TEXT); INVALID SQL;",
            ),
            self.assertRaises(sqlite3.OperationalError),
        ):
            migrate_schema(db)

        self.assertIsNone(
            db.execute(
                "SELECT name FROM sqlite_master WHERE name='nutrition_products'"
            ).fetchone()
        )
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
        self.assertEqual(self.rows(db), before)
        migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))

    def test_invalid_migration_result_is_rolled_back(self):
        db = self.old_database()
        with (
            patch(
                "backend.db.migrations.NUTRITION_PRODUCTS_DDL",
                "CREATE TABLE nutrition_products (id TEXT);",
            ),
            self.assertRaisesRegex(RuntimeError, "validiert"),
        ):
            migrate_schema(db)
        self.assertIsNone(
            db.execute(
                "SELECT name FROM sqlite_master WHERE name='nutrition_products'"
            ).fetchone()
        )
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_schema_v4_upgrade_preserves_data_and_defaults_meal_time_known(self):
        db = self.schema_v4_database()
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
        self.seed_all_tables(db)
        before = self.rows(db)

        migrate_schema(db)
        db.commit()
        migrate_schema(db)
        db.commit()

        self.assertEqual(self.rows(db, before), before)
        self.assert_provider_tables_empty(db)
        self.assertEqual(
            db.execute("SELECT logged_time_known FROM nutrition_logs").fetchone()[0],
            1,
        )
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )
        self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_release_1_12_26_upgrades_directly_to_current_and_keeps_meal_logs(self):
        db = self.release_1_12_26_database()
        db.execute(
            "INSERT INTO nutrition_logs(id, meal_date, logged_at, meal_type, description, kcal, created_at, updated_at) "
            "VALUES ('meal-1', '2026-09-15', '2026-09-15T13:00:00', 'lunch', 'Synthetic meal', 500, 'now', 'now')"
        )
        db.commit()

        migrate_schema(db)
        db.commit()

        self.assertEqual(
            tuple(
                db.execute(
                    "SELECT description, meal_type, logged_time_known FROM nutrition_logs WHERE id='meal-1'"
                ).fetchone()
            ),
            ("Synthetic meal", "lunch", 1),
        )
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )

    def test_schema_v4_failed_validation_rolls_back_and_can_be_retried(self):
        db = self.schema_v4_database()
        self.seed_all_tables(db)
        before = self.rows(db)
        with (
            patch(
                "backend.db.migrations.database_schema_is_current",
                return_value=False,
            ),
            self.assertRaisesRegex(RuntimeError, "validiert"),
        ):
            migrate_schema(db)

        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
        columns = {
            row["name"] for row in db.execute("PRAGMA table_info(nutrition_logs)")
        }
        self.assertNotIn("logged_time_known", columns)
        self.assertEqual(self.rows(db), before)

        migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))

    def test_schema_v4_marked_as_current_is_rejected_without_mutation(self):
        db = self.schema_v4_database()
        db.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
        db.commit()
        before = list(db.iterdump())

        with self.assertRaises(RuntimeError):
            migrate_schema(db)

        self.assertEqual(list(db.iterdump()), before)

    def test_schema_v5_fixture_is_released_schema_v5(self):
        db = self.schema_v5_database()
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 5)
        self.assertEqual(released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V5)
        self.assertFalse(database_schema_is_current(db))
        self.assertEqual(
            set(self.existing_tables(db)),
            set(CURRENT_DATABASE_SCHEMA)
            - set(PROVIDER_TABLES)
            - set(ADDED_IN_V8_TABLES),
        )

    def test_schema_v5_populated_database_upgrades_preserving_rows_and_is_restart_stable(
        self,
    ):
        db = self.schema_v5_database()
        self.seed_all_tables(db)
        before_rows = self.full_rows(db)

        migrate_schema(db)
        db.commit()
        upgraded_dump = list(db.iterdump())

        self.assertEqual(self.full_rows(db, before_rows), before_rows)
        self.assert_provider_tables_empty(db)
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )

        migrate_schema(db)
        db.commit()
        self.assertEqual(list(db.iterdump()), upgraded_dump)
        self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_schema_v5_database_file_upgrades_once_and_reopens_unchanged(self):
        with tempfile.TemporaryDirectory() as data_dir:
            path = Path(data_dir) / "schema-v5.sqlite3"
            with closing(sqlite3.connect(path)) as setup:
                setup.row_factory = sqlite3.Row
                setup.executescript(SCHEMA_V5.read_text(encoding="utf-8"))
                self.seed_all_tables(setup)
                v5_rows = self.full_rows(setup)
            with closing(sqlite3.connect(path)) as upgrade:
                upgrade.row_factory = sqlite3.Row
                migrate_schema(upgrade)
                upgrade.commit()
                self.assertEqual(self.full_rows(upgrade, v5_rows), v5_rows)
                self.assert_provider_tables_empty(upgrade)
                self.seed_provider_tables(upgrade)

            with closing(sqlite3.connect(path)) as snapshot:
                snapshot.row_factory = sqlite3.Row
                before_rows = self.full_rows(snapshot)
                before_dump = list(snapshot.iterdump())

            for _ in range(2):
                with closing(sqlite3.connect(path)) as db:
                    db.row_factory = sqlite3.Row
                    migrate_schema(db)
                    db.commit()
                    self.assertEqual(self.full_rows(db), before_rows)
                    self.assertEqual(list(db.iterdump()), before_dump)
                    self.assertEqual(
                        db.execute("PRAGMA user_version").fetchone()[0],
                        CURRENT_SCHEMA_VERSION,
                    )

    def test_schema_v5_upgrade_failure_rolls_back_and_can_be_retried(self):
        db = self.schema_v5_database()
        self.seed_all_tables(db)
        before_dump = list(db.iterdump())
        with (
            patch(
                "backend.db.migrations.PROVIDER_TABLES_DDL",
                "CREATE TABLE provider_records (id TEXT); INVALID SQL;",
            ),
            self.assertRaises(sqlite3.OperationalError),
        ):
            migrate_schema(db)
        self.assertEqual(list(db.iterdump()), before_dump)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 5)

        migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))
        self.assert_provider_tables_empty(db)

    def test_schema_v5_upgrade_validation_failure_rolls_back(self):
        db = self.schema_v5_database()
        self.seed_all_tables(db)
        before_dump = list(db.iterdump())
        with (
            patch(
                "backend.db.migrations.database_schema_is_current",
                return_value=False,
            ),
            self.assertRaisesRegex(RuntimeError, "validiert"),
        ):
            migrate_schema(db)
        self.assertEqual(list(db.iterdump()), before_dump)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 5)

    def test_schema_v5_unsupported_versions_are_rejected_without_modification(self):
        for version in (1, 2, 3, 4, 6, 8, 99):
            with self.subTest(version=version):
                db = self.schema_v5_database()
                self.seed_all_tables(db)
                db.execute(f"PRAGMA user_version = {version}")
                db.commit()
                before = list(db.iterdump())
                with self.assertRaises(RuntimeError):
                    migrate_schema(db)
                self.assertEqual(list(db.iterdump()), before)
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0], version
                )

    def test_schema_v5_with_unknown_column_is_rejected_without_modification(self):
        db = self.schema_v5_database()
        db.execute("ALTER TABLE kv ADD COLUMN unknown TEXT")
        db.commit()
        before = list(db.iterdump())
        with self.assertRaises(RuntimeError):
            migrate_schema(db)
        self.assertEqual(list(db.iterdump()), before)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 5)

    def schema_v6_database(self):
        db = self.connect()
        db.executescript(SCHEMA_V6.read_text(encoding="utf-8"))
        return db

    def test_schema_v6_fixture_is_released_schema_v6(self):
        db = self.schema_v6_database()
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 6)
        self.assertEqual(released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V6)
        self.assertFalse(database_schema_is_current(db))
        self.assertNotIn(
            "provider",
            {row[1] for row in db.execute("PRAGMA table_info(activity_feedback)")},
        )

    def test_schema_v6_populated_database_upgrades_preserving_rows_and_is_restart_stable(
        self,
    ):
        db = self.schema_v6_database()
        self.seed_all_tables(db)
        self.seed_provider_tables(db)
        before_rows = self.full_rows(db)

        migrate_schema(db)
        db.commit()
        upgraded_dump = list(db.iterdump())

        self.assertEqual(self.full_rows(db, before_rows), before_rows)
        self.assertEqual(
            db.execute(
                "SELECT COUNT(*) FROM activity_feedback WHERE provider IS NOT NULL"
            ).fetchone()[0],
            0,
        )
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )

        migrate_schema(db)
        db.commit()
        self.assertEqual(list(db.iterdump()), upgraded_dump)
        self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_schema_v6_database_file_upgrades_once_and_reopens_unchanged(self):
        with tempfile.TemporaryDirectory() as data_dir:
            path = Path(data_dir) / "schema-v6.sqlite3"
            with closing(sqlite3.connect(path)) as setup:
                setup.row_factory = sqlite3.Row
                setup.executescript(SCHEMA_V6.read_text(encoding="utf-8"))
                self.seed_all_tables(setup)
                self.seed_provider_tables(setup)
                v6_rows = self.full_rows(setup)
            with closing(sqlite3.connect(path)) as upgrade:
                upgrade.row_factory = sqlite3.Row
                migrate_schema(upgrade)
                upgrade.commit()
                self.assertEqual(self.full_rows(upgrade, v6_rows), v6_rows)
                before_dump = list(upgrade.iterdump())

            for _ in range(2):
                with closing(sqlite3.connect(path)) as db:
                    db.row_factory = sqlite3.Row
                    migrate_schema(db)
                    db.commit()
                    self.assertEqual(self.full_rows(db), v6_rows)
                    self.assertEqual(list(db.iterdump()), before_dump)
                    self.assertEqual(
                        db.execute("PRAGMA user_version").fetchone()[0],
                        CURRENT_SCHEMA_VERSION,
                    )

    def test_schema_v6_upgrade_failure_rolls_back_and_can_be_retried(self):
        db = self.schema_v6_database()
        self.seed_all_tables(db)
        before_dump = list(db.iterdump())
        with (
            patch(
                "backend.db.migrations.ACTIVITY_FEEDBACK_TABLE_SQL",
                "CREATE TABLE activity_feedback (INVALID SQL);",
            ),
            self.assertRaises(sqlite3.OperationalError),
        ):
            migrate_schema(db)
        self.assertEqual(list(db.iterdump()), before_dump)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 6)

        migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))

    def test_schema_v6_unsupported_versions_are_rejected_without_modification(self):
        for version in (1, 2, 3, 4, 5, 7, 8, 99):
            with self.subTest(version=version):
                db = self.schema_v6_database()
                self.seed_all_tables(db)
                db.execute(f"PRAGMA user_version = {version}")
                db.commit()
                before = list(db.iterdump())
                with self.assertRaises(RuntimeError):
                    migrate_schema(db)
                self.assertEqual(list(db.iterdump()), before)
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0], version
                )

    def test_schema_v6_with_unknown_column_is_rejected_without_modification(self):
        db = self.schema_v6_database()
        db.execute("ALTER TABLE observations ADD COLUMN unknown TEXT")
        db.commit()
        before = list(db.iterdump())
        with self.assertRaises(RuntimeError):
            migrate_schema(db)
        self.assertEqual(list(db.iterdump()), before)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 6)

    def schema_v7_database(self):
        db = self.connect()
        db.executescript(SCHEMA_V7.read_text(encoding="utf-8"))
        return db

    def test_schema_v7_fixture_is_released_schema_v7(self):
        db = self.schema_v7_database()
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 7)
        self.assertEqual(released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V7)
        self.assertFalse(database_schema_is_current(db))
        self.assertNotIn(
            "remote_links",
            {row[0] for row in db.execute("SELECT name FROM sqlite_master")},
        )
        self.assertNotIn(
            "provider",
            {
                row[1]
                for row in db.execute("PRAGMA table_info(competition_sync_tombstones)")
            },
        )

    def clone_row(self, db, table, **overrides):
        # Copy the first seeded row of a table with some columns replaced.
        columns = [
            column["name"]
            for column in db.execute(f"PRAGMA table_info({table})")
            if column["name"] != "id"
        ]
        selected = ",".join(
            f"? AS {column}" if column in overrides else column for column in columns
        )
        db.execute(
            f"INSERT INTO {table}({','.join(columns)}) "
            f"SELECT {selected} FROM {table} ORDER BY rowid LIMIT 1",
            [overrides[column] for column in columns if column in overrides],
        )

    def seed_remote_slots(self, db):
        # Layer the legacy remote slots on top of the generic seed rows. Tables
        # a released database lacks are skipped; returns the expected links.
        tables = set(self.existing_tables(db))
        expected = set()
        stamp = "2026-10-01T08:00:00+00:00"
        if "workout_library" in tables:
            db.execute(
                "UPDATE workout_library SET external_id='ext-lib-1', last_synced_at=?, "
                "payload='{\"remote_event_id\": 501}'",
                (stamp,),
            )
            local_id = db.execute("SELECT local_id FROM workout_library").fetchone()[0]
            self.clone_row(
                db,
                "workout_library",
                local_id="lib-duplicate",
                external_id="ext-lib-2",
                last_synced_at=None,
                payload='{"remote_event_id": 501}',
            )
            self.clone_row(
                db,
                "workout_library",
                local_id="lib-malformed",
                external_id=None,
                last_synced_at=None,
                payload="{not json",
            )
            self.clone_row(
                db,
                "workout_library",
                local_id="",
                external_id="ext-blank-local-id",
                last_synced_at=None,
                payload='{"remote_event_id": 502}',
            )
            self.clone_row(
                db,
                "workout_library",
                local_id="lib-local-only",
                external_id=None,
                last_synced_at=None,
                payload='{"remote_event_id": null}',
            )
            expected |= {
                ("library_workout", local_id, "501", "ext-lib-1", "synced", stamp),
                (
                    "library_workout",
                    "lib-duplicate",
                    None,
                    "ext-lib-2",
                    "pending",
                    None,
                ),
            }
        if "planned_units" in tables:
            db.execute(
                "UPDATE planned_units SET external_id=NULL, last_synced_at=?, "
                "baseline_hash='baseline-1', "
                'payload=\'{"remote_event_id": "unit-9"}\'',
                (stamp,),
            )
            local_id = db.execute(
                "SELECT local_id FROM planned_units ORDER BY id LIMIT 1"
            ).fetchone()[0]
            expected.add(("planned_unit", local_id, "unit-9", None, "synced", stamp))
        if "competitions" in tables:
            db.execute(
                "UPDATE competitions SET intervals_event_id='77', "
                "external_id='ext-comp-1', last_synced_at=?",
                (stamp,),
            )
            competition_id = db.execute(
                "SELECT id FROM competitions ORDER BY id LIMIT 1"
            ).fetchone()[0]
            expected.add(
                (
                    "competition",
                    str(competition_id),
                    "77",
                    "ext-comp-1",
                    "synced",
                    stamp,
                )
            )
        db.commit()
        return expected

    def links(self, db):
        return {
            tuple(row)
            for row in db.execute(
                "SELECT entity_kind, local_id, remote_id, remote_external_id, "
                "sync_state, last_synced_at FROM remote_links"
            )
        }

    def test_every_released_schema_upgrades_with_remote_links_backfilled_from_slots(
        self,
    ):
        factories = {
            1: self.old_database,
            2: self.previous_database,
            4: self.schema_v4_database,
            5: self.schema_v5_database,
            6: self.schema_v6_database,
            7: self.schema_v7_database,
        }
        for version, factory in factories.items():
            with self.subTest(version=version):
                db = factory()
                self.seed_all_tables(db)
                expected = self.seed_remote_slots(db)
                tombstones = db.execute(
                    "SELECT COUNT(*) FROM competition_sync_tombstones"
                ).fetchone()[0]
                before_rows = self.rows(db)

                migrate_schema(db)
                db.commit()
                upgraded_dump = list(db.iterdump())

                self.assertTrue(database_schema_is_current(db))
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0],
                    CURRENT_SCHEMA_VERSION,
                )
                self.assertEqual(self.rows(db, before_rows), before_rows)
                self.assertEqual(self.links(db), expected)
                self.assertEqual(
                    {row[0] for row in db.execute("SELECT provider FROM remote_links")}
                    - {INTERVALS},
                    set(),
                )
                self.assertEqual(
                    tuple(
                        db.execute(
                            "SELECT COUNT(*), COUNT(CASE WHEN provider=? THEN 1 END) "
                            "FROM competition_sync_tombstones",
                            (INTERVALS,),
                        ).fetchone()
                    ),
                    (tombstones, tombstones),
                )
                migrate_schema(db)
                db.commit()
                self.assertEqual(list(db.iterdump()), upgraded_dump)
                self.assertEqual(
                    db.execute("PRAGMA integrity_check").fetchone()[0], "ok"
                )
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_schema_v7_database_file_upgrades_once_and_reopens_unchanged(self):
        with tempfile.TemporaryDirectory() as data_dir:
            path = Path(data_dir) / "schema-v7.sqlite3"
            with closing(sqlite3.connect(path)) as setup:
                setup.row_factory = sqlite3.Row
                setup.executescript(SCHEMA_V7.read_text(encoding="utf-8"))
                self.seed_all_tables(setup)
                expected = self.seed_remote_slots(setup)
                v7_rows = self.full_rows(setup)
            with closing(sqlite3.connect(path)) as upgrade:
                upgrade.row_factory = sqlite3.Row
                migrate_schema(upgrade)
                upgrade.commit()
                before_dump = list(upgrade.iterdump())

            for _ in range(2):
                with closing(sqlite3.connect(path)) as db:
                    db.row_factory = sqlite3.Row
                    migrate_schema(db)
                    db.commit()
                    self.assertEqual(self.full_rows(db, v7_rows), v7_rows)
                    self.assertEqual(self.links(db), expected)
                    self.assertEqual(list(db.iterdump()), before_dump)
                    self.assertEqual(
                        db.execute("PRAGMA user_version").fetchone()[0],
                        CURRENT_SCHEMA_VERSION,
                    )

    def test_schema_v7_upgrade_failure_rolls_back_and_can_be_retried(self):
        db = self.schema_v7_database()
        self.seed_all_tables(db)
        expected = self.seed_remote_slots(db)
        before_dump = list(db.iterdump())
        with (
            patch(
                "backend.db.migrations.COMPETITION_SYNC_TOMBSTONES_TABLE_SQL",
                "CREATE TABLE competition_sync_tombstones (INVALID SQL);",
            ),
            self.assertRaises(sqlite3.OperationalError),
        ):
            migrate_schema(db)
        self.assertEqual(list(db.iterdump()), before_dump)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 7)
        self.assertEqual(released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V7)

        migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(self.links(db), expected)

    def test_schema_v7_unsupported_versions_are_rejected_without_modification(self):
        for version in (1, 2, 3, 4, 5, 6, 8, 99):
            with self.subTest(version=version):
                db = self.schema_v7_database()
                self.seed_all_tables(db)
                db.execute(f"PRAGMA user_version = {version}")
                db.commit()
                before = list(db.iterdump())
                with self.assertRaises(RuntimeError):
                    migrate_schema(db)
                self.assertEqual(list(db.iterdump()), before)
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0], version
                )

    def test_schema_v7_with_unknown_column_is_rejected_without_modification(self):
        db = self.schema_v7_database()
        db.execute("ALTER TABLE competition_sync_tombstones ADD COLUMN unknown TEXT")
        db.commit()
        before = list(db.iterdump())
        with self.assertRaises(RuntimeError):
            migrate_schema(db)
        self.assertEqual(list(db.iterdump()), before)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 7)

    def schema_v8_database(self):
        db = self.connect()
        db.executescript(SCHEMA_V8.read_text(encoding="utf-8"))
        return db

    def test_schema_v8_fixture_is_released_schema_v8(self):
        db = self.schema_v8_database()
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 8)
        self.assertEqual(released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V8)
        self.assertFalse(database_schema_is_current(db))
        self.assertNotIn(
            "environment",
            {row[1] for row in db.execute("PRAGMA table_info(competitions)")},
        )

    EQUIPMENT_SPORT_CASES = (
        ("Ride", ("ride", "unknown", False)),
        ("VirtualRide", ("ride", "virtual", False)),
        ("WeightTraining", ("strength", "unknown", False)),
        ("Run", ("run", "unknown", False)),
        ("Cross-country skiing", ("other", "unknown", True)),
        ("", ("other", "unknown", True)),
    )
    COMPETITION_SPORT_CASES = (
        ("Ride", ("ride", "unknown", None)),
        ("VirtualRide", ("ride", "virtual", None)),
        ("Cycling", ("ride", "unknown", None)),
        ("WeightTraining", ("strength", "unknown", None)),
        ("Run", ("run", "unknown", None)),
        ("Obstacle course", ("other", "unknown", "Obstacle course")),
        ("", ("other", "unknown", None)),
    )
    WORKOUT_SPORT_CASES = (
        ("Ride", ("ride", "unknown", None)),
        ("VirtualRide", ("ride", "virtual", None)),
        ("WeightTraining", ("strength", "unknown", None)),
        ("GravelRide", ("ride", "unknown", "GravelRide")),
        ("Basket weaving", ("other", "unknown", "Basket weaving")),
    )

    def seed_sport_tokens(self, db):
        # Layer legacy sport tokens (one row per case) over the generic seed rows.
        tables = set(self.existing_tables(db))
        stamp = "2026-10-01T08:00:00+00:00"
        for index, (token, _) in enumerate(self.EQUIPMENT_SPORT_CASES):
            payload = {"id": f"e{index}", "sport": token, "kind": "bike", "x": [1]}
            db.execute(
                "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?)",
                (f"equipment:e{index}", json.dumps(payload), stamp),
            )
        if "competitions" in tables:
            for index, (token, _) in enumerate(self.COMPETITION_SPORT_CASES):
                self.clone_row(
                    db, "competitions", sport=token, name=f"c{index}", external_id=None
                )
            db.execute("DELETE FROM competitions WHERE name NOT LIKE 'c_'")
        for table in ("workout_library", "planned_units"):
            if table not in tables:
                continue
            for index, (token, _) in enumerate(self.WORKOUT_SPORT_CASES):
                payload = {"name": f"w{index}", "type": token, "target": "AUTO"}
                self.clone_row(
                    db,
                    table,
                    local_id=f"{table}-{index}",
                    external_id=None,
                    payload=json.dumps(payload),
                )
        db.commit()

    def assert_canonical_sports(self, db):
        tables = set(self.existing_tables(db))
        equipment = {
            json.loads(row[0])["id"]: json.loads(row[0])
            for row in db.execute("SELECT value FROM kv WHERE key LIKE 'equipment:e%'")
        }
        for index, (token, expected) in enumerate(self.EQUIPMENT_SPORT_CASES):
            with self.subTest(equipment=token):
                item = equipment[f"e{index}"]
                self.assertEqual(
                    (item["sport"], item["environment"], item["sport_pending"]),
                    expected,
                )
                self.assertEqual(item["kind"], "bike")
                self.assertEqual(item["x"], [1])
        if "competitions" in tables:
            rows = {
                row[0]: tuple(row[1:])
                for row in db.execute(
                    "SELECT name, sport, environment, sport_detail FROM competitions"
                )
            }
            for index, (token, expected) in enumerate(self.COMPETITION_SPORT_CASES):
                with self.subTest(competition=token):
                    self.assertEqual(rows[f"c{index}"], expected)
        for table in ("workout_library", "planned_units"):
            if table not in tables:
                continue
            payloads = {
                json.loads(row[0])["name"]: json.loads(row[0])
                for row in db.execute(f"SELECT payload FROM {table}")
                if row[0].startswith("{") and "name" in row[0]
            }
            for index, (token, expected) in enumerate(self.WORKOUT_SPORT_CASES):
                with self.subTest(table=table, token=token):
                    payload = payloads[f"w{index}"]
                    self.assertNotIn("type", payload)
                    self.assertEqual(
                        (
                            payload["sport"],
                            payload["environment"],
                            payload.get("sport_detail"),
                        ),
                        expected,
                    )
                    self.assertEqual(payload["target"], "AUTO")

    def test_schema_v8_populated_database_upgrades_to_canonical_sports(self):
        db = self.schema_v8_database()
        self.seed_all_tables(db)
        self.seed_sport_tokens(db)
        before_rows = self.full_rows(db)

        migrate_schema(db)
        db.commit()
        upgraded_dump = list(db.iterdump())

        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )
        self.assertEqual(self.full_rows(db, before_rows), before_rows)
        self.assert_canonical_sports(db)
        migrate_schema(db)
        db.commit()
        self.assertEqual(list(db.iterdump()), upgraded_dump)
        self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_every_released_schema_upgrades_with_canonical_sports(self):
        factories = {
            1: self.old_database,
            2: self.previous_database,
            4: self.schema_v4_database,
            5: self.schema_v5_database,
            6: self.schema_v6_database,
            7: self.schema_v7_database,
            8: self.schema_v8_database,
        }
        for version, factory in factories.items():
            with self.subTest(version=version):
                db = factory()
                self.seed_all_tables(db)
                self.seed_sport_tokens(db)
                migrate_schema(db)
                db.commit()
                self.assertTrue(database_schema_is_current(db))
                self.assert_canonical_sports(db)

    def test_schema_v8_database_file_upgrades_once_and_reopens_unchanged(self):
        with tempfile.TemporaryDirectory() as data_dir:
            path = Path(data_dir) / "schema-v8.sqlite3"
            with closing(sqlite3.connect(path)) as setup:
                setup.row_factory = sqlite3.Row
                setup.executescript(SCHEMA_V8.read_text(encoding="utf-8"))
                self.seed_all_tables(setup)
                self.seed_sport_tokens(setup)
                v8_rows = self.full_rows(setup)
            with closing(sqlite3.connect(path)) as upgrade:
                upgrade.row_factory = sqlite3.Row
                migrate_schema(upgrade)
                upgrade.commit()
                before_dump = list(upgrade.iterdump())

            for _ in range(2):
                with closing(sqlite3.connect(path)) as db:
                    db.row_factory = sqlite3.Row
                    migrate_schema(db)
                    db.commit()
                    self.assertEqual(self.full_rows(db, v8_rows), v8_rows)
                    self.assert_canonical_sports(db)
                    self.assertEqual(list(db.iterdump()), before_dump)
                    self.assertEqual(
                        db.execute("PRAGMA user_version").fetchone()[0],
                        CURRENT_SCHEMA_VERSION,
                    )

    def test_schema_v8_upgrade_failure_rolls_back_and_can_be_retried(self):
        db = self.schema_v8_database()
        self.seed_all_tables(db)
        self.seed_sport_tokens(db)
        before_dump = list(db.iterdump())
        real = migrations._canonical_workout_payload
        calls = []

        def fail_on_second(payload):
            calls.append(payload)
            if len(calls) == 2:
                raise sqlite3.OperationalError("synthetic failure")
            return real(payload)

        with (
            patch.object(migrations, "_canonical_workout_payload", fail_on_second),
            self.assertRaises(sqlite3.OperationalError),
        ):
            migrate_schema(db)
        self.assertEqual(list(db.iterdump()), before_dump)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 8)
        self.assertEqual(released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V8)

        migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))
        self.assert_canonical_sports(db)

    def test_schema_v8_unsupported_versions_are_rejected_without_modification(self):
        for version in (1, 2, 3, 4, 5, 6, 7, 99):
            with self.subTest(version=version):
                db = self.schema_v8_database()
                self.seed_all_tables(db)
                db.execute(f"PRAGMA user_version = {version}")
                db.commit()
                before = list(db.iterdump())
                with self.assertRaises(RuntimeError):
                    migrate_schema(db)
                self.assertEqual(list(db.iterdump()), before)
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0], version
                )

    def test_schema_v8_with_unknown_column_is_rejected_without_modification(self):
        db = self.schema_v8_database()
        db.execute("ALTER TABLE competitions ADD COLUMN unknown TEXT")
        db.commit()
        before = list(db.iterdump())
        with self.assertRaises(RuntimeError):
            migrate_schema(db)
        self.assertEqual(list(db.iterdump()), before)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 8)

    def test_newer_schema_version_is_rejected_without_modification(self):
        db = self.connect()
        initialize_schema(db)
        db.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION + 1}")
        db.commit()
        before = list(db.iterdump())
        with self.assertRaises(RuntimeError):
            migrate_schema(db)
        self.assertEqual(list(db.iterdump()), before)

    def test_remote_links_reject_duplicate_remote_ids_per_provider_and_kind(self):
        db = self.connect()
        initialize_schema(db)
        insert = (
            "INSERT INTO remote_links(entity_kind, local_id, provider, remote_id, "
            "sync_state) VALUES (?, ?, ?, ?, 'synced')"
        )
        db.execute(insert, ("competition", "1", INTERVALS, "9"))
        db.execute(insert, ("competition", "2", "other-provider", "9"))
        db.execute(insert, ("library_workout", "1", INTERVALS, "9"))
        db.execute(insert, ("competition", "3", INTERVALS, None))
        db.execute(insert, ("competition", "4", INTERVALS, None))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(insert, ("competition", "5", INTERVALS, "9"))

    def test_unknown_or_newer_schema_is_not_modified(self):
        for version in (None, 5, 6, 7, 99):
            with self.subTest(version=version):
                db = self.old_database()
                if version is not None:
                    db.execute(f"PRAGMA user_version = {version}")
                else:
                    db.execute("ALTER TABLE messages ADD COLUMN unknown TEXT")
                db.commit()
                before = list(db.iterdump())
                with self.assertRaises(RuntimeError):
                    migrate_schema(db)
                self.assertEqual(list(db.iterdump()), before)
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0],
                    0 if version is None else version,
                )

    def test_old_schema_with_changed_column_definition_is_not_migrated(self):
        db = self.old_database()
        db.executescript(
            """
            ALTER TABLE messages RENAME TO messages_original;
            CREATE TABLE messages (
                attachments TEXT NOT NULL DEFAULT '[]',
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT,
                client_turn_id TEXT,
                created_at TEXT NOT NULL
            );
            INSERT INTO messages(id, role, content, client_turn_id, created_at)
                SELECT id, role, content, client_turn_id, created_at FROM messages_original;
            DROP TABLE messages_original;
            """
        )
        db.commit()
        before = list(db.iterdump())

        with self.assertRaises(RuntimeError):
            migrate_schema(db)

        self.assertEqual(list(db.iterdump()), before)

    def test_unknown_trigger_with_sqlite_like_name_is_rejected(self):
        db = self.old_database()
        db.execute("CREATE TRIGGER sqlitecustom AFTER INSERT ON kv BEGIN SELECT 1; END")
        db.commit()
        before = list(db.iterdump())
        with self.assertRaises(RuntimeError):
            migrate_schema(db)
        self.assertEqual(list(db.iterdump()), before)

    def test_caller_rollback_also_rolls_back_schema_and_version(self):
        with tempfile.TemporaryDirectory() as root:
            manager = DatabaseManager(
                Path(root) / "upgrade.db", sqlite3, row_factory=sqlite3.Row
            )
            self.addCleanup(manager.close)
            with manager.unit_of_work() as db:
                db.executescript(RELEASE_SCHEMA.read_text(encoding="utf-8"))
            with (
                self.assertRaisesRegex(RuntimeError, "startup failure"),
                manager.unit_of_work() as db,
            ):
                migrate_schema(db)
                raise RuntimeError("startup failure")
            with manager.reader() as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
                self.assertIsNone(
                    db.execute(
                        "SELECT name FROM sqlite_master WHERE name='nutrition_products'"
                    ).fetchone()
                )
            manager.close()

    @unittest.skipIf(
        cipher_backend is None, "SQLCipher requires the Docker runtime on Windows"
    )
    def test_encrypted_1_12_19_update_preserves_data_and_reopens_with_same_key(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "encrypted.db"
            options = {
                "password": "synthetic-migration-test-key",
                "configure": configure_cipher,
                "row_factory": cipher_backend.Row,
            }
            manager = DatabaseManager(path, cipher_backend, **options)
            try:
                with manager.unit_of_work() as db:
                    db.executescript(RELEASE_SCHEMA.read_text(encoding="utf-8"))
                    self.seed_all_tables(db)
                    before = self.rows(db)
                with manager.unit_of_work() as db:
                    migrate_schema(db)
            finally:
                manager.close()
            reopened = DatabaseManager(path, cipher_backend, **options)
            try:
                with reopened.unit_of_work() as db:
                    migrate_schema(db)
                    self.assertEqual(self.rows(db, before), before)
                    self.assert_provider_tables_empty(db)
                    self.assertTrue(database_schema_is_current(db))
                    self.assertEqual(
                        db.execute("PRAGMA integrity_check").fetchone()[0], "ok"
                    )
                    self.assertEqual(
                        db.execute("PRAGMA cipher_integrity_check").fetchall(), []
                    )
                    self.assertEqual(
                        db.execute("PRAGMA foreign_key_check").fetchall(), []
                    )
            finally:
                reopened.close()
            self.assertNotEqual(path.read_bytes()[:16], b"SQLite format 3\x00")

    @unittest.skipIf(
        cipher_backend is None, "SQLCipher requires the Docker runtime on Windows"
    )
    def test_encrypted_schema_v7_update_backfills_links_and_reopens_with_same_key(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "encrypted.db"
            options = {
                "password": "synthetic-migration-test-key",
                "configure": configure_cipher,
                "row_factory": cipher_backend.Row,
            }
            manager = DatabaseManager(path, cipher_backend, **options)
            try:
                with manager.unit_of_work() as db:
                    db.executescript(SCHEMA_V7.read_text(encoding="utf-8"))
                    self.seed_all_tables(db)
                    expected = self.seed_remote_slots(db)
                    before = self.full_rows(db)
                with manager.unit_of_work() as db:
                    migrate_schema(db)
            finally:
                manager.close()
            reopened = DatabaseManager(path, cipher_backend, **options)
            try:
                with reopened.unit_of_work() as db:
                    migrate_schema(db)
                    self.assertEqual(self.full_rows(db, before), before)
                    self.assertEqual(self.links(db), expected)
                    self.assertTrue(database_schema_is_current(db))
                    self.assertEqual(
                        db.execute("PRAGMA integrity_check").fetchone()[0], "ok"
                    )
                    self.assertEqual(
                        db.execute("PRAGMA cipher_integrity_check").fetchall(), []
                    )
                    self.assertEqual(
                        db.execute("PRAGMA foreign_key_check").fetchall(), []
                    )
            finally:
                reopened.close()
            self.assertNotEqual(path.read_bytes()[:16], b"SQLite format 3\x00")

    @unittest.skipIf(
        cipher_backend is None, "SQLCipher requires the Docker runtime on Windows"
    )
    def test_encrypted_1_12_26_gemini_migration_reopens_idempotently(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "encrypted.db"
            options = {
                "password": "synthetic-migration-test-key",
                "configure": configure_cipher,
                "row_factory": cipher_backend.Row,
            }
            manager = DatabaseManager(path, cipher_backend, **options)
            try:
                with manager.unit_of_work() as db:
                    db.executescript(RELEASE_1_12_26_SCHEMA.read_text(encoding="utf-8"))
                    db.execute(
                        "INSERT INTO kv(key, value, updated_at) VALUES "
                        "('gemini_conversation_history', 'synthetic-history', 'before')"
                    )
                    db.execute(
                        "INSERT INTO messages(role, content, client_turn_id, created_at) "
                        "VALUES ('user', 'Gemini prompt', 'gemini-turn', 'before')"
                    )
                    db.execute(
                        "INSERT INTO coach_commands(id, client_turn_id, intent, target_system, "
                        "status, receipt, created_at, updated_at) VALUES "
                        "('command', 'gemini-turn', '{}', 'local', 'running', "
                        "'{\"ai_provider\":\"gemini\"}', 'before', 'before')"
                    )
                with manager.unit_of_work() as db:
                    migrate_schema(db)
            finally:
                manager.close()

            reopened = DatabaseManager(path, cipher_backend, **options)
            try:
                with reopened.unit_of_work() as db:
                    migrate_schema(db)
                    self.assertTrue(database_schema_is_current(db))
                    self.assertIsNone(
                        db.execute(
                            "SELECT value FROM kv WHERE key='gemini_conversation_history'"
                        ).fetchone()
                    )
                    self.assertEqual(
                        db.execute(
                            "SELECT status FROM coach_commands WHERE client_turn_id='gemini-turn'"
                        ).fetchone()[0],
                        "cancelled",
                    )
                    self.assertEqual(
                        db.execute("PRAGMA integrity_check").fetchone()[0], "ok"
                    )
                    self.assertEqual(
                        db.execute("PRAGMA cipher_integrity_check").fetchall(), []
                    )
                    self.assertEqual(
                        db.execute("PRAGMA foreign_key_check").fetchall(), []
                    )
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
