"""Acceptance test: a provider through the full sync orchestration.

Wahoo, ranked last, with a fake job owner stands in for any provider the table
lists. It must reach scheduling, the job queue, execution with real payload
normalization, freshness and status projection, the HTTP manual route and Coach
refresh through the real orchestration owners.

The test is deterministic: a fake clock, a temporary SQLite database built from
the current schema, a fake job owner and mocked HTTP and Coach collaborators.
It uses no network, no real ``.env``, no data directory and no provider account.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import tempfile
import threading
import unittest
from collections.abc import Mapping
from dataclasses import fields, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from support import dispatch_route, make_config, temp_database

from backend.canonical.vocabulary import GARMIN_ID, WAHOO_ID
from backend.db.key_value import KeyValueService
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.diagnostics.report import (
    DiagnosticReportDependencies,
    DiagnosticReportService,
)
from backend.errors import AppError
from backend.http_api.bootstrap_state import (
    PublicBootstrapDependencies,
    PublicBootstrapService,
)
from backend.http_api.sync_commands import SyncCommandEndpoint
from backend.http_api.sync_commands_post import SyncCommandPostRoute
from backend.http_api.sync_get import SyncGetRoutes
from backend.provider_credentials import WAHOO_TOKENS_KEY
from backend.runtime.events import StateEventBuffer
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.commands import ProviderRefreshCommandService
from backend.sync.daily import DailySyncMarkerService
from backend.sync.executor import SyncJobExecutor
from backend.sync.freshness import ProviderFreshnessService
from backend.sync.full_resync import (
    FullProviderResyncService,
    FullResyncStateStore,
)
from backend.sync.garmin import GarminSyncStateService
from backend.sync.job_outcomes import SyncJobOutcomeService
from backend.sync.jobs import SyncJobStore
from backend.sync.provider_table import (
    CALENDAR_ID,
    WAHOO_NOT_CONFIGURED_MESSAGE,
    WEATHER_ID,
)
from backend.sync.queue import SyncJobQueueService
from backend.sync.scheduler import (
    DailySyncScheduler,
    DailySyncSchedulerConfig,
    StartupSyncScheduler,
    StartupSyncSchedulerConfig,
)
from backend.sync.state import SyncStateRepository
from backend.sync.status import SyncPublicStateService

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
AUTO_UPDATE_LABEL = "stündliche automatische Aktualisierung"
MANUAL_PATH = "/api/wahoo/sync"
PERIOD_PATH = "/api/garmin/sync"
PERIOD_MESSAGE = "Der Zeitraum für garmin muss -1 oder zwischen 1 und 90 Tagen liegen."
WAHOO_TOKENS = json.dumps(
    {"access_token": "placeholder", "refresh_token": "placeholder"}
)


class _Clock:
    """Fake clock that the store, markers, freshness and outcomes all read."""

    def __init__(self, start: datetime) -> None:
        self.current = start

    def now(self) -> datetime:
        return self.current

    def iso(self) -> str:
        return self.current.isoformat()

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


class _Policy:
    """Schedule policy that records refreshes and, optionally, its configuration asks."""

    def __init__(self, provider_id: str = WAHOO_ID, *, log: list[str] | None = None):
        self._provider_id = provider_id
        self._log = log
        self.refresh_calls: list[tuple[str, str]] = []

    def configured(self) -> bool:
        if self._log is not None:
            self._log.append(self._provider_id)
            return False
        return True

    def blocked(self) -> bool:
        return False

    def refresh_payload(self, trigger: str, reason: str) -> dict[str, Any]:
        self.refresh_calls.append((trigger, reason))
        return {"days": 14, "reason": reason}


class _Owner:
    """Fake provider owner that persists its own last-sync timestamp on success."""

    def __init__(
        self,
        database: DatabaseManager,
        key_values: KeyValueRepository,
        clock: _Clock,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._database = database
        self._key_values = key_values
        self._clock = clock

    def execute(
        self,
        job: Mapping[str, Any],
        payload: dict[str, Any],
        reason: str,
        *,
        job_type: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "job": dict(job),
                "payload": dict(payload),
                "reason": reason,
                "job_type": job_type,
            }
        )
        with self._database.unit_of_work() as db:
            self._key_values.set(db, "last_wahoo_sync_at", self._clock.iso())
        return {"status": "completed"}


class OrchestrationCase(unittest.TestCase):
    """Wire every real orchestration owner around one temporary database."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.clock = _Clock(NOW)
        self.database = temp_database(
            self,
            path=root / "acceptance.sqlite",
            row_factory=sqlite3.Row,
            schema=True,
        )
        self.config = make_config(
            garmin_tokenstore=str(root / "garmin-tokenstore-not-created"),
            wahoo_client_id="client-id",
            wahoo_client_secret="client-secret",
            wahoo_redirect_uri="https://coach.example.invalid/api/wahoo/callback",
        )
        self.key_values = KeyValueRepository(self.clock.iso)
        self.connect_wahoo()
        identifiers = iter(f"job-{index}" for index in range(1, 500))
        self.publisher = Mock(spec=StateEventBuffer)
        self.gate = MaintenanceGate()
        self.wake = threading.Event()
        self.store = SyncJobStore(
            self.database, self.clock.iso, lambda: next(identifiers)
        )
        self.markers = DailySyncMarkerService(
            self.database, self.key_values, self.clock.now
        )
        self.queue = SyncJobQueueService(
            self.store,
            self.publisher,
            self.gate,
            self.wake,
            all_sync_days=-1,
            daily_sync_markers=self.markers,
        )
        self.owner = _Owner(self.database, self.key_values, self.clock)
        self.executor = SyncJobExecutor(
            historical_sync=Mock(),
            outcome_service=SyncJobOutcomeService(
                self.store,
                self.publisher,
                self.wake,
                lambda text: text,
                logging.getLogger("acceptance.provider"),
                self.clock.now,
                retry_base_seconds=1,
                retry_max_seconds=60,
            ),
            all_sync_days=-1,
            job_owners={WAHOO_ID: self.owner},
        )
        self.sync_state = SyncStateRepository(
            self.database, self.key_values, self.clock.iso
        )
        self.provider_configured = Mock(return_value=True)
        self.endpoint = SyncCommandEndpoint(
            self.queue,
            self.sync_state,
            Mock(),
            lambda: "operation-1",
            {WAHOO_ID: 84, GARMIN_ID: 84},
            -1,
            provider_configured=self.provider_configured,
        )
        self.post_route = SyncCommandPostRoute(lambda: self.endpoint)
        self.profile = Mock()
        self.profile.get.return_value = {}
        self.garmin_state = Mock()
        self.garmin_state.core_error_entries.return_value = []
        self.state_versions = Mock()
        self.state_versions.versions.return_value = {"sync": "1"}
        self.freshness = ProviderFreshnessService(
            self.config, self.database, self.key_values, self.clock.now
        )
        self.status = SyncPublicStateService(
            self.config,
            self.database,
            self.key_values,
            self.freshness,
            self.profile,
            self.garmin_state,
            self.gate,
            self.queue,
            self.state_versions,
            running_probes={},
        )
        self.get_routes = SyncGetRoutes(
            lambda: self.queue,
            lambda: self.status,
            Mock(),
            lambda: date(2026, 9, 20),
            -1,
        )
        self.synchronous = Mock()
        self.synchronous.refresh.return_value = {"ok": True, "status": "completed"}
        self.refresh = ProviderRefreshCommandService(
            self.queue,
            synchronous_refreshes={WAHOO_ID: self.synchronous},
        )

    def connect_wahoo(self, *, connected: bool = True) -> None:
        with self.database.unit_of_work() as db:
            if connected:
                self.key_values.set(db, WAHOO_TOKENS_KEY, WAHOO_TOKENS)
            else:
                self.key_values.delete(db, WAHOO_TOKENS_KEY)

    def daily_scheduler(self, policies: Mapping[str, Any]) -> DailySyncScheduler:
        return DailySyncScheduler(
            self.queue,
            self.markers,
            self.gate,
            config=DailySyncSchedulerConfig(
                auto_update_label=AUTO_UPDATE_LABEL,
            ),
            schedule_policies=policies,
        )

    def startup_scheduler(self, policies: Mapping[str, Any]) -> StartupSyncScheduler:
        return StartupSyncScheduler(
            self.queue,
            self.sync_state,
            config=StartupSyncSchedulerConfig(
                sync_chunk_days=30,
                sync_earliest_date=date(2026, 1, 1),
            ),
            schedule_policies=policies,
        )

    def _wahoo_freshness(self) -> dict[str, Any]:
        entries = self.freshness.current(
            profile={},
            garmin_has_core_error=False,
            garmin_tokenstore_exists=False,
        )
        return next(
            entry
            for entry in entries
            if (entry["provider"], entry["area"]) == (WAHOO_ID, "activities")
        )


