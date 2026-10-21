"""Composition for the canonical snapshot projection.

The projection reads the snapshot and payload that the sync layer already
stores. This module only connects those existing readers, the athlete's time
zone and the clock to ``CanonicalSnapshotProjection``. It names no provider and
changes no consumer.

Version contract: the Intervals.icu version is a SHA-256 digest of the stored
snapshot text, read from the same row that ``latest_snapshot`` reads. A changed
row therefore always changes the version, so the cache cannot hold older content
under a newer version. A reader that sees a newer row than its version caches
that row under the older version, which the next call recomputes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, tzinfo
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from backend.athlete.profile import timezone_name
from backend.db import garmin_store
from backend.runtime.ports import ProviderSnapshotReader
from backend.sync.canonical_projection import CanonicalSnapshotProjection


class StoredPayloadReader(Protocol):
    def latest_payload(self, db: Any) -> str | None: ...


class AthleteTimezoneReader(Protocol):
    def get(self) -> dict[str, Any]: ...


def build_canonical_snapshot_projection(
    *,
    intervals_snapshots: ProviderSnapshotReader,
    snapshot_payloads: StoredPayloadReader,
    profile: AthleteTimezoneReader,
    clock: Callable[[], datetime],
    garmin_payload: Callable[[Any], dict[str, Any]] = garmin_store.read_view,
) -> CanonicalSnapshotProjection:
    """Return one canonical projection over the stored snapshots."""
    return CanonicalSnapshotProjection(
        intervals_snapshot=intervals_snapshots.latest_snapshot,
        intervals_version=_intervals_version(snapshot_payloads),
        garmin_payload=garmin_payload,
        zone=_athlete_zone(profile),
        clock=clock,
    )


def _intervals_version(reader: StoredPayloadReader) -> Callable[[Any], str]:
    def version(db: Any) -> str:
        stored = reader.latest_payload(db) or ""
        return hashlib.sha256(stored.encode("utf-8")).hexdigest()

    return version


def _athlete_zone(profile: AthleteTimezoneReader) -> Callable[[Any], tzinfo]:
    def zone(_db: Any) -> tzinfo:
        return ZoneInfo(timezone_name(profile.get().get("timezone")))

    return zone
