import copy
import unittest

from backend.activities.detail_projection import detailed_activity


class ActivityDetailProjectionTests(unittest.TestCase):
    def test_scalars_allowlist_and_string_limits(self):
        activity = {
            "name": "N" * 600,
            "type": "T" * 300,
            "moving_time": 3600,
            "average_watts": 250.5,
            "faded": False,
            "decoupling": None,
            "raw_payload": {"secret": True},
            "metadata": "must not leak",
        }

        result = detailed_activity(activity)

        self.assertEqual(len(result["name"]), 500)
        self.assertEqual(len(result["type"]), 200)
        self.assertEqual(result["moving_time"], 3600)
        self.assertEqual(result["average_watts"], 250.5)
        self.assertFalse(result["faded"])
        self.assertNotIn("decoupling", result)
        self.assertNotIn("raw_payload", result)
        self.assertNotIn("metadata", result)

    def test_stream_allowlist_downsampling_and_endpoints(self):
        points = list(range(3000))
        activity = {
            "streams": {
                "time": points,
                "distance": ["start"] + [None] * 2998 + ["end"],
                "not_allowed": [1, 2, 3],
                "temperature": "malformed",
            }
        }

        result = detailed_activity(activity)

        self.assertIn("streams", result)
        self.assertEqual(len(result["streams"]["time"]), 2000)
        self.assertEqual(result["streams"]["time"][0], 0)
        self.assertEqual(result["streams"]["time"][-1], 2999)
        self.assertEqual(len(result["streams"]["distance"]), 2000)
        self.assertEqual(result["streams"]["distance"][0], "start")
        self.assertEqual(result["streams"]["distance"][-1], "end")
        self.assertEqual(result["streams"]["temperature"], [])
        self.assertNotIn("not_allowed", result["streams"])

    def test_laps_allowlist_bounds_and_malformed_values(self):
        laps = (
            [
                {"name": "L" * 150, "distance": 1000, "secret": "no"},
                {"average_watts": None, "max_speed": True, "icu_training_load": 80},
            ]
            + [{"distance": index} for index in range(300)]
            + ["malformed"]
        )

        result = detailed_activity({"laps": laps})

        self.assertEqual(len(result["laps"]), 200)
        self.assertEqual(len(result["laps"][0]["name"]), 120)
        self.assertEqual(result["laps"][0]["distance"], 1000)
        self.assertNotIn("secret", result["laps"][0])
        self.assertEqual(result["laps"][1]["max_speed"], True)
        self.assertEqual(result["laps"][1]["icu_training_load"], 80)

    def test_malformed_input_empty_optional_sections_and_nonmutation(self):
        activity = {
            "streams": {"time": None, "distance": []},
            "laps": [None, {}, {"unknown": "x"}],
            "name": "safe",
        }
        original = copy.deepcopy(activity)

        result = detailed_activity(activity)

        self.assertEqual(result["name"], "safe")
        self.assertEqual(result["streams"], {"time": [], "distance": []})
        self.assertNotIn("laps", result)
        self.assertEqual(activity, original)
        self.assertEqual(detailed_activity(None), {})
        self.assertEqual(detailed_activity([]), {})

    def test_projection_matches_original_for_representative_payload(self):
        activity = {
            "start_date_local": "2026-09-07T08:00:00Z",
            "name": "Synthetic run",
            "type": "Run",
            "distance": 5000,
            "streams": {"time": [0, 1, 2], "pace": [300, 295, 290]},
            "laps": [{"name": "lap 1", "distance": 1000}],
            "raw": {"credentials": "fake"},
        }
        self.assertEqual(
            detailed_activity(activity),
            {
                "start_date_local": "2026-09-07T08:00:00Z",
                "name": "Synthetic run",
                "type": "Run",
                "distance": 5000,
                "streams": {"time": [0, 1, 2], "pace": [300, 295, 290]},
                "laps": [{"name": "lap 1", "distance": 1000}],
            },
        )


if __name__ == "__main__":
    unittest.main()