def drain(case: OrchestrationCase) -> None:
    """Claim and run queued jobs until none is claimable, as the worker does."""
    while (job := case.store.claim()) is not None:
        case.executor.run(job)


def job_rows(
    case: OrchestrationCase, provider: str | None = WAHOO_ID, job_type: str = "refresh"
) -> list[dict[str, Any]]:
    """Return the stored jobs of one provider (all providers for ``None``)."""
    with case.database.unit_of_work() as db:
        rows = db.execute(
            "SELECT * FROM sync_jobs WHERE (provider=? OR ? IS NULL) AND type=? "
            "ORDER BY rowid",
            (provider, provider, job_type),
        ).fetchall()
    return [dict(row) for row in rows]


class SchedulingTests(OrchestrationCase):
    def test_startup_enqueues_the_provider_as_a_startup_refresh(self) -> None:
        policy = _Policy()

        self.startup_scheduler({WAHOO_ID: policy}).schedule()

        rows = job_rows(self)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["requested_by"], "startup")
        self.assertEqual(
            json.loads(rows[0]["payload"]), {"days": 14, "reason": "startup"}
        )
        self.assertEqual(policy.refresh_calls, [("startup", "startup")])

    def test_daily_scheduler_honours_the_marker_interval_and_active_jobs(self) -> None:
        policy = _Policy()
        scheduler = self.daily_scheduler({WAHOO_ID: policy})

        scheduler.schedule()
        self.assertEqual(len(job_rows(self)), 1)
        self.assertEqual(job_rows(self)[0]["requested_by"], "scheduler")

        self.clock.advance(600)
        scheduler.schedule()
        self.assertEqual(len(job_rows(self)), 1, "an active job blocks a second one")

        drain(self)
        scheduler.schedule()
        self.assertEqual(len(job_rows(self)), 1, "marker is not due within an hour")

        self.clock.advance(4300 - 600)
        scheduler.schedule()
        rows = job_rows(self)
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            json.loads(rows[1]["payload"]),
            {"days": 14, "reason": AUTO_UPDATE_LABEL},
        )
        self.assertEqual(
            policy.refresh_calls,
            [("daily", AUTO_UPDATE_LABEL), ("daily", AUTO_UPDATE_LABEL)],
        )

    def test_startup_and_daily_order_follow_the_table_ranks(self) -> None:
        daily_log: list[str] = []
        startup_log: list[str] = []
        ids = (WAHOO_ID, GARMIN_ID, CALENDAR_ID, WEATHER_ID)

        self.daily_scheduler(
            {pid: _Policy(pid, log=daily_log) for pid in ids}
        ).schedule()
        self.startup_scheduler(
            {pid: _Policy(pid, log=startup_log) for pid in ids}
        ).schedule()

        self.assertEqual(daily_log, [WEATHER_ID, CALENDAR_ID, GARMIN_ID, WAHOO_ID])
        self.assertEqual(startup_log, [CALENDAR_ID, GARMIN_ID, WEATHER_ID, WAHOO_ID])
        self.assertEqual(job_rows(self, None), [], "order probes enqueue nothing")


