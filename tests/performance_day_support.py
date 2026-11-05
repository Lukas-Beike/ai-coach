"""Build canonical day views from synthetic Intervals rows through the real mapper."""

from dataclasses import fields, replace
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.activities.activity_summary import ActivitySummary, activity_summaries
from backend.canonical.local_time import local_date
from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.performance.canonical_body import read_body_inputs
from backend.performance.canonical_current import (
    CanonicalCurrentInputs,
    read_current_inputs,
)
from backend.performance.canonical_inputs import (
    CanonicalPerformanceInputs,
    read_performance_inputs,
)
from backend.performance.current_metrics import current_performance_metrics
from backend.performance.freshness import GarminSyncStatus
from backend.performance.garmin_canonical import (
    GarminCanonicalMetrics,
    read_garmin_state,
)
from backend.performance.wellness_days import WellnessDay, current_window, latest
from backend.providers.garmin_activity_mapping import (
    map_garmin_activities,
    merge_training_load_rows,
)
from backend.providers.garmin_health_mapping import map_garmin_health
from backend.providers.intervals_activity_mapping import map_intervals_activities
from backend.providers.intervals_wellness_mapping import map_intervals_wellness
from backend.providers.snapshot_projection import project_intervals_snapshot

UTC_ZONE = ZoneInfo("UTC")
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


# Garmin metric key -> (kind, sport) of its threshold observation.
_GARMIN_THRESHOLD_KEYS = {
    "cycling_ftp_watts": (MetricKind.FTP, Sport.RIDE),
    "run_threshold_watts": (MetricKind.FTP, Sport.RUN),
    "bike_threshold_hr_bpm": (MetricKind.THRESHOLD_HR, Sport.RIDE),
    "run_threshold_hr_bpm": (MetricKind.THRESHOLD_HR, Sport.RUN),
    "run_threshold_pace_seconds_per_km": (MetricKind.THRESHOLD_PACE, Sport.RUN),
    "cycling_max_hr_bpm": (MetricKind.MAX_HR, Sport.RIDE),
    "running_max_hr_bpm": (MetricKind.MAX_HR, Sport.RUN),
}


def garmin_threshold_observations(
    garmin: dict[str, dict[str, Any]],
) -> tuple[Observation, ...]:
    """The Garmin threshold observations behind a Garmin metrics dict, dated today.

    Production reads both from the same Garmin observations; a payload-built dict
    needs them added. An activity-derived max heart rate (it carries an
    ``observed_at``) is not a threshold.
    """
    result = []
    for key, (kind, sport) in _GARMIN_THRESHOLD_KEYS.items():
        entry = garmin.get(key) or {}
        value = entry.get("value")
        if value is None or (kind is MetricKind.MAX_HR and entry.get("observed_at")):
            continue
        if kind is MetricKind.THRESHOLD_PACE:
            value = 1000 / value
        result.append(
            Observation(
                kind=kind,
                value=MetricValue(float(value), kind.unit),
                observed_on=SYNCED_AT.date(),
                observed_at=None,
                provenance=Provenance(
                    provider=ProviderId.GARMIN,
                    source_kind=SourceKind.PROVIDER_REPORTED,
                    source_record_id=f"garmin-{key}",
                    recorded_by=RecordingOrigin.GARMIN,
                    retrieved_at=SYNCED_AT,
                    label=None,
                ),
                sport=sport,
            )
        )
    return tuple(result)


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

    Without ``activities`` the summaries of the snapshot's ``recent_activities``
    stand in for the canonical activity summaries. A given ``canonical`` replaces
    the snapshot's read.
    """
    if activities is None:
        activities = list(snapshot_activity_summaries(snapshot))
    return current_performance_metrics(
        profile,
        garmin,
        canonical=_overlaid(
            current_from_snapshot(
                snapshot,
                latest_wellness=latest_wellness,
                extra=(
                    *extra,
                    # A Wahoo FTP overlay is a stored observation the read resolves.
                    *(
                        ()
                        if canonical is None or canonical.wahoo_ftp is None
                        else (canonical.wahoo_ftp,)
                    ),
                ),
            ),
            canonical,
        ),
        activities=activities,
        latest_wellness=latest_wellness,
        garmin_thresholds=garmin_threshold_observations(garmin),
        as_of=SYNCED_AT.date(),
    )


def _overlaid(
    read: CanonicalCurrentInputs, overlay: CanonicalCurrentInputs | None
) -> CanonicalCurrentInputs:
    if overlay is None:
        return read
    values = {
        item.name: getattr(overlay, item.name)
        for item in fields(overlay)
        # An empty mapping (the default resolved thresholds) keeps the read's.
        if getattr(overlay, item.name) not in (None, ())
        and getattr(overlay, item.name) != {}
    }
    return replace(read, **values)


def intervals_activity_summaries(
    rows: list[dict[str, Any]], zone: ZoneInfo = UTC_ZONE
) -> tuple[ActivitySummary, ...]:
    """Summaries of synthetic Intervals.icu rows, mapped like production."""
    mapped = map_intervals_activities(rows, zone=zone, retrieved_at=SYNCED_AT)
    return activity_summaries(
        ((f"act_{record.activity_id}", [record]) for record in mapped.records), zone
    )


def snapshot_activity_summaries(
    snapshot: dict[str, Any],
) -> tuple[ActivitySummary, ...]:
    """Summaries of a synthetic snapshot's compact activity rows."""
    return intervals_activity_summaries(snapshot.get("recent_activities") or [])


