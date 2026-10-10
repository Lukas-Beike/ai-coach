"""Characterize duplicate matching and calendar projection before refactoring.

The assertions pin the current behavior, quirks included, as the parity
reference for later provider-neutral refactors. Deliberately pinned quirks are
marked with a "Quirk:" comment.
"""

from __future__ import annotations

import copy
import unittest
from datetime import date
from typing import Any, ClassVar

from backend.activities.calendar_projection import (
    calendar_activity_identity,
    calendar_activity_payload,
    planning_compliance_state,
    training_calendar_items,
    workout_compliance,
)
from backend.activities.duplicates import (
    duplicate_delete_action,
    garmin_activity_duplicates_intervals,
    intervals_cycling_activities_match,
    latest_wahoo_garmin_duplicate,
    remove_activity_from_snapshot,
    validate_duplicate_delete,
)
from backend.activities.matching import match_planned_workouts
from backend.errors import AppError
from backend.planning.calendar_read_model import project_planning_calendar

TODAY = date(2026, 5, 4)
STALE_DUPLICATE_MESSAGE = (
    "Das Wahoo-/Garmin-Duplikat ist nicht mehr aktuell. "
    "Bitte die letzte Einheit erneut analysieren."
)


def _garmin(**overrides: Any) -> dict[str, Any]:
    activity: dict[str, Any] = {
        "activityId": "garmin-1",
        "activityType": "cycling",
        "startTimeLocal": "2026-05-04T07:05:00",
        "duration": 3600,
        "distance": 30_000,
    }
    activity.update(overrides)
    return activity


def _intervals(**overrides: Any) -> dict[str, Any]:
    activity: dict[str, Any] = {
        "id": "intervals-1",
        "type": "Ride",
        "start_date_local": "2026-05-04T07:00:00",
        "moving_time": 3600,
        "distance": 30_000,
    }
    activity.update(overrides)
    return activity


def _planned(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": "event-1",
        "category": "WORKOUT",
        "type": "Ride",
        "start_date_local": "2026-05-04T09:00:00",
        "moving_time": 3600,
        "name": "Endurance",
    }
    event.update(overrides)
    return event


def _activity(**overrides: Any) -> dict[str, Any]:
    activity: dict[str, Any] = {
        "id": "activity-1",
        "type": "Ride",
        "start_date_local": "2026-05-04T07:00:00",
        "moving_time": 3600,
        "distance": 30_000,
        "name": "Morning ride",
    }
    activity.update(overrides)
    return activity


def _unit(name: str, day: str, **overrides: Any) -> dict[str, Any]:
    unit: dict[str, Any] = {
        "id": f"unit-{name}",
        "date": day,
        "start_date_local": f"{day}T09:00:00",
        "name": name,
        "type": "Ride",
        "moving_time": 3600,
    }
    unit.update(overrides)
    return unit


