"""Deleted athlete data leaves the database file and the WAL, and the WAL stays small.

Plain SQLite on temporary files stands in for SQLCipher: ``secure_delete``,
``VACUUM``, ``journal_size_limit`` and ``wal_checkpoint`` are SQLite pragmas and
statements that SQLCipher accepts unchanged.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

from backend.activities.route_store import INDEX_KEY
from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.db.manager import (
    JOURNAL_SIZE_LIMIT_BYTES,
    DatabaseManager,
    background_writer,
    secure_deletion,
)
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.privacy import (
    GPS_TRACKS_DELETE_CONFIRMATION_TEXT,
    PRIVACY_DELETE_CONFIRMATION_TEXT,
    PrivacyDeleteDependencies,
    PrivacyDeleteService,
)
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.scheduler import DailySyncLoop
from backend.sync.scheduler_assembly import (
    DailySyncLoopSettings,
    SyncScheduleControls,
    SyncScheduleOwners,
    SyncSchedulePersistence,
    SyncSchedulePolicy,
    SyncSchedulerAssembly,
)

STAMP = "2026-10-01T08:00:00+00:00"
SENTINEL = "synthetic-sentinel-4f9c2a71"
ROUTE_SENTINEL = "synthetic-route-name-88d1e0b3"


class _FailingVacuumConnection(sqlite3.Connection):
    def execute(self, sql: str, *args: Any) -> sqlite3.Cursor:
        if sql == "VACUUM":
            raise sqlite3.OperationalError("database or disk is full")
        return super().execute(sql, *args)


def _failing_vacuum_backend() -> Any:
    return SimpleNamespace(
        connect=lambda path, **kwargs: sqlite3.connect(
            path, factory=_FailingVacuumConnection, **kwargs
        )
    )


def _make_manager(root: str, backend: Any = sqlite3) -> DatabaseManager:
    manager = DatabaseManager(
        Path(root) / "athlete.db", backend, row_factory=sqlite3.Row
    )
    with manager.unit_of_work() as db:
        initialize_schema(db)
    return manager


def _open(
    case: unittest.TestCase, backend: Any = sqlite3
) -> tuple[str, DatabaseManager]:
    """A seeded temporary manager; connections close before the directory goes."""
    root = case.enterContext(tempfile.TemporaryDirectory())
    manager = _make_manager(root, backend)
    case.addCleanup(manager.close)
    return root, manager


def _storage_bytes(root: str) -> bytes:
    """The main database file and its write-ahead log."""
    return b"".join(
        path.read_bytes()
        for path in (Path(root) / "athlete.db", Path(root) / "athlete.db-wal")
        if path.exists()
    )


def _seed_sentinel(manager: DatabaseManager, route: str = SENTINEL) -> None:
    with manager.unit_of_work() as db:
        for index in range(40):
            db.execute(
                "INSERT INTO messages(role, content, created_at) VALUES ('user', ?, ?)",
                (f"{SENTINEL} {index} " + "x" * 400, STAMP),
            )
        db.execute(
            "INSERT INTO snapshots(payload, created_at) VALUES (?, ?)",
            (json.dumps({"note": SENTINEL}), STAMP),
        )
        db.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
            (INDEX_KEY, json.dumps({"route": route}), STAMP),
        )


def _delete_service(
    manager: DatabaseManager, logger: Any | None = None
) -> PrivacyDeleteService:
    planning = Mock()
    openai = Mock()
    return PrivacyDeleteService(
        PrivacyDeleteDependencies(
            database_manager=manager,
            database_lock=threading.RLock(),
            key_value_repository=KeyValueRepository(lambda: STAMP),
            maintenance_gate=MaintenanceGate(),
            profile_mutation_coordinator=threading.RLock(),
            planning_revision_service=planning,
            openai_client=openai,
            logger=logger or Mock(),
            diagnostics_suspended=nullcontext,
        )
    )


class JournalSizeLimitTests(unittest.TestCase):
    def test_every_connection_limits_the_wal_size(self) -> None:
        _root, manager = _open(self)
        with manager.unit_of_work() as writer:
            self.assertEqual(
                writer.execute("PRAGMA journal_size_limit").fetchone()[0],
                67108864,
            )
        with manager.reader() as reader:
            self.assertEqual(
                reader.execute("PRAGMA journal_size_limit").fetchone()[0],
                JOURNAL_SIZE_LIMIT_BYTES,
            )

    def test_checkpoint_truncates_the_wal(self) -> None:
        root, manager = _open(self)
        _seed_sentinel(manager)
        wal = Path(root) / "athlete.db-wal"
        self.assertGreater(wal.stat().st_size, 0)

        self.assertTrue(manager.checkpoint_wal())

        self.assertEqual(wal.stat().st_size, 0)
        with manager.reader() as db:
            count = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        self.assertEqual(count, 40)


class SecureDeleteTests(unittest.TestCase):
    def test_secure_delete_is_scoped_to_the_unit_of_work(self) -> None:
        _root, manager = _open(self)
        with manager.unit_of_work() as db:
            before = db.execute("PRAGMA secure_delete").fetchone()[0]
        with manager.unit_of_work() as db, secure_deletion(db):
            self.assertEqual(db.execute("PRAGMA secure_delete").fetchone()[0], 1)
        with manager.unit_of_work() as db:
            self.assertEqual(db.execute("PRAGMA secure_delete").fetchone()[0], before)

    def test_secure_delete_is_restored_after_a_failed_unit_of_work(self) -> None:
        _root, manager = _open(self)
        with manager.unit_of_work() as db:
            before = db.execute("PRAGMA secure_delete").fetchone()[0]
        with (
            self.assertRaises(RuntimeError),
            manager.unit_of_work() as db,
            secure_deletion(db),
        ):
            raise RuntimeError("synthetic")
        with manager.unit_of_work() as db:
            self.assertEqual(db.execute("PRAGMA secure_delete").fetchone()[0], before)

    def test_a_plain_delete_leaves_the_content_in_the_file(self) -> None:
        # Control: without secure_delete and VACUUM the sentinel stays behind,
        # which is what the purge tests below must get rid of.
        root, manager = _open(self)
        with manager.unit_of_work() as db:
            if db.execute("PRAGMA secure_delete").fetchone()[0]:
                self.skipTest("this SQLite build zeroes deleted content already")
        _seed_sentinel(manager)
        with manager.unit_of_work() as db:
            db.execute("DELETE FROM messages")
            db.execute("DELETE FROM snapshots")
        manager.checkpoint_wal()

        self.assertIn(SENTINEL.encode(), _storage_bytes(root))

    def test_reclaim_inside_a_transaction_is_refused(self) -> None:
        _root, manager = _open(self)
        with manager.unit_of_work() as db:
            db.execute("DELETE FROM messages")
            with self.assertRaises(RuntimeError):
                manager.reclaim_space()


class PurgeLeavesNoTraceTests(unittest.TestCase):
    def test_purge_removes_the_content_from_the_file_and_the_wal(self) -> None:
        root, manager = _open(self)
        _seed_sentinel(manager)
        self.assertIn(SENTINEL.encode(), _storage_bytes(root))

        result = _delete_service(manager).delete(PRIVACY_DELETE_CONFIRMATION_TEXT)

        self.assertTrue(result["local_data_deleted"])
        self.assertNotIn(SENTINEL.encode(), _storage_bytes(root))
        with manager.reader() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0
            )
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_gps_track_delete_removes_the_routes_from_the_file_and_the_wal(
        self,
    ) -> None:
        root, manager = _open(self)
        _seed_sentinel(manager, ROUTE_SENTINEL)
        self.assertIn(ROUTE_SENTINEL.encode(), _storage_bytes(root))

        result = _delete_service(manager).delete_gps_tracks(
            GPS_TRACKS_DELETE_CONFIRMATION_TEXT
        )

        self.assertEqual(result["status"], "ok")
        self.assertNotIn(ROUTE_SENTINEL.encode(), _storage_bytes(root))
        with manager.reader() as db:
            # Only the routes and tracks go; other data stays.
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 40
            )

    def test_a_failing_vacuum_leaves_the_data_intact_and_the_purge_succeeds(
        self,
    ) -> None:
        _root, manager = _open(self, _failing_vacuum_backend())
        _seed_sentinel(manager)
        logger = Mock()

        result = _delete_service(manager, logger).delete(
            PRIVACY_DELETE_CONFIRMATION_TEXT
        )

        self.assertTrue(result["local_data_deleted"])
        warning = logger.warning.call_args.kwargs["extra"]
        self.assertEqual(warning["event"], "privacy_space_reclaim_failed")
        self.assertEqual(warning["context"], {"error_class": "OperationalError"})
        with manager.reader() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0
            )
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        # The writer is free again for the next request.
        with manager.unit_of_work(timeout=1) as db:
            db.execute(
                "INSERT INTO messages(role, content, created_at) VALUES ('user', 'next', ?)",
                (STAMP,),
            )

    def test_an_incomplete_checkpoint_is_logged_without_failing_the_purge(
        self,
    ) -> None:
        _root, manager = _open(self)
        logger = Mock()
        with patch.object(manager, "reclaim_space", return_value=False):
            result = _delete_service(manager, logger).delete(
                PRIVACY_DELETE_CONFIRMATION_TEXT
            )

        self.assertTrue(result["local_data_deleted"])
        self.assertEqual(
            logger.warning.call_args.kwargs["extra"]["event"],
            "privacy_space_reclaim_incomplete",
        )

    def test_a_wrong_confirmation_reclaims_nothing(self) -> None:
        _root, manager = _open(self)
        with (
            patch.object(manager, "reclaim_space") as reclaim,
            self.assertRaises(AppError),
        ):
            _delete_service(manager).delete("falsch")
        reclaim.assert_not_called()


class SameBuildRestartAfterReclaimTests(unittest.TestCase):
    def test_the_database_reopens_with_its_data_after_a_purge(self) -> None:
        root, manager = _open(self)
        _seed_sentinel(manager)
        _delete_service(manager).delete(PRIVACY_DELETE_CONFIRMATION_TEXT)
        manager.close()

        restarted = DatabaseManager(
            Path(root) / "athlete.db", sqlite3, row_factory=sqlite3.Row
        )
        self.addCleanup(restarted.close)
        with restarted.unit_of_work() as db:
            db.execute(
                "INSERT INTO messages(role, content, created_at) VALUES ('user', 'after restart', ?)",
                (STAMP,),
            )
        with restarted.reader() as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(
                db.execute("SELECT content FROM messages").fetchone()[0],
                "after restart",
            )


class BackupAndRestoreAfterReclaimTests(unittest.TestCase):
    def test_a_backup_after_a_purge_restores_into_a_working_database(self) -> None:
        root, manager = _open(self)
        _seed_sentinel(manager)
        _delete_service(manager).delete(PRIVACY_DELETE_CONFIRMATION_TEXT)
        with manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO messages(role, content, created_at) VALUES ('user', 'kept', ?)",
                (STAMP,),
            )
        config = DatabaseBackupConfig(
            database_path=Path(root) / "athlete.db",
            data_dir=Path(root),
            maximum_bytes=100_000_000,
            minimum_free_bytes=10,
            time_limit_seconds=5,
            monotonic=lambda: 10.0,
            disk_usage=lambda _path: SimpleNamespace(free=10**12),
        )
        service = DatabaseBackupService(manager, threading.RLock(), config, Mock())

        with service.stream_file() as snapshot:
            self.assertNotIn(SENTINEL.encode(), snapshot.read_bytes())
            copy = Path(root) / "restore-candidate.db"
            shutil.copyfile(snapshot, copy)

        with manager.restore_drain():
            for suffix in ("-wal", "-shm"):
                Path(f"{config.database_path}{suffix}").unlink(missing_ok=True)
            copy.replace(config.database_path)
        with manager.reader() as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(
                db.execute("SELECT content FROM messages").fetchone()[0], "kept"
            )


class IdleCheckpointLoopTests(unittest.TestCase):
    class _Stop:
        def __init__(self, waits: int) -> None:
            self.waits = waits
            self.count = 0

        def wait(self, _timeout: float) -> bool:
            self.count += 1
            return self.count >= self.waits

    def _run(self, checkpoint: Any, logger: Any, waits: int = 2) -> Mock:
        scheduler = Mock()
        DailySyncLoop(
            scheduler,
            Mock(),
            sleep=lambda _seconds: None,
            logger=logger,
            stop_event=cast(Any, self._Stop(waits)),
            wal_checkpoint=checkpoint,
        ).run()
        return scheduler

    def test_the_loop_runs_the_checkpoint_each_cycle(self) -> None:
        checkpoint = Mock()
        scheduler = self._run(checkpoint, Mock(), waits=3)

        self.assertEqual(checkpoint.call_count, 2)
        self.assertEqual(scheduler.schedule.call_count, 2)

    def test_a_failing_checkpoint_is_logged_and_never_stops_the_loop(self) -> None:
        logger = Mock()
        scheduler = self._run(
            Mock(side_effect=sqlite3.OperationalError("private detail")),
            logger,
            waits=3,
        )

        self.assertEqual(scheduler.schedule.call_count, 2)
        extra = logger.error.call_args.kwargs["extra"]
        self.assertEqual(extra["event"], "wal_checkpoint_failed")
        self.assertEqual(extra["context"], {"error_class": "OperationalError"})
        self.assertNotIn("private detail", repr(logger.error.call_args))

    def test_maintenance_is_not_a_checkpoint_failure(self) -> None:
        logger = Mock()
        scheduler = self._run(
            Mock(side_effect=AppError(503, "Wartung", reason="maintenance")), logger
        )

        scheduler.schedule.assert_called_once_with()
        logger.error.assert_not_called()

    def test_the_checkpoint_truncates_a_real_wal_behind_the_background_writer(
        self,
    ) -> None:
        root, manager = _open(self)
        _seed_sentinel(manager)
        wal = Path(root) / "athlete.db-wal"
        self.assertGreater(wal.stat().st_size, 0)

        def checkpoint() -> None:
            with background_writer():
                manager.checkpoint_wal()

        self._run(checkpoint, Mock())

        self.assertEqual(wal.stat().st_size, 0)


class DailyLoopAssemblyTests(unittest.TestCase):
    def _loop(self, manager: DatabaseManager | None) -> DailySyncLoop:
        assembly = SyncSchedulerAssembly(
            dependencies=SyncSchedulerAssembly.Inputs(
                owners=SyncScheduleOwners(Mock(), Mock(), Mock(), Mock()),
                persistence=SyncSchedulePersistence(Mock()),
                controls=SyncScheduleControls(MaintenanceGate(), lambda _s: None),
                policy=SyncSchedulePolicy(Mock(), 1, "label", 1, Mock()),
                daily_loop=DailySyncLoopSettings(
                    Mock(),
                    Mock(),
                    database_manager=None if manager is None else lambda: manager,
                ),
            )
        )
        with patch.object(assembly, "daily_scheduler"):
            return assembly.daily_loop()

    def test_the_composed_loop_truncates_the_wal(self) -> None:
        root, manager = _open(self)
        _seed_sentinel(manager)
        wal = Path(root) / "athlete.db-wal"
        self.assertGreater(wal.stat().st_size, 0)

        checkpoint = self._loop(manager)._wal_checkpoint
        assert checkpoint is not None
        checkpoint()

        self.assertEqual(wal.stat().st_size, 0)

    def test_without_a_database_manager_the_loop_has_no_checkpoint(self) -> None:
        self.assertIsNone(self._loop(None)._wal_checkpoint)


if __name__ == "__main__":
    unittest.main()
