"""Canonical reader over the stored Intervals.icu snapshot and Garmin payload.

The projection is computed once and reused while its inputs are unchanged. The
cache key is the Intervals.icu snapshot version, a SHA-256 digest of the Garmin
payload and the athlete's time zone, so a new sync, changed Garmin data or a
zone change recomputes it. Provider keys and mappers live in
``backend.providers.snapshot_projection``; this module names providers only
through the canonical ``ProviderId`` enum.

Mapping issues are counted per provider for ``ProviderCoverage``. They are never
logged and never returned by the record readers.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from itertools import chain
from typing import Any

from backend.canonical.coverage import ProviderCoverage, count_issues
from backend.canonical.local_time import local_date
from backend.canonical.mapping import MappingResult
from backend.canonical.records import ActivityRecord, Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.providers.snapshot_projection import (
    project_garmin_snapshot,
    project_intervals_snapshot,
    stored_retrieved_at,
)
from backend.runtime.ports import (
    ActivityReader,
    ObservationReader,
    ProviderCoverageReader,
)

type _CacheKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class _Source:
    provider: ProviderId
    stored_at: datetime | None
    activities: MappingResult[ActivityRecord]
    observations: MappingResult[Observation]


@dataclass(frozen=True, slots=True)
class _Projection:
    activities: tuple[ActivityRecord, ...]
    observations: tuple[Observation, ...]
    coverage: tuple[ProviderCoverage, ...]
    # True when a provider had no stored sync time, so the clock supplied the
    # retrieval time and the athlete-local dates. Such a projection depends on
    # the clock, which is not part of the cache key, so it is never cached.
    clock_dependent: bool


class CanonicalSnapshotProjection(
    ActivityReader, ObservationReader, ProviderCoverageReader
):
    """Serves canonical activities, observations and coverage from snapshots.

    ``intervals_snapshot`` and ``garmin_payload`` return the stored documents,
    ``intervals_version`` returns a string that changes whenever the Intervals.icu
    snapshot changes, and ``zone`` returns the athlete's time zone. ``clock``
    supplies the retrieval time for input that has no stored sync time.

    The version and the snapshot are read by separate callbacks. This is safe
    only if the writer commits the snapshot before it changes the version: a
    reader that sees a new version then reads the matching or newer snapshot.
    A writer that bumps the version first could let a reader cache the old
    snapshot under the new version until the next version change.

    Coverage ``retrieved_at`` is None when the provider has no stored sync time.
    Records from that provider carry the clock fallback as provenance instead.
    """

    def __init__(
        self,
        *,
        intervals_snapshot: Callable[[Any], dict[str, Any] | None],
        intervals_version: Callable[[Any], str],
        garmin_payload: Callable[[Any], dict[str, Any]],
        zone: Callable[[Any], tzinfo],
        clock: Callable[[], datetime],
    ) -> None:
        self._intervals_snapshot = intervals_snapshot
        self._intervals_version = intervals_version
        self._garmin_payload = garmin_payload
        self._zone = zone
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: tuple[_CacheKey, _Projection] | None = None

    def activities(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[ActivityRecord, ...]:
        projection, zone = self._current(db)
        return tuple(
            record
            for record in projection.activities
            if _in_range(local_date(record.started_at, zone), start, end)
        )

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        projection, _zone = self._current(db)
        return tuple(
            observation
            for observation in projection.observations
            if observation.kind == kind
            and _in_range(observation.observed_on, start, end)
            and (sport is None or observation.sport == sport)
        )

    def coverage(self, db: Any) -> tuple[ProviderCoverage, ...]:
        projection, _zone = self._current(db)
        return projection.coverage

    def _current(self, db: Any) -> tuple[_Projection, tzinfo]:
        with self._lock:
            zone = self._zone(db)
            payload = self._garmin_payload(db)
            key = (self._intervals_version(db), _digest(payload), str(zone))
            cached = self._cache
            if cached is None or cached[0] != key:
                projection = self._compute(db, payload, zone)
                if projection.clock_dependent:
                    self._cache = None
                    return projection, zone
                cached = (key, projection)
                self._cache = cached
            return cached[1], zone

    def _compute(self, db: Any, payload: dict[str, Any], zone: tzinfo) -> _Projection:
        snapshot = self._intervals_snapshot(db)
        fallback = self._clock()
        intervals_stored = stored_retrieved_at(snapshot, zone=zone)
        garmin_stored = stored_retrieved_at(payload, zone=zone)
        intervals_activities, intervals_observations = project_intervals_snapshot(
            snapshot,
            zone=zone,
            retrieved_at=_or_else(intervals_stored, fallback),
        )
        garmin_activities, garmin_observations = project_garmin_snapshot(
            payload,
            zone=zone,
            retrieved_at=_or_else(garmin_stored, fallback),
        )
        sources = (
            _Source(
                ProviderId.INTERVALS,
                intervals_stored,
                intervals_activities,
                intervals_observations,
            ),
            _Source(
                ProviderId.GARMIN,
                garmin_stored,
                garmin_activities,
                garmin_observations,
            ),
        )
        return _Projection(
            activities=tuple(
                sorted(
                    chain.from_iterable(s.activities.records for s in sources),
                    key=_activity_order,
                )
            ),
            observations=tuple(
                sorted(
                    chain.from_iterable(s.observations.records for s in sources),
                    key=_observation_order,
                )
            ),
            coverage=tuple(_coverage(source) for source in sources),
            clock_dependent=intervals_stored is None or garmin_stored is None,
        )


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _or_else(value: datetime | None, fallback: datetime) -> datetime:
    return fallback if value is None else value


def _in_range(day: date, start: date | None, end: date | None) -> bool:
    return (start is None or day >= start) and (end is None or day <= end)


def _activity_order(record: ActivityRecord) -> tuple[datetime, str, str]:
    provenance = record.provenance
    return (
        record.started_at,
        str(provenance.provider or ""),
        provenance.source_record_id or "",
    )


def _observation_order(observation: Observation) -> tuple[date, str, str]:
    provenance = observation.provenance
    return (
        observation.observed_on,
        str(provenance.provider or ""),
        str(observation.kind),
    )


def _coverage(source: _Source) -> ProviderCoverage:
    days = [observation.observed_on for observation in source.observations.records]
    return ProviderCoverage(
        provider=source.provider,
        retrieved_at=source.stored_at,
        activity_count=len(source.activities.records),
        observation_count=len(source.observations.records),
        issue_counts=count_issues(
            (*source.activities.issues, *source.observations.issues)
        ),
        first_observed_on=min(days, default=None),
        last_observed_on=max(days, default=None),
    )