class GarminDuplicateCharacterizationTests(unittest.TestCase):
    def test_other_sport_on_either_side_matches_any_known_sport(self) -> None:
        self.assertTrue(
            garmin_activity_duplicates_intervals(
                _garmin(activityType="Workout"), [_intervals(type="Run")]
            )
        )
        self.assertTrue(
            garmin_activity_duplicates_intervals(
                _garmin(activityType="running"), [_intervals(type="Workout")]
            )
        )
        self.assertTrue(
            garmin_activity_duplicates_intervals(
                _garmin(activityType="Workout"), [_intervals(type="Strength")]
            )
        )

    def test_known_sports_must_agree_and_unknown_sport_still_needs_measurements(
        self,
    ) -> None:
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(activityType="cycling"), [_intervals(type="Strength")]
            )
        )
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(activityType="Workout", duration=2_000),
                [_intervals(type="Run")],
            )
        )

    def test_duration_only_match_when_distance_is_missing(self) -> None:
        intervals = _intervals(distance=None)
        self.assertTrue(
            garmin_activity_duplicates_intervals(_garmin(distance=None), [intervals])
        )
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(distance=None, duration=3_000), [intervals]
            )
        )

    def test_distance_only_match_when_duration_is_missing(self) -> None:
        intervals = _intervals(moving_time=None)
        self.assertTrue(
            garmin_activity_duplicates_intervals(_garmin(duration=None), [intervals])
        )
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(duration=None, distance=20_000), [intervals]
            )
        )

    def test_no_comparable_measurement_is_never_a_duplicate(self) -> None:
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(duration=None, distance=None),
                [_intervals(moving_time=None, distance=None)],
            )
        )

    def test_zero_distance_is_skipped_rather_than_compared(self) -> None:
        # Quirk: a zero distance on either side removes the distance check
        # entirely, so a differing distance cannot reject the pair.
        self.assertTrue(
            garmin_activity_duplicates_intervals(
                _garmin(distance=0), [_intervals(distance=30_000)]
            )
        )

    def test_zero_duration_falls_back_to_moving_time_alias(self) -> None:
        # Quirk: `duration or movingTime` treats a zero duration as missing, so
        # the duration check is skipped and the distance alone decides.
        self.assertTrue(
            garmin_activity_duplicates_intervals(
                _garmin(duration=0, movingTime=None),
                [_intervals(moving_time=600)],
            )
        )
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(duration=0, movingTime=3_600),
                [_intervals(moving_time=600)],
            )
        )

    def test_start_window_is_inclusive_at_thirty_minutes_in_both_directions(
        self,
    ) -> None:
        # The Intervals start in _intervals() is 07:00:00, so 06:30 is the
        # earlier boundary and 07:30 the later one.
        self.assertTrue(
            garmin_activity_duplicates_intervals(
                _garmin(startTimeLocal="2026-05-04T06:30:00"), [_intervals()]
            )
        )
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(startTimeLocal="2026-05-04T06:29:59"), [_intervals()]
            )
        )
        self.assertTrue(
            garmin_activity_duplicates_intervals(
                _garmin(startTimeLocal="2026-05-04T07:30:00"), [_intervals()]
            )
        )
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(startTimeLocal="2026-05-04T07:30:01"), [_intervals()]
            )
        )

    def test_intervals_start_falls_back_to_start_date(self) -> None:
        intervals = _intervals(start_date_local=None, start_date="2026-05-04T07:00:00")
        self.assertTrue(garmin_activity_duplicates_intervals(_garmin(), [intervals]))

    def test_duration_tolerance_reference_is_the_intervals_side(self) -> None:
        # Quirk: the Garmin check takes 10% of the Intervals value only, so
        # swapping the two durations flips the outcome. The Intervals-to-Intervals
        # check uses the larger side and is symmetric.
        self.assertTrue(
            garmin_activity_duplicates_intervals(
                _garmin(duration=3_600), [_intervals(moving_time=4_000)]
            )
        )
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(duration=4_000), [_intervals(moving_time=3_600)]
            )
        )

    def test_duration_floor_is_two_minutes_for_short_activities(self) -> None:
        self.assertTrue(
            garmin_activity_duplicates_intervals(
                _garmin(duration=720), [_intervals(moving_time=600)]
            )
        )
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(duration=721), [_intervals(moving_time=600)]
            )
        )

    def test_distance_floor_is_500_meters_for_short_activities(self) -> None:
        self.assertTrue(
            garmin_activity_duplicates_intervals(
                _garmin(distance=1_500), [_intervals(distance=1_000)]
            )
        )
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(distance=1_501), [_intervals(distance=1_000)]
            )
        )


class IntervalsCyclingCharacterizationTests(unittest.TestCase):
    def test_duration_tolerance_uses_the_larger_side_and_is_symmetric(self) -> None:
        left = _intervals(moving_time=3_600)
        at_boundary = _intervals(id="right", moving_time=4_000)
        beyond = _intervals(id="right", moving_time=4_001)
        # The larger side is 4001, so the tolerance grows to 400.1 seconds.
        for first, second, expected in (
            (left, at_boundary, True),
            (at_boundary, left, True),
            (left, beyond, False),
            (beyond, left, False),
        ):
            with self.subTest(right=second["moving_time"], left=first["moving_time"]):
                self.assertEqual(
                    intervals_cycling_activities_match(first, second), expected
                )

    def test_distance_floor_is_500_meters_for_short_rides(self) -> None:
        short = _intervals(distance=1_000)
        self.assertTrue(
            intervals_cycling_activities_match(
                short, _intervals(id="right", distance=1_500)
            )
        )
        self.assertFalse(
            intervals_cycling_activities_match(
                short, _intervals(id="right", distance=1_501)
            )
        )

    def test_duration_floor_is_two_minutes_for_short_rides(self) -> None:
        short = _intervals(moving_time=600)
        self.assertTrue(
            intervals_cycling_activities_match(
                short, _intervals(id="right", moving_time=720)
            )
        )
        self.assertFalse(
            intervals_cycling_activities_match(
                short, _intervals(id="right", moving_time=721)
            )
        )

    def test_zero_moving_time_does_not_fall_back_to_elapsed_time(self) -> None:
        # Quirk: zero is a present value for the moving_time/elapsed_time
        # lookup, so elapsed_time is never consulted and the pair is rejected.
        zero_moving = _intervals(moving_time=0, elapsed_time=3_600)
        self.assertFalse(
            intervals_cycling_activities_match(zero_moving, _intervals(id="right"))
        )

    def test_start_window_is_inclusive_at_thirty_minutes(self) -> None:
        self.assertTrue(
            intervals_cycling_activities_match(
                _intervals(),
                _intervals(id="right", start_date_local="2026-05-04T07:30:00"),
            )
        )
        self.assertFalse(
            intervals_cycling_activities_match(
                _intervals(),
                _intervals(id="right", start_date_local="2026-05-04T07:30:01"),
            )
        )

    def test_non_dict_inputs_are_rejected(self) -> None:
        self.assertFalse(intervals_cycling_activities_match(None, _intervals()))
        self.assertFalse(intervals_cycling_activities_match(_intervals(), "ride"))


