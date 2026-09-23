import unittest
from datetime import date

from backend.weather.history import (
    add_to_planned,
    calendar_state,
    decode_history,
    remember_forecasts,
)


class WeatherHistoryTests(unittest.TestCase):
    def test_decode_history_accepts_dict_and_json_and_rejects_malformed_values(self):
        source = {"2026-09-19": {"temperature_max": 18}}
        decoded = decode_history(source)
        self.assertEqual(decoded, source)
        self.assertIsNot(decoded, source)
        self.assertEqual(decode_history('{"2026-09-19": {}}'), {"2026-09-19": {}})
        for value in ("{", "[]", 1, None):
            self.assertEqual(decode_history(value), {})

    def test_remember_forecasts_overwrites_days_and_preserves_metadata(self):
        history = {"2026-09-18": {"note": "preserve"}}
        first_cache = {
            "query": "Berlin",
            "location": {"name": "Berlin"},
            "fetched_at": "saved-1",
            "forecast": {
                "daily": {
                    "time": ["2026-09-18", "2026-09-19", "bad-date"],
                    "temperature_2m_max": [12, 17, 99],
                }
            },
        }
        second_cache = {
            "query": "Bonn",
            "location": {"name": ""},
            "fetched_at": "saved-2",
            "forecast": {
                "daily": {
                    "time": ["2026-09-19"],
                    "temperature_2m_max": [20],
                }
            },
        }

        remembered = remember_forecasts(
            history, None, {"forecast": []}, first_cache, second_cache
        )

        self.assertEqual(history, {"2026-09-18": {"note": "preserve"}})
        self.assertEqual(remembered["2026-09-18"]["temperature_max"], 12)
        self.assertEqual(remembered["2026-09-18"]["forecast_location"], "Berlin")
        self.assertEqual(remembered["2026-09-18"]["forecast_saved_at"], "saved-1")
        self.assertEqual(remembered["2026-09-19"]["temperature_max"], 20)
        self.assertEqual(remembered["2026-09-19"]["forecast_location"], "Bonn")
        self.assertEqual(remembered["2026-09-19"]["forecast_saved_at"], "saved-2")
        self.assertNotIn("bad-date", remembered)

    def test_calendar_state_keeps_past_history_and_current_weather_wins(self):
        today = date(2026, 9, 20)
        history = {
            "2026-09-18": {"date": "2026-09-18", "temperature_max": 12},
            "2026-09-19": {"date": "2026-09-19", "temperature_max": 13},
            "2026-09-20": {"date": "2026-09-20", "temperature_max": 1},
            "not-a-day": {"date": "not-a-day"},
            "2026-09-17": None,
        }
        weather = {
            "fetched_at": "current-save",
            "query": "Ignored fallback",
            "location": {},
            "days": [
                {"date": "2026-09-20", "temperature_max": 21},
                {"date": "2026-09-19", "temperature_max": 19},
                {"date": "2026-09-21", "temperature_max": 22},
                {"date": None, "temperature_max": 99},
                None,
            ],
        }

        state = calendar_state(history, weather, today=today)

        self.assertEqual(
            [row["date"] for row in state["days"]],
            ["2026-09-18", "2026-09-19", "2026-09-20", "2026-09-21"],
        )
        self.assertEqual(state["days"][0]["temperature_max"], 12)
        self.assertTrue(state["days"][0]["archived_forecast"])
        self.assertEqual(state["days"][1]["temperature_max"], 19)
        self.assertEqual(state["days"][1]["forecast_saved_at"], "current-save")
        self.assertIsNone(state["days"][1]["forecast_location"])
        self.assertFalse(state["days"][2]["archived_forecast"])
        self.assertEqual(history["2026-09-20"]["temperature_max"], 1)
        self.assertNotIn("archived_forecast", weather["days"][0])

    def test_calendar_state_accepts_malformed_inputs(self):
        self.assertEqual(
            calendar_state("{", None, today=date(2026, 9, 20)), {"days": []}
        )
        self.assertEqual(
            calendar_state(
                {"2026-09-19": "broken"}, {"days": "broken"}, today=date(2026, 9, 20)
            ),
            {"days": []},
        )

    def test_add_to_planned_matches_id_before_date_and_name_without_mutation(self):
        planned = [
            {
                "id": "same-id",
                "name": "Renamed",
                "start_date_local": "2026-09-21T08:00",
            },
            {
                "id": "date-match",
                "name": "Tempo",
                "start_date_local": "2026-09-22T09:00",
            },
            {"name": "Geplante Einheit", "date": "2026-09-23"},
            {"id": "none", "name": "No match", "date": "2026-09-24"},
        ]
        recommendations = [
            {
                "event_id": "same-id",
                "date": "2026-09-25",
                "event_name": "Other",
                "tag": "id",
            },
            {"date": "2026-09-22", "event_name": "Tempo", "tag": "date-name"},
            {
                "date": "2026-09-23",
                "event_name": "Geplante Einheit",
                "tag": "default-name",
            },
            None,
        ]
        weather = {"recommendations": recommendations}

        enriched = add_to_planned(planned, weather)

        self.assertEqual(
            [event.get("weather_recommendation", {}).get("tag") for event in enriched],
            ["id", "date-name", "default-name", None],
        )
        self.assertEqual(
            [event.get("id") for event in enriched],
            ["same-id", "date-match", None, "none"],
        )
        self.assertTrue(
            all(copy is not original for copy, original in zip(enriched, planned))
        )
        self.assertNotIn("weather_recommendation", planned[0])
        self.assertNotIn("weather_recommendation", planned[1])
        self.assertEqual(
            recommendations[0],
            {
                "event_id": "same-id",
                "date": "2026-09-25",
                "event_name": "Other",
                "tag": "id",
            },
        )

    def test_add_to_planned_handles_malformed_weather_and_custom_default_name(self):
        planned = [{"date": "2026-09-21", "name": "Custom"}]
        self.assertEqual(add_to_planned(planned, None), planned)
        self.assertEqual(add_to_planned(planned, {"recommendations": {}}), planned)
        result = add_to_planned(
            [{"date": "2026-09-22"}],
            {"recommendations": [{"date": "2026-09-22", "event_name": "Workout"}]},
            default_name="Workout",
        )
        self.assertIn("weather_recommendation", result[0])

    def test_add_to_planned_does_not_normalize_recommendation_match_keys(self):
        planned = [
            {"id": "recommendation-id-only", "date": "2026-09-21", "name": "Planned"},
            {
                "event_id": "planned-event-id-only",
                "date": "2026-09-22",
                "name": "Planned",
            },
            {"date": "2026-09-23", "name": "x" * 200},
            {"date": "2026-09-24", "name": "Geplante Einheit"},
        ]
        weather = {
            "recommendations": [
                {
                    "id": "recommendation-id-only",
                    "date": "other-day",
                    "event_name": "Different",
                },
                {
                    "event_id": "planned-event-id-only",
                    "date": "other-day",
                    "event_name": "Different",
                },
                {
                    "date": "2026-09-23",
                    "event_name": "x" * 200 + " beyond planned limit",
                },
                {"date": "2026-09-24"},
            ]
        }

        enriched = add_to_planned(planned, weather)

        self.assertTrue(
            all("weather_recommendation" not in event for event in enriched)
        )


if __name__ == "__main__":
    unittest.main()
