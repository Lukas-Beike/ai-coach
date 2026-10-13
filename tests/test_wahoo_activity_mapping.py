"""Wahoo workout mapper and ingest plan: sports, faults, local dates, ids."""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.canonical.mapping import IssueReason
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    Sport,
)
from backend.providers.canonical_plans import (
    current_mapper_versions,
    wahoo_ingest_plan,
)
from backend.providers.wahoo_activity_mapping import (
    MAPPER_VERSION,
    WAHOO_LABEL,
    WAHOO_WORKOUT_TYPES,
    map_wahoo_activities,
)

FETCHED = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
BERLIN = ZoneInfo("Europe/Berlin")
LOS_ANGELES = ZoneInfo("America/Los_Angeles")


def row(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 100,
        "starts": "2026-10-11T06:30:00.000Z",
        "minutes": 999,
        "name": "Morning ride",
        "workout_type_id": 0,
        "workout_summary": {
            "duration_active_accum": "3600.4",
            "duration_total_accum": "3900",
            "distance_accum": "30250.5",
            "heart_rate_avg": "142.3",
            "power_avg": "210",
            "calories_accum": "700",
        },
    }
    base.update(changes)
    return base


def mapped(*rows: object) -> Any:
    return map_wahoo_activities(list(rows), zone=UTC, retrieved_at=FETCHED)


class SportTests(unittest.TestCase):
    def test_each_workout_type_maps_to_its_sport_and_environment(self) -> None:
        cases = {
            0: (Sport.RIDE, Environment.OUTDOOR),
            12: (Sport.RIDE, Environment.INDOOR),
            68: (Sport.RIDE, Environment.VIRTUAL),
            1: (Sport.RUN, Environment.OUTDOOR),
            5: (Sport.RUN, Environment.INDOOR),
            6: (Sport.WALK, Environment.OUTDOOR),
            9: (Sport.HIKE, Environment.OUTDOOR),
            25: (Sport.SWIM, Environment.INDOOR),
            26: (Sport.SWIM, Environment.OUTDOOR),
            22: (Sport.ROW, Environment.INDOOR),
            30: (Sport.NORDIC_SKI, Environment.OUTDOOR),
            29: (Sport.ALPINE_SKI, Environment.OUTDOOR),
            66: (Sport.YOGA, Environment.UNKNOWN),
            255: (Sport.OTHER, Environment.UNKNOWN),
        }
        for type_id, expected in cases.items():
            with self.subTest(type_id=type_id):
                record = mapped(row(workout_type_id=type_id)).records[0]
                self.assertEqual(expected, (record.sport, record.environment))
                self.assertEqual(expected, WAHOO_WORKOUT_TYPES[type_id])

    def test_digit_text_type_ids_are_accepted(self) -> None:
        record = mapped(row(workout_type_id="1")).records[0]

        self.assertIs(Sport.RUN, record.sport)

    def test_unknown_type_is_other_with_an_issue_and_keeps_the_record(self) -> None:
        result = mapped(row(workout_type_id=9999))

        record = result.records[0]
        self.assertEqual(
            (Sport.OTHER, Environment.UNKNOWN), (record.sport, record.environment)
        )
        self.assertEqual(
            [("workout_type_id", IssueReason.UNKNOWN_VALUE)],
            [(issue.field, issue.reason) for issue in result.issues],
        )

    def test_missing_and_invalid_types_keep_the_record_as_other(self) -> None:
        for value, reason in (
            (None, IssueReason.MISSING),
            (True, IssueReason.INVALID_TYPE),
            ("run", IssueReason.INVALID_TYPE),
            (1.5, IssueReason.INVALID_TYPE),
        ):
            with self.subTest(value=value):
                result = mapped(row(workout_type_id=value))
                self.assertIs(Sport.OTHER, result.records[0].sport)
                self.assertEqual([reason], [issue.reason for issue in result.issues])


