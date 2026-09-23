from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime

from backend.activities.identity import (
    activity_datetime,
    activity_kind,
    intervals_activity_device_source,
)


class ActivityDatetimeTests(unittest.TestCase):
    def test_falsy_and_invalid_values_return_none(self) -> None:
        for value in (None, "", 0, False, "not-a-date", object()):
            with self.subTest(value=type(value).__name__):
                self.assertIsNone(activity_datetime(value))

    def test_utc_suffix_is_normalized_to_naive_utc(self) -> None:
        self.assertEqual(
            activity_datetime("2026-09-20T12:34:56Z"),
            datetime.fromisoformat("2026-09-20T12:34:56"),
        )

    def test_aware_values_are_converted_to_utc_and_naive_values_remain_naive(
        self,
    ) -> None:
        self.assertEqual(
            activity_datetime("2026-09-20T14:34:56+02:00"),
            datetime.fromisoformat("2026-09-20T12:34:56"),
        )
        parsed = activity_datetime("2026-09-20T12:34:56")
        self.assertEqual(parsed, datetime.fromisoformat("2026-09-20T12:34:56"))
        self.assertIsNotNone(parsed)
        self.assertIsNone(parsed.tzinfo)


class ActivityKindTests(unittest.TestCase):
    def test_non_dict_and_unknown_values_are_other(self) -> None:
        self.assertEqual(activity_kind(None), "other")
        self.assertEqual(activity_kind("cycling"), "other")
        self.assertEqual(activity_kind({"name": "hiking"}), "other")

    def test_fields_are_casefolded_and_priority_is_preserved(self) -> None:
        cases = (
            ({"type": "STRENGTH RIDE"}, "cycling"),
            ({"sport": "Lauf und Ride"}, "cycling"),
            ({"sport_type": "SCHWIMMEN"}, "swimming"),
            ({"activityType": "JOG"}, "running"),
            ({"activityName": "KRAFTTRAINING"}, "strength"),
            ({"name": "gym"}, "strength"),
        )
        for activity, expected in cases:
            with self.subTest(activity=activity):
                self.assertEqual(activity_kind(activity), expected)


class ActivityDeviceSourceTests(unittest.TestCase):
    def test_explicit_provenance_and_wahoo_priority(self) -> None:
        self.assertIsNone(intervals_activity_device_source(None))
        self.assertEqual(
            intervals_activity_device_source({"source": "GARMIN"}), "garmin"
        )
        self.assertEqual(
            intervals_activity_device_source({"device_name": "Wahoo ELEMNT"}),
            "wahoo",
        )
        self.assertEqual(
            intervals_activity_device_source(
                {"source": "Garmin", "external_id": "wahoo-123"}
            ),
            "wahoo",
        )
        self.assertIsNone(
            intervals_activity_device_source({"name": "Wahoo", "device": "Garmin"})
        )


class ActivityInputImmutabilityTests(unittest.TestCase):
    def test_identity_helpers_do_not_mutate_input(self) -> None:
        activity = {
            "type": "Ride",
            "sport": "Cycling",
            "source": "Garmin",
            "device_name": "Wahoo ELEMNT",
            "nested": {"keep": True},
        }
        original = deepcopy(activity)
        activity_kind(activity)
        intervals_activity_device_source(activity)
        self.assertEqual(activity, original)


if __name__ == "__main__":
    unittest.main()
