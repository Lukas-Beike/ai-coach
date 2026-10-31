"""Map the stored Intervals.icu power curve envelope to canonical power curve points.

The envelope is what ``IntervalsReader`` stores as ``cycling_power_profile``:
``status``, the fetch window ``start`` and ``end``, ``synced_at`` and the
``points`` of ``backend.providers.intervals_power.cycling_power_points``. Each
point keeps its watts, the day and activity of the best effort, the window and
the fetch status. The points were fetched at ``synced_at``; without a usable
one, the raw record's fetch time stands in. Only ``ok`` points are mapped. A
point that fails validation, repeats a duration, or an envelope without a
usable window maps to nothing, so a corrupted curve never blocks the rest.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, tzinfo
from typing import Final

from backend.canonical.domain_records import PowerCurvePoint
from backend.canonical.local_time import parse_provider_datetime
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import ProviderId, RecordingOrigin, SourceKind
from backend.providers.intervals_power import POWER_CURVE_LABEL

MAPPER_VERSION: Final = 1
_POINT_OK: Final = "ok"


def _day(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _point(
    point: object,
    *,
    window: tuple[date, date],
    fetch_status: str,
    provenance: Provenance,
) -> PowerCurvePoint | None:
    if not isinstance(point, Mapping) or point.get("status") != _POINT_OK:
        return None
    day = _day(point.get("date"))
    duration, watts = point.get("duration_seconds"), point.get("watts")
    activity = point.get("activity_id")
    if day is None or duration is None or watts is None:
        return None
    try:
        return PowerCurvePoint(
            duration_s=duration,
            watts=watts,
            observed_on=day,
            provider_activity_id=activity
            if isinstance(activity, str) and activity
            else None,
            window_start=window[0],
            window_end=window[1],
            fetch_status=fetch_status,
            provenance=provenance,
        )
    except TypeError, ValueError:
        return None


def map_intervals_power_curve(
    envelope: object,
    *,
    source_record_id: str,
    fetched_at: datetime,
    zone: tzinfo,
) -> tuple[PowerCurvePoint, ...]:
    """Return the best power per duration of one stored power curve envelope."""
    if not isinstance(envelope, Mapping):
        return ()
    start, end = _day(envelope.get("start")), _day(envelope.get("end"))
    status = envelope.get("status")
    points = envelope.get("points")
    if start is None or end is None or not isinstance(points, list):
        return ()
    if not isinstance(status, str):
        return ()
    provenance = Provenance(
        provider=ProviderId.INTERVALS,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=source_record_id,
        recorded_by=RecordingOrigin.UNKNOWN,
        retrieved_at=parse_provider_datetime(envelope.get("synced_at"), zone)
        or fetched_at,
        label=POWER_CURVE_LABEL,
    )
    mapped: dict[int, PowerCurvePoint] = {}
    for item in points:
        point = _point(
            item, window=(start, end), fetch_status=status, provenance=provenance
        )
        if point is not None and point.duration_s not in mapped:
            mapped[point.duration_s] = point
    return tuple(mapped[duration] for duration in sorted(mapped))
