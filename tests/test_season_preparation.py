import unittest
from datetime import date

from backend.planning.season_preparation import season_preparation

TODAY = date(2026, 10, 2)
BASIS_DAY = date(2026, 10, 1)


def _season(rows, events, today, observations=None):
    """Run season_preparation over fixed activity rows."""
    return season_preparation(
        events,
        today,
        "UTC",
        observations,
        activity_summaries=lambda start, end: rows,
    )


class SeasonPreparationTests(unittest.TestCase):
    today = date(2026, 10, 2)

    def test_preparation_is_observed_and_does_not_follow_calendar_phase(self):
        event = {
            "id": "race",
            "event_date": "2026-10-10",
            "sport": "Running",
            "priority": "A",
            "name": "Synthetic race",
        }
        result = _season([], [event], self.today)["events"][0]
        self.assertEqual("taper", result["phase"])
        self.assertEqual("insufficient_data", result["preparation"]["status"])
        rows = [
            {
                "id": "run",
                "sport": "run",
                "started_at_local": "2026-10-01T10:00:00",
                "moving_duration_s": 3600,
            }
        ]
        result = _season(rows, [event], self.today)["events"][0]
        self.assertEqual("observations", result["preparation"]["status"])
        self.assertEqual(
            "run", result["preparation"]["long_sessions"][0]["activity_id"]
        )

    def test_competition_sport_matches_canonical_sport_and_indoor_environment(self):
        ride = {"id": "a", "sport": "ride", "started_at_local": "2026-10-01T10:00:00"}
        rows = [
            {**ride, "moving_duration_s": 3600, "environment": "outdoor"},
            {**ride, "id": "b", "moving_duration_s": 1800, "environment": "virtual"},
            {**ride, "id": "c", "sport": "run", "moving_duration_s": 900},
        ]
        base = {
            "id": "race",
            "event_date": "2026-10-10",
            "priority": "A",
            "name": "Synthetic",
        }
        for event, expected in (
            ({"sport": "Cycling"}, ("ride", ["a"])),
            ({"sport": "VirtualRide"}, ("ride", ["b"])),
            ({"sport": "ride", "environment": "indoor"}, ("ride", ["b"])),
            ({"sport": "Running"}, ("run", ["c"])),
        ):
            with self.subTest(event=event):
                result = _season(rows, [{**base, **event}], self.today)["events"][0]
                preparation = result["preparation"]
                self.assertEqual(expected[0], preparation["sport"])
                self.assertEqual(
                    expected[1],
                    [item["activity_id"] for item in preparation["long_sessions"]],
                )

    def test_analyses_are_found_under_the_stored_activity_key(self):
        event = {
            "id": "race",
            "event_date": "2026-10-10",
            "sport": "Running",
            "priority": "A",
            "name": "Synthetic",
        }
        row = {
            "id": "act_1",
            "sport": "run",
            "started_at_local": "2026-10-01T10:00:00",
            "moving_duration_s": 3600,
            "record_ids": {"intervals": "i-1"},
        }
        analyses = [{"activity_id": "act_1", "aerobic": {"status": "ok"}}]
        result = _season([row], [event], self.today, analyses)["events"][0]
        preparation = result["preparation"]
        self.assertEqual("act_1", preparation["long_sessions"][0]["activity_id"])
        self.assertEqual({"status": "ok"}, preparation["long_sessions"][0]["aerobic"])
        self.assertEqual(1, preparation["source_counts"]["cached activity analyses"])

    def test_race_context_requires_confirmed_units_and_reports_known_dimensions(self):
        event = {
            "id": "race",
            "event_date": "2027-04-10",
            "sport": "Run",
            "priority": "B",
            "distance": "21.0975 km",
            "target": "01:45:00",
            "name": "Half",
        }
        activity = {
            "id": "run",
            "sport": "run",
            "started_at_local": "2026-10-01T07:00:00",
            "moving_duration_s": 7200,
            "distance_m": 18000,
        }
        analyses = [
            {
                "activity_id": "run",
                "aerobic": {"status": "ok"},
                "power_profile": {"status": "insufficient_data"},
                "interval_quality": {"status": "ok"},
            }
        ]
        result = _season([activity], [event], self.today, analyses)["events"][0][
            "preparation"
        ]
        self.assertEqual(21097.5, result["target_context"]["distance_meters"])
        self.assertTrue(result["target_context"]["target_confirmed"])
        self.assertEqual(1, result["weekly_observed_volume"]["weeks_with_sessions"])
        self.assertEqual(7200, result["long_session_evidence"]["duration_seconds"])
        self.assertEqual(
            {"aerobic": 1, "power_profile": 0, "interval_quality": 1},
            result["specificity_evidence"]["known_dimensions"],
        )

    def test_no_history_unknown_distance_and_target_remain_nullable(self):
        event = {
            "id": "race",
            "event_date": "2027-04-10",
            "sport": "Ride",
            "priority": "B",
            "distance": "Gran Fondo",
            "target": "",
            "name": "Event",
        }
        result = _season([], [event], self.today)["events"][0]["preparation"]
        self.assertEqual("insufficient_data", result["status"])
        self.assertIsNone(result["target_context"]["distance_meters"])
        self.assertFalse(result["target_context"]["distance_confirmed"])
        self.assertIsNone(result["target_context"]["target"])
        self.assertEqual(
            "insufficient_data", result["weekly_observed_volume"]["status"]
        )
        self.assertIsNone(result["weekly_observed_volume"]["distance_meters"])
        self.assertIsNone(result["long_session_evidence"]["duration_seconds"])
        self.assertEqual("insufficient_data", result["specificity_evidence"]["status"])

    def test_numeric_race_distance_needs_reliable_meter_scale(self):
        for distance, expected in (
            ("21.1", None),
            ("21097", 21097),
            ("21.1 km", 21100),
            ("half marathon", None),
        ):
            event = {
                "id": "race",
                "event_date": "2027-04-10",
                "sport": "Run",
                "priority": "B",
                "distance": distance,
                "name": "Event",
            }
            actual = _season([], [event], self.today)["events"][0]["preparation"][
                "target_context"
            ]["distance_meters"]
            self.assertEqual(expected, actual)

    def test_past_competition_window_is_anchored_at_event_date(self):
        event = {
            "id": "past",
            "event_date": "2026-09-01",
            "sport": "Run",
            "priority": "A",
            "name": "Past race",
        }
        rows = [
            {
                "id": "before",
                "sport": "run",
                "started_at_local": "2026-06-14T09:00:00",
                "moving_duration_s": 1800,
            },
            {
                "id": "first-week",
                "sport": "run",
                "started_at_local": "2026-06-15T09:00:00",
                "moving_duration_s": 1800,
            },
            {
                "id": "sunday",
                "sport": "run",
                "started_at_local": "2026-08-30T09:00:00",
                "moving_duration_s": 1800,
            },
            {
                "id": "after",
                "sport": "run",
                "started_at_local": "2026-09-02T09:00:00",
                "moving_duration_s": 1800,
            },
        ]
        preparation = _season(rows, [event], self.today)["events"][0]["preparation"]
        self.assertEqual("2026-06-15", preparation["window_start"])
        self.assertEqual("2026-09-01", preparation["window_end"])
        self.assertEqual(2, preparation["sessions_84_days"])
        weeks = preparation["weeks"]
        self.assertEqual(12, len(weeks))
        for week in weeks:
            start, end = (
                date.fromisoformat(week["start"]),
                date.fromisoformat(week["end"]),
            )
            self.assertEqual(0, start.weekday())
            self.assertEqual(6, end.weekday())
        self.assertEqual("2026-06-15", weeks[0]["start"])
        self.assertEqual("2026-08-31", weeks[-1]["start"])
        self.assertEqual(12, preparation["weekly_observed_volume"]["weeks_total"])

    def test_future_competition_evidence_covers_the_weeks_up_to_today(self):
        event = {
            "id": "future",
            "event_date": "2026-12-20",
            "sport": "Run",
            "priority": "A",
            "name": "Future race",
        }
        rows = [
            {
                "id": "run",
                "sport": "run",
                "started_at_local": "2026-10-01T09:00:00",
                "moving_duration_s": 1800,
            },
        ]
        preparation = _season(rows, [event], self.today)["events"][0]["preparation"]
        self.assertEqual("2026-07-13", preparation["window_start"])
        self.assertEqual("2026-10-02", preparation["window_end"])
        self.assertEqual(1, preparation["sessions_84_days"])
        self.assertEqual(12, len(preparation["weeks"]))
        self.assertEqual("2026-09-28", preparation["weeks"][-1]["start"])
        self.assertEqual(1, preparation["weeks_with_recorded_training"])

    def test_far_future_competition_keeps_current_evidence(self):
        event = {
            "id": "far",
            "event_date": "2027-04-10",
            "sport": "Run",
            "priority": "B",
            "name": "Far race",
        }
        rows = [
            {
                "id": "run",
                "sport": "run",
                "started_at_local": "2026-10-01T09:00:00",
                "moving_duration_s": 1800,
            },
        ]
        preparation = _season(rows, [event], self.today)["events"][0]["preparation"]
        self.assertEqual("2026-07-13", preparation["window_start"])
        self.assertEqual("2026-10-02", preparation["window_end"])
        self.assertEqual(1, preparation["sessions_84_days"])
        self.assertEqual("observations", preparation["status"])


if __name__ == "__main__":
    unittest.main()
