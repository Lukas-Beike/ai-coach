"""Seven-day ln(RMSSD) comparison, card M2 version 4 (#1772)."""

import math
import unittest
from dataclasses import replace
from datetime import date, timedelta

from canonical_recovery_support import mapped_personal_recovery, mapped_recovery_inputs

from backend.canonical.records import MeasurementContext
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance.personal_recovery import personal_recovery
from backend.performance.rolling_hrv import rolling_lnrmssd

TODAY = date(2026, 10, 2)
# Baseline ln(RMSSD): mean 4.05, sample SD 0.16 over 30 nights.
SPREAD = 0.16 * math.sqrt(29 / 30)
BASELINE = [math.exp(4.05 + (SPREAD if night % 2 else -SPREAD)) for night in range(30)]


def day(offset: int) -> str:
    return (TODAY - timedelta(days=offset)).isoformat()


def series(window: dict[int, float], baseline=BASELINE) -> dict[str, float]:
    """Return nights keyed by day: ``window`` by age, ``baseline`` from day 7 on."""
    records = {day(7 + index): value for index, value in enumerate(baseline)}
    records.update({day(age): value for age, value in window.items()})
    return records


WORKED = {0: 52, 1: 48, 2: 61, 3: 45, 4: 55}


class RollingLnRmssdTests(unittest.TestCase):
    def test_worked_example_below_the_range(self):
        result = rolling_lnrmssd(
            series(WORKED), day(0), current=True, segment_start=None
        )
        self.assertEqual(
            {
                "method": "rolling-lnrmssd-v1",
                "status": "ok",
                "window_days": 7,
                "window_nights": 5,
                "baseline_days": 42,
                "baseline_nights": 30,
                "mean_ms": 51.9,
                "lower_ms": 53.0,
                "upper_ms": 62.2,
                "position": "below",
                "cv_pct": 3.0,
            },
            result,
        )

    def test_inside_and_above_the_range(self):
        inside = rolling_lnrmssd(
            series({0: 57, 2: 58, 4: 56, 5: 57, 6: 59}),
            day(0),
            current=True,
            segment_start=None,
        )
        above = rolling_lnrmssd(
            series({0: 70, 1: 66, 3: 72}), day(0), current=True, segment_start=None
        )
        self.assertEqual(("ok", "within"), (inside["status"], inside["position"]))
        self.assertEqual(
            ("provisional", "above", 3),
            (above["status"], above["position"], above["window_nights"]),
        )

    def test_too_few_nights(self):
        two = rolling_lnrmssd(
            series({0: 52, 5: 50}), day(0), current=True, segment_start=None
        )
        self.assertEqual(
            (
                "insufficient_data",
                2,
                "Mindestens 3 Nächte in den letzten 7 Tagen erforderlich.",
            ),
            (two["status"], two["window_nights"], two["reason"]),
        )
        self.assertNotIn("mean_ms", two)
        short = rolling_lnrmssd(
            series(WORKED, BASELINE[:13]), day(0), current=True, segment_start=None
        )
        self.assertEqual(
            (
                "insufficient_data",
                13,
                "Mindestens 14 frühere passende Nächte vor den letzten 7 Tagen erforderlich.",
            ),
            (short["status"], short["baseline_nights"], short["reason"]),
        )
        provisional = rolling_lnrmssd(
            series(WORKED, BASELINE[:14]), day(0), current=True, segment_start=None
        )
        self.assertEqual("provisional", provisional["status"])

    def test_baseline_ends_before_the_window_and_spans_42_days(self):
        records = series(WORKED, [55.0] * 60)
        result = rolling_lnrmssd(records, day(0), current=True, segment_start=None)
        self.assertEqual(42, result["baseline_nights"])

    def test_segment_restart_and_stale_value(self):
        restarted = rolling_lnrmssd(
            series(WORKED), day(0), current=True, segment_start=day(10)
        )
        self.assertEqual(
            (
                "insufficient_data",
                5,
                4,
                (
                    "Messkontext geändert; mindestens 14 passende Nächte vor den "
                    "letzten 7 Tagen seitdem erforderlich."
                ),
            ),
            (
                restarted["status"],
                restarted["window_nights"],
                restarted["baseline_nights"],
                restarted["reason"],
            ),
        )
        window_only = rolling_lnrmssd(
            series(WORKED), day(0), current=True, segment_start=day(2)
        )
        self.assertEqual(3, window_only["window_nights"])
        stale = rolling_lnrmssd(
            series(WORKED), day(0), current=False, segment_start=None
        )
        self.assertEqual(
            ("insufficient_data", "Messung veraltet."),
            (stale["status"], stale["reason"]),
        )


class PersonalRecoveryRollingTests(unittest.TestCase):
    def garmin_inputs(self, records: dict[str, float]):
        return mapped_recovery_inputs(
            {
                "hrv": [
                    {"calendarDate": key, "lastNightAvg": value}
                    for key, value in records.items()
                ]
            },
            [],
        )

    def hrv_row(self, inputs):
        (row,) = [
            row
            for row in personal_recovery({}, TODAY, canonical=inputs)["baselines"]
            if row["metric"] == "hrv"
        ]
        return row

    def test_garmin_rmssd_carries_the_rolling_comparison(self):
        row = self.hrv_row(self.garmin_inputs(series(WORKED)))
        self.assertEqual(
            ("rolling-lnrmssd-v1", 51.9, "below"),
            (
                row["rolling"]["method"],
                row["rolling"]["mean_ms"],
                row["rolling"]["position"],
            ),
        )

    def test_a_device_change_restarts_the_rolling_baseline(self):
        inputs = self.garmin_inputs(series(WORKED))
        device = MeasurementContext(device_model="Forerunner 965", window="overnight")
        changed = []
        for observation in inputs.of(MetricKind.HRV_RMSSD):
            if (TODAY - observation.observed_on).days <= 10:
                provenance = replace(observation.provenance, context=device)
                observation = replace(observation, provenance=provenance)
            changed.append(observation)
        inputs = replace(
            inputs,
            observations={**inputs.observations, MetricKind.HRV_RMSSD: tuple(changed)},
        )
        rolling = self.hrv_row(inputs)["rolling"]
        self.assertEqual((5, 4), (rolling["window_nights"], rolling["baseline_nights"]))
        self.assertEqual("insufficient_data", rolling["status"])

    def test_intervals_series_has_no_rolling_comparison(self):
        rows = [
            {"id": day(age), "sleepSecs": 7 * 3600, "restingHR": 50, "hrv": 40}
            for age in range(31)
        ]
        result = mapped_personal_recovery(rows, {}, {}, TODAY)
        for row in result["baselines"]:
            self.assertEqual(ProviderId.INTERVALS.value, row["source_provider"])
            self.assertNotIn("rolling", row)


if __name__ == "__main__":
    unittest.main()
