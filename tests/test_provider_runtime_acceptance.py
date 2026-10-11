"""Acceptance test: a test-only mock provider through the full sync orchestration.

``acme-mock`` exists only in this module, registered next to the real descriptors.
It must reach scheduling, the job queue, execution with real payload
normalization, freshness and status projection, the HTTP manual route and Coach
refresh without any provider literal in the orchestration code.

The test is deterministic: a fake clock, a temporary SQLite database built from
the current schema, a fake job owner and mocked HTTP and Coach collaborators.
It uses no network, no real ``.env``, no data directory and no provider account.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sqlite3
import tempfile
import threading
import unittest
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from provider_runtime_fakes import (
    ACME_AREA,
    ACME_ID,
    FakeJobOwner,
    FakeSchedulePolicy,
    acme_descriptor,
    acme_freshness_source,
)

from backend.coach.authorization import request_target_enum
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.http_api.sync_commands import SyncCommandEndpoint
from backend.http_api.sync_commands_post import SyncCommandPostRoute
from backend.http_api.sync_get import SyncGetRoutes
from backend.providers.descriptors import (
    DEFAULT_PROVIDER_DESCRIPTORS,
    ManualSyncRoute,
    ProviderDescriptor,
)
from backend.runtime.events import StateEventBuffer
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.commands import ProviderRefreshCommandService
from backend.sync.daily import DailySyncMarkerService
from backend.sync.executor import SyncJobExecutor
from backend.sync.freshness import ProviderFreshnessService
from backend.sync.freshness_sources import DEFAULT_FRESHNESS_SOURCES
from backend.sync.job_outcomes import SyncJobOutcomeService
from backend.sync.jobs import SyncJobStore
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from backend.sync.queue import SyncJobQueueService
from backend.sync.scheduler import (
    DailySyncScheduler,
    DailySyncSchedulerConfig,
    StartupSyncScheduler,
    StartupSyncSchedulerConfig,
)
from backend.sync.status import SyncPublicStateService

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
AUTO_UPDATE_LABEL = "stündliche automatische Aktualisierung"
MANUAL_PATH = "/api/acme-mock/sync"
NOT_CONFIGURED_MESSAGE = "Acme mock ist nicht konfiguriert."
PERIOD_MESSAGE = (
    "Der Zeitraum für acme-mock muss -1 oder zwischen 1 und 60 Tagen liegen."
)
DEFAULT_SNAPSHOT = DEFAULT_PROVIDER_REGISTRY.all()


def acceptance_descriptor(**changes: Any) -> ProviderDescriptor:
    """Return the acme descriptor with the routes and fields the orchestration uses."""
    base = dataclasses.replace(
        acme_descriptor(),
        refresh_fields=frozenset({"days", "reason"}),
        not_configured_message=NOT_CONFIGURED_MESSAGE,
        manual_sync=ManualSyncRoute(
            path=MANUAL_PATH,
            uses_sync_period=True,
            payload=(("reason", "manual"),),
        ),
    )
    return dataclasses.replace(base, **changes)


ACCEPTANCE_DESCRIPTOR = acceptance_descriptor()
REGISTRY = ProviderRegistry((*DEFAULT_PROVIDER_REGISTRY.all(), ACCEPTANCE_DESCRIPTOR))


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


class _Policy(FakeSchedulePolicy):
    """Schedule policy whose refresh payload uses only fields the descriptor declares."""

    def refresh_payload(self, trigger: str, reason: str) -> dict[str, Any]:
        self.refresh_calls.append((trigger, reason))
        return {"days": 14, "reason": reason}


class _RecordingPolicy(FakeSchedulePolicy):
    """Records the order in which the scheduler asks providers for configuration."""

    def __init__(self, provider_id: str, log: list[str]) -> None:
        super().__init__(configured=False)
        self._provider_id = provider_id
        self._log = log

    def configured(self) -> bool:
        self._log.append(self._provider_id)
        return False


class _AcmeOwner(FakeJobOwner):
    """Fake provider owner that persists its own last-sync timestamp on success."""

    def __init__(
        self,
        database: DatabaseManager,
        key_values: KeyValueRepository,
        clock: _Clock,
    ) -> None:
        super().__init__()
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
        result = super().execute(job, payload, reason, job_type=job_type)
        if result.get("status") == "completed":
            with self._database.unit_of_work() as db:
                self._key_values.set(db, "acme_last_sync_at", self._clock.iso())
        return result


def _set_period(provider_id: str, days: Any, all_sync_days: int) -> int:
    value = int(days)
    if value == all_sync_days or 1 <= value <= ACCEPTANCE_DESCRIPTOR.max_sync_days:
        return value
    raise ValueError(f"period out of range for {provider_id}")


def _config(tokenstore: str) -> Config:
    return Config(
        port=8090,
        openai_api_key="",
        openai_base_url="https://api.openai.com/v1",
        openai_model="model",
        intervals_api_key="",
        intervals_athlete_id="0",
        garmin_email="",
        garmin_password="",
        garmin_tokenstore=tokenstore,
        garmin_fixture_path="",
        calendar_ical_url="",
        app_password="",
        secure_cookies=False,
        data_retention_days=-1,
    )


class AcmeOrchestrationCase(unittest.TestCase):
    """Wire every real orchestration owner around one temporary database."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.clock = _Clock(NOW)
        self.database = DatabaseManager(
            root / "acceptance.sqlite", sqlite3, row_factory=sqlite3.Row
        )
        self.addCleanup(self.database.close)
        with self.database.unit_of_work() as db:
            initialize_schema(db)
        self.config = _config(str(root / "garmin-tokenstore-not-created"))
        self.key_values = KeyValueRepository(self.clock.iso)
        identifiers = iter(f"job-{index}" for index in range(1, 500))
        self.publisher = Mock(spec=StateEventBuffer)
        self.gate = MaintenanceGate()
        self.wake = threading.Event()
        self.store = SyncJobStore(
            self.database,
            self.clock.iso,
            lambda: next(identifiers),
            registry=REGISTRY,
        )
        self.markers = DailySyncMarkerService(
            self.database, self.key_values, self.clock.now, registry=REGISTRY
        )
        self.queue = SyncJobQueueService(
            self.store,
            self.publisher,
            self.gate,
            self.wake,
            all_sync_days=-1,
            daily_sync_markers=self.markers,
            registry=REGISTRY,
        )
        self.owner = _AcmeOwner(self.database, self.key_values, self.clock)
        self.executor = SyncJobExecutor(
            historical_sync=Mock(),
            outcome_service=SyncJobOutcomeService(
                self.store,
                self.publisher,
                self.wake,
                lambda text: text,
                logging.getLogger("acceptance.acme"),
                self.clock.now,
                retry_base_seconds=1,
                retry_max_seconds=60,
            ),
            all_sync_days=-1,
            job_owners={ACME_ID: self.owner},
            registry=REGISTRY,
        )
        self.period_state = Mock()
        self.period_state.sync_period.return_value = 14
        self.period_state.set_sync_period.side_effect = _set_period
        self.full_resync = Mock()
        self.full_resync.provider_configured.return_value = True
        self.endpoint = SyncCommandEndpoint(
            self.queue,
            self.period_state,
            Mock(),
            self.full_resync,
            lambda: "operation-1",
            {ACME_ID: 14},
            -1,
            registry=REGISTRY,
        )
        self.post_route = SyncCommandPostRoute(lambda: self.endpoint, registry=REGISTRY)
        self.profile = Mock()
        self.profile.get.return_value = {"acme_enabled": True}
        self.garmin_state = Mock()
        self.garmin_state.core_error_entries.return_value = []
        self.state_versions = Mock()
        self.state_versions.versions.return_value = {"sync": "1"}
        self.freshness = ProviderFreshnessService(
            self.config,
            self.database,
            self.key_values,
            self.clock.now,
            freshness_sources={
                **DEFAULT_FRESHNESS_SOURCES,
                ACME_ID: {ACME_AREA: acme_freshness_source()},
            },
            registry=REGISTRY,
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
            Mock(),
            running_probes={},
        )
        self.get_routes = SyncGetRoutes(
            lambda: Mock(),
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
            Mock(),
            -1,
            synchronous_refreshes={ACME_ID: self.synchronous},
        )

    def daily_scheduler(self, policies: Mapping[str, Any]) -> DailySyncScheduler:
        return DailySyncScheduler(
            Mock(),
            self.queue,
            self.markers,
            Mock(),
            self.database,
            self.key_values,
            threading.Lock(),
            Mock(),
            Mock(),
            self.gate,
            config=DailySyncSchedulerConfig(
                calendar_url_enabled=False,
                intervals_key_enabled=False,
                garmin_automatic_sync_days=-1,
                auto_update_label=AUTO_UPDATE_LABEL,
                sync_period_defaults={},
                all_sync_days=-1,
            ),
            schedule_policies=policies,
            registry=REGISTRY,
        )

    def startup_scheduler(self, policies: Mapping[str, Any]) -> StartupSyncScheduler:
        return StartupSyncScheduler(
            Mock(),
            self.queue,
            Mock(),
            Mock(),
            config=StartupSyncSchedulerConfig(
                calendar_enabled=False,
                intervals_enabled=False,
                garmin_automatic_sync_days=-1,
                sync_period_defaults={},
                all_sync_days=-1,
                sync_chunk_days=30,
                sync_earliest_date=date(2026, 1, 1),
            ),
            schedule_policies=policies,
            registry=REGISTRY,
        )

    def acme_freshness(self, *, enabled: bool = True) -> dict[str, Any]:
        entries = self.freshness.current(
            profile={"acme_enabled": enabled},
            garmin_has_core_error=False,
            garmin_tokenstore_exists=False,
        )
        return next(
            entry
            for entry in entries
            if (entry["provider"], entry["area"]) == (ACME_ID, ACME_AREA)
        )


