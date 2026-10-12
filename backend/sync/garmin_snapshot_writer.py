"""The one write path for the Garmin snapshot.

Garmin sync and the Morning Body Battery refresh both store the snapshot through
``GarminSnapshotWriter.write``. Inside the caller's unit of work it writes the
canonical rows and the legacy ``garmin_snapshot`` value together, so a failure in
either rolls back both.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, tzinfo
from typing import Any, Final

from backend.db.repositories import KeyValueRepository
from backend.sync.canonical_coverage_store import (
    CanonicalCoverageStore,
    garmin_payload_coverage,
)
from backend.sync.canonical_ingest import CanonicalIngestCounters, ingest_garmin_payload

GARMIN_SNAPSHOT_KEY: Final = "garmin_snapshot"


class GarminSnapshotWriter:
    def __init__(
        self,
        key_values: KeyValueRepository,
        zone_provider: Callable[[], tzinfo | None],
    ) -> None:
        self._key_values = key_values
        self._coverage = CanonicalCoverageStore(key_values)
        self._zone_provider = zone_provider

    def write(self, db: Any, payload: Mapping[str, Any]) -> CanonicalIngestCounters:
        """Write canonical rows and the legacy snapshot value on the same connection."""
        zone = self._zone_provider() or UTC
        counters = ingest_garmin_payload(db, payload, zone=zone)
        self._coverage.persist(
            db, garmin_payload_coverage(payload, zone=zone), zone=zone
        )
        self._key_values.set(
            db,
            GARMIN_SNAPSHOT_KEY,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
        return counters
