from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, patch

from backend.athlete.profile import DEFAULT_PROFILE
from backend.backup import wiring as backup_wiring
from backend.backup.database import (
    EXPORT_TIME_LIMIT_SECONDS,
    MAX_BACKUP_BYTES,
    MIN_EXPORT_FREE_BYTES,
)
from backend.backup.wiring import build_backup
from backend.coach.job_worker import COACH_JOB_WORKER
from backend.db import row_factory
from backend.db.schema import configure_cipher, database_schema_is_current
from backend.privacy import MAX_PRIVACY_EXPORT_BYTES, PrivacyServices, build_privacy
from backend.runtime import maintenance as runtime_maintenance
from backend.sync.full_resync import PROVIDER_RESYNC_KEYS
from backend.sync.worker import shared_sync_job_wake_event


class PrivacyBuilderTests(unittest.TestCase):
    def _build(self, active: dict[str, Mock]) -> tuple[dict[str, Any], PrivacyServices]:
        arguments: dict[str, Any] = {
            "database_manager": Mock(return_value=active["manager"]),
            "database_lock": lambda: active["lock"],
            "key_values": Mock(name="key_values"),
            "maintenance_gate": lambda: active["gate"],
            "profile_service": Mock(return_value=active["profile"]),
            "competition_service": Mock(return_value=active["competition"]),
            "adaptive_preview_service": Mock(return_value=active["preview"]),
            "planning_revision_service": Mock(name="planning_revision"),
            "openai_client": Mock(return_value=Mock(name="openai")),
            "logger": Mock(name="logger"),
            "local_now": Mock(name="local_now"),
            "utc_now": Mock(name="utc_now"),
            "data_dir": Mock(return_value=Path("temporary-data")),
            "database_path": Mock(return_value=Path("temporary-data/db.sqlite")),
            "diagnostics_suspended": MagicMock(name="diagnostics_suspended"),
            "refresh_credentials": Mock(name="refresh_credentials"),
            "cancel_garmin_login": Mock(name="cancel_garmin_login"),
            "disconnect_wahoo": Mock(name="disconnect_wahoo"),
            "cancel_coach_turns": Mock(name="cancel_coach_turns"),
            "log_files": Mock(name="log_files"),
        }
        return arguments, build_privacy(**arguments)

    def _active(self) -> dict[str, Mock]:
        return {
            name: Mock(name=name)
            for name in ("manager", "lock", "gate", "profile", "competition", "preview")
        }

    def test_construction_is_inert_and_services_share_manager_and_live_owners(
        self,
    ) -> None:
        active = self._active()
        arguments, services = self._build(active)

        for name in (
            "database_manager",
            "profile_service",
            "competition_service",
            "adaptive_preview_service",
            "openai_client",
            "data_dir",
            "database_path",
            "diagnostics_suspended",
            "refresh_credentials",
            "cancel_garmin_login",
            "disconnect_wahoo",
            "cancel_coach_turns",
            "log_files",
        ):
            arguments[name].assert_not_called()
        replacement_lock = Mock(name="replacement_lock")
        replacement_gate = Mock(name="replacement_gate")
        active.update(lock=replacement_lock, gate=replacement_gate)
        first = services.archive_export_service()
        second = services.archive_export_service()

        self.assertIsNot(first, second)
        self.assertIs(first._database_manager, active["manager"])
        self.assertFalse(hasattr(first, "_db_lock"))
        self.assertIs(first._profile, active["profile"])
        self.assertIs(first._competitions, active["competition"])
        self.assertIs(first._adaptive_preview, active["preview"])
        deletion = services.delete_service()
        self.assertIs(deletion._dependencies.database_lock, replacement_lock)
        self.assertIs(deletion._dependencies.maintenance_gate, replacement_gate)

    def test_export_limits_come_from_the_backup_and_privacy_constants(self) -> None:
        active = self._active()
        arguments, services = self._build(active)

        config = services.archive_export_service()._config
        self.assertEqual(config.maximum_bytes, MAX_PRIVACY_EXPORT_BYTES)
        self.assertEqual(config.minimum_free_bytes, MIN_EXPORT_FREE_BYTES)
        self.assertEqual(config.time_limit_seconds, EXPORT_TIME_LIMIT_SECONDS)
        self.assertEqual(config.data_dir, Path("temporary-data"))
        self.assertIs(config.utc_now, arguments["utc_now"])
        arguments["local_now"].return_value = datetime(2026, 1, 2, 23, 30, tzinfo=UTC)
        export_day = config.today
        self.assertEqual(export_day(), date(2026, 1, 2))

    def test_the_purge_gets_every_dependency_and_reaches_late_owners_only_when_run(
        self,
    ) -> None:
        active = self._active()
        arguments, services = self._build(active)

        dependencies = services.delete_service()._dependencies

        self.assertIs(dependencies.database_manager, active["manager"])
        self.assertIs(dependencies.database_lock, active["lock"])
        self.assertIs(dependencies.key_value_repository, arguments["key_values"])
        self.assertIs(dependencies.maintenance_gate, active["gate"])
        self.assertIs(
            dependencies.profile_mutation_coordinator,
            active["profile"].mutation_coordinator,
        )
        self.assertIs(
            dependencies.planning_revision_service,
            arguments["planning_revision_service"],
        )
        self.assertIs(dependencies.openai_client, arguments["openai_client"]())
        self.assertIs(dependencies.logger, arguments["logger"])
        self.assertIs(
            dependencies.diagnostics_suspended, arguments["diagnostics_suspended"]
        )
        self.assertIs(
            dependencies.refresh_credentials, arguments["refresh_credentials"]
        )
        self.assertIs(
            dependencies.cancel_garmin_login, arguments["cancel_garmin_login"]
        )
        self.assertIs(dependencies.disconnect_wahoo, arguments["disconnect_wahoo"])
        self.assertIs(dependencies.cancel_coach_turns, arguments["cancel_coach_turns"])
        self.assertIs(dependencies.log_files, arguments["log_files"].return_value)
        self.assertIs(dependencies.utc_now, arguments["utc_now"])
        assert dependencies.recovery_copies is not None
        self.assertEqual(dependencies.recovery_copies._data_dir, Path("temporary-data"))
        for name in (
            "diagnostics_suspended",
            "refresh_credentials",
            "cancel_garmin_login",
            "disconnect_wahoo",
            "cancel_coach_turns",
        ):
            arguments[name].assert_not_called()


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
            self.assertIs(
                dependencies.maintenance_gate, runtime_maintenance.MAINTENANCE_GATE
            )
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

    def test_restore_validation_gets_the_cipher_schema_and_startup_invariants(
        self,
    ) -> None:
        ctx = Mock()
        validation = build_backup(ctx).restore_validation_service()
        config = validation._config

        self.assertIs(configure_cipher, config.configure_cipher)
        self.assertIs(row_factory, config.row_factory)
        self.assertIs(database_schema_is_current, config.schema_is_current)
        with patch.object(backup_wiring, "apply_startup_invariants") as invariants:
            config.startup_invariants("db")
        kwargs = invariants.call_args.kwargs
        self.assertEqual("db", invariants.call_args.args[0])
        self.assertIs(ctx.key_values, kwargs["key_values"])
        self.assertEqual(json.dumps(DEFAULT_PROFILE), kwargs["default_profile_json"])
        self.assertEqual(
            list(PROVIDER_RESYNC_KEYS.values()), list(kwargs["provider_resync_keys"])
        )


if __name__ == "__main__":
    unittest.main()
