"""Season-preparation ATL read from canonical observations.

The scenario keeps the legacy value unless the canonical ATL is the record the
legacy reader picked and carries the same number, so the scenario output stays
byte-identical. A populated temporary database is the end-to-end check. Every
provider is mocked by fixtures and all storage is temporary.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime, timedelta
from typing import Any

from canonical_read_support import CanonicalReadFixture, make_selector, populate

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.performance.canonical_inputs import CanonicalPerformanceSource
from backend.performance.canonical_season_load import (
    CanonicalSeasonLoad,
    matched_atl,
    read_season_load,
    season_load_options,
    snapshot_with_season_load,
)
from backend.performance.report_service import TrainingReportReadService
from backend.planning.season_preparation import load_scenarios

TODAY = date(2026, 10, 11)
BASIS = date(2026, 10, 10)
VALUES = {"end": "2026-10-20"}
RETRIEVED = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
LABEL = "Intervals.icu recorded wellness"


def _atl(
    value: float, day: date = BASIS, provider: ProviderId = ProviderId.INTERVALS
) -> Observation:
    recorded_by = (
        RecordingOrigin.GARMIN
        if provider is ProviderId.GARMIN
        else RecordingOrigin.MANUAL
    )
    return Observation(
        kind=MetricKind.ATL,
        value=MetricValue(value, "load"),
        observed_on=day,
        observed_at=None,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=day.isoformat(),
            recorded_by=recorded_by,
            retrieved_at=RETRIEVED,
            label=None,
        ),
    )


def _row(day: date, atl: float | None) -> dict[str, Any]:
    row: dict[str, Any] = {"id": day.isoformat(), "ctl": 53.4}
    if atl is not None:
        row["atl"] = atl
    return row


def _snapshot(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"synced_at": "2026-10-11T06:00:00+00:00", "recent_wellness": list(rows)}


def _dump(value: Any) -> str:
    return json.dumps(value, default=str)


class _FakeReader:
    """Serves fixed ATL observations and records each read."""

    def __init__(self, observations: tuple[Observation, ...]) -> None:
        self._observations = observations
        self.calls: list[
            tuple[Any, MetricKind, date | None, date | None, Sport | None]
        ] = []

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        self.calls.append((db, kind, start, end, sport))
        return self._observations


class _FakeDatabase:
    """Stands in for DatabaseManager and records the units of work it opens."""

    def __init__(self) -> None:
        self.opened = 0

    def unit_of_work(self) -> _FakeDatabase:
        return self

    def __enter__(self) -> str:
        self.opened += 1
        return "db"

    def __exit__(self, *exc: object) -> None:
        return None


class SeasonLoadOptionsTests(unittest.TestCase):
    def test_absent_canonical_keeps_the_legacy_call_shape(self) -> None:
        self.assertEqual(season_load_options(None), {})
        canonical = CanonicalSeasonLoad(basis_day=BASIS, atl=None)
        self.assertEqual(season_load_options(canonical), {"canonical": canonical})


class ReadSeasonLoadTests(unittest.TestCase):
    def test_reads_atl_for_the_basis_day_only(self) -> None:
        reader = _FakeReader(())
        loaded = read_season_load(reader, "db", basis_day=BASIS)
        self.assertEqual(reader.calls, [("db", MetricKind.ATL, BASIS, BASIS, None)])
        self.assertEqual(loaded, CanonicalSeasonLoad(basis_day=BASIS, atl=None))

    def test_selects_the_first_intervals_record_of_the_day(self) -> None:
        first, second = _atl(57.0), _atl(60.0)
        loaded = read_season_load(_FakeReader((first, second)), "db", basis_day=BASIS)
        self.assertIs(loaded.atl, first)


class SnapshotWithSeasonLoadTests(unittest.TestCase):
    def test_without_a_source_the_snapshot_is_read_as_before(self) -> None:
        snapshot = _snapshot(_row(BASIS, 57.0))
        read = []

        def read_snapshot() -> dict[str, Any]:
            read.append(True)
            return snapshot

        served, canonical = snapshot_with_season_load(None, read_snapshot, BASIS)
        self.assertIs(served, snapshot)
        self.assertIsNone(canonical)
        self.assertEqual(read, [True])

    def test_with_a_source_the_snapshot_and_atl_share_one_unit_of_work(self) -> None:
        database = _FakeDatabase()
        source = CanonicalPerformanceSource(
            lambda: database, lambda: _FakeReader((_atl(57.0),))
        )
        snapshot = _snapshot(_row(BASIS, 57.0))
        served, canonical = snapshot_with_season_load(source, lambda: snapshot, BASIS)
        self.assertIs(served, snapshot)
        self.assertEqual(database.opened, 1)
        assert canonical is not None
        self.assertEqual(canonical.basis_day, BASIS)
        self.assertEqual(canonical.atl, _atl(57.0))


class MatchedAtlTests(unittest.TestCase):
    def test_absent_canonical_never_matches(self) -> None:
        self.assertIsNone(matched_atl(None, 57.0))

    def test_missing_canonical_or_legacy_value_never_matches(self) -> None:
        canonical = CanonicalSeasonLoad(basis_day=BASIS, atl=_atl(57.0))
        self.assertIsNone(matched_atl(CanonicalSeasonLoad(BASIS, None), 57.0))
        self.assertIsNone(matched_atl(canonical, None))

    def test_other_provider_never_matches(self) -> None:
        observation = _atl(57.0, provider=ProviderId.GARMIN)
        self.assertIsNone(matched_atl(CanonicalSeasonLoad(BASIS, observation), 57.0))

    def test_other_day_never_matches(self) -> None:
        observation = _atl(57.0, day=BASIS - timedelta(days=1))
        self.assertIsNone(matched_atl(CanonicalSeasonLoad(BASIS, observation), 57.0))

    def test_different_number_never_matches(self) -> None:
        observation = _atl(56.0)
        self.assertIsNone(matched_atl(CanonicalSeasonLoad(BASIS, observation), 57.0))

    def test_same_record_and_number_matches(self) -> None:
        observation = _atl(57.0)
        self.assertIs(
            matched_atl(CanonicalSeasonLoad(BASIS, observation), 57.0), observation
        )


class LoadScenariosParityTests(unittest.TestCase):
    def test_matching_canonical_atl_keeps_the_legacy_output(self) -> None:
        snapshot = _snapshot(_row(BASIS, 57.0))
        canonical = CanonicalSeasonLoad(basis_day=BASIS, atl=_atl(57.0))
        legacy = load_scenarios(snapshot, {}, TODAY, VALUES)
        served = load_scenarios(snapshot, {}, TODAY, VALUES, canonical=canonical)
        self.assertEqual(_dump(served), _dump(legacy))
        self.assertEqual(served["basis"]["atl"], 57.0)
        self.assertEqual(served["basis"]["source"], LABEL)

    def test_canonical_mismatch_keeps_the_legacy_output(self) -> None:
        snapshot = _snapshot(_row(BASIS, 57.0))
        canonical = CanonicalSeasonLoad(basis_day=BASIS, atl=_atl(50.0))
        legacy = load_scenarios(snapshot, {}, TODAY, VALUES)
        served = load_scenarios(snapshot, {}, TODAY, VALUES, canonical=canonical)
        self.assertEqual(_dump(served), _dump(legacy))
        self.assertEqual(served["basis"]["atl"], 57.0)

    def test_other_day_or_garmin_canonical_atl_keeps_the_legacy_output(self) -> None:
        snapshot = _snapshot(_row(BASIS, 57.0))
        legacy = _dump(load_scenarios(snapshot, {}, TODAY, VALUES))
        for observation in (
            _atl(57.0, day=BASIS - timedelta(days=1)),
            _atl(57.0, provider=ProviderId.GARMIN),
        ):
            with self.subTest(observation=observation.provenance.provider):
                canonical = CanonicalSeasonLoad(basis_day=BASIS, atl=observation)
                served = load_scenarios(
                    snapshot, {}, TODAY, VALUES, canonical=canonical
                )
                self.assertEqual(_dump(served), legacy)

    def test_missing_legacy_atl_stays_insufficient_data(self) -> None:
        snapshot = _snapshot(_row(BASIS, None))
        canonical = CanonicalSeasonLoad(basis_day=BASIS, atl=_atl(57.0))
        legacy = load_scenarios(snapshot, {}, TODAY, VALUES)
        served = load_scenarios(snapshot, {}, TODAY, VALUES, canonical=canonical)
        self.assertEqual(served["status"], "insufficient_data")
        self.assertEqual(_dump(served), _dump(legacy))

    def test_multi_record_day_keeps_the_legacy_last_row(self) -> None:
        snapshot = _snapshot(_row(BASIS, 57.0), _row(BASIS, 60.0))
        canonical = CanonicalSeasonLoad(basis_day=BASIS, atl=_atl(57.0))
        legacy = load_scenarios(snapshot, {}, TODAY, VALUES)
        served = load_scenarios(snapshot, {}, TODAY, VALUES, canonical=canonical)
        self.assertEqual(served["basis"]["atl"], 60.0)
        self.assertEqual(_dump(served), _dump(legacy))


class ReportServiceWiringTests(unittest.TestCase):
    def test_service_without_a_source_calls_the_scenario_as_before(self) -> None:
        calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        def fake_scenarios(*args: Any, **kwargs: Any) -> dict[str, Any]:
            calls.append((args, kwargs))
            return {"status": "fake"}

        service = _service(fake_scenarios, None)
        self.assertEqual(service.scenarios(VALUES), {"status": "fake"})
        self.assertEqual(calls[0][1], {})
        self.assertEqual(len(calls[0][0]), 5)


def _service(
    load: Any, canonical: Any, snapshot: dict[str, Any] | None = None
) -> TrainingReportReadService:
    stored = snapshot if snapshot is not None else _snapshot(_row(BASIS, 57.0))
    return TrainingReportReadService(
        read_snapshot=lambda: stored,
        read_plan=dict,
        read_checkins=list,
        read_feedback=list,
        today=lambda: TODAY,
        load_scenarios=load,
        canonical=canonical,
    )


class PopulatedSeasonLoadTests(CanonicalReadFixture):
    def test_populated_tables_reproduce_the_legacy_scenario_bytes(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)
        self.assertEqual(self.write(selector.summary)["serving"], "tables")
        source = CanonicalPerformanceSource(lambda: self.manager, lambda: selector)
        legacy = load_scenarios(self.intervals, {}, TODAY, VALUES)
        served = _service(load_scenarios, source, self.intervals).scenarios(VALUES)
        self.assertEqual(_dump(served), _dump(legacy))
        snapshot, canonical = snapshot_with_season_load(
            source, lambda: self.intervals, BASIS
        )
        self.assertIs(snapshot, self.intervals)
        assert canonical is not None
        self.assertIsNotNone(canonical.atl)
        self.assertIsNotNone(matched_atl(canonical, legacy["basis"]["atl"]))
        self.assertEqual(legacy["basis"]["atl"], 57.0)
        self.assertEqual(legacy["basis"]["source"], LABEL)
