"""Map the stored Intervals.icu power curve envelope to canonical power curve rows.

The envelope is what ``IntervalsReader`` stores as ``cycling_power_profile``:
``status``, the fetch window ``start`` and ``end``, ``synced_at`` and the
``points`` of ``backend.providers.intervals_power.cycling_power_points``.

The fetch-level facts (status, window, ``synced_at``) map once to a
``PowerCurveFetch``; each point keeps its watts and the day and activity of the
best effort. The points were fetched at ``synced_at``; without a usable one, the
raw record's fetch time stands in. Only ``ok`` points inside the window are
mapped; a point that fails validation or repeats a duration is left out.

An envelope without a usable window or point list, such as ``{"status":
"failed"}`` after a failed first fetch, reports no curve: its points are None,
so the stored best efforts are kept, while its status is still recorded. An
envelope without a usable status maps to nothing at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from typing import Final

from backend.canonical.domain_records import PowerCurveFetch, PowerCurvePoint
from backend.canonical.local_time import parse_provider_datetime
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import ProviderId, RecordingOrigin, SourceKind
from backend.providers.intervals_power import POWER_CURVE_LABEL

MAPPER_VERSION: Final = 1
_POINT_OK: Final = "ok"


@dataclass(frozen=True, slots=True)
class PowerCurveMapping:
    """The fetch and the points of one envelope; None means keep what is stored."""

    fetch: PowerCurveFetch | None = None
    points: tuple[PowerCurvePoint, ...] | None = None


def _day(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _provenance(source_record_id: str, retrieved_at: datetime | None) -> Provenance:
    return Provenance(
        provider=ProviderId.INTERVALS,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=source_record_id,
        recorded_by=RecordingOrigin.UNKNOWN,
        retrieved_at=retrieved_at,
        label=POWER_CURVE_LABEL,
    )


def _fetch(
    envelope: Mapping[str, object],
    window: tuple[date, date] | None,
    provenance: Provenance,
) -> PowerCurveFetch | None:
    status = envelope.get("status")
    if not isinstance(status, str):
        return None
    try:
        return PowerCurveFetch(
            fetch_status=status,
            window_start=None if window is None else window[0],
            window_end=None if window is None else window[1],
            provenance=provenance,
        )
    except TypeError, ValueError:
        return None


def _point(
    point: object, *, window: tuple[date, date], provenance: Provenance
) -> PowerCurvePoint | None:
    if not isinstance(point, Mapping) or point.get("status") != _POINT_OK:
        return None
    day = _day(point.get("date"))
    duration, watts = point.get("duration_seconds"), point.get("watts")
    activity = point.get("activity_id")
    if day is None or duration is None or watts is None:
        return None
    if not window[0] <= day <= window[1]:
        return None
    try:
        return PowerCurvePoint(
            duration_s=duration,
            watts=watts,
            observed_on=day,
            provider_activity_id=activity
            if isinstance(activity, str) and activity
            else None,
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
) -> PowerCurveMapping:
    """Return the fetch and the best power per duration of one stored envelope."""
    if not isinstance(envelope, Mapping):
        return PowerCurveMapping()
    synced_at = parse_provider_datetime(envelope.get("synced_at"), zone)
    start, end = _day(envelope.get("start")), _day(envelope.get("end"))
    window = (start, end) if start is not None and end is not None else None
    if window is not None and window[0] > window[1]:
        window = None
    fetch = _fetch(envelope, window, _provenance(source_record_id, synced_at))
    rows = envelope.get("points")
    if fetch is None or window is None or not isinstance(rows, list):
        return PowerCurveMapping(fetch=fetch)
    provenance = _provenance(source_record_id, synced_at or fetched_at)
    mapped: dict[int, PowerCurvePoint] = {}
    for item in rows:
        point = _point(item, window=window, provenance=provenance)
        if point is not None and point.duration_s not in mapped:
            mapped[point.duration_s] = point
    return PowerCurveMapping(
        fetch=fetch, points=tuple(mapped[duration] for duration in sorted(mapped))
    )
