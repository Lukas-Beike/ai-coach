from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock

from backend.backup.database import (
    EXPORT_TIME_LIMIT_SECONDS,
    MAX_BACKUP_BYTES,
    MIN_EXPORT_FREE_BYTES,
)
from backend.backup.wiring import build_backup
from backend.coach.job_worker import COACH_JOB_WORKER
from backend.privacy import (
    PrivacyArchiveSettings,
    PrivacyAssembly,
    PrivacyAthleteSources,
    PrivacyClock,
    PrivacyContextSources,
    PrivacyPlanningSources,
    PrivacyStateDependencies,
)
from backend.sync.worker import shared_sync_job_wake_event


class PrivacyAssemblyTests(unittest.TestCase):
    def test_constructor_is_inert_and_services_share_manager_and_lock(self) -> None:
        manager = Mock(name="manager")
        lock = Mock(name="database_lock")
        gate = Mock(name="maintenance_gate")
        active = {"lock": lock, "gate": gate}
        key_values = Mock(name="key_values")
        manager_provider = Mock(return_value=manager)
        profile = Mock(name="profile_service")
        competition = Mock(name="competition_service")
        preview = Mock(name="preview_service")
        assembly = PrivacyAssembly(
            dependencies=PrivacyAssembly.Inputs(
                athlete=PrivacyAthleteSources(
                    profile_service=Mock(return_value=profile),
                ),
                planning=PrivacyPlanningSources(
                    competition_service=Mock(return_value=competition),
                ),
                context=PrivacyContextSources(
                    adaptive_preview_service=Mock(return_value=preview),
                ),
                clock=PrivacyClock(local_now=Mock(), utc_now=Mock()),
                state=PrivacyStateDependencies(
                    database_manager=manager_provider,
                    database_lock=lambda: active["lock"],
                    key_value_repository=key_values,
                    maintenance_gate=lambda: active["gate"],
                    planning_revision_service=Mock(),
                    openai_client=Mock(return_value=Mock()),
                    logger=Mock(),
                    diagnostics_suspended=MagicMock(),
                ),
                archive=PrivacyArchiveSettings(
                    data_dir=Mock(return_value=Path("temporary-data")),
                    database_path=Mock(return_value=Path("temporary-data/db.sqlite")),
                    maximum_export_bytes=100,
                    minimum_free_bytes=10,
                    time_limit_seconds=5,
                ),
            )
        )

        manager_provider.assert_not_called()
        replacement_lock = Mock(name="replacement_lock")
        replacement_gate = Mock(name="replacement_gate")
        active.update(lock=replacement_lock, gate=replacement_gate)
        first = assembly.archive_export_service()
        second = assembly.archive_export_service()

        self.assertIsNot(first, second)
        self.assertIs(first._database_manager, manager)
        self.assertFalse(hasattr(first, "_db_lock"))
        self.assertIs(first._profile, profile)
        self.assertIs(first._competitions, competition)
        self.assertIs(first._adaptive_preview, preview)
        deletion = assembly.delete_service()
        self.assertIs(deletion._dependencies.database_lock, replacement_lock)
        self.assertIs(deletion._dependencies.maintenance_gate, replacement_gate)


class PrivacyModuleBoundaryTests(unittest.TestCase):
    def test_privacy_module_has_no_server_dependency(self) -> None:
        import backend.privacy as privacy_module

        source = Path(privacy_module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import server", source)


class BackupBuilderTests(unittest.TestCase):
    def test_restore_reuses_shared_workers_queue_and_database_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            database_path = data_dir / "database.sqlite"
            manager = Mock(name="manager")
            lock = Mock(name="database_lock")
            ctx = Mock(name="context")
            ctx.database = lambda: manager
            ctx.database_lock = lock
            ctx.database_path = lambda: database_path
            ctx.data_dir = lambda: data_dir
            ctx.config.return_value.app_password = "synthetic-password"
            ctx.sqlcipher_available = lambda: False
            ctx.profile_mutation_coordinator = threading.RLock()
            backup_services = build_backup(ctx)

            backup = backup_services.backup_service()
            replacement_lock = Mock(name="replacement_lock")
            ctx.database_lock = replacement_lock
            restore = backup_services.restore_service()

            self.assertIs(backup._manager, manager)
            self.assertIs(backup._database_lock, lock)
            self.assertEqual(backup._config.maximum_bytes, MAX_BACKUP_BYTES)
            self.assertEqual(backup._config.minimum_free_bytes, MIN_EXPORT_FREE_BYTES)
            self.assertEqual(
                backup._config.time_limit_seconds, EXPORT_TIME_LIMIT_SECONDS
            )
            dependencies = restore._dependencies
            self.assertIs(dependencies.database_lock, replacement_lock)
            self.assertIs(dependencies.maintenance_gate, ctx.maintenance)
            self.assertIs(
                dependencies.profile_mutation_coordinator,
                ctx.profile_mutation_coordinator,
            )
            self.assertIs(dependencies.sync_jobs, ctx.sync_job_queue.service())
            self.assertIs(
                dependencies.coach_jobs, ctx.coach_background_jobs.job_store()
            )
            self.assertIs(
                dependencies.coach_failures,
                ctx.coach_background_jobs.turn_failure_service(),
            )
            self.assertIs(dependencies.sync_wake, shared_sync_job_wake_event())
            self.assertIs(dependencies.coach_wake, COACH_JOB_WORKER.wake_event)
            self.assertEqual(dependencies.config.database_path, database_path)
            self.assertEqual(dependencies.config.data_dir, data_dir)
            self.assertIs(
                dependencies.validation._config.sqlite_backend, ctx.sqlite_backend
            )
            self.assertEqual(
                dependencies.validation._config.app_password, "synthetic-password"
            )

    def test_restore_reaches_late_owners_only_when_it_runs(self) -> None:
        ctx = Mock(name="context")
        ctx.data_dir = lambda: Path("data")
        ctx.database_path = lambda: Path("data") / "database.sqlite"
        dependencies = build_backup(ctx).restore_service()._dependencies

        ctx.diagnostic_capture.suspended.assert_not_called()
        ctx.canonical_backfill.worker.start.assert_not_called()
        ctx.coach_conversation.reset_service.assert_not_called()
        dependencies.diagnostics_suspended()
        dependencies.canonical_backfill_start()
        cancel = dependencies.cancel_coach_turns
        assert cancel is not None
        cancel()
        ctx.diagnostic_capture.suspended.assert_called_once_with()
        ctx.canonical_backfill.worker.start.assert_called_once_with()
        cancel_turns = ctx.coach_conversation.reset_service().cancel_running_turns
        cancel_turns.assert_called_once_with()
        self.assertIs(dependencies.refresh_credentials, ctx.refresh_config)
        self.assertIs(dependencies.redact, ctx.redactor.redact_text)


if __name__ == "__main__":
    unittest.main()
