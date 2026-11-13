"""Credentials saved in the app apply to the next sync job without a restart.

The executor is built once, as the sync worker does, before any credential is
saved. ``ProviderCredentialService`` then saves or removes the Intervals.icu key
and the next queued job must follow it. Real selected-workout, library and
competition services run behind the production gates; only their remote and
persistence collaborators are doubles. Temporary SQLite storage, no network.
"""

from __future__ import annotations

import tempfile
import threading
import unittest
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from support import temp_database

from backend import errors
from backend.config import Config, load_config
from backend.db import row_factory
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.planning import library as planning_library
from backend.provider_credentials import ProviderCredentialService
from backend.sync.competitions import CompetitionSyncService
from backend.sync.execution_wiring import build_sync_job_execution
from backend.sync.executor import PerJobOwner
from backend.sync.gates import ProviderResyncGate
from backend.sync.library import WorkoutLibrarySyncService
from backend.sync.selected import SelectedWorkoutSyncService
from backend.sync.wiring import SyncWindow

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
UNIT = "22222222-2222-4222-8222-222222222222"
LIBRARY_PAYLOAD = '{"name": "Easy ride"}'
REACHED = "library export reached"
SAVED_KEY = "saved-in-app-key"
MANIFEST = [{"type": "competition", "id": "race-1", "sha256": "b" * 64}]


class _LockedCompetitionLock:
    """A busy lock: a competition sync that passes its gate reports it and stops."""

    def acquire(self, blocking: bool = True) -> bool:
        return False

    def release(self) -> None:
        raise AssertionError("never acquired")


class _Observer:
    def observe(self, *args: Any, **kwargs: Any) -> Any:
        scope = mock.MagicMock()
        scope.__enter__.return_value = mock.Mock(result=None)
        return scope


