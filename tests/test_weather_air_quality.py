import unittest
from datetime import date
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from backend.providers import air_quality, dwd_pollen
from backend.providers.weather import WeatherClient
from backend.weather import cache, history, projection, recommendations

LOCATION = {
    "name": "Dortmund",
    "country": "Deutschland",
    "country_code": "DE",
    "latitude": 51.51494,
    "longitude": 7.466,
    "timezone": "Europe/Berlin",
}

EVENT = {"type": "Run", "name": "Lauf", "start_date_local": "2026-10-17"}


def dwd_feed():
    return {
        "last_update": "2026-10-17 11:00 Uhr",
        "content": [
            {
                "region_id": 40,
                "partregion_id": 41,
                "region_name": "Nordrhein-Westfalen",
                "partregion_name": "Rhein.-Westfäl. Tiefland",
                "Pollen": {
                    "Birke": {"today": "1-2", "tomorrow": "1", "dayafter_to": "0"},
                    "Graeser": {"today": "0", "tomorrow": "2", "dayafter_to": "x"},
                    "Unbekannt": {"today": "3"},
                },
            },
            {
                "region_id": 50,
                "partregion_id": -1,
                "region_name": "Brandenburg und Berlin",
                "partregion_name": "",
                "Pollen": {"Erle": {"today": "3", "tomorrow": "3", "dayafter_to": "3"}},
            },
        ],
    }


def weather_forecast():
    return {
        "hourly": {
            "time": ["2026-10-17T10:00", "2026-10-17T11:00", "2026-10-18T10:00"],
            "temperature_2m": [12, 13, 14],
        },
        "daily": {"time": ["2026-10-17", "2026-10-18"]},
    }


def air_quality_response():
    return {
        "hourly": {
            "time": ["2026-10-17T11:00", "2026-10-18T10:00", "2026-10-19T10:00"],
            "european_aqi": [65, 18, 30],
            "pm2_5": [21.4, 4.0, 5.0],
            "uv_index": [2.5, 1.0, 1.0],
            "birch_pollen": [12.6, 0.4, 0.0],
            "ozone": [1, 2],
        }
    }


class AirQualityProviderTests(unittest.TestCase):
    def test_params_request_hourly_cams_variables(self):
        params = air_quality.air_quality_params(LOCATION)

        self.assertEqual(params["domains"], "auto")
        self.assertIn("european_aqi", params["hourly"].split(","))
        self.assertIn("birch_pollen", params["hourly"].split(","))

    def test_merge_aligns_series_to_forecast_hours(self):
        forecast = weather_forecast()

        merged = air_quality.merge_air_quality(forecast, air_quality_response())

        self.assertEqual(merged["hourly"]["european_aqi"], [None, 65, 18])
        self.assertEqual(merged["hourly"]["temperature_2m"], [12, 13, 14])
        self.assertNotIn("ozone", merged["hourly"])
        self.assertNotIn("european_aqi", forecast["hourly"])

    def test_merge_ignores_malformed_air_quality(self):
        forecast = weather_forecast()

        for payload in (None, {"hourly": []}, {"hourly": {"time": "x"}}):
            with self.subTest(payload=payload):
                self.assertEqual(
                    air_quality.merge_air_quality(forecast, payload), forecast
                )

    def test_client_rejects_response_without_hourly_data(self):
        client = air_quality.AirQualityClient(Mock(return_value={"error": True}))

        with self.assertRaises(TypeError):
            client.fetch(LOCATION)


