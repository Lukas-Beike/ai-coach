"""Stored body-history days preserve provenance and read no load or rating kinds."""

import unittest
from datetime import UTC, date, datetime

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.performance.canonical_inputs import read_performance_inputs
from backend.performance.wellness_days import read_wellness_days

TODAY = date(2026, 10, 12)
SYNCED = datetime(2026, 10, 12, 8, tzinfo=UTC)


def observation(
    kind, day, value, *, sport=None, record=None, provider=ProviderId.INTERVALS
):
    return Observation(
        kind=kind,
        value=MetricValue(value, kind.unit),
        observed_on=day,
        observed_at=None,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=record or day.isoformat(),
            recorded_by=RecordingOrigin.UNKNOWN,
            retrieved_at=SYNCED,
            label=None,
        ),
        sport=sport,
    )


class Reader:
    def __init__(self, *observations):
        self.items = observations
        self.calls = []

    def observations(self, _db, kind, *, start=None, end=None, sport=None):
        self.calls.append(kind)
        return tuple(
            item
            for item in self.items
            if item.kind is kind
            and (start is None or start <= item.observed_on)
            and (end is None or item.observed_on <= end)
            and (sport is None or item.sport is sport)
        )


class WellnessDayTests(unittest.TestCase):
    def test_scopes_provider_and_provenance(self):
        weight = observation(MetricKind.WEIGHT, TODAY, 72)
        reader = Reader(
            weight,
            observation(MetricKind.WEIGHT, TODAY, 99, record="athlete"),
            observation(MetricKind.EFTP, TODAY, 250, sport=Sport.RUN),
            observation(MetricKind.WEIGHT, TODAY, 80, provider=ProviderId.GARMIN),
        )
        (day,) = read_wellness_days(reader, object())
        self.assertEqual(day.value(MetricKind.WEIGHT), 72)
        self.assertIs(day.observations[MetricKind.WEIGHT], weight)
        self.assertIsNone(day.value(MetricKind.EFTP))
        self.assertEqual(read_wellness_days(Reader(), object()), ())

    def test_load_and_rating_kinds_are_not_read(self):
        reader = Reader(
            observation(MetricKind.CTL, TODAY, 70),
            observation(MetricKind.FORM, TODAY, -4),
            observation(MetricKind.SUBJECTIVE_FATIGUE, TODAY, 3.0),
            observation(MetricKind.WEIGHT, TODAY, 70.5),
        )
        (day,) = read_wellness_days(reader, object())
        self.assertEqual(set(day.observations), {MetricKind.WEIGHT})
        self.assertNotIn(MetricKind.CTL, reader.calls)
        self.assertNotIn(MetricKind.FORM, reader.calls)

    def test_integral_values_serialise_like_the_former_rows(self):
        reader = Reader(observation(MetricKind.RESTING_HR, TODAY, 52.0))
        (day,) = read_wellness_days(reader, object())
        self.assertEqual(day.value(MetricKind.RESTING_HR), 52)
        self.assertIsInstance(day.value(MetricKind.RESTING_HR), int)

    def test_eftp_observations_feed_no_series(self):
        reader = Reader(
            observation(MetricKind.WEIGHT, TODAY, 72),
            observation(MetricKind.EFTP, TODAY, 250, sport=Sport.RIDE),
        )
        inputs = read_performance_inputs(reader, object(), as_of=TODAY)
        assert inputs is not None and inputs.history_wellness_days is not None
        self.assertNotIn(MetricKind.EFTP, reader.calls)
        self.assertFalse(hasattr(inputs, "eftp_by_day"))
        self.assertEqual([day.day for day in inputs.history_wellness_days], [TODAY])
        self.assertEqual(len(reader.calls), len(set(reader.calls)))


if __name__ == "__main__":
    unittest.main()
