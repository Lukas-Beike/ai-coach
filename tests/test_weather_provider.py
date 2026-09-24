import copy
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from backend.errors import AppError
from backend.providers.weather import WeatherClient


class WeatherProviderTests(unittest.TestCase):
    def setUp(self):
        self.now = Mock(return_value="2026-09-20T12:34:56+00:00")
        self.logger = Mock()

    @staticmethod
    def location(*, country_code="DE", latitude=51.5, longitude=7.5):
        return {
            "name": "Münster",
            "country": "Deutschland",
            "country_code": country_code,
            "latitude": latitude,
            "longitude": longitude,
            "timezone": "Europe/Berlin",
        }

    @staticmethod
    def forecast(*, hourly_values=None, daily_values=None):
        return {
            "hourly": {
                "time": ["2026-09-20T00:00"],
                "temperature_2m": hourly_values or [12],
            },
            "daily": {
                "time": ["2026-09-20"],
                "temperature_2m_max": daily_values or [20],
            },
        }

    def make_client(self, location, forecast, *, icon_forecast=None, icon_error=None):
        requests = []

        def request(method, url, **kwargs):
            requests.append((method, url, kwargs))
            if kwargs["service"] == "open-meteo-geocoding":
                return {"results": [location]}
            if kwargs["service"] == "open-meteo-forecast-ecmwf":
                return forecast
            if icon_error is not None:
                raise icon_error
            return icon_forecast

        return WeatherClient(request, self.now, self.logger), requests

    def test_non_german_and_outside_nrw_skip_icon_d2(self):
        for location in (
            self.location(country_code="NL"),
            self.location(latitude=52.7),
        ):
            with self.subTest(location=location):
                base = self.forecast()
                client, requests = self.make_client(location, base)

                result = client.fetch("Münster")

                self.assertEqual(len(requests), 2)
                self.assertEqual(result["model"], "ECMWF IFS HRES (3–14 Tage)")
                self.assertIs(result["forecast"], base)
                self.logger.warning.assert_not_called()

    def test_nrw_merges_icon_d2_and_preserves_request_contract(self):
        base = self.forecast()
        original_base = copy.deepcopy(base)
        icon = self.forecast(hourly_values=[8], daily_values=[16])
        original_icon = copy.deepcopy(icon)
        long_query = "M" * 220
        client, requests = self.make_client(self.location(), base, icon_forecast=icon)

        result = client.fetch(long_query)

        self.assertEqual(result["query"], long_query[:200])
        self.assertEqual(result["fetched_at"], "2026-09-20T12:34:56+00:00")
        self.now.assert_called_once_with()
        self.assertEqual(
            result["model"], "ICON-D2 (0–2 Tage) + ECMWF IFS HRES (3–14 Tage)"
        )
        self.assertEqual(result["forecast"]["hourly"]["temperature_2m"], [8])
        self.assertEqual(result["forecast"]["daily"]["temperature_2m_max"], [16])
        self.assertEqual(base, original_base)
        self.assertEqual(icon, original_icon)

        self.assertEqual(
            [request[2]["service"] for request in requests],
            [
                "open-meteo-geocoding",
                "open-meteo-forecast-ecmwf",
                "open-meteo-forecast-icon-d2",
            ],
        )
        self.assertTrue(all(request[2]["timeout"] == 10 for request in requests))
        geocode_params = parse_qs(urlsplit(requests[0][1]).query)
        self.assertEqual(
            geocode_params,
            {
                "name": [long_query[:200]],
                "count": ["1"],
                "language": ["de"],
                "format": ["json"],
            },
        )
        ecmwf_params = parse_qs(urlsplit(requests[1][1]).query)
        icon_params = parse_qs(urlsplit(requests[2][1]).query)
        self.assertEqual(ecmwf_params["forecast_days"], ["14"])
        self.assertEqual(ecmwf_params["models"], ["ecmwf_ifs"])
        self.assertEqual(icon_params["forecast_days"], ["2"])
        self.assertEqual(icon_params["models"], ["icon_d2"])
        self.assertEqual(icon_params["hourly"], ecmwf_params["hourly"])
        self.assertEqual(icon_params["daily"], ecmwf_params["daily"])

    def test_icon_exception_logs_structured_warning_and_falls_back(self):
        base = self.forecast()
        client, requests = self.make_client(
            self.location(), base, icon_error=TimeoutError("offline")
        )

        result = client.fetch("Münster")

        self.assertEqual(len(requests), 3)
        self.assertEqual(result["forecast"], base)
        self.assertEqual(result["model"], "ECMWF IFS HRES (3–14 Tage)")
        self.logger.warning.assert_called_once_with(
            "ICON-D2 weather synchronization failed; using ECMWF",
            extra={
                "event": "weather_icon_d2_failed",
                "context": {"error_type": "TimeoutError"},
            },
        )

    def test_missing_geocoded_location_raises_400(self):
        requests = []

        def request(method, url, **kwargs):
            requests.append((method, url, kwargs))
            return {"results": []}

        client = WeatherClient(request, self.now, self.logger)

        with self.assertRaises(AppError) as raised:
            client.fetch("Atlantis")

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(len(requests), 1)

    def test_incomplete_ecmwf_forecast_raises_502_without_icon_request(self):
        client, requests = self.make_client(
            self.location(), {"daily": {}, "hourly": []}
        )

        with self.assertRaises(AppError) as raised:
            client.fetch("Münster")

        self.assertEqual(raised.exception.status, 502)
        self.assertEqual(len(requests), 2)


if __name__ == "__main__":
    unittest.main()
