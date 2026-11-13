"""A user-started sync job is admitted from the provider's own configured state.

Admission must not depend on full-resync handlers: Intervals.icu has none, yet its
plan push is a user job. The endpoint below runs on the real built-in runtime
bindings, the real job queue and normalization, and a temporary SQLite database.
No network, no real ``.env``, no data directory and no provider account.
"""

from __future__ import annotations

import sqlite3
import threading
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest import mock

from support import temp_database

from backend.canonical.vocabulary import GARMIN_ID, INTERVALS_ID, WAHOO_ID
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.http_api.sync_commands import SyncCommandEndpoint
from backend.runtime.events import StateEventBuffer
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.daily import DailySyncMarkerService
from backend.sync.execution_wiring import provider_configured_checks
from backend.sync.jobs import SyncJobStore
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
from backend.sync.queue import SyncJobQueueService

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
WORKOUT_ID = "11111111-1111-4111-8111-111111111111"
ENTRIES = [{"library_workout_id": WORKOUT_ID, "expected_payload_hash": "a" * 64}]
JOBS = "/api/sync/jobs"


def _body(provider: Any) -> dict[str, Any]:
    return {"provider": provider, "type": "plan_push", "payload": {"entries": ENTRIES}}


def _configured(
    *, intervals_key: str, wahoo_connected: bool, garmin_configured: bool
) -> dict[str, Any]:
    """Stand in for live owners; only the configured state is read."""
    config: Any = SimpleNamespace(intervals_api_key=intervals_key, calendar_ical_url="")
    garmin = mock.Mock(name="garmin")
    garmin.sync_service.return_value.configured.return_value = garmin_configured
    wahoo_sync = mock.Mock(name="wahoo_sync")
    wahoo_sync.configured.return_value = wahoo_connected
    ctx = mock.Mock(
        config=lambda: config,
        garmin=garmin,
        wahoo=SimpleNamespace(sync_service=lambda: wahoo_sync),
    )
    return provider_configured_checks(ctx)


def build_endpoint(
    case: unittest.TestCase,
    *,
    intervals_key: str,
    wahoo_connected: bool,
    garmin_configured: bool,
) -> tuple[SyncCommandEndpoint, DatabaseManager]:
    """Wire the real configured checks, queue and a temporary database for a case."""
    database = temp_database(
        case, "admission.sqlite", row_factory=sqlite3.Row, schema=True
    )
    identifiers = iter(f"job-{index}" for index in range(1, 100))
    store = SyncJobStore(database, NOW.isoformat, lambda: next(identifiers))
    queue = SyncJobQueueService(
        store,
        mock.Mock(spec=StateEventBuffer),
        MaintenanceGate(),
        threading.Event(),
        all_sync_days=-1,
        daily_sync_markers=DailySyncMarkerService(
            database, KeyValueRepository(NOW.isoformat), lambda: NOW
        ),
    )
    configured = _configured(
        intervals_key=intervals_key,
        wahoo_connected=wahoo_connected,
        garmin_configured=garmin_configured,
    )
    endpoint = SyncCommandEndpoint(
        queue,
        mock.Mock(),
        mock.Mock(),
        lambda: "operation-1",
        {"intervals": 90},
        -1,
        provider_configured=lambda provider_id: configured[provider_id](),
    )
    return endpoint, database


def stored_jobs(database: DatabaseManager) -> int:
    with database.unit_of_work() as db:
        return int(db.execute("SELECT COUNT(*) FROM sync_jobs").fetchone()[0])


class ConfiguredProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.endpoint, self.database = build_endpoint(
            self,
            intervals_key="fake-key",
            wahoo_connected=True,
            garmin_configured=True,
        )

    def test_configured_intervals_and_wahoo_plan_push_are_enqueued(self) -> None:
        for provider in (INTERVALS_ID, WAHOO_ID):
            with self.subTest(provider=provider):
                status, job = self.endpoint.execute(JOBS, _body(provider))

                self.assertEqual(202, status)
                self.assertEqual(
                    (provider, "plan_push"), (job["provider"], job["type"])
                )

    def test_every_registered_plan_push_provider_is_admitted(self) -> None:
        providers = [
            descriptor.provider_id
            for descriptor in DEFAULT_PROVIDER_REGISTRY.all()
            if "plan_push" in descriptor.job_types
        ]
        self.assertEqual({INTERVALS_ID, GARMIN_ID, WAHOO_ID}, set(providers))

        for provider in providers:
            with self.subTest(provider=provider):
                status, _ = self.endpoint.execute(JOBS, _body(provider))

                self.assertEqual(202, status)

    def test_unknown_provider_is_a_validation_error_not_a_job(self) -> None:
        with self.assertRaises(AppError) as caught:
            self.endpoint.execute(JOBS, _body("unknown"))

        self.assertEqual(400, caught.exception.status)
        self.assertEqual("invalid_job_request", caught.exception.reason)
        self.assertEqual(0, stored_jobs(self.database))


class UnconfiguredProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.endpoint, self.database = build_endpoint(
            self, intervals_key="", wahoo_connected=False, garmin_configured=False
        )

    def test_unconfigured_providers_get_409_before_any_job_is_stored(self) -> None:
        for provider in (INTERVALS_ID, GARMIN_ID, WAHOO_ID):
            with self.subTest(provider=provider):
                with self.assertRaises(AppError) as caught:
                    self.endpoint.execute(JOBS, _body(provider))

                self.assertEqual(409, caught.exception.status)
                self.assertEqual("not_configured", caught.exception.reason)
                self.assertEqual(
                    DEFAULT_PROVIDER_REGISTRY.get(provider).not_configured_message,
                    caught.exception.message,
                )
        self.assertEqual(0, stored_jobs(self.database))


if __name__ == "__main__":
    unittest.main()
