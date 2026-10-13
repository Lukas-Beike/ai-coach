"""Choose the canonical read source: the legacy projection or the canonical tables.

The tables serve reads if and only if ``backfill_complete`` is True at read time:
the backfill status is ``complete`` and its stored mapper versions and time zone
equal the current ones (the tables hold local dates computed in the zone of the
write). Nothing else gates the switch. A mapper upgrade or a zone change makes the
backfill incomplete again until the worker re-projects, and reads fall back to the
legacy projection meanwhile; a pending, running or failed backfill does the same.

Raw activity rows (``activity_rows``) follow the same decision as ``activities``.

Tables keep serving after a sync, because the ingest writes each new snapshot
into the tables in the same transaction.

Parity is diagnostic only. The worker calls ``refresh`` when the backfill
completes and at startup; it records the parity counts, but a mismatch never
forces legacy reads.

Coverage is served from the summary each ingest persists
(``canonical_coverage:<provider>``, see ``canonical_coverage_store``), because
mapping issue counts are not stored in the tables. A provider without a current
summary falls back to the legacy projection. Only the providers the ingest
writes coverage for are consulted.

The record in the ``canonical_read_state`` key is content-free and diagnostic:
the last source, a reason word, the digest, the parity counts and, on failure,
only an exception class name. A corrupt record reads as empty and never changes
which source serves.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Final

from backend.canonical.coverage import ProviderCoverage
from backend.canonical.records import ActivityRecord, Observation
from backend.canonical.vocabulary import MetricKind, Sport
from backend.db.repositories import KeyValueRepository
from backend.providers.canonical_plans import current_mapper_versions
from backend.runtime.ports import (
    ActivityReader,
    ActivityRowReader,
    CanonicalReadRefresher,
    ObservationSourceSelector,
    ProviderCoverageReader,
)
from backend.sync.canonical_backfill import backfill_complete
from backend.sync.canonical_coverage_store import (
    CANONICAL_COVERAGE_PROVIDERS,
    LIVE_COVERAGE_PROVIDERS,
    CanonicalCoverageStore,
)
from backend.sync.canonical_parity import CanonicalParity, CanonicalReader
from backend.sync.canonical_projection import CanonicalSnapshotProjection

STATE_KEY: Final = "canonical_read_state"
SOURCE_TABLES: Final = "tables"
SOURCE_LEGACY: Final = "legacy"
REASON_COMPLETE: Final = "backfill_complete"
REASON_PENDING: Final = "backfill_pending"
REASON_ERROR: Final = "error"


class CanonicalReadSelector(
    ActivityReader,
    ActivityRowReader,
    ObservationSourceSelector,
    ProviderCoverageReader,
    CanonicalReadRefresher,
):
    """Serves reads from the tables once the backfill is complete, else from legacy."""

    def __init__(
        self,
        *,
        legacy: CanonicalSnapshotProjection,
        table: CanonicalReader,
        parity: CanonicalParity,
        key_values: KeyValueRepository,
    ) -> None:
        self._legacy = legacy
        self._table = table
        self._parity = parity
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
        if source is self._table and self._legacy.has_only_compact_activity_rows(db):
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

        A provider without a current persisted summary (nothing ingested yet, or
        mapper versions or time zone changed since) falls back to the legacy
        projection, which is computed only when at least one provider needs it.
        A live-ingested provider (no legacy snapshot) is appended when present.
        """
        zone = self._legacy.zone(db)
        stored = {
            provider: self._coverage_store.load(db, provider, zone=zone)
            for provider in CANONICAL_COVERAGE_PROVIDERS
        }
        live = tuple(
            summary
            for provider in LIVE_COVERAGE_PROVIDERS
            if (summary := self._coverage_store.load(db, provider, zone=zone))
            is not None
        )
        if all(summary is not None for summary in stored.values()):
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
        return self._serves_tables(db)

    def refresh(self, db: Any) -> None:
        """Record the diagnostic parity counts; the result never gates reads."""
        if not self._serves_tables(db):
            self._store(db, {"source": SOURCE_LEGACY, "reason": REASON_PENDING})
            return
        digest = self._digest(db)
        report = self._parity.check(db)
        self._store(
            db,
            {
                "source": SOURCE_TABLES,
                "reason": REASON_COMPLETE,
                "digest": digest,
                "parity": report.as_dict(),
            },
        )

    def record_failure(self, db: Any, error_class: str) -> None:
        self._store(
            db,
            {
                "source": SOURCE_LEGACY,
                "reason": REASON_ERROR,
                "error_class": error_class,
            },
        )

    def summary(self, db: Any) -> dict[str, Any]:
        """Return the content-free switch state for diagnostics."""
        state = self._state(db)
        serving = self._serves_tables(db)
        return {
            "serving": "tables" if serving else "legacy",
            "reason": REASON_COMPLETE if serving else REASON_PENDING,
            "digest_current": state.get("digest") == self._digest(db),
            "parity": state.get("parity"),
        }

    def _source(self, db: Any) -> CanonicalReader:
        return self._table if self._serves_tables(db) else self._legacy

    def _serves_tables(self, db: Any) -> bool:
        return backfill_complete(self._key_values, db, zone=self._legacy.zone(db))

    def _digest(self, db: Any) -> str:
        """Digest of the inputs a recorded parity result describes: mappers and zone."""
        payload = {
            "mapper_versions": current_mapper_versions(),
            "zone": str(self._legacy.zone(db)),
        }
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _state(self, db: Any) -> dict[str, Any]:
        raw = self._key_values.get(db, STATE_KEY)
        if raw is None:
            return {}
        try:
            loaded = json.loads(raw)
        except ValueError:
            # A corrupt switch record is unchecked, so reads stay on legacy.
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _store(self, db: Any, state: dict[str, Any]) -> None:
        self._key_values.set(
            db, STATE_KEY, json.dumps(state, sort_keys=True, separators=(",", ":"))
        )
