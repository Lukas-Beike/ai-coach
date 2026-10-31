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

from backend.activities.canonical_sessions import bundle_sessions
from backend.canonical.coverage import (
    MetricWindow,
    ProviderCoverage,
    summarize_provider,
)
from backend.canonical.local_time import local_date
from backend.canonical.mapping import MappingResult
from backend.canonical.ordering import activity_order, observation_order
from backend.canonical.records import ActivityRecord, Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.providers.snapshot_projection import (
    intervals_activity_rows,
    intervals_row_local_date,
    intervals_snapshot_has_only_compact_rows,
    project_garmin_snapshot,
    project_intervals_snapshot,
    stored_retrieved_at,
)
from backend.runtime.ports import (
    ActivityReader,
    ActivityRowReader,
    ActivitySessionReader,
    ObservationReader,
    ProviderCoverageReader,
    SessionRecords,
)

type _CacheKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class _Source:
    provider: ProviderId
    stored_at: datetime | None
    activities: MappingResult[ActivityRecord]
    observations: MappingResult[Observation]
    activities_retrieved_at: datetime | None
    observations_retrieved_at: datetime | None


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
    ActivityReader,
    ActivityRowReader,
    ActivitySessionReader,
    ObservationReader,
    ProviderCoverageReader,
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

    def activity_sessions(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        newest: int | None = None,
    ) -> tuple[SessionRecords, ...]:
        """Bundle the projected records into sessions with the duplicate rules.

        ``newest`` is accepted for the port; the projection is in memory already.

        The projection has no local session ids, so a session is named by its
        primary record's provider activity id.
        """
        del newest
        zone = self._zone(db)
        return tuple(
            (session.primary.activity_id, (session.primary, *session.duplicates))
            for session in bundle_sessions(
                self.activities(db, start=start, end=end), zone=zone
            )
        )

    def activity_max_hr(
        self, db: Any, provider: ProviderId, *, low: float, high: float
    ) -> tuple[tuple[Sport, float, date], ...]:
        """Return each sport's highest projected max heart rate and its newest day."""
        projection, zone = self._current(db)
        best: dict[Sport, tuple[float, date]] = {}
        for record in projection.activities:
            value = record.max_hr
            if (
                record.provenance.provider is not provider
                or value is None
                or not low <= value <= high
            ):
                continue
            candidate = (value, local_date(record.started_at, zone))
            best[record.sport] = max(best.get(record.sport, candidate), candidate)
        return tuple(
            (sport, value, day) for sport, (value, day) in sorted(best.items())
        )

    def activity_rows(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return the stored raw Intervals.icu activity rows, in snapshot order.

        These are the rows the report readers start from, before de-duplication.
        Without bounds every row is returned. With a bound, a row is kept when the
        activity mapper gives it an athlete-local date inside the bounds; a row the
        mapper rejects has no date and is then left out. ``limit`` keeps the
        first rows after the bounds.
        """
        rows = intervals_activity_rows(self._intervals_snapshot(db))
        if start is not None or end is not None:
            zone = self._zone(db)
            retrieved_at = self._clock()
            rows = tuple(
                row
                for row in rows
                if _row_in_range(row, zone, retrieved_at, start=start, end=end)
            )
        return rows if limit is None else rows[:limit]

    def has_only_compact_activity_rows(self, db: Any) -> bool:
        """Return True when the stored snapshot lists activities only in compact form."""
        return intervals_snapshot_has_only_compact_rows(self._intervals_snapshot(db))

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

    def metric_windows(self, db: Any) -> tuple[MetricWindow, ...]:
        """Return no per-metric windows: the legacy projection keeps none.

        Per-metric counts exist only in the canonical tables, so before the first
        completed backfill the diagnostics report no metrics.
        """
        return ()

    def zone(self, db: Any) -> tzinfo:
        """Return the athlete's time zone, the one the projection's dates use."""
        return self._zone(db)

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
        activities_stored = (
            stored_retrieved_at(
                {"synced_at": snapshot.get("activities_synced_at")}, zone=zone
            )
            if isinstance(snapshot, dict) and "activities_synced_at" in snapshot
            else intervals_stored
        )
        garmin_stored = stored_retrieved_at(payload, zone=zone)
        intervals_activities, _unused_observations = project_intervals_snapshot(
            snapshot,
            zone=zone,
            retrieved_at=_or_else(activities_stored, fallback),
        )
        _unused_activities, intervals_observations = project_intervals_snapshot(
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
                activities_stored,
                intervals_stored,
            ),
            _Source(
                ProviderId.GARMIN,
                garmin_stored,
                garmin_activities,
                garmin_observations,
                garmin_stored,
                garmin_stored,
            ),
        )
        return _Projection(
            activities=tuple(
                sorted(
                    chain.from_iterable(s.activities.records for s in sources),
                    key=activity_order,
                )
            ),
            observations=tuple(
                sorted(
                    chain.from_iterable(s.observations.records for s in sources),
                    key=observation_order,
                )
            ),
            coverage=tuple(_coverage(source) for source in sources),
            clock_dependent=(
                activities_stored is None
                or intervals_stored is None
                or garmin_stored is None
            ),
        )


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _or_else(value: datetime | None, fallback: datetime) -> datetime:
    return fallback if value is None else value


def _in_range(day: date, start: date | None, end: date | None) -> bool:
    return (start is None or day >= start) and (end is None or day <= end)


def _row_in_range(
    row: dict[str, Any],
    zone: tzinfo,
    retrieved_at: datetime,
    *,
    start: date | None,
    end: date | None,
) -> bool:
    day = intervals_row_local_date(row, zone=zone, retrieved_at=retrieved_at)
    return day is not None and _in_range(day, start, end)


def _coverage(source: _Source) -> ProviderCoverage:
    return summarize_provider(
        source.provider,
        source.stored_at,
        source.activities,
        source.observations,
        activities_retrieved_at=source.activities_retrieved_at,
        observations_retrieved_at=source.observations_retrieved_at,
    )
