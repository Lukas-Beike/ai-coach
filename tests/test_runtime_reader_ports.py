"""Canonical reader protocols, exercised through in-memory fake implementations."""

from __future__ import annotations

import inspect
import unittest
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from backend.canonical.coverage import MetricWindow, ProviderCoverage
from backend.canonical.local_time import local_date
from backend.canonical.mapping import IssueReason
from backend.canonical.records import (
    ActivityRecord,
    MetricValue,
    Observation,
    Provenance,
)
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.runtime.ports import (
    ActivityReader,
    ObservationReader,
    ProviderCoverageReader,
)

FAKE_DB: Any = object()
FAKE_RETRIEVED_AT = datetime(2026, 5, 1, 6, 0, tzinfo=UTC)


def make_provenance(record_id: str) -> Provenance:
    return Provenance(
        provider=ProviderId.INTERVALS,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=record_id,
        recorded_by=RecordingOrigin.UNKNOWN,
        retrieved_at=FAKE_RETRIEVED_AT,
        label=None,
    )


ATHLETE_ZONE = timezone(timedelta(hours=-5))


def make_activity(activity_id: str, started_at: datetime) -> ActivityRecord:
    return ActivityRecord(
        activity_id=activity_id,
        provenance=make_provenance(activity_id),
        sport=Sport.RIDE,
        environment=Environment.OUTDOOR,
        started_at=started_at,
        duration_s=3600.0,
        distance_m=None,
        load=None,
        load_model=LoadModel.UNKNOWN,
        avg_hr=None,
        avg_power=None,
        name=None,
    )


def make_observation(observed_on: date, sport: Sport | None) -> Observation:
    return Observation(
        kind=MetricKind.WEIGHT,
        value=MetricValue(72.5, MetricKind.WEIGHT.unit),
        observed_on=observed_on,
        observed_at=None,
        provenance=make_provenance(observed_on.isoformat()),
        sport=sport,
    )


def within(day: date, start: date | None, end: date | None) -> bool:
    return (start is None or day >= start) and (end is None or day <= end)


