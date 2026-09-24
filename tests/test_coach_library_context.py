import unittest

from backend.coach.context import coach_workout_library


class CoachWorkoutLibraryProjectionTests(unittest.TestCase):
    def project(self, items, *, limit=12, description_limit=1500):
        return coach_workout_library(
            items, limit=limit, description_limit=description_limit,
        )

    def test_sorts_types_for_round_robin_and_preserves_order_within_each_type(self):
        result = self.project([
            {"id": "b1", "type": "Beta"},
            {"id": "a1", "type": "Alpha"},
            {"id": "b2", "type": "Beta"},
            {"id": "a2", "type": "Alpha"},
            {"id": "b3", "type": "Beta"},
        ])

        self.assertEqual([item["id"] for item in result], ["a1", "b1", "a2", "b2", "b3"])

    def test_respects_limit_across_round_robin(self):
        result = self.project([
            {"id": "b1", "type": "Beta"},
            {"id": "a1", "type": "Alpha"},
            {"id": "b2", "type": "Beta"},
            {"id": "a2", "type": "Alpha"},
        ], limit=3)

        self.assertEqual([item["id"] for item in result], ["a1", "b1", "a2"])

    def test_excludes_dated_plan_rows(self):
        result = self.project([
            {"id": "template", "type": "Run"},
            {"id": "planned", "type": "Run", "date": "2026-09-24"},
        ])

        self.assertEqual([item["id"] for item in result], ["template"])

    def test_whitelists_fields_and_bounds_long_or_private_values(self):
        result = self.project([{
            "id": "workout",
            "name": "n" * 250,
            "description": "d" * 30,
            "type": "Run",
            "moving_time": 3600,
            "distance": 10000,
            "target": {"power": 200},
            "icu_training_load": 50,
            "icu_intensity": 0.8,
            "indoor": False,
            "tags": ["t" * 90 for _ in range(12)],
            "athlete_private_note": "must not enter prompt",
            "date": "",
        }], description_limit=7)[0]

        self.assertEqual(set(result), {
            "id", "name", "description", "type", "moving_time", "distance",
            "target", "icu_training_load", "icu_intensity", "indoor", "tags",
        })
        self.assertEqual(len(result["name"]), 200)
        self.assertEqual(result["description"], "d" * 7)
        self.assertEqual(len(result["tags"]), 10)
        self.assertEqual([len(tag) for tag in result["tags"]], [80] * 10)

    def test_ignores_non_dict_items(self):
        result = self.project([None, "invalid", 4, {"id": "valid", "sport": "Run"}])

        self.assertEqual([item["id"] for item in result], ["valid"])

    def test_empty_and_non_positive_limit_return_empty_projection(self):
        self.assertEqual(self.project([]), [])
        self.assertEqual(self.project([{"id": "valid"}], limit=0), [])


if __name__ == "__main__":
    unittest.main()
