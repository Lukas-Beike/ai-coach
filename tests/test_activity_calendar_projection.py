import copy
import unittest
from datetime import date, timedelta

from backend.activities.calendar_projection import (
    CALENDAR_ACTIVITY_FIELDS,
    activity_metric,
    calendar_activity_identity,
    calendar_activity_payload,
    planning_compliance_state,
    training_calendar_items,
    workout_compliance,
)


class ActivityMetricTests(unittest.TestCase):
    def test_numeric_variants_and_nonnegative_contract(self):
        self.assertEqual(activity_metric({"value": "12,50"}, ("value",)), 12.5)
        self.assertEqual(activity_metric({"value": 12.0}, ("value",)), 12)
        self.assertEqual(activity_metric({"value": "0"}, ("value",)), 0)
        self.assertIsNone(activity_metric({"value": -1}, ("value",)))
        self.assertIsNone(activity_metric({"value": float("nan")}, ("value",)))
        self.assertIsNone(activity_metric({"value": float("inf")}, ("value",)))
        self.assertEqual(activity_metric({"fallback": 7}, ("missing", "fallback")), 7)


class CalendarActivityPayloadTests(unittest.TestCase):
    def test_allowlist_dates_and_completed_activity_markers(self):
        activity = {
            "id": "activity-1",
            "started_at_local": "2026-09-07T06:30:00+02:00",
            "name": "Morning Ride",
            "sport": "ride",
            "moving_duration_s": 3600,
            "distance_m": 30_000,
            "source": "Garmin",
            "private_note": "must not leak",
            "raw_payload": {"secret": True},
        }

        result = calendar_activity_payload(activity)

        self.assertEqual(result["date"], "2026-09-07")
        self.assertEqual(result["started_at_local"], activity["started_at_local"])
        self.assertEqual(result["category"], "ACTIVITY")
        self.assertEqual(result["calendar_entry_type"], "completed_activity")
        self.assertTrue(result["is_completed_activity"])
        self.assertNotIn("private_note", result)
        self.assertNotIn("raw_payload", result)
        self.assertEqual(
            set(result)
            - {"date", "category", "calendar_entry_type", "is_completed_activity"},
            {key for key in CALENDAR_ACTIVITY_FIELDS if key in activity},
        )

    def test_date_and_start_fallbacks_and_malformed_values(self):
        self.assertEqual(
            calendar_activity_payload({"date": "2026-09-07T10:00:00Z"})["date"],
            "2026-09-07",
        )
        self.assertEqual(
            calendar_activity_payload({"started_at_local": "not-a-date"})["date"],
            "not-a-date",
        )
        self.assertEqual(calendar_activity_payload({})["date"], "")
        self.assertEqual(calendar_activity_payload(None), {})


class CalendarActivityIdentityTests(unittest.TestCase):
    def test_session_id_is_the_identity(self):
        self.assertEqual(
            calendar_activity_identity({"id": 0, "external_id": "external-1"}),
            ("id", "0", "", "", ""),
        )
        self.assertEqual(
            calendar_activity_identity({"id": "act_1", "started_at_local": "x"}),
            ("id", "act_1", "", "", ""),
        )

    def test_fallback_identity_and_missing_start(self):
        activity = {
            "started_at_local": "2026-09-07T10:00:00",
            "sport": "RUN",
            "elapsed_duration_s": "1800",
            "distance_m": "5.5",
        }
        self.assertEqual(
            calendar_activity_identity(activity),
            ("fallback", "2026-09-07T10:00:00", "run", 1800, 5.5),
        )
        self.assertIsNone(calendar_activity_identity({"sport": "run"}))
        self.assertIsNone(calendar_activity_identity("not-an-activity"))

    def test_identity_and_payload_do_not_mutate_input(self):
        activity = {
            "date": "2026-09-07",
            "sport": "ride",
            "moving_duration_s": "3600",
            "distance_m": 20_000,
            "extra": {"keep": True},
        }
        original = copy.deepcopy(activity)

        calendar_activity_payload(activity)
        calendar_activity_identity(activity)

        self.assertEqual(activity, original)