def drain(case: AcmeOrchestrationCase) -> None:
    """Claim and run queued jobs until none is claimable, as the worker does."""
    while (job := case.store.claim()) is not None:
        case.executor.run(job)


def job_rows(case: AcmeOrchestrationCase) -> list[dict[str, Any]]:
    with case.database.unit_of_work() as db:
        rows = db.execute(
            "SELECT * FROM sync_jobs WHERE provider=? ORDER BY rowid",
            (ACME_ID,),
        ).fetchall()
    return [dict(row) for row in rows]


class AcmeSchedulingTests(AcmeOrchestrationCase):
    def test_startup_enqueues_acme_as_a_startup_refresh(self) -> None:
        policy = _Policy()

        self.startup_scheduler({ACME_ID: policy}).schedule()

        rows = job_rows(self)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["requested_by"], "startup")
        self.assertEqual(
            json.loads(rows[0]["payload"]), {"days": 14, "reason": "startup"}
        )
        self.assertEqual(policy.refresh_calls, [("startup", "startup")])

    def test_daily_scheduler_honours_the_marker_interval_and_active_jobs(self) -> None:
        policy = _Policy()
        scheduler = self.daily_scheduler({ACME_ID: policy})

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

    def test_startup_and_daily_order_follow_the_registry_ranks(self) -> None:
        daily_log: list[str] = []
        startup_log: list[str] = []
        ids = [descriptor.provider_id for descriptor in REGISTRY.all()]

        self.daily_scheduler(
            {pid: _RecordingPolicy(pid, daily_log) for pid in ids}
        ).schedule()
        self.startup_scheduler(
            {pid: _RecordingPolicy(pid, startup_log) for pid in ids}
        ).schedule()

        self.assertEqual(daily_log, list(REGISTRY.daily_order()))
        self.assertEqual(startup_log, list(REGISTRY.startup_order()))
        self.assertEqual(daily_log[-1], ACME_ID)
        self.assertEqual(startup_log[-1], ACME_ID)
        self.assertEqual(job_rows(self), [], "order probes enqueue nothing")


