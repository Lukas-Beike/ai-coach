"""Choose the canonical read source: the legacy projection or the canonical tables.

The tables serve reads once the backfill has completed at least once
(``read_state``); the legacy snapshot projection serves only an installation whose
backfill never completed, for example right after an upgrade from a released
schema. A pending, running or failed first backfill reads from legacy.

After the first completion reads never go back to legacy. A mapper upgrade or a
zone change still makes the worker re-project the stored raw records; meanwhile
the selector serves the tables through a reader that returns each observation at
the newest version stored for it, so nothing vanishes. Once the re-projection
completes, only observations at the current mapper version are served.

Raw activity rows (``activity_rows``) follow the same decision as ``activities``,
except that a snapshot listing activities only in compact form stays on legacy: the
backfill cannot map those rows.

Tables keep serving after a sync, because the ingest writes each new snapshot
into the tables in the same transaction. While the tables serve, the stored
snapshot omits the activity sections the tables hold (``canonical_sections``
marker, see ``SnapshotStorage``).

Coverage is served from the summary each ingest persists
(``canonical_coverage:<provider>``, see ``canonical_coverage_store``), because
mapping issue counts are not stored in the tables. Before the first completed
backfill a provider without a current summary falls back to the legacy projection;
afterwards the last persisted summary is reported even when it predates a mapper
or zone change, and a provider without one is omitted. Only the providers the
ingest writes coverage for are consulted.

An old ``canonical_read_state`` record, with its parity counts, is never read or
written and stays in place.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Final

from backend.canonical.coverage import ProviderCoverage
from backend.canonical.records import ActivityRecord, Observation
from backend.canonical.vocabulary import MetricKind, Sport
from backend.db.repositories import KeyValueRepository
from backend.runtime.ports import (
    ActivityReader,
    ActivityRowReader,
    CanonicalReader,
    ObservationSourceSelector,
    ProviderCoverageReader,
)
from backend.sync.canonical_backfill import ReadState, read_state
from backend.sync.canonical_coverage_store import (
    CANONICAL_COVERAGE_PROVIDERS,
    LIVE_COVERAGE_PROVIDERS,
    CanonicalCoverageStore,
)
from backend.sync.canonical_projection import CanonicalSnapshotProjection

REASON_COMPLETE: Final = "backfill_complete"
REASON_PENDING: Final = "backfill_pending"


class CanonicalReadSelector(
    ActivityReader,
    ActivityRowReader,
    ObservationSourceSelector,
    ProviderCoverageReader,
):
    """Serves reads from the tables once the backfill completed once, else from legacy."""

    def __init__(
        self,
        *,
        legacy: CanonicalSnapshotProjection,
        table: CanonicalReader,
        reprojecting_table: CanonicalReader,
        key_values: KeyValueRepository,
    ) -> None:
        self._legacy = legacy
        self._table = table
        self._reprojecting_table = reprojecting_table
        self._key_values = key_values
        self._coverage_store = CanonicalCoverageStore(key_values)

    def activities(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[ActivityRecord, ...]:
        return self._source(db).activities(db, start=start, end=end)

    def activity_rows(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return raw activity rows from the same source as ``activities``.

        A snapshot that lists activities only in compact form stays on legacy: the
        backfill cannot map those rows, so the tables would serve none of them.
        """
        source: CanonicalReader = self._source(db)
        if source is not self._legacy and self._legacy.has_only_compact_activity_rows(
            db
        ):
            source = self._legacy
        return source.activity_rows(db, start=start, end=end, limit=limit)

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        return self._source(db).observations(
            db, kind, start=start, end=end, sport=sport
        )

    def reader_for(self, db: Any) -> CanonicalReader:
        """Choose the serving source once for several reads in one unit of work."""
        return self._source(db)

    def coverage(self, db: Any) -> tuple[ProviderCoverage, ...]:
        """Return the coverage persisted at ingest time.

        Before the first completed backfill, a provider without a current
        persisted summary (nothing ingested yet, or mapper versions or time zone
        changed since) falls back to the legacy projection, which is computed only
        when at least one provider needs it. Afterwards the last persisted summary
        is reported as it is, and a provider without one is omitted.
        A live-ingested provider (no legacy snapshot) is appended when present.
        """
        zone = self._legacy.zone(db)
        completed = self._read_state(db) is not ReadState.LEGACY
        stored = {
            provider: self._coverage_store.load(
                db, provider, zone=zone, allow_outdated=completed
            )
            for provider in CANONICAL_COVERAGE_PROVIDERS
        }
        live = tuple(
            summary
            for provider in LIVE_COVERAGE_PROVIDERS
            if (
                summary := self._coverage_store.load(
                    db, provider, zone=zone, allow_outdated=completed
                )
            )
            is not None
        )
        if completed or all(summary is not None for summary in stored.values()):
            persisted = tuple(s for s in stored.values() if s is not None)
            return persisted + live
        return (
            tuple(
                stored.get(summary.provider) or summary
                for summary in self._legacy.coverage(db)
            )
            + live
        )

    def serves_tables(self, db: Any) -> bool:
        """Return True while observation and activity reads come from the tables."""
        return self._read_state(db) is not ReadState.LEGACY

    def summary(self, db: Any) -> dict[str, Any]:
        """Return the content-free switch state for diagnostics.

        ``digest_current`` is False while a mapper or zone change is re-projected.
        """
        state = self._read_state(db)
        serving = state is not ReadState.LEGACY
        return {
            "serving": "tables" if serving else "legacy",
            "reason": REASON_COMPLETE if serving else REASON_PENDING,
            "digest_current": state is ReadState.TABLES,
        }

    def _source(self, db: Any) -> CanonicalReader:
        state = self._read_state(db)
        if state is ReadState.LEGACY:
            return self._legacy
        if state is ReadState.TABLES_REPROJECTING:
            return self._reprojecting_table
        return self._table

    def _read_state(self, db: Any) -> ReadState:
        return read_state(self._key_values, db, zone=self._legacy.zone(db))
