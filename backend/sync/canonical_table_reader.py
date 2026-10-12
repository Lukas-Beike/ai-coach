"""Canonical reader over the canonical tables, without any provider client or sync.

Reads the stored rows only, so the last stored data stays readable with no provider
configured and no sync performed. Served records are the ones the legacy projection
would return for the same data:

- activities: ``active`` activity records whose session is not ``deleted``. Invalid
  and deleted records are never served.
- observations: rows whose ``mapper_version`` equals the current version of their
  provider. Observations have no state column, so a row that an upgraded mapper no
  longer emits is recognised by its old version and is not served.

Results use the same inclusive bounds and the same total order as
``CanonicalSnapshotProjection``. Activity bounds filter the stored athlete-local
date, which the ingest computed with the athlete's zone at write time.

Mapping issue counts are not stored in the tables, so this reader does not
implement ``ProviderCoverageReader``. ``CanonicalReadSelector`` keeps coverage on
the legacy projection.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Final

from backend.canonical.ordering import activity_order, observation_order
from backend.canonical.records import (
    ActivityRecord,
    MetricValue,
    Observation,
    Provenance,
)
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.db import canonical_store
from backend.providers.canonical_plans import current_observation_mapper_versions
from backend.providers.garmin_activity_mapping import GARMIN_LABEL
from backend.providers.intervals_activity_mapping import INTERVALS_LABEL
from backend.runtime.ports import ActivityReader, ObservationReader

_ACTIVITY_LABELS: Final[Mapping[ProviderId, str]] = {
    ProviderId.INTERVALS: INTERVALS_LABEL,
    ProviderId.GARMIN: GARMIN_LABEL,
}


class CanonicalTableReader(ActivityReader, ObservationReader):
    """Serves canonical activities and observations from the stored tables."""

    def activities(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[ActivityRecord, ...]:
        rows = canonical_store.active_activity_rows(
            db, start=_iso(start), end=_iso(end)
        )
        return tuple(sorted((_activity(row) for row in rows), key=activity_order))

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        rows = canonical_store.current_observation_rows(
            db,
            kind.value,
            current_observation_mapper_versions(),
            start=_iso(start),
            end=_iso(end),
            sport=None if sport is None else sport.value,
        )
        return tuple(sorted((_observation(row) for row in rows), key=observation_order))


def _iso(day: date | None) -> str | None:
    return None if day is None else day.isoformat()


def _optional_datetime(text: object) -> datetime | None:
    return None if text is None else datetime.fromisoformat(str(text))


def _activity(row: Mapping[str, Any]) -> ActivityRecord:
    provider = ProviderId(row["provider"])
    return ActivityRecord(
        activity_id=str(row["provider_activity_id"]),
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind(row["source_kind"]),
            source_record_id=row["source_record_id"],
            recorded_by=RecordingOrigin(row["recorded_by"]),
            # The row's own fetch time. Garmin sections keep their own fetch time.
            retrieved_at=datetime.fromisoformat(str(row["fetched_at"])),
            label=_ACTIVITY_LABELS[provider],
        ),
        sport=Sport(row["sport"]),
        environment=Environment(row["environment"]),
        started_at=datetime.fromisoformat(str(row["started_at"])),
        duration_s=row["duration_s"],
        distance_m=row["distance_m"],
        load=row["load"],
        load_model=LoadModel(row["load_model"]),
        avg_hr=row["avg_hr"],
        avg_power=row["avg_power"],
        name=row["name"],
    )


def _observation(row: Mapping[str, Any]) -> Observation:
    provider = row["provider"]
    return Observation(
        kind=MetricKind(row["metric"]),
        value=MetricValue(value=row["value"], unit=row["unit"]),
        observed_on=date.fromisoformat(str(row["observed_on"])),
        observed_at=_optional_datetime(row["observed_at"]),
        provenance=Provenance(
            provider=None if provider is None else ProviderId(provider),
            source_kind=SourceKind(row["source_kind"]),
            source_record_id=row["source_record_id"],
            recorded_by=RecordingOrigin(row["recorded_by"]),
            retrieved_at=_optional_datetime(row["retrieved_at"]),
            label=row["label"],
        ),
        sport=None if row["sport"] is None else Sport(row["sport"]),
    )
