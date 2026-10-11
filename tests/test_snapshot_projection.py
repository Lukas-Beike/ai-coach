"""Provider snapshot projection: stored keys, empty results and malformed input."""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from support import (
    PROVIDER_SYNCED_TEXT,
    garmin_payload_fixture,
    intervals_snapshot_fixture,
    load_provider_fixture,
)

from backend.canonical.mapping import IssueReason, MappingResult
from backend.providers.snapshot_projection import (
    project_garmin_snapshot,
    project_intervals_snapshot,
    stored_retrieved_at,
)

BERLIN = ZoneInfo("Europe/Berlin")
SYNCED_AT = datetime(2026, 10, 10, 6, 0, tzinfo=UTC)
GARBAGE_VALUES: tuple[object, ...] = (
    None,
    0,
    3.5,
    "text",
    [],
    [None, 1, "x"],
    ("a",),
    {},
    {"nested": ["x"]},
)


class StoredRetrievedAtTests(unittest.TestCase):
    def test_reads_aware_stored_time(self) -> None:
        self.assertEqual(
            stored_retrieved_at({"synced_at": PROVIDER_SYNCED_TEXT}, zone=BERLIN),
            SYNCED_AT,
        )

    def test_reads_naive_stored_time_as_athlete_wall_time(self) -> None:
        self.assertEqual(
            stored_retrieved_at({"synced_at": "2026-10-10T08:00:00"}, zone=BERLIN),
            SYNCED_AT,
        )

    def test_missing_or_unusable_stored_time_is_none(self) -> None:
        records: tuple[object, ...] = (
            None,
            [],
            "text",
            {},
            {"synced_at": None},
            {"synced_at": "not a time"},
            {"synced_at": 1786000000},
        )
        for record in records:
            with self.subTest(record=record):
                self.assertIsNone(stored_retrieved_at(record, zone=BERLIN))


class IntervalsProjectionTests(unittest.TestCase):
    def test_non_mapping_snapshot_projects_to_empty_results(self) -> None:
        snapshots: tuple[object, ...] = (None, [], "text", 3)
        for snapshot in snapshots:
            with self.subTest(snapshot=snapshot):
                activities, observations = project_intervals_snapshot(
                    snapshot, zone=BERLIN, retrieved_at=SYNCED_AT
                )
                self.assertEqual(activities, MappingResult())
                self.assertEqual(observations, MappingResult())

    def test_wrong_section_types_report_one_issue_each(self) -> None:
        snapshot: dict[str, object] = {
            "recent_activities": "text",
            "recent_wellness": None,
            "athlete": [],
        }

        activities, observations = project_intervals_snapshot(
            snapshot, zone=BERLIN, retrieved_at=SYNCED_AT
        )

        self.assertEqual(activities.records, ())
        self.assertEqual(observations.records, ())
        self.assertEqual(len(activities.issues), 1)
        self.assertEqual(len(observations.issues), 2)
        for issue in (*activities.issues, *observations.issues):
            self.assertEqual(issue.reason, IssueReason.INVALID_TYPE)

    def test_athlete_thresholds_are_dated_on_retrieved_local_date(self) -> None:
        # 00:30 on 10 October in Berlin is still 9 October in UTC.
        retrieved_at = datetime(2026, 10, 9, 22, 30, tzinfo=UTC)

        _, observations = project_intervals_snapshot(
            {"athlete": load_provider_fixture("intervals/athlete.json")},
            zone=BERLIN,
            retrieved_at=retrieved_at,
        )

        self.assertTrue(observations.records)
        self.assertEqual(
            {observation.observed_on for observation in observations.records},
            {date(2026, 10, 10)},
        )

    def test_wellness_and_athlete_observations_are_merged_in_order(self) -> None:
        snapshot = intervals_snapshot_fixture()
        wellness_only = {"recent_wellness": snapshot["recent_wellness"]}
        athlete_only = {"athlete": snapshot["athlete"]}

        _, merged = project_intervals_snapshot(
            snapshot, zone=BERLIN, retrieved_at=SYNCED_AT
        )
        _, wellness = project_intervals_snapshot(
            wellness_only, zone=BERLIN, retrieved_at=SYNCED_AT
        )
        _, athlete = project_intervals_snapshot(
            athlete_only, zone=BERLIN, retrieved_at=SYNCED_AT
        )

        self.assertEqual(merged.records, wellness.records + athlete.records)
        self.assertEqual(merged.issues, ())


class GarminProjectionTests(unittest.TestCase):
    def test_non_mapping_payload_projects_to_empty_results(self) -> None:
        payloads: tuple[object, ...] = (None, [], "text", 3)
        for payload in payloads:
            with self.subTest(payload=payload):
                activities, observations = project_garmin_snapshot(
                    payload, zone=BERLIN, retrieved_at=SYNCED_AT
                )
                self.assertEqual(activities, MappingResult())
                self.assertEqual(observations, MappingResult())

    def test_activities_of_wrong_type_report_one_issue(self) -> None:
        activities, observations = project_garmin_snapshot(
            {"activities": "text"}, zone=BERLIN, retrieved_at=SYNCED_AT
        )

        self.assertEqual(activities.records, ())
        self.assertEqual(len(activities.issues), 1)
        self.assertEqual(activities.issues[0].reason, IssueReason.INVALID_TYPE)
        self.assertEqual(observations, MappingResult())

    def test_fixture_payload_maps_activities_and_health_observations(self) -> None:
        activities, observations = project_garmin_snapshot(
            garmin_payload_fixture(), zone=BERLIN, retrieved_at=SYNCED_AT
        )

        self.assertEqual(len(activities.records), 2)
        self.assertEqual(activities.issues, ())
        self.assertTrue(observations.records)
        self.assertTrue(
            all(
                observation.provenance.retrieved_at == SYNCED_AT
                for observation in observations.records
            )
        )


class MalformedInputTests(unittest.TestCase):
    def test_garbage_documents_and_sections_never_raise(self) -> None:
        for garbage in GARBAGE_VALUES:
            with self.subTest(garbage=garbage):
                intervals = project_intervals_snapshot(
                    {
                        "recent_activities": garbage,
                        "recent_wellness": garbage,
                        "athlete": garbage,
                    },
                    zone=BERLIN,
                    retrieved_at=SYNCED_AT,
                )
                garmin = project_garmin_snapshot(
                    {
                        "activities": garbage,
                        "sleep": garbage,
                        "weight": garbage,
                        "running_threshold": garbage,
                        "cycling_ftp": garbage,
                    },
                    zone=BERLIN,
                    retrieved_at=SYNCED_AT,
                )
                for activities, observations in (intervals, garmin):
                    self.assertIsInstance(activities, MappingResult)
                    self.assertIsInstance(observations, MappingResult)
                self.assertIsInstance(
                    project_intervals_snapshot(
                        garbage, zone=BERLIN, retrieved_at=SYNCED_AT
                    )[0],
                    MappingResult,
                )
                self.assertIsInstance(
                    project_garmin_snapshot(
                        garbage, zone=BERLIN, retrieved_at=SYNCED_AT
                    )[1],
                    MappingResult,
                )

    def test_malformed_rows_become_counted_issues_not_records(self) -> None:
        snapshot = {
            "recent_activities": [None, 3, {"start_date_local": 5}],
            "recent_wellness": [None, "row", {"id": 7}],
        }

        activities, observations = project_intervals_snapshot(
            snapshot, zone=BERLIN, retrieved_at=SYNCED_AT
        )

        self.assertEqual(activities.records, ())
        self.assertEqual(observations.records, ())
        self.assertTrue(activities.issues)
