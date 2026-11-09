"""The athlete's recording sensors and the power meter change marker (#1869).

Every stream set names the external heart rate, power meter and trainer
sensors of its recording, each as a hash of manufacturer, product and serial
number (``ActivitySensor.key``). This module folds those lists, one per session,
into a registry of distinct sensors and finds the day a sport's power meter
changed. A serial number is never read, stored or shown; the registry shows a
short prefix of the hash as the sensor's id. Stdlib only and without I/O;
``activity_detail_store.sensor_uses`` reads the inputs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final

from backend.canonical.activity_detail import ActivitySensor
from backend.canonical.vocabulary import SensorRole

SENSOR_ID_LENGTH: Final = 16
POWER_METER_CHANGE_NOTE: Final = (
    "Neues Wattmessgerät: Werte vor und nach diesem Tag (kritische Leistung, "
    "FTP-Vergleiche, Bestwerte) nicht ohne Hinweis vergleichen."
)


@dataclass(frozen=True, slots=True)
class SensorUse:
    """The sensors one session's recording named, on the day it started."""

    session_id: str
    sport: str
    started_at: datetime
    sensors: tuple[ActivitySensor, ...]


def sensor_id(key: str) -> str:
    """The short id of a sensor hash, as shown to the athlete."""
    return key[:SENSOR_ID_LENGTH]


def registry(
    uses: Iterable[SensorUse], assignments: Mapping[str, str] | None = None
) -> list[dict[str, Any]]:
    """Distinct sensors with their first and last day, newest first.

    ``assignments`` maps a full sensor key to an equipment id the athlete chose.
    """
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for use in uses:
        for sensor in use.sensors:
            entry = found.setdefault(
                (sensor.role.value, sensor.key),
                {
                    "id": sensor_id(sensor.key),
                    "role": sensor.role.value,
                    "connection": sensor.connection,
                    "manufacturer": sensor.manufacturer,
                    "product": sensor.product,
                    "first_seen": use.started_at.date().isoformat(),
                    "last_seen": use.started_at.date().isoformat(),
                    "sessions": set(),
                    "sports": set(),
                    "equipment_id": (assignments or {}).get(sensor.key),
                },
            )
            day = use.started_at.date().isoformat()
            entry["first_seen"] = min(entry["first_seen"], day)
            entry["last_seen"] = max(entry["last_seen"], day)
            entry["sessions"].add(use.session_id)
            entry["sports"].add(use.sport)
    rows = [
        {
            **{k: v for k, v in entry.items() if k not in ("sessions", "sports")},
            "sessions": len(entry["sessions"]),
            "sports": sorted(entry["sports"]),
        }
        for entry in found.values()
    ]
    rows.sort(key=lambda row: (row["last_seen"], row["id"]), reverse=True)
    return rows


def power_meter_changes(uses: Iterable[SensorUse]) -> list[dict[str, Any]]:
    """One marker per sport and day a recording first uses a power meter never seen before.

    A change needs the recording's meters to share none with the previous
    recording's and none with any earlier one, so alternating between two bikes
    that each keep their meter is no change. Sessions without a named power meter
    are skipped, so a ride on another bike or an indoor trainer does not end a
    meter's run. A replaced pair of pedals shows as a change; swapping only one
    of two meters is not detected.
    """
    by_sport: dict[str, list[tuple[datetime, frozenset[str]]]] = {}
    for use in uses:
        meters = frozenset(
            sensor.key
            for sensor in use.sensors
            if sensor.role is SensorRole.POWER_METER
        )
        if meters:
            by_sport.setdefault(use.sport, []).append((use.started_at, meters))
    changes: list[dict[str, Any]] = []
    for sport, sessions in by_sport.items():
        sessions.sort(key=lambda item: item[0])
        seen = set(sessions[0][1])
        for started_at, after in sessions[1:]:
            new = after.isdisjoint(seen)
            seen |= after
            if new:
                changes.append(
                    {
                        "sport": sport,
                        "date": started_at.date().isoformat(),
                        "sensor_ids": sorted(sensor_id(key) for key in after),
                        "note": POWER_METER_CHANGE_NOTE,
                    }
                )
    changes.sort(key=lambda row: (row["date"], row["sport"]), reverse=True)
    return changes


def changes_since(
    changes: Sequence[Mapping[str, Any]], sport: str, first_day: date
) -> list[dict[str, Any]]:
    """The markers of ``sport`` on or after ``first_day``."""
    return [
        dict(change)
        for change in changes
        if change["sport"] == sport and change["date"] >= first_day.isoformat()
    ]
