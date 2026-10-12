"""Choose the canonical read source: the legacy projection or the canonical tables.

The tables serve reads only when all of these hold at read time:

- the canonical backfill status is ``complete``;
- the last parity check passed; and
- the digest it checked equals the current digest. The digest covers only the
  activity and observation mapper versions and the athlete's time zone. A
  mapper upgrade or a zone change therefore falls back to legacy until the next
  parity check.

A new snapshot does not change the digest. Tables keep serving after a sync,
because the ingest writes each new snapshot into the tables in the same
transaction. The parity check is not re-run after every sync. It runs when the
backfill completes and at startup (the worker calls ``refresh``), so a
divergence that the dual-write did not catch is found at the next check, not
immediately.

Otherwise reads come from the legacy projection, which is always correct. Coverage
is served from the summary each ingest persists (``canonical_coverage:<provider>``,
see ``canonical_coverage_store``), because mapping issue counts are not stored in
the tables. A provider without a current summary falls back to the legacy
projection.

The switch state is a content-free record in the ``canonical_read_state`` key. It
holds the source, a reason word, the digest, the parity counts and, on failure,
only an exception class name. A corrupt record is treated as unchecked.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Final

from backend.canonical.coverage import ProviderCoverage
from backend.canonical.records import ActivityRecord, Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.db.repositories import KeyValueRepository
from backend.providers.canonical_plans import current_mapper_versions
from backend.runtime.ports import (
    ActivityReader,
    CanonicalReadRefresher,
    ObservationSourceSelector,
    ProviderCoverageReader,
)
from backend.sync.canonical_backfill import BackfillStatus, read_status
from backend.sync.canonical_coverage_store import CanonicalCoverageStore
from backend.sync.canonical_parity import CanonicalParity, CanonicalReader
from backend.sync.canonical_projection import CanonicalSnapshotProjection

STATE_KEY: Final = "canonical_read_state"
SOURCE_TABLES: Final = "tables"
SOURCE_LEGACY: Final = "legacy"


class CanonicalReadSelector(
    ActivityReader,
    ObservationSourceSelector,
    ProviderCoverageReader,
    CanonicalReadRefresher,
):
    """Serves reads from the tables after a passing parity check, else from legacy."""

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
        """
        zone = self._legacy.zone(db)
        stored = {
            provider: self._coverage_store.load(db, provider, zone=zone)
            for provider in ProviderId
        }
        if all(summary is not None for summary in stored.values()):
            return tuple(summary for summary in stored.values() if summary is not None)
        return tuple(
            stored.get(summary.provider) or summary
            for summary in self._legacy.coverage(db)
        )

    def serves_tables(self, db: Any) -> bool:
        """Return True while observation and activity reads come from the tables."""
        return self._serves_tables(db)

    def refresh(self, db: Any) -> None:
        """Run parity for the current digest and store the result."""
        if read_status(self._key_values, db) != BackfillStatus.COMPLETE.value:
            self._store(db, {"source": SOURCE_LEGACY, "reason": "backfill_incomplete"})
            return
        digest = self._digest(db)
        report = self._parity.check(db)
        passed = report.passed
        self._store(
            db,
            {
                "source": SOURCE_TABLES if passed else SOURCE_LEGACY,
                "reason": "parity_passed" if passed else "parity_failed",
                "digest": digest,
                "parity": report.as_dict(),
            },
        )

    def record_failure(self, db: Any, error_class: str) -> None:
        self._store(
            db,
            {"source": SOURCE_LEGACY, "reason": "error", "error_class": error_class},
        )

    def summary(self, db: Any) -> dict[str, Any]:
        """Return the content-free switch state for diagnostics."""
        state = self._state(db)
        return {
            "serving": "tables" if self._serves_tables(db) else "legacy",
            "reason": str(state.get("reason", "not_checked")),
            "digest_current": state.get("digest") == self._digest(db),
            "parity": state.get("parity"),
        }

    def _source(self, db: Any) -> CanonicalReader:
        return self._table if self._serves_tables(db) else self._legacy

    def _serves_tables(self, db: Any) -> bool:
        state = self._state(db)
        return (
            state.get("source") == SOURCE_TABLES
            and state.get("digest") == self._digest(db)
            and read_status(self._key_values, db) == BackfillStatus.COMPLETE.value
        )

    def _digest(self, db: Any) -> str:
        """Digest of the inputs a parity result is only valid for: mappers and zone."""
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
