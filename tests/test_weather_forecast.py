import copy
import unittest

from backend.weather.forecast import (
    merge_weather_forecasts,
    weather_forecast_is_complete,
    weather_forecast_params,
)


class WeatherForecastTests(unittest.TestCase):
    def test_merge_overlays_matching_hourly_and_daily_values(self):
        long_forecast = {
            "hourly": {
                "time": ["2026-09-01T00:00", "2026-09-01T01:00"],
                "temperature_2m": [10, 11],
                "weather_code": [1, 2],
            },
            "daily": {
                "time": ["2026-09-01", "2026-09-02"],
                "temperature_2m_max": [20, 21],
            },
            "metadata": {"provider": "ecmwf"},
        }
        short_forecast = {
            "hourly": {
                "time": ["2026-09-01T01:00", "2026-09-01T02:00"],
                "temperature_2m": [99, 98],
                "weather_code": [63, 65],
            },
            "daily": {
                "time": ["2026-09-02", "2026-09-03"],
                "temperature_2m_max": [31, 32],
            },
        }

        self.assertEqual(
            merge_weather_forecasts(long_forecast, short_forecast),
            {
                "hourly": {
                    "time": ["2026-09-01T00:00", "2026-09-01T01:00"],
                    "temperature_2m": [10, 99],
                    "weather_code": [1, 63],
                },
                "daily": {
                    "time": ["2026-09-01", "2026-09-02"],
                    "temperature_2m_max": [20, 31],
                },
                "metadata": {"provider": "ecmwf"},
            },
        )

    def test_merge_deep_copies_and_ignores_missing_or_malformed_series(self):
        long_forecast = {
            "hourly": {
                "time": ["2026-09-01T00:00", "2026-09-01T01:00"],
                "matching": [1, {"nested": [2]}],
                "wrong_length": [3],
                "not_a_series": "unchanged",
            },
            "daily": {"time": "not-a-list", "matching": []},
            "nested": {"keep": [{"value": 1}]},
        }
        short_forecast = {
            "hourly": {
                "time": ["2026-09-01T01:00"],
                "matching": [99],
                "new_series": [42],
                "not_a_series": {"ignored": True},
            },
            "daily": {"time": ["2026-09-01"], "matching": [100]},
        }
        before = copy.deepcopy(long_forecast)

        merged = merge_weather_forecasts(long_forecast, short_forecast)

        self.assertEqual(long_forecast, before)
        self.assertEqual(merged["hourly"]["matching"], [1, 99])
        self.assertEqual(merged["hourly"]["wrong_length"], [3])
        self.assertNotIn("new_series", merged["hourly"])
        self.assertEqual(merged["daily"]["matching"], [])
        merged["nested"]["keep"][0]["value"] = 2
        self.assertEqual(long_forecast["nested"]["keep"][0]["value"], 1)

    def test_params_preserve_location_days_model_and_requested_fields(self):
        params = weather_forecast_params(
            {"latitude": 51.96, "longitude": 7.63}, 14, "icon_d2"
        )

        self.assertEqual(params["latitude"], 51.96)
        self.assertEqual(params["longitude"], 7.63)
        self.assertEqual(params["forecast_days"], 14)
        self.assertEqual(params["models"], "icon_d2")
        self.assertEqual(params["timezone"], "auto")
        self.assertEqual(
            params["hourly"].split(","),
            [
                "temperature_2m",
                "apparent_temperature",
                "precipitation_probability",
                "rain",
                "showers",
                "snowfall",
                "weather_code",
                "wind_speed_10m",
                "wind_direction_10m",
                "wind_gusts_10m",
            ],
        )
        self.assertEqual(
            params["daily"].split(","),
            [
                "weather_code",
                "temperature_2m_min",
                "temperature_2m_max",
                "apparent_temperature_min",
                "apparent_temperature_max",
                "precipitation_probability_max",
                "rain_sum",
                "showers_sum",
                "snowfall_sum",
                "wind_speed_10m_max",
                "wind_gusts_10m_max",
                "wind_direction_10m_dominant",
                "sunrise",
                "sunset",
            ],
        )

    def test_completeness_accepts_empty_sections_and_rejects_malformed_values(self):
        self.assertTrue(weather_forecast_is_complete({"daily": {}, "hourly": {}}))
        self.assertTrue(
            weather_forecast_is_complete({"daily": {"time": []}, "hourly": {}})
        )
        for forecast in (
            None,
            [],
            {},
            {"daily": {}, "hourly": []},
            {"daily": [], "hourly": {}},
            {"daily": None, "hourly": {}},
            {"daily": {}, "hourly": None},
        ):
            self.assertFalse(weather_forecast_is_complete(forecast))


if __name__ == "__main__":
    unittest.main()
