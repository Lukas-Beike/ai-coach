"""Pure canonical ingest plans: identifiers, skipped rows and per-provider shape.

Fixtures are synthetic and read with the standard library only. No database,
network, provider account or real data directory is involved.
"""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.canonical.mapping import MappingResult
from backend.canonical.records import ActivityRecord
from backend.canonical.vocabulary import ProviderId
from backend.providers import canonical_plans as plans
from backend.providers.intervals_activity_mapping import map_intervals_activities

ZONE = ZoneInfo("Europe/Berlin")
RETRIEVED_AT = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "providers"
ACTIVITY_ROW: dict[str, Any] = {
    "id": "i-plan-1",
    "start_date_local": "2026-06-01T07:00:00",
    "type": "Ride",
}


def fixture(provider: str, name: str) -> Any:
    return json.loads((FIXTURES / provider / name).read_text(encoding="utf-8"))


def garmin_row(**overrides: object) -> dict[str, Any]:
    row: dict[str, Any] = {
        "activityId": 910010,
        "activityName": "Synthetic ride",
        "activityType": {"typeKey": "cycling"},
        "startTimeLocal": "2026-10-08 07:15:00",
        "distance": 20000.0,
        "duration": 3600.0,
        "averageHR": 140,
        "activityTrainingLoad": 50.0,
    }
    row.update(overrides)
    return row


class RowIdTests(unittest.TestCase):
    def test_accepts_text_and_turns_integers_into_text(self) -> None:
        self.assertEqual(plans._row_id({"id": "abc"}, "id"), "abc")
        self.assertEqual(plans._row_id({"id": 42}, "id"), "42")

    def test_accepts_an_identifier_at_the_length_limit(self) -> None:
        identifier = "x" * plans.MAX_RECORD_ID_LENGTH
        self.assertEqual(plans._row_id({"id": identifier}, "id"), identifier)

    def test_rejects_rows_without_a_usable_identifier(self) -> None:
        rows: list[object] = [
            "not a mapping",
            None,
            {},
            {"id": True},
            {"id": 1.5},
            {"id": ""},
            {"id": "   "},
            {"id": "x" * (plans.MAX_RECORD_ID_LENGTH + 1)},
        ]
        for row in rows:
            with self.subTest(row=row):
                self.assertIsNone(plans._row_id(row, "id"))


class ActivityBatchTests(unittest.TestCase):
    def test_non_list_rows_yield_nothing(self) -> None:
        items, raw, skipped, present = plans._activity_batch(
            "not a list",
            id_key="id",
            mapper=lambda rows: map_intervals_activities(
                rows, zone=ZONE, retrieved_at=RETRIEVED_AT
            ),
            mapper_version=1,
            zone=ZONE,
        )
        self.assertEqual((items, raw, skipped, present), ([], [], 0, set()))

    def test_record_without_a_source_identifier_is_skipped(self) -> None:
        mapped = map_intervals_activities(
            [ACTIVITY_ROW], zone=ZONE, retrieved_at=RETRIEVED_AT
        ).records[0]
        unidentified = replace(
            mapped, provenance=replace(mapped.provenance, source_record_id=None)
        )

        def mapper(rows: list[Any]) -> MappingResult[ActivityRecord]:
            return MappingResult(records=(unidentified,))

        items, raw, skipped, present = plans._activity_batch(
            [ACTIVITY_ROW], id_key="id", mapper=mapper, mapper_version=1, zone=ZONE
        )
        self.assertEqual((items, raw, skipped), ([], [], 1))
        # The provider still returned this id, so a full-window deletion must keep it.
        self.assertEqual(present, {"i-plan-1"})


