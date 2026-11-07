"""The athlete's switch for reading data from Intervals.icu.

Intervals.icu is an output target (library and planned workouts, competitions,
nutrition, sport settings). Reading its activities, wellness, athlete record and
activity details is a dormant fallback: off unless the athlete turns it on. A
missing key means off, so an upgraded database starts with the ingest off and
keeps every stored Intervals.icu record. A manual one-off sync reads the recent
window once while the switch stays off.
"""

from __future__ import annotations

from typing import Any, Final

from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.providers.descriptors import INTERVALS_ID

INGEST_PROVIDER_ID: Final = INTERVALS_ID
INGEST_ENABLED_KEY: Final = "intervals_ingest_enabled"
# Days a manual one-off sync reads while the ingest is off.
ONE_OFF_DAYS: Final = 42
INGEST_OFF_REASON: Final = "intervals_ingest_off"


def ingest_enabled_value(value: str | None) -> bool:
    """Decode the stored switch value; a missing key is off."""
    return value == "1"


def ingest_off_result() -> dict[str, Any]:
    """Return the result of an ingest step skipped because the switch is off."""
    return {"status": "skipped", "reason": INGEST_OFF_REASON}


class IntervalsIngestSwitch:
    """Read and store whether Intervals.icu data is read in."""

    def __init__(self, database_manager: Any, key_values: KeyValueRepository) -> None:
        self._database_manager = database_manager
        self._key_values = key_values

    def enabled(self) -> bool:
        with self._database_manager.reader() as db:
            return ingest_enabled_value(self._key_values.get(db, INGEST_ENABLED_KEY))

    def save(self, values: Any) -> dict[str, Any]:
        """Store the switch from ``{"enabled": bool}``."""
        enabled = values.get("enabled") if isinstance(values, dict) else None
        if not isinstance(enabled, bool):
            raise AppError(400, "Der Schalter braucht den Wert an oder aus.")
        with self._database_manager.unit_of_work() as db:
            self._key_values.set(db, INGEST_ENABLED_KEY, "1" if enabled else "0")
        return {"status": "ok", "enabled": enabled}
