"""Garmin gear payload accessors that return neutral values.

The sync reads gear identity and activity starts through these functions so Garmin
wire keys stay inside the provider adapters.
"""

from collections.abc import Mapping
from typing import Any, Final

_GEAR_ID: Final = "gearUUID"


def garmin_gear_id(row: Mapping[str, Any]) -> str:
    """Return the Garmin gear identifier, or an empty string when absent."""
    return str(row.get(_GEAR_ID) or "")


def activity_start_local(activity: Mapping[str, Any]) -> Any:
    """Return the Garmin activity local start, in either payload spelling."""
    return activity.get("startTimeLocal") or activity.get("start_time_local")
