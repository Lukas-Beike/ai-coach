"""Garmin gear payload accessors that return neutral values.

Equipment code reads gear identity and labels through these functions so Garmin
wire keys stay inside the provider adapters.
"""

from collections.abc import Iterable, Mapping
from typing import Any, Final

from backend.canonical.domain_records import GearActivityLink, GearItem
from backend.canonical.vocabulary import ProviderId

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


def canonical_gear_rows(
    items: Iterable[GearItem], links: Iterable[GearActivityLink]
) -> list[dict[str, Any]]:
    """Render canonical Garmin gear in the stored gear row shape equipment reads.

    The activity list is present only when it was known; a partial list keeps
    the truncated mark. Other providers' gear is left out.
    """
    activity_ids: dict[str, list[str]] = {}
    for link in links:
        if link.provenance.provider is ProviderId.GARMIN:
            activity_ids.setdefault(link.gear_id, []).append(link.provider_activity_id)
    rows: list[dict[str, Any]] = []
    for item in items:
        if item.provenance.provider is not ProviderId.GARMIN:
            continue
        row: dict[str, Any] = {
            _GEAR_ID: item.gear_id,
            "stats": {
                key: value
                for key, value in (
                    ("totalDistance", item.total_distance_m),
                    ("totalActivities", item.total_activities),
                )
                if value is not None
            },
        }
        for key, value in (
            (_GEAR_NAME, item.name),
            ("gearTypeName", item.type_label),
            ("activityTypeName", item.activity_type_label),
            ("gearStatusName", item.status_label),
            ("maximumMeters", item.maximum_distance_m),
        ):
            if value is not None:
                row[key] = value
        if item.activity_list_partial is not None:
            row["activity_ids"] = activity_ids.get(item.gear_id, [])
            if item.activity_list_partial:
                row["activity_ids_truncated"] = True
        rows.append(row)
    return rows


def activity_start_local(activity: Mapping[str, Any]) -> Any:
    """Return the Garmin activity local start, in either payload spelling."""
    return activity.get("startTimeLocal") or activity.get("start_time_local")