class WahooGarminPairCharacterizationTests(unittest.TestCase):
    def test_raw_activity_list_takes_precedence_over_recent_activities(self) -> None:
        snapshot = {
            "raw_provider_data": {
                "activities": [
                    _intervals(id="wahoo-a", source="Wahoo"),
                    _intervals(
                        id=None,
                        activityId="garmin-a",
                        source="Garmin",
                        start_date_local="2026-05-04T07:02:00",
                    ),
                ]
            },
            "recent_activities": [
                _intervals(id="wahoo-b", source="Wahoo"),
                _intervals(id=None, activityId="garmin-b", source="Garmin"),
            ],
        }
        pair = latest_wahoo_garmin_duplicate(snapshot)
        assert pair is not None
        self.assertEqual(pair["canonical_id"], "wahoo-a")
        self.assertEqual(pair["duplicate_id"], "garmin-a")

    def test_empty_raw_activity_list_does_not_fall_back_to_recent_activities(
        self,
    ) -> None:
        # Quirk: only a non-list raw value triggers the recent_activities
        # fallback, so an empty raw list hides a valid recent pair.
        snapshot = {
            "raw_provider_data": {"activities": []},
            "recent_activities": [
                _intervals(id="wahoo", source="Wahoo"),
                _intervals(id=None, activityId="garmin", source="Garmin"),
            ],
        }
        self.assertIsNone(latest_wahoo_garmin_duplicate(snapshot))

    def test_non_list_raw_activities_fall_back_to_recent_activities(self) -> None:
        snapshot = {
            "raw_provider_data": {"activities": "unavailable"},
            "recent_activities": [
                _intervals(id="wahoo", source="Wahoo"),
                _intervals(id=None, activityId="garmin", source="Garmin"),
            ],
        }
        pair = latest_wahoo_garmin_duplicate(snapshot)
        assert pair is not None
        self.assertEqual(pair["canonical_id"], "wahoo")

    def test_newest_pair_is_selected_by_canonical_start(self) -> None:
        # The newest activity is the Garmin copy, so both Wahoo rides pair with
        # it. The pair whose Wahoo canonical starts later wins.
        snapshot = {
            "raw_provider_data": {
                "activities": [
                    _intervals(
                        id="wahoo-early",
                        source="Wahoo",
                        start_date_local="2026-05-04T09:45:00",
                    ),
                    _intervals(
                        id="wahoo-late",
                        source="Wahoo",
                        start_date_local="2026-05-04T10:00:00",
                    ),
                    _intervals(
                        id=None,
                        activityId="garmin-latest",
                        source="Garmin",
                        start_date_local="2026-05-04T10:10:00",
                    ),
                ]
            }
        }
        pair = latest_wahoo_garmin_duplicate(snapshot)
        assert pair is not None
        self.assertEqual(pair["canonical_id"], "wahoo-late")
        self.assertEqual(pair["duplicate_id"], "garmin-latest")

    def test_device_provenance_reads_device_name_and_external_id(self) -> None:
        snapshot = {
            "raw_provider_data": {
                "activities": [
                    _intervals(id="wahoo", source=None, device_name="ELEMNT BOLT"),
                    _intervals(
                        id="garmin",
                        source=None,
                        external_id="garmin:42",
                        moving_time=3_560,
                        distance=29_800,
                    ),
                ]
            }
        }
        pair = latest_wahoo_garmin_duplicate(snapshot)
        assert pair is not None
        self.assertEqual(pair["canonical_id"], "wahoo")
        self.assertEqual(pair["duplicate_id"], "garmin")

    def test_wahoo_marker_wins_when_garmin_and_wahoo_markers_both_appear(self) -> None:
        # Quirk: "wahoo" is checked before "garmin" in the combined provenance
        # text, so this Garmin-sourced ride is classified as Wahoo and cannot
        # serve as the duplicate.
        snapshot = {
            "raw_provider_data": {
                "activities": [
                    _intervals(id="wahoo", source="Wahoo"),
                    _intervals(id="mixed", source="Garmin", device_name="Wahoo ELEMNT"),
                ]
            }
        }
        self.assertIsNone(latest_wahoo_garmin_duplicate(snapshot))

    def test_garmin_provenance_must_be_explicit(self) -> None:
        snapshot = {
            "raw_provider_data": {
                "activities": [
                    _intervals(id="wahoo", source="Wahoo"),
                    _intervals(id="unlabelled", source=None),
                ]
            }
        }
        self.assertIsNone(latest_wahoo_garmin_duplicate(snapshot))

    def test_missing_names_use_german_fallbacks_and_elapsed_time_backs_moving_time(
        self,
    ) -> None:
        snapshot = {
            "raw_provider_data": {
                "activities": [
                    _intervals(
                        id="wahoo",
                        source="Wahoo",
                        name=None,
                        moving_time=None,
                        elapsed_time=3_600,
                    ),
                    _intervals(
                        id=None, activityId="garmin", source="Garmin", name=None
                    ),
                ]
            }
        }
        pair = latest_wahoo_garmin_duplicate(snapshot)
        assert pair is not None
        self.assertEqual(pair["canonical_name"], "Wahoo-Radeinheit")
        self.assertEqual(pair["duplicate_name"], "Garmin-Radeinheit")
        self.assertEqual(pair["moving_time"], 3_600)
        self.assertEqual(pair["distance"], 30_000)


