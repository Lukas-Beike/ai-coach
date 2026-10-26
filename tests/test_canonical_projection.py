"""Canonical snapshot projection: cache, filters, coverage and end-to-end fixtures.

Every test uses in-memory fakes in place of the stored Intervals.icu snapshot and
Garmin payload. The wire fixtures under tests/fixtures/providers are read only.
"""

from __future__ import annotations

import threading
import time
import unittest
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from support import (
    PROVIDER_SYNCED_TEXT,
    garmin_payload_fixture,
    intervals_snapshot_fixture,
)

from backend.canonical.coverage import ProviderCoverage
from backend.canonical.mapping import IssueReason
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.runtime.ports import (
    ActivityReader,
    ObservationReader,
    ProviderCoverageReader,
)
from backend.sync.canonical_projection import CanonicalSnapshotProjection

BERLIN = ZoneInfo("Europe/Berlin")
SYNCED_AT = datetime(2026, 10, 10, 6, 0, tzinfo=UTC)
CLOCK_AT = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
FAKE_DB: Any = object()


class FakeStore:
    """Mutable in-memory stand-in for the stored snapshot, payload and settings."""

    def __init__(self) -> None:
        self.snapshot: Any = intervals_snapshot_fixture()
        self.version = "2026-10-10T06:00:00+00:00:42"
        self.payload: Any = garmin_payload_fixture()
        self.zone: tzinfo = BERLIN
        self.clock_at = CLOCK_AT
        self.snapshot_reads = 0
        self.snapshot_delay = 0.0

    def read_snapshot(self, db: Any) -> dict[str, Any] | None:
        self.snapshot_reads += 1
        if self.snapshot_delay:
            time.sleep(self.snapshot_delay)
        return self.snapshot

    def read_payload(self, db: Any) -> dict[str, Any]:
        return self.payload

    def read_version(self, db: Any) -> str:
        return self.version

    def read_zone(self, db: Any) -> tzinfo:
        return self.zone

    def read_clock(self) -> datetime:
        return self.clock_at

    def projection(self) -> CanonicalSnapshotProjection:
        return CanonicalSnapshotProjection(
            intervals_snapshot=self.read_snapshot,
            intervals_version=self.read_version,
            garmin_payload=self.read_payload,
            zone=self.read_zone,
            clock=self.read_clock,
        )


def all_observations(
    projection: ObservationReader,
) -> tuple[Observation, ...]:
    return tuple(
        observation
        for kind in MetricKind
        for observation in projection.observations(FAKE_DB, kind)
    )


def provider_of(observation: Observation) -> ProviderId | None:
    return observation.provenance.provider


class ProjectionInterfaceTests(unittest.TestCase):
    def test_projection_implements_the_three_reader_ports(self) -> None:
        for port in (ActivityReader, ObservationReader, ProviderCoverageReader):
            with self.subTest(port=port.__name__):
                self.assertIn(port, CanonicalSnapshotProjection.__mro__)


class FixtureProjectionTests(unittest.TestCase):
    def test_fixture_snapshots_project_through_the_reader_ports(self) -> None:
        projection = FakeStore().projection()

        activities = projection.activities(FAKE_DB)
        observations = all_observations(projection)

        self.assertEqual(len(activities), 7)
        self.assertEqual(
            [record.started_at for record in activities],
            sorted(record.started_at for record in activities),
        )
        # The fixture athlete's weight is one more Intervals observation (mapper v2).
        # Intervals wellness v6 adds FORM and eFTP per row plus the athlete eFTP;
        # Garmin health v5 adds the running threshold power, v11 the weekly HRV.
        self.assertEqual(len(observations), 59)
        for record in activities:
            self.assertEqual(record.provenance.retrieved_at, SYNCED_AT)

    def test_fixture_coverage_reports_counts_per_provider(self) -> None:
        projection = FakeStore().projection()
        coverage: dict[ProviderId, ProviderCoverage] = {
            entry.provider: entry for entry in projection.coverage(FAKE_DB)
        }

        intervals = coverage[ProviderId.INTERVALS]
        garmin = coverage[ProviderId.GARMIN]
        self.assertEqual(intervals.activity_count, 5)
        # Includes the fixture athlete's weight (mapper v2), and per wellness row
        # FORM and eFTP plus the athlete eFTP (mapper v6).
        self.assertEqual(intervals.observation_count, 39)
        self.assertEqual(intervals.retrieved_at, SYNCED_AT)
        self.assertEqual(garmin.activity_count, 2)
        # Includes the running threshold power (mapper v5) and the weekly HRV
        # average (mapper v11).
        self.assertEqual(garmin.observation_count, 20)
        self.assertEqual(garmin.retrieved_at, SYNCED_AT)
        self.assertEqual(garmin.issue_counts[IssueReason.UNSUPPORTED], 2)
        self.assertEqual(intervals.issue_counts[IssueReason.UNSUPPORTED], 0)

    def test_observed_range_matches_the_provider_observations(self) -> None:
        projection = FakeStore().projection()
        observations = all_observations(projection)
        intervals_days = [
            observation.observed_on
            for observation in observations
            if provider_of(observation) == ProviderId.INTERVALS
        ]

        intervals = {entry.provider: entry for entry in projection.coverage(FAKE_DB)}[
            ProviderId.INTERVALS
        ]

        self.assertEqual(intervals.first_observed_on, min(intervals_days))
        self.assertEqual(intervals.last_observed_on, max(intervals_days))


