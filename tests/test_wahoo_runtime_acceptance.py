"""Acceptance test: a connected Wahoo account through the real sync orchestration.

Recipe: temporary database, connected token state, a fake Wahoo HTTP transport.
The scheduler enqueues a Wahoo refresh, the executor runs the real owner, the
canonical activities carry ``wahoo`` with their local dates, freshness and the
status projection read "Wahoo", and a disconnect makes the next run skip with
the descriptor's not-configured message. It uses no network, no real ``.env``,
no data directory and no Wahoo account; every token is a placeholder.
"""

from __future__ import annotations

import json
import logging
import threading
import unittest
from datetime import date
from typing import Any
from unittest.mock import Mock

from backend.providers.descriptors import (
    WAHOO_ID,
    WAHOO_NOT_CONFIGURED_MESSAGE,
)
from backend.providers.wahoo_client import WahooClient
from backend.sync.daily import daily_marker_key
from backend.sync.executor import SyncJobExecutor, WahooJobAdapter
from backend.sync.freshness import ProviderFreshnessService
from backend.sync.freshness_sources import DEFAULT_FRESHNESS_SOURCES
from backend.sync.job_outcomes import SyncJobOutcomeService
from backend.sync.jobs import SyncJobStore
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
from backend.sync.queue import SyncJobQueueService
from backend.sync.schedule_policies import WahooSchedulePolicy
from backend.sync.scheduler import (
    DailySyncScheduler,
    DailySyncSchedulerConfig,
    StartupSyncScheduler,
    StartupSyncSchedulerConfig,
)
from backend.sync.status import SyncPublicStateService
from backend.sync.wahoo_connection import WAHOO_TOKENS_KEY, WahooConnectionService
from backend.sync.wahoo_sync import WahooSyncService
from tests.wahoo_sync_fixture import (
    EARLIER_UTC,
    LATE_EVENING_UTC,
    ZONE,
    WahooSyncCase,
    workout,
)

AUTO_UPDATE_LABEL = "stündliche automatische Aktualisierung"
REGISTRY = DEFAULT_PROVIDER_REGISTRY


