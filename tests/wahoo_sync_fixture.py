"""Shared fixture for the Wahoo sync owner and acceptance tests.

Helper module, not a test module: it is imported by test modules and discovered
by none. It wires the real owner, observer, markers and canonical tables around a
temporary SQLite database and a fake Wahoo transport. It uses no network, no
real ``.env``, no data directory and no Wahoo account; every token is a
placeholder.
"""

from __future__ import annotations

import logging
import sqlite3
import tempfile
import threading
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from backend.config import Config
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.providers.wahoo_client import WahooWorkoutFetch
from backend.runtime.events import StateEventBuffer
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.daily import DailySyncMarkerService, daily_marker_key
from backend.sync.observation import SyncOperationObserver
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
from backend.sync.refresh import ProviderRefreshTracker
from backend.sync.wahoo_sync import WahooSyncService

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
ZONE = ZoneInfo("Europe/Berlin")
LATE_EVENING_UTC = "2026-10-11T22:30:00.000Z"
EARLIER_UTC = "2026-10-10T06:00:00.000Z"


def make_config(*, wahoo: bool = True) -> Config:
    return Config(
        port=8090,
        openai_api_key="",
        openai_base_url="https://api.openai.com/v1",
        openai_model="model",
        intervals_api_key="",
        intervals_athlete_id="0",
        garmin_email="",
        garmin_password="",
        garmin_tokenstore="unused",
        garmin_fixture_path="",
        calendar_ical_url="",
        app_password="",
        secure_cookies=False,
        data_retention_days=-1,
        wahoo_client_id="client-id" if wahoo else "",
        wahoo_client_secret="client-secret-placeholder" if wahoo else "",
        wahoo_redirect_uri="https://coach.example.invalid/api/wahoo/callback"
        if wahoo
        else "",
    )


def workout(number: int, starts: str, **changes: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": number,
        "starts": starts,
        "name": f"Workout {number}",
        "workout_type_id": 0,
        "workout_summary": {
            "duration_active_accum": "3600",
            "distance_accum": "30000",
            "heart_rate_avg": "140",
        },
    }
    row.update(changes)
    return row


class FakeWahooSource:
    """Stands in for the Wahoo read transport."""

    def __init__(self) -> None:
        self.fetch = WahooWorkoutFetch(())
        self.error: BaseException | None = None
        self.windows: list[datetime] = []
        self.upper_bounds: list[datetime | None] = []

    def list_workouts(
        self, *, since: datetime, until: datetime | None = None
    ) -> WahooWorkoutFetch:
        self.windows.append(since)
        self.upper_bounds.append(until)
        if self.error is not None:
            raise self.error
        return self.fetch


class FakeConnection:
    """Token-free connection status, switchable between connected and not."""

    def __init__(self, connected: bool = True) -> None:
        self.connected = connected

    def status(self) -> dict[str, Any]:
        return {"configured": True, "connected": self.connected}


class WahooSyncCase(unittest.TestCase):
    """A real Wahoo sync owner over a temporary database and a fake source."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = DatabaseManager(
            Path(temporary.name) / "wahoo.sqlite", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.database.close)
        with self.database.unit_of_work() as db:
            initialize_schema(db)
        self.now = NOW
        self.config = make_config()
        self.key_values = KeyValueRepository(lambda: self.now.isoformat())
        self.markers = DailySyncMarkerService(
            self.database, self.key_values, lambda: self.now
        )
        self.events = Mock(spec=StateEventBuffer)
        tracker = ProviderRefreshTracker(
            self.database, self.events, lambda: self.now, uuid.uuid4
        )
        self.gate = MaintenanceGate()
        self.observer = SyncOperationObserver(
            tracker, self.gate, logging.getLogger("wahoo.test.observer")
        )
        self.source = FakeWahooSource()
        self.connection = FakeConnection()
        self.logger = Mock(spec=logging.Logger)
        self.lock = threading.Lock()
        self.service = WahooSyncService(
            config=lambda: self.config,
            connection=lambda: self.connection,
            source=lambda: self.source,
            database_manager=lambda: self.database,
            database_lock=threading.RLock(),
            key_values=self.key_values,
            daily_markers=lambda: self.markers,
            observer=lambda: self.observer,
            registry=DEFAULT_PROVIDER_REGISTRY,
            zone_provider=lambda: ZONE,
            now=lambda: self.now,
            logger=self.logger,
            lock=self.lock,
        )

    def rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.database.reader() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def _value(self, key: str) -> str | None:
        with self.database.reader() as db:
            return self.key_values.get(db, key)

    def _marker(self) -> str | None:
        return self._value(daily_marker_key("wahoo"))

    def _activity_rows(self) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT provider, provider_activity_id, local_date, sport, state "
            "FROM activity_records ORDER BY provider_activity_id"
        )

    def _canonical_row_count(self) -> int:
        return sum(
            int(self.rows(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"])
            for table in ("provider_records", "activity_records", "activity_sessions")
        )

    def _refresh_statuses(self) -> list[str]:
        return [
            row["status"]
            for row in self.rows(
                "SELECT status FROM provider_refresh_history "
                "WHERE provider = 'wahoo' ORDER BY started_at, id"
            )
        ]

    def advance(self, **delta: int) -> None:
        self.now += timedelta(**delta)