class QueueAndExecutionTests(OrchestrationCase):
    def test_queue_normalizes_the_payload_before_persisting_it(self) -> None:
        self.queue.enqueue(
            WAHOO_ID,
            "refresh",
            {"days": "7", "reason": "  manual  "},
            requested_by="user",
        )

        rows = job_rows(self)
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            json.loads(rows[0]["payload"]), {"days": 7, "reason": "manual"}
        )
        self.assertEqual(rows[0]["status"], "queued")

    def test_queue_rejects_unknown_fields_before_persisting(self) -> None:
        error = self.rejection({"bogus": 1})

        self.assertEqual(error.status, 400)
        self.assertEqual(error.reason, "invalid_job_request")
        self.assertEqual(job_rows(self), [])

    def test_queue_enforces_the_provider_period_limit(self) -> None:
        """The provider's ``max_sync_days`` (90 for Wahoo) bounds queued jobs."""
        error = self.rejection({"days": 91, "reason": "too long"})

        self.assertEqual(error.status, 400)
        self.assertEqual(job_rows(self), [])

    def rejection(self, payload: dict[str, Any]) -> AppError:
        with self.assertRaises(AppError) as raised:
            self.queue.enqueue(WAHOO_ID, "refresh", payload, requested_by="user")
        return raised.exception

    def test_executor_runs_the_normalized_payload_through_the_owner(self) -> None:
        self.queue.enqueue(
            WAHOO_ID, "refresh", {"days": "7", "reason": "manual"}, requested_by="user"
        )

        drain(self)

        self.assertEqual(len(self.owner.calls), 1)
        call = self.owner.calls[0]
        self.assertEqual(call["payload"], {"days": 7, "reason": "manual"})
        self.assertEqual(call["job_type"], "refresh")
        self.assertEqual(job_rows(self)[0]["status"], "completed")