class AcmeQueueAndExecutionTests(AcmeOrchestrationCase):
    def test_queue_normalizes_the_payload_before_persisting_it(self) -> None:
        self.queue.enqueue(
            ACME_ID,
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

    @unittest.expectedFailure
    def test_queue_enforces_the_provider_period_limit(self) -> None:
        """Known production gap, not patched here.

        ``_normalize_refresh_days`` (backend/sync/jobs.py) bounds ``days`` by a
        fixed 3660 for every provider. The descriptor's ``max_sync_days`` (60 for
        acme) is only enforced by ``SyncStateRepository.set_sync_period``. A job
        that bypasses that setter (``POST /api/sync/jobs``, Coach refresh through
        ``queue.enqueue``) is therefore accepted above the provider limit.
        """
        error = self.rejection({"days": 61, "reason": "too long"})

        self.assertEqual(error.status, 400)
        self.assertEqual(job_rows(self), [])

    def rejection(self, payload: dict[str, Any]) -> AppError:
        with self.assertRaises(AppError) as raised:
            self.queue.enqueue(ACME_ID, "refresh", payload, requested_by="user")
        return raised.exception

    def test_executor_runs_the_normalized_payload_through_the_acme_owner(self) -> None:
        self.queue.enqueue(
            ACME_ID, "refresh", {"days": "7", "reason": "manual"}, requested_by="user"
        )

        drain(self)

        self.assertEqual(len(self.owner.calls), 1)
        call = self.owner.calls[0]
        self.assertEqual(call["payload"], {"days": 7, "reason": "manual"})
        self.assertEqual(call["job_type"], "refresh")
        self.assertEqual(job_rows(self)[0]["status"], "completed")


class AcmeFreshnessAndStatusTests(AcmeOrchestrationCase):
    def test_freshness_moves_from_never_loaded_to_fresh_then_stale(self) -> None:
        self.assertEqual(self.acme_freshness()["state"], "never_loaded")

        self.queue.enqueue(
            ACME_ID, "refresh", {"days": 7, "reason": "manual"}, requested_by="user"
        )
        self.clock.advance(60)
        drain(self)
        success_at = self.clock.current.isoformat()

        fresh = self.acme_freshness()
        self.assertEqual(fresh["state"], "fresh")
        self.assertTrue(fresh["configured"])
        self.assertTrue(fresh["read_only"])
        self.assertEqual(fresh["last_success_at"], success_at)
        self.assertTrue(fresh["has_last_good"])

        self.clock.advance(3 * 24 * 60 * 60)
        stale = self.acme_freshness()
        self.assertEqual(stale["state"], "stale")
        self.assertTrue(stale["stale"])

    def test_disabled_provider_is_reported_as_not_configured(self) -> None:
        entry = self.acme_freshness(enabled=False)

        self.assertEqual(entry["state"], "not_configured")
        self.assertFalse(entry["configured"])

    def test_status_json_reports_the_acme_job_and_its_freshness(self) -> None:
        handler = Mock()
        handler.read_json.return_value = {"days": 7}
        handler.path = MANUAL_PATH
        self.post_route.handle(handler, MANUAL_PATH)
        self.clock.advance(30)
        drain(self)

        status_handler = Mock()
        status_handler.path = "/api/sync/status"
        self.assertTrue(self.get_routes.handle(status_handler, "/api/sync/status"))

        status_code, payload = status_handler.send_json.call_args.args
        self.assertEqual(status_code, 200)
        acme_jobs = [job for job in payload["jobs"] if job["provider"] == ACME_ID]
        self.assertEqual([job["status"] for job in acme_jobs], ["completed"])
        acme_entries = [
            entry
            for entry in payload["provider_freshness"]
            if (entry["provider"], entry["area"]) == (ACME_ID, ACME_AREA)
        ]
        self.assertEqual([entry["state"] for entry in acme_entries], ["fresh"])


class AcmeHttpRouteTests(AcmeOrchestrationCase):
    def test_manual_route_enqueues_a_user_refresh_and_answers_202(self) -> None:
        handler = Mock()
        handler.read_json.return_value = {"days": 7}

        self.assertTrue(self.post_route.handle(handler, MANUAL_PATH))

        status_code, body = handler.send_json.call_args.args
        self.assertEqual(status_code, 202)
        rows = job_rows(self)
        self.assertEqual([row["id"] for row in rows], [body["id"]])
        self.assertEqual(rows[0]["requested_by"], "user")
        self.assertEqual(
            json.loads(rows[0]["payload"]), {"days": 7, "reason": "manual"}
        )
        self.period_state.set_sync_period.assert_called_once_with(ACME_ID, 7, -1)

    def test_manual_route_refuses_an_out_of_range_period_before_queueing(self) -> None:
        handler = Mock()
        handler.read_json.return_value = {"days": 99}

        with self.assertRaises(AppError) as raised:
            self.post_route.handle(handler, MANUAL_PATH)

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(str(raised.exception), PERIOD_MESSAGE)
        self.assertEqual(job_rows(self), [])

    def test_unconfigured_provider_is_refused_with_409(self) -> None:
        self.full_resync.provider_configured.return_value = False
        handler = Mock()
        handler.read_json.return_value = {"days": 7}

        with self.assertRaises(AppError) as raised:
            self.post_route.handle(handler, MANUAL_PATH)

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.reason, "not_configured")
        self.assertEqual(str(raised.exception), NOT_CONFIGURED_MESSAGE)
        self.assertEqual(job_rows(self), [])

    def test_route_for_an_undeclared_acme_path_is_not_handled(self) -> None:
        handler = Mock()

        self.assertFalse(self.post_route.handle(handler, "/api/acme-mock/other"))
        handler.send_json.assert_not_called()


