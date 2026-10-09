from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from backend.backup.assembly import (
    BackupAssembly,
    BackupStorageDependencies,
    RestoreLifecycleDependencies,
    RestoreValidationDependencies,
)
from backend.privacy import (
    PrivacyArchiveSettings,
    PrivacyAssembly,
    PrivacyAthleteSources,
    PrivacyClock,
    PrivacyContextSources,
    PrivacyPlanningSources,
    PrivacyStateDependencies,
)


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
                    checkin_service=Mock(return_value=Mock()),
                    activity_feedback_service=Mock(return_value=Mock()),
                ),
                planning=PrivacyPlanningSources(
                    workout_library_service=Mock(return_value=Mock()),
                    competition_service=Mock(return_value=competition),
                    training_plan_service=Mock(return_value=Mock()),
                ),
                context=PrivacyContextSources(
                    adaptive_preview_service=Mock(return_value=preview),
                    external_calendar_reader=Mock(return_value=Mock()),
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
        exported = assembly.data_export_service()

        self.assertIsNot(first, second)
        self.assertIs(first._database_manager, manager)
        self.assertFalse(hasattr(first, "_db_lock"))
        self.assertIs(first._profile, profile)
        self.assertIs(first._competitions, competition)
        self.assertIs(first._adaptive_preview, preview)
        self.assertIs(exported._dependencies.database_manager, manager)
        self.assertIs(exported._dependencies.database_lock, replacement_lock)
        deletion = assembly.delete_service()
        self.assertIs(deletion._dependencies.database_lock, replacement_lock)
        self.assertIs(deletion._dependencies.maintenance_gate, replacement_gate)
        self.assertIs(exported._dependencies.key_value_repository, key_values)


class BackupAssemblyTests(unittest.TestCase):
    def test_restore_reuses_shared_workers_queue_and_database_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            database_path = data_dir / "database.sqlite"
            manager = Mock(name="manager")
            lock = Mock(name="database_lock")
            queue = Mock(name="sync_queue")
            coach_store = Mock(name="coach_store")
            failures = Mock(name="coach_failures")
            sync_wake = Mock(name="sync_wake")
            coach_wake = Mock(name="coach_wake")
            active_lock = {"value": lock}
            assembly = BackupAssembly(
                dependencies=BackupAssembly.Inputs(
                    storage=BackupStorageDependencies(
                        database_manager=lambda: manager,
                        database_path=lambda: database_path,
                        data_dir=lambda: data_dir,
                        database_lock=lambda: active_lock["value"],
                        maximum_bytes=1000,
                        minimum_free_bytes=10,
                        time_limit_seconds=5,
                        logger=Mock(),
                    ),
                    validation=RestoreValidationDependencies(
                        app_password=lambda: "synthetic-password",
                        sqlcipher_available=lambda: False,
                        sqlite_backend=Mock(),
                        configure_cipher=Mock(),
                        row_factory=Mock(),
                        schema_is_current=Mock(),
                    ),
                    lifecycle=RestoreLifecycleDependencies(
                        maintenance_gate=lambda: Mock(name="maintenance_gate"),
                        sync_jobs=lambda: queue,
                        coach_jobs=lambda: coach_store,
                        coach_failures=lambda: failures,
                        sync_wake_event=lambda: sync_wake,
                        coach_wake_event=coach_wake,
                        redact=Mock(),
                    ),
                )
            )

            backup = assembly.backup_service()
            replacement_lock = Mock(name="replacement_lock")
            active_lock["value"] = replacement_lock
            restore = assembly.restore_service()

            self.assertIs(backup._manager, manager)
            self.assertIs(backup._database_lock, lock)
            self.assertIs(restore._dependencies.database_lock, replacement_lock)
            self.assertIs(restore._dependencies.sync_jobs, queue)
            self.assertIs(restore._dependencies.coach_jobs, coach_store)
            self.assertIs(restore._dependencies.coach_failures, failures)
            self.assertIs(restore._dependencies.sync_wake, sync_wake)
            self.assertIs(restore._dependencies.coach_wake, coach_wake)
            self.assertEqual(restore._dependencies.config.database_path, database_path)


if __name__ == "__main__":
    unittest.main()
