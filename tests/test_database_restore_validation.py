from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

from backend.backup.restore_validation import (
    DatabaseRestoreValidationConfig,
    DatabaseRestoreValidationService,
)
from backend.errors import AppError


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
            self.assertRegex(staged.name, r"^\.intervals-coach-restore-[0-9a-f]{32}\.db$")
            self.assertEqual(staged.read_bytes(), b"safe")

    def test_validate_commits_session_scrubbing_after_schema_integrity_and_fk_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE sessions (token TEXT)")
                connection.execute("INSERT INTO sessions VALUES ('synthetic-session')")
                connection.commit()
            service(Path(directory)).validate(path)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)

    def test_validate_rejects_unexpected_schema_without_scrubbing_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE sessions (token TEXT)")
                connection.execute("INSERT INTO sessions VALUES ('synthetic-session')")
                connection.commit()
            with self.assertRaises(AppError) as raised:
                service(Path(directory), schema_is_current=lambda _connection: False).validate(path)
            self.assertEqual(raised.exception.status, 400)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1)

    def test_validate_rejects_foreign_key_violations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("PRAGMA foreign_keys = OFF")
                connection.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
                connection.execute("CREATE TABLE children (parent_id INTEGER REFERENCES parents(id))")
                connection.execute("INSERT INTO children VALUES (404)")
                connection.commit()
            with self.assertRaises(AppError) as raised:
                service(Path(directory)).validate(path)
            self.assertEqual(raised.exception.status, 400)

    def test_validate_rejects_failed_integrity_check_before_scrubbing(self) -> None:
        connection = Mock()
        connection.execute.side_effect = lambda statement: {
            "PRAGMA integrity_check": Mock(fetchone=Mock(return_value={"integrity_check": "corrupt"})),
            "PRAGMA foreign_key_check": Mock(fetchall=Mock(return_value=[])),
        }.get(statement, Mock())
        backend = Mock(connect=Mock(return_value=connection))
        validator = service(Path("unused"), sqlite_backend=backend, sqlcipher_available=True)
        with self.assertRaises(AppError) as raised:
            validator.validate(Path("backup.db"))
        self.assertEqual(raised.exception.status, 400)
        self.assertFalse(any(call.args == ("DELETE FROM sessions",) for call in connection.execute.call_args_list))
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


if __name__ == "__main__":
    unittest.main()
