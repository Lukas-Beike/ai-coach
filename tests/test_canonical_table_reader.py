"""Canonical table reader: stored rows only, the legacy order and the stored-state rules."""

from __future__ import annotations

from datetime import date

from canonical_read_support import (
    CanonicalReadFixture,
    populate,
)

from backend.canonical.vocabulary import MetricKind, Sport
from backend.providers.canonical_plans import current_observation_mapper_versions


class CanonicalTableReaderTests(CanonicalReadFixture):
    def test_populated_tables_serve_the_legacy_activities_in_the_same_order(
        self,
    ) -> None:
        populate(self)
        legacy = self.read(self.projection.activities)
        table = self.read(self.table.activities)

        self.assertTrue(table)
        self.assertEqual(
            [(a.activity_id, a.provenance.provider) for a in legacy],
            [(a.activity_id, a.provenance.provider) for a in table],
        )

    def test_stored_activities_keep_their_elapsed_duration(self) -> None:
        populate(self)
        legacy = self.read(self.projection.activities)
        table = self.read(self.table.activities)

        self.assertIn(5600.0, [a.elapsed_duration_s for a in table])
        self.assertEqual(
            [a.elapsed_duration_s for a in legacy],
            [a.elapsed_duration_s for a in table],
        )

    def test_populated_tables_serve_observations_with_their_legacy_values(self) -> None:
        populate(self)
        served = 0
        for kind in MetricKind:
            legacy = self.read(self.projection.observations, kind)
            table = self.read(self.table.observations, kind)
            # The table keeps one row per natural key, so identical duplicate
            # legacy rows (for example two Garmin FTP sections) collapse to one.
            self.assertEqual(
                list(dict.fromkeys((o.observed_on, o.value) for o in legacy)),
                list(dict.fromkeys((o.observed_on, o.value) for o in table)),
            )
            served += len(table)
        self.assertGreater(served, 0)

    def test_activity_bounds_select_the_athlete_local_day(self) -> None:
        populate(self)
        everything = self.read(self.table.activities)
        local_day = self.rows(
            "SELECT local_date FROM activity_records ORDER BY local_date LIMIT 1"
        )[0]["local_date"]
        day = date.fromisoformat(str(local_day))

        on_day = self.read(self.table.activities, start=day, end=day)
        expected = self.rows(
            "SELECT r.provider, r.provider_activity_id FROM activity_records AS r "
            "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
            "WHERE r.state = 'active' AND s.state <> 'deleted' AND r.local_date = ?",
            (day.isoformat(),),
        )
        self.assertTrue(on_day)
        self.assertEqual(
            sorted((a.activity_id, a.provenance.provider.value) for a in on_day),
            sorted((r["provider_activity_id"], r["provider"]) for r in expected),
        )
        self.assertLess(len(on_day), len(everything))
        self.assertEqual(self.read(self.table.activities, start=date(2999, 1, 1)), ())

    def test_observation_sport_filter_keeps_only_that_sport(self) -> None:
        populate(self)
        for kind in MetricKind:
            everything = self.read(self.table.observations, kind)
            for sport in Sport:
                filtered = self.read(self.table.observations, kind, sport=sport)
                self.assertTrue(all(o.sport is sport for o in filtered))
                self.assertEqual(
                    len(filtered), len([o for o in everything if o.sport is sport])
                )

    def test_invalid_records_and_deleted_sessions_are_not_served(self) -> None:
        populate(self)
        before = len(self.read(self.table.activities))
        self.assertGreater(before, 1)
        self.execute(
            "UPDATE activity_records SET state = 'invalid' "
            "WHERE provider_activity_id = "
            "(SELECT MIN(provider_activity_id) FROM activity_records)"
        )
        self.assertEqual(len(self.read(self.table.activities)), before - 1)

        self.execute("UPDATE activity_sessions SET state = 'deleted'")
        self.assertEqual(self.read(self.table.activities), ())

    def test_observations_from_a_superseded_mapper_version_are_not_served(self) -> None:
        populate(self)
        metric = MetricKind(
            self.rows("SELECT metric FROM observations LIMIT 1")[0]["metric"]
        )
        self.assertTrue(self.read(self.table.observations, metric))

        self.execute(
            "UPDATE observations SET mapper_version = mapper_version - 1 WHERE metric = ?",
            (metric.value,),
        )
        self.assertEqual(self.read(self.table.observations, metric), ())

    def test_stored_observation_versions_match_the_current_mapper_versions(
        self,
    ) -> None:
        populate(self)
        versions = current_observation_mapper_versions()
        stored = self.rows("SELECT DISTINCT provider, mapper_version FROM observations")
        self.assertTrue(stored)
        for row in stored:
            self.assertEqual(versions[row["provider"]], row["mapper_version"])