class DwdPollenProviderTests(unittest.TestCase):
    def test_region_query_uses_lat_lon_point(self):
        params = dwd_pollen.pollen_region_params(LOCATION)

        self.assertEqual(params["typeNames"], "dwd:Pollenfluggebiete")
        self.assertEqual(
            params["CQL_FILTER"], "INTERSECTS(THE_GEOM,POINT(7.466 51.5149))"
        )

    def test_region_id_accepts_only_positive_numbers(self):
        self.assertEqual(
            dwd_pollen.pollen_region_id(
                {"features": [{"properties": {"GF": True}}, {"properties": {"GF": 41}}]}
            ),
            41,
        )
        for response in ({"features": []}, {"features": [{"properties": {"GF": -1}}]}):
            with self.subTest(response=response):
                self.assertIsNone(dwd_pollen.pollen_region_id(response))

    def test_forecast_maps_partregion_levels_to_dates(self):
        forecast = dwd_pollen.pollen_forecast(dwd_feed(), 41)

        self.assertEqual(forecast["source"], "DWD")
        self.assertEqual(forecast["region"], "Rhein.-Westfäl. Tiefland")
        self.assertEqual(
            forecast["days"],
            {
                "2026-10-17": {"Birke": "1-2", "Gräser": "0"},
                "2026-10-18": {"Birke": "1", "Gräser": "2"},
                "2026-10-19": {"Birke": "0"},
            },
        )

    def test_forecast_uses_region_without_partregion(self):
        forecast = dwd_pollen.pollen_forecast(dwd_feed(), 50)

        self.assertEqual(forecast["region"], "Brandenburg und Berlin")
        self.assertEqual(forecast["days"]["2026-10-17"], {"Erle": "3"})

    def test_forecast_rejects_unknown_region_or_date(self):
        self.assertIsNone(dwd_pollen.pollen_forecast(dwd_feed(), 99))
        self.assertIsNone(
            dwd_pollen.pollen_forecast({**dwd_feed(), "last_update": "gestern"}, 41)
        )

    def test_client_skips_lookup_outside_germany(self):
        request = Mock()

        result = dwd_pollen.DwdPollenClient(request).fetch(
            {**LOCATION, "country_code": "AT"}
        )

        self.assertIsNone(result)
        request.assert_not_called()

    def test_client_resolves_region_then_reads_feed(self):
        def request(method, url, **kwargs):
            if kwargs["service"] == "dwd-pollen-region":
                query = parse_qs(urlsplit(url).query)
                self.assertEqual(query["propertyName"], ["GF"])
                return {"features": [{"properties": {"GF": 41}}]}
            self.assertEqual(url, dwd_pollen.DWD_POLLEN_URL)
            return dwd_feed()

        result = dwd_pollen.DwdPollenClient(request).fetch(LOCATION)

        self.assertEqual(result["region_id"], 41)

    def test_client_returns_none_without_region(self):
        request = Mock(return_value={"features": []})

        self.assertIsNone(dwd_pollen.DwdPollenClient(request).fetch(LOCATION))
        self.assertEqual(request.call_count, 1)


class WeatherClientOptionalSourcesTests(unittest.TestCase):
    def make_client(self, air_quality_client, pollen_client):
        def request(method, url, **kwargs):
            if kwargs["service"] == "open-meteo-geocoding":
                return {"results": [{**LOCATION, "country_code": "NL"}]}
            return {
                "hourly": {"time": ["2026-10-17T11:00"], "temperature_2m": [12]},
                "daily": {"time": ["2026-10-17"], "temperature_2m_max": [15]},
            }

        logger = Mock()
        client = WeatherClient(
            request,
            Mock(return_value="2026-10-17T12:00:00+00:00"),
            logger,
            forecast_days=14,
            air_quality_client=air_quality_client,
            pollen_client=pollen_client,
        )
        return client, logger

    def test_optional_sources_enrich_cached_weather(self):
        aq_client = Mock()
        aq_client.fetch.return_value = air_quality_response()
        pollen_client = Mock()
        pollen_client.fetch.return_value = {"source": "DWD", "days": {}}
        client, logger = self.make_client(aq_client, pollen_client)

        result = client.fetch("Amsterdam")

        self.assertEqual(result["forecast"]["hourly"]["european_aqi"], [65])
        self.assertEqual(result["air_quality_source"], "Open-Meteo/CAMS")
        self.assertEqual(result["pollen"], {"source": "DWD", "days": {}})
        logger.warning.assert_not_called()

    def test_optional_source_failures_keep_weather_and_log_type_only(self):
        aq_client = Mock()
        aq_client.fetch.side_effect = TypeError("secret detail")
        pollen_client = Mock()
        pollen_client.fetch.side_effect = RuntimeError("secret detail")
        client, logger = self.make_client(aq_client, pollen_client)

        result = client.fetch("Amsterdam")

        self.assertNotIn("air_quality_source", result)
        self.assertNotIn("pollen", result)
        self.assertNotIn("european_aqi", result["forecast"]["hourly"])
        self.assertEqual(logger.warning.call_count, 2)
        self.assertNotIn("secret detail", repr(logger.warning.call_args_list))


