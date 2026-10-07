from __future__ import annotations

import unittest
from datetime import date

from backend.performance.garmin_metric_history import ftp_points, metric_points
from backend.providers.garmin import GarminCollectionOptions, collect_garmin_data

TODAY = date(2026, 10, 6)
START = date(2026, 7, 9)


class GarminHistoricMetricCollectorTests(unittest.TestCase):
    def test_endurance_score_dto_range_is_unwrapped(self):
        points = metric_points(
            {
                "enduranceScoreDTO": {
                    "calendarDate": "2026-10-05",
                    "overallScore": 712,
                    "timestamp": 123,
                }
            },
            start=START,
            end=TODAY,
        )
        self.assertEqual(points[0]["date"], "2026-10-05")
        self.assertEqual(
            points[0]["values"], {"overallScore": 712.0, "timestamp": 123.0}
        )

    def test_known_sdk_methods_get_bounded_dates_and_explicit_aggregation(self):
        calls = []

        class Client:
            def get_activities_by_date(self, *_args):
                return []

            def get_functional_threshold_power_range(self, start, end, **kwargs):
                calls.append(("ftp", start, end, kwargs))
                return []

            def get_endurance_score(self, start, end=None):
                calls.append(("endurance", start, end))
                return []

            def get_running_tolerance(self, start, end, aggregation="weekly"):
                calls.append(("tolerance", start, end, aggregation))
                return []

        result = collect_garmin_data(
            Client(),
            [(TODAY, TODAY)],
            start=TODAY,
            today=TODAY,
            synced_at="sync",
            external_call=lambda _service, _op, fn, _details: fn(),
            redact=str,
            options=GarminCollectionOptions(
                include_recovery=False,
                include_current_metrics=False,
                include_historic_metrics=True,
            ),
        )

        self.assertEqual(
            calls,
            [
                (
                    "ftp",
                    "2026-07-09",
                    "2026-10-06",
                    {"sport": "CYCLING", "aggregation": "daily"},
                ),
                ("endurance", "2026-07-09", "2026-10-06"),
                ("tolerance", "2026-07-09", "2026-10-06", "weekly"),
            ],
        )
        self.assertEqual(result["errors"], [])
        self.assertEqual(
            result["provider_sync"]["pagination"]["endurance_score"]["aggregation"],
            "weekly",
        )

    def test_missing_capabilities_are_explained_without_failing_other_sources(self):
        class Client:
            def get_activities_by_date(self, *_args):
                return []

        result = collect_garmin_data(
            Client(),
            [(TODAY, TODAY)],
            start=TODAY,
            today=TODAY,
            synced_at="sync",
            external_call=lambda _service, _op, fn, _details: fn(),
            redact=str,
            options=GarminCollectionOptions(
                include_recovery=False,
                include_current_metrics=False,
                include_historic_metrics=True,
            ),
        )
        for source in ("cycling_ftp_history", "endurance_score", "running_tolerance"):
            self.assertEqual(
                result["provider_sync"]["pagination"][source]["status"],
                "unsupported",
            )
        self.assertEqual(result["errors"], [])

    def test_one_optional_failure_does_not_suppress_other_metrics(self):
        class Client:
            def get_activities_by_date(self, *_args):
                return []

            def get_functional_threshold_power_range(self, *_args, **_kwargs):
                raise RuntimeError("synthetic FTP failure")

            def get_endurance_score(self, start, end=None):
                return {"date": end, "undocumentedMetric": 12}

            def get_running_tolerance(self, start, end, aggregation="weekly"):
                return []

        result = collect_garmin_data(
            Client(),
            [(TODAY, TODAY)],
            start=TODAY,
            today=TODAY,
            synced_at="sync",
            external_call=lambda _service, _op, fn, _details: fn(),
            redact=lambda _value: "redacted",
            options=GarminCollectionOptions(
                include_recovery=False,
                include_current_metrics=False,
                include_historic_metrics=True,
            ),
        )
        self.assertEqual(
            [item["source"] for item in result["errors"]], ["cycling_ftp_history"]
        )
        self.assertIn("endurance_score", result)
        self.assertIn("running_tolerance", result)

    def test_invalid_record_shape_isolated_as_capability_error(self):
        class Client:
            def get_activities_by_date(self, *_args):
                return []

            def get_functional_threshold_power_range(self, *_args, **_kwargs):
                return ["invalid"]

            def get_endurance_score(self, *_args):
                return []

            def get_running_tolerance(self, *_args, **_kwargs):
                return []

        result = collect_garmin_data(
            Client(),
            [(TODAY, TODAY)],
            start=TODAY,
            today=TODAY,
            synced_at="sync",
            external_call=lambda _service, _op, fn, _details: fn(),
            redact=str,
            options=GarminCollectionOptions(
                include_recovery=False,
                include_current_metrics=False,
                include_historic_metrics=True,
            ),
        )
        self.assertEqual(result["errors"][0]["source"], "cycling_ftp_history")
        self.assertFalse(
            result["provider_sync"]["pagination"]["cycling_ftp_history"]["complete"]
        )


class GarminHistoricMetricNormalizationTests(unittest.TestCase):
    def test_ftp_requires_known_field_dated_finite_bounded_non_future_values(self):
        points = ftp_points(
            [
                {"calendarDate": "2026-10-01", "functionalThresholdPower": 270},
                {"calendarDate": "2026-10-01", "functionalThresholdPower": 0},
                {"calendarDate": "2026-10-01", "value": 280},
                {"calendarDate": "2026-10-07", "functionalThresholdPower": 290},
                {"calendarDate": "not-date", "functionalThresholdPower": 260},
                {
                    "calendarDate": "2026-10-02",
                    "functionalThresholdPower": float("inf"),
                },
            ],
            start=START,
            end=TODAY,
        )
        self.assertEqual(
            points,
            [
                {
                    "date": "2026-10-01",
                    "value": 270,
                    "source": "Garmin Connect",
                    "field": "functionalThresholdPower",
                }
            ],
        )

    def test_generic_metrics_keep_field_names_unknown_and_deduplicate_dates(self):
        points = metric_points(
            [
                {"date": "2026-10-01", "mysteryA": 12.5, "mysteryB": "4"},
                {"date": "2026-10-01", "mysteryA": 14},
                {"date": "2026-10-07", "future": 3},
                {"date": "2026-10-02", "bad": float("nan")},
                {"date": "invalid", "undated": 8},
                {"mystery": 3},
            ],
            start=START,
            end=TODAY,
        )
        self.assertEqual(
            points,
            [
                {
                    "date": "2026-10-01",
                    "values": {"mysteryA": 14, "mysteryB": 4},
                    "source": "Garmin Connect",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
