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
from backend.canonical.section_items import section_of, split_section, wrapped
from backend.canonical.vocabulary import ProviderId
from backend.providers import canonical_plans as plans
from backend.providers.garmin_health_mapping import map_garmin_health
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
            all(
                item.mapper_version == plans.INTERVALS_WELLNESS_VERSION
                for item in plan.observations
            ),
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
        plan = plans.garmin_ingest_plan(["not", "a", "mapping"], zone=ZONE)
        self.assertEqual(plan, plans.IngestPlan(provider=ProviderId.GARMIN))

    def test_activities_are_planned_by_activity_id_and_invalid_ones_counted(
        self,
    ) -> None:
        payload = {
            "synced_at": RETRIEVED_AT.isoformat(),
            "activities": [
                garmin_row(),
                {"activityName": "no identifier"},
                "junk",
            ],
        }
        plan = plans.garmin_ingest_plan(payload, zone=ZONE)
        self.assertEqual(
            [item.record.provenance.source_record_id for item in plan.activities],
            ["910010"],
        )
        self.assertEqual(plan.skipped_invalid, 2)
        self.assertEqual(plan.present_activity_ids, frozenset({"910010"}))

    def test_non_list_activities_are_ignored(self) -> None:
        plan = plans.garmin_ingest_plan(
            {"synced_at": RETRIEVED_AT.isoformat(), "activities": None}, zone=ZONE
        )
        self.assertEqual(plan.activities, ())
        self.assertEqual(plan.skipped_invalid, 0)

    def test_health_sections_become_one_raw_record_each(self) -> None:
        payload = {
            "synced_at": RETRIEVED_AT.isoformat(),
            "sleep": {"hours": 7},
            "hrv": None,
            "resting_hr": [49],
        }
        plan = plans.garmin_ingest_plan(payload, zone=ZONE)
        health = [
            (item.source_record_id, dict(item.payload))
            for item in plan.raw_records
            if item.record_kind == plans.HEALTH_RECORD_KIND
        ]
        # Each raw record holds one element as the health mapper reads it, so re-projection can rebuild it.
        self.assertEqual(
            [(section_of(record_id), body) for record_id, body in health],
            [("resting_hr", {"resting_hr": [49]}), ("sleep", {"sleep": {"hours": 7}})],
        )
        self.assertTrue(health[0][0].startswith("resting_hr/"))
        self.assertEqual(health[1][0], "sleep")


if __name__ == "__main__":
    unittest.main()


EARLIER = datetime(2026, 10, 10, 6, 0, tzinfo=UTC)
MORNING = datetime(2026, 10, 11, 5, 30, tzinfo=UTC)


def garmin_health_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {"synced_at": RETRIEVED_AT.isoformat()}
    for name in plans.GARMIN_HEALTH_SECTION_NAMES:
        path = FIXTURES / "garmin" / f"{name}.json"
        if path.exists():
            payload[name] = fixture("garmin", f"{name}.json")
    return payload