class CacheTests(unittest.TestCase):
    def test_repeated_reads_reuse_one_projection(self) -> None:
        store = FakeStore()
        projection = store.projection()

        projection.activities(FAKE_DB)
        all_observations(projection)
        projection.coverage(FAKE_DB)

        self.assertEqual(store.snapshot_reads, 1)

    def test_intervals_version_change_recomputes(self) -> None:
        store = FakeStore()
        projection = store.projection()
        projection.activities(FAKE_DB)

        store.version = "2026-10-11T06:00:00+00:00:43"
        projection.activities(FAKE_DB)

        self.assertEqual(store.snapshot_reads, 2)

    def test_garmin_content_change_recomputes(self) -> None:
        store = FakeStore()
        projection = store.projection()
        before = projection.coverage(FAKE_DB)

        store.payload = {**store.payload, "weight": []}
        after = projection.coverage(FAKE_DB)

        self.assertEqual(store.snapshot_reads, 2)
        self.assertNotEqual(
            {entry.provider: entry.observation_count for entry in before},
            {entry.provider: entry.observation_count for entry in after},
        )

    def test_equal_garmin_content_with_reordered_keys_is_a_cache_hit(self) -> None:
        store = FakeStore()
        projection = store.projection()
        projection.coverage(FAKE_DB)

        store.payload = dict(reversed(list(store.payload.items())))
        projection.coverage(FAKE_DB)

        self.assertEqual(store.snapshot_reads, 1)

    def test_zone_change_recomputes_with_the_new_zone(self) -> None:
        store = FakeStore()
        projection = store.projection()
        berlin_offsets = {
            record.started_at.utcoffset() for record in projection.activities(FAKE_DB)
        }

        store.zone = UTC
        utc_offsets = {
            record.started_at.utcoffset() for record in projection.activities(FAKE_DB)
        }

        self.assertEqual(store.snapshot_reads, 2)
        self.assertEqual(utc_offsets, {timedelta(0)})
        self.assertNotEqual(berlin_offsets, utc_offsets)

    def test_missing_stored_time_uses_the_clock_for_provenance(self) -> None:
        store = FakeStore()
        store.payload = {
            key: value for key, value in store.payload.items() if key != "synced_at"
        }
        projection = store.projection()

        garmin_records = [
            record
            for record in projection.activities(FAKE_DB)
            if record.provenance.provider == ProviderId.GARMIN
        ]
        garmin = {entry.provider: entry for entry in projection.coverage(FAKE_DB)}[
            ProviderId.GARMIN
        ]

        self.assertTrue(garmin_records)
        for record in garmin_records:
            self.assertEqual(record.provenance.retrieved_at, CLOCK_AT)
        self.assertIsNone(garmin.retrieved_at)

    def test_clock_fallback_is_not_served_across_local_midnight(self) -> None:
        store = FakeStore()
        store.snapshot = {
            key: value for key, value in store.snapshot.items() if key != "synced_at"
        }
        store.payload = {
            key: value for key, value in store.payload.items() if key != "synced_at"
        }
        # 23:30 on 10 October in Berlin, then 00:30 on 11 October.
        store.clock_at = datetime(2026, 10, 10, 21, 30, tzinfo=UTC)
        projection = store.projection()
        before = all_observations(projection)

        store.clock_at = datetime(2026, 10, 10, 22, 30, tzinfo=UTC)
        after = all_observations(projection)
        fresh = all_observations(store.projection())

        self.assertNotEqual(before, after)
        self.assertEqual(after, fresh)

    def test_concurrent_first_reads_compute_once(self) -> None:
        store = FakeStore()
        store.snapshot_delay = 0.02
        projection = store.projection()
        thread_count = 8
        barrier = threading.Barrier(thread_count)
        results: list[int] = []
        results_lock = threading.Lock()

        def read() -> None:
            # An exception here ends the thread without a result, which fails
            # the count assertion below.
            barrier.wait()
            count = len(projection.activities(FAKE_DB))
            with results_lock:
                results.append(count)

        threads = [threading.Thread(target=read) for _ in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(results, [7] * thread_count)
        self.assertEqual(store.snapshot_reads, 1)


class FilterTests(unittest.TestCase):
    def test_activity_bounds_use_the_athlete_local_date(self) -> None:
        store = FakeStore()
        row = dict(store.snapshot["recent_activities"][0])
        row["id"] = "i-act-midnight"
        row["start_date_local"] = "2026-10-10T00:30:00"
        store.snapshot["recent_activities"].append(row)
        store.version = "2026-10-10T06:00:00+00:00:43"
        projection = store.projection()

        def ids(day_start: date | None, day_end: date | None) -> set[str]:
            return {
                record.activity_id
                for record in projection.activities(
                    FAKE_DB, start=day_start, end=day_end
                )
            }

        midnight = date(2026, 10, 10)
        self.assertIn("i-act-midnight", ids(midnight, midnight))
        self.assertIn("i-act-midnight", ids(None, midnight))
        self.assertNotIn("i-act-midnight", ids(None, date(2026, 10, 9)))
        self.assertNotIn("i-act-midnight", ids(date(2026, 10, 11), None))

    def test_activity_bounds_are_inclusive_at_both_ends(self) -> None:
        projection = FakeStore().projection()
        records = projection.activities(FAKE_DB)
        first_day = min(
            record.started_at.astimezone(BERLIN).date() for record in records
        )
        last_day = max(
            record.started_at.astimezone(BERLIN).date() for record in records
        )

        bounded = projection.activities(FAKE_DB, start=first_day, end=last_day)

        self.assertEqual(bounded, records)
        self.assertEqual(
            projection.activities(FAKE_DB, start=last_day + timedelta(days=1)), ()
        )

    def test_observation_bounds_are_inclusive_on_observed_day(self) -> None:
        projection = FakeStore().projection()
        observations = all_observations(projection)
        day = min(observation.observed_on for observation in observations)
        on_day = [
            observation
            for observation in observations
            if observation.observed_on == day
        ]

        for kind in {observation.kind for observation in on_day}:
            with self.subTest(kind=kind):
                expected = tuple(
                    observation for observation in on_day if observation.kind == kind
                )
                self.assertEqual(
                    projection.observations(FAKE_DB, kind, start=day, end=day),
                    expected,
                )
                self.assertEqual(
                    projection.observations(
                        FAKE_DB, kind, start=day + timedelta(days=1)
                    ),
                    tuple(
                        observation
                        for observation in observations
                        if observation.kind == kind and observation.observed_on > day
                    ),
                )

    def test_sport_filter_keeps_only_observations_of_that_sport(self) -> None:
        projection = FakeStore().projection()
        observations = all_observations(projection)
        sports = {observation.sport for observation in observations} - {None}
        self.assertTrue(sports)

        for sport in sports:
            for kind in MetricKind:
                with self.subTest(sport=sport, kind=kind):
                    self.assertEqual(
                        projection.observations(FAKE_DB, kind, sport=sport),
                        tuple(
                            observation
                            for observation in projection.observations(FAKE_DB, kind)
                            if observation.sport == sport
                        ),
                    )
        self.assertEqual(
            projection.observations(FAKE_DB, MetricKind.WEIGHT, sport=Sport.RIDE),
            tuple(
                observation
                for observation in observations
                if observation.kind == MetricKind.WEIGHT
                and observation.sport == Sport.RIDE
            ),
        )

    def test_activities_are_sorted_by_start(self) -> None:
        projection = FakeStore().projection()
        starts: list[datetime] = [
            record.started_at for record in projection.activities(FAKE_DB)
        ]

        self.assertEqual(starts, sorted(starts))

    def test_observations_are_sorted_by_day_provider_and_kind(self) -> None:
        projection = FakeStore().projection()
        checked = 0
        for kind in MetricKind:
            observations = projection.observations(FAKE_DB, kind)
            projected = [
                (
                    observation.observed_on,
                    str(provider_of(observation) or ""),
                    str(observation.kind),
                )
                for observation in observations
            ]
            checked += len(projected)
            with self.subTest(kind=kind):
                self.assertEqual(projected, sorted(projected))
        self.assertGreater(checked, 1)


class CoverageTests(unittest.TestCase):
    def test_wrong_section_types_are_counted_per_provider_and_reason(self) -> None:
        store = FakeStore()
        store.payload = {**store.payload, "activities": "not a list"}
        store.snapshot = {**store.snapshot, "recent_wellness": None}
        store.version = "2026-10-10T06:00:00+00:00:43"
        projection = store.projection()

        coverage = {entry.provider: entry for entry in projection.coverage(FAKE_DB)}

        garmin = coverage[ProviderId.GARMIN]
        self.assertEqual(garmin.activity_count, 0)
        self.assertEqual(garmin.issue_counts[IssueReason.INVALID_TYPE], 1)
        self.assertEqual(garmin.issue_counts[IssueReason.UNSUPPORTED], 2)
        intervals = coverage[ProviderId.INTERVALS]
        self.assertEqual(intervals.issue_counts[IssueReason.INVALID_TYPE], 1)
        self.assertEqual(intervals.activity_count, 5)
        self.assertEqual(
            intervals.observation_count,
            sum(
                1
                for observation in all_observations(projection)
                if provider_of(observation) == ProviderId.INTERVALS
            ),
        )

    def test_absent_intervals_snapshot_reports_empty_coverage(self) -> None:
        store = FakeStore()
        store.snapshot = None
        store.version = "none"
        projection = store.projection()

        intervals = {entry.provider: entry for entry in projection.coverage(FAKE_DB)}[
            ProviderId.INTERVALS
        ]

        self.assertIsNone(intervals.retrieved_at)
        self.assertEqual(intervals.activity_count, 0)
        self.assertEqual(intervals.observation_count, 0)
        self.assertIsNone(intervals.first_observed_on)
        self.assertIsNone(intervals.last_observed_on)
        self.assertEqual(
            {
                reason: count
                for reason, count in intervals.issue_counts.items()
                if count
            },
            {},
        )
        self.assertTrue(projection.activities(FAKE_DB))

    def test_every_issue_reason_is_present_in_each_provider_tally(self) -> None:
        projection = FakeStore().projection()

        for entry in projection.coverage(FAKE_DB):
            with self.subTest(provider=entry.provider):
                self.assertEqual(set(entry.issue_counts), set(IssueReason))


class MalformedDocumentTests(unittest.TestCase):
    def test_garbage_documents_never_raise(self) -> None:
        values: tuple[object, ...] = (
            None,
            [],
            "text",
            3,
            {"recent_activities": "text", "athlete": []},
            {"recent_activities": [None, 3, {"start_date_local": 5}]},
            {"recent_wellness": [None, "row", {"id": 7}], "athlete": {"x": 1}},
        )
        for index, value in enumerate(values):
            with self.subTest(value=value):
                store = FakeStore()
                store.snapshot = value
                store.payload = value
                store.version = f"garbage-{index}"
                projection = store.projection()

                self.assertIsInstance(projection.activities(FAKE_DB), tuple)
                self.assertIsInstance(all_observations(projection), tuple)
                self.assertEqual(len(projection.coverage(FAKE_DB)), 2)

    def test_garbage_sections_inside_valid_documents_never_raise(self) -> None:
        for index, garbage in enumerate(
            (None, 0, "text", [], [None, 1], {"nested": ["x"]})
        ):
            with self.subTest(garbage=garbage):
                store = FakeStore()
                store.snapshot = {
                    **store.snapshot,
                    "recent_activities": garbage,
                    "recent_wellness": garbage,
                    "athlete": garbage,
                }
                store.payload = {
                    "synced_at": PROVIDER_SYNCED_TEXT,
                    "activities": garbage,
                    "weight": garbage,
                    "sleep": garbage,
                    "running_threshold": garbage,
                    "cycling_ftp": garbage,
                }
                store.version = f"section-{index}"
                projection = store.projection()

                self.assertEqual(projection.activities(FAKE_DB), ())
                self.assertEqual(
                    projection.observations(FAKE_DB, MetricKind.WEIGHT, sport=None),
                    (),
                )
                self.assertEqual(len(projection.coverage(FAKE_DB)), 2)
