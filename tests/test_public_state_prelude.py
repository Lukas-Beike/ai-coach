"""Bootstrap local transaction and out-of-lock weather regressions."""

import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import Mock

from backend.http_api.state_prelude import (
    CalendarWindowRange,
    PublicStateLocalPrelude,
    PublicStateWeatherPrelude,
)


class PublicStatePreludeTests(unittest.TestCase):
    def setUp(self):
        self.locked = False

        @contextmanager
        def lock():
            self.locked = True
            try:
                yield
            finally:
                self.locked = False

        self.lock = lock()
        self.manager = Mock()

        @contextmanager
        def unit_of_work():
            yield object()

        self.manager.unit_of_work.side_effect = unit_of_work
        self.state = Mock()
        self.state.latest_snapshot.return_value = {"recent_activities": []}
        self.feedback = Mock()
        self.feedback.attach_to_activities.return_value = []
        self.planned = Mock()
        self.planned.list.return_value = []
        self.weather = Mock()
        self.weather.state.side_effect = self._weather_state
        self.followup = Mock()
        self.local = PublicStateLocalPrelude(
            self.state, self.feedback, self.planned, self.weather,
            self.manager, self.lock, lambda: date(2026, 9, 23),
            CalendarWindowRange(35, 35),
        )

    def _weather_state(self, _planned, *, refresh):
        if refresh:
            self.assertFalse(self.locked)
            return {"forecast": [], "_refreshed": True}
        self.assertTrue(self.locked)
        return {"forecast": []}

    def test_local_bootstrap_is_offline_and_uses_calendar_fallback_window(self):
        result = self.local.read(local_only=True)
        self.assertEqual(
            result.calendar_window,
            {"start": "2026-08-19", "end": "2026-10-28"},
        )
        self.weather.state.assert_called_once_with([], refresh=False)
        self.assertFalse(self.locked)
        weather = PublicStateWeatherPrelude(self.weather, self.followup).project(
            result.canonical_planned, result.weather
        )
        self.assertEqual(weather, {"forecast": []})
        self.weather.state.assert_called_once()
        self.followup.check.assert_not_called()

    def test_provider_refresh_and_adaptive_followup_happen_after_local_lock(self):
        self.state.latest_snapshot.return_value = {
            "recent_activities": [],
            "provider_sync": {"calendar_window": {"start": "2020-01-01", "end": "2020-02-01"}},
        }
        result = self.local.read(local_only=False)
        self.assertEqual(result.calendar_window["start"], "2020-01-01")
        self.weather.state.assert_not_called()
        weather = PublicStateWeatherPrelude(self.weather, self.followup).project(
            result.canonical_planned, result.weather
        )
        self.assertEqual(weather, {"forecast": []})
        self.weather.state.assert_called_once_with([], refresh=True)
        self.followup.check.assert_called_once_with("weather")


if __name__ == "__main__":
    unittest.main()
