import copy
import unittest
from datetime import date, timedelta

from backend.weather.recommendations import (
    is_cycling_activity,
    is_outdoor_activity,
    weather_recommendation,
    weather_recommendations,
)


def forecast_for(target: date, *, low_hours=range(24), code=1):
    times = [f"{target.isoformat()}T{hour:02d}:00" for hour in range(24)]
    low_hours = set(low_hours)
    precipitation = [5 if hour in low_hours else 80 for hour in range(24)]
    return {
        "hourly": {
            "time": times,
            "apparent_temperature": [18] * 24,
            "precipitation_probability": precipitation,
            "rain": [0] * 24,
            "showers": [0] * 24,
            "wind_speed_10m": [12] * 24,
            "wind_gusts_10m": [20] * 24,
            "wind_direction_10m": [180] * 24,
            "weather_code": [code] * 24,
        }
    }


class WeatherRecommendationsTests(unittest.TestCase):
    def test_activity_classification_preserves_aliases_and_indoor_exclusions(self):
        self.assertTrue(is_outdoor_activity({"type": "Ride"}))
        self.assertTrue(is_outdoor_activity({"sport_type": "Laufen"}))
        self.assertTrue(is_cycling_activity({"name": "Gravel ride"}))
        self.assertFalse(is_outdoor_activity({"type": "Indoor cycling"}))
        self.assertFalse(is_outdoor_activity({"type": "Treadmill run"}))
        self.assertFalse(is_cycling_activity({"type": "Run"}))
        self.assertFalse(is_outdoor_activity(None))

    def test_weekday_and_friday_windows_are_selected_deterministically(self):
        monday = date(2026, 8, 31)
        friday = date(2026, 9, 4)
        monday_result = weather_recommendation(
            {
                "id": "monday",
                "type": "Ride",
                "start_date_local": f"{monday}T08:00:00",
                "moving_time": 7200,
            },
            forecast_for(monday, low_hours={8, 9, 16, 17}),
        )
        friday_result = weather_recommendation(
            {
                "id": "friday",
                "type": "Run",
                "start_date_local": f"{friday}T08:00:00",
                "moving_time": 3600,
            },
            forecast_for(friday, low_hours={8, 14}),
        )
        self.assertEqual(monday_result["suggested_time"], "16:00–18:00 Uhr")
        self.assertEqual(monday_result["availability"], "nach der Arbeit")
        self.assertEqual(friday_result["suggested_time"], "14:00–15:00 Uhr")
        self.assertEqual(friday_result["availability"], "nach der Arbeit")

    def test_weekend_and_missing_hour_gaps(self):
        saturday = date(2026, 9, 5)
        result = weather_recommendation(
            {"type": "Ride", "date": saturday.isoformat(), "moving_time": 3600},
            forecast_for(saturday),
        )
        self.assertEqual(result["availability"], "Wochenende")
        forecast = forecast_for(saturday)
        forecast["hourly"]["time"] = [
            f"{saturday.isoformat()}T{hour:02d}:00" for hour in range(6, 22, 2)
        ]
        missing = weather_recommendation(
            {"type": "Ride", "date": saturday.isoformat(), "moving_time": 7200},
            forecast,
        )
        self.assertIsNone(missing)

    def test_invalid_dates_and_duration_bounds(self):
        target = date(2026, 9, 5)
        self.assertIsNone(
            weather_recommendation({"type": "Ride"}, forecast_for(target))
        )
        self.assertIsNone(
            weather_recommendation(
                {"type": "Ride", "date": "2026-02-30"}, forecast_for(target)
            )
        )
        short = weather_recommendation(
            {"type": "Ride", "date": target.isoformat(), "moving_time": -1},
            forecast_for(target),
        )
        long = weather_recommendation(
            {"type": "Ride", "date": target.isoformat(), "moving_time": 999999},
            forecast_for(target),
        )
        self.assertEqual(short["duration_minutes"], 5)
        self.assertEqual(long["duration_minutes"], 600)

    def test_output_fields_rounding_bounds_and_input_nonmutation(self):
        target = date(2026, 9, 5)
        event = {
            "id": 42,
            "name": "x" * 250,
            "type": "Ride",
            "date": target.isoformat(),
            "moving_time": 3660,
        }
        forecast = forecast_for(target, code=63)
        before = (copy.deepcopy(event), copy.deepcopy(forecast))
        result = weather_recommendation(event, forecast)
        self.assertEqual(result["event_id"], "42")
        self.assertEqual(len(result["event_name"]), 200)
        self.assertEqual(result["duration_minutes"], 61)
        self.assertEqual(result["weather_code"], 63)
        self.assertEqual(result["precipitation_probability"], 5)
        self.assertEqual(result["apparent_temperature"], 18)
        self.assertEqual(result["wind_direction"], 180)
        self.assertTrue(result["icon"])
        self.assertIn("Böen bis 20 km/h", result["reason"])
        self.assertEqual((event, forecast), before)

    def test_five_day_filter_keeps_input_order_and_excludes_indoor_invalid(self):
        today = date(2026, 9, 1)
        planned = [
            {"id": "today", "type": "Ride", "date": today.isoformat()},
            {
                "id": "inside",
                "type": "Indoor cycling",
                "date": (today + timedelta(days=1)).isoformat(),
            },
            {
                "id": "fifth",
                "type": "Run",
                "date": (today + timedelta(days=4)).isoformat(),
            },
            {
                "id": "sixth",
                "type": "Ride",
                "date": (today + timedelta(days=5)).isoformat(),
            },
            {"id": "bad", "type": "Ride", "date": "not-a-date"},
        ]
        before = copy.deepcopy(planned)
        forecast = {
            "hourly": {
                "time": [
                    f"{(today + timedelta(days=offset)).isoformat()}T{hour:02d}:00"
                    for offset in range(5)
                    for hour in range(24)
                ],
                "apparent_temperature": [18] * 120,
                "precipitation_probability": [5] * 120,
                "rain": [0] * 120,
                "showers": [0] * 120,
                "wind_speed_10m": [12] * 120,
                "wind_gusts_10m": [20] * 120,
                "wind_direction_10m": [180] * 120,
                "weather_code": [1] * 120,
            }
        }
        result = weather_recommendations(planned, forecast, today)
        self.assertEqual([item["event_id"] for item in result], ["today", "fifth"])
        self.assertEqual(planned, before)


if __name__ == "__main__":
    unittest.main()
