"""Build canonical day views from synthetic Intervals rows through the real mapper."""

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind
from backend.performance.canonical_inputs import read_performance_inputs
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


def canonical_from_snapshot(snapshot: dict[str, Any], as_of: date):
    """Map synthetic snapshot rows through the production mapper and read ports."""
    _, mapped = project_intervals_snapshot(
        snapshot, zone=ZoneInfo("UTC"), retrieved_at=SYNCED_AT
    )
    observations = tuple(mapped.records)

    class Reader:
        def observations(self, _db, kind, *, start=None, end=None, sport=None):
            return tuple(
                item
                for item in observations
                if item.kind is kind
                and (start is None or item.observed_on >= start)
                and (end is None or item.observed_on <= end)
                and (sport is None or item.sport is sport)
            )

    class ActivityReader:
        def activity_rows(self, _db, *, start=None, end=None, limit=None):
            return tuple(snapshot.get("recent_activities") or ())

    return read_performance_inputs(
        Reader(), object(), activity_reader=ActivityReader(), as_of=as_of
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

        def activities(self, _db, *, start=None, end=None):
            return tuple(activities)

    reader = Reader()
    return read_garmin_state(reader, object(), activities=reader).metrics
