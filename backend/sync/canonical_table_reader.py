"""Canonical reader over the canonical tables, without any provider client or sync.

Reads the stored rows only, so the last stored data stays readable with no provider
configured and no sync performed. Served records are the ones the legacy projection
would return for the same data:

- activities: ``active`` activity records whose session is not ``deleted``. Invalid
  and deleted records are never served.
- activity rows: the stored raw Intervals.icu payloads of those same activities.
- observations: rows whose ``mapper_version`` equals the current version of their
  provider. Observations have no state column, so a row that an upgraded mapper no
  longer emits is recognised by its old version and is not served. While a
  re-projection is pending (``oldest_versions``) rows that still carry a version
  between the one of the last completed run and the current one are served too: a
  natural key has one row, so each identity is served at the newest version stored
  for it and nothing vanishes meanwhile. Rows retired before the last completed run
  carry an older version and stay hidden. A
  mapper that moves a measurement to a different natural key leaves the old-key row
  next to the new one until the re-projection completes, so that one measurement
  can briefly appear twice.

Results use the same inclusive bounds and the same total order as
``CanonicalSnapshotProjection``. Activity bounds filter the stored athlete-local
date, which the ingest computed with the athlete's zone at write time.

Mapping issue counts are not stored in the tables, so this reader does not
implement ``ProviderCoverageReader``. ``CanonicalReadSelector`` serves coverage
from the summaries persisted at ingest.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
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
from backend.providers.canonical_plans import (
    ACTIVITY_RECORD_KIND,
    current_observation_mapper_versions,
)
from backend.providers.garmin_activity_mapping import GARMIN_LABEL
from backend.providers.intervals_activity_mapping import INTERVALS_LABEL
from backend.providers.wahoo_activity_mapping import WAHOO_LABEL
from backend.runtime.ports import ActivityReader, ActivityRowReader, ObservationReader

_ACTIVITY_LABELS: Final[Mapping[ProviderId, str]] = {
    ProviderId.INTERVALS: INTERVALS_LABEL,
    ProviderId.GARMIN: GARMIN_LABEL,
    ProviderId.WAHOO: WAHOO_LABEL,
}


class CanonicalTableReader(ActivityReader, ActivityRowReader, ObservationReader):
    """Serves canonical activities, raw activity rows and observations from the tables."""

    def __init__(
        self, *, oldest_versions: Callable[[Any], Mapping[str, int]] | None = None
    ) -> None:
        self._oldest_versions = oldest_versions

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

    def activity_rows(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return the stored raw Intervals.icu payloads of live activities.

        Newest first, like the stored snapshot (activity start, then provider
        activity id, both descending). The stored payload
        is the ingest-sanitized one: credential-like keys and signed URLs are
        already removed. ``limit`` is applied in SQL before any payload is read.
        A payload that does not parse as a JSON object is skipped; its content
        is never logged.
        """
        texts = canonical_store.active_activity_payload_texts(
            db,
            provider=ProviderId.INTERVALS.value,
            record_kind=ACTIVITY_RECORD_KIND,
            start=_iso(start),
            end=_iso(end),
            limit=limit,
        )
        parsed = (_payload_object(text) for text in texts)
        return tuple(row for row in parsed if row is not None)

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
            oldest_versions=(
                None if self._oldest_versions is None else self._oldest_versions(db)
            ),
        )
        return tuple(sorted((_observation(row) for row in rows), key=observation_order))


def _payload_object(text: str) -> dict[str, Any] | None:
    try:
        loaded = json.loads(text)
    except ValueError, RecursionError:
        return None
    return loaded if isinstance(loaded, dict) else None


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
        moving_duration_s=row["moving_duration_s"],
        elevation_gain_m=row["elevation_gain_m"],
        normalized_power=row["normalized_power"],
        avg_cadence=row["avg_cadence"],
        energy_kj=row["energy_kj"],
        elapsed_duration_s=canonical_store.activity_elapsed_duration(row["details"]),
        max_hr=canonical_store.activity_max_hr(row["details"]),
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
