"""Choose the one record of Garmin's device-keyed status responses.

Training status and load balance answer with one record per device, keyed by a
device id. The primary training device's record wins when exactly one is marked
and dated. Otherwise the latest dated records count, and only when they agree on
the compared fields; any ambiguity yields no record. The device keys are never
returned or stored.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

CALENDAR_DATE: Final = "calendarDate"
PRIMARY_DEVICE_KEY: Final = "primaryTrainingDevice"
_DEVICE_LIMIT: Final = 100

type DayParser = Callable[[Any], str | None]


def primary_device_record(
    value: Any,
    section_key: str,
    devices_key: str,
    comparable_fields: tuple[str, ...],
    *,
    day: DayParser,
) -> dict[str, Any] | None:
    """Return the record of the primary or the unambiguous latest device, or None.

    ``day`` turns a record's ``calendarDate`` into an ISO day or None.
    """
    if not isinstance(value, dict):
        return None
    section = value.get(section_key)
    devices = value.get(devices_key)
    if not isinstance(devices, dict) and isinstance(section, dict):
        devices = section.get(devices_key)
    if not isinstance(devices, dict) or not devices:
        return None
    candidates = [
        dict(item)
        for item in list(devices.values())[:_DEVICE_LIMIT]
        if isinstance(item, dict)
    ]
    primary = [item for item in candidates if item.get(PRIMARY_DEVICE_KEY) is True]
    if primary:
        return (
            primary[0]
            if len(primary) == 1 and day(primary[0].get(CALENDAR_DATE))
            else None
        )
    dated: list[tuple[str, dict[str, Any]]] = []
    for item in candidates:
        observed = day(item.get(CALENDAR_DATE))
        if observed is not None:
            dated.append((observed, item))
    latest = max((observed for observed, _ in dated), default=None)
    if latest is None:
        return None
    matches = [item for observed, item in dated if observed == latest]
    if len(matches) == 1:
        return matches[0]

    def comparable(item: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(
            nested_value(item, field.split(".")) for field in comparable_fields
        )

    first = comparable(matches[0])
    return (
        matches[0] if all(comparable(item) == first for item in matches[1:]) else None
    )


def nested_value(value: dict[str, Any], keys: list[str]) -> Any:
    current: Any = value
    for key in keys:
        current = current.get(key) if isinstance(current, dict) else None
    return current