class AirQualityProjectionTests(unittest.TestCase):
    def forecast(self):
        return air_quality.merge_air_quality(weather_forecast(), air_quality_response())

    def test_daily_summary_adds_air_quality_and_cams_pollen(self):
        first, second = projection.daily_summary(self.forecast())

        self.assertEqual(
            first["air_quality"],
            {
                "european_aqi_max": 65.0,
                "pm2_5_max": 21.4,
                "uv_index_max": 2.5,
                "european_aqi_category": "schlecht",
            },
        )
        self.assertEqual(
            first["pollen"],
            {
                "source": "Open-Meteo/CAMS",
                "unit": "Körner/m³",
                "concentrations": {"Birke": 13},
            },
        )
        self.assertEqual(second["pollen"]["concentrations"], {})

    def test_dwd_pollen_takes_precedence_over_cams(self):
        pollen = dwd_pollen.pollen_forecast(dwd_feed(), 41)

        first, second = projection.daily_summary(self.forecast(), pollen)

        self.assertEqual(
            first["pollen"],
            {
                "source": "DWD",
                "region": "Rhein.-Westfäl. Tiefland",
                "levels": {"Birke": "1-2"},
            },
        )
        self.assertEqual(second["pollen"]["levels"], {"Birke": "1", "Gräser": "2"})

    def test_rows_without_optional_data_stay_unchanged(self):
        rows = projection.daily_summary(weather_forecast())

        self.assertTrue(all("air_quality" not in row for row in rows))
        self.assertTrue(all("pollen" not in row for row in rows))

    def test_european_aqi_categories(self):
        cases = {
            None: None,
            -1: None,
            20: "gut",
            40: "ordentlich",
            55: "mäßig",
            80: "schlecht",
            100: "sehr schlecht",
            101: "extrem schlecht",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(projection.european_aqi_category(value), expected)

    def test_history_archives_pollen_with_forecast(self):
        cached = {
            "forecast": self.forecast(),
            "pollen": dwd_pollen.pollen_forecast(dwd_feed(), 41),
            "fetched_at": "2026-10-17T12:00:00+00:00",
        }

        archived = history.remember_forecasts({}, cached)

        self.assertEqual(archived["2026-10-17"]["pollen"]["source"], "DWD")

    def test_ready_state_attributes_every_present_source(self):
        cached = {
            "query": "Dortmund",
            "forecast": self.forecast(),
            "air_quality_source": "Open-Meteo/CAMS",
            "pollen": dwd_pollen.pollen_forecast(dwd_feed(), 41),
            "fetched_at": "2026-10-17T12:00:00+00:00",
        }
        state = cache.cache_state(
            "Dortmund", cached, {}, now=cache._parse_utc(cached["fetched_at"])
        )

        ready = cache.ready_state(state, [], today=date(2026, 10, 17))

        self.assertIn("CAMS", ready["attribution"])
        self.assertIn("Deutscher Wetterdienst", ready["attribution"])
        self.assertEqual(ready["days"][0]["pollen"]["source"], "DWD")


class AirQualityRecommendationTests(unittest.TestCase):
    @staticmethod
    def forecast(aqi_values):
        times = [f"2026-10-17T{hour:02d}:00" for hour in range(6, 22)]
        return {
            "hourly": {
                "time": times,
                "precipitation_probability": [0] * len(times),
                "apparent_temperature": [15] * len(times),
                "european_aqi": aqi_values(len(times)),
            }
        }

    def test_poor_air_quality_moves_window(self):
        # 2026-10-17 is a Saturday: polluted until 14:00, clean afterwards.
        forecast = self.forecast(lambda count: [90] * 8 + [10] * (count - 8))

        result = recommendations.weather_recommendation(EVENT, forecast)

        self.assertEqual(result["suggested_time"], "14:00–15:00 Uhr")
        self.assertEqual(result["european_aqi"], 10)
        self.assertNotIn("Luftqualität", result["reason"])

    def test_reason_names_poor_air_quality_when_unavoidable(self):
        result = recommendations.weather_recommendation(
            EVENT, self.forecast(lambda count: [70] * count)
        )

        self.assertIn("Luftqualität schlecht (AQI 70)", result["reason"])

    def test_unknown_air_quality_adds_no_field(self):
        result = recommendations.weather_recommendation(
            EVENT, self.forecast(lambda count: [None] * count)
        )

        self.assertNotIn("european_aqi", result)


if __name__ == "__main__":
    unittest.main()
