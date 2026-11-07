"""The athlete's switch for reading data from Intervals.icu.

Intervals.icu is an output target (library and planned workouts, competitions,
nutrition, sport settings). Reading its activities, wellness, athlete record and
activity details is a dormant fallback: off unless the athlete turns it on. A
missing key means off, so an upgraded database starts with the ingest off and
keeps every stored Intervals.icu record. A manual one-off sync reads the recent
window once while the switch stays off.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final, Protocol

from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.providers.descriptors import INTERVALS_ID

INGEST_PROVIDER_ID: Final = INTERVALS_ID
INGEST_ENABLED_KEY: Final = "intervals_ingest_enabled"
# Days a manual one-off sync reads while the ingest is off.
ONE_OFF_DAYS: Final = 42
INGEST_OFF_REASON: Final = "intervals_ingest_off"
# The completion marker of the Intervals.icu ingest purge (#1728): once it is
# done, the ingest stays off and no one-off read stores Intervals.icu data again.
PURGE_STATE_KEY: Final = "intervals_purge_state"
PURGE_VERSION: Final = 1
PURGE_DONE: Final = "done"
INGEST_PURGED_REASON: Final = "intervals_ingest_purged"
# Written beside the database after the purge: a restored pre-purge database
# has no marker of its own, so the file keeps the ingest off there too.
PURGE_MARKER_FILE: Final = f"intervals-purge-v{PURGE_VERSION}.done"


def purge_marker_exists(data_dir: Path) -> bool:
    """Whether the data directory holds the marker file of a completed purge."""
    return (data_dir / PURGE_MARKER_FILE).is_file()


def ingest_enabled_value(value: str | None) -> bool:
    """Decode the stored switch value; a missing key is off."""
    return value == "1"


def purge_state_value(raw: object) -> dict[str, Any]:
    """Decode a stored purge state; a missing or corrupt value reads as empty."""
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        state = json.loads(raw)
    except ValueError:
        return {}
    return state if isinstance(state, dict) else {}


def purge_state(key_values: KeyValueRepository, db: Any) -> dict[str, Any]:
    """Return the stored purge state; a missing or corrupt record reads as empty."""
    return purge_state_value(key_values.get(db, PURGE_STATE_KEY))


def purge_done(state: Mapping[str, Any]) -> bool:
    """Whether a purge state records a completed purge of this version or later."""
    version = state.get("version")
    return (
        state.get("status") == PURGE_DONE
        and isinstance(version, int)
        and version >= PURGE_VERSION
    )


def ingest_off_result() -> dict[str, Any]:
    """Return the result of an ingest step skipped because the switch is off."""
    return {"status": "skipped", "reason": INGEST_OFF_REASON}


class IngestGate(Protocol):
    """Whether Intervals.icu data is read in, and whether it was purged."""

    def enabled(self) -> bool: ...

    def purged(self) -> bool: ...


class _IngestOn:
    """The gate of a caller without a switch: reading on, nothing purged."""

    def enabled(self) -> bool:
        return True

    def purged(self) -> bool:
        return False


INGEST_ON: Final = _IngestOn()


class IntervalsIngestSwitch:
    """Read and store whether Intervals.icu data is read in.

    ``purge_marker`` tells whether the data directory holds the purge marker
    file; with it or the database marker the purge counts as done.
    """

    def __init__(
        self,
        database_manager: Any,
        key_values: KeyValueRepository,
        purge_marker: Callable[[], bool] = lambda: False,
    ) -> None:
        self._database_manager = database_manager
        self._key_values = key_values
        self._purge_marker = purge_marker

    def enabled(self) -> bool:
        with self._database_manager.reader() as db:
            return ingest_enabled_value(self._key_values.get(db, INGEST_ENABLED_KEY))

    def purged(self) -> bool:
        """Whether the stored Intervals.icu ingest data was purged (#1728)."""
        if self._purge_marker():
            return True
        with self._database_manager.reader() as db:
            return purge_done(purge_state(self._key_values, db))

    def save(self, values: Any) -> dict[str, Any]:
        """Store the switch from ``{"enabled": bool}``; after the purge it stays off."""
        enabled = values.get("enabled") if isinstance(values, dict) else None
        if not isinstance(enabled, bool):
            raise AppError(400, "Der Schalter braucht den Wert an oder aus.")
        with self._database_manager.unit_of_work() as db:
            if enabled and (
                self._purge_marker() or purge_done(purge_state(self._key_values, db))
            ):
                raise AppError(
                    409,
                    "Intervals.icu-Daten wurden bereinigt; das Einlesen bleibt aus.",
                    reason=INGEST_PURGED_REASON,
                )
            self._key_values.set(db, INGEST_ENABLED_KEY, "1" if enabled else "0")
        return {"status": "ok", "enabled": enabled}
