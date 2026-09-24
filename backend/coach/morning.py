"""Manual morning check-in preparation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.performance import garmin_observations
from backend.performance.morning_battery_service import MorningBodyBatteryService
from backend.sync.garmin import GarminPayloadService
from backend.sync.garmin_service import GARMIN_AUTOMATIC_SYNC_DAYS, GarminSyncService


class ManualMorningCheckinService:
    """Prepare current Garmin sleep and morning Body Battery for a manual check-in."""

    def __init__(
        self,
        garmin_sync: GarminSyncService,
        garmin_payload: GarminPayloadService,
        morning_battery: MorningBodyBatteryService,
        local_today: Callable[[], date],
        logger: logging.Logger,
    ) -> None:
        self._garmin_sync = garmin_sync
        self._garmin_payload = garmin_payload
        self._morning_battery = morning_battery
        self._local_today = local_today
        self._logger = logger

    def prepare(self) -> None:
        if not self._garmin_sync.configured():
            return

        checkin_date = self._local_today()
        try:
            self._garmin_sync.sync(
                days=GARMIN_AUTOMATIC_SYNC_DAYS,
                reason="Morgen-Check-in",
                wait_for_existing=True,
            )
        except Exception:
            self._logger.warning(
                "Morning Garmin synchronization failed",
                extra={"event": "morning_garmin_sync_failed"},
                exc_info=True,
            )

        if not garmin_observations.garmin_sleep_ready_for_checkin(
            checkin_date, self._garmin_payload.snapshot()
        ):
            raise AppError(
                503,
                "Der Morgen-Check-in wartet auf Garmins Schlafdaten für heute.",
                reason="garmin_sleep_not_ready",
            )

        self._morning_battery.refresh(checkin_date)


class MorningCheckinStateService:
    """Project persisted morning check-in state for the current local day."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        key_values: KeyValueRepository,
        local_today: Callable[[], date],
    ) -> None:
        self._database_manager = database_manager
        self._key_values = key_values
        self._local_today = local_today

    def state(self) -> dict[str, Any]:
        with self._database_manager.reader() as db:
            completed_date = self._key_values.get(db, "morning_checkin_date")
            status = self._key_values.get(db, "morning_checkin_status") or "waiting"

        current = completed_date == self._local_today().isoformat()
        if status == "ready" and not current:
            status = "waiting"
        return {
            "status": status,
            "date": completed_date,
            "current_for_today": current,
            "last_error": None,
        }
