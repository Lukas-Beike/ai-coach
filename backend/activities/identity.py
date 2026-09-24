"""Pure identity helpers for untrusted activity records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_UTC_OFFSET_SUFFIX = "+00:00"
_ACTIVITY_KIND_FIELDS = (
    "type",
    "sport",
    "sport_type",
    "activityType",
    "activityName",
    "name",
)
_DEVICE_SOURCE_FIELDS = ("source", "device_name", "external_id")


def activity_datetime(value: Any) -> datetime | None:
    """Parse an activity timestamp using the legacy normalization rules."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", _UTC_OFFSET_SUFFIX))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def activity_kind(activity: Any) -> str:
    """Classify an activity by its legacy case-insensitive name matching."""
    if not isinstance(activity, dict):
        return "other"
    value = " ".join(
        str(activity.get(key) or "") for key in _ACTIVITY_KIND_FIELDS
    ).casefold()
    if any(
        term in value for term in ("ride", "bike", "cycling", "rad", "velo", "bicycle")
    ):
        return "cycling"
    if any(term in value for term in ("run", "lauf", "jog")):
        return "running"
    if any(term in value for term in ("swim", "schwimm")):
        return "swimming"
    if any(term in value for term in ("strength", "kraft", "weight", "gym")):
        return "strength"
    return "other"


def intervals_activity_device_source(activity: Any) -> str | None:
    """Return explicit Wahoo or Garmin provenance from an activity."""
    if not isinstance(activity, dict):
        return None
    provenance = " ".join(
        str(activity.get(key) or "") for key in _DEVICE_SOURCE_FIELDS
    ).casefold()
    if "wahoo" in provenance or "elemnt" in provenance:
        return "wahoo"
    if "garmin" in provenance:
        return "garmin"
    return None
