"""Choose the canonical read source: nothing yet, or the canonical tables.

The tables serve reads once the backfill has completed at least once
(``read_state``). Before that, for example right after an upgrade from a released
schema, every read returns nothing: no partial values are shown while the data is
being prepared. A pending, running or failed first backfill reads nothing.

After the first completion reads stay on the tables. A mapper upgrade or a zone
change still makes the worker re-project the stored raw records; meanwhile the
selector serves the tables through a reader that returns each observation at the
newest version stored for it, so nothing vanishes. Once the re-projection
completes, only observations at the current mapper version are served.

Raw activity rows (``intervals_activity_payloads``) follow the same decision as ``activities``.
A stored Intervals.icu snapshot that lists activities only in compact form (from a
release before ``raw_provider_data``) cannot be backfilled; its activities stay
missing from the tables until the full read-only Intervals.icu reload returns raw
rows for them. An incremental sync keeps the older compact rows next to its raw
window. ``activities_need_refresh`` reports that gap.

Tables keep serving after a sync, because the ingest writes each new snapshot
into the tables in the same transaction. While the tables serve, the stored
snapshot omits the activity sections the tables hold (``canonical_sections``
marker, see ``SnapshotStorage``).

Coverage is served from the summary each ingest persists
(``canonical_coverage:<provider>``, see ``canonical_coverage_store``), because
mapping issue counts are not stored in the tables. Before the first completed
backfill only current summaries are reported; afterwards the last persisted
summary is reported even when it predates a mapper or zone change. A provider
without one is omitted. Only the providers the ingest writes coverage for are
consulted.

An old ``canonical_read_state`` record, with its parity counts, is never read or
written and stays in place.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, tzinfo
from typing import Any, Final, cast

from backend.activities.activity_summary import ActivitySummary, activity_summaries
from backend.activities.session_purpose import with_competitions
from backend.canonical.activity_summary import summary_local_date
from backend.canonical.coverage import MetricWindow, ProviderCoverage
from backend.canonical.domain_records import (
    EMPTY_POWER_CURVE,
    PowerCurve,
    SleepPeriod,
)
from backend.canonical.records import ActivityRecord, Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.db.repositories import CompetitionRepository, KeyValueRepository
from backend.runtime.ports import (
    ActivityReader,
    ActivityRowReader,
    ActivitySummaryReader,
    CanonicalReader,
    ObservationSourceSelector,
    ProviderActivityKey,
    ProviderCoverageReader,
    SessionRecords,
)
from backend.sync.canonical_backfill import (
    BackfillStatus,
    ReadState,
    read_state,
    read_status,
)
from backend.sync.canonical_coverage_store import (
    CANONICAL_COVERAGE_PROVIDERS,
    LIVE_COVERAGE_PROVIDERS,
    CanonicalCoverageStore,
)
from backend.sync.local_load import (
    daily_local_loads,
    stored_local_loads,
    with_local_loads,
)

REASON_COMPLETE: Final = "backfill_complete"
REASON_PENDING: Final = "backfill_pending"


class _PendingReader:
    """The reader served before the first completed backfill: every read is empty."""

    def activities(
        self, db: Any, *, start: date | None = None, end: date | None = None
    ) -> tuple[ActivityRecord, ...]:
        del db, start, end
        return ()

    def activity_max_hr(
        self, db: Any, provider: ProviderId, *, low: float, high: float
    ) -> tuple[tuple[Sport, float, date], ...]:
        del db, provider, low, high
        return ()

    def intervals_activity_payloads(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        del db, start, end, limit
        return ()

    def activity_sessions(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        newest: int | None = None,
    ) -> tuple[SessionRecords, ...]:
        del db, start, end, newest
        return ()

    def summary_fingerprints(
        self, db: Any, keys: Iterable[ProviderActivityKey]
    ) -> dict[ProviderActivityKey, str]:
        del db, keys
        return {}

    def intervals_summary_row(
        self, db: Any, provider_activity_id: str
    ) -> dict[str, Any] | None:
        del db, provider_activity_id
        return None

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        del db, kind, start, end, sport
        return ()

    def sleep_periods(
        self, db: Any, *, start: date | None = None, end: date | None = None
    ) -> tuple[SleepPeriod, ...]:
        del start, end, db
        return ()

    def power_curve(self, db: Any) -> PowerCurve:
        del db
        return EMPTY_POWER_CURVE

    def metric_windows(self, db: Any) -> tuple[MetricWindow, ...]:
        del db
        return ()


PENDING_READER: Final[CanonicalReader] = _PendingReader()


class CanonicalReadSelector(
    ActivityReader,
    ActivityRowReader,
    ActivitySummaryReader,
    ObservationSourceSelector,
    ProviderCoverageReader,
):
    """Serves reads from the tables once the backfill completed once, else nothing.

    ``zone`` returns the athlete's time zone, the one the backfill stores with its
    state. ``compact_only`` returns True when a compact activity row of the stored
    Intervals.icu snapshot has no raw counterpart.
    """

    def __init__(
        self,
        *,
        table: CanonicalReader,
        reprojecting_table: CanonicalReader,
        key_values: KeyValueRepository,
        zone: Callable[[Any], tzinfo],
        compact_only: Callable[[Any], bool],
        competitions: CompetitionRepository,
    ) -> None:
        self._zone = zone
        self._competitions = competitions
        self._compact_only = compact_only
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

    def activity_max_hr(
        self, db: Any, provider: ProviderId, *, low: float, high: float
    ) -> tuple[tuple[Sport, float, date], ...]:
        return self._source(db).activity_max_hr(db, provider, low=low, high=high)

    def intervals_activity_payloads(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return raw activity rows from the same source as ``activities``."""
        return self._source(db).intervals_activity_payloads(
            db, start=start, end=end, limit=limit
        )

    def summary_fingerprints(
        self, db: Any, keys: Iterable[ProviderActivityKey]
    ) -> dict[ProviderActivityKey, str]:
        """Return current summary fingerprints from the serving source."""
        return self._source(db).summary_fingerprints(db, keys)

    def intervals_summary_row(
        self, db: Any, provider_activity_id: str
    ) -> dict[str, Any] | None:
        """Return one stored Intervals.icu payload from the serving source."""
        return self._source(db).intervals_summary_row(db, provider_activity_id)

    def activities_need_refresh(self, db: Any) -> bool:
        """Return True while a stored compact activity row has no raw counterpart.

        Those activities never reach the tables; the full read-only Intervals.icu
        reload that returns their raw rows closes the gap.
        """
        return self._compact_only(db)

    def activity_summaries(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> tuple[ActivitySummary, ...]:
        """Return one neutral summary per session, newest first.

        ``training_load`` and ``intensity`` are the stored local load (card M6);
        stored competitions mark and link their races (``with_competitions``).
        """
        source = self._source(db)
        summaries = activity_summaries(
            source.activity_sessions(db, start=start, end=end, newest=limit),
            self._zone(db),
            limit=limit,
        )
        loaded = with_local_loads(
            summaries,
            stored_local_loads(db, (summary["id"] for summary in summaries)),
        )
        days = sorted(filter(None, (summary_local_date(row) for row in loaded)))
        if not days:
            return cast(tuple[ActivitySummary, ...], loaded)
        competitions = self._competitions.between(db, days[0], days[-1])
        if not competitions:
            return cast(tuple[ActivitySummary, ...], loaded)
        # A limit can cut the oldest day: link over all its sessions, so the
        # race hint never depends on the page size.
        whole_day: tuple[ActivitySummary, ...] = ()
        if limit is not None:
            oldest = date.fromisoformat(days[0])
            whole_day = activity_summaries(
                source.activity_sessions(db, start=oldest, end=oldest),
                self._zone(db),
            )
        page = {str(row["id"]) for row in loaded}
        linked = {
            str(row["id"]): row
            for row in with_competitions(
                [
                    *loaded,
                    *(row for row in whole_day if str(row["id"]) not in page),
                ],
                competitions,
            )
        }
        return cast(
            tuple[ActivitySummary, ...],
            tuple(linked[str(row["id"])] for row in loaded),
        )

    def local_load_days(self, db: Any) -> dict[str, float]:
        """Return the stored local session load (card M6) summed per local day.

        Empty before the first completed backfill, as every other read.
        """
        if self._read_state(db) is ReadState.PENDING:
            return {}
        return daily_local_loads(db)

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

        Before the first completed backfill only a current persisted summary is
        reported (none when mapper versions or the time zone changed since);
        afterwards the last persisted summary is reported as it is. A provider
        without one is omitted. Live-ingested providers follow the same rule and
        come last.
        """
        zone = self._zone(db)
        completed = self._read_state(db) is not ReadState.PENDING
        return tuple(
            summary
            for provider in (*CANONICAL_COVERAGE_PROVIDERS, *LIVE_COVERAGE_PROVIDERS)
            if (
                summary := self._coverage_store.load(
                    db, provider, zone=zone, allow_outdated=completed
                )
            )
            is not None
        )

    def metric_windows(self, db: Any) -> tuple[MetricWindow, ...]:
        """Return per-metric counts from the source that serves observations.

        Before the first completed backfill nothing is reported; afterwards the
        serving tables are counted.
        """
        return self._source(db).metric_windows(db)

    def serves_tables(self, db: Any) -> bool:
        """Return True while observation and activity reads come from the tables."""
        return self._read_state(db) is not ReadState.PENDING

    def backfill_failed(self, db: Any) -> bool:
        """Return whether the backfill most recently failed."""
        return read_status(self._key_values, db) == BackfillStatus.FAILED

    def summary(self, db: Any) -> dict[str, Any]:
        """Return the content-free switch state for diagnostics.

        ``digest_current`` is False while a mapper or zone change is re-projected.
        """
        state = self._read_state(db)
        serving = state is not ReadState.PENDING
        return {
            "serving": "tables" if serving else "pending",
            "reason": REASON_COMPLETE if serving else REASON_PENDING,
            "digest_current": state is ReadState.TABLES,
        }

    def _source(self, db: Any) -> CanonicalReader:
        state = self._read_state(db)
        if state is ReadState.PENDING:
            return PENDING_READER
        if state is ReadState.TABLES_REPROJECTING:
            return self._reprojecting_table
        return self._table

    def _read_state(self, db: Any) -> ReadState:
        return read_state(self._key_values, db, zone=self._zone(db))
