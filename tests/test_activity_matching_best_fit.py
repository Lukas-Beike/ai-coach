import itertools
import unittest

from backend.activities.matching import match_planned_workouts

DAY = "2026-09-20"


def _unit(unit_id, sport, minutes, load=None):
    unit = {
        "id": unit_id,
        "category": "WORKOUT",
        "type": sport,
        "start_date_local": DAY,
        "moving_time": minutes * 60,
    }
    if load is not None:
        unit["icu_training_load"] = load
    return unit


def _activity(activity_id, sport, minutes, start="08:00:00", load=None):
    activity = {
        "id": activity_id,
        "type": sport,
        "start_date_local": f"{DAY}T{start}",
        "moving_time": minutes * 60,
    }
    if load is not None:
        activity["icu_training_load"] = load
    return activity


def _pairs(planned, activities, result):
    """Map planned unit ids to matched activity ids for order-free comparison."""
    return {planned[index]["id"]: activity["id"] for index, activity in result.items()}


class DateOnlyBestFitTests(unittest.TestCase):
    def test_same_day_ride_and_run_pair_by_sport_then_duration(self):
        planned = [_unit("ride", "Ride", 60), _unit("run", "Run", 30)]
        activities = [
            _activity("run-35", "Run", 35),
            _activity("ride-65", "VirtualRide", 65),
        ]
        expected = {"ride": "ride-65", "run": "run-35"}
        for planned_order, activity_order in itertools.product(
            [planned, list(reversed(planned))],
            [activities, list(reversed(activities))],
        ):
            with self.subTest(
                planned=[unit["id"] for unit in planned_order],
                activities=[activity["id"] for activity in activity_order],
            ):
                result = match_planned_workouts(planned_order, activity_order)
                self.assertEqual(
                    _pairs(planned_order, activity_order, result), expected
                )

    def test_same_sport_units_prefer_closest_duration_regardless_of_order(self):
        planned = [_unit("short", "Run", 30), _unit("long", "Run", 60)]
        activities = [_activity("a-65", "Run", 65), _activity("a-35", "Run", 35)]
        expected = {"short": "a-35", "long": "a-65"}
        for planned_order, activity_order in itertools.product(
            [planned, list(reversed(planned))],
            [activities, list(reversed(activities))],
        ):
            with self.subTest(
                planned=[unit["id"] for unit in planned_order],
                activities=[activity["id"] for activity in activity_order],
            ):
                result = match_planned_workouts(planned_order, activity_order)
                self.assertEqual(
                    _pairs(planned_order, activity_order, result), expected
                )

    def test_sport_family_members_are_equivalent(self):
        cases = [
            ("Ride", "VirtualRide"),
            ("VirtualRide", "Ride"),
            ("Ride", "GravelRide"),
            ("MountainBikeRide", "VirtualRide"),
            ("Run", "TrailRun"),
            ("VirtualRun", "Run"),
            ("Swim", "OpenWaterSwim"),
        ]
        for planned_sport, activity_sport in cases:
            with self.subTest(planned=planned_sport, activity=activity_sport):
                planned = [_unit("unit", planned_sport, 60)]
                activities = [_activity("act", activity_sport, 60)]
                result = match_planned_workouts(planned, activities)
                self.assertEqual(_pairs(planned, activities, result), {"unit": "act"})

    def test_different_sport_family_stays_unmatched(self):
        cases = [("Swim", "Run"), ("Run", "Ride"), ("Ride", "Swim")]
        for planned_sport, activity_sport in cases:
            with self.subTest(planned=planned_sport, activity=activity_sport):
                planned = [_unit("unit", planned_sport, 60)]
                activities = [_activity("act", activity_sport, 60)]
                self.assertEqual(match_planned_workouts(planned, activities), {})

    def test_load_breaks_duration_ties_in_either_order(self):
        planned = [_unit("unit", "Ride", 60, load=80)]
        activities = [
            _activity("far-load", "Ride", 60, start="07:00:00", load=50),
            _activity("near-load", "Ride", 60, start="09:00:00", load=78),
        ]
        for activity_order in (activities, list(reversed(activities))):
            with self.subTest(order=[activity["id"] for activity in activity_order]):
                result = match_planned_workouts(planned, activity_order)
                self.assertEqual(
                    _pairs(planned, activity_order, result), {"unit": "near-load"}
                )

    def test_start_time_breaks_remaining_ties(self):
        planned = [_unit("unit", "Run", 30)]
        activities = [
            _activity("late", "Run", 30, start="14:00:00"),
            _activity("early", "Run", 30, start="08:00:00"),
        ]
        for activity_order in (activities, list(reversed(activities))):
            with self.subTest(order=[activity["id"] for activity in activity_order]):
                result = match_planned_workouts(planned, activity_order)
                self.assertEqual(
                    _pairs(planned, activity_order, result), {"unit": "early"}
                )

    def test_one_activity_is_never_assigned_to_two_units(self):
        planned = [_unit("first", "Run", 30), _unit("second", "Run", 31)]
        activities = [_activity("only", "Run", 30)]
        result = match_planned_workouts(planned, activities)
        self.assertEqual(len(result), 1)
        self.assertEqual(_pairs(planned, activities, result), {"first": "only"})

    def test_midnight_unit_prefers_the_fitting_later_ride(self):
        # Units without a planned time are stored at local midnight (P2-04).
        for start in (f"{DAY}T00:00:00", f"{DAY}T00:00", f"{DAY} 00:00:00"):
            with self.subTest(start=start):
                unit = {**_unit("ride", "Ride", 45), "start_date_local": start}
                activities = [
                    _activity("noon-30", "Ride", 30, start="12:00:00"),
                    _activity("evening-45", "VirtualRide", 45, start="18:00:00"),
                ]
                result = match_planned_workouts([unit], activities)
                self.assertEqual(
                    _pairs([unit], activities, result), {"ride": "evening-45"}
                )

    def test_timed_unit_keeps_its_nearest_start_match(self):
        timed = {
            "id": "timed",
            "category": "WORKOUT",
            "type": "Run",
            "start_date_local": f"{DAY}T10:00:00",
        }
        activities = [
            _activity("morning", "Run", 30, start="09:00:00"),
            _activity("late", "Run", 30, start="10:30:00"),
        ]
        result = match_planned_workouts([timed], activities)
        self.assertEqual(_pairs([timed], activities, result), {"timed": "late"})

    def test_timed_unit_is_not_stolen_by_an_earlier_date_only_unit(self):
        date_only = _unit("date-only", "Run", 30)
        timed = {
            "id": "timed",
            "category": "WORKOUT",
            "type": "Run",
            "start_date_local": f"{DAY}T10:00:00",
        }
        activities = [_activity("only", "Run", 30, start="10:00:00")]
        result = match_planned_workouts([date_only, timed], activities)
        self.assertEqual(
            _pairs([date_only, timed], activities, result), {"timed": "only"}
        )


if __name__ == "__main__":
    unittest.main()
