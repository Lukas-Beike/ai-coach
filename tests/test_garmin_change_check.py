"""The light Garmin change check through the Personal API (#2303).

The check reads a mocked Personal API and a temporary database; it never
reaches a real Garmin account.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from typing import Any, cast
from unittest.mock import Mock

from support import temp_database

from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.providers import http as provider_http
from backend.providers.garmin_morning import has_night
from backend.sync.daily import DailySyncMarkerService
from backend.sync.garmin import GarminPayloadService
from backend.sync.garmin_change_check import GarminChangeCheck
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter
from backend.sync.schedule_policies import GarminSchedulePolicy
from backend.sync.state import SyncStateRepository

ZONE = timezone(timedelta(hours=1))
TODAY = date(2026, 11, 12)
NOW = "2026-11-12T09:00:00+00:00"


def _activity(activity_id: int, day: date = TODAY) -> dict[str, Any]:
    return {
        "activityId": activity_id,
        "activityName": "Synthetic run",
        "activityType": {"typeKey": "running"},
        "startTimeLocal": f"{day.isoformat()} 07:00:00",
        "duration": 1800.0,
    }


def _night(day: date = TODAY, seconds: int | None = 27000) -> dict[str, Any]:
    return {
        "calendarDate": day.isoformat(),
        "dailySleepDTO": {"calendarDate": day.isoformat(), "sleepTimeSeconds": seconds},
    }


class _Personal:
    """Personal API stand-in: only the two change-marker reads exist on it."""

    def __init__(self) -> None:
        self.activity_ids = ["900001"]
        self.nights: list[dict[str, Any]] = []
        self.calls: list[str] = []
        self.error: Exception | None = None
        self.release: threading.Event | None = None
        self.reading = threading.Event()

    def newest_activity_ids(self, start: str, end: str) -> list[str]:
        self.calls.append("activities")
        self.reading.set()
        if self.release is not None:
            self.release.wait(5)
        if self.error is not None:
            raise self.error
        return list(self.activity_ids)

    def get_sleep_daily(self, start: str, end: str) -> list[dict[str, Any]]:
        self.calls.append("sleep")
        return list(self.nights)


class GarminChangeCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = temp_database(self, "test.sqlite3", row_factory=sqlite3.Row)
        self.key_values = KeyValueRepository(lambda: NOW)
        with self.database.unit_of_work() as db:
            initialize_schema(db)
        self.local = datetime(2026, 11, 12, 10, 0, tzinfo=ZONE)
        self.mono = 1000.0
        self.payload = GarminPayloadService(
            self.database,
            self.key_values,
            SyncStateRepository(self.database, self.key_values, lambda: NOW),
            lambda: self.local.date(),
        )
        self.markers = DailySyncMarkerService(
            self.database, self.key_values, lambda: self.local
        )
        self.personal = _Personal()
        self.keyed = True
        self.logger = Mock(spec=logging.Logger)
        self.check = GarminChangeCheck(
            personal=lambda: cast(Any, self.personal) if self.keyed else None,
            known_activity_ids=self.payload.known_activity_ids,
            stored_sleep=lambda day: self.payload.view(
                ["sleep"], start=day.isoformat(), end=day.isoformat()
            ).get("sleep"),
            last_refresh=lambda: self.markers.last_success("garmin"),
            local_now=lambda: self.local,
            logger=self.logger,
            monotonic=lambda: self.mono,
        )
        self.store(activities=[_activity(900001)], sleep=[_night()])
        self.markers.mark("garmin", self.local.replace(hour=6))

    def store(self, **sections: Any) -> None:
        """Store sections as a refresh does, outside the check."""
        with self.database.unit_of_work() as db:
            GarminSnapshotWriter(self.key_values, lambda: ZONE).write(
                db, {"synced_at": NOW, **sections}
            )

    def due(self) -> bool:
        """Ask the check as the scheduler does, with the hourly attempt marker."""
        return self.check.refresh_due(lambda: self.markers.is_due("garmin", self.local))

    def ticks(self, start: datetime, minutes: int) -> list[bool]:
        """Ask the check every 5 minutes, like the daily loop."""
        answers = []
        for step in range(0, minutes, 5):
            self.local = start + timedelta(minutes=step)
            answers.append(self.due())
            self.mono += 300
        return answers

    def test_unchanged_garmin_checks_every_10_minutes_by_day_and_30_at_night(
        self,
    ) -> None:
        by_day = self.ticks(datetime(2026, 11, 12, 10, 0, tzinfo=ZONE), 60)
        day_reads = len(self.personal.calls)
        at_night = self.ticks(datetime(2026, 11, 12, 23, 0, tzinfo=ZONE), 60)

        self.assertEqual([False] * 24, by_day + at_night)
        # Every read is a Personal change marker; the stored night skips sleep.
        self.assertEqual(["activities"] * 8, self.personal.calls)
        self.assertEqual((6, 2), (day_reads, len(self.personal.calls) - day_reads))
        self.assertEqual(
            {"checks": 8, "changes": 0, "throttled": 0, "failed": 0},
            self.check.counts,
        )

    def test_a_new_activity_makes_the_refresh_due_until_it_is_stored(self) -> None:
        self.assertFalse(self.due())
        self.personal.activity_ids.insert(0, "900002")
        self.mono += 600

        self.assertTrue(self.due())
        self.store(activities=[_activity(900002)])
        self.mono += 600
        self.assertFalse(self.due())
        self.assertEqual(1, self.check.counts["changes"])

    def test_a_change_the_refresh_does_not_store_returns_hourly(self) -> None:
        self.personal.activity_ids.insert(0, "900003")
        self.assertTrue(self.due())
        self.mono += 600
        # Still queued or failed: no successful refresh since, so it stays due.
        self.assertTrue(self.due())

        self.local += timedelta(minutes=20)
        self.markers.mark("garmin", self.local)
        for _ in range(3):
            self.mono += 600
            self.local += timedelta(minutes=10)
            self.assertFalse(self.due())
        # An hour after it was held back it is reported again, the old pace.
        self.mono += 2400
        self.assertTrue(self.due())
        self.store(activities=[_activity(900003)])
        self.personal.activity_ids.insert(0, "900004")
        self.mono += 600
        self.assertTrue(self.due())

    def test_a_new_night_makes_the_refresh_due_and_morning_waits_for_it(self) -> None:
        self.local = datetime(2026, 11, 13, 6, 0, tzinfo=ZONE)
        self.assertFalse(self.due())
        self.assertEqual(["activities", "sleep"], self.personal.calls)
        self.assertFalse(self.check.morning_due())

        # Garmin publishes an empty entry first, then the night.
        self.personal.nights = [_night(self.local.date(), None)]
        self.mono += 600
        self.assertFalse(self.due())
        self.personal.nights = [_night(self.local.date())]
        self.mono += 600
        self.assertTrue(self.due())

        self.store(sleep=[_night(self.local.date())])
        self.assertTrue(self.check.morning_due())
        self.mono += 600
        self.personal.calls.clear()
        self.assertFalse(self.due())
        self.assertEqual(["activities"], self.personal.calls)

    def test_retry_after_delays_the_next_check(self) -> None:
        self.personal.error = provider_http.ProviderHTTPError(
            "garmin", "rate_limited", 429, retry_after=3600.0
        )
        self.assertFalse(self.due())
        self.personal.error = None

        for minutes in (10, 30, 59):
            self.mono = 1000.0 + minutes * 60
            self.assertFalse(self.due())
        self.assertEqual(1, len(self.personal.calls))
        self.mono = 1000.0 + 3600
        self.due()
        self.assertEqual(2, len(self.personal.calls))
        self.assertEqual(1, self.check.counts["throttled"])

    def test_failures_back_off_and_a_rejected_key_surfaces_through_the_refresh(
        self,
    ) -> None:
        self.personal.error = OSError("synthetic outage")
        self.assertFalse(self.due())
        self.mono += 600
        self.assertFalse(self.due())
        self.assertEqual(1, len(self.personal.calls))
        self.mono += 600

        # A rejected key or endpoint queues the refresh, at the backoff pace.
        self.personal.error = provider_http.ProviderHTTPError(
            "garmin", "authentication", 403
        )
        self.assertTrue(self.due())
        self.mono += 1200
        self.assertFalse(self.due())
        self.assertEqual(2, len(self.personal.calls))
        self.assertEqual(2, self.check.counts["failed"])

    def test_a_local_database_error_is_no_garmin_failure(self) -> None:
        def maintenance(_days: int) -> list[str]:
            raise AppError(503, "maintenance", reason="maintenance")

        self.check._known_activity_ids = maintenance
        with self.assertRaises(AppError):
            self.due()
        self.assertEqual(0, self.check.counts["failed"])

    def test_one_full_refresh_per_day_is_due_from_noon_without_a_remote_read(
        self,
    ) -> None:
        self.local = datetime(2026, 11, 13, 11, 55, tzinfo=ZONE)
        self.personal.nights = []
        self.assertFalse(self.due())
        self.personal.calls.clear()

        self.local = datetime(2026, 11, 13, 12, 0, tzinfo=ZONE)
        self.assertTrue(self.due())
        self.assertTrue(self.check.morning_due())
        self.assertEqual([], self.personal.calls)
        # The queued refresh ended without today's success: hourly, not every pass.
        self.markers.mark_attempt("garmin", self.local)
        self.local += timedelta(minutes=5)
        self.mono += 600
        self.assertFalse(self.due())
        self.local += timedelta(minutes=55)
        self.assertTrue(self.due())
        self.markers.mark("garmin", self.local)
        self.mono += 600
        self.assertFalse(self.due())

    def test_a_night_is_found_under_either_garmin_alias(self) -> None:
        flat = {"summaryDate": TODAY.isoformat(), "sleepDuration": 27000}
        self.assertTrue(has_night([flat], TODAY))
        self.assertFalse(has_night([{**flat, "sleepDuration": 0}], TODAY))
        self.assertFalse(has_night([flat], TODAY + timedelta(days=1)))

    def test_without_a_personal_key_the_hourly_marker_and_morning_polling_stay(
        self,
    ) -> None:
        self.keyed = False
        policy = GarminSchedulePolicy(Mock(), 2, None, self.check)

        self.assertTrue(self.check.morning_due())
        self.assertTrue(policy.refresh_due(lambda: True))
        self.assertFalse(policy.refresh_due(lambda: False))

    def test_a_slow_check_never_delays_a_foreground_write(self) -> None:
        # The check reads remotely outside any database lease (#2287 style):
        # a login waiting for the writer gets it while Garmin is slow.
        self.personal.release = threading.Event()
        worker = threading.Thread(target=self.due)
        worker.start()
        self.addCleanup(worker.join, 5)
        self.assertTrue(self.personal.reading.wait(5))
        with self.database.unit_of_work(timeout=1.0) as db:
            self.key_values.set(db, "synthetic_login", "1")
        self.personal.release.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
