"""Stored weather of activities: labels, reads and the Coach block (#1868).

The values are derived observations owned by their canonical session, written
by ``backend.sync.activity_weather``. A row names only the kind of location
("activity_start" or "home"), never a coordinate; readers never fetch.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from typing import Any, Final

from backend.canonical.vocabulary import MetricKind
from backend.db import canonical_store
from backend.weather import cache
from backend.weather.activity_weather import heat_note

METHOD_ID: Final = "open-meteo-activity-weather"
METHOD_VERSION: Final = 1
LOCATION_START: Final = "activity_start"
LOCATION_HOME: Final = "home"
LOCATION_LABELS: Final = {
    LOCATION_START: "Open-Meteo Modell, Startposition",
    LOCATION_HOME: "Open-Meteo Modell, Wohnort",
}
# Block key, metric kind and the ActivityWeather attribute of each value.
VALUES: Final[tuple[tuple[str, MetricKind, str], ...]] = (
    ("temperature_c", MetricKind.ACTIVITY_WEATHER_TEMPERATURE, "temperature_c"),
    (
        "apparent_temperature_c",
        MetricKind.ACTIVITY_WEATHER_APPARENT_TEMPERATURE,
        "apparent_temperature_c",
    ),
    (
        "relative_humidity_pct",
        MetricKind.ACTIVITY_WEATHER_HUMIDITY,
        "relative_humidity_pct",
    ),
    ("wind_speed_mps", MetricKind.ACTIVITY_WEATHER_WIND_SPEED, "wind_speed_mps"),
    ("precipitation_mm", MetricKind.ACTIVITY_WEATHER_PRECIPITATION, "precipitation_mm"),
)
_KEY_OF_KIND: Final = {kind.value: key for key, kind, _ in VALUES}


def stored_activity_weather(
    db: Any, session_ids: Iterable[str] | None = None
) -> dict[str, dict[str, dict[str, Any]]]:
    """Map each session id to its stored weather rows by metric name."""
    owners = None if session_ids is None else list(session_ids)
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for row in canonical_store.derived_observation_rows(db, METHOD_ID, owners=owners):
        owner = row.get("owner_record_id")
        if isinstance(owner, str):
            result.setdefault(owner, {})[row["metric"]] = row
    return result


def weather_block(rows: Mapping[str, Mapping[str, Any]]) -> dict[str, Any] | None:
    """The compact block of one session's rows, or None without a stored value.

    It carries the values, the location kind, the source label and, from an
    apparent temperature of 25 C, the heat note. Never a coordinate.
    """
    values = {
        _KEY_OF_KIND[metric]: row["value"]
        for metric, row in rows.items()
        if metric in _KEY_OF_KIND
    }
    if not values:
        return None
    first = next(row for metric, row in rows.items() if metric in _KEY_OF_KIND)
    kind = first["derivation"].get("location_kind")
    block: dict[str, Any] = {
        key: values[key] for key, _kind, _ in VALUES if key in values
    }
    block["location_kind"] = kind
    block["source"] = LOCATION_LABELS.get(str(kind), LOCATION_LABELS[LOCATION_START])
    note = heat_note(values.get("apparent_temperature_c"))
    if note is not None:
        block["heat_note"] = note
    return block


def home_coordinates(
    key_values: Any, db: Any, query: str
) -> tuple[float, float] | None:
    """The cached geocoded coordinates of the saved weather location ``query``."""
    wanted = query.strip()[:200]
    if not wanted:
        return None
    try:
        cached = json.loads(key_values.get(db, cache.CACHE_KEY) or "{}")
        if cached.get("query") != wanted:
            return None
        location = cached["location"]
        latitude, longitude = float(location["latitude"]), float(location["longitude"])
    except TypeError, ValueError, KeyError, AttributeError:
        return None
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return None
    return latitude, longitude
