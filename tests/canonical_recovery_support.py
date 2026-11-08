"""Shared synthetic recovery observations and a recording reader for recovery tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from activity_row_support import summaries_of_rows
from intervals_wellness_stub import map_intervals_wellness

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
from backend.performance.local_tss import DatedThresholds, LocalLoad, session_loads
from backend.providers.garmin_health_mapping import map_garmin_health
from backend.providers.sleep_period_mapping import map_sleep_periods
from backend.sync.local_load import with_local_loads

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


def recovery_inputs(
    observations: Iterable[Observation] = (),
    *,
    sleep_periods: tuple[SleepPeriod, ...] | None = None,
) -> CanonicalRecoveryInputs:
    """Group synthetic recovery observations into canonical recovery inputs."""
    by_kind: dict[MetricKind, list[Observation]] = {}
    for observation in observations:
        by_kind.setdefault(observation.kind, []).append(observation)
    return CanonicalRecoveryInputs(
        observations={kind: tuple(by_kind.get(kind, ())) for kind in RECOVERY_KINDS},
        sleep_periods=sleep_periods,
    )


def mapped_sleep_periods(
    garmin: Mapping[str, Any] | None,
    wellness: list[dict[str, Any]] | None,
    wellness_provider: ProviderId = ProviderId.INTERVALS,
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
                provider=wellness_provider,
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
    wellness_provider: ProviderId = ProviderId.INTERVALS,
) -> CanonicalRecoveryInputs:
    """Map raw Garmin sections and wellness rows with the real provider mappers.

    The legacy recovery tests keep their raw fixtures; this turns them into the
    canonical observations a sync would store. The latest wellness day defaults to
    the newest strict ``YYYY-MM-DD`` row id, as the canonical performance inputs
    derive it. ``wellness_provider`` is the provider the daily rows are stored
    under: Intervals.icu is no recovery source, so a test of the baseline, deficit
    and timing logic stores them as Garmin days.
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
            replace(
                record,
                provenance=replace(record.provenance, provider=wellness_provider),
            )
            for record in map_intervals_wellness(rows, retrieved_at=RETRIEVED).records
            if isinstance(record, Observation)
        )
    return recovery_inputs(
        observations,
        sleep_periods=mapped_sleep_periods(garmin, rows, wellness_provider),
    )


def mapped_personal_recovery(
    wellness: list[dict[str, Any]],
    garmin: dict[str, Any],
    profile: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    """Run personal recovery on the observations and sleep periods the raw fixtures map to."""
    from backend.performance.personal_recovery import personal_recovery

    return personal_recovery(
        profile,
        today,
        canonical=mapped_recovery_inputs(
            garmin, wellness, wellness_provider=ProviderId.GARMIN
        ),
    )


def recovery_only_inputs(
    garmin: Mapping[str, Any] | None = None,
    wellness: list[dict[str, Any]] | None = None,
    snapshot: Mapping[str, Any] | None = None,
    *,
    wellness_provider: ProviderId = ProviderId.INTERVALS,
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
    from intervals_plan_stub import project_intervals_snapshot
    from performance_day_support import (
        garmin_metrics_from_payload,
        snapshot_retrieved_at,
    )

    from backend.performance.canonical_inputs import (
        CanonicalPerformanceInputs,
        read_performance_inputs,
    )

    inputs = CanonicalPerformanceInputs(
        recovery=mapped_recovery_inputs(
            garmin, wellness, wellness_provider=wellness_provider
        ),
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
        activity_reader=SnapshotActivityRows(snapshot, mapped.records),
        as_of=RETRIEVED.date(),
    )
    if full is None:
        return inputs
    return replace(
        inputs,
        current=full.current,
        activities=full.activities,
    )


def with_local_load_of(
    summaries: Iterable[Mapping[str, Any]], observations: Iterable[Observation]
) -> tuple[dict[str, Any], ...]:
    """The summaries as the reader serves them after a local load pass (card M6).

    The local load is computed from ``observations`` (the mapped thresholds and
    resting HR) the way the stage stores it, then set on the summaries.
    """
    listed = tuple(summaries)
    observed = tuple(observations)
    thresholds = DatedThresholds(
        observed,
        resting_hr=[item for item in observed if item.kind is MetricKind.RESTING_HR],
    )
    stored: dict[str, dict[str, Any]] = {}
    for session_id, load in session_loads(listed, thresholds).items():
        if not isinstance(load, LocalLoad):
            continue
        rows = {
            MetricKind.SESSION_LOAD.value: {
                "value": load.load,
                "derivation": dict(load.details),
                "method_version": 1,
            }
        }
        if load.intensity_pct is not None:
            rows[MetricKind.INTENSITY_FACTOR.value] = {
                "value": load.intensity_pct,
                "derivation": dict(load.details),
                "method_version": 1,
            }
        stored[session_id] = rows
    return with_local_loads(listed, stored)


class SnapshotActivityRows:
    """Serves the activity rows of a stored Intervals.icu snapshot.

    With ``observations`` the summaries carry the local load a pass would store.
    """

    def __init__(
        self, snapshot: Mapping[str, Any], observations: Iterable[Observation] = ()
    ) -> None:
        self._rows = tuple(snapshot.get("recent_activities") or ())
        self._observations = tuple(observations)

    def activity_summaries(self, db: Any, **bounds: Any) -> tuple[Any, ...]:
        return with_local_load_of(summaries_of_rows(self._rows), self._observations)


class NoActivityRows:
    """An activity row reader without rows: the activities stay on the snapshot."""

    def activity_summaries(self, db: Any, **bounds: Any) -> tuple[Any, ...]:
        return ()

    def summary_fingerprints(self, db: Any, keys: Any) -> dict[Any, str]:
        return {}


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
