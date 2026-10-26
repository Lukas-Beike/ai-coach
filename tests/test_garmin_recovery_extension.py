"""Garmin recovery extension: HRV metadata, stress, resting energy and Body Battery.

Synthetic Garmin sections only; no account, network or real data is used.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from backend.canonical.mapping import IssueReason
from backend.canonical.records import UNKNOWN_CONTEXT
from backend.canonical.vocabulary import (
    MetricKind,
    ObservationAggregation,
    SourceKind,
)
from backend.providers.garmin_health_mapping import map_garmin_health

ZONE = ZoneInfo("Europe/Berlin")
RETRIEVED_AT = datetime(2026, 10, 11, 6, 0, tzinfo=UTC)
DAY = "2026-10-10"


def _map(sections: object) -> list:
    return list(
        map_garmin_health(sections, zone=ZONE, retrieved_at=RETRIEVED_AT).records
    )


def _of(kind: MetricKind, sections: object) -> list:
    return [obs for obs in _map(sections) if obs.kind is kind]


class HrvMetadataTests(unittest.TestCase):
    def test_last_night_hrv_is_an_overnight_rmssd_mean_with_unknown_hardware(
        self,
    ) -> None:
        (hrv,) = _of(
            MetricKind.HRV_RMSSD,
            {"hrv": [{"calendarDate": DAY, "lastNightAvg": 61, "weeklyAvg": 58}]},
        )
        self.assertEqual(hrv.value.value, 61.0)
        self.assertEqual(hrv.method, "rmssd")
        self.assertIs(hrv.aggregation, ObservationAggregation.MEAN)
        context = hrv.provenance.context
        self.assertEqual(context.window, "overnight")
        self.assertIsNone(context.device_model)
        self.assertIsNone(context.firmware)
        self.assertIsNone(context.sensor)
        self.assertNotEqual(context.identity, UNKNOWN_CONTEXT.identity)
        self.assertIs(hrv.provenance.source_kind, SourceKind.DEVICE_MEASURED)

    def test_other_values_keep_an_unknown_context(self) -> None:
        (resting,) = _of(
            MetricKind.RESTING_HR,
            {"resting_hr": [{"calendarDate": DAY, "restingHeartRate": 48}]},
        )
        self.assertTrue(resting.provenance.context.is_unknown)
        self.assertIsNone(resting.method)


class StressTests(unittest.TestCase):
    def stress(self, record: dict) -> list:
        return _of(
            MetricKind.STRESS, {"daily_stats": [{"calendarDate": DAY, **record}]}
        )

    def test_flat_daily_mean_is_stored_on_the_provider_scale(self) -> None:
        (stress,) = self.stress({"averageStressLevel": 34})
        self.assertEqual(stress.value.value, 34.0)
        self.assertEqual(stress.observed_on.isoformat(), DAY)
        self.assertIs(stress.aggregation, ObservationAggregation.MEAN)
        self.assertIs(stress.provenance.source_kind, SourceKind.PROVIDER_REPORTED)

    def test_nested_range_value_is_read_and_a_flat_value_wins(self) -> None:
        (nested,) = self.stress({"stress": {"avgLevel": 27}})
        self.assertEqual(nested.value.value, 27.0)
        (flat,) = self.stress({"stress": {"avgLevel": 27}, "averageStressLevel": 30})
        self.assertEqual(flat.value.value, 30.0)

    def test_zero_is_a_measurement(self) -> None:
        (stress,) = self.stress({"averageStressLevel": 0})
        self.assertEqual(stress.value.value, 0.0)

    def test_missing_and_invalid_values_are_not_measurements(self) -> None:
        self.assertEqual(self.stress({"totalSteps": 10}), [])
        for value in (-1, -2, 101, "high"):
            with self.subTest(value=value):
                result = map_garmin_health(
                    {
                        "daily_stats": [
                            {"calendarDate": DAY, "averageStressLevel": value}
                        ]
                    },
                    zone=ZONE,
                    retrieved_at=RETRIEVED_AT,
                )
                self.assertEqual(
                    [o for o in result.records if o.kind is MetricKind.STRESS], []
                )
                self.assertTrue(result.issues)

    def test_subjective_stress_is_never_read(self) -> None:
        self.assertEqual(self.stress({"stress": 3, "stressLevel": 2}), [])


class RestingEnergyTests(unittest.TestCase):
    def test_reported_resting_energy_is_a_provider_total(self) -> None:
        (resting,) = _of(
            MetricKind.DAILY_ENERGY_RESTING,
            {"daily_stats": [{"calendarDate": DAY, "bmrKilocalories": 1750}]},
        )
        self.assertEqual(resting.value.value, 1750.0)
        self.assertIs(resting.aggregation, ObservationAggregation.TOTAL)
        self.assertIs(resting.provenance.source_kind, SourceKind.PROVIDER_REPORTED)

    def test_absent_resting_energy_is_not_estimated(self) -> None:
        self.assertEqual(
            _of(
                MetricKind.DAILY_ENERGY_RESTING,
                {
                    "daily_stats": [
                        {
                            "calendarDate": DAY,
                            "totalKilocalories": 2400,
                            "activeKilocalories": 600,
                        }
                    ]
                },
            ),
            [],
        )


class BodyBatteryTests(unittest.TestCase):
    def test_charged_and_drained_are_separate_daily_totals(self) -> None:
        records = _map(
            {"body_battery": [{"calendarDate": DAY, "charged": 72, "drained": 0}]}
        )
        self.assertEqual(
            sorted((o.kind.value, o.value.value) for o in records),
            [("body_battery_charged", 72.0), ("body_battery_drained", 0.0)],
        )
        for observation in records:
            self.assertIs(observation.aggregation, ObservationAggregation.TOTAL)

    def test_each_timed_level_is_a_sample_on_its_local_day(self) -> None:
        # 22:30 UTC on 2026-10-10 is 00:30 on 2026-10-11 in Berlin.
        late = int(datetime(2026, 10, 10, 22, 30, tzinfo=UTC).timestamp() * 1000)
        early = int(datetime(2026, 10, 10, 5, 0, tzinfo=UTC).timestamp() * 1000)
        levels = _of(
            MetricKind.BODY_BATTERY,
            {
                "body_battery": [
                    {
                        "calendarDate": DAY,
                        "bodyBatteryValuesArray": [[early, 81], [late, 24.6]],
                    }
                ]
            },
        )
        self.assertEqual(
            sorted(
                (o.observed_at.isoformat(), o.observed_on.isoformat(), o.value.value)
                for o in levels
            ),
            [
                ("2026-10-10T05:00:00+00:00", "2026-10-10", 81.0),
                ("2026-10-10T22:30:00+00:00", "2026-10-11", 25.0),
            ],
        )
        for level in levels:
            self.assertIs(level.aggregation, ObservationAggregation.SAMPLE)

    def test_out_of_range_levels_are_issues(self) -> None:
        moment = int(datetime(2026, 10, 10, 5, 0, tzinfo=UTC).timestamp() * 1000)
        result = map_garmin_health(
            {
                "body_battery": [
                    {"calendarDate": DAY, "bodyBatteryValuesArray": [[moment, 140]]}
                ]
            },
            zone=ZONE,
            retrieved_at=RETRIEVED_AT,
        )
        self.assertEqual(result.records, ())
        self.assertEqual(
            [issue.reason for issue in result.issues], [IssueReason.OUT_OF_RANGE]
        )

    def test_a_malformed_element_is_one_issue(self) -> None:
        for payload in (["junk"], "junk"):
            with self.subTest(payload=payload):
                result = map_garmin_health(
                    {"body_battery": payload}, zone=ZONE, retrieved_at=RETRIEVED_AT
                )
                self.assertEqual(
                    [issue.reason for issue in result.issues],
                    [IssueReason.INVALID_TYPE],
                )

    def test_a_sample_at_the_edge_of_the_datetime_range_is_an_issue(self) -> None:
        result = map_garmin_health(
            {
                "body_battery": [
                    {
                        "calendarDate": DAY,
                        "bodyBatteryValuesArray": [["9999-12-31T23:30:00-01:00", 40]],
                    }
                ]
            },
            zone=ZONE,
            retrieved_at=RETRIEVED_AT,
        )
        self.assertEqual(result.records, ())
        self.assertEqual(len(result.issues), 1)


if __name__ == "__main__":
    unittest.main()