class AcmeCoachRefreshTests(AcmeOrchestrationCase):
    def test_coach_target_enum_lists_acme_last_and_the_default_registry_does_not(
        self,
    ) -> None:
        targets = request_target_enum(REGISTRY)

        self.assertEqual(targets[0], "local")
        self.assertEqual(targets[-1], ACME_ID)
        self.assertNotIn(ACME_ID, request_target_enum(DEFAULT_PROVIDER_REGISTRY))

    def test_coach_refresh_enqueues_asynchronously_by_default(self) -> None:
        result = self.refresh.start(ACME_ID, {"days": 7, "reason": "coach"})

        self.assertEqual(result["status"], "queued")
        self.assertTrue(result["ok"])
        rows = job_rows(self)
        self.assertEqual([row["id"] for row in rows], [result["sync_job_id"]])
        self.assertEqual(rows[0]["requested_by"], "coach")
        self.synchronous.refresh.assert_not_called()

    def test_coach_refresh_waits_for_the_synchronous_refresh_when_asked(self) -> None:
        result = self.refresh.start(
            ACME_ID, {"days": 7, "reason": "coach", "_wait_for_completion": True}
        )

        self.assertEqual(result, {"ok": True, "status": "completed"})
        self.synchronous.refresh.assert_called_once()
        self.assertEqual(job_rows(self), [])

    def test_coach_wait_without_a_synchronous_refresh_is_refused(self) -> None:
        service = ProviderRefreshCommandService(
            self.queue, Mock(), -1, synchronous_refreshes={}
        )

        with self.assertRaises(AppError) as raised:
            service.start(ACME_ID, {"days": 7, "_wait_for_completion": True})

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(job_rows(self), [])

    def test_coach_refresh_rejects_unknown_fields_without_queueing(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.refresh.start(ACME_ID, {"bogus": 1})

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(job_rows(self), [])


class AcmePerformanceRefreshGapTests(AcmeOrchestrationCase):
    @unittest.expectedFailure
    def test_performance_refresh_single_flight_applies_to_any_provider(self) -> None:
        """Known production gap, not patched here.

        ``SyncJobStore.enqueue`` (backend/sync/jobs.py) deduplicates an active
        ``performance_refresh`` only for ``provider='intervals'``, so a second
        acme request creates a second job. This test declares the acme job type and
        expects the dedup a registry-driven provider should get; it fails until the
        single-flight scope is derived from the registry.
        """
        registry = ProviderRegistry(
            (
                *DEFAULT_PROVIDER_REGISTRY.all(),
                acceptance_descriptor(
                    job_types=frozenset({"refresh", "performance_refresh"})
                ),
            )
        )
        identifiers = iter(f"perf-{index}" for index in range(1, 50))
        store = SyncJobStore(
            self.database,
            self.clock.iso,
            lambda: next(identifiers),
            registry=registry,
        )
        queue = SyncJobQueueService(
            store,
            self.publisher,
            self.gate,
            self.wake,
            all_sync_days=-1,
            daily_sync_markers=self.markers,
            registry=registry,
        )

        first = queue.enqueue(ACME_ID, "performance_refresh", {"reason": "manual"})
        second = queue.enqueue(ACME_ID, "performance_refresh", {"reason": "scheduled"})

        self.assertEqual(second["id"], first["id"])


class RegistryIsolationTests(AcmeOrchestrationCase):
    def test_default_registry_is_unchanged_by_the_acceptance_scenarios(self) -> None:
        self.assertEqual(DEFAULT_PROVIDER_REGISTRY.all(), DEFAULT_SNAPSHOT)
        self.assertNotIn(ACME_ID, [d.provider_id for d in DEFAULT_PROVIDER_DESCRIPTORS])
        self.assertNotIn(ACME_ID, DEFAULT_PROVIDER_REGISTRY.daily_order())


if __name__ == "__main__":
    unittest.main()
