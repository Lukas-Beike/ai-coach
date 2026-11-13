"""Canonical table reader: stored rows only, the canonical order and the stored-state rules."""

from __future__ import annotations

from datetime import date

from canonical_read_support import (
    WAHOO_RUN_COPY,
    CanonicalReadFixture,
    drop_intervals_activities,
    make_selector,
    populate,
    store_wahoo_run_copy,
)

from backend.backup.export import PRIVACY_EXPORT_JSONL_SOURCES
from backend.canonical.vocabulary import MetricKind, Sport
from backend.providers.canonical_plans import current_observation_mapper_versions

# Garmin activities a minute either side of both daylight-saving changes.
DST_ACTIVITIES = [
    ("920001", "2026-03-29 01:59:00", "running", 2400.0),
    ("920002", "2026-03-29 03:01:00", "running", 2300.0),
    ("920003", "2026-10-25 01:59:00", "cycling", 3600.0),
    ("920004", "2026-10-25 03:01:00", "cycling", 3300.0),
]
# The Garmin activities in canonical order: provider activity id, provider and
# elapsed duration.
FIXTURE_ACTIVITIES = [
    ("920001", "garmin", 2400.0),
    ("920002", "garmin", 2300.0),
    ("910001", "garmin", 5400.0),
    ("910002", "garmin", 2400.0),
    ("920003", "garmin", 3600.0),
    ("920004", "garmin", 3300.0),
]


def garmin_activities_only(case: CanonicalReadFixture) -> None:
    """The Garmin fixture rides and runs plus the daylight-saving boundary ones."""
    drop_intervals_activities(case)
    case.garmin["activities"] = [
        *case.garmin["activities"],
        *(
            {
                "activityId": int(activity_id),
                "activityName": "Synthetic daylight-saving boundary",
                "activityType": {"typeKey": sport},
                "startTimeLocal": local,
                "duration": duration,
                "distance": 7600.0,
            }
            for activity_id, local, sport, duration in DST_ACTIVITIES
        ),
    ]


# The stored observations per metric after the fixture backfill.
FIXTURE_OBSERVATION_COUNTS = {
    "weight": 5,
    "ftp": 5,
    "threshold_hr": 4,
    "max_hr": 2,
    "resting_hr": 4,
    "hrv_rmssd": 4,
    "hrv_weekly_average": 1,
    "sleep_duration": 5,
    "sleep_score": 5,
    "vo2max": 2,
    "threshold_pace": 2,
    "readiness": 4,
    "ctl": 3,
    "atl": 3,
    "form": 3,
    "eftp": 4,
    "acute_load": 1,
    "chronic_load": 1,
    "acute_chronic_ratio": 1,
    "load_balance_aerobic_low": 1,
    "load_balance_aerobic_low_target_min": 1,
    "load_balance_aerobic_low_target_max": 1,
    "load_balance_aerobic_high": 1,
    "load_balance_aerobic_high_target_min": 1,
    "load_balance_aerobic_high_target_max": 1,
    "load_balance_anaerobic": 1,
    "load_balance_anaerobic_target_min": 1,
    "load_balance_anaerobic_target_max": 1,
    "subjective_fatigue": 3,
    "subjective_soreness": 3,
    "subjective_stress": 3,
    "subjective_mood": 3,
    "w_prime": 1,
    "height": 1,
}


