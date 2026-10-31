"""Shared synthetic recovery observations and a recording reader for recovery tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from activity_row_support import summaries_of_rows

from backend.canonical.domain_records import SleepPeriod
from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.performance.canonical_recovery import (
    RECOVERY_KINDS,
    CanonicalRecoveryInputs,
)
from backend.providers.garmin_health_mapping import map_garmin_health
from backend.providers.intervals_wellness_mapping import map_intervals_wellness
from backend.providers.sleep_period_mapping import map_sleep_periods

RETRIEVED = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
UNITS = {
    MetricKind.SLEEP_SCORE: "score",
    MetricKind.RESTING_HR: "bpm",
    MetricKind.READINESS: "score",
    MetricKind.HRV_RMSSD: "ms",
    MetricKind.HRV_SDNN: "ms",
    MetricKind.HRV_WEEKLY_AVERAGE: "ms",
    MetricKind.SLEEP_DURATION: "s",
    MetricKind.CTL: "load",
    MetricKind.ATL: "load",
}


def recovery_observation(
    kind: MetricKind,
    value: float,
    day: str,
    provider: ProviderId = ProviderId.GARMIN,
    record_id: str | None = None,
) -> Observation:
    """Return a provider-reported recovery observation for one local day."""
    recorded_by = (
        RecordingOrigin.GARMIN
        if provider is ProviderId.GARMIN
        else RecordingOrigin.MANUAL
    )
    return Observation(
        kind=kind,
        value=MetricValue(value, UNITS.get(kind, kind.unit)),
        observed_on=date.fromisoformat(day),
        observed_at=None,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=record_id or f"{kind.value}-{day}",
            recorded_by=recorded_by,
            retrieved_at=RETRIEVED,
            label=None,
        ),
    )


class RecordingReader:
    """Serves fixed observations per kind and records each read."""

    def __init__(self, by_kind: dict[MetricKind, list[Observation]]) -> None:
        self._by_kind = by_kind
        self.calls: list[tuple[MetricKind, date | None, date | None]] = []

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        self.calls.append((kind, start, end))
        return tuple(self._by_kind.get(kind, []))


_LATEST_ROW: Any = object()


def recovery_inputs(
    observations: Iterable[Observation] = (),
    *,
    latest_wellness_day: date | None = None,
    sleep_periods: tuple[SleepPeriod, ...] | None = None,
) -> CanonicalRecoveryInputs:
    """Group synthetic recovery observations into canonical recovery inputs."""
    by_kind: dict[MetricKind, list[Observation]] = {}
    for observation in observations:
        by_kind.setdefault(observation.kind, []).append(observation)
    return CanonicalRecoveryInputs(
        observations={kind: tuple(by_kind.get(kind, ())) for kind in RECOVERY_KINDS},
        latest_wellness_day=latest_wellness_day,
        sleep_periods=sleep_periods,
    )


def mapped_sleep_periods(
    garmin: Mapping[str, Any] | None, wellness: list[dict[str, Any]] | None
) -> tuple[SleepPeriod, ...]:
    """Map the raw Garmin sleep elements and wellness rows to canonical periods."""
    sleep = (garmin or {}).get("sleep")
    elements = sleep if isinstance(sleep, list) else [sleep] if sleep else []
    periods: list[SleepPeriod] = []
    for index, element in enumerate(elements):
        periods.extend(
            map_sleep_periods(
                element,
                provider=ProviderId.GARMIN,
                source_record_id=f"sleep/{index}",
                retrieved_at=RETRIEVED,
                zone=ZoneInfo("Europe/Berlin"),
            )
        )
    for index, row in enumerate(wellness or []):
        periods.extend(
            map_sleep_periods(
                row,
                provider=ProviderId.INTERVALS,
                source_record_id=str(row.get("id") or index),
                retrieved_at=RETRIEVED,
                zone=ZoneInfo("Europe/Berlin"),
            )
        )
    return tuple(periods)


def mapped_recovery_inputs(
    garmin: Mapping[str, Any] | None = None,
    wellness: list[dict[str, Any]] | None = None,
    *,
    latest_wellness_day: Any = _LATEST_ROW,
) -> CanonicalRecoveryInputs:
    """Map raw Garmin sections and wellness rows with the real provider mappers.

    The legacy recovery tests keep their raw fixtures; this turns them into the
    canonical observations a sync would store. The latest wellness day defaults to
    the newest strict ``YYYY-MM-DD`` row id, as the canonical performance inputs
    derive it.
    """
    observations: list[Observation] = []
    if garmin:
        observations.extend(
            map_garmin_health(
                dict(garmin), zone=ZoneInfo("Europe/Berlin"), retrieved_at=RETRIEVED
            ).records
        )
    rows = list(wellness or [])
    if rows:
        observations.extend(
            map_intervals_wellness(rows, retrieved_at=RETRIEVED).records
        )
    if latest_wellness_day is _LATEST_ROW:
        latest_wellness_day = max(
            (day for day in map(_row_day, rows) if day is not None), default=None
        )
    return recovery_inputs(
        observations,
        latest_wellness_day=latest_wellness_day,
        sleep_periods=mapped_sleep_periods(garmin, rows),
    )


def _row_day(row: Mapping[str, Any]) -> date | None:
    text = row.get("id")
    if not isinstance(text, str) or len(text) != 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def mapped_personal_recovery(
    wellness: list[dict[str, Any]],
    garmin: dict[str, Any],
    profile: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    """Run personal recovery on the observations and sleep periods the raw fixtures map to."""
    from backend.performance.personal_recovery import personal_recovery

    return personal_recovery(
        profile, today, canonical=mapped_recovery_inputs(garmin, wellness)
    )


def recovery_only_inputs(
    garmin: Mapping[str, Any] | None = None,
    wellness: list[dict[str, Any]] | None = None,
    snapshot: Mapping[str, Any] | None = None,
) -> Any:
    """Return performance inputs for a context test that changes only some sources.

    The inputs carry the mapped recovery observations and the Garmin metrics mapped
    from ``garmin`` (#1415). With a ``snapshot`` they also carry what the
    Intervals.icu observations of that snapshot give for form, ramp rate and the
    current athlete settings (#1412, #1415), and the snapshot's activity rows as
    the activity reader serves them; ctl and atl stay on the snapshot rows.
    """
    from dataclasses import replace

    from canonical_daily_health_support import mapped_health
    from performance_day_support import (
        garmin_metrics_from_payload,
        snapshot_coverage_time,
        snapshot_retrieved_at,
    )

    from backend.performance.canonical_inputs import (
        CanonicalPerformanceInputs,
        read_performance_inputs,
    )
    from backend.providers.snapshot_projection import project_intervals_snapshot

    inputs = CanonicalPerformanceInputs(
        wellness_day=None,
        ctl=None,
        atl=None,
        recovery=mapped_recovery_inputs(garmin, wellness),
        garmin=None if garmin is None else garmin_metrics_from_payload(dict(garmin)),
        # Daily totals come only from observations (#1415).
        daily_health=None if garmin is None else mapped_health(dict(garmin)),
    )
    if snapshot is None:
        return inputs
    _activities, mapped = project_intervals_snapshot(
        snapshot,
        zone=ZoneInfo("Europe/Berlin"),
        retrieved_at=snapshot_retrieved_at(dict(snapshot), RETRIEVED),
    )
    full = read_performance_inputs(
        FilteringReader(tuple(mapped.records)),
        None,
        activity_reader=SnapshotActivityRows(snapshot),
        as_of=RETRIEVED.date(),
    )
    if full is None:
        return inputs
    return replace(
        inputs,
        wellness_day=full.wellness_day,
        form_by_day=full.form_by_day,
        eftp_by_day=full.eftp_by_day,
        ramp_rate=full.ramp_rate,
        current=full.current,
        activities=full.activities,
        # The stored wellness days mark the provider data as present (#1416).
        history_wellness_days=full.history_wellness_days,
        # The sync stores its fetch time with the canonical coverage (#1416).
        intervals_synced_at=snapshot_coverage_time(snapshot),
    )


class SnapshotActivityRows:
    """Serves the activity rows of a stored Intervals.icu snapshot."""

    def __init__(self, snapshot: Mapping[str, Any]) -> None:
        self._rows = tuple(snapshot.get("recent_activities") or ())

    def activity_summaries(self, db: Any, **bounds: Any) -> tuple[Any, ...]:
        return summaries_of_rows(self._rows)


class NoActivityRows:
    """An activity row reader without rows: the activities stay on the snapshot."""

    def activity_summaries(self, db: Any, **bounds: Any) -> tuple[Any, ...]:
        return ()

    def activity_rows(self, db: Any, **bounds: Any) -> tuple[Any, ...]:
        return ()


class FilteringReader:
    """Serves observations by kind, inclusive observed_on window and sport."""

    def __init__(self, observations: tuple[Observation, ...]) -> None:
        self._observations = observations

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        return tuple(
            observation
            for observation in self._observations
            if observation.kind is kind
            and (start is None or start <= observation.observed_on)
            and (end is None or observation.observed_on <= end)
            and (sport is None or observation.sport is sport)
        )