class LiveCredentialHarness:
    """A worker executor built before the first credential is saved."""

    def __init__(self, case: unittest.TestCase) -> None:
        root = Path(case.enterContext(tempfile.TemporaryDirectory()))
        env_config = load_config(
            root,
            root / "data",
            {"APP_PASSWORD": "synthetic-password-123", "INTERVALS_ATHLETE_ID": "i42"},
        )
        self.config: Config = env_config
        self.database = temp_database(
            case, path=root / "live.sqlite", row_factory=row_factory
        )
        with self.database.unit_of_work() as db:
            initialize_schema(db)
            db.execute(
                "INSERT INTO workout_library (id, local_id, payload, sync_state, "
                "updated_at) VALUES (?, ?, ?, 'local', ?)",
                (UNIT, UNIT, LIBRARY_PAYLOAD, NOW.isoformat()),
            )
        lock = threading.RLock()
        self.credentials = ProviderCredentialService(
            env_config=env_config,
            database_manager=lambda: self.database,
            database_lock=lambda: lock,
            key_values=KeyValueRepository(NOW.isoformat),
            apply_config=self._apply,
            current_config=lambda: self.config,
        )
        self.library_state = mock.Mock()
        self.library_state.load_for_sync.side_effect = RuntimeError(REACHED)
        gate = ProviderResyncGate("Intervals.icu")

        def selected() -> SelectedWorkoutSyncService:
            library = WorkoutLibrarySyncService(
                self.config, mock.Mock(), self.library_state
            )
            return SelectedWorkoutSyncService(
                self.config,
                self.database,
                library,
                mock.Mock(),
                mock.Mock(),
                str,
                provider_resync_gate=gate,
            )

        def competitions() -> CompetitionSyncService:
            return CompetitionSyncService(
                self.config,
                mock.Mock(),
                mock.Mock(),
                mock.Mock(),
                self.database,
                mock.Mock(),
                mock.Mock(),
                cast(Any, str),
                mock.Mock(),
                NOW.isoformat,
                competition_lock=_LockedCompetitionLock(),
            )

        ctx = SimpleNamespace(
            clock=SimpleNamespace(now=lambda: NOW),
            sync_persistence=SimpleNamespace(state_repository=mock.Mock),
            sync_job_queue=SimpleNamespace(
                service=mock.Mock, outcome_service=mock.Mock
            ),
            provider_sync=SimpleNamespace(operation_observer=_Observer),
            nutrition=SimpleNamespace(intervals_sync_service=mock.Mock),
            morning_body_battery_service=mock.Mock,
            garmin=SimpleNamespace(
                sync_service=mock.Mock,
                fixture_loader=mock.Mock,
                activity_detail_service=mock.Mock,
                strength_push_service=mock.Mock,
                wellness_history_service=mock.Mock,
                stream_backfill_service=mock.Mock,
            ),
            external_calendar=SimpleNamespace(sync_service=mock.Mock),
            wahoo=SimpleNamespace(
                sync_service=mock.Mock,
                plan_push_service=mock.Mock,
                stream_backfill_service=mock.Mock,
            ),
        )
        # Built once, like the sync worker; every later job reuses this executor.
        self.executor = build_sync_job_execution(
            cast(Any, ctx),
            window=SyncWindow({}, -1, 30, NOW.date()),
            selected_workout_sync_service=selected,
            competition_sync_service=competitions,
            weather_sync_service=mock.Mock,
            intervals_resync_gate=gate,
            after_job=lambda _job: None,
        ).executor()

    def _apply(self, config: Config) -> None:
        self.config = config

    def save_key(self, key: str | None) -> None:
        self.credentials.update({"intervals_api_key": key})

    def run_job(self, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.executor.execute(
            {
                "id": "job-1",
                "provider": "intervals",
                "type": job_type,
                "payload": payload,
            }
        )


def _plan_push_payload() -> dict[str, Any]:
    digest = planning_library.library_payload_hash(LIBRARY_PAYLOAD)
    return {"entries": [{"library_workout_id": UNIT, "expected_payload_hash": digest}]}


class LiveCredentialJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = LiveCredentialHarness(self)

    def assert_not_configured(self, run: Callable[[], Any]) -> None:
        with self.assertRaises(AppError) as raised:
            run()
        self.assertEqual(raised.exception.reason, "not_configured")
        self.assertEqual(raised.exception.message, errors.INTERVALS_API_KEY_ERROR)

    def plan_push(self) -> dict[str, Any]:
        return self.harness.run_job("plan_push", _plan_push_payload())

    def competition_push(self) -> dict[str, Any]:
        return self.harness.run_job(
            "competition_push", {"reason": "test", "approval_manifest": MANIFEST}
        )

    def test_plan_push_and_library_sync_follow_the_saved_key(self) -> None:
        self.assert_not_configured(self.plan_push)

        self.harness.save_key(SAVED_KEY)
        result = self.plan_push()

        # The real library service passed its own gate and reached the export.
        self.assertEqual(result["results"][0]["status"], "error")
        self.assertIn(REACHED, result["results"][0]["error"])
        self.harness.library_state.load_for_sync.assert_called_once()

        self.harness.save_key(None)
        self.harness.library_state.load_for_sync.reset_mock()
        self.assert_not_configured(self.plan_push)
        self.harness.library_state.load_for_sync.assert_not_called()

    def test_competition_push_follows_the_saved_key(self) -> None:
        self.assert_not_configured(self.competition_push)

        self.harness.save_key(SAVED_KEY)
        self.assertEqual(self.competition_push().get("status"), "already_running")

        self.harness.save_key(None)
        self.assert_not_configured(self.competition_push)


class PerJobOwnerTests(unittest.TestCase):
    def test_builds_a_fresh_owner_for_every_job(self) -> None:
        owners = [mock.Mock(), mock.Mock()]
        owners[0].execute.return_value = {"n": 1}
        owners[1].execute.return_value = {"n": 2}
        build = mock.Mock(side_effect=owners)
        owner = PerJobOwner(build)
        build.assert_not_called()

        first = owner.execute({"id": "a"}, {}, "manual", job_type="refresh")
        second = owner.execute({"id": "b"}, {}, "manual", job_type="refresh")

        self.assertEqual((first, second), ({"n": 1}, {"n": 2}))
        self.assertEqual(build.call_count, 2)


class NotConfiguredMessageTests(unittest.TestCase):
    def test_messages_name_no_environment_variable(self) -> None:
        for message in (errors.INTERVALS_API_KEY_ERROR, errors.OPENAI_API_KEY_ERROR):
            with self.subTest(message=message):
                self.assertNotIn("INTERVALS_API_KEY", message)
                self.assertNotIn("OPENAI_API_KEY", message)
                self.assertIn("Mehr → Anbindungen", message)

    def test_messages_name_the_provider(self) -> None:
        self.assertTrue(errors.INTERVALS_API_KEY_ERROR.startswith("Intervals.icu"))
        self.assertTrue(errors.OPENAI_API_KEY_ERROR.startswith("OpenAI"))


if __name__ == "__main__":
    unittest.main()