class DuplicateDeleteActionCharacterizationTests(unittest.TestCase):
    def test_action_shape_keeps_wahoo_and_names_the_garmin_copy(self) -> None:
        action = duplicate_delete_action(
            {
                "canonical_id": "wahoo",
                "duplicate_id": "garmin",
                "duplicate_name": "Garmin ride",
                "start_date_local": "2026-05-04T07:00:00",
                "snapshot_synced_at": "2026-05-04T08:00:00+00:00",
            }
        )
        self.assertEqual(action["action_type"], "delete_duplicate_intervals_activity")
        self.assertEqual(
            action["object_ids"],
            {"keep_activity_id": "wahoo", "delete_activity_id": "garmin"},
        )
        self.assertEqual(
            action["diff"],
            [
                {
                    "type": "delete",
                    "id": "garmin",
                    "name": "Garmin ride",
                    "date": "2026-05-04",
                    "source": "Garmin",
                    "kept_source": "Wahoo",
                }
            ],
        )
        self.assertEqual(
            action["payload"],
            {
                "canonical_id": "wahoo",
                "duplicate_id": "garmin",
                "snapshot_synced_at": "2026-05-04T08:00:00+00:00",
            },
        )

    def test_missing_start_produces_an_empty_diff_date(self) -> None:
        action = duplicate_delete_action(
            {"canonical_id": "wahoo", "duplicate_id": "garmin", "duplicate_name": "G"}
        )
        self.assertEqual(action["diff"][0]["date"], "")
        self.assertIsNone(action["payload"]["snapshot_synced_at"])


class SnapshotRemovalCharacterizationTests(unittest.TestCase):
    def test_removes_exact_id_matches_from_both_lists_and_stamps_synced_at(
        self,
    ) -> None:
        snapshot = {
            "synced_at": "old",
            "recent_activities": [
                {"id": 9, "name": "int id"},
                {"activityId": "9", "name": "alias"},
                {"id": "10", "name": "keep"},
            ],
            "raw_provider_data": {
                "source": "intervals",
                "activities": [{"id": "9"}, {"id": "11"}],
            },
        }

        updated = remove_activity_from_snapshot(snapshot, "9", synced_at="new")
        assert updated is not None

        self.assertEqual(updated["recent_activities"], [{"id": "10", "name": "keep"}])
        self.assertEqual(
            updated["raw_provider_data"],
            {"source": "intervals", "activities": [{"id": "11"}]},
        )
        self.assertEqual(updated["synced_at"], "new")

    def test_id_match_is_exact_and_keeps_unidentified_and_scalar_entries(self) -> None:
        scalar = "provider marker"
        unidentified = {"name": "no id"}
        snapshot = {
            "recent_activities": [
                {"id": " 9"},
                {"id": "9 "},
                {"id": "09"},
                scalar,
                unidentified,
            ]
        }

        updated = remove_activity_from_snapshot(snapshot, "9", synced_at=None)
        assert updated is not None

        self.assertEqual(
            updated["recent_activities"],
            [{"id": " 9"}, {"id": "9 "}, {"id": "09"}, scalar, unidentified],
        )

    def test_empty_activity_id_removes_every_unidentified_row(self) -> None:
        # Quirk: an empty ID compares equal to the empty identity of rows that
        # have no id. The duplicate service never passes an empty ID because
        # latest_wahoo_garmin_duplicate requires a non-empty duplicate_id.
        snapshot = {
            "recent_activities": [{"name": "no id"}, {"id": "keep"}, "scalar"],
        }

        updated = remove_activity_from_snapshot(snapshot, "", synced_at=None)
        assert updated is not None

        self.assertEqual(updated["recent_activities"], [{"id": "keep"}, "scalar"])

    def test_missing_raw_activities_are_materialized_as_an_empty_list(self) -> None:
        # Quirk: a raw_provider_data dict without an activities key gains an
        # empty activities list after any removal.
        snapshot = {"raw_provider_data": {"source": "intervals"}}

        updated = remove_activity_from_snapshot(snapshot, "9", synced_at=None)
        assert updated is not None

        self.assertEqual(
            updated["raw_provider_data"], {"source": "intervals", "activities": []}
        )

    def test_non_list_collections_become_empty_and_non_dict_raw_is_untouched(
        self,
    ) -> None:
        snapshot = {"recent_activities": "unavailable", "raw_provider_data": "raw"}

        updated = remove_activity_from_snapshot(snapshot, "9", synced_at=None)
        assert updated is not None

        self.assertEqual(updated["recent_activities"], [])
        self.assertEqual(updated["raw_provider_data"], "raw")

    def test_non_dict_snapshot_returns_none(self) -> None:
        self.assertIsNone(remove_activity_from_snapshot(None, "9", synced_at=None))
        self.assertIsNone(remove_activity_from_snapshot([], "9", synced_at=None))

    def test_input_snapshot_is_not_mutated(self) -> None:
        snapshot = {
            "synced_at": "old",
            "recent_activities": [{"id": "9"}, {"id": "10"}],
            "raw_provider_data": {"activities": [{"id": "9"}]},
        }
        original = copy.deepcopy(snapshot)

        remove_activity_from_snapshot(snapshot, "9", synced_at="new")

        self.assertEqual(snapshot, original)