def snapshot_coverage_time(snapshot: Any) -> str | None:
    """The Intervals.icu coverage time a sync of the snapshot stores, if any."""
    try:
        synced = datetime.fromisoformat(str((snapshot or {}).get("synced_at") or ""))
    except ValueError:
        return None
    return synced.isoformat() if synced.tzinfo is not None else None


def snapshot_retrieved_at(
    snapshot: dict[str, Any], default: datetime = SYNCED_AT
) -> datetime:
    """The fetch time a sync stamps a snapshot's observations with: its sync time."""
    try:
        synced = datetime.fromisoformat(str(snapshot.get("synced_at") or ""))
    except ValueError:
        return default
    return synced if synced.tzinfo is not None else default


def canonical_from_snapshot(snapshot: dict[str, Any], as_of: date):
    """Map synthetic snapshot rows through the production mapper and read ports."""
    _, mapped = project_intervals_snapshot(
        snapshot, zone=ZoneInfo("UTC"), retrieved_at=snapshot_retrieved_at(snapshot)
    )

    class ActivityReader:
        def activity_summaries(self, _db, *, start=None, end=None, limit=None):
            return snapshot_activity_summaries(snapshot)

    inputs = read_performance_inputs(
        StubReader(tuple(mapped.records)),
        object(),
        activity_reader=ActivityReader(),
        as_of=as_of,
    )
    if inputs is None:
        return None
    # The sync stores its fetch time with the canonical coverage (#1416).
    return replace(inputs, intervals_synced_at=snapshot_coverage_time(snapshot))


def garmin_metrics_from_payload(
    payload: dict[str, Any], *, retrieved_at: datetime = SYNCED_AT
) -> GarminCanonicalMetrics:
    """Map a synthetic Garmin payload and its activities through the real mappers."""
    zone = ZoneInfo("UTC")
    observations = map_garmin_health(
        dict(payload), zone=zone, retrieved_at=retrieved_at
    ).records
    activities = map_garmin_activities(
        payload.get("activities") or [], zone=zone, retrieved_at=retrieved_at
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


def garmin_body_from_payload(
    payload: dict[str, Any], today: date, *, retrieved_at: datetime = SYNCED_AT
):
    """Map a synthetic Garmin payload and read its canonical weight and body fat."""
    observations = map_garmin_health(
        dict(payload), zone=ZoneInfo("UTC"), retrieved_at=retrieved_at
    ).records
    return read_body_inputs(StubReader(tuple(observations)), None, today)


def garmin_inputs_from_payload(
    payload: dict[str, Any], today: date, base: CanonicalPerformanceInputs
) -> CanonicalPerformanceInputs:
    """``base`` with the canonical Garmin values and body of a synthetic payload."""
    return replace(
        base,
        garmin=garmin_metrics_from_payload(payload),
        body=garmin_body_from_payload(payload, today),
    )


def garmin_activity_summaries(
    payload: dict[str, Any], zone: ZoneInfo = UTC_ZONE
) -> tuple[ActivitySummary, ...]:
    """Summaries of a synthetic Garmin payload's activities, as a sync stores them.

    The dedicated training-load rows are merged in first, and one activity id is
    one record, as in the activity tables.
    """
    rows = merge_training_load_rows(
        payload.get("activities") or [], payload.get("training_load_activities")
    )
    mapped = map_garmin_activities(rows, zone=zone, retrieved_at=SYNCED_AT)
    records = {record.activity_id: record for record in mapped.records}
    return activity_summaries(
        ((f"act_garmin_{key}", [record]) for key, record in records.items()), zone
    )


def garmin_sync_status(payload: dict[str, Any]) -> GarminSyncStatus:
    """The sync status of a synthetic payload: its sections count as stored."""
    return GarminSyncStatus.from_state(payload)
