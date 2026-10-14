"""Wahoo power zones and profile weight: mapping, ingest and reprojection."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from backend.canonical.mapping import IssueReason
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.providers import canonical_plans as plans
from backend.providers.wahoo_threshold_mapping import (
    MAPPER_VERSION,
    USER_RECORD_ID,
    map_wahoo_power_zones,
    map_wahoo_threshold_payload,
    map_wahoo_user,
    select_power_zone_sets,
)

RETRIEVED = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
CEST = timezone(timedelta(hours=2))
CYCLING = 0  # workout_type_family_id of biking
RUNNING = 1  # workout_type_family_id of running


def zone_row(
    record_id: int,
    *,
    family: int = CYCLING,
    ftp: Any = 250,
    updated: str = "2026-10-01T10:00:00Z",
) -> dict[str, Any]:
    return {
        "id": record_id,
        "workout_type_family_id": family,
        "ftp": ftp,
        "updated_at": updated,
    }


def reasons(issues: tuple[Any, ...]) -> list[IssueReason]:
    return [issue.reason for issue in issues]


class PowerZoneSelectionTests(unittest.TestCase):
    def test_the_newest_zone_set_of_each_family_is_kept_in_input_order(self) -> None:
        rows = [
            zone_row(1, ftp=240, updated="2026-10-01T10:00:00Z"),
            zone_row(2, ftp=260, updated="2026-10-05T10:00:00Z"),
            zone_row(3, family=RUNNING, ftp=300, updated="2026-09-01T10:00:00Z"),
        ]

        chosen, issues = select_power_zone_sets(rows, zone=UTC)

        self.assertEqual(["2", "3"], [item.record_id for item in chosen])
        self.assertEqual((), issues)

    def test_an_equal_update_time_keeps_the_later_row(self) -> None:
        rows = [zone_row(1, ftp=230), zone_row(2, ftp=250)]

        chosen, _ = select_power_zone_sets(rows, zone=UTC)

        self.assertEqual(["2"], [item.record_id for item in chosen])

    def test_tuples_from_the_client_and_lists_from_storage_are_both_read(self) -> None:
        rows = [zone_row(1)]

        self.assertEqual(1, len(select_power_zone_sets(tuple(rows), zone=UTC)[0]))
        self.assertEqual(1, len(select_power_zone_sets(rows, zone=UTC)[0]))

    def test_a_non_list_payload_is_one_issue(self) -> None:
        chosen, issues = select_power_zone_sets({"id": 1}, zone=UTC)

        self.assertEqual((), chosen)
        self.assertEqual([IssueReason.INVALID_TYPE], reasons(issues))

    def test_unreadable_rows_are_issues_and_do_not_stop_the_others(self) -> None:
        rows = [
            "text",
            {"id": 0, "workout_type_family_id": CYCLING, "updated_at": "x"},
            {
                "id": 5,
                "workout_type_family_id": 9999,
                "updated_at": "2026-10-01T10:00:00Z",
            },
            {"id": 6, "workout_type_family_id": CYCLING, "updated_at": None},
            zone_row(7),
        ]

        chosen, issues = select_power_zone_sets(rows, zone=UTC)

        self.assertEqual(["7"], [item.record_id for item in chosen])
        self.assertEqual(
            [
                IssueReason.INVALID_TYPE,
                IssueReason.OUT_OF_RANGE,
                IssueReason.UNKNOWN_VALUE,
                IssueReason.MISSING,
            ],
            reasons(issues),
        )


class PowerZoneMappingTests(unittest.TestCase):
    def map(self, rows: object, zone: Any = UTC) -> Any:
        return map_wahoo_power_zones(rows, zone=zone, retrieved_at=RETRIEVED)

    def test_each_family_maps_to_its_ftp_in_watts_with_its_sport(self) -> None:
        result = self.map([zone_row(1, ftp=250), zone_row(2, family=RUNNING, ftp=300)])

        observations = {item.sport: item for item in result.records}
        self.assertEqual({Sport.RIDE, Sport.RUN}, set(observations))
        ride = observations[Sport.RIDE]
        self.assertIs(MetricKind.FTP, ride.kind)
        self.assertEqual(250, ride.value.value)
        self.assertEqual("W", ride.value.unit)
        self.assertEqual(300, observations[Sport.RUN].value.value)
        self.assertEqual((), result.issues)

    def test_provenance_names_wahoo_and_the_zone_set(self) -> None:
        (record,) = self.map([zone_row(42, ftp=250)]).records

        self.assertIs(ProviderId.WAHOO, record.provenance.provider)
        self.assertEqual("42", record.provenance.source_record_id)
        self.assertEqual(RETRIEVED, record.provenance.retrieved_at)

    def test_zero_ftp_means_not_set_and_is_not_an_issue(self) -> None:
        for value in (0, "0", 0.0):
            with self.subTest(value=value):
                result = self.map([zone_row(1, ftp=value)])

                self.assertEqual((), result.records)
                self.assertEqual((), result.issues)

    def test_a_missing_ftp_is_not_set(self) -> None:
        result = self.map(
            [
                {
                    "id": 1,
                    "workout_type_family_id": CYCLING,
                    "updated_at": "2026-10-01T10:00:00Z",
                }
            ]
        )

        self.assertEqual((), result.records)
        self.assertEqual((), result.issues)

    def test_out_of_bounds_ftp_is_an_issue_without_a_value(self) -> None:
        result = self.map([zone_row(1, ftp=5000)])

        self.assertEqual((), result.records)
        (issue,) = result.issues
        self.assertEqual("ftp", issue.field)
        self.assertEqual(IssueReason.OUT_OF_RANGE, issue.reason)
        self.assertNotIn("5000", repr(issue))

    def test_text_numbers_with_a_comma_decimal_mark_are_read(self) -> None:
        (record,) = self.map([zone_row(1, ftp="250,5")]).records

        self.assertEqual(250.5, record.value.value)

    def test_boolean_and_non_numeric_ftp_are_issues(self) -> None:
        # Same family and time would supersede the first row, so use two families.
        result = self.map(
            [zone_row(1, ftp=True), zone_row(2, family=RUNNING, ftp="abc")]
        )

        self.assertEqual((), result.records)
        self.assertEqual(
            [IssueReason.INVALID_TYPE, IssueReason.INVALID_NUMBER],
            reasons(result.issues),
        )

    def test_the_observed_day_is_the_athlete_local_day(self) -> None:
        rows = [zone_row(1, updated="2026-10-01T23:30:00Z")]

        (utc_record,) = self.map(rows, zone=UTC).records
        (local_record,) = self.map(rows, zone=CEST).records

        self.assertEqual(date(2026, 10, 1), utc_record.observed_on)
        self.assertEqual(date(2026, 10, 2), local_record.observed_on)

    def test_a_naive_retrieved_at_is_a_programming_error(self) -> None:
        with self.assertRaises(ValueError):
            map_wahoo_power_zones(
                [zone_row(1)],
                zone=UTC,
                retrieved_at=datetime(2026, 10, 12),  # noqa: DTZ001 - naive on purpose
            )


class UserMappingTests(unittest.TestCase):
    def test_weight_is_mapped_on_the_given_day_without_a_sport(self) -> None:
        result = map_wahoo_user(
            {"weight": 78.5}, observed_on=date(2026, 10, 12), retrieved_at=RETRIEVED
        )

        (record,) = result.records
        self.assertIs(MetricKind.WEIGHT, record.kind)
        self.assertEqual(78.5, record.value.value)
        self.assertEqual("kg", record.value.unit)
        self.assertIsNone(record.sport)
        self.assertEqual(date(2026, 10, 12), record.observed_on)
        self.assertEqual(USER_RECORD_ID, record.provenance.source_record_id)

    def test_a_text_weight_with_a_comma_is_read(self) -> None:
        result = map_wahoo_user(
            {"weight": "78,5"}, observed_on=date(2026, 10, 12), retrieved_at=RETRIEVED
        )

        self.assertEqual(78.5, result.records[0].value.value)

    def test_zero_or_missing_weight_is_not_set(self) -> None:
        for user in ({"weight": 0}, {"height": 180}):
            with self.subTest(user=user):
                result = map_wahoo_user(
                    user, observed_on=date(2026, 10, 12), retrieved_at=RETRIEVED
                )

                self.assertEqual((), result.records)
                self.assertEqual((), result.issues)

    def test_other_profile_fields_are_never_observations(self) -> None:
        user = {"height": 180, "birth_date": "1990-01-01", "gender": 1, "weight": 0}

        result = map_wahoo_user(
            user, observed_on=date(2026, 10, 12), retrieved_at=RETRIEVED
        )

        self.assertEqual((), result.records)

    def test_an_out_of_bounds_or_non_object_profile_is_an_issue(self) -> None:
        weight = map_wahoo_user(
            {"weight": 5000}, observed_on=date(2026, 10, 12), retrieved_at=RETRIEVED
        )
        profile = map_wahoo_user(
            "text", observed_on=date(2026, 10, 12), retrieved_at=RETRIEVED
        )

        self.assertEqual([IssueReason.OUT_OF_RANGE], reasons(weight.issues))
        self.assertEqual([IssueReason.INVALID_TYPE], reasons(profile.issues))


class PayloadMappingTests(unittest.TestCase):
    def test_a_fetch_that_was_not_made_maps_nothing(self) -> None:
        result = map_wahoo_threshold_payload(
            None, None, zone=UTC, retrieved_at=RETRIEVED
        )

        self.assertEqual((), result.records)
        self.assertEqual((), result.issues)

    def test_the_profile_is_dated_on_the_local_day_of_the_fetch(self) -> None:
        late = datetime(2026, 10, 12, 23, 30, tzinfo=UTC)

        result = map_wahoo_threshold_payload(
            None, {"weight": 80}, zone=CEST, retrieved_at=late
        )

        (record,) = result.records
        self.assertEqual(date(2026, 10, 13), record.observed_on)

    def test_the_module_version_is_one(self) -> None:
        self.assertEqual(1, MAPPER_VERSION)


class IngestAndReprojectionTests(unittest.TestCase):
    """Stored rows must re-map to exactly the observations the ingest wrote."""

    def payload(self) -> dict[str, Any]:
        return {
            "synced_at": RETRIEVED.isoformat(),
            "workouts": [],
            "power_zones": [
                zone_row(1, ftp=240, updated="2026-10-01T10:00:00Z"),
                zone_row(2, ftp=260, updated="2026-10-05T10:00:00Z"),
                zone_row(3, family=RUNNING, ftp=300),
            ],
            "user": {"weight": 78.5},
        }

    def test_only_the_chosen_zone_sets_and_the_profile_are_stored_raw(self) -> None:
        plan = plans.wahoo_ingest_plan(self.payload(), zone=UTC)

        raw = {
            (record.record_kind, record.source_record_id) for record in plan.raw_records
        }
        self.assertEqual(
            {
                ("power_zones", "2"),
                ("power_zones", "3"),
                ("user", USER_RECORD_ID),
            },
            raw,
        )
        observed = [
            (item.observation.kind, item.observation.value.value)
            for item in plan.observations
        ]
        self.assertCountEqual(
            [(MetricKind.FTP, 260), (MetricKind.FTP, 300), (MetricKind.WEIGHT, 78.5)],
            observed,
        )

    def test_a_stored_threshold_row_reprojects_to_its_ingested_observation(
        self,
    ) -> None:
        plan = plans.wahoo_ingest_plan(self.payload(), zone=UTC)
        ingested = {
            (item.observation.provenance.source_record_id, item.observation.kind): (
                item.observation
            )
            for item in plan.observations
        }

        for record in plan.raw_records:
            stored = {
                "provider": "wahoo",
                "record_kind": record.record_kind,
                "source_record_id": record.source_record_id,
                "payload": json.dumps(record.payload),
                "fetched_at": RETRIEVED.isoformat(),
            }
            with self.subTest(record=record.record_kind, id=record.source_record_id):
                reprojected = plans.reprojection_plan(stored, zone=UTC)

                assert reprojected is not None
                self.assertTrue(reprojected.observations)
                version = plans.reprojection_mapper_version("wahoo", record.record_kind)
                for item in reprojected.observations:
                    self.assertEqual(version, item.mapper_version)
                    key = (
                        item.observation.provenance.source_record_id,
                        item.observation.kind,
                    )
                    self.assertEqual(ingested[key], item.observation)

    def test_the_threshold_kinds_have_their_own_mapper_versions(self) -> None:
        self.assertEqual(1, plans.reprojection_mapper_version("wahoo", "power_zones"))
        self.assertEqual(1, plans.reprojection_mapper_version("wahoo", "user"))

    def test_a_threshold_row_without_a_fetch_time_is_not_reprojected(self) -> None:
        stored = {
            "provider": "wahoo",
            "record_kind": "user",
            "source_record_id": USER_RECORD_ID,
            "payload": json.dumps({"weight": 78.5}),
            "fetched_at": None,
        }

        plan = plans.reprojection_plan(stored, zone=UTC)

        assert plan is not None
        self.assertEqual((), plan.observations)


if __name__ == "__main__":
    unittest.main()
