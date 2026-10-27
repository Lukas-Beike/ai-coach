"""Shared synthetic recovery observations and a recording reader for recovery tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

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
) -> CanonicalRecoveryInputs:
    """Group synthetic recovery observations into canonical recovery inputs."""
    by_kind: dict[MetricKind, list[Observation]] = {}
    for observation in observations:
        by_kind.setdefault(observation.kind, []).append(observation)
    return CanonicalRecoveryInputs(
        observations={kind: tuple(by_kind.get(kind, ())) for kind in RECOVERY_KINDS},
        latest_wellness_day=latest_wellness_day,
    )


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
    return recovery_inputs(observations, latest_wellness_day=latest_wellness_day)


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
    """Run personal recovery on the observations the raw fixtures map to.

    Sleep timing variability still reads the raw records (#1419), so they are passed too.
    """
    from backend.performance.personal_recovery import personal_recovery

    return personal_recovery(
        wellness,
        garmin,
        profile,
        today,
        canonical=mapped_recovery_inputs(garmin, wellness),
    )


def recovery_only_inputs(
    garmin: Mapping[str, Any] | None = None,
    wellness: list[dict[str, Any]] | None = None,
) -> Any:
    """Return performance inputs that carry only the mapped recovery observations.

    Without a wellness day the load, threshold and Garmin metric readers keep the
    snapshot path, so a context test changes only its recovery source.
    """
    from backend.performance.canonical_inputs import CanonicalPerformanceInputs

    return CanonicalPerformanceInputs(
        wellness_day=None,
        ctl=None,
        atl=None,
        recovery=mapped_recovery_inputs(garmin, wellness),
    )
