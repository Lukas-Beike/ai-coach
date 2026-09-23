"""Isolated daily scheduler decision and gate regressions."""

from __future__ import annotations

import threading
import unittest
from contextlib import contextmanager

from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.gates import ProviderResyncGate
from backend.sync.scheduler import DailySyncScheduler


class _Profile:
    def __init__(self, location: str = "Synthetic city"):
        self.location = location

    def get(self):
        return {"weather_location": self.location}


class _Queue:
    def __init__(self, active: set[str] | None = None):
        self.active_providers = active or set()
        self.jobs = []

    def active(self, provider: str) -> bool:
        return provider in self.active_providers

    def enqueue(self, provider, job_type, payload, *, requested_by):
        self.jobs.append((provider, job_type, payload, requested_by))


class _Markers:
    def __init__(self, due: dict[str, bool] | None = None):
        self.due = due or {"calendar": True, "garmin": True, "intervals": True}
        self.checked = []

    def is_due(self, provider: str) -> bool:
        self.checked.append(provider)
        return self.due.get(provider, False)


class _Garmin:
    def __init__(self, configured: bool = True):
        self.is_configured = configured

    def configured(self) -> bool:
        return self.is_configured


class _Database:
    @contextmanager
    def unit_of_work(self):
        yield object()


class _KeyValues:
    def __init__(self, sync_running: str | None = None):
        self.sync_running = sync_running

    def get(self, _db, key: str) -> str | None:
        return self.sync_running if key == "sync_running" else None


class _SyncState:
    def __init__(self, period: int = 14):
        self.period = period

    def sync_period(self, _provider, _defaults, _all_days) -> int:
        return self.period


class DailySyncSchedulerTests(unittest.TestCase):
    def make_scheduler(
        self,
        *,
        profile=None,
        queue=None,
        markers=None,
        garmin=None,
        sync_running=None,
        reset_gate=None,
        maintenance_gate=None,
        calendar_enabled=True,
        intervals_enabled=True,
    ):
        self.queue = queue or _Queue()
        self.markers = markers or _Markers()
        return DailySyncScheduler(
            profile or _Profile(),
            self.queue,
            self.markers,
            garmin or _Garmin(),
            _Database(),
            _KeyValues(sync_running),
            threading.Lock(),
            _SyncState(),
            reset_gate or ProviderResyncGate("Intervals.icu"),
            maintenance_gate or MaintenanceGate(),
            calendar_url_enabled=calendar_enabled,
            intervals_key_enabled=intervals_enabled,
            garmin_automatic_sync_days=2,
            auto_update_label="automatic refresh",
            sync_period_defaults={"intervals": 90, "garmin": 30},
            all_sync_days=-1,
        )

    def test_enqueues_due_jobs_in_order_with_existing_payloads(self):
        scheduler = self.make_scheduler()

        scheduler.schedule()

        self.assertEqual(
            self.queue.jobs,
            [
                ("weather", "refresh", {"force": False, "reason": "automatic refresh"}, "scheduler"),
                ("calendar", "refresh", {"reason": "automatic refresh"}, "scheduler"),
                ("garmin", "refresh", {"days": 2, "reason": "automatic refresh"}, "scheduler"),
                ("intervals", "refresh", {"days": 14, "reason": "automatic refresh"}, "scheduler"),
            ],
        )

    def test_skips_disabled_or_unconfigured_providers_before_marker_checks(self):
        scheduler = self.make_scheduler(
            profile=_Profile(""),
            garmin=_Garmin(False),
            calendar_enabled=False,
            intervals_enabled=False,
        )

        scheduler.schedule()

        self.assertEqual(self.queue.jobs, [])
        self.assertEqual(self.markers.checked, [])

    def test_skips_active_jobs_and_not_due_markers(self):
        queue = _Queue({"weather", "calendar", "garmin"})
        markers = _Markers({"calendar": True, "garmin": True, "intervals": False})
        scheduler = self.make_scheduler(queue=queue, markers=markers)

        scheduler.schedule()

        self.assertEqual(self.queue.jobs, [])
        self.assertEqual(markers.checked, ["calendar", "garmin", "intervals"])

    def test_intervals_is_skipped_while_syncing_resetting_or_active(self):
        for kwargs in (
            {"sync_running": "1"},
            {"reset_gate": self._resetting_gate()},
            {"queue": _Queue({"intervals"})},
        ):
            with self.subTest(kwargs=kwargs):
                scheduler = self.make_scheduler(**kwargs)
                scheduler.schedule()
                self.assertNotIn("intervals", [job[0] for job in self.queue.jobs])

    def _resetting_gate(self):
        gate = ProviderResyncGate("Intervals.icu")
        self.assertTrue(gate.begin_reset())
        self.addCleanup(gate.end_reset)
        return gate

    def test_maintenance_gate_prevents_scheduling(self):
        gate = MaintenanceGate()
        scheduler = self.make_scheduler(maintenance_gate=gate)

        with gate.restore(), self.assertRaises(AppError) as raised:
            scheduler.schedule()

        self.assertEqual(raised.exception.reason, "maintenance")
        self.assertEqual(self.queue.jobs, [])


if __name__ == "__main__":
    unittest.main()
