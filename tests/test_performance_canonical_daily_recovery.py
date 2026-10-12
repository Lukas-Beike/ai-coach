"""Per-day recovery reads from canonical observations (the planning view's source).

``read_daily_recovery`` reads each switched kind once over the inclusive window and
applies the daily source rule per day: Garmin before Intervals for sleep score and
resting HR, Intervals before Garmin for readiness. All data is synthetic.
"""

from __future__ import annotations

import unittest
from datetime import date

from canonical_recovery_support import RecordingReader
from canonical_recovery_support import recovery_observation as _observation

from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance.canonical_recovery import (
    CanonicalDailyRecovery,
    read_daily_recovery,
)

DAY = "2026-09-20"
OTHER_DAY = "2026-09-21"


class DailyRecoveryReadTests(unittest.TestCase):
    def test_each_kind_is_read_once_over_the_window(self) -> None:
        reader = RecordingReader({})
        result = read_daily_recovery(
            reader,
            "db",
            start=date(2026, 9, 20),
            end=date(2026, 9, 21),
        )
        window = (date(2026, 9, 20), date(2026, 9, 21))
        self.assertEqual(
            reader.calls,
            [
                (MetricKind.SLEEP_SCORE, *window),
                (MetricKind.RESTING_HR, *window),
                (MetricKind.READINESS, *window),
            ],
        )
        self.assertEqual(
            result,
            CanonicalDailyRecovery(sleep_score={}, resting_hr={}, readiness={}),
        )

    def test_daily_rules_pick_one_observation_per_day(self) -> None:
        reader = RecordingReader(
            {
                MetricKind.SLEEP_SCORE: [
                    _observation(
                        MetricKind.SLEEP_SCORE, 80, DAY, ProviderId.INTERVALS, "w1"
                    ),
                    _observation(
                        MetricKind.SLEEP_SCORE, 84, DAY, ProviderId.GARMIN, "g1"
                    ),
                ],
                MetricKind.READINESS: [
                    _observation(
                        MetricKind.READINESS, 70, DAY, ProviderId.GARMIN, "g2"
                    ),
                    _observation(
                        MetricKind.READINESS, 74, DAY, ProviderId.INTERVALS, "w2"
                    ),
                    _observation(
                        MetricKind.READINESS, 66, OTHER_DAY, ProviderId.GARMIN, "g3"
                    ),
                ],
                MetricKind.RESTING_HR: [
                    _observation(
                        MetricKind.RESTING_HR, 49, OTHER_DAY, ProviderId.INTERVALS, "w3"
                    ),
                ],
            }
        )
        result = read_daily_recovery(
            reader, "db", start=date(2026, 9, 20), end=date(2026, 9, 21)
        )
        self.assertEqual(
            {day: obs.value.value for day, obs in result.sleep_score.items()},
            {DAY: 84},
        )
        self.assertEqual(
            {day: obs.value.value for day, obs in result.readiness.items()},
            {DAY: 74, OTHER_DAY: 66},
        )
        self.assertEqual(
            {day: obs.value.value for day, obs in result.resting_hr.items()},
            {OTHER_DAY: 49},
        )

    def test_by_field_maps_each_planning_field_to_its_day_map(self) -> None:
        sleep = {
            DAY: _observation(MetricKind.SLEEP_SCORE, 84, DAY, ProviderId.GARMIN, "s")
        }
        resting = {
            DAY: _observation(MetricKind.RESTING_HR, 49, DAY, ProviderId.GARMIN, "r")
        }
        readiness = {
            DAY: _observation(MetricKind.READINESS, 74, DAY, ProviderId.INTERVALS, "d")
        }
        result = CanonicalDailyRecovery(
            sleep_score=sleep, resting_hr=resting, readiness=readiness
        )
        self.assertEqual(
            result.by_field(),
            {"sleep_score": sleep, "resting_hr": resting, "readiness": readiness},
        )


if __name__ == "__main__":
    unittest.main()