class DeleteConfirmationCharacterizationTests(unittest.TestCase):
    _CURRENT: ClassVar[dict[str, Any]] = {
        "canonical_id": "wahoo-1",
        "duplicate_id": "garmin-1",
        "snapshot_synced_at": "2026-05-04T08:00:00+00:00",
        "duplicate_name": "Garmin ride",
    }

    def _payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "canonical_id": "wahoo-1",
            "duplicate_id": "garmin-1",
            "snapshot_synced_at": "2026-05-04T08:00:00+00:00",
        }
        payload.update(overrides)
        return payload

    def test_matching_confirmation_returns_canonical_and_duplicate_ids(self) -> None:
        self.assertEqual(
            validate_duplicate_delete(self._payload(extra="ignored"), self._CURRENT),
            ("wahoo-1", "garmin-1"),
        )

    def test_non_dict_or_empty_inputs_fail_closed_with_409(self) -> None:
        for payload, current in (
            (None, self._CURRENT),
            ("wahoo-1", self._CURRENT),
            (["wahoo-1"], self._CURRENT),
            (self._payload(), None),
            (self._payload(), {}),
            (self._payload(), ["wahoo-1"]),
        ):
            with self.subTest(payload=payload, current=current):
                with self.assertRaises(AppError) as context:
                    validate_duplicate_delete(payload, current)
                self.assertEqual(context.exception.status, 409)
                self.assertEqual(context.exception.message, STALE_DUPLICATE_MESSAGE)

    def test_any_changed_identity_or_snapshot_stamp_fails_closed(self) -> None:
        for key, value in (
            ("canonical_id", "wahoo-2"),
            ("duplicate_id", "garmin-2"),
            ("snapshot_synced_at", "2026-05-04T09:00:00+00:00"),
        ):
            with self.subTest(key=key):
                with self.assertRaises(AppError) as context:
                    validate_duplicate_delete(
                        self._payload(**{key: value}), self._CURRENT
                    )
                self.assertEqual(context.exception.status, 409)

    def test_missing_payload_field_fails_when_current_has_a_value(self) -> None:
        payload = self._payload()
        del payload["duplicate_id"]
        with self.assertRaises(AppError):
            validate_duplicate_delete(payload, self._CURRENT)

    def test_missing_field_equals_null_field_after_string_coercion(self) -> None:
        # Known defect, pinned as current behavior: values are compared as
        # str(value or ""), so a missing key and a null value are equal, and 1
        # matches "1". A fail-closed fix must update this test deliberately.
        current = {**self._CURRENT, "snapshot_synced_at": None}
        payload = self._payload()
        del payload["snapshot_synced_at"]
        self.assertEqual(
            validate_duplicate_delete(payload, current),
            ("wahoo-1", "garmin-1"),
        )
        numeric = {**self._CURRENT, "snapshot_synced_at": "1"}
        self.assertEqual(
            validate_duplicate_delete(self._payload(snapshot_synced_at=1), numeric),
            ("wahoo-1", "garmin-1"),
        )


