"""Stage and validate a database backup before the restore owner replaces it."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.db.migrations import migrate_schema
from backend.errors import AppError


@dataclass(frozen=True)
class DatabaseRestoreValidationConfig:
    data_dir: Path
    maximum_bytes: int
    app_password: str
    sqlcipher_available: bool
    sqlite_backend: Any
    configure_cipher: Callable[[Any, str], None]
    row_factory: Any
    schema_is_current: Callable[[Any], bool]
    migrate_schema: Callable[[Any], None] = migrate_schema


class DatabaseRestoreValidationService:
    """Own temporary restore payload staging and its complete DB validation."""

    def __init__(self, config: DatabaseRestoreValidationConfig) -> None:
        self._config = config

    def stage(self, payload: bytes | Iterable[bytes]) -> Path:
        """Write a whole payload, or its chunks in order, to a new staging file.

        Chunks are written as they arrive and the size limit is enforced while
        writing. Any failure removes the staging file.
        """
        chunks = (payload,) if isinstance(payload, bytes) else payload
        self._config.data_dir.mkdir(parents=True, exist_ok=True)
        path = self._config.data_dir / f".intervals-coach-restore-{uuid.uuid4().hex}.db"
        created = False
        size = 0
        try:
            with path.open("xb") as temporary:
                created = True
                for chunk in chunks:
                    size += len(chunk)
                    if size > self._config.maximum_bytes:
                        raise AppError(
                            413, "Das Datenbank-Backup ist leer oder zu groß."
                        )
                    temporary.write(chunk)
            if size == 0:
                raise AppError(413, "Das Datenbank-Backup ist leer oder zu groß.")
        except BaseException:
            if created:
                path.unlink(missing_ok=True)
            raise
        return path

    def validate(self, temporary_path: Path) -> None:
        if self._config.app_password and not self._config.sqlcipher_available:
            raise AppError(
                503, "SQLCipher ist für die Wiederherstellung nicht verfügbar."
            )
        backend = (
            self._config.sqlite_backend if self._config.sqlcipher_available else sqlite3
        )
        connection = backend.connect(temporary_path, timeout=20)
        connection.row_factory = self._config.row_factory
        try:
            if self._config.app_password:
                self._config.configure_cipher(connection, self._config.app_password)
            connection.execute("PRAGMA foreign_keys = ON")
            try:
                self._config.migrate_schema(connection)
            except RuntimeError as error:
                raise AppError(
                    400, "Das Backup entspricht keinem unterstützten Datenbankschema."
                ) from error
            if not self._config.schema_is_current(connection):
                raise AppError(
                    400,
                    "Das Backup entspricht nicht exakt dem aktuellen Datenbankschema.",
                )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise AppError(400, "Das Backup enthält ungültige Fremdschlüssel.")
            if not integrity or str(integrity["integrity_check"]).casefold() != "ok":
                raise AppError(
                    400, "Die Integritätsprüfung des Backups ist fehlgeschlagen."
                )
            # Sessions from the backup must never survive a restore.
            connection.execute("DELETE FROM sessions")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
