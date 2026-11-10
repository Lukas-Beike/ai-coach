"""Reduce Coach attachments to measurements before they leave the server.

Pure stdlib functions. The athlete keeps every measurement point for analysis;
what is removed is identifying: the positions within 500 m of the start and the
end of a track, device and user records, file metadata and image metadata.
"""

from __future__ import annotations

import itertools
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from typing import Any

from backend.providers.fit_file import (
    fit_messages,
    fit_named_values,
    fit_scaled_array,
)

TRIM_METERS = 500.0
_EARTH_RADIUS_M = 6371000
# FIT latitude and longitude are semicircles: 2**31 of them make 180 degrees.
_SEMICIRCLES_TO_DEGREES = 180 / 2**31
_FIT_EXPORT_MESSAGES = {18: "sessions", 19: "laps", 20: "records", 225: "sets"}
_FIT_TIME_FIELDS = {"timestamp", "start_time"}
_FIT_POSITION_FIELDS = {
    "position_lat": "latitude_deg",
    "position_long": "longitude_deg",
}
_GPX_SKIPPED_FIELDS = {"name", "desc", "cmt", "src", "sym", "type", "link", "fix"}
_GPX_MAX_METRICS = 12
_GPX_METRIC_NAME = re.compile(r"[a-z][a-z0-9_]{0,23}")
_GPX_TIME = re.compile(r"[0-9TZ:+.\- ]{10,40}")


def haversine_m(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    a, b = math.radians(lat_a), math.radians(lat_b)
    h = (
        math.sin((b - a) / 2) ** 2
        + math.cos(a) * math.cos(b) * math.sin(math.radians(lon_b - lon_a) / 2) ** 2
    )
    return _EARTH_RADIUS_M * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def hidden_position_indexes(
    positions: Sequence[tuple[float, float] | None], trim_m: float = TRIM_METERS
) -> set[int]:
    """Indexes whose position lies within trim_m of the track's start or end.

    Distance runs along the located points. A track shorter than twice the
    trim hides every position.
    """
    located = [index for index, position in enumerate(positions) if position]
    cumulative = [0.0]
    for first, second in itertools.pairwise(located):
        cumulative.append(
            cumulative[-1] + haversine_m(*positions[first], *positions[second])  # type: ignore[misc]
        )
    total = cumulative[-1]
    return {
        index
        for index, distance in zip(located, cumulative)
        if distance < trim_m or total - distance < trim_m
    }


def _number(value: object, digits: int) -> int | float:
    if isinstance(value, float):
        return round(value, digits)
    return value  # type: ignore[return-value]


def _columns(rows: list[dict[str, Any]]) -> dict[str, Any]:
    names = sorted({key for row in rows for key in row})
    return {
        "columns": names,
        "rows": [[row.get(name) for name in names] for row in rows],
    }


def _fit_row(values: dict[str, Any], origin: float | None) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in values.items():
        if key in _FIT_POSITION_FIELDS:
            row[_FIT_POSITION_FIELDS[key]] = round(value * _SEMICIRCLES_TO_DEGREES, 6)
        elif key not in _FIT_TIME_FIELDS:
            row[key] = _number(value, 4)
        elif origin is not None:
            row["time_s"] = round(value - origin, 3)
    return row


def _hide_record_positions(records: list[dict[str, Any]]) -> None:
    positions = [
        (row["latitude_deg"], row["longitude_deg"])
        if "latitude_deg" in row and "longitude_deg" in row
        else None
        for row in records
    ]
    for index in hidden_position_indexes(positions):
        records[index].pop("latitude_deg", None)
        records[index].pop("longitude_deg", None)


def fit_document(name: str, summary: Any, data: bytes) -> dict[str, Any]:
    """The measurements of a FIT file without device, user or file records."""
    parsed = fit_messages(data)
    messages = [
        (number, fit_named_values(fields, number))
        for number, fields in parsed
        if number in _FIT_EXPORT_MESSAGES
    ]
    record_times = [
        values["timestamp"]
        for number, values in messages
        if number == 20 and "timestamp" in values
    ]
    origin = min(record_times) if record_times else None
    tables: dict[str, list[dict[str, Any]]] = {
        label: [] for label in _FIT_EXPORT_MESSAGES.values()
    }
    for number, values in messages:
        tables[_FIT_EXPORT_MESSAGES[number]].append(_fit_row(values, origin))
    _hide_record_positions(tables["records"])
    return {
        "format": "FIT",
        "filename": name,
        "summary": summary if isinstance(summary, dict) else {},
        "note": (
            "Measurements only. Positions within 500 m of the start and end of "
            "the track, device and user records and file metadata are left out."
        ),
        "records": _columns(tables["records"]),
        "laps": tables["laps"],
        "sessions": tables["sessions"],
        "sets": tables["sets"],
        "heart_rate_variability_rr_s": [
            _number(slot, 4)
            for number, fields in parsed
            if number == 78
            for slot in fit_scaled_array(fields, 78, 0)
            if slot is not None
        ],
    }


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _gpx_value(name: str, text: str) -> int | float | str | None:
    """The kept value of one point child, or None when it is not a measurement."""
    if name == "time":
        return text if _GPX_TIME.fullmatch(text) else None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 4)


def _gpx_point_values(node: ET.Element) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for child in node.iter():
        name = _local_name(child.tag).lower()
        text = (child.text or "").strip()
        if (
            child is node
            or not text
            or name in _GPX_SKIPPED_FIELDS
            or not _GPX_METRIC_NAME.fullmatch(name)
        ):
            continue
        value = _gpx_value(name, text)
        if value is not None:
            values[name] = value
    return values


def gpx_document(name: str, text: str) -> dict[str, Any]:
    """The points of a GPX file; no author, device, links or names.

    Positions within 500 m of the start and end are left out of their points,
    whose time, elevation and sensor values stay.
    """
    root = ET.fromstring(text)
    points: list[dict[str, Any]] = []
    for group in root.iter():
        if _local_name(group.tag) not in {"trkseg", "rte"}:
            continue
        for node in group:
            if _local_name(node.tag) not in {"trkpt", "rtept"}:
                continue
            point = _gpx_point_values(node)
            point["lat"] = float(node.attrib["lat"])
            point["lon"] = float(node.attrib["lon"])
            points.append(point)
    hidden = hidden_position_indexes([(p["lat"], p["lon"]) for p in points])
    names = sorted({key for point in points for key in point} - {"lat", "lon"})
    columns = ["lat", "lon", *names[:_GPX_MAX_METRICS]]
    return {
        "format": "GPX",
        "filename": name,
        "note": (
            "Measurements only. Positions within 500 m of the start and end of "
            "the track and file metadata are left out."
        ),
        "columns": columns,
        "points": [
            [
                None
                if index in hidden and column in {"lat", "lon"}
                else point.get(column)
                for column in columns
            ]
            for index, point in enumerate(points)
        ],
    }
