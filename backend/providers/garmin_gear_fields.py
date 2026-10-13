"""Garmin gear payload accessors that return neutral values.

Equipment code reads gear identity and labels through these functions so Garmin
wire keys stay inside the provider adapters.
"""

from collections.abc import Mapping
from typing import Any, Final

_GEAR_ID: Final = "gearUUID"
_GEAR_NAME: Final = "gearName"
_GEAR_DESCRIPTOR_KEYS: Final = ("gearTypeName", _GEAR_NAME, "activityTypeName")


def garmin_gear_id(row: Mapping[str, Any]) -> str:
    """Return the Garmin gear identifier, or an empty string when absent."""
    return str(row.get(_GEAR_ID) or "")


def garmin_gear_name(row: Mapping[str, Any]) -> str:
    """Return the Garmin gear name, or an empty string when absent."""
    return str(row.get(_GEAR_NAME) or "")


def garmin_gear_descriptor_texts(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the type, name and activity-type labels used to classify gear."""
    return tuple(str(row.get(key) or "") for key in _GEAR_DESCRIPTOR_KEYS)


def activity_start_local(activity: Mapping[str, Any]) -> Any:
    """Return the Garmin activity local start, in either payload spelling."""
    return activity.get("startTimeLocal") or activity.get("start_time_local")