class PlanningComplianceTests(unittest.TestCase):
    def test_paired_match_rolls_up_weekly_training_load(self):
        today = date(2026, 8, 26)
        events = [
            {
                "id": "done",
                "category": "WORKOUT",
                "type": "Ride",
                "starts_at_local": today.isoformat(),
                "planned_duration_s": 3600,
                "icu_training_load": 50,
            },
            {
                "id": "missed",
                "category": "WORKOUT",
                "type": "Ride",
                "starts_at_local": (today - timedelta(days=1)).isoformat(),
                "planned_duration_s": 3600,
                "icu_training_load": 50,
            },
        ]
        activities = [
            {
                "id": "activity",
                "planned_event_id": "done",
                "sport": "ride",
                "started_at_local": f"{today.isoformat()}T07:00:00",
                "moving_duration_s": 3300,
                "training_load": 40,
                "private_note": "hidden",
            }
        ]

        enriched, weekly = planning_compliance_state(events, activities, today)

        self.assertEqual(enriched[0]["compliance"]["percentage"], 80)
        self.assertNotIn("private_note", enriched[0]["compliance"]["actual_activity"])
        self.assertEqual(enriched[1]["compliance"]["percentage"], 0)
        self.assertEqual(sum(row["planned_units"] for row in weekly), 2)

    def test_duration_and_unavailable_fallbacks(self):
        today = date(2026, 9, 12)
        activity = {
            "id": "done",
            "started_at_local": today.isoformat(),
            "moving_duration_s": 2700,
        }

        duration = workout_compliance(
            {"starts_at_local": today.isoformat(), "planned_duration_s": 3600},
            activity,
            today,
        )
        unavailable = workout_compliance(
            {"starts_at_local": today.isoformat()}, activity, today
        )

        self.assertEqual((duration["basis"], duration["percentage"]), ("duration", 75))
        self.assertEqual(
            (unavailable["basis"], unavailable["percentage"]),
            ("unavailable", 100),
        )

    def test_calendar_keeps_unmatched_activity_without_repeating_match(self):
        planned = [
            {
                "id": "event",
                "starts_at_local": "2026-08-26",
                "compliance": {
                    "actual_activity": calendar_activity_payload(
                        {
                            "id": "matched",
                            "sport": "ride",
                            "started_at_local": "2026-08-26T07:00:00",
                        }
                    )
                },
            }
        ]
        activities = [
            {
                "id": "matched",
                "sport": "ride",
                "started_at_local": "2026-08-26T07:00:00",
            },
            {
                "id": "extra",
                "sport": "run",
                "started_at_local": "2026-08-26T18:00:00",
            },
        ]

        calendar = training_calendar_items(planned, activities)

        self.assertEqual([row["id"] for row in calendar], ["event", "extra"])

    def test_completed_walk_is_one_row_with_its_planned_walk(self):
        today = date(2026, 9, 12)
        events = [
            {
                "id": "planned-walk",
                "category": "WORKOUT",
                "type": "Walk",
                "starts_at_local": today.isoformat(),
                "planned_duration_s": 3600,
            }
        ]
        activities = [
            {
                "id": "walk",
                "sport": "walk",
                "started_at_local": f"{today.isoformat()}T07:00:00",
                "moving_duration_s": 3300,
            }
        ]

        enriched, _weekly = planning_compliance_state(events, activities, today)
        calendar = training_calendar_items(enriched, activities)

        self.assertEqual([row["id"] for row in calendar], ["planned-walk"])
        self.assertEqual(
            calendar[0]["compliance"]["actual_activity"]["id"],
            "walk",
        )


if __name__ == "__main__":
    unittest.main()