class MatchingPrecedenceCharacterizationTests(unittest.TestCase):
    def test_paired_activity_ignores_sport_and_calendar_day(self) -> None:
        # Quirk: paired_event_id is trusted without a sport or date check.
        planned = [_planned(id="event", type="Ride", start_date_local="2026-05-04")]
        paired = _activity(
            id="paired",
            paired_event_id="event",
            type="Run",
            start_date_local="2026-05-06T07:00:00",
        )
        self.assertEqual(match_planned_workouts(planned, [paired]), {0: paired})

    def test_unknown_sport_units_match_only_through_paired_id(self) -> None:
        # Quirk: a unit with an unknown sport never gets a fallback candidate,
        # even when an unpaired same-day activity is also unknown-sport.
        unit = {
            "category": "WORKOUT",
            "type": "Workout",
            "date": "2026-05-04",
            "moving_time": 3600,
        }
        unpaired = {
            "id": "unpaired",
            "type": "Workout",
            "start_date_local": "2026-05-04T07:00:00",
        }
        self.assertEqual(match_planned_workouts([unit], [unpaired]), {})

        paired_unknown = {**unpaired, "id": "paired", "paired_event_id": "unit-id"}
        matched = match_planned_workouts([{**unit, "id": "unit-id"}], [paired_unknown])
        self.assertEqual(matched, {0: paired_unknown})

    def test_midnight_units_are_date_only_and_other_starts_are_timed(self) -> None:
        # Two same-day rides: "early" is closest in start time but its duration
        # is a worse fit. Date-only units use best-fit (duration), timed units use
        # nearest start.
        activities = [
            _activity(
                id="early",
                start_date_local="2026-05-04T09:00:00",
                moving_time=1_800,
            ),
            _activity(
                id="late",
                start_date_local="2026-05-04T14:00:00",
                moving_time=3_600,
            ),
        ]
        expectations = (
            ("2026-05-04", "late"),
            ("2026-05-04 00:00", "late"),
            ("2026-05-04T00:00:00.000", "late"),
            ("2026-05-04T00:00:01", "early"),
            ("2026-05-04T09:00:00", "early"),
        )
        for start, expected_id in expectations:
            with self.subTest(start=start):
                unit = {
                    "category": "WORKOUT",
                    "type": "Ride",
                    "start_date_local": start,
                    "moving_time": 3_600,
                }
                matches = match_planned_workouts([unit], activities)
                self.assertEqual(matches[0]["id"], expected_id)

    def test_offset_aware_activity_start_is_compared_by_its_utc_day(self) -> None:
        # Known defect, pinned as current behavior: an activity at 01:00 on
        # 2026-05-04 with a +02:00 offset is attributed to 2026-05-03 because day
        # matching uses the UTC date.
        unit = {"category": "WORKOUT", "type": "Ride", "date": "2026-05-04"}
        shifted = _activity(start_date_local="2026-05-04T01:00:00+02:00")
        local = _activity(id="local", start_date_local="2026-05-04T01:00:00")
        self.assertEqual(match_planned_workouts([unit], [shifted]), {})
        self.assertEqual(match_planned_workouts([unit], [local]), {0: local})


class CalendarIdentityCharacterizationTests(unittest.TestCase):
    def test_fallback_identity_prefers_type_over_sport_and_drops_negative_metrics(
        self,
    ) -> None:
        identity = calendar_activity_identity(
            {
                "start_date_local": "2026-05-04T07:00:00",
                "type": "Ride",
                "sport": "Run",
                "moving_time": -1,
                "distance": "12.5",
            }
        )
        self.assertEqual(
            identity,
            ("fallback", "2026-05-04T07:00:00", "ride", None, 12.5),
        )

    def test_fallback_identity_is_case_insensitive_and_start_field_order_is_fixed(
        self,
    ) -> None:
        upper = calendar_activity_identity(
            {"start_date": "2026-05-04T07:00:00", "date": "2026-05-01", "type": "RIDE"}
        )
        assert upper is not None
        lower = calendar_activity_identity(
            {"start_date": "2026-05-04T07:00:00", "type": "ride"}
        )
        self.assertEqual(upper, lower)
        self.assertEqual(upper[1], "2026-05-04T07:00:00")

    def test_empty_id_is_skipped_and_activity_id_alias_is_used(self) -> None:
        self.assertEqual(
            calendar_activity_identity({"id": "", "activityId": "provider-7"}),
            ("id", "provider-7", "", "", ""),
        )


