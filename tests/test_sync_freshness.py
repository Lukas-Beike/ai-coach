from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from support import make_config

from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.sync.freshness import (
    ProviderFreshnessService,
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def _create_tables(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE provider_refresh_history (
            id TEXT PRIMARY KEY, provider TEXT NOT NULL, area TEXT NOT NULL,
            operation_id TEXT NOT NULL, trigger TEXT NOT NULL, started_at TEXT NOT NULL,
            finished_at TEXT, phase TEXT NOT NULL, status TEXT NOT NULL,
            error_code TEXT, next_retry_at TEXT
        );
        CREATE TABLE sync_jobs (
            id TEXT PRIMARY KEY, provider TEXT NOT NULL, type TEXT NOT NULL,
            status TEXT NOT NULL, payload TEXT, requested_by TEXT, attempts INTEGER,
            progress_total INTEGER, progress_completed INTEGER, error_class TEXT,
            available_at TEXT, started_at TEXT, finished_at TEXT, created_at TEXT,
            updated_at TEXT
        );
        """
    )


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    _create_tables(db)
    db.commit()
    return db


def _values(values: dict[str, str]):
    # The Intervals.icu ingest is on unless a case says otherwise.
    stored = {"intervals_ingest_enabled": "1", **values}
    return lambda key: stored.get(key)


def _item(result, provider: str, area: str) -> dict:
    return next(
        item for item in result if (item["provider"], item["area"]) == (provider, area)
    )


class _TrackingDatabaseManager(DatabaseManager):
    def __init__(self, *args, **kwargs):
        self.connection_count = 0
        self.unit_of_work_count = 0
        super().__init__(*args, **kwargs)

    def _connect(self):
        self.connection_count += 1
        return super()._connect()

    def unit_of_work(self):
        self.unit_of_work_count += 1
        return super().unit_of_work()


class _TrackingKeyValueRepository(KeyValueRepository):
    def __init__(self):
        super().__init__(lambda: "test")
        self.connections = []

    def get(self, db, key):
        self.connections.append(db)
        return super().get(db, key)


class ProviderFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.db = _db()
        self.addCleanup(self.db.close)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.manager = _TrackingDatabaseManager(
            Path(self.temp_dir.name) / "freshness.sqlite",
            sqlite3,
            row_factory=sqlite3.Row,
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            _create_tables(db)
            # These cases cover the Intervals.icu ingest switched on.
            db.execute(
                "INSERT INTO kv VALUES ('intervals_ingest_enabled', '1', 'test')"
            )
        self.manager.connection_count = 0
        self.manager.unit_of_work_count = 0
        self.key_values = _TrackingKeyValueRepository()

    def _service(self, config: Config | None = None, now=NOW):
        return ProviderFreshnessService(
            config or make_config(), self.manager, self.key_values, lambda: now
        )







    def test_service_commits_cleanup_on_success(self):
        old = NOW - timedelta(days=31)
        rows = [
            (
                "old",
                old.isoformat(),
                old.isoformat(),
            )
        ]
        rows.extend(
            (
                f"recent-{index}",
                (NOW - timedelta(minutes=index)).isoformat(),
                (NOW - timedelta(minutes=index)).isoformat(),
            )
            for index in range(201)
        )
        with self.manager.unit_of_work() as db:
            db.executemany(
                "INSERT INTO provider_refresh_history VALUES (?, 'intervals', 'activities', "
                "'op', 'test', ?, ?, 'complete', 'success', NULL, NULL)",
                rows,
            )

        self._service(make_config(intervals_api_key="configured")).current(
            profile={}, garmin_has_core_error=False, garmin_tokenstore_exists=False
        )
        with self.manager.unit_of_work() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM provider_refresh_history").fetchone()[
                    0
                ],
                200,
            )

    def test_service_rolls_back_cleanup_when_projection_fails(self):
        old = NOW - timedelta(days=31)
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO provider_refresh_history VALUES "
                "('old', 'intervals', 'activities', 'op', 'test', ?, ?, "
                "'complete', 'success', NULL, NULL)",
                (old.isoformat(), old.isoformat()),
            )

        with (
            patch(
                "backend.sync.freshness._scheduled_provider_retry_at",
                side_effect=RuntimeError("forced projection failure"),
            ),
            self.assertRaisesRegex(RuntimeError, "forced projection failure"),
        ):
            self._service().current(
                profile={},
                garmin_has_core_error=False,
                garmin_tokenstore_exists=False,
            )

        with self.manager.unit_of_work() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM provider_refresh_history").fetchone()[
                    0
                ],
                1,
            )

    def test_import_smoke_from_empty_cwd_without_bytecode(self):
        package_root = Path(__import__("backend").__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temp_dir:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(package_root)
            completed = subprocess.run(
                [sys.executable, "-B", "-c", "import backend.sync.freshness"],
                cwd=temp_dir,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(list(Path(temp_dir).rglob("*.pyc")), [])


if __name__ == "__main__":
    unittest.main()