class FreshnessAndStatusTests(OrchestrationCase):
    def test_freshness_moves_from_never_loaded_to_fresh_then_stale(self) -> None:
        self.assertEqual(self._wahoo_freshness()["state"], "never_loaded")

        self.queue.enqueue(
            WAHOO_ID, "refresh", {"days": 7, "reason": "manual"}, requested_by="user"
        )
        self.clock.advance(60)
        drain(self)
        success_at = self.clock.current.isoformat()

        fresh = self._wahoo_freshness()
        self.assertEqual(fresh["state"], "fresh")
        self.assertTrue(fresh["configured"])
        self.assertTrue(fresh["read_only"])
        self.assertEqual(fresh["last_success_at"], success_at)
        self.assertTrue(fresh["has_last_good"])

        self.clock.advance(3 * 24 * 60 * 60)
        stale = self._wahoo_freshness()
        self.assertEqual(stale["state"], "stale")
        self.assertTrue(stale["stale"])

    def test_disconnected_provider_is_reported_as_not_configured(self) -> None:
        self.connect_wahoo(connected=False)

        entry = self._wahoo_freshness()

        self.assertEqual(entry["state"], "not_configured")
        self.assertFalse(entry["configured"])

    def test_status_json_reports_the_job_and_its_freshness(self) -> None:
        handler = Mock()
        dispatch_route(self.post_route, handler, MANUAL_PATH, method="POST")
        self.clock.advance(30)
        drain(self)

        status_handler = Mock()
        status_handler.path = "/api/sync/status"
        self.assertTrue(
            dispatch_route(self.get_routes, status_handler, "/api/sync/status")
        )

        status_code, payload = status_handler.send_json.call_args.args
        self.assertEqual(status_code, 200)
        wahoo_jobs = [job for job in payload["jobs"] if job["provider"] == WAHOO_ID]
        self.assertEqual([job["status"] for job in wahoo_jobs], ["completed"])
        wahoo_entries = [
            entry
            for entry in payload["provider_freshness"]
            if (entry["provider"], entry["area"]) == (WAHOO_ID, "activities")
        ]
        self.assertEqual([entry["state"] for entry in wahoo_entries], ["fresh"])


