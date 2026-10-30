"""Canonical wellness days preserve provenance and ignore snapshot carriers."""

import json
import unittest
from datetime import UTC, date, datetime, timedelta

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.performance.canonical_inputs import read_performance_inputs
from backend.performance.wellness_days import (
    current_window,
    latest,
    read_wellness_days,
    series,
)

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
    def test_scopes_form_only_empty_and_provenance(self):
        form = observation(MetricKind.FORM, TODAY, -4)
        weight = observation(MetricKind.WEIGHT, TODAY, 72)
        reader = Reader(
            form,
            weight,
            observation(MetricKind.WEIGHT, TODAY, 99, record="athlete"),
            observation(MetricKind.EFTP, TODAY, 250, sport=Sport.RUN),
            observation(MetricKind.CTL, TODAY, 70, provider=ProviderId.GARMIN),
        )
        (day,) = read_wellness_days(reader, object())
        self.assertEqual(day.value(MetricKind.FORM), -4)
        self.assertEqual(day.value(MetricKind.WEIGHT), 72)
        self.assertIs(day.observations[MetricKind.WEIGHT], weight)
        self.assertIs(day.observations[MetricKind.FORM], form)
        self.assertIsNone(day.value(MetricKind.EFTP))
        self.assertIsNone(day.value(MetricKind.CTL))
        self.assertEqual(read_wellness_days(Reader(), object()), ())

    def test_integral_values_serialise_like_the_former_rows(self):
        reader = Reader(
            observation(MetricKind.SUBJECTIVE_FATIGUE, TODAY, 3.0),
            observation(MetricKind.WEIGHT, TODAY, 70.5),
        )
        (day,) = read_wellness_days(reader, object())
        self.assertEqual(
            '{"fatigue": 3, "weight": 70.5}',
            json.dumps(
                {
                    "fatigue": day.value(MetricKind.SUBJECTIVE_FATIGUE),
                    "weight": day.value(MetricKind.WEIGHT),
                }
            ),
        )

    def test_current_window_and_history(self):
        reader = Reader(
            observation(MetricKind.CTL, TODAY - timedelta(days=91), 1),
            observation(MetricKind.FORM, TODAY - timedelta(days=89), 2),
            observation(MetricKind.WEIGHT, TODAY, 72),
        )
        history = read_wellness_days(reader, object())
        current = current_window(history)
        self.assertEqual(len(history), 3)
        self.assertEqual(
            [item.day for item in current], [TODAY - timedelta(days=89), TODAY]
        )
        self.assertEqual(latest(current).day, TODAY)
        self.assertEqual(series(current, MetricKind.WEIGHT), {TODAY: 72})
        self.assertIsNone(latest(()))

    def test_contradicting_snapshot_rows_do_not_change_inputs(self):
        reader = Reader(
            observation(MetricKind.CTL, TODAY, 58.4),
            observation(MetricKind.ATL, TODAY, 40),
        )
        plain = read_performance_inputs(reader, object(), {}, as_of=TODAY)
        contradiction = read_performance_inputs(
            reader,
            object(),
            {
                "recent_wellness": [
                    {"id": TODAY.isoformat(), "ctl": 999, "atl": 999},
                    {"id": (TODAY + timedelta(days=1)).isoformat(), "ctl": 1000},
                ],
                "raw_provider_data": {
                    "wellness": [{"id": TODAY.isoformat(), "weight": 1}]
                },
            },
            as_of=TODAY,
        )
        self.assertEqual(plain, contradiction)
        self.assertEqual(contradiction.wellness_day, TODAY)

    def test_run_eftp_is_a_separate_sparse_series(self):
        yesterday = TODAY - timedelta(days=1)
        reader = Reader(
            observation(MetricKind.FORM, TODAY, -3),
            observation(MetricKind.EFTP, yesterday, 310, sport=Sport.RUN),
            observation(MetricKind.EFTP, TODAY, 250, sport=Sport.RIDE),
            observation(MetricKind.EFTP, TODAY, 999, sport=Sport.RUN, record="athlete"),
        )
        inputs = read_performance_inputs(reader, object(), {}, as_of=TODAY)
        assert inputs is not None and inputs.wellness_days is not None
        self.assertEqual(inputs.run_eftp_by_day, {yesterday: 310})
        self.assertEqual(inputs.eftp_by_day, {TODAY: 250})
        self.assertEqual([day.day for day in inputs.wellness_days], [TODAY])
        self.assertEqual(len(reader.calls), len(set(reader.calls)))


if __name__ == "__main__":
    unittest.main()
