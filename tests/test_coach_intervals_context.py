import unittest
from datetime import date, timedelta

from backend.coach.context import CoachIntervalsContextService


class CoachIntervalsContextTests(unittest.TestCase):
    def setUp(self):
        self.service = CoachIntervalsContextService()
        self.today = date(2026, 9, 23)

    def test_projects_five_newest_per_sport_with_deterministic_ties_and_rollups(self):
        rides = [
            {
                "id": f"ride-{index}",
                "sport": "ride",
                "name": f"Ride {index}",
                "started_at_local": (self.today - timedelta(days=index)).isoformat(),
                "moving_duration_s": 3600,
                "training_load": 50,
            }
            for index in range(7)
        ]
        same_day = [
            {
                "id": "a",
                "sport": "run",
                "name": "A",
                "started_at_local": self.today.isoformat(),
            },
            {
                "id": "b",
                "sport": "run",
                "name": "B",
                "started_at_local": self.today.isoformat(),
            },
        ]
        result = self.service.project(
            [],
            self.today,
            rides + same_day + [None, "invalid"],
            synced_at="sync-time",
        )
        self.assertEqual(result["synced_at"], "sync-time")
        self.assertEqual(result["source"]["synced_at"], "sync-time")

        self.assertEqual(
            [row["name"] for row in result["recent_activities_by_sport"]["Radfahren"]],
            ["Ride 0", "Ride 1", "Ride 2", "Ride 3", "Ride 4"],
        )
        self.assertEqual(
            [row["id"] for row in result["recent_activities_by_sport"]["Laufen"]],
            ["b", "a"],
        )
        self.assertEqual(
            result["activity_rollups_by_sport"]["Radfahren"]["last_7_days"]["sessions"],
            7,
        )
        self.assertEqual(
            result["activity_rollups_by_sport"]["Radfahren"]["last_30_days"]["days"], 30
        )

    def test_ignores_invalid_activities_and_preserves_unclassified_sport(self):
        result = self.service.project(
            None,
            self.today,
            [None, {"name": "No sport", "started_at_local": "bad-date"}],
        )

        # Canonical: a summary without a sport falls under the "other" label
        # instead of being grouped by its name.
        self.assertEqual(list(result["recent_activities_by_sport"]), ["Sonstiges"])
        self.assertEqual(
            result["activity_rollups_by_sport"]["Sonstiges"]["last_7_days"]["sessions"],
            0,
        )

    def test_planned_units_are_future_sorted_limited_and_compacted_without_description(
        self,
    ):
        events = [
            {
                "id": "past",
                "name": "Past",
                "date": (self.today - timedelta(days=1)).isoformat(),
            },
            {"id": "invalid", "name": "Invalid", "date": "not-a-date"},
            {
                "id": "today",
                "name": "Today",
                "date": self.today.isoformat(),
                "description": "private",
            },
        ]
        events.extend(
            {
                "id": f"future-{index:02}",
                "name": f"Future {index:02}",
                "starts_at_local": (self.today + timedelta(days=1)).isoformat(),
                "description": "private provider detail",
                "athlete_detail": "private athlete detail",
            }
            for index in range(55)
        )

        result = self.service.project(events, self.today)
        projected = result["planned_workouts"]

        self.assertEqual(len(projected), 50)
        self.assertEqual(projected[0]["name"], "Today")
        self.assertEqual(projected[1]["name"], "Future 00")
        self.assertNotIn("description", projected[0])
        self.assertNotIn("athlete_detail", projected[1])

    def test_no_planned_units_or_activities_has_exact_empty_projection_shape(self):
        result = self.service.project(None, self.today)

        self.assertEqual(
            result,
            {
                "source": {
                    "provider": "intervals",
                    "label": "Intervals.icu",
                    "synced_at": None,
                    "applies_to": [
                        "recent_activities_by_sport",
                        "activity_rollups_by_sport",
                    ],
                },
                "synced_at": None,
                "recent_activities_by_sport": {},
                "activity_rollups_by_sport": {},
                "planned_workouts": [],
                "planned_workouts_source": {
                    "kind": "local_planning",
                    "label": "Lokale Planung",
                },
                "scope": "Letzte 5 abgeschlossene Einheiten je Sportart, Sportartensummen sowie zukünftige geplante Einheiten; kein vollständiger Roh-Snapshot.",
            },
        )


if __name__ == "__main__":
    unittest.main()