class FakeWahooTransport:
    """Dispatches on the URL path like the Wahoo API, returning canned rows."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method: str, url: str, **_kwargs: Any) -> Any:
        self.calls.append((method, url))
        if "/v1/workouts" in url:
            return {"workouts": self.rows}
        raise AssertionError(f"unexpected Wahoo request: {method} {url}")


class WahooOrchestrationCase(WahooSyncCase):
    """Wire the real orchestration owners around the Wahoo sync owner."""

    def setUp(self) -> None:
        super().setUp()
        self.transport = FakeWahooTransport()
        self.oauth = Mock()
        self.connection_service = WahooConnectionService(
            config=lambda: self.config,
            oauth=lambda: self.oauth,
            database_manager=lambda: self.database,
            database_lock=threading.RLock,
            key_values=self.key_values,
            utc_now=lambda: self.now.isoformat(),
        )
        self.connect()
        self.service = WahooSyncService(
            config=lambda: self.config,
            connection=lambda: self.connection_service,
            source=lambda: WahooClient(
                request=self.transport,
                access_token=self.connection_service.access_token,
                refresh_access_token=self.connection_service.refresh_access_token,
            ),
            database_manager=lambda: self.database,
            database_lock=threading.RLock(),
            key_values=self.key_values,
            daily_markers=lambda: self.markers,
            observer=lambda: self.observer,
            registry=REGISTRY,
            zone_provider=lambda: ZONE,
            now=lambda: self.now,
            logger=self.logger,
            lock=threading.Lock(),
        )
        identifiers = iter(f"job-{index}" for index in range(1, 500))
        publisher = Mock()
        gate = self.gate
        wake = threading.Event()
        self.store = SyncJobStore(
            self.database,
            lambda: self.now.isoformat(),
            lambda: next(identifiers),
            registry=REGISTRY,
        )
        self.queue = SyncJobQueueService(
            self.store,
            publisher,
            gate,
            wake,
            all_sync_days=-1,
            daily_sync_markers=self.markers,
            registry=REGISTRY,
        )
        self.executor = SyncJobExecutor(
            historical_sync=Mock(),
            outcome_service=SyncJobOutcomeService(
                self.store,
                publisher,
                wake,
                lambda text: text,
                logging.getLogger("acceptance.wahoo"),
                lambda: self.now,
                retry_base_seconds=1,
                retry_max_seconds=60,
            ),
            all_sync_days=-1,
            job_owners={WAHOO_ID: WahooJobAdapter(sync=self.service)},
            registry=REGISTRY,
        )
        sync_state = Mock()
        sync_state.sync_period.return_value = 84
        self.policy = WahooSchedulePolicy(
            configured=self.wahoo_connected,
            sync_state=sync_state,
            sync_period_defaults={WAHOO_ID: 84},
            all_sync_days=-1,
        )
        self.freshness = ProviderFreshnessService(
            self.config,
            self.database,
            self.key_values,
            lambda: self.now,
            freshness_sources=DEFAULT_FRESHNESS_SOURCES,
            registry=REGISTRY,
        )
        profile = Mock()
        profile.get.return_value = {}
        garmin_state = Mock()
        garmin_state.core_error_entries.return_value = []
        state_versions = Mock()
        state_versions.versions.return_value = {}
        self.status = SyncPublicStateService(
            self.config,
            self.database,
            self.key_values,
            self.freshness,
            profile,
            garmin_state,
            gate,
            self.queue,
            state_versions,
            Mock(),
            running_probes={},
        )

    def connect(self) -> None:
        tokens = {
            "access_token": "access-placeholder",
            "refresh_token": "refresh-placeholder",
            "expires_at": "2026-12-01T00:00:00+00:00",
            "scope": "workouts_read",
            "connected_at": self.now.isoformat(),
        }
        with self.database.unit_of_work() as db:
            self.key_values.set(db, WAHOO_TOKENS_KEY, json.dumps(tokens))

    def wahoo_connected(self) -> bool:
        status = self.connection_service.status()
        return bool(status["configured"] and status["connected"])

    def _daily_scheduler(self) -> DailySyncScheduler:
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
            schedule_policies={WAHOO_ID: self.policy},
            registry=REGISTRY,
        )

    def _startup_scheduler(self) -> StartupSyncScheduler:
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
            schedule_policies={WAHOO_ID: self.policy},
            registry=REGISTRY,
        )

    def _drain(self) -> None:
        while (job := self.store.claim()) is not None:
            self.executor.run(job)

    def _jobs(self) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT * FROM sync_jobs WHERE provider = ? ORDER BY rowid", (WAHOO_ID,)
        )

    def _wahoo_freshness(self) -> dict[str, Any]:
        entries = self.freshness.current(
            profile={}, garmin_has_core_error=False, garmin_tokenstore_exists=False
        )
        return next(entry for entry in entries if entry["provider"] == WAHOO_ID)


class WahooAcceptanceTests(WahooOrchestrationCase):
    def test_connected_account_flows_from_the_scheduler_to_the_status(self) -> None:
        self.transport.rows = [
            workout(1, LATE_EVENING_UTC),
            workout(2, EARLIER_UTC),
        ]
        self.assertEqual("never_loaded", self._wahoo_freshness()["state"])

        self._startup_scheduler().schedule()

        jobs = self._jobs()
        self.assertEqual(["startup"], [job["requested_by"] for job in jobs])
        self.assertEqual(
            {"days": 84, "reason": "startup"}, json.loads(jobs[0]["payload"])
        )

        self.advance(minutes=1)
        self._drain()

        self.assertEqual(["completed"], [job["status"] for job in self._jobs()])
        rows = self._activity_rows()
        self.assertEqual({"wahoo"}, {row["provider"] for row in rows})
        self.assertEqual(
            ["2026-10-12", "2026-10-10"], [row["local_date"] for row in rows]
        )
        self.assertIsNotNone(self._marker())
        self.assertEqual(["success"], self.refresh_statuses())

        entry = self._wahoo_freshness()
        self.assertEqual("fresh", entry["state"])
        self.assertEqual("Wahoo", entry["label"])
        self.assertTrue(entry["configured"])
        self.assertTrue(entry["read_only"])

        state = self.status.state()
        self.assertEqual(
            ["fresh"],
            [
                item["state"]
                for item in state["provider_freshness"]
                if item["provider"] == WAHOO_ID
            ],
        )
        self.assertEqual(
            ["completed"],
            [job["status"] for job in state["jobs"] if job["provider"] == WAHOO_ID],
        )

    def test_daily_scheduler_honours_the_marker_interval(self) -> None:
        scheduler = self._daily_scheduler()

        scheduler.schedule()
        self.assertEqual(1, len(self._jobs()))
        self._drain()
        scheduler.schedule()
        self.assertEqual(1, len(self._jobs()), "the marker is not due within an hour")

        self.advance(seconds=4300)
        scheduler.schedule()
        rows = self._jobs()
        self.assertEqual(2, len(rows))
        self.assertEqual(
            {"days": 84, "reason": AUTO_UPDATE_LABEL}, json.loads(rows[1]["payload"])
        )
        self.assertTrue(self._value(daily_marker_key(WAHOO_ID)))

    def test_disconnect_makes_the_next_run_skip_with_the_descriptor_message(
        self,
    ) -> None:
        self.transport.rows = [workout(1, EARLIER_UTC)]
        self._startup_scheduler().schedule()
        self._drain()
        calls_before = len(self.transport.calls)
        stored = self._activity_rows()

        self.connection_service.disconnect()
        self.advance(hours=2)
        self.assertFalse(self.wahoo_connected())
        self._startup_scheduler().schedule()
        self.assertEqual(1, len(self._jobs()), "an unconnected account is not queued")
        self.queue.enqueue(
            WAHOO_ID,
            "refresh",
            {"days": 7, "reason": "manual"},
            requested_by="user",
        )
        self._drain()

        self.assertEqual(calls_before, len(self.transport.calls))
        self.assertEqual(stored, self._activity_rows(), "stored activities are kept")
        self.assertEqual(
            {"status": "not_configured", "message": WAHOO_NOT_CONFIGURED_MESSAGE},
            self.executor.execute(self._jobs()[-1]),
        )
        self.assertEqual(calls_before, len(self.transport.calls))
        self.assertEqual("skipped", self.refresh_statuses()[-1])
        self.assertEqual("not_configured", self._wahoo_freshness()["state"])

    def test_the_owner_never_writes_to_wahoo(self) -> None:
        self.transport.rows = [workout(1, EARLIER_UTC)]
        self._startup_scheduler().schedule()
        self._drain()

        self.assertEqual({"GET"}, {method for method, _url in self.transport.calls})


if __name__ == "__main__":
    unittest.main()