class CompliancePlanningCharacterizationTests(unittest.TestCase):
    def test_status_is_missed_only_for_past_units_without_an_activity(self) -> None:
        past = _planned(start_date_local="2026-05-03T09:00:00")
        today = _planned(start_date_local="2026-05-04T09:00:00")
        future = _planned(start_date_local="2026-05-05T09:00:00")

        self.assertEqual(workout_compliance(past, None, TODAY)["status"], "missed")
        self.assertEqual(workout_compliance(today, None, TODAY)["status"], "planned")
        self.assertEqual(workout_compliance(future, None, TODAY)["status"], "planned")
        self.assertEqual(
            workout_compliance(past, _activity(), TODAY)["status"], "completed"
        )

    def test_missed_unit_scores_zero_and_has_no_basis(self) -> None:
        result = workout_compliance(
            _planned(start_date_local="2026-05-03T09:00:00"), None, TODAY
        )
        self.assertEqual(result["percentage"], 0)
        self.assertIsNone(result["basis"])
        self.assertIsNone(result["planned_value"])

    def test_zero_planned_load_is_neither_unavailable_nor_scored(self) -> None:
        # Quirk: a planned load of 0 is not "unavailable" (that needs both planned
        # load and planned duration to be missing), and it is not a valid basis.
        result = workout_compliance(
            _planned(icu_training_load=0, moving_time=None),
            _activity(icu_training_load=40),
            TODAY,
        )
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(result["basis"])
        self.assertIsNone(result["percentage"])

    def test_load_basis_falls_back_to_duration_when_actual_load_is_missing(
        self,
    ) -> None:
        result = workout_compliance(
            _planned(icu_training_load=50, moving_time=3_600),
            _activity(moving_time=1_800),
            TODAY,
        )
        self.assertEqual((result["basis"], result["percentage"]), ("duration", 50))

    def test_undated_unit_is_reported_missed_and_left_out_of_weeks(self) -> None:
        # Quirk: an undated unit has an empty date, which sorts before today's
        # ISO string, so it is reported as missed. It cannot be placed in a week.
        enriched, weekly = planning_compliance_state(
            [{"category": "WORKOUT", "type": "Ride", "moving_time": 3_600}],
            [],
            TODAY,
        )
        self.assertEqual(enriched[0]["compliance"]["status"], "missed")
        self.assertEqual(weekly, [])

    def test_non_workout_entries_pass_through_without_compliance(self) -> None:
        race = {"id": "race", "category": "RACE_A", "date": "2026-05-09"}
        enriched, weekly = planning_compliance_state([race], [], TODAY)
        self.assertEqual(enriched, [race])
        self.assertEqual(weekly, [])

    def test_weekly_rows_start_on_monday_and_sunday_belongs_to_previous_week(
        self,
    ) -> None:
        planned = [
            _planned(id="sunday", start_date_local="2026-05-03T09:00:00"),
            _planned(id="monday", start_date_local="2026-05-04T09:00:00"),
            _planned(id="next-sunday", start_date_local="2026-05-10T09:00:00"),
        ]
        _enriched, weekly = planning_compliance_state(planned, [], TODAY)
        self.assertEqual(
            [
                (row["week_start"], row["week_end"], row["planned_units"])
                for row in weekly
            ],
            [("2026-04-27", "2026-05-03", 1), ("2026-05-04", "2026-05-10", 2)],
        )

    def test_weekly_totals_count_missed_units_as_zero_actual(self) -> None:
        planned = [
            _planned(
                id="done",
                start_date_local="2026-04-27T09:00:00",
                icu_training_load=50,
            ),
            _planned(
                id="missed",
                start_date_local="2026-05-03T09:00:00",
                icu_training_load=50,
            ),
        ]
        activities = [
            _activity(
                id="done-activity",
                paired_event_id="done",
                start_date_local="2026-04-27T09:00:00",
                icu_training_load=40,
            )
        ]
        _enriched, weekly = planning_compliance_state(planned, activities, TODAY)
        self.assertEqual(len(weekly), 1)
        row = weekly[0]
        self.assertEqual(
            (
                row["basis"],
                row["planned_value"],
                row["actual_value"],
                row["percentage"],
            ),
            ("training_load", 100.0, 40.0, 40),
        )
        self.assertEqual(
            (row["planned_units"], row["completed_units"], row["unit_percentage"]),
            (2, 1, 50),
        )

    def test_weekly_basis_falls_back_to_duration_when_any_unit_lacks_load(self) -> None:
        planned = [
            _planned(
                id="with-load",
                start_date_local="2026-04-28T09:00:00",
                moving_time=3_600,
                icu_training_load=50,
            ),
            _planned(
                id="duration-only",
                start_date_local="2026-04-29T09:00:00",
                moving_time=1_800,
            ),
        ]
        activities = [
            _activity(
                id="done",
                paired_event_id="with-load",
                start_date_local="2026-04-28T09:00:00",
                moving_time=3_000,
                icu_training_load=40,
            )
        ]
        _enriched, weekly = planning_compliance_state(planned, activities, TODAY)
        self.assertEqual(weekly[0]["basis"], "duration")
        self.assertEqual(weekly[0]["planned_value"], 5_400.0)
        self.assertEqual(weekly[0]["actual_value"], 3_000.0)
        self.assertEqual(weekly[0]["percentage"], 56)

    def test_weekly_score_is_none_without_a_shared_basis(self) -> None:
        planned = [
            _planned(
                id="bare", start_date_local="2026-04-28T09:00:00", moving_time=None
            )
        ]
        activities = [
            _activity(
                id="done",
                paired_event_id="bare",
                start_date_local="2026-04-28T09:00:00",
            )
        ]
        _enriched, weekly = planning_compliance_state(planned, activities, TODAY)
        self.assertIsNone(weekly[0]["basis"])
        self.assertIsNone(weekly[0]["percentage"])
        self.assertIsNone(weekly[0]["planned_value"])