class HttpRouteTests(OrchestrationCase):
    def test_manual_route_enqueues_a_user_refresh_and_answers_202(self) -> None:
        handler = Mock()

        self.assertTrue(
            dispatch_route(self.post_route, handler, MANUAL_PATH, method="POST")
        )

        status_code, body = handler.send_json.call_args.args
        self.assertEqual(status_code, 202)
        rows = job_rows(self)
        self.assertEqual([row["id"] for row in rows], [body["id"]])
        self.assertEqual(rows[0]["requested_by"], "user")
        self.assertEqual(json.loads(rows[0]["payload"]), {"reason": "manual"})
        handler.read_json.assert_not_called()

    def test_period_route_refuses_an_out_of_range_period_before_queueing(self) -> None:
        handler = Mock()
        handler.read_json.return_value = {"days": 99}

        with self.assertRaises(AppError) as raised:
            dispatch_route(self.post_route, handler, PERIOD_PATH, method="POST")

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(str(raised.exception), PERIOD_MESSAGE)
        self.assertEqual(job_rows(self, None), [])

    def test_unconfigured_provider_is_refused_with_409(self) -> None:
        self.provider_configured.return_value = False
        handler = Mock()

        with self.assertRaises(AppError) as raised:
            dispatch_route(self.post_route, handler, MANUAL_PATH, method="POST")

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.reason, "not_configured")
        self.assertEqual(str(raised.exception), WAHOO_NOT_CONFIGURED_MESSAGE)
        self.assertNotIn("Intervals.icu", str(raised.exception))
        self.assertEqual(job_rows(self), [])

    def test_route_for_an_undeclared_path_is_not_handled(self) -> None:
        handler = Mock()

        self.assertFalse(
            dispatch_route(self.post_route, handler, "/api/wahoo/other", method="POST")
        )
        handler.send_json.assert_not_called()