class FieldTests(unittest.TestCase):
    def test_summary_values_map_to_canonical_numbers(self) -> None:
        record = mapped(row()).records[0]

        self.assertEqual("100", record.activity_id)
        self.assertEqual(3600.4, record.duration_s)
        self.assertEqual(30250.5, record.distance_m)
        self.assertEqual(142.3, record.avg_hr)
        self.assertEqual(210.0, record.avg_power)
        self.assertIsNone(record.load)
        self.assertIs(LoadModel.UNKNOWN, record.load_model)
        self.assertEqual("Morning ride", record.name)
        self.assertEqual(datetime(2026, 10, 11, 6, 30, tzinfo=UTC), record.started_at)

    def test_provenance_names_wahoo_as_provider_and_recorder(self) -> None:
        provenance = mapped(row()).records[0].provenance

        self.assertIs(ProviderId.WAHOO, provenance.provider)
        self.assertIs(RecordingOrigin.WAHOO, provenance.recorded_by)
        self.assertEqual("100", provenance.source_record_id)
        self.assertEqual(WAHOO_LABEL, provenance.label)
        self.assertEqual(FETCHED, provenance.retrieved_at)

    def test_planned_minutes_are_never_the_duration(self) -> None:
        record = mapped(row(workout_summary=None)).records[0]

        self.assertIsNone(record.duration_s)

    def test_total_duration_is_the_fallback_for_the_active_duration(self) -> None:
        summary = {"duration_active_accum": None, "duration_total_accum": "1800"}

        record = mapped(row(workout_summary=summary)).records[0]

        self.assertEqual(1800.0, record.duration_s)

    def test_a_missing_summary_is_not_an_issue(self) -> None:
        result = mapped(row(workout_summary=None))

        self.assertEqual((), result.issues)
        self.assertIsNone(result.records[0].distance_m)

    def test_invalid_summary_fields_become_none_with_a_value_free_issue(self) -> None:
        summary = {
            "duration_active_accum": "secret-text-SENTINEL",
            "distance_accum": "-5",
            "heart_rate_avg": "900",
            "power_avg": "NaN",
        }

        result = mapped(row(workout_summary=summary))

        record = result.records[0]
        self.assertEqual(
            (None, None, None, None),
            (record.duration_s, record.distance_m, record.avg_hr, record.avg_power),
        )
        self.assertEqual(
            {
                "duration_active_accum",
                "distance_accum",
                "heart_rate_avg",
                "power_avg",
            },
            {issue.field for issue in result.issues},
        )
        self.assertNotIn("SENTINEL", repr(result.issues))
        self.assertTrue(all(issue.record_ref == "100" for issue in result.issues))

    def test_a_non_object_summary_is_an_issue_not_a_failure(self) -> None:
        result = mapped(row(workout_summary=["x"]))

        self.assertEqual(1, len(result.records))
        self.assertEqual("workout_summary", result.issues[0].field)

    def test_names_are_trimmed_and_bounded(self) -> None:
        self.assertEqual("Ride", mapped(row(name="  Ride  ")).records[0].name)
        self.assertIsNone(mapped(row(name="   ")).records[0].name)
        self.assertEqual(200, len(mapped(row(name="x" * 500)).records[0].name or ""))
        result = mapped(row(name=5))
        self.assertIsNone(result.records[0].name)
        self.assertEqual("name", result.issues[0].field)


