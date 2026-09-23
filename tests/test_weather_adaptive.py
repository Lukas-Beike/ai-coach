import copy
import math
import unittest
from datetime import date, timedelta
from typing import Any

from backend.weather.adaptive import (
    WEATHER_ADAPTIVE_DAYS,
    WEATHER_ADAPTIVE_LONG_RIDE_MINUTES,
    _weather_adaptive_duration_minutes,
    _weather_adaptive_precipitation,
    weather_adaptive_reason,
)


def forecast(*, code=63, probability=70, rain=3, showers=0, snow=0) -> dict[str, Any]:
    return {
        "weather_code": code,
        "precipitation_probability_max": probability,
        "rain_sum": rain,
        "showers_sum": showers,
        "snowfall_sum": snow,
    }


def event_for(target: date, **values: Any) -> dict[str, Any]:
    return {
        "type": "Ride",
        "date": target.isoformat(),
        "moving_time": 10_800,
        **values,
    }


class WeatherAdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 9, 20)
        self.target = self.today + timedelta(days=1)
        self.weather_days = {self.target.isoformat(): forecast()}

    def test_classification_only_long_outdoor_cycling_is_adaptive(self):
        self.assertIsNotNone(
            weather_adaptive_reason(
                event_for(self.target), self.weather_days, self.today
            )
        )
        for event in (
            event_for(self.target, type="Run"),
            event_for(self.target, type="VirtualRide"),
            event_for(self.target, type="Indoor cycling"),
            event_for(self.target, type="Treadmill run"),
            None,
        ):
            self.assertIsNone(
                weather_adaptive_reason(event, self.weather_days, self.today)
            )

    def test_duration_prefers_duration_minutes_then_moving_time(self):
        self.assertEqual(
            _weather_adaptive_duration_minutes(
                {"duration_minutes": "180,25", "moving_time": 1}
            ),
            180.25,
        )
        self.assertEqual(
            _weather_adaptive_duration_minutes(
                {"duration_minutes": "bad", "moving_time": 3600}
            ),
            60,
        )
        self.assertEqual(_weather_adaptive_duration_minutes({"moving_time": "bad"}), 0)
        self.assertEqual(
            _weather_adaptive_duration_minutes(
                {"duration_minutes": math.inf, "moving_time": 3600}
            ),
            60,
        )

    def test_duration_threshold_is_inclusive(self):
        short = event_for(
            self.target, duration_minutes=WEATHER_ADAPTIVE_LONG_RIDE_MINUTES - 0.01
        )
        exact = event_for(
            self.target, duration_minutes=WEATHER_ADAPTIVE_LONG_RIDE_MINUTES
        )
        self.assertIsNone(weather_adaptive_reason(short, self.weather_days, self.today))
        self.assertIsNotNone(
            weather_adaptive_reason(exact, self.weather_days, self.today)
        )

    def test_forecast_window_includes_today_and_third_day_only(self):
        for offset in range(WEATHER_ADAPTIVE_DAYS):
            target = self.today + timedelta(days=offset)
            self.assertIsNotNone(
                weather_adaptive_reason(
                    event_for(target), {target.isoformat(): forecast()}, self.today
                )
            )
        for offset in (-1, WEATHER_ADAPTIVE_DAYS):
            target = self.today + timedelta(days=offset)
            self.assertIsNone(
                weather_adaptive_reason(
                    event_for(target), {target.isoformat(): forecast()}, self.today
                )
            )

    def test_date_precedence_and_malformed_dates(self):
        event = event_for(
            self.target, date="not-a-date", start_date_local=self.target.isoformat()
        )
        self.assertIsNone(weather_adaptive_reason(event, self.weather_days, self.today))
        self.assertIsNone(
            weather_adaptive_reason(
                event_for(self.target, date="2026-02-30"), self.weather_days, self.today
            )
        )
        self.assertIsNone(
            weather_adaptive_reason(
                event_for(self.target, date=None, start_date_local="bad"),
                self.weather_days,
                self.today,
            )
        )

    def test_rain_thresholds_and_code_handling(self):
        self.assertEqual(
            _weather_adaptive_precipitation(forecast(code=61, probability=70, rain=3))[
                :2
            ],
            (True, False),
        )
        self.assertEqual(
            _weather_adaptive_precipitation(forecast(code=61, probability=69, rain=3))[
                :2
            ],
            (False, False),
        )
        self.assertEqual(
            _weather_adaptive_precipitation(forecast(code=61, probability=0, rain=8))[
                :2
            ],
            (True, False),
        )
        self.assertEqual(
            _weather_adaptive_precipitation(forecast(code=63, probability=0, rain=0))[
                :2
            ],
            (True, False),
        )
        self.assertEqual(
            _weather_adaptive_precipitation(forecast(code="malformed"))[:2],
            (False, False),
        )

    def test_snow_thresholds(self):
        self.assertEqual(
            _weather_adaptive_precipitation(forecast(code=71, probability=70, snow=0))[
                :2
            ],
            (False, True),
        )
        self.assertEqual(
            _weather_adaptive_precipitation(
                forecast(code=71, probability=69, snow=1.99)
            )[:2],
            (False, False),
        )
        self.assertEqual(
            _weather_adaptive_precipitation(forecast(code=71, probability=0, snow=2))[
                :2
            ],
            (False, True),
        )

    def test_malformed_weather_values_are_safe(self):
        malformed = forecast(
            code="not-a-code", probability="NaN", rain="inf", showers={}, snow=None
        )
        self.assertIsNone(
            weather_adaptive_reason(
                event_for(self.target), {self.target.isoformat(): malformed}, self.today
            )
        )
        self.assertIsNone(weather_adaptive_reason(None, None, self.today))
        self.assertIsNone(
            weather_adaptive_reason(event_for(self.target), {}, self.today)
        )

    def test_exact_reason_text_and_input_nonmutation(self):
        event = event_for(self.target)
        weather_days = {
            self.target.isoformat(): forecast(
                code=63, probability=70, rain=2, showers=1
            )
        }
        before = (copy.deepcopy(event), copy.deepcopy(weather_days))
        self.assertEqual(
            weather_adaptive_reason(event, weather_days, self.today),
            f"Wetterprognose für {self.target.isoformat()}: anhaltenden Regen (bis zu 70 % Niederschlagswahrscheinlichkeit, ca. 3 mm Regen); lange Outdoor-Ausfahrt nicht sinnvoll",
        )
        self.assertEqual((event, weather_days), before)

        snow_days = {
            self.target.isoformat(): forecast(code=71, probability=70, rain=0, snow=2)
        }
        self.assertEqual(
            weather_adaptive_reason(event, snow_days, self.today),
            f"Wetterprognose für {self.target.isoformat()}: anhaltenden Schneefall (bis zu 70 % Niederschlagswahrscheinlichkeit, ca. 2 cm Schnee); lange Outdoor-Ausfahrt nicht sinnvoll",
        )


if __name__ == "__main__":
    unittest.main()