class IntervalsPlanTests(unittest.TestCase):
    def test_non_mapping_raw_block_yields_an_empty_plan(self) -> None:
        plan = plans.intervals_ingest_plan(None, zone=ZONE, retrieved_at=RETRIEVED_AT)
        self.assertEqual(plan, plans.IngestPlan(provider=ProviderId.INTERVALS))

    def test_non_list_activities_are_ignored(self) -> None:
        plan = plans.intervals_ingest_plan(
            {"activities": "nope"}, zone=ZONE, retrieved_at=RETRIEVED_AT
        )
        self.assertEqual(plan.activities, ())
        self.assertEqual(plan.raw_records, ())
        self.assertEqual(plan.skipped_invalid, 0)

    def test_valid_activity_is_planned_and_invalid_rows_are_counted(self) -> None:
        raw = {
            "activities": [
                ACTIVITY_ROW,
                {"type": "Ride", "start_date_local": "2026-06-01T07:00:00"},
                "junk",
            ]
        }
        plan = plans.intervals_ingest_plan(raw, zone=ZONE, retrieved_at=RETRIEVED_AT)
        self.assertEqual(
            [item.record.provenance.source_record_id for item in plan.activities],
            ["i-plan-1"],
        )
        self.assertEqual(plan.activities[0].local_date.isoformat(), "2026-06-01")
        self.assertEqual(plan.skipped_invalid, 2)
        self.assertEqual(plan.present_activity_ids, frozenset({"i-plan-1"}))
        self.assertEqual(
            [(item.record_kind, item.source_record_id) for item in plan.raw_records],
            [(plans.ACTIVITY_RECORD_KIND, "i-plan-1")],
        )

    def test_wellness_rows_need_an_identifier(self) -> None:
        raw = {
            "wellness": [
                {"id": "2026-10-08", "ctl": 40.0},
                {"ctl": 40.0},
                "junk",
            ]
        }
        plan = plans.intervals_ingest_plan(raw, zone=ZONE, retrieved_at=RETRIEVED_AT)
        wellness = [
            item
            for item in plan.raw_records
            if item.record_kind == plans.WELLNESS_RECORD_KIND
        ]
        self.assertEqual([item.source_record_id for item in wellness], ["2026-10-08"])
        self.assertEqual(plan.skipped_invalid, 2)

    def test_wellness_observations_come_from_the_mapper(self) -> None:
        plan = plans.intervals_ingest_plan(
            {"wellness": fixture("intervals", "wellness.json")},
            zone=ZONE,
            retrieved_at=RETRIEVED_AT,
        )
        self.assertTrue(plan.observations)
        self.assertTrue(
            all(item.mapper_version == 2 for item in plan.observations),
        )

    def test_athlete_block_is_mapped_and_a_non_mapping_athlete_is_counted(self) -> None:
        plan = plans.intervals_ingest_plan(
            {"athlete": fixture("intervals", "athlete.json")},
            zone=ZONE,
            retrieved_at=RETRIEVED_AT,
        )
        self.assertIn(
            plans.ATHLETE_RECORD_KIND, [item.record_kind for item in plan.raw_records]
        )
        self.assertTrue(plan.observations)
        self.assertEqual(plan.skipped_invalid, 0)

        malformed = plans.intervals_ingest_plan(
            {"athlete": "bad"}, zone=ZONE, retrieved_at=RETRIEVED_AT
        )
        self.assertEqual(malformed.skipped_invalid, 1)
        self.assertEqual(malformed.raw_records, ())

        absent = plans.intervals_ingest_plan(
            {"athlete": None}, zone=ZONE, retrieved_at=RETRIEVED_AT
        )
        self.assertEqual(absent.skipped_invalid, 0)


class GarminPlanTests(unittest.TestCase):
    def test_non_mapping_payload_yields_an_empty_plan(self) -> None:
        plan = plans.garmin_ingest_plan(
            ["not", "a", "mapping"], zone=ZONE, retrieved_at=RETRIEVED_AT
        )
        self.assertEqual(plan, plans.IngestPlan(provider=ProviderId.GARMIN))

    def test_activities_are_planned_by_activity_id_and_invalid_ones_counted(
        self,
    ) -> None:
        payload = {
            "activities": [
                garmin_row(),
                {"activityName": "no identifier"},
                "junk",
            ]
        }
        plan = plans.garmin_ingest_plan(payload, zone=ZONE, retrieved_at=RETRIEVED_AT)
        self.assertEqual(
            [item.record.provenance.source_record_id for item in plan.activities],
            ["910010"],
        )
        self.assertEqual(plan.skipped_invalid, 2)
        self.assertEqual(plan.present_activity_ids, frozenset({"910010"}))

    def test_non_list_activities_are_ignored(self) -> None:
        plan = plans.garmin_ingest_plan(
            {"activities": None}, zone=ZONE, retrieved_at=RETRIEVED_AT
        )
        self.assertEqual(plan.activities, ())
        self.assertEqual(plan.skipped_invalid, 0)

    def test_health_sections_become_one_raw_record_each(self) -> None:
        payload = {"sleep": {"hours": 7}, "hrv": None, "resting_hr": [49]}
        plan = plans.garmin_ingest_plan(payload, zone=ZONE, retrieved_at=RETRIEVED_AT)
        health = [
            (item.source_record_id, dict(item.payload))
            for item in plan.raw_records
            if item.record_kind == plans.HEALTH_RECORD_KIND
        ]
        self.assertEqual(
            health,
            [("sleep", {"data": {"hours": 7}}), ("resting_hr", {"data": [49]})],
        )


if __name__ == "__main__":
    unittest.main()
