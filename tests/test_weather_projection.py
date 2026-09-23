import copy
import unittest

from backend.weather.projection import (
    WEATHER_CONDITIONS,
    WEATHER_ICONS,
    daily_summary,
    hourly_rows,
    weather_icon,
    weather_number,
)


class WeatherProjectionTests(unittest.TestCase):
    def test_public_scalar_projection_helpers_keep_fallbacks(self):
        self.assertEqual(weather_number("1.5"), 1.5)
        self.assertIsNone(weather_number(float("nan")))
        self.assertIsNone(weather_number("1,5"))
        self.assertEqual(weather_icon(63), WEATHER_ICONS[63])
        self.assertEqual(weather_icon(999), "🌤️")
        self.assertEqual(weather_icon(None), "🌡️")

    def test_daily_summary_filters_dates_caps_rows_and_projects_fields(self):
        dates = [f"2026-09-{day:02d}" for day in range(1, 15)] + [
            "bad-date",
            "2026-09-15",
        ]
        daily = {
            "time": dates,
            "weather_code": [0, 63, 999, 3] + [0] * 20,
            "temperature_2m_min": [12, 13, 14, 15],
            "temperature_2m_max": [22, 23, 24, 25],
            "apparent_temperature_min": [11],
            "apparent_temperature_max": [21, 22, 23, 24],
            "precipitation_probability_max": [10, 20, 30, 40],
            "rain_sum": [0.0, "1.5", float("nan"), 2],
            "showers_sum": [0, 1, 2, 3],
            "snowfall_sum": [0, 0, 0, 0],
            "wind_speed_10m_max": [10, 11, 12, 13],
            "wind_gusts_10m_max": [20, 21, 22, 23],
            "wind_direction_10m_dominant": [180, 190, 200, 210],
            "sunrise": ["06:30", "06:31", "06:32", "06:33"],
            "sunset": ["20:00", "19:59", "19:58", "19:57"],
        }
        result = daily_summary({"daily": daily, "hourly": {"time": []}})

        self.assertEqual(len(result), 14)
        self.assertEqual(result[0]["date"], "2026-09-01")
        self.assertEqual(result[0]["weather_code"], 0)
        self.assertEqual(result[0]["condition"], WEATHER_CONDITIONS[0])
        self.assertEqual(result[0]["icon"], WEATHER_ICONS[0])
        self.assertEqual(result[0]["temperature_min"], 12)
        self.assertEqual(result[0]["sunrise"], "06:30")
        self.assertEqual(result[1]["date"], "2026-09-02")
        self.assertEqual(result[1]["temperature_min"], 13)
        self.assertEqual(result[1]["rain_sum"], 1.5)
        self.assertEqual(result[2]["weather_code"], 999)
        self.assertEqual(result[2]["condition"], "Unbekannte Wetterlage")

    def test_daily_fallbacks_unknown_codes_and_missing_arrays(self):
        result = daily_summary(
            {
                "daily": {
                    "time": ["2026-09-01"],
                    "weather_code": [999],
                    "temperature_2m_min": [None],
                    "sunrise": [],
                }
            }
        )[0]
        self.assertEqual(result["condition"], "Unbekannte Wetterlage")
        self.assertEqual(result["icon"], "🌤️")
        self.assertIsNone(result["temperature_min"])
        self.assertIsNone(result["sunrise"])

        no_code = daily_summary({"daily": {"time": ["2026-09-01"]}})[0]
        self.assertIsNone(no_code["weather_code"])
        self.assertEqual(no_code["condition"], "Keine Angabe")
        self.assertEqual(no_code["icon"], "🌡️")
        self.assertEqual(daily_summary({}), [])

    def test_hourly_rows_filters_date_and_keeps_available_values(self):
        forecast = {
            "hourly": {
                "time": [
                    "2026-09-01T09:00",
                    "2026-09-01T12:30",
                    "2026-09-02T10:00",
                    "2026-09-01Tbad",
                ],
                "temperature_2m": [18, 20, 21],
                "apparent_temperature": [17, 19, 20],
                "precipitation_probability": [10, 80, 50],
                "rain": [0, "1,5", 2],
                "showers": [0, 1, 0],
                "snowfall": [0, 0, 0],
                "wind_speed_10m": [5, 8, 7],
                "wind_direction_10m": [180, 200, 190],
                "wind_gusts_10m": [12, 16, 14],
                "weather_code": [1, 63, 2],
            }
        }
        result = hourly_rows(forecast, "2026-09-01")

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["hour"], 9)
        self.assertEqual(result[1]["hour"], 12)
        self.assertNotIn("rain", result[1])
        self.assertEqual(result[1]["weather_code"], 63)
        self.assertNotIn("missing", result[0])

    def test_daily_peak_requires_valid_time_and_a_real_peak(self):
        forecast = {
            "daily": {
                "time": ["2026-09-01"],
                "weather_code": [63],
            },
            "hourly": {
                "time": [
                    "2026-09-01T09:00",
                    "2026-09-01T12:30",
                    "2026-09-01Tbad",
                    "2026-09-01T14:70",
                ],
                "precipitation_probability": [10, 80, 99, 90],
            },
        }
        result = daily_summary(forecast)[0]
        self.assertEqual(result["rain_peak_time"], "12:30")

        same_peak = copy.deepcopy(forecast)
        same_peak["hourly"]["precipitation_probability"] = [80, 80, 80, 80]
        self.assertIsNone(daily_summary(same_peak)[0]["rain_peak_time"])

    def test_projection_does_not_mutate_forecast(self):
        forecast = {
            "daily": {"time": ["2026-09-01"], "weather_code": [0]},
            "hourly": {
                "time": ["2026-09-01T10:00"],
                "temperature_2m": [20],
            },
            "unrelated": {"nested": [1, 2]},
        }
        original = copy.deepcopy(forecast)

        daily_summary(forecast)
        hourly_rows(forecast, "2026-09-01")

        self.assertEqual(forecast, original)


if __name__ == "__main__":
    unittest.main()
