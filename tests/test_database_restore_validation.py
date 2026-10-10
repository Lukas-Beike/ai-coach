from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

from backend.backup.restore_validation import (
    DatabaseRestoreValidationConfig,
    DatabaseRestoreValidationService,
)
from backend.db.bootstrap import initialize_application_database
from backend.db.migrations import migrate_schema
from backend.db.repositories import KeyValueRepository
from backend.db.schema import database_schema_is_current, initialize_schema
from backend.errors import AppError

RELEASE_1_12_26_SCHEMA = Path(__file__).with_name("fixtures") / "schema_1_12_26.sql.txt"


def service(data_dir: Path, **overrides: object) -> DatabaseRestoreValidationService:
    values: dict[str, object] = {
        "data_dir": data_dir,
        "maximum_bytes": 1024,
        "app_password": "",
        "sqlcipher_available": False,
        "sqlite_backend": sqlite3,
        "configure_cipher": Mock(),
        "row_factory": sqlite3.Row,
        "schema_is_current": lambda _connection: True,
        "migrate_schema": Mock(),
    }
    values.update(overrides)
    return DatabaseRestoreValidationService(DatabaseRestoreValidationConfig(**values))  # type: ignore[arg-type]


class DatabaseRestoreValidationTests(unittest.TestCase):
    def test_stage_enforces_payload_boundary_and_uses_uuid_filename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            validator = service(Path(directory), maximum_bytes=4)
            for payload in (b"", b"12345"):
                with self.assertRaises(AppError) as raised:
                    validator.stage(payload)
                self.assertEqual(raised.exception.status, 413)
            self.assertEqual(list(Path(directory).iterdir()), [])

            staged = validator.stage(b"safe")
            self.assertRegex(
                staged.name, r"^\.intervals-coach-restore-[0-9a-f]{32}\.db$"
            )
            self.assertEqual(staged.read_bytes(), b"safe")

    def test_validate_commits_session_scrubbing_after_schema_integrity_and_fk_checks(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE sessions (token TEXT)")
                connection.execute("INSERT INTO sessions VALUES ('synthetic-session')")
                connection.commit()
            service(Path(directory)).validate(path)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0
                )

    def test_validate_rejects_unexpected_schema_without_scrubbing_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE sessions (token TEXT)")
                connection.execute("INSERT INTO sessions VALUES ('synthetic-session')")
                connection.commit()
            with self.assertRaises(AppError) as raised:
                service(
                    Path(directory), schema_is_current=lambda _connection: False
                ).validate(path)
            self.assertEqual(raised.exception.status, 400)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1
                )

    def test_validate_rejects_foreign_key_violations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("PRAGMA foreign_keys = OFF")
                connection.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
                connection.execute(
                    "CREATE TABLE children (parent_id INTEGER REFERENCES parents(id))"
                )
                connection.execute("INSERT INTO children VALUES (404)")
                connection.commit()
            with self.assertRaises(AppError) as raised:
                service(Path(directory)).validate(path)
            self.assertEqual(raised.exception.status, 400)

    def test_validate_rejects_failed_integrity_check_before_scrubbing(self) -> None:
        connection = Mock()
        connection.execute.side_effect = lambda statement: {
            "PRAGMA integrity_check": Mock(
                fetchone=Mock(return_value={"integrity_check": "corrupt"})
            ),
            "PRAGMA foreign_key_check": Mock(fetchall=Mock(return_value=[])),
        }.get(statement, Mock())
        backend = Mock(connect=Mock(return_value=connection))
        validator = service(
            Path("unused"), sqlite_backend=backend, sqlcipher_available=True
        )
        with self.assertRaises(AppError) as raised:
            validator.validate(Path("backup.db"))
        self.assertEqual(raised.exception.status, 400)
        self.assertFalse(
            any(
                call.args == ("DELETE FROM sessions",)
                for call in connection.execute.call_args_list
            )
        )
        connection.commit.assert_not_called()
        connection.close.assert_called_once()

    def test_validate_requires_sqlcipher_for_encrypted_restore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backend = Mock()
            validator = service(
                Path(directory),
                app_password="synthetic-key",
                sqlcipher_available=False,
                sqlite_backend=backend,
            )
            with self.assertRaises(AppError) as raised:
                validator.validate(Path(directory) / "does-not-exist.db")
            self.assertEqual(raised.exception.status, 503)
            backend.connect.assert_not_called()

    def test_validate_migrates_supported_old_backup_before_scrubbing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.db"
            with closing(sqlite3.connect(path)) as connection:
                initialize_schema(connection)
                connection.execute("DROP TABLE nutrition_products")
                connection.execute(
                    "ALTER TABLE external_calendar_events DROP COLUMN no_training"
                )
                connection.execute(
                    "ALTER TABLE nutrition_logs DROP COLUMN logged_time_known"
                )
                connection.execute("PRAGMA user_version = 1")
                connection.execute(
                    "INSERT INTO sessions(token_hash, csrf_hash, expires_at, created_at, last_seen) VALUES ('token', 'csrf', 1, 'now', 'now')"
                )
                connection.commit()
            validator = service(
                Path(directory),
                schema_is_current=database_schema_is_current,
                migrate_schema=migrate_schema,
            )

            validator.validate(path)

            with closing(sqlite3.connect(path)) as connection:
                connection.row_factory = sqlite3.Row
                self.assertTrue(database_schema_is_current(connection))
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0
                )

    def test_validate_migrates_release_1_12_26_gemini_state_before_scrubbing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(
                    RELEASE_1_12_26_SCHEMA.read_text(encoding="utf-8")
                )
                connection.executemany(
                    "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, 'before')",
                    [
                        ("gemini_conversation_id", "gemini-conversation"),
                        ("gemini_conversation_history", "synthetic-history"),
                        ("gemini_call_names", "synthetic-call-names"),
                        ("gemini_usage", "synthetic-usage"),
                        ("gemini_status", "synthetic-status"),
                        ("selected_ai_provider", "gemini"),
                        ("selected_model_gemini", "gemini-test"),
                        ("openai_usage", "synthetic-openai-usage"),
                        ("openai_conversation_id", "openai-conversation"),
                        ("profile", '{"name":"Synthetic athlete"}'),
                    ],
                )
                connection.execute(
                    "INSERT INTO messages(role, content, client_turn_id, created_at) "
                    "VALUES ('user', 'Gemini content', 'gemini-turn', 'before')"
                )
                connection.execute(
                    "INSERT INTO messages(role, content, client_turn_id, created_at) "
                    "VALUES ('user', 'OpenAI content', 'openai-turn', 'before')"
                )
                connection.execute(
                    "INSERT INTO coach_commands(id, client_turn_id, conversation_id, intent, "
                    "target_system, status, receipt, created_at, updated_at) VALUES "
                    "('gemini-command', 'gemini-turn', 'gemini-conversation', '{}', 'local', "
                    "'running', ?, 'before', 'before')",
                    (json.dumps({"ai_provider": "gemini", "message": "private"}),),
                )
                connection.execute(
                    "INSERT INTO coach_commands(id, client_turn_id, conversation_id, intent, "
                    "target_system, status, receipt, created_at, updated_at) VALUES "
                    "('openai-command', 'openai-turn', 'openai-conversation', '{}', 'local', "
                    "'queued', ?, 'before', 'before')",
                    (json.dumps({"ai_provider": "openai"}),),
                )
                connection.execute(
                    "INSERT INTO sessions VALUES ('synthetic-session', 'synthetic-csrf', "
                    "1, 'before', 'before')"
                )
                connection.commit()
            validator = service(
                Path(directory),
                maximum_bytes=path.stat().st_size,
                schema_is_current=database_schema_is_current,
                migrate_schema=migrate_schema,
            )

            staged = validator.stage(path.read_bytes())
            validator.validate(staged)

            with closing(sqlite3.connect(staged)) as connection:
                connection.row_factory = sqlite3.Row
                self.assertTrue(database_schema_is_current(connection))
                values = dict(
                    connection.execute("SELECT key, value FROM kv").fetchall()
                )
                self.assertEqual(values["profile"], '{"name":"Synthetic athlete"}')
                self.assertEqual(values["selected_ai_provider"], "openai")
                self.assertEqual(values["openai_usage"], "synthetic-openai-usage")
                self.assertEqual(
                    values["openai_conversation_id"], "openai-conversation"
                )
                self.assertFalse(any(key.startswith("gemini_") for key in values))
                self.assertNotIn("selected_model_gemini", values)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0
                )
                self.assertEqual(
                    [
                        row[0]
                        for row in connection.execute(
                            "SELECT content FROM messages ORDER BY id"
                        )
                    ],
                    ["OpenAI content"],
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT status FROM coach_commands WHERE client_turn_id='gemini-turn'"
                    ).fetchone()[0],
                    "cancelled",
                )
                self.assertEqual(
                    json.loads(
                        connection.execute(
                            "SELECT receipt FROM coach_commands WHERE client_turn_id='gemini-turn'"
                        ).fetchone()[0]
                    )["phase"],
                    "migration_gemini_removed",
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT conversation_id FROM coach_commands WHERE client_turn_id='openai-turn'"
                    ).fetchone()[0],
                    "openai-conversation",
                )
                initialize_application_database(
                    connection,
                    key_values=KeyValueRepository(lambda: "after"),
                    now="after",
                    current_time=datetime(2026, 10, 7, tzinfo=UTC),
                    default_profile_json="{}",
                    provider_resync_keys=(),
                    retention_days=-1,
                    all_sync_days=-1,
                )
                connection.commit()
                self.assertEqual(
                    dict(connection.execute("SELECT key, value FROM kv")), values
                )
            with closing(sqlite3.connect(path)) as source:
                self.assertEqual(source.execute("PRAGMA user_version").fetchone()[0], 3)
                self.assertEqual(
                    source.execute(
                        "SELECT value FROM kv WHERE key='selected_ai_provider'"
                    ).fetchone()[0],
                    "gemini",
                )

    def test_failed_release_1_12_26_restore_rolls_back_all_gemini_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.db"
            with closing(sqlite3.connect(path)) as db:
                db.executescript(RELEASE_1_12_26_SCHEMA.read_text(encoding="utf-8"))
                db.executemany(
                    "INSERT INTO kv VALUES (?, ?, 'before')",
                    [("selected_ai_provider", "gemini"), ("gemini_usage", "{}")],
                )
                db.execute(
                    "INSERT INTO messages(role, content, client_turn_id, created_at) "
                    "VALUES ('user', 'Synthetic message', 'turn', 'before')"
                )
                db.execute(
                    "INSERT INTO coach_commands(id, client_turn_id, intent, target_system, "
                    "status, receipt, created_at, updated_at) VALUES "
                    "('command', 'turn', '{}', 'local', 'running', "
                    "'{\"ai_provider\":\"gemini\"}', 'before', 'before')"
                )
                db.execute(
                    "INSERT INTO sync_job_items(id, job_id, item_key, operation, "
                    "payload_hash, status, created_at, updated_at) VALUES "
                    "('item', 'missing', 'key', 'pull', 'hash', 'pending', 'before', 'before')"
                )
                db.commit()
                before = list(db.iterdump())
            with self.assertRaises(AppError):
                service(
                    Path(directory),
                    schema_is_current=database_schema_is_current,
                    migrate_schema=migrate_schema,
                ).validate(path)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(list(db.iterdump()), before)
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)

    def test_failed_old_backup_validation_rolls_back_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.db"
            with closing(sqlite3.connect(path)) as connection:
                initialize_schema(connection)
                connection.execute("DROP TABLE nutrition_products")
                connection.execute(
                    "ALTER TABLE external_calendar_events DROP COLUMN no_training"
                )
                connection.execute(
                    "ALTER TABLE nutrition_logs DROP COLUMN logged_time_known"
                )
                connection.execute("PRAGMA user_version = 1")
                connection.execute(
                    "INSERT INTO sync_job_items(id, job_id, item_key, operation, payload_hash, status, created_at, updated_at) VALUES ('item', 'missing-job', 'key', 'pull', 'hash', 'pending', 'now', 'now')"
                )
                connection.commit()
            validator = service(
                Path(directory),
                schema_is_current=database_schema_is_current,
                migrate_schema=migrate_schema,
            )

            with self.assertRaises(AppError):
                validator.validate(path)

            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(
                    connection.execute("PRAGMA user_version").fetchone()[0], 1
                )
                self.assertIsNone(
                    connection.execute(
                        "SELECT name FROM sqlite_master WHERE name='nutrition_products'"
                    ).fetchone()
                )


if __name__ == "__main__":
    unittest.main()
