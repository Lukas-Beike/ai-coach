"""Map stored Garmin gear elements to canonical gear and gear-to-activity links.

One element of the ``gear`` section is one gear item as the collector normalized
it: ``gearUUID``, ``gearName``, ``gearTypeName``, ``activityTypeName``,
``gearStatusName``, ``maximumMeters``, the usage ``stats`` (``totalDistance`` in
metres, ``totalActivities``) and, when the link list was read, ``activity_ids``.
A missing ``activity_ids`` means the links are unknown, so none are emitted. A
list marked ``activity_ids_truncated`` or ``activity_ids_stale`` (kept from an
earlier sync) is partial. Equipment reads resolve the links to
canonical sessions through the provider activity id.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

from backend.canonical.domain_records import (
    MAX_GEAR_ACTIVITIES,
    MAX_GEAR_DISTANCE_M,
    GearActivityLink,
    GearItem,
)
from backend.canonical.mapping import coerce_number
from backend.canonical.records import Provenance
from backend.canonical.validation import MAX_TEXT_LENGTH
from backend.canonical.vocabulary import ProviderId, RecordingOrigin, SourceKind

GARMIN_LABEL: Final = "Garmin Connect"
_MAX_LINKS: Final = 1000
# The canonical text bound of a provider activity id.
_MAX_ID_LENGTH: Final = MAX_TEXT_LENGTH


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:limit] if text else None


def _distance(value: Any) -> float | None:
    number = coerce_number(value)
    return number if number is not None and 0 <= number <= MAX_GEAR_DISTANCE_M else None


def _count(value: Any) -> int | None:
    number = coerce_number(value)
    if number is None or not number.is_integer():
        return None
    return int(number) if 0 <= number <= MAX_GEAR_ACTIVITIES else None


def _list_partial(element: Mapping[str, Any]) -> bool | None:
    if not isinstance(element.get("activity_ids"), list):
        return None
    return bool(
        element.get("activity_ids_truncated") is True
        or element.get("activity_ids_stale") is True
    )


def map_garmin_gear(
    element: object, *, source_record_id: str, retrieved_at: datetime
) -> tuple[tuple[GearItem, ...], tuple[GearActivityLink, ...]]:
    """Return the gear item and its activity links of one stored gear element.

    An implausible distance or count is left out rather than dropping the item.
    """
    if not isinstance(element, Mapping):
        return (), ()
    gear_id = _text(element.get("gearUUID"), 200)
    if gear_id is None:
        return (), ()
    provenance = Provenance(
        provider=ProviderId.GARMIN,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=source_record_id,
        recorded_by=RecordingOrigin.GARMIN,
        retrieved_at=retrieved_at,
        label=GARMIN_LABEL,
    )
    stats = element.get("stats")
    stats = stats if isinstance(stats, Mapping) else {}
    try:
        item = GearItem(
            gear_id=gear_id,
            name=_text(element.get("gearName"), 200),
            type_label=_text(element.get("gearTypeName"), 100),
            activity_type_label=_text(element.get("activityTypeName"), 100),
            status_label=_text(element.get("gearStatusName"), 100),
            maximum_distance_m=_distance(element.get("maximumMeters")),
            total_distance_m=_distance(stats.get("totalDistance")),
            total_activities=_count(stats.get("totalActivities")),
            provenance=provenance,
            activity_list_partial=_list_partial(element),
        )
    except TypeError, ValueError:
        return (), ()
    ids = element.get("activity_ids")
    links = tuple(
        GearActivityLink(gear_id, activity_id, provenance)
        for activity_id in dict.fromkeys(
            str(value)
            for value in (ids if isinstance(ids, list) else [])[:_MAX_LINKS]
            if isinstance(value, str | int)
            and not isinstance(value, bool)
            and str(value).strip()
            # A longer id is malformed and is skipped, never stored.
            and len(str(value)) <= _MAX_ID_LENGTH
        )
    )
    return (item,), links
