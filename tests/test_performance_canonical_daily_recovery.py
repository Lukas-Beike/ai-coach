"""Per-day recovery reads from canonical observations (the planning view's source).

``read_daily_recovery`` reads each switched kind once over the inclusive window and
applies the daily source rule per day: Garmin before Intervals for sleep score and
resting HR, Intervals before Garmin for readiness. All data is synthetic.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from typing import Any

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.performance.canonical_recovery import (
    CanonicalDailyRecovery,
    read_daily_recovery,
)

DAY = "2026-09-20"
OTHER_DAY = "2026-09-21"
RETRIEVED = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
UNITS = {
    MetricKind.SLEEP_SCORE: "score",
    MetricKind.RESTING_HR: "bpm",
    MetricKind.READINESS: "score",
}


def _observation(
    kind: MetricKind, value: float, day: str, provider: ProviderId, record_id: str
) -> Observation:
    recorded_by = (
        RecordingOrigin.GARMIN
        if provider is ProviderId.GARMIN
        else RecordingOrigin.MANUAL
    )
    return Observation(
        kind=kind,
        value=MetricValue(value, UNITS[kind]),
        observed_on=date.fromisoformat(day),
        observed_at=None,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=record_id,
            recorded_by=recorded_by,
            retrieved_at=RETRIEVED,
            label=None,
        ),
    )


class _FakeReader:
    """Serves fixed observations per kind and records each read."""

    def __init__(self, by_kind: dict[MetricKind, list[Observation]]) -> None:
        self._by_kind = by_kind
        self.calls: list[tuple[MetricKind, date | None, date | None]] = []

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        self.calls.append((kind, start, end))
        return tuple(self._by_kind.get(kind, []))


class DailyRecoveryReadTests(unittest.TestCase):
    def test_each_kind_is_read_once_over_the_window(self) -> None:
        reader = _FakeReader({})
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
        reader = _FakeReader(
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
