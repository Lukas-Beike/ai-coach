"""Pure identity helpers for untrusted activity records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.canonical.sports import classify_sport_text, legacy_activity_family
from backend.canonical.vocabulary import Sport

_UTC_OFFSET_SUFFIX = "+00:00"
_ACTIVITY_KIND_FIELDS = (
    "type",
    "sport",
    "sport_type",
    "activityType",
    "activityName",
    "name",
)


def activity_datetime(value: Any) -> datetime | None:
    """Parse an activity timestamp using the legacy normalization rules."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", _UTC_OFFSET_SUFFIX))
    except TypeError, ValueError, OverflowError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def activity_sport(activity: Any) -> Sport:
    """Classify an activity's canonical sport from its legacy identity fields."""
    if not isinstance(activity, dict):
        return Sport.OTHER
    value = " ".join(
        str(activity.get(key) or "") for key in _ACTIVITY_KIND_FIELDS
    ).casefold()
    return classify_sport_text(value)


def activity_kind(activity: Any) -> str:
    """Classify an activity by its legacy case-insensitive name matching."""
    return legacy_activity_family(activity_sport(activity))
