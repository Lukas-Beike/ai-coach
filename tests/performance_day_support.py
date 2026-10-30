"""Build canonical day views from synthetic Intervals rows through the real mapper."""

from dataclasses import fields, replace
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.canonical.local_time import local_date
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind
from backend.performance.canonical_current import (
    CanonicalCurrentInputs,
    read_current_inputs,
)
from backend.performance.canonical_inputs import read_performance_inputs
from backend.performance.current_metrics import current_performance_metrics
from backend.performance.garmin_canonical import (
    GarminCanonicalMetrics,
    read_garmin_state,
)
from backend.performance.wellness_days import WellnessDay, current_window, latest
from backend.providers.garmin_activity_mapping import map_garmin_activities
from backend.providers.garmin_health_mapping import map_garmin_health
from backend.providers.intervals_wellness_mapping import map_intervals_wellness
from backend.providers.snapshot_projection import project_intervals_snapshot

SYNCED_AT = datetime(2026, 10, 12, 8, tzinfo=UTC)


def days_from_rows(rows: list[dict[str, Any]]) -> tuple[WellnessDay, ...]:
    mapped = map_intervals_wellness(rows, retrieved_at=SYNCED_AT)
    by_day: dict[Any, dict[MetricKind, Observation]] = {}
    for observation in mapped.records:
        if (
            observation.sport is None
            and observation.provenance.source_record_id
            == observation.observed_on.isoformat()
        ):
            by_day.setdefault(observation.observed_on, {})[observation.kind] = (
                observation
            )
    return tuple(WellnessDay(day, by_day[day]) for day in sorted(by_day))


def current_days(rows: list[dict[str, Any]]) -> tuple[WellnessDay, ...]:
    return current_window(days_from_rows(rows))


def latest_day(rows: list[dict[str, Any]]) -> WellnessDay | None:
    return latest(current_days(rows))


class StubReader:
    """Serves observations by kind, inclusive observed_on window and sport."""

    def __init__(self, observations: tuple[Observation, ...]) -> None:
        self._observations = observations

    def observations(self, _db, kind, *, start=None, end=None, sport=None):
        return tuple(
            item
            for item in self._observations
            if item.kind is kind
            and (start is None or item.observed_on >= start)
            and (end is None or item.observed_on <= end)
            and (sport is None or item.sport is sport)
        )


def current_from_snapshot(
    snapshot: dict[str, Any],
    *,
    latest_wellness: WellnessDay | None = None,
    extra: tuple[Observation, ...] = (),
) -> CanonicalCurrentInputs:
    """Read the current inputs of a synthetic snapshot through the real mapper."""
    _, mapped = project_intervals_snapshot(
        snapshot, zone=ZoneInfo("UTC"), retrieved_at=SYNCED_AT
    )
    return read_current_inputs(
        StubReader((*mapped.records, *extra)),
        None,
        latest_wellness_day=None if latest_wellness is None else latest_wellness.day,
        as_of=SYNCED_AT.date(),
    )


def snapshot_metrics(
    snapshot: dict[str, Any],
    profile: dict[str, Any],
    garmin: dict[str, dict[str, Any]],
    *,
    activities: list[Any] | None = None,
    latest_wellness: WellnessDay | None = None,
    extra: tuple[Observation, ...] = (),
    canonical: CanonicalCurrentInputs | None = None,
) -> dict[str, dict[str, Any]]:
    """Current metrics of a synthetic snapshot: mapper, canonical read, composition.

    Without ``activities`` the snapshot's ``recent_activities`` stand in for the
    canonical activity rows. A given ``canonical`` replaces the snapshot's read.
    """
    if activities is None:
        stored = snapshot.get("recent_activities")
        activities = stored if isinstance(stored, list) else []
    return current_performance_metrics(
        profile,
        garmin,
        canonical=_overlaid(
            current_from_snapshot(
                snapshot, latest_wellness=latest_wellness, extra=extra
            ),
            canonical,
        ),
        activities=activities,
        latest_wellness=latest_wellness,
    )


def _overlaid(
    read: CanonicalCurrentInputs, overlay: CanonicalCurrentInputs | None
) -> CanonicalCurrentInputs:
    if overlay is None:
        return read
    values = {
        item.name: getattr(overlay, item.name)
        for item in fields(overlay)
        if getattr(overlay, item.name) not in (None, ())
    }
    return replace(read, **values)


def canonical_from_snapshot(snapshot: dict[str, Any], as_of: date):
    """Map synthetic snapshot rows through the production mapper and read ports."""
    _, mapped = project_intervals_snapshot(
        snapshot, zone=ZoneInfo("UTC"), retrieved_at=SYNCED_AT
    )

    class ActivityReader:
        def activity_rows(self, _db, *, start=None, end=None, limit=None):
            return tuple(snapshot.get("recent_activities") or ())

    return read_performance_inputs(
        StubReader(tuple(mapped.records)),
        object(),
        activity_reader=ActivityReader(),
        as_of=as_of,
    )


def garmin_metrics_from_payload(payload: dict[str, Any]) -> GarminCanonicalMetrics:
    """Map a synthetic Garmin payload and its activities through the real mappers."""
    zone = ZoneInfo("UTC")
    observations = map_garmin_health(
        dict(payload), zone=zone, retrieved_at=SYNCED_AT
    ).records
    activities = map_garmin_activities(
        payload.get("activities") or [], zone=zone, retrieved_at=SYNCED_AT
    ).records

    class Reader:
        def observations(self, _db, kind, *, start=None, end=None, sport=None):
            return tuple(item for item in observations if item.kind is kind)

        def activity_max_hr(self, _db, provider, *, low, high):
            best: dict[Any, tuple[float, date]] = {}
            for record in activities:
                value = record.max_hr
                if value is None or not low <= value <= high:
                    continue
                candidate = (value, local_date(record.started_at, zone))
                best[record.sport] = max(best.get(record.sport, candidate), candidate)
            return tuple((sport, *best[sport]) for sport in best)

    return read_garmin_state(Reader(), object()).metrics