class CoachRefreshTests(OrchestrationCase):
    def test_coach_refresh_enqueues_asynchronously_by_default(self) -> None:
        result = self.refresh.start(WAHOO_ID, {"days": 7, "reason": "coach"})

        self.assertEqual(result["status"], "queued")
        self.assertTrue(result["ok"])
        rows = job_rows(self)
        self.assertEqual([row["id"] for row in rows], [result["sync_job_id"]])
        self.assertEqual(rows[0]["requested_by"], "coach")
        self.synchronous.refresh.assert_not_called()

    def test_coach_refresh_waits_for_the_synchronous_refresh_when_asked(self) -> None:
        result = self.refresh.start(
            WAHOO_ID, {"days": 7, "reason": "coach", "_wait_for_completion": True}
        )

        self.assertEqual(result, {"ok": True, "status": "completed"})
        self.synchronous.refresh.assert_called_once()
        self.assertEqual(job_rows(self), [])

    def test_coach_wait_without_a_synchronous_refresh_is_refused(self) -> None:
        service = ProviderRefreshCommandService(self.queue, {})

        with self.assertRaises(AppError) as raised:
            service.start(WAHOO_ID, {"days": 7, "_wait_for_completion": True})

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(job_rows(self), [])

    def test_coach_refresh_rejects_unknown_fields_without_queueing(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.refresh.start(WAHOO_ID, {"bogus": 1})

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(job_rows(self), [])


UNREAD_VALUE = "fake-unread-status"
SYNC_STATE = {
    "sync_operation_id": "op-fake-1",
    "sync_operation_status": "completed",
    "sync_operation_phase": "wellness",
    "sync_operation_progress": "40",
    "sync_operation_message": "Fake sync message",
    "sync_operation_started_at": "2026-09-20T11:00:00+00:00",
    "sync_operation_finished_at": "2026-09-20T11:05:00+00:00",
    "last_sync_error": "fake-last-sync-error",
    "garmin_sync_status": "Fake Garmin status",
    "last_garmin_sync_at": "2026-09-20T11:30:00+00:00",
    "last_garmin_error": '[{"source":"activities","message":"fake garmin failure"}]',
    "last_wahoo_sync_at": "2026-09-18T01:00:00+00:00",
    "last_wahoo_sync_error": "fake-wahoo-error",
    "last_external_calendar_sync_at": "2026-09-20T09:00:00+00:00",
    "last_external_calendar_sync_error": "fake-calendar-error",
    "last_competition_sync_at": "2026-09-20T08:00:00+00:00",
    "last_competition_sync_error": "",
    "sync_garmin_last_success_at": "2026-09-20T11:50:00+00:00",
    "sync_garmin_last_attempt_at": "2026-09-20T11:55:00+00:00",
    "sync_wahoo_last_success_at": "2026-09-20T09:00:00+00:00",
    "sync_wahoo_last_attempt_at": "2026-09-20T10:00:00+00:00",
    "sync_calendar_last_success_at": "2026-09-20T11:30:00+00:00",
    "sync_calendar_last_attempt_at": "2026-09-20T10:00:00+00:00",
    "garmin_full_resync_running": "0",
    "garmin_full_resync_status": "hidden while not running",
    "garmin_full_resync_at": "2026-09-19T08:00:00+00:00",
    "garmin_full_resync_error": "",
    "wahoo_full_resync_running": "1",
    "wahoo_full_resync_status": "Fake Wahoo resync running",
    "wahoo_full_resync_at": "2026-09-18T08:00:00+00:00",
    "wahoo_full_resync_error": "fake-resync-error",
    # Written by earlier releases, read by nothing (#2080).
    "competition_sync_running": "1",
    "competition_sync_status": UNREAD_VALUE,
    "external_calendar_sync_status": UNREAD_VALUE,
}
# Wahoo activities: an earlier success, then a newer failed attempt.
HISTORY_ROWS = (
    ("h-1", "2026-09-20T10:59:00+00:00", "2026-09-20T11:00:00+00:00", "success", None),
    (
        "h-2",
        "2026-09-20T11:45:00+00:00",
        "2026-09-20T11:46:00+00:00",
        "error",
        "auth_expired",
    ),
)
RESYNC_PATHS = {
    "/api/garmin/full-resync": GARMIN_ID,
    "/api/wahoo/full-resync": WAHOO_ID,
}
RESYNC_STATES: dict[str, dict[str, Any]] = {
    GARMIN_ID: {
        "running": False,
        "status": None,
        "last_resync_at": "2026-09-19T08:00:00+00:00",
        "last_error": None,
    },
    WAHOO_ID: {
        "running": True,
        "status": "Fake Wahoo resync running",
        "last_resync_at": "2026-09-18T08:00:00+00:00",
        "last_error": "fake-resync-error",
    },
}


def seed_sync_state(case: OrchestrationCase) -> None:
    """Write every key-value sync-state kind and the refresh history of one area."""
    with case.database.unit_of_work() as db:
        for key, value in SYNC_STATE.items():
            case.key_values.set(db, key, value)
        for row_id, started, finished, status, error_code in HISTORY_ROWS:
            db.execute(
                "INSERT INTO provider_refresh_history(id, provider, area, "
                "operation_id, trigger, started_at, finished_at, phase, status, "
                "error_code) VALUES (?, 'wahoo', 'activities', 'op', 'manual', "
                "?, ?, 'done', ?, ?)",
                (row_id, started, finished, status, error_code),
            )


def mock_dependencies(dependencies: type, **overrides: Any) -> Any:
    """Build a dependency dataclass whose fields are mocks unless overridden."""
    values = {field.name: Mock() for field in fields(dependencies)}
    return dependencies(**{**values, **overrides})


class SyncStateReaderTests(OrchestrationCase):
    """Pin what every reader of the sync state shows for one seeded database."""

    def setUp(self) -> None:
        super().setUp()
        seed_sync_state(self)
        self.config = replace(
            self.config,
            calendar_ical_url="https://calendar.example.invalid/feed.ics",
            intervals_api_key="fake-intervals-key",
        )
        self.freshness = ProviderFreshnessService(
            self.config, self.database, self.key_values, self.clock.now
        )
        self.garmin_errors = GarminSyncStateService(
            self.database,
            self.key_values,
            self.sync_state,
            self.markers,
            Mock(),
            self.clock.iso,
            self.clock.now,
            snapshot_writer=Mock(),
        )
        self.resync = FullProviderResyncService(
            {GARMIN_ID: Mock(), WAHOO_ID: Mock()},
            FullResyncStateStore(self.database, self.key_values),
            Mock(),
        )

    def entries(self) -> dict[tuple[str, str], dict[str, Any]]:
        entries = self.freshness.current(
            profile={},
            garmin_has_core_error=bool(self.garmin_errors.core_error_entries()),
            garmin_tokenstore_exists=True,
            read_only=True,
        )
        return {(entry["provider"], entry["area"]): entry for entry in entries}

    def test_public_status_reads_operation_fields_and_running_probes(self) -> None:
        running = [True]
        service = SyncPublicStateService(
            self.config,
            self.database,
            self.key_values,
            self.freshness,
            self.profile,
            self.garmin_state,
            self.gate,
            self.queue,
            self.state_versions,
            running_probes={"garmin": lambda: False, "wahoo": lambda: running[0]},
        )
        expected = {
            "status": "completed",
            "phase": "wellness",
            "progress": 40,
            "operation_id": "op-fake-1",
            "message": "Fake sync message",
            "started_at": "2026-09-20T11:00:00+00:00",
            "finished_at": "2026-09-20T11:05:00+00:00",
            "last_error": "fake-last-sync-error",
        }

        state = service.state(freshness=[], jobs=[])
        running[0] = False
        idle_state = service.state(freshness=[], jobs=[])

        # While Wahoo runs, the finished Garmin operation is not shown as the
        # running one (#2706); the general error stays.
        self.assertEqual(
            {
                **dict.fromkeys(expected),
                "status": "running",
                "phase": "running",
                "progress": 0,
                "started_at": "2026-09-20T11:00:00+00:00",
                "finished_at": "2026-09-20T11:05:00+00:00",
                "last_error": "fake-last-sync-error",
            },
            {key: state[key] for key in expected},
        )
        self.assertNotIn(UNREAD_VALUE, json.dumps(state, default=str))
        self.assertTrue(state["running"], "only a probe sets running")
        self.assertEqual({key: idle_state[key] for key in expected}, expected)
        self.assertFalse(idle_state["running"], "a stored status does not")

    def test_freshness_reads_history_first_and_key_values_as_fallback(self) -> None:
        entries = self.entries()

        wahoo = entries[(WAHOO_ID, "activities")]
        self.assertEqual(
            {key: wahoo[key] for key in ("last_attempt_at", "last_success_at")},
            {
                "last_attempt_at": "2026-09-20T11:45:00+00:00",
                "last_success_at": "2026-09-20T11:00:00+00:00",
            },
        )
        self.assertEqual(
            (wahoo["state"], wahoo["error_code"]), ("stale", "auth_expired")
        )
        fallbacks = {
            (GARMIN_ID, "data"): ("2026-09-20T11:30:00+00:00", "provider_error"),
            (CALENDAR_ID, "events"): ("2026-09-20T09:00:00+00:00", "provider_error"),
            ("intervals", "competitions"): ("2026-09-20T08:00:00+00:00", None),
        }
        for key, (at, error_code) in fallbacks.items():
            with self.subTest(key=key):
                entry = entries[key]
                self.assertEqual(
                    (entry["last_attempt_at"], entry["last_success_at"]), (at, at)
                )
                self.assertEqual(
                    (entry["state"], entry["error_code"]), ("fresh", error_code)
                )

    def test_full_resync_state_reaches_the_progress_route_and_bootstrap(self) -> None:
        routes = SyncGetRoutes(
            lambda: self.queue,
            lambda: self.status,
            Mock(),
            lambda: date(2026, 9, 20),
            -1,
            full_resync=lambda: self.resync,
            full_resync_providers=RESYNC_PATHS,
        )
        for path, provider in RESYNC_PATHS.items():
            handler = Mock()
            handler.path = path
            dispatch_route(routes, handler, path)
            self.assertEqual(
                handler.send_json.call_args.args,
                (200, {**RESYNC_STATES[provider], "outcome": None}),
            )

        bootstrap = PublicBootstrapService(
            mock_dependencies(
                PublicBootstrapDependencies,
                database_manager=lambda: self.database,
                config=self.config,
                key_values=KeyValueService(self.database, self.key_values),
                full_provider_resync_service=lambda: self.resync,
                garmin_sync_service=lambda: Mock(running=lambda: False),
                settings=Mock(selected_provider=lambda: "openai"),
                threshold_warnings=lambda: None,
            )
        ).read()

        self.assertEqual(bootstrap["provider_resync"], RESYNC_STATES)
        self.assertNotIn(UNREAD_VALUE, json.dumps(bootstrap, default=str))
        self.assertEqual(
            bootstrap["garmin_sync"], {"running": False, "status": "Fake Garmin status"}
        )

    def test_diagnostics_report_the_stored_errors_and_last_syncs(self) -> None:
        report = DiagnosticReportService(
            mock_dependencies(
                DiagnosticReportDependencies,
                database_manager=self.database,
                key_values=self.key_values,
                config=self.config,
                utc_now=NOW.isoformat,
                redactor=Mock(redact_text=lambda text: text),
                diagnostic_capture=Mock(status=dict, entries=list),
                settings=Mock(available_model_options=list),
                canonical_backfill=None,
                canonical_read=None,
                garmin_change_check=None,
                lt1_ride_coverage=None,
            )
        ).report()

        self.assertEqual(report["sync"]["last_error"], "fake-last-sync-error")
        self.assertNotIn(UNREAD_VALUE, json.dumps(report, default=str))
        self.assertEqual(
            report["sync"]["providers"],
            {
                "garmin": {"last_sync_at": None, "last_plan_sync_at": None},
                "wahoo": {
                    "last_sync_at": "2026-09-20T11:00:00+00:00",
                    "last_plan_sync_at": None,
                },
                "intervals": {"last_sync_at": None, "last_plan_sync_at": None},
            },
        )
        wahoo = report["wahoo"]
        self.assertEqual(
            (wahoo["last_wahoo_sync_at"], wahoo["last_wahoo_sync_error"]),
            ("2026-09-18T01:00:00+00:00", "fake-wahoo-error"),
        )
        calendar = report["external_calendar"]
        self.assertEqual(
            (calendar["last_sync_at"], calendar["last_error"]),
            ("2026-09-20T09:00:00+00:00", "fake-calendar-error"),
        )

    def test_scheduler_due_check_uses_the_freshest_marker(self) -> None:
        self.assertFalse(self.markers.is_due(GARMIN_ID), "attempt 5 minutes ago")
        self.assertTrue(self.markers.is_due(WAHOO_ID), "newest marker 2 hours ago")
        self.assertFalse(self.markers.is_due(CALENDAR_ID), "success 30 minutes ago")


if __name__ == "__main__":
    unittest.main()
