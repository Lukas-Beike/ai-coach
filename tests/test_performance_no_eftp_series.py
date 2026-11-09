"""The performance inputs read no eFTP series."""

import unittest
from datetime import UTC, date, datetime

from canonical_recovery_support import NoActivityRows

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.performance.canonical_inputs import read_performance_inputs

TODAY = date(2026, 10, 12)
SYNCED = datetime(2026, 10, 12, 8, tzinfo=UTC)


def observation(kind, day, value, *, sport=None):
    return Observation(
        kind=kind,
        value=MetricValue(value, kind.unit),
        observed_on=day,
        observed_at=None,
        provenance=Provenance(
            provider=ProviderId.INTERVALS,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=day.isoformat(),
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


class NoEftpSeriesTests(unittest.TestCase):
    def test_eftp_observations_feed_no_series(self):
        reader = Reader(
            observation(MetricKind.WEIGHT, TODAY, 72),
            observation(MetricKind.EFTP, TODAY, 250, sport=Sport.RIDE),
        )
        inputs = read_performance_inputs(
            reader, object(), activity_reader=NoActivityRows(), as_of=TODAY
        )
        assert inputs is not None
        self.assertNotIn(MetricKind.EFTP, reader.calls)
        self.assertFalse(hasattr(inputs, "eftp_by_day"))
        self.assertEqual(len(reader.calls), len(set(reader.calls)))


if __name__ == "__main__":
    unittest.main()
