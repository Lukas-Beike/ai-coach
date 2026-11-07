"""Performance refresh ingest, persisted canonical coverage and the backfill query.

All storage is temporary and the provider client is a mock.
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

from canonical_read_support import (
    MAX_BATCHES,
    CanonicalReadFixture,
    intervals_snapshot,
    make_selector,
    new_backfill,
    populate,
)
from support import load_provider_fixture

from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.providers import canonical_plans
from backend.sync.canonical_backfill import STATE_KEY, backfill_complete
from backend.sync.canonical_coverage_store import (
    CANONICAL_COVERAGE_PROVIDERS,
    LIVE_COVERAGE_PROVIDERS,
    CanonicalCoverageStore,
    coverage_key,
    garmin_payload_coverage,
    intervals_snapshot_coverage,
    wahoo_payload_coverage,
)
from backend.sync.canonical_read_selector import PENDING_READER, CanonicalReadSelector
from backend.sync.canonical_table_reader import CanonicalTableReader

NOW = "2026-10-10T06:30:00+00:00"
ZONE = ZoneInfo("Europe/Berlin")
OBSERVATION_COLUMNS = (
    "natural_key, metric, value, unit, source_kind, provider, source_record_id, "
    "observed_on, retrieved_at, mapper_version"
)


def performance_response() -> dict[str, Any]:
    wellness = load_provider_fixture("intervals/wellness.json")
    athlete = load_provider_fixture("intervals/athlete.json")
    return {
        "synced_at": NOW,
        "athlete": athlete,
        "recent_wellness": wellness,
        "raw_provider_data": {"athlete": athlete, "wellness": wellness},
    }




class PersistedCoverageTests(CanonicalReadFixture):
    def selector(self) -> CanonicalReadSelector:
        return make_selector(self)

    def store(self, *, zone: ZoneInfo | None = None) -> None:
        use = zone or ZONE
        coverage = CanonicalCoverageStore(self.key_values)
        with self.manager.unit_of_work() as db:
            coverage.persist(
                db, intervals_snapshot_coverage(self.intervals, zone=use), zone=use
            )
            coverage.persist(
                db, garmin_payload_coverage(self.garmin, zone=use), zone=use
            )

    def strip_snapshot_inputs(self) -> None:
        synced_at = self.intervals["synced_at"]
        self.intervals.clear()
        self.intervals["synced_at"] = synced_at

    def summaries(self) -> tuple[Any, ...]:
        """The Intervals.icu and Garmin summaries ``store`` persists."""
        return (
            intervals_snapshot_coverage(self.intervals, zone=ZONE),
            garmin_payload_coverage(self.garmin, zone=ZONE),
        )

    def test_without_persisted_data_coverage_is_empty(self) -> None:
        self.assertEqual(self.read(self.selector().coverage), ())

    def test_persisted_coverage_is_read_instead_of_recomputed(self) -> None:
        expected = self.summaries()
        self.store()
        # The snapshot inputs change, but the persisted summary is what is served.
        self.strip_snapshot_inputs()
        self.garmin.clear()

        self.assertEqual(self.read(self.selector().coverage), expected)

    def test_a_provider_without_a_summary_is_omitted(self) -> None:
        intervals, _garmin = self.summaries()
        coverage = CanonicalCoverageStore(self.key_values)
        with self.manager.unit_of_work() as db:
            coverage.persist(db, intervals, zone=ZONE)

        self.assertEqual(self.read(self.selector().coverage), (intervals,))
        self.assertIsNone(
            self.read(self.key_values.get, coverage_key(ProviderId.GARMIN))
        )

    def test_outdated_or_corrupt_summaries_are_ignored(self) -> None:
        _intervals, garmin = self.summaries()
        self.store()
        self.strip_snapshot_inputs()

        with patch(
            "backend.sync.canonical_coverage_store.current_mapper_versions",
            return_value={"changed": 1},
        ):
            self.assertEqual(self.read(self.selector().coverage), ())

        self.zone = ZoneInfo("America/New_York")
        self.assertEqual(self.read(self.selector().coverage), ())
        self.zone = ZONE

        with self.manager.unit_of_work() as db:
            self.key_values.set(db, coverage_key(ProviderId.INTERVALS), "{not json")
        self.assertEqual(self.read(self.selector().coverage), (garmin,))

    def test_only_the_ingested_providers_are_consulted(self) -> None:
        self.assertEqual(
            CANONICAL_COVERAGE_PROVIDERS, (ProviderId.INTERVALS, ProviderId.GARMIN)
        )
        expected = self.summaries()
        self.store()
        self.strip_snapshot_inputs()
        self.garmin.clear()

        loaded: list[ProviderId] = []
        original = CanonicalCoverageStore.load

        def spy(
            store: CanonicalCoverageStore, db: Any, provider: ProviderId, **kw: Any
        ) -> Any:
            loaded.append(provider)
            return original(store, db, provider, **kw)

        with patch.object(CanonicalCoverageStore, "load", spy):
            result = self.read(self.selector().coverage)

        self.assertEqual(
            tuple(loaded), CANONICAL_COVERAGE_PROVIDERS + LIVE_COVERAGE_PROVIDERS
        )
        self.assertEqual(result, expected)

    def test_a_live_provider_summary_is_appended_without_gating(self) -> None:
        self.assertEqual(LIVE_COVERAGE_PROVIDERS, (ProviderId.WAHOO,))
        expected = self.summaries()
        self.store()
        wahoo = wahoo_payload_coverage(
            {
                canonical_plans.WAHOO_SYNCED_AT_KEY: "2026-10-01T08:00:00+00:00",
                canonical_plans.WAHOO_WORKOUTS_KEY: [],
            },
            zone=ZONE,
        )
        self.assertIsNotNone(wahoo)
        with self.manager.unit_of_work() as db:
            CanonicalCoverageStore(self.key_values).persist(db, wahoo, zone=ZONE)

        result = self.read(self.selector().coverage)

        self.assertEqual(result, (*expected, wahoo))
        with self.manager.unit_of_work() as db:
            self.key_values.set(db, coverage_key(ProviderId.INTERVALS), "{not json")
        self.assertEqual(self.read(self.selector().coverage), (expected[1], wahoo))

    def test_persisted_value_holds_counts_only(self) -> None:
        self.store()
        text = self.read(self.key_values.get, coverage_key(ProviderId.INTERVALS))
        data = json.loads(text)
        self.assertEqual(
            set(data),
            {
                "provider",
                "mapper_versions",
                "zone",
                "retrieved_at",
                "activities_retrieved_at",
                "observations_retrieved_at",
                "activity_count",
                "observation_count",
                "issue_counts",
                "first_observed_on",
                "last_observed_on",
            },
        )


class BackfillCompleteTests(CanonicalReadFixture):
    def complete(self) -> bool:
        return self.read(
            lambda db: backfill_complete(self.key_values, db, zone=self.zone)
        )

    def test_false_for_another_zone_or_a_state_without_a_zone(self) -> None:
        populate(self)
        self.assertTrue(self.complete())
        self.zone = ZoneInfo("America/Los_Angeles")
        self.assertFalse(self.complete())
        self.zone = ZONE
        with self.manager.unit_of_work() as db:
            state = json.loads(self.key_values.get(db, STATE_KEY) or "{}")
            del state["zone"]
            self.key_values.set(db, STATE_KEY, json.dumps(state))
        self.assertFalse(self.complete())

    def test_false_before_and_true_after_the_backfill(self) -> None:
        self.assertFalse(self.complete())
        populate(self)
        self.assertTrue(self.complete())

    def test_false_for_a_failed_corrupt_or_outdated_record(self) -> None:
        populate(self)
        with self.manager.unit_of_work() as db:
            state = json.loads(self.key_values.get(db, STATE_KEY) or "{}")
            self.key_values.set(
                db, STATE_KEY, json.dumps({**state, "status": "failed"})
            )
        self.assertFalse(self.complete())

        with self.manager.unit_of_work() as db:
            self.key_values.set(db, STATE_KEY, "{not json")
        self.assertFalse(self.complete())

        with self.manager.unit_of_work() as db:
            self.key_values.set(db, STATE_KEY, json.dumps({**state, "versions": {}}))
        self.assertFalse(self.complete())

    def test_false_after_a_mapper_version_bump(self) -> None:
        populate(self)
        bumped = {
            key: version + 1
            for key, version in canonical_plans.current_mapper_versions().items()
        }
        with patch(
            "backend.sync.canonical_backfill.current_mapper_versions",
            return_value=bumped,
        ):
            self.assertFalse(self.complete())


class ReadsAfterBackfillTests(CanonicalReadFixture):
    """Ingest, backfill complete, then a stale read-state record and a mapper change."""

    def ids(self, records: Any) -> list[tuple[str, str]]:
        return [(r.activity_id, r.provenance.provider.value) for r in records]

    def test_tables_keep_serving_through_mapper_and_zone_changes(self) -> None:
        self.assertIs(self.read(make_selector(self).reader_for), PENDING_READER)

        populate(self)  # ingests the snapshots and completes the backfill
        obsolete = {
            "source": "legacy",
            "reason": "parity_failed",
            "digest": "stale",
            "parity": {"passed": False},
        }
        with self.manager.unit_of_work() as db:
            self.key_values.set(db, "canonical_read_state", json.dumps(obsolete))
        selector = make_selector(self)

        self.assertTrue(self.read(selector.serves_tables))
        self.assertIsInstance(self.read(selector.reader_for), CanonicalTableReader)
        self.assertEqual(
            self.ids(self.read(selector.activities)),
            self.ids(self.read(self.table.activities)),
        )

        bumped = {
            key: version + 1
            for key, version in canonical_plans.current_mapper_versions().items()
        }
        with patch(
            "backend.sync.canonical_backfill.current_mapper_versions",
            return_value=bumped,
        ):
            self.assertTrue(self.read(selector.serves_tables))
            self.assertIsNot(self.read(selector.reader_for), PENDING_READER)
            self.assertEqual(
                self.ids(self.read(selector.activities)),
                self.ids(self.read(self.table.activities)),
            )

        # A zone change keeps the tables serving while the re-projection runs.
        self.assertTrue(self.read(selector.serves_tables))
        self.zone = ZoneInfo("America/Los_Angeles")
        self.assertTrue(self.read(selector.serves_tables))
        self.assertIsNot(self.read(selector.reader_for), PENDING_READER)
        backfill = new_backfill(self)
        for _ in range(MAX_BATCHES):
            with self.manager.unit_of_work() as db:
                if backfill.run_batch(db).done:
                    break
        self.assertTrue(self.read(selector.serves_tables))
        self.assertTrue(self.read(selector.summary)["digest_current"])

    def weights(self) -> list[tuple[str, float]]:
        return [
            (row["natural_key"], row["value"])
            for row in self.rows(
                "SELECT natural_key, value, mapper_version FROM observations "
                "WHERE metric = 'weight' AND provider = 'intervals' "
                "AND mapper_version = ? ORDER BY natural_key",
                (canonical_plans.current_observation_mapper_versions()["intervals"],),
            )
        ]

    def test_reprojection_separates_a_merged_wellness_and_athlete_weight(self) -> None:
        self.intervals = intervals_snapshot(athlete_weight=True)
        populate(self)
        current = self.weights()
        athlete_keys = [key for key, _ in current if "|athlete|" in key]
        self.assertEqual(len(athlete_keys), 1)
        athlete_value = dict(current)[athlete_keys[0]]
        day = athlete_keys[0].rsplit("|", 1)[1]
        wellness_key = f"intervals|weight|||{day}"
        wellness_value = dict(current)[wellness_key]
        self.assertNotEqual(wellness_value, athlete_value)

        # The database as the previous mapper left it: one merged row on the
        # wellness key holding the athlete value, at the previous version.
        previous = (
            canonical_plans.current_observation_mapper_versions()["intervals"] - 1
        )
        self.execute(
            "DELETE FROM observations WHERE natural_key = ?", (athlete_keys[0],)
        )
        self.execute(
            "UPDATE observations SET value = ? WHERE natural_key = ?",
            (athlete_value, wellness_key),
        )
        self.execute(
            "UPDATE observations SET mapper_version = ? WHERE provider = 'intervals'",
            (previous,),
        )
        self.execute(
            "UPDATE provider_records SET mapped_version = ? "
            "WHERE provider = 'intervals' AND record_kind IN ('wellness', 'athlete')",
            (previous,),
        )
        with self.manager.unit_of_work() as db:
            state = json.loads(self.key_values.get(db, STATE_KEY) or "{}")
            for key in ("intervals.wellness", "intervals.athlete"):
                state["versions"][key] = previous
            self.key_values.set(db, STATE_KEY, json.dumps(state))
        selector = make_selector(self)
        self.assertTrue(self.read(selector.serves_tables))
        self.assertEqual(self.weights(), [])

        backfill = new_backfill(self)
        for _ in range(MAX_BATCHES):
            with self.manager.unit_of_work() as db:
                if backfill.run_batch(db).done:
                    break

        after = dict(self.weights())
        self.assertEqual(after[wellness_key], wellness_value)
        self.assertEqual(after[athlete_keys[0]], athlete_value)
        self.assertEqual(sorted(after), sorted(key for key, _ in current))
        self.assertTrue(self.read(selector.serves_tables))
        self.assertEqual(
            self.read(selector.observations, MetricKind.WEIGHT),
            self.read(self.table.observations, MetricKind.WEIGHT),
        )


if __name__ == "__main__":
    unittest.main()
