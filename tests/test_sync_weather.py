"""Tests for observed weather refresh orchestration."""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest.mock import Mock

from backend.errors import AppError
from backend.sync.weather import WeatherSyncService


class _Scope:
    operation_id = "observed-operation"
    result = None


class _Observer:
    @contextmanager
    def observe(self, provider, area, reason, operation_id):
        self.arguments = (provider, area, reason, operation_id)
        scope = _Scope()
        yield scope
        self.result = scope.result


class WeatherSyncServiceTests(unittest.TestCase):
    def make_service(self, *, location="Berlin", weather=None, preview=None):
        self.profile = Mock()
        self.profile.get.return_value = {"weather_location": location}
        self.weather = Mock()
        self.weather.state.return_value = weather or {
            "days": [{}],
            "fetched_at": "2026-09-20T10:00:00+00:00",
        }
        self.preview = Mock()
        self.preview.preview.return_value = preview or {"changes": []}
        self.preview.status.return_value = {
            "needs_replan": False,
            "replan_changes": 0,
        }
        self.observer = _Observer()
        self.logger = Mock()
        return WeatherSyncService(
            self.profile,
            self.weather,
            self.preview,
            self.observer,
            self.logger,
        )

    def test_unconfigured_location_skips_weather_refresh(self):
        service = self.make_service(location="  ")

        result = service.sync(reason="startup", operation_id="job-1")

        self.assertEqual(result, {"status": "not_configured"})
        self.weather.state.assert_not_called()
        self.assertEqual(
            self.observer.arguments,
            ("weather", "forecast", "startup", "job-1"),
        )
        self.assertEqual(self.observer.result, result)

    def test_refresh_preserves_result_and_updates_adaptive_preview(self):
        service = self.make_service(
            weather={
                "days": [{}],
                "fetched_at": "2026-09-20T10:00:00+00:00",
                "_refreshed": True,
            },
            preview={"changes": [{"id": "change-1"}]},
        )

        result = service.sync(reason="manual", force=True)

        self.weather.state.assert_called_once_with(
            refresh=True,
            force=True,
            track_refresh=False,
        )
        self.assertEqual(
            result,
            {
                "status": "ok",
                "reason": "manual",
                "fetched_at": "2026-09-20T10:00:00+00:00",
                "needs_replan": True,
                "replan_changes": 1,
            },
        )
        self.assertEqual(self.observer.result, result)

    def test_cached_result_uses_existing_adaptive_status(self):
        service = self.make_service(
            weather={
                "days": [{}],
                "fetched_at": "2026-09-20T10:00:00+00:00",
                "stale": True,
            }
        )

        result = service.sync()

        self.assertEqual(result["status"], "stale")
        self.preview.preview.assert_not_called()
        self.preview.status.assert_called_once_with()

    def test_provider_error_without_days_is_raised(self):
        service = self.make_service(weather={"days": [], "error": "offline"})

        with self.assertRaises(AppError) as raised:
            service.sync()

        self.assertEqual(raised.exception.status, 502)
        self.assertEqual(raised.exception.message, "offline")

    def test_adaptive_preview_failure_falls_back_to_status(self):
        service = self.make_service(
            weather={"days": [{}], "_refreshed": True},
        )
        self.preview.preview.side_effect = RuntimeError("synthetic failure")

        result = service.sync()

        self.assertFalse(result["needs_replan"])
        self.preview.status.assert_called_once_with()
        self.logger.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
