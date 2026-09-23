"""Tests for manual morning check-in preparation."""

from __future__ import annotations

import logging
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from backend.coach.morning import (
    ManualMorningCheckinService,
    MorningCheckinStateService,
)
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.sync.garmin_service import GARMIN_AUTOMATIC_SYNC_DAYS

TODAY = date(2026, 9, 23)


class ManualMorningCheckinServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.garmin_sync = Mock()
        self.garmin_payload = Mock()
        self.morning_battery = Mock()
        self.local_today = Mock(return_value=TODAY)
        self.logger = Mock(spec=logging.Logger)
        self.service = ManualMorningCheckinService(
            self.garmin_sync,
            self.garmin_payload,
            self.morning_battery,
            self.local_today,
            self.logger,
        )

    def test_unconfigured_garmin_returns_without_reading_or_refreshing(self) -> None:
        self.garmin_sync.configured.return_value = False

        self.service.prepare()

        self.local_today.assert_not_called()
        self.garmin_sync.sync.assert_not_called()
        self.garmin_payload.snapshot.assert_not_called()
        self.morning_battery.refresh.assert_not_called()

    def test_fresh_sleep_syncs_then_refreshes_battery(self) -> None:
        events: list[str] = []
        self.garmin_sync.configured.return_value = True
        self.garmin_sync.sync.side_effect = lambda **_: events.append("sync")
        self.garmin_payload.snapshot.side_effect = lambda: (
            events.append("snapshot")
            or {"sleep": [{"calendarDate": TODAY.isoformat()}]}
        )
        self.morning_battery.refresh.side_effect = lambda day: events.append(
            f"battery:{day.isoformat()}"
        )

        self.service.prepare()

        self.garmin_sync.sync.assert_called_once_with(
            days=GARMIN_AUTOMATIC_SYNC_DAYS,
            reason="Morgen-Check-in",
            wait_for_existing=True,
        )
        self.morning_battery.refresh.assert_called_once_with(TODAY)
        self.assertEqual(events, ["sync", "snapshot", "battery:2026-09-23"])

    def test_missing_or_stale_sleep_raises_without_refreshing_battery(self) -> None:
        for snapshot in (
            {},
            {"sleep": [{"calendarDate": (TODAY - timedelta(days=1)).isoformat()}]},
        ):
            with self.subTest(snapshot=snapshot):
                self.garmin_payload.snapshot.return_value = snapshot
                self.morning_battery.refresh.reset_mock()

                with self.assertRaises(AppError) as raised:
                    self.service.prepare()

                self.assertEqual(raised.exception.status, 503)
                self.assertEqual(raised.exception.reason, "garmin_sleep_not_ready")
                self.morning_battery.refresh.assert_not_called()

    def test_sync_failure_logs_and_stale_snapshot_still_blocks(self) -> None:
        self.garmin_sync.sync.side_effect = RuntimeError("provider unavailable")
        self.garmin_payload.snapshot.return_value = {}

        with self.assertRaises(AppError) as raised:
            self.service.prepare()

        self.assertEqual(raised.exception.reason, "garmin_sleep_not_ready")
        self.logger.warning.assert_called_once_with(
            "Morning Garmin synchronization failed",
            extra={"event": "morning_garmin_sync_failed"},
            exc_info=True,
        )
        self.morning_battery.refresh.assert_not_called()

    def test_sync_failure_with_fresh_snapshot_logs_then_refreshes(self) -> None:
        self.garmin_sync.sync.side_effect = RuntimeError("provider unavailable")
        self.garmin_payload.snapshot.return_value = {
            "sleep": [{"calendarDate": TODAY.isoformat()}]
        }

        self.service.prepare()

        self.logger.warning.assert_called_once()
        self.morning_battery.refresh.assert_called_once_with(TODAY)


class MorningCheckinStateServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.database = DatabaseManager(
            Path(temporary_directory.name) / "test.sqlite3",
            sqlite3,
            row_factory=sqlite3.Row,
        )
        self.addCleanup(self.database.close)
        self.key_values = KeyValueRepository(lambda: "2026-09-23T12:00:00")
        with self.database.unit_of_work() as db:
            initialize_schema(db)
        self.service = MorningCheckinStateService(
            self.database, self.key_values, lambda: TODAY
        )

    def set_value(self, key: str, value: str) -> None:
        with self.database.unit_of_work() as db:
            self.key_values.set(db, key, value)

    def test_today_ready_state_is_current(self) -> None:
        self.set_value("morning_checkin_date", TODAY.isoformat())
        self.set_value("morning_checkin_status", "ready")

        self.assertEqual(
            self.service.state(),
            {
                "status": "ready",
                "date": TODAY.isoformat(),
                "current_for_today": True,
                "last_error": None,
            },
        )

    def test_yesterday_ready_state_is_projected_as_waiting(self) -> None:
        yesterday = TODAY - timedelta(days=1)
        self.set_value("morning_checkin_date", yesterday.isoformat())
        self.set_value("morning_checkin_status", "ready")

        self.assertEqual(
            self.service.state(),
            {
                "status": "waiting",
                "date": yesterday.isoformat(),
                "current_for_today": False,
                "last_error": None,
            },
        )

    def test_missing_state_defaults_to_waiting(self) -> None:
        self.assertEqual(
            self.service.state(),
            {
                "status": "waiting",
                "date": None,
                "current_for_today": False,
                "last_error": None,
            },
        )

    def test_non_ready_status_is_preserved(self) -> None:
        self.set_value("morning_checkin_date", TODAY.isoformat())
        self.set_value("morning_checkin_status", "failed")

        self.assertEqual(
            self.service.state(),
            {
                "status": "failed",
                "date": TODAY.isoformat(),
                "current_for_today": True,
                "last_error": None,
            },
        )

    def test_state_reads_through_reader_without_unit_of_work(self) -> None:
        self.set_value("morning_checkin_date", TODAY.isoformat())
        self.set_value("morning_checkin_status", "ready")
        with patch.object(
            self.database,
            "unit_of_work",
            side_effect=AssertionError("state projection must be read-only"),
        ) as unit_of_work:
            state = self.service.state()

        self.assertEqual(state["status"], "ready")
        unit_of_work.assert_not_called()


if __name__ == "__main__":
    unittest.main()
