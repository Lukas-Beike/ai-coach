"""Composition of the canonical snapshot projection from the stored readers.

The stores are in-memory fakes. The wire fixtures under tests/fixtures/providers
are read only.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

from support import garmin_payload_fixture, intervals_snapshot_fixture

from backend.athlete.profile import DEFAULT_TIMEZONE
from backend.canonical.vocabulary import ProviderId
from backend.sync.canonical_projection import CanonicalSnapshotProjection
from backend.sync.canonical_projection_assembly import (
    build_canonical_snapshot_projection,
)

CLOCK_AT = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
FAKE_DB: Any = object()
ASSEMBLY_MODULE = "backend.sync.canonical_projection_assembly"


class StubSnapshots:
    def __init__(self, snapshot: dict[str, Any] | None) -> None:
        self.snapshot = snapshot
        self.reads = 0

    def latest_snapshot(self, db: Any) -> dict[str, Any] | None:
        self.reads += 1
        return self.snapshot


class StubPayloadText:
    """Stands in for the stored snapshot row; its text is the version source."""

    def __init__(self, text: str) -> None:
        self.text = text

    def latest_payload(self, db: Any) -> str | None:
        return self.text


class StubGarmin:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def snapshot(self) -> dict[str, Any]:
        return self.payload


class StubProfile:
    def __init__(self, timezone: str | None) -> None:
        self.timezone = timezone

    def get(self) -> dict[str, str]:
        if self.timezone is None:
            return {}
        return {"timezone": self.timezone}


class Stores:
    def __init__(
        self,
        *,
        snapshot: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        version: str = "row-1",
        timezone: str | None = "Europe/Berlin",
    ) -> None:
        self.snapshots = StubSnapshots(
            intervals_snapshot_fixture() if snapshot is None else snapshot
        )
        self.version_source = StubPayloadText(version)
        self.garmin = StubGarmin(
            garmin_payload_fixture() if payload is None else payload
        )
        self.profile = StubProfile(timezone)

    def projection(self) -> CanonicalSnapshotProjection:
        return build_canonical_snapshot_projection(
            intervals_snapshots=self.snapshots,
            snapshot_payloads=self.version_source,
            garmin_payloads=lambda: self.garmin,
            profile=self.profile,
            clock=lambda: CLOCK_AT,
        )


class AssemblyWiringTests(unittest.TestCase):
    def test_returns_one_projection_over_the_stored_readers(self) -> None:
        projection = Stores().projection()

        self.assertIsInstance(projection, CanonicalSnapshotProjection)
        self.assertEqual(len(projection.activities(FAKE_DB)), 7)
        coverage = {item.provider: item for item in projection.coverage(FAKE_DB)}
        self.assertEqual(coverage[ProviderId.INTERVALS].activity_count, 5)
        self.assertEqual(coverage[ProviderId.GARMIN].activity_count, 2)
        self.assertIsNotNone(coverage[ProviderId.INTERVALS].retrieved_at)

    def test_stored_version_change_recomputes_the_projection(self) -> None:
        stores = Stores()
        projection = stores.projection()
        self.assertEqual(
            {item.provider: item for item in projection.coverage(FAKE_DB)}[
                ProviderId.INTERVALS
            ].activity_count,
            5,
        )

        stores.snapshots.snapshot = dict(
            intervals_snapshot_fixture(), recent_activities=[]
        )
        stores.version_source.text = "row-2"

        coverage = {item.provider: item for item in projection.coverage(FAKE_DB)}
        self.assertEqual(coverage[ProviderId.INTERVALS].activity_count, 0)

    def test_unchanged_version_serves_the_cached_projection(self) -> None:
        stores = Stores()
        projection = stores.projection()
        projection.activities(FAKE_DB)
        reads = stores.snapshots.reads

        projection.activities(FAKE_DB)
        projection.coverage(FAKE_DB)

        self.assertEqual(stores.snapshots.reads, reads)

    def test_zone_is_read_from_the_athlete_profile(self) -> None:
        stores = Stores(timezone="Pacific/Auckland")
        projection = stores.projection()

        with patch(f"{ASSEMBLY_MODULE}.ZoneInfo", wraps=ZoneInfo) as zone:
            projection.activities(FAKE_DB)

        zone.assert_called_with("Pacific/Auckland")

    def test_missing_profile_zone_falls_back_to_the_default_zone(self) -> None:
        stores = Stores(timezone=None)
        projection = stores.projection()

        with patch(f"{ASSEMBLY_MODULE}.ZoneInfo", wraps=ZoneInfo) as zone:
            projection.activities(FAKE_DB)

        zone.assert_called_with(DEFAULT_TIMEZONE)

    def test_clock_supplies_retrieval_time_when_no_sync_time_is_stored(self) -> None:
        snapshot = intervals_snapshot_fixture()
        snapshot.pop("synced_at", None)
        payload = garmin_payload_fixture()
        payload.pop("synced_at", None)
        projection = Stores(snapshot=snapshot, payload=payload).projection()

        activities = projection.activities(FAKE_DB)
        coverage = projection.coverage(FAKE_DB)

        self.assertTrue(activities)
        for record in activities:
            self.assertEqual(record.provenance.retrieved_at, CLOCK_AT)
        for item in coverage:
            self.assertIsNone(item.retrieved_at)

    def test_projection_without_stored_sync_time_is_not_cached(self) -> None:
        snapshot = intervals_snapshot_fixture()
        snapshot.pop("synced_at", None)
        payload = garmin_payload_fixture()
        payload.pop("synced_at", None)
        stores = Stores(snapshot=snapshot, payload=payload)
        projection = stores.projection()

        projection.activities(FAKE_DB)
        reads = stores.snapshots.reads
        projection.activities(FAKE_DB)

        self.assertEqual(stores.snapshots.reads, reads + 1)


if __name__ == "__main__":
    unittest.main()