class CanonicalTableReaderTests(CanonicalReadFixture):
    def test_populated_tables_serve_the_activities_in_canonical_order(
        self,
    ) -> None:
        garmin_activities_only(self)
        populate(self)
        table = self.read(self.table.activities)

        self.assertEqual(
            [(a.activity_id, a.provenance.provider.value) for a in table],
            [
                (activity_id, provider)
                for activity_id, provider, _ in FIXTURE_ACTIVITIES
            ],
        )

    def test_stored_activities_keep_their_elapsed_duration(self) -> None:
        garmin_activities_only(self)
        populate(self)
        table = self.read(self.table.activities)

        self.assertEqual(
            [a.elapsed_duration_s for a in table],
            [elapsed for _id, _provider, elapsed in FIXTURE_ACTIVITIES],
        )

    def test_populated_tables_serve_one_observation_per_natural_key(self) -> None:
        populate(self)
        counts = {
            kind.value: len(served)
            for kind in MetricKind
            if (served := self.read(self.table.observations, kind))
        }
        # Identical duplicate source rows (for example two Garmin FTP sections)
        # collapse to one row per natural key.
        self.assertEqual(counts, FIXTURE_OBSERVATION_COUNTS)

    def test_activity_bounds_select_the_athlete_local_day(self) -> None:
        garmin_activities_only(self)
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
    def test_backfilled_copies_are_summarised_once_per_session(
        self,
    ) -> None:
        populate(self)
        store_wahoo_run_copy(self)
        grouped = self.read(self.table.activity_sessions)
        summaries = self.read(make_selector(self).activity_summaries)

        self.assertEqual(len(grouped), len(summaries))
        groups = [
            sorted(record.activity_id for record in records) for _id, records in grouped
        ]
        self.assertIn(["910002", WAHOO_RUN_COPY], groups)
        self.assertEqual(1, sum("910002" in group for group in groups))
        merged = [s for s in summaries if "910002" in s["record_ids"].values()]
        self.assertEqual(
            [{"garmin": "910002", "wahoo": WAHOO_RUN_COPY}],
            [summary["record_ids"] for summary in merged],
        )
        self.assertEqual(
            sorted(summaries, key=lambda s: s["started_at"], reverse=True),
            list(summaries),
        )
        self.assertTrue(all(summary["id"].startswith("act_") for summary in summaries))

    def test_deleted_sessions_are_not_summarised(self) -> None:
        populate(self)
        store_wahoo_run_copy(self)
        # The survivor of the merged run: its merged copy must go with it.
        session_id = self.rows(
            "SELECT s.merged_into FROM activity_records AS r "
            "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
            "WHERE s.state = 'duplicate' AND r.provider_activity_id IN (?, ?)",
            ("910002", WAHOO_RUN_COPY),
        )[0]["merged_into"]
        self.execute(
            "UPDATE activity_sessions SET state = 'deleted' WHERE activity_id = ?",
            (session_id,),
        )

        summaries = self.read(make_selector(self).activity_summaries)

        self.assertNotIn(session_id, [summary["id"] for summary in summaries])
        shown = {
            value for summary in summaries for value in summary["record_ids"].values()
        }
        self.assertFalse({"910002", WAHOO_RUN_COPY} & shown)

    def test_stored_intervals_copies_are_never_served_but_stay_stored(self) -> None:
        # Intervals.icu is output only (#2148): no reader serves its copies.
        populate(self)
        served = [
            *self.read(self.table.activities),
            *(
                record
                for _id, records in self.read(self.table.activity_sessions)
                for record in records
            ),
        ]
        self.assertTrue(served)
        self.assertNotIn(
            "intervals", {record.provenance.provider.value for record in served}
        )
        for session_id, _records in self.read(self.table.activity_sessions):
            self.assertNotIn(
                "intervals",
                {
                    record.provenance.provider.value
                    for record in self.read(self.table.session_activities, session_id)
                },
            )
        exported = dict(PRIVACY_EXPORT_JSONL_SOURCES)["activity_records.jsonl"]
        stored = {row["provider_activity_id"] for row in self.read(exported)}
        self.assertTrue(
            {"i-act-001", "i-act-002", "i-act-003", "i-act-004", "i-act-005"} <= stored
        )

    def test_records_of_an_unknown_provider_are_skipped(self) -> None:
        drop_intervals_activities(self)
        populate(self)
        before = self.read(make_selector(self).activity_summaries)
        self.execute(
            "UPDATE activity_records SET provider = 'retired-provider' "
            "WHERE provider_activity_id = '910001'"
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
