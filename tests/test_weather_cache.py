import json
import math
import unittest
from datetime import date, datetime, timedelta, timezone

from backend.weather.cache import (
    cache_state,
    failure_record,
    ready_state,
    retry_wait,
    unavailable_state,
)


class WeatherCacheTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)

    def cached_value(self, *, fetched_at="2026-09-20T11:00:00Z", **overrides):
        value = {
            "query": "Berlin",
            "forecast": {"daily": {"time": ["2026-09-20"]}},
            "fetched_at": fetched_at,
            "model": "icon",
            "location": {"name": "Berlin"},
        }
        value.update(overrides)
        return json.dumps(value)

    def test_invalid_json_and_types_are_empty_records(self):
        for cached, failure in (("{", "not json"), ([], object()), ("null", "[]")):
            with self.subTest(cached=cached, failure=failure):
                state = cache_state("Berlin", cached, failure, now=self.now)
                self.assertEqual(state.cached, {})
                self.assertEqual(state.failure, {})
                self.assertEqual(state.previous_failure_count, 0)
                self.assertFalse(state.cache_matches)
                self.assertTrue(math.isinf(state.cache_age))

    def test_cache_requires_same_query_and_dict_forecast(self):
        mismatch = cache_state("Hamburg", self.cached_value(), "", now=self.now)
        invalid_forecast = cache_state(
            "Berlin",
            self.cached_value(forecast=[]),
            "",
            now=self.now,
        )
        self.assertFalse(mismatch.cache_matches)
        self.assertFalse(invalid_forecast.cache_matches)

    def test_freshness_boundary_and_utc_z_timestamp(self):
        state = cache_state(
            "Berlin",
            self.cached_value(fetched_at="2026-09-20T09:00:00Z"),
            "",
            now=self.now,
        )
        self.assertTrue(state.cache_matches)
        self.assertEqual(state.cache_age, 10800)
        self.assertEqual(state.error, "Wetterdaten sind veraltet.")

        fresh = cache_state(
            "Berlin", self.cached_value(), "", now=self.now, cache_seconds=10801
        )
        self.assertIsNone(fresh.error)

    def test_failure_makes_matching_cache_stale_and_count_is_nonnegative(self):
        state = cache_state(
            "Berlin",
            self.cached_value(),
            '{"count": -4, "retry_at": "invalid"}',
            now=self.now,
        )
        self.assertTrue(state.cache_matches)
        self.assertEqual(state.previous_failure_count, 0)
        self.assertEqual(state.error, "Wetterdaten sind veraltet.")

    def test_retry_wait_parses_z_and_returns_remaining_seconds(self):
        failure = {"retry_at": "2026-09-20T12:15:00Z"}
        self.assertEqual(retry_wait(failure, now=self.now), 900)
        self.assertEqual(
            retry_wait(failure, now=self.now + timedelta(minutes=20)), -300
        )
        self.assertEqual(retry_wait({}, now=self.now), 0)

    def test_failure_delay_caps_at_six_hours(self):
        record = failure_record(6, now=self.now)
        self.assertEqual(record["count"], 7)
        self.assertEqual(record["failed_at"], self.now.isoformat())
        self.assertEqual(retry_wait(record, now=self.now), 21600)
        self.assertEqual(failure_record(-10, now=self.now)["count"], 1)

    def test_unavailable_state_loading_and_error_messages(self):
        self.assertEqual(
            unavailable_state(False, "ignored"),
            {
                "configured": True,
                "state": "loading",
                "provider": "Open-Meteo",
                "days": [],
                "recommendations": [],
                "loading": True,
                "message": "Wetterdaten werden nachgeladen.",
            },
        )
        error = unavailable_state(True, None)
        self.assertEqual(error["state"], "error")
        self.assertEqual(error["error"], "Wetterdaten sind nicht verfügbar.")
        self.assertEqual(unavailable_state(True, "Fehler")["error"], "Fehler")

    def test_ready_stale_and_refreshed_projection(self):
        state = cache_state("Berlin", self.cached_value(), "", now=self.now)
        planned = [{"name": "Easy run", "date": "2026-09-20"}]
        original_planned = [dict(item) for item in planned]
        ready = ready_state(state, planned, today=date(2026, 9, 20))
        self.assertEqual(ready["state"], "ready")
        self.assertEqual(ready["provider"], "Open-Meteo")
        self.assertEqual(
            ready["attribution"], "Wetterdaten: Open-Meteo.com (CC BY 4.0)"
        )
        self.assertEqual(ready["model"], "icon")
        self.assertEqual(ready["location"], {"name": "Berlin"})
        self.assertEqual(ready["fetched_at"], "2026-09-20T11:00:00Z")
        self.assertEqual(ready["days"][0]["date"], "2026-09-20")
        self.assertEqual(ready["recommendations"], [])
        self.assertNotIn("_refreshed", ready)
        self.assertEqual(planned, original_planned)

        state.error = "Wetterdaten sind veraltet."
        state.refreshed = True
        stale = ready_state(state, planned, today=date(2026, 9, 20))
        self.assertEqual(stale["state"], "stale")
        self.assertTrue(stale["stale"])
        self.assertEqual(stale["error"], "Wetterdaten sind veraltet.")
        self.assertTrue(stale["_refreshed"])


if __name__ == "__main__":
    unittest.main()
