"""Startup sync scheduling contract tests using isolated service fakes."""

from __future__ import annotations

import unittest
from datetime import date

from backend.sync.scheduler import StartupSyncScheduler, StartupSyncSchedulerConfig


class _Profile:
    def __init__(self, weather_location: str = "Synthetic city"):
        self.weather_location = weather_location
        self.reads = 0

    def get(self):
        self.reads += 1
        return {"weather_location": self.weather_location}


class _Queue:
    def __init__(self, active: set[tuple[str, str]] | None = None):
        self.active_jobs = active or set()
        self.active_checks = []
        self.jobs = []

    def active(self, provider: str, job_type: str) -> bool:
        self.active_checks.append((provider, job_type))
        return (provider, job_type) in self.active_jobs

    def enqueue(self, provider, job_type, payload, *, requested_by):
        self.jobs.append((provider, job_type, payload, requested_by))


class _Garmin:
    def __init__(self, configured: bool = True):
        self.is_configured = configured
        self.checks = 0

    def configured(self) -> bool:
        self.checks += 1
        return self.is_configured


class _SyncState:
    def __init__(self, cursors=None, period: int = 17):
        self.cursors = cursors or {}
        self.period = period
        self.cursor_reads = []
        self.period_reads = []

    def cursor(self, provider: str, stream: str):
        self.cursor_reads.append((provider, stream))
        return {"cursor": self.cursors.get(provider)}

    def sync_period(self, provider, defaults, all_days):
        self.period_reads.append((provider, defaults, all_days))
        return self.period


class StartupSyncSchedulerTests(unittest.TestCase):
    def make_scheduler(
        self,
        *,
        profile=None,
        queue=None,
        garmin=None,
        sync_state=None,
        calendar_enabled=True,
        intervals_enabled=True,
    ):
        self.profile = profile or _Profile()
        self.queue = queue or _Queue()
        self.garmin = garmin or _Garmin()
        self.sync_state = sync_state or _SyncState()
        return StartupSyncScheduler(
            self.profile,
            self.queue,
            self.garmin,
            self.sync_state,
            config=StartupSyncSchedulerConfig(
                calendar_enabled=calendar_enabled,
                intervals_enabled=intervals_enabled,
                garmin_automatic_sync_days=9,
                sync_period_defaults={"intervals": 90, "garmin": 30},
                all_sync_days=-1,
                sync_chunk_days=45,
                sync_earliest_date=date(2000, 1, 1),
            ),
        )

    def test_enqueues_all_provider_jobs_in_contract_order_with_exact_payloads(self):
        sync_state = _SyncState({"intervals": "2026-08-01", "garmin": None})
        scheduler = self.make_scheduler(sync_state=sync_state)

        scheduler.schedule()

        self.assertEqual(
            self.queue.jobs,
            [
                ("calendar", "refresh", {"reason": "startup"}, "startup"),
                ("intervals", "refresh", {"days": 17, "reason": "startup"}, "startup"),
                (
                    "intervals",
                    "historical_backfill",
                    {"days": 45, "reason": "startup historical backfill", "end_date": "2026-07-31"},
                    "startup",
                ),
                ("garmin", "refresh", {"days": 9, "reason": "startup"}, "startup"),
                (
                    "garmin",
                    "historical_backfill",
                    {"days": 45, "reason": "startup historical backfill"},
                    "startup",
                ),
                ("weather", "refresh", {"force": True, "reason": "startup"}, "startup"),
            ],
        )
        self.assertEqual(
            sync_state.cursor_reads,
            [("intervals", "historical"), ("garmin", "historical")],
        )
        self.assertEqual(sync_state.period_reads[0][0], "intervals")

    def test_does_not_duplicate_any_active_refresh_or_backfill(self):
        active_jobs = {
            (provider, kind)
            for provider, kinds in {
                "calendar": ("refresh",),
                "intervals": ("refresh", "historical_backfill"),
                "garmin": ("refresh", "historical_backfill"),
                "weather": ("refresh",),
            }.items()
            for kind in kinds
        }
        sync_state = _SyncState()
        scheduler = self.make_scheduler(
            queue=_Queue(active_jobs),
            sync_state=sync_state,
        )

        scheduler.schedule()

        self.assertEqual(self.queue.jobs, [])
        self.assertEqual(
            self.queue.active_checks,
            [
                ("calendar", "refresh"),
                ("intervals", "refresh"),
                ("intervals", "historical_backfill"),
                ("garmin", "refresh"),
                ("garmin", "historical_backfill"),
                ("weather", "refresh"),
            ],
        )
        self.assertEqual(sync_state.cursor_reads, [])

    def test_skips_disabled_providers_and_unconfigured_garmin(self):
        garmin = _Garmin(False)
        scheduler = self.make_scheduler(
            profile=_Profile(""),
            garmin=garmin,
            calendar_enabled=False,
            intervals_enabled=False,
        )

        scheduler.schedule()

        self.assertEqual(self.queue.jobs, [])
        self.assertEqual(garmin.checks, 1)
        self.assertEqual(self.sync_state.cursor_reads, [])

    def test_cursor_date_and_earliest_boundary_contract(self):
        cases = (
            (None, {"days": 45, "reason": "startup historical backfill"}),
            ("not-a-date", {"days": 45, "reason": "startup historical backfill"}),
            ("2026-08-01T12:30:00", {"days": 45, "reason": "startup historical backfill", "end_date": "2026-07-31"}),
        )
        for cursor, expected in cases:
            with self.subTest(cursor=cursor):
                sync_state = _SyncState({"intervals": cursor})
                scheduler = self.make_scheduler(
                    calendar_enabled=False,
                    intervals_enabled=True,
                    garmin=_Garmin(False),
                    sync_state=sync_state,
                )
                scheduler.schedule()
                historical = next(
                    job for job in self.queue.jobs if job[1] == "historical_backfill"
                )
                self.assertEqual(historical[2], expected)

        for cursor in ("2000-01-01", "1999-12-31"):
            with self.subTest(cursor=cursor):
                scheduler = self.make_scheduler(
                    calendar_enabled=False,
                    intervals_enabled=True,
                    garmin=_Garmin(False),
                    sync_state=_SyncState({"intervals": cursor}),
                )
                scheduler.schedule()
                self.assertFalse(
                    any(job[1] == "historical_backfill" for job in self.queue.jobs)
                )


if __name__ == "__main__":
    unittest.main()
