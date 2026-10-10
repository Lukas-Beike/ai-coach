"""Data-preserving upgrades against supported frozen release schemas."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.db.manager import DatabaseManager
from backend.db.migrations import migrate_schema
from backend.db.schema import (
    CURRENT_DATABASE_SCHEMA,
    CURRENT_SCHEMA_VERSION,
    configure_cipher,
    database_schema_is_current,
    initialize_schema,
)

RELEASE_SCHEMA = Path(__file__).with_name("fixtures") / "schema_1_12_19.sql.txt"
PREVIOUS_SCHEMA = Path(__file__).with_name("fixtures") / "schema_v2.sql.txt"
RELEASE_1_12_26_SCHEMA = Path(__file__).with_name("fixtures") / "schema_1_12_26.sql.txt"
SCHEMA_V4 = Path(__file__).with_name("fixtures") / "schema_v4.sql.txt"

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

    def seed_all_tables(self, db):
        # One synthetic row per durable table, including FK-linked records.
        for table in CURRENT_DATABASE_SCHEMA:
            if table == "nutrition_products":
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

    def rows(self, db):
        # Columns added by later schema versions are checked separately.
        added_later = {
            ("external_calendar_events", "no_training"),
            ("nutrition_logs", "logged_time_known"),
        }
        return {
            table: [
                tuple(row)
                for row in db.execute(
                    f"SELECT {','.join(column['name'] for column in db.execute(f'PRAGMA table_info({table})') if (table, column['name']) not in added_later)} FROM {table}"
                )
            ]
            for table in CURRENT_DATABASE_SCHEMA
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

        self.assertEqual(self.rows(db), before)
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
                after = self.rows(db)
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

        self.assertEqual(self.rows(db), before)
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

    def test_unknown_or_newer_schema_is_not_modified(self):
        for version in (None, 5, 6, 99):
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
                    self.assertEqual(self.rows(db), before)
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