class GarminSectionTimeTests(unittest.TestCase):
    def test_sections_mapped_one_by_one_match_one_whole_payload_mapping(self) -> None:
        payload = garmin_health_payload()
        plan = plans.garmin_ingest_plan(payload, zone=ZONE)
        expected = [
            observation
            for name in plans.GARMIN_HEALTH_SECTION_NAMES
            for section in (
                plans.WEIGHT_SECTIONS
                if name == plans.GARMIN_WEIGHT_SECTION
                else (name,)
            )
            for item in split_section(payload.get(section))
            if item.value is not None
            for observation in map_garmin_health(
                wrapped(section, item), zone=ZONE, retrieved_at=RETRIEVED_AT
            ).records
        ]
        self.assertGreater(len(expected), 0)
        self.assertEqual([item.observation for item in plan.observations], expected)

    def test_a_retained_section_keeps_the_time_of_the_read_that_fetched_it(
        self,
    ) -> None:
        payload = garmin_health_payload()
        payload["source_freshness"] = {
            "hrv": {"freshness": "stale", "fetched_at": EARLIER.isoformat()},
            "sleep": {"freshness": "current", "fetched_at": RETRIEVED_AT.isoformat()},
        }
        payload["activities"] = [garmin_row()]
        plan = plans.garmin_ingest_plan(payload, zone=ZONE)
        raw_times = {
            item.source_record_id: item.retrieved_at for item in plan.raw_records
        }
        by_section = {
            section_of(key): at for key, at in raw_times.items() if key != "910010"
        }
        self.assertEqual(by_section["hrv"], EARLIER)
        self.assertEqual(by_section["sleep"], RETRIEVED_AT)
        self.assertEqual(raw_times["910010"], RETRIEVED_AT)
        self.assertEqual(plan.activities[0].retrieved_at, RETRIEVED_AT)
        hrv = [
            item.observation.provenance.retrieved_at
            for item in plan.observations
            if item.observation.kind.value.startswith("hrv")
        ]
        self.assertTrue(hrv)
        self.assertEqual(set(hrv), {EARLIER})

    def test_a_successful_morning_refresh_stamps_body_battery_only(self) -> None:
        payload = {
            "synced_at": EARLIER.isoformat(),
            "body_battery": fixture("garmin", "body_battery.json"),
            "sleep": fixture("garmin", "sleep.json"),
            "morning_body_battery": {"attempted_at": MORNING.isoformat()},
        }
        self.assertEqual(
            plans.garmin_section_retrieved_at(payload, "body_battery", zone=ZONE),
            MORNING,
        )
        self.assertEqual(
            plans.garmin_section_retrieved_at(payload, "sleep", zone=ZONE), EARLIER
        )
        self.assertEqual(plans.garmin_payload_retrieved_at(payload, zone=ZONE), MORNING)

    def test_an_older_or_failed_morning_attempt_does_not_restamp_body_battery(
        self,
    ) -> None:
        older = {
            "synced_at": RETRIEVED_AT.isoformat(),
            "morning_body_battery": {"attempted_at": EARLIER.isoformat()},
        }
        failed = {
            "synced_at": EARLIER.isoformat(),
            "morning_body_battery": {
                "attempted_at": MORNING.isoformat(),
                "error": "unavailable",
            },
        }
        unparsable = {
            "synced_at": EARLIER.isoformat(),
            "morning_body_battery": {"attempted_at": "not a time"},
        }
        for payload, expected in (
            (older, RETRIEVED_AT),
            (failed, EARLIER),
            (unparsable, EARLIER),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(
                    plans.garmin_section_retrieved_at(
                        payload, "body_battery", zone=ZONE
                    ),
                    expected,
                )

    def test_a_payload_without_any_sync_time_keeps_only_dated_sections(self) -> None:
        payload = {
            "activities": [garmin_row()],
            "sleep": fixture("garmin", "sleep.json"),
            "body_battery": fixture("garmin", "body_battery.json"),
            "morning_body_battery": {"attempted_at": MORNING.isoformat()},
        }
        plan = plans.garmin_ingest_plan(payload, zone=ZONE)
        self.assertEqual(plan.activities, ())
        self.assertEqual(
            {section_of(item.source_record_id) for item in plan.raw_records},
            {"body_battery"},
        )
        self.assertTrue(all(item.retrieved_at == MORNING for item in plan.raw_records))
        # Only the Body Battery section has a fetch time; the sleep section is left out.
        self.assertEqual(
            {
                (item.observation.provenance.source_record_id or "").partition(":")[0]
                for item in plan.observations
            },
            {"body_battery"},
        )
        self.assertTrue(
            all(
                item.observation.provenance.retrieved_at == MORNING
                for item in plan.observations
            )
        )
        self.assertEqual(plan.domain_batches, ())
        self.assertEqual(plans.garmin_payload_retrieved_at(payload, zone=ZONE), MORNING)

    def test_no_fetch_time_at_all_gives_none(self) -> None:
        self.assertIsNone(plans.garmin_payload_retrieved_at({}, zone=ZONE))
        self.assertIsNone(plans.garmin_payload_retrieved_at(["junk"], zone=ZONE))
        self.assertEqual(
            plans.garmin_ingest_plan({"sleep": {"hours": 7}}, zone=ZONE),
            plans.IngestPlan(provider=ProviderId.GARMIN),
        )
