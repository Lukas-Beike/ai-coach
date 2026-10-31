"""Canonical table reader: stored rows only, the legacy order and the stored-state rules."""

from __future__ import annotations

from datetime import date

from canonical_read_support import (
    CanonicalReadFixture,
    make_selector,
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

        self.execute(
            "UPDATE activity_sessions SET state = 'deleted', merged_into = NULL"
        )
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


class ActivitySessionReadTests(CanonicalReadFixture):
    def test_backfilled_copies_are_summarised_once_like_the_legacy_bundles(
        self,
    ) -> None:
        legacy = self.read(self.projection.activity_sessions)
        populate(self)
        grouped = self.read(self.table.activity_sessions)
        summaries = self.read(make_selector(self).activity_summaries)

        self.assertEqual(len(legacy), len(grouped))
        self.assertEqual(len(legacy), len(summaries))
        self.assertEqual(
            sorted(
                sorted(record.activity_id for record in records)
                for _id, records in legacy
            ),
            sorted(
                sorted(record.activity_id for record in records)
                for _id, records in grouped
            ),
        )
        merged = [s for s in summaries if len(s["record_ids"]) > 1]
        self.assertEqual(1, len(merged))
        self.assertEqual({"intervals", "garmin"}, set(merged[0]["record_ids"]))
        self.assertEqual(
            sorted(summaries, key=lambda s: s["started_at"], reverse=True),
            list(summaries),
        )
        self.assertTrue(all(summary["id"].startswith("act_") for summary in summaries))

    def test_deleted_sessions_are_not_summarised(self) -> None:
        populate(self)
        # The survivor of the merged ride: its merged Garmin copy must go with it.
        session_id = self.rows(
            "SELECT merged_into FROM activity_sessions WHERE state = 'duplicate'"
        )[0]["merged_into"]
        self.execute(
            "UPDATE activity_sessions SET state = 'deleted' WHERE activity_id = ?",
            (session_id,),
        )

        summaries = self.read(make_selector(self).activity_summaries)

        self.assertNotIn(session_id, [summary["id"] for summary in summaries])
        self.assertFalse(any(len(s["record_ids"]) > 1 for s in summaries))

    def test_records_of_an_unknown_provider_are_skipped(self) -> None:
        populate(self)
        before = self.read(make_selector(self).activity_summaries)
        self.execute(
            "UPDATE activity_records SET provider = 'retired-provider' "
            "WHERE provider_activity_id = 'i-act-002'"
        )

        after = self.read(make_selector(self).activity_summaries)

        self.assertEqual(len(before) - 1, len(after))

    def test_a_limit_keeps_the_same_newest_summaries(self) -> None:
        populate(self)
        selector = make_selector(self)
        everything = self.read(selector.activity_summaries)

        for limit in (1, 2, 3, len(everything), len(everything) + 5):
            with self.subTest(limit=limit):
                self.assertEqual(
                    everything[:limit],
                    self.read(selector.activity_summaries, limit=limit),
                )

    def test_a_limit_is_filled_when_newer_sessions_have_no_active_record(
        self,
    ) -> None:
        populate(self)
        newest = self.rows(
            "SELECT provider_activity_id FROM activity_records "
            "ORDER BY started_at DESC LIMIT 2"
        )
        for row in newest:
            self.execute(
                "UPDATE activity_records SET state = 'invalid' "
                "WHERE provider_activity_id = ?",
                (row["provider_activity_id"],),
            )
        selector = make_selector(self)
        everything = self.read(selector.activity_summaries)

        for limit in (1, 2, 3):
            with self.subTest(limit=limit):
                self.assertEqual(
                    everything[:limit],
                    self.read(selector.activity_summaries, limit=limit),
                )