class TrainingCalendarCharacterizationTests(unittest.TestCase):
    def test_fallback_identity_hides_a_matched_activity_without_an_id(self) -> None:
        activity = {
            "start_date_local": "2026-05-04T07:00:00",
            "type": "Ride",
            "moving_time": 3_600,
            "distance": 30_000,
        }
        planned = [
            {
                "id": "event",
                "start_date_local": "2026-05-04T09:00:00",
                "compliance": {"actual_activity": calendar_activity_payload(activity)},
            }
        ]
        rows = training_calendar_items(planned, [activity])
        self.assertEqual([row["id"] for row in rows], ["event"])

    def test_completed_activity_without_a_start_is_omitted(self) -> None:
        self.assertEqual(training_calendar_items([], [{"id": "a", "type": "Ride"}]), [])

    def test_sport_only_activity_is_listed_twice_after_matching(self) -> None:
        # Quirk: the matched copy is projected through calendar_activity_payload,
        # which keeps "type" but not "sport". Its fallback identity therefore
        # differs from the raw activity and the activity is not de-duplicated.
        activity = {
            "start_date_local": "2026-05-04T07:00:00",
            "sport": "Ride",
            "moving_time": 3_600,
            "distance": 30_000,
        }
        enriched, _weekly = planning_compliance_state(
            [_planned(id="event", start_date_local="2026-05-04")], [activity], TODAY
        )
        rows = training_calendar_items(enriched, [activity])
        self.assertEqual([row["id"] for row in rows if "id" in row], ["event"])
        self.assertEqual(len(rows), 2)

    def test_activity_id_alias_is_listed_twice_after_matching(self) -> None:
        # Quirk: calendar_activity_payload keeps "id" and "external_id" but not
        # "activityId", so an activityId-only record loses its stable identity
        # when it is matched and is listed a second time.
        activity = {
            "activityId": "provider-1",
            "start_date_local": "2026-05-04T07:00:00",
            "type": "Ride",
            "moving_time": 3_600,
            "distance": 30_000,
        }
        enriched, _weekly = planning_compliance_state(
            [_planned(id="event", start_date_local="2026-05-04")], [activity], TODAY
        )
        rows = training_calendar_items(enriched, [activity])
        self.assertEqual(len(rows), 2)

    def test_rows_sort_by_start_then_casefolded_name_then_id(self) -> None:
        planned = [
            {"id": "p", "name": "Zeta", "start_date_local": "2026-05-04T09:00:00"}
        ]
        activities = [
            {
                "id": "a-9",
                "name": "alpha",
                "start_date_local": "2026-05-04T09:00:00",
                "type": "Run",
            },
            {
                "id": "a-1",
                "name": "Beta",
                "start_date_local": "2026-05-04T08:00:00",
                "type": "Run",
            },
        ]
        rows = training_calendar_items(planned, activities)
        self.assertEqual([row["name"] for row in rows], ["Beta", "alpha", "Zeta"])

    def test_identical_start_and_name_tie_breaks_by_id(self) -> None:
        activities = [
            {
                "id": "a-2",
                "name": "Same",
                "start_date_local": "2026-05-04T09:00:00",
                "type": "Run",
            },
            {
                "id": "a-1",
                "name": "same",
                "start_date_local": "2026-05-04T09:00:00",
                "type": "Run",
            },
        ]
        rows = training_calendar_items([], activities)
        self.assertEqual([row["id"] for row in rows], ["a-1", "a-2"])


class PlanningCalendarProjectionCharacterizationTests(unittest.TestCase):
    def test_projection_is_local_only_and_never_adds_provider_calendar_rows(
        self,
    ) -> None:
        # Only local planned rows and provider activities are projected. Remote
        # calendar events are never passed in, so remote_count stays 0 and a
        # remote_event_id on a local row does not mark it as linked.
        unit = _unit(
            "Endurance",
            "2026-05-04",
            remote_event_id="intervals-event-9",
        )
        activity = _activity(id="a-1")

        result = project_planning_calendar(
            [unit],
            [activity],
            {},
            [],
            [],
            today=TODAY,
            provider_window={},
            default_name="Planned workout",
        )

        self.assertEqual(result["planning_view"]["source"], "local")
        self.assertEqual(result["planning_view"]["local_count"], 1)
        self.assertEqual(result["planning_view"]["remote_count"], 0)
        self.assertEqual(len(result["planned"]), 1)
        planned = result["planned"][0]
        self.assertTrue(planned["is_local"])
        self.assertFalse(planned["is_remote"])
        self.assertEqual(planned["sync_source"], "local")
        self.assertEqual(planned["compliance"]["status"], "completed")
        self.assertEqual(
            [row.get("id") for row in result["training_calendar"]],
            [planned["id"]],
        )
        calendar_ids = [item.get("id") for item in result["calendar"]]
        self.assertIn(planned["id"], calendar_ids)
        self.assertEqual(
            [item for item in result["calendar"] if not item.get("is_local")],
            [],
        )


if __name__ == "__main__":
    unittest.main()