class DroppedRowTests(unittest.TestCase):
    def test_rows_without_a_usable_id_or_start_are_dropped_with_an_issue(self) -> None:
        cases = (
            (row(id=None), "id", IssueReason.MISSING),
            (row(id=True), "id", IssueReason.INVALID_TYPE),
            (row(id="abc"), "id", IssueReason.INVALID_TYPE),
            (row(id=0), "id", IssueReason.OUT_OF_RANGE),
            (row(id=2**63), "id", IssueReason.OUT_OF_RANGE),
            (row(starts=None), "starts", IssueReason.MISSING),
            (row(starts="  "), "starts", IssueReason.MISSING),
            (row(starts="not a date"), "starts", IssueReason.INVALID_TYPE),
        )
        for bad, field, reason in cases:
            with self.subTest(field=field, reason=reason):
                result = mapped(bad)
                self.assertEqual((), result.records)
                self.assertIn(
                    (field, reason), [(i.field, i.reason) for i in result.issues]
                )

    def test_non_object_rows_and_non_list_input_never_raise(self) -> None:
        result = mapped("text", 3, None)
        self.assertEqual((), result.records)
        self.assertEqual(3, len(result.issues))
        bad = map_wahoo_activities({"workouts": []}, zone=UTC, retrieved_at=FETCHED)
        self.assertEqual("rows", bad.issues[0].field)

    def test_naive_retrieval_time_is_a_programming_error(self) -> None:
        with self.assertRaises(ValueError):
            map_wahoo_activities([], zone=UTC, retrieved_at=datetime(2026, 1, 1))  # noqa: DTZ001 - naive on purpose

    def test_start_without_an_offset_is_read_as_utc(self) -> None:
        record = mapped(row(starts="2026-10-11T06:30:00")).records[0]

        self.assertEqual(datetime(2026, 10, 11, 6, 30, tzinfo=UTC), record.started_at)

    def test_ids_are_deterministic_and_digit_text_equals_the_integer(self) -> None:
        first = mapped(row(id=100)).records[0]
        again = mapped(row(id=100)).records[0]
        text = mapped(row(id="100")).records[0]

        self.assertEqual(first, again)
        self.assertEqual(first.activity_id, text.activity_id)
        self.assertEqual("100", first.activity_id)


class IngestPlanTests(unittest.TestCase):
    def payload(self, *rows: object, synced_at: object = FETCHED.isoformat()) -> dict:
        return {"synced_at": synced_at, "workouts": list(rows)}

    def test_local_date_follows_the_athlete_zone(self) -> None:
        late = row(starts="2026-10-11T22:30:00.000Z")
        payload = self.payload(late)

        berlin = wahoo_ingest_plan(payload, zone=BERLIN).activities[0]
        utc = wahoo_ingest_plan(payload, zone=UTC).activities[0]
        los_angeles = wahoo_ingest_plan(payload, zone=LOS_ANGELES).activities[0]

        self.assertEqual(date(2026, 10, 12), berlin.local_date)
        self.assertEqual(date(2026, 10, 11), utc.local_date)
        self.assertEqual(date(2026, 10, 11), los_angeles.local_date)

    def test_the_workouts_own_time_zone_field_is_ignored(self) -> None:
        shifted = row(starts="2026-10-11T22:30:00.000Z", time_zone="Asia/Tokyo")

        plan = wahoo_ingest_plan(self.payload(shifted), zone=UTC)

        self.assertEqual(date(2026, 10, 11), plan.activities[0].local_date)

    def test_plan_carries_provider_raw_records_and_mapper_version(self) -> None:
        plan = wahoo_ingest_plan(self.payload(row(id=1), row(id=2)), zone=UTC)

        self.assertIs(ProviderId.WAHOO, plan.provider)
        self.assertEqual(frozenset({"1", "2"}), plan.present_activity_ids)
        self.assertEqual(["1", "2"], [r.source_record_id for r in plan.raw_records])
        self.assertEqual({MAPPER_VERSION}, {i.mapper_version for i in plan.activities})
        self.assertEqual(MAPPER_VERSION, current_mapper_versions()["wahoo.activity"])

    def test_invalid_rows_are_counted_and_do_not_drop_valid_ones(self) -> None:
        plan = wahoo_ingest_plan(
            self.payload(row(id=1), row(id=None), "text", row(id=3, starts=None)),
            zone=UTC,
        )

        self.assertEqual(["1"], [i.record.activity_id for i in plan.activities])
        self.assertEqual(3, plan.skipped_invalid)

    def test_without_a_fetch_time_nothing_is_planned(self) -> None:
        for synced_at in (None, "", "garbage"):
            with self.subTest(synced_at=synced_at):
                plan = wahoo_ingest_plan(
                    self.payload(row(), synced_at=synced_at), zone=UTC
                )
                self.assertEqual((), plan.activities)
                self.assertEqual((), plan.raw_records)

    def test_a_non_list_workout_payload_plans_nothing(self) -> None:
        payloads: tuple[object, ...] = (
            {"synced_at": FETCHED.isoformat(), "workouts": {}},
            None,
            [],
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                plan = wahoo_ingest_plan(payload, zone=UTC)
                self.assertEqual((), plan.activities)


if __name__ == "__main__":
    unittest.main()