class FakeActivityReader:
    def __init__(self, activities: tuple[ActivityRecord, ...]) -> None:
        self._activities = activities

    def activities(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[ActivityRecord, ...]:
        return tuple(
            activity
            for activity in self._activities
            if within(local_date(activity.started_at, ATHLETE_ZONE), start, end)
        )


class FakeObservationReader:
    def __init__(self, observations: tuple[Observation, ...]) -> None:
        self._observations = observations

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        return tuple(
            observation
            for observation in self._observations
            if observation.kind is kind
            and within(observation.observed_on, start, end)
            and (sport is None or observation.sport is sport)
        )


class FakeProviderCoverageReader:
    def coverage(self, db: Any) -> tuple[ProviderCoverage, ...]:
        return (
            ProviderCoverage(
                provider=ProviderId.INTERVALS,
                retrieved_at=FAKE_RETRIEVED_AT,
                activity_count=1,
                observation_count=0,
                issue_counts={IssueReason.INVALID_NUMBER: 2},
                first_observed_on=None,
                last_observed_on=None,
            ),
        )

    def metric_windows(self, db: Any) -> tuple[MetricWindow, ...]:
        return ()


class ActivityReaderPortTests(unittest.TestCase):
    def setUp(self) -> None:
        self.activities = (
            make_activity("fake-activity-1", datetime(2026, 3, 1, 12, tzinfo=UTC)),
            make_activity("fake-activity-2", datetime(2026, 3, 10, 12, tzinfo=UTC)),
            make_activity("fake-activity-3", datetime(2026, 3, 20, 12, tzinfo=UTC)),
        )
        reader: ActivityReader = FakeActivityReader(self.activities)
        self.reader = reader

    def test_unbounded_read_returns_every_record_as_a_tuple(self) -> None:
        result = self.reader.activities(FAKE_DB)

        self.assertIsInstance(result, tuple)
        self.assertEqual(self.activities, result)

    def test_bounds_use_the_athlete_local_date_not_the_utc_date(self) -> None:
        # 02:30 UTC on 11 March is 21:30 on 10 March at UTC-5.
        late = make_activity(
            "fake-activity-late", datetime(2026, 3, 11, 2, 30, tzinfo=UTC)
        )
        reader: ActivityReader = FakeActivityReader((late,))

        self.assertEqual(1, len(reader.activities(FAKE_DB, end=date(2026, 3, 10))))
        self.assertEqual((), reader.activities(FAKE_DB, start=date(2026, 3, 11)))

    def test_bounds_are_inclusive_on_the_local_start_date(self) -> None:
        result = self.reader.activities(
            FAKE_DB, start=date(2026, 3, 10), end=date(2026, 3, 20)
        )

        self.assertEqual(
            ("fake-activity-2", "fake-activity-3"),
            tuple(activity.activity_id for activity in result),
        )

    def test_open_ended_bounds_apply_independently(self) -> None:
        from_start = self.reader.activities(FAKE_DB, start=date(2026, 3, 10))
        until_end = self.reader.activities(FAKE_DB, end=date(2026, 3, 10))

        self.assertEqual(2, len(from_start))
        self.assertEqual(2, len(until_end))


class ObservationReaderPortTests(unittest.TestCase):
    def setUp(self) -> None:
        observations = (
            make_observation(date(2026, 4, 1), None),
            make_observation(date(2026, 4, 2), Sport.RUN),
            make_observation(date(2026, 4, 3), Sport.RIDE),
        )
        reader: ObservationReader = FakeObservationReader(observations)
        self.reader = reader

    def test_filters_by_kind_with_inclusive_observed_on_bounds(self) -> None:
        result = self.reader.observations(
            FAKE_DB,
            MetricKind.WEIGHT,
            start=date(2026, 4, 2),
            end=date(2026, 4, 3),
        )

        self.assertEqual(2, len(result))
        self.assertTrue(all(isinstance(item, Observation) for item in result))

    def test_sport_restricts_results_when_given(self) -> None:
        result = self.reader.observations(FAKE_DB, MetricKind.WEIGHT, sport=Sport.RUN)

        self.assertEqual((Sport.RUN,), tuple(item.sport for item in result))

    def test_unknown_kind_yields_no_results(self) -> None:
        self.assertEqual((), self.reader.observations(FAKE_DB, MetricKind.FTP))


class ProviderCoverageReaderPortTests(unittest.TestCase):
    def test_reports_counts_without_exposing_issue_details(self) -> None:
        reader: ProviderCoverageReader = FakeProviderCoverageReader()

        coverage = reader.coverage(FAKE_DB)

        self.assertIsInstance(coverage, tuple)
        self.assertEqual(1, len(coverage))
        self.assertEqual(2, coverage[0].issue_counts[IssueReason.INVALID_NUMBER])

    def test_metric_windows_hold_counts_and_days_only(self) -> None:
        reader: ProviderCoverageReader = FakeProviderCoverageReader()

        self.assertEqual((), reader.metric_windows(FAKE_DB))


class PortSignatureTests(unittest.TestCase):
    """Pin public parameter names so readers and fakes cannot drift apart."""

    def test_activity_reader_signature(self) -> None:
        self.assertEqual(
            ["self", "db", "start", "end"],
            list(inspect.signature(ActivityReader.activities).parameters),
        )

    def test_activity_reader_bounds_are_keyword_only(self) -> None:
        parameters = inspect.signature(ActivityReader.activities).parameters

        self.assertEqual(
            [
                inspect.Parameter.KEYWORD_ONLY,
                inspect.Parameter.KEYWORD_ONLY,
            ],
            [parameters["start"].kind, parameters["end"].kind],
        )

    def test_observation_reader_signature(self) -> None:
        parameters = inspect.signature(ObservationReader.observations).parameters

        self.assertEqual(
            ["self", "db", "kind", "start", "end", "sport"],
            list(parameters),
        )
        self.assertEqual(
            [inspect.Parameter.KEYWORD_ONLY] * 3,
            [parameters[name].kind for name in ("start", "end", "sport")],
        )

    def test_coverage_reader_signature(self) -> None:
        self.assertEqual(
            ["self", "db"],
            list(inspect.signature(ProviderCoverageReader.coverage).parameters),
        )

    def test_metric_windows_signature(self) -> None:
        self.assertEqual(
            ["self", "db"],
            list(inspect.signature(ProviderCoverageReader.metric_windows).parameters),
        )


if __name__ == "__main__":
    unittest.main()
