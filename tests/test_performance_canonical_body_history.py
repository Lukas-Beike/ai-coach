"""Body fat history read from canonical observations matches legacy.

``body_history`` with canonical inputs must return the same output as the legacy
builder on the same data. The cases cover the consumer parity ledger inputs, the
legacy plausibility bounds, null days, athlete-record exclusion, future days, the
serving gate and read window, unit-of-work order, and a populated temporary
database served through the real selector.
"""

from __future__ import annotations

import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import Mock

from canonical_consumer_parity import CASES, TODAY, _observations
from canonical_read_support import (
    CLOCK_AT,
    CanonicalReadFixture,
    make_selector,
    populate,
)

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
)
from backend.http_api.public_performance import PublicPerformanceStateService
from backend.performance.body import body_history
from backend.performance.canonical_body import (
    CanonicalBodyInputs,
    read_body_inputs,
)
from backend.performance.canonical_inputs import CanonicalPerformanceSource
from backend.runtime.ports import ObservationReader

PROFILE = {"timezone": "Europe/Berlin"}
DAY = TODAY - timedelta(days=1)


class BodyReader(ObservationReader):
    """Serves observations by kind and window, optionally ignoring the window."""

    def __init__(
        self,
        observations: tuple[Observation, ...] = (),
        *,
        events: list[str] | None = None,
        honour_window: bool = True,
    ) -> None:
        self._observations = observations
        self._events = events
        self._honour_window = honour_window
        self.calls: list[tuple[MetricKind, date | None, date | None]] = []

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Any = None,
    ) -> tuple[Observation, ...]:
        self.calls.append((kind, start, end))
        if self._events is not None:
            self._events.append("read")
        if not self._honour_window:
            return tuple(o for o in self._observations if o.kind is kind)
        return tuple(
            observation
            for observation in self._observations
            if observation.kind is kind
            and (start is None or start <= observation.observed_on)
            and (end is None or observation.observed_on <= end)
        )


class ServingGate:
    """Stands in for the canonical selector's serving check."""

    def __init__(self, serving: bool, *, events: list[str] | None = None) -> None:
        self._serving = serving
        self._events = events
        self.calls = 0

    def serves_tables(self, db: Any) -> bool:
        self.calls += 1
        if self._events is not None:
            self._events.append("serves")
        return self._serving


class SelectingReader:
    """Chooses one source inside a unit of work, as the canonical selector does."""

    def __init__(self, chosen: ObservationReader, events: list[str]) -> None:
        self._chosen = chosen
        self._events = events
        self.choices = 0

    def reader_for(self, db: Any) -> ObservationReader:
        self.choices += 1
        self._events.append("choose")
        return self._chosen

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Any = None,
    ) -> tuple[Observation, ...]:
        raise AssertionError("a selecting reader must be resolved before reading")


class RecordingManager:
    """Records unit-of-work leases in the shared event list."""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    @contextmanager
    def unit_of_work(self) -> Iterator[str]:
        self._events.append("enter")
        try:
            yield "db"
        finally:
            self._events.append("exit")


def _measure(
    kind: MetricKind,
    value: float,
    day: date,
    *,
    provider: ProviderId = ProviderId.INTERVALS,
    record: str | None = None,
    observed_at: datetime | None = None,
) -> Observation:
    unit = "kg" if kind is MetricKind.WEIGHT else "%"
    return Observation(
        kind=kind,
        value=MetricValue(value=value, unit=unit),
        observed_on=day,
        observed_at=observed_at,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=day.isoformat() if record is None else record,
            recorded_by=RecordingOrigin.MANUAL,
            retrieved_at=None,
            label=None,
        ),
    )


def _legacy_body(case: Any) -> dict[str, Any]:
    return body_history(case.intervals, case.garmin, TODAY)


def _service(
    snapshot: dict[str, Any],
    garmin: dict[str, Any],
    source: CanonicalPerformanceSource | None,
    *,
    events: list[str] | None = None,
) -> PublicPerformanceStateService:
    sync_state = Mock()
    sync_state.latest_snapshot.return_value = snapshot

    def capture_garmin(_db: Any) -> dict[str, Any]:
        if events is not None:
            events.append("garmin")
        return garmin

    garmin_payload = Mock()
    garmin_payload.snapshot_in.side_effect = capture_garmin
    garmin_payload.snapshot.return_value = garmin
    if events is not None:
        # With an event log, any read outside the captured transaction fails.
        garmin_payload.snapshot.side_effect = AssertionError(
            "Garmin re-read outside the transaction"
        )
    profile = Mock()
    profile.get.return_value = PROFILE
    projection = Mock()
    projection.public_state.return_value = {}
    return PublicPerformanceStateService(
        sync_state,
        garmin_payload,
        profile,
        projection,
        lambda: TODAY,
        source,
    )


class CanonicalBodyLedgerCaseTests(unittest.TestCase):
    def test_every_ledger_case_matches_legacy_body_history(self) -> None:
        for case in CASES:
            with self.subTest(case=case.name):
                inputs = read_body_inputs(
                    BodyReader(_observations(case)), ServingGate(True), "db", TODAY
                )
                self.assertIsNotNone(inputs)
                self.assertEqual(
                    body_history(case.intervals, case.garmin, TODAY, canonical=inputs),
                    _legacy_body(case),
                )


class CanonicalBodyInputTests(unittest.TestCase):
    def test_reads_weight_and_body_fat_for_their_windows_ending_today(self) -> None:
        reader = BodyReader()
        read_body_inputs(reader, ServingGate(True), "db", TODAY)
        # Weight looks back 7 extra days for the quotient; body fat covers the chart.
        self.assertEqual(
            [
                (MetricKind.WEIGHT, TODAY - timedelta(days=90), TODAY),
                (MetricKind.BODY_FAT, TODAY - timedelta(days=83), TODAY),
            ],
            reader.calls,
        )

    def test_gate_closed_reads_nothing_and_keeps_legacy(self) -> None:
        reader = BodyReader(_observations(CASES[0]))
        gate = ServingGate(False)
        self.assertIsNone(read_body_inputs(reader, gate, "db", TODAY))
        self.assertEqual(1, gate.calls)
        self.assertEqual([], reader.calls)

    def test_bounds_and_rounding_match_the_legacy_limits(self) -> None:
        # Legacy checks the bounds before rounding, so 300.004 is out and 299.996
        # is in and rounds to 300.0.
        days = [TODAY - timedelta(days=offset) for offset in range(1, 6)]
        observations = (
            _measure(MetricKind.BODY_FAT, 1.99, days[0]),
            _measure(MetricKind.BODY_FAT, 2.0, days[1]),
            _measure(MetricKind.BODY_FAT, 69.996, days[2]),
            _measure(MetricKind.BODY_FAT, 70.01, days[3]),
            _measure(MetricKind.BODY_FAT, 14.456, days[4]),
            _measure(MetricKind.WEIGHT, 29.99, days[0]),
            _measure(MetricKind.WEIGHT, 30.0, days[1]),
            _measure(MetricKind.WEIGHT, 300.004, days[2]),
            _measure(MetricKind.WEIGHT, 299.996, days[3]),
        )
        inputs = read_body_inputs(
            BodyReader(observations), ServingGate(True), "db", TODAY
        )
        self.assertIsNotNone(inputs)
        assert inputs is not None
        self.assertEqual(
            {days[1]: 2.0, days[2]: 70.0, days[4]: 14.46},
            inputs.intervals_body_fat_pct,
        )
        self.assertEqual(
            {days[1]: 30.0, days[3]: 300.0},
            inputs.intervals_weight_kg,
        )

    def test_last_in_bounds_observation_wins_per_day(self) -> None:
        morning = datetime(2026, 10, 11, 6, tzinfo=UTC)
        evening = datetime(2026, 10, 11, 20, tzinfo=UTC)
        observations = (
            _measure(
                MetricKind.BODY_FAT,
                12.0,
                DAY,
                provider=ProviderId.GARMIN,
                observed_at=morning,
            ),
            _measure(
                MetricKind.BODY_FAT,
                13.0,
                DAY,
                provider=ProviderId.GARMIN,
                observed_at=evening,
            ),
            _measure(
                MetricKind.BODY_FAT,
                71.0,
                DAY,
                provider=ProviderId.GARMIN,
                observed_at=evening + timedelta(hours=1),
            ),
            _measure(
                MetricKind.WEIGHT,
                80.0,
                DAY,
                provider=ProviderId.GARMIN,
                observed_at=morning,
            ),
            _measure(
                MetricKind.WEIGHT,
                350.0,
                DAY,
                provider=ProviderId.GARMIN,
                observed_at=evening,
            ),
        )
        inputs = read_body_inputs(
            BodyReader(observations), ServingGate(True), "db", TODAY
        )
        self.assertIsNotNone(inputs)
        assert inputs is not None
        self.assertEqual({DAY: 13.0}, inputs.garmin_body_fat_pct)
        self.assertEqual({DAY: 80.0}, inputs.garmin_weight_kg)

    def test_garmin_same_day_order_compares_instants_across_offsets(self) -> None:
        # 23:30+02:00 is 21:30 UTC, which is earlier than 22:00+00:00. Text order
        # would pick the 23:30 reading, so the UTC instant must decide.
        plus_two = timezone(timedelta(hours=2))
        observations = (
            _measure(
                MetricKind.WEIGHT,
                81.0,
                DAY,
                provider=ProviderId.GARMIN,
                observed_at=datetime(2026, 10, 11, 22, 0, tzinfo=UTC),
            ),
            _measure(
                MetricKind.WEIGHT,
                80.0,
                DAY,
                provider=ProviderId.GARMIN,
                observed_at=datetime(2026, 10, 11, 23, 30, tzinfo=plus_two),
            ),
            _measure(
                MetricKind.BODY_FAT,
                13.0,
                DAY,
                provider=ProviderId.GARMIN,
                observed_at=datetime(2026, 10, 11, 23, 30, tzinfo=plus_two),
            ),
            _measure(
                MetricKind.BODY_FAT,
                12.0,
                DAY,
                provider=ProviderId.GARMIN,
                observed_at=datetime(2026, 10, 11, 22, 0, tzinfo=UTC),
            ),
        )
        inputs = read_body_inputs(
            BodyReader(observations), ServingGate(True), "db", TODAY
        )
        assert inputs is not None
        self.assertEqual({DAY: 81.0}, inputs.garmin_weight_kg)
        self.assertEqual({DAY: 12.0}, inputs.garmin_body_fat_pct)

    def test_timed_garmin_reading_beats_an_untimed_one_on_the_same_day(self) -> None:
        # The legacy reader ranks untimed readings below timed ones, whatever their
        # traversal order, so the timed 80.0 wins even when it comes first.
        observations = (
            _measure(
                MetricKind.WEIGHT,
                80.0,
                DAY,
                provider=ProviderId.GARMIN,
                observed_at=datetime(2026, 10, 11, 6, 0, tzinfo=UTC),
            ),
            _measure(MetricKind.WEIGHT, 79.0, DAY, provider=ProviderId.GARMIN),
        )
        inputs = read_body_inputs(
            BodyReader(observations), ServingGate(True), "db", TODAY
        )
        assert inputs is not None
        self.assertEqual({DAY: 80.0}, inputs.garmin_weight_kg)

    def test_athlete_record_values_are_not_body_measurements(self) -> None:
        observations = (
            _measure(MetricKind.BODY_FAT, 12.0, DAY, record="athlete-42"),
            _measure(MetricKind.BODY_FAT, 14.0, DAY),
        )
        inputs = read_body_inputs(
            BodyReader(observations), ServingGate(True), "db", TODAY
        )
        self.assertIsNotNone(inputs)
        assert inputs is not None
        self.assertEqual({DAY: 14.0}, inputs.intervals_body_fat_pct)

    def test_future_days_never_enter_the_inputs(self) -> None:
        tomorrow = TODAY + timedelta(days=1)
        observations = (
            _measure(MetricKind.BODY_FAT, 15.0, tomorrow),
            _measure(MetricKind.BODY_FAT, 16.0, tomorrow, provider=ProviderId.GARMIN),
            _measure(MetricKind.WEIGHT, 75.0, tomorrow),
            _measure(MetricKind.WEIGHT, 76.0, tomorrow, provider=ProviderId.GARMIN),
        )
        # The reader here ignores its window, so the module's own guard is tested.
        inputs = read_body_inputs(
            BodyReader(observations, honour_window=False),
            ServingGate(True),
            "db",
            TODAY,
        )
        self.assertEqual(
            CanonicalBodyInputs(
                intervals_weight_kg={},
                intervals_body_fat_pct={},
                garmin_weight_kg={},
                garmin_body_fat_pct={},
            ),
            inputs,
        )


# The body-history windows. Current-metric reads also read WEIGHT (U5) over other
# windows, so the closed-gate assertions check these exact body windows.
BODY_WEIGHT_WINDOW = (MetricKind.WEIGHT, TODAY - timedelta(days=90), TODAY)
BODY_FAT_WINDOW = (MetricKind.BODY_FAT, TODAY - timedelta(days=83), TODAY)


class CanonicalBodyPublicStateTests(unittest.TestCase):
    def test_body_history_reads_inside_the_unit_of_work(self) -> None:
        case = CASES[0]
        events: list[str] = []
        reader = BodyReader(_observations(case), events=events)
        gate = ServingGate(True, events=events)
        source = CanonicalPerformanceSource(
            database_manager=lambda: RecordingManager(events),
            observation_reader=lambda: reader,
            serving=lambda: gate,
        )
        state = _service(case.intervals, case.garmin, source).performance_state()
        legacy = _service(case.intervals, case.garmin, None).from_snapshot(
            case.intervals
        )
        self.assertEqual(
            legacy["performance"]["history"]["body"],
            state["performance"]["history"]["body"],
        )
        # Body reads and the serving check happen inside the single lease.
        enter, exit_ = events.index("enter"), events.index("exit")
        self.assertEqual(1, events.count("enter"))
        self.assertEqual(1, events.count("exit"))
        self.assertLess(enter, events.index("serves"))
        self.assertLess(events.index("serves"), exit_)
        self.assertTrue(
            all(enter < i < exit_ for i, e in enumerate(events) if e == "read")
        )
        kinds = {kind for kind, _s, _e in reader.calls}
        self.assertIn(MetricKind.BODY_FAT, kinds)
        self.assertIn(MetricKind.WEIGHT, kinds)

    def test_garmin_snapshot_is_captured_once_inside_the_unit_of_work(self) -> None:
        case = CASES[0]
        events: list[str] = []
        reader = BodyReader(_observations(case), events=events)
        gate = ServingGate(True, events=events)
        source = CanonicalPerformanceSource(
            database_manager=lambda: RecordingManager(events),
            observation_reader=lambda: reader,
            serving=lambda: gate,
        )
        # The Garmin re-read raises, so the projection must use the captured value.
        state = _service(
            case.intervals, case.garmin, source, events=events
        ).performance_state()
        self.assertEqual(1, events.count("enter"))
        self.assertEqual(1, events.count("exit"))
        self.assertEqual(1, events.count("garmin"))
        self.assertLess(events.index("enter"), events.index("garmin"))
        self.assertLess(events.index("garmin"), events.index("exit"))
        legacy = _service(case.intervals, case.garmin, None).from_snapshot(
            case.intervals
        )
        self.assertEqual(
            legacy["performance"]["history"]["body"],
            state["performance"]["history"]["body"],
        )

    def test_body_and_load_reads_share_one_selected_source(self) -> None:
        case = CASES[0]
        events: list[str] = []
        chosen = BodyReader(_observations(case), events=events)
        selector = SelectingReader(chosen, events)
        source = CanonicalPerformanceSource(
            database_manager=lambda: RecordingManager(events),
            observation_reader=lambda: selector,
            serving=lambda: ServingGate(True, events=events),
        )
        _service(case.intervals, case.garmin, source).performance_state()
        # One choice per unit of work, made inside the lease and before any read.
        self.assertEqual(1, selector.choices)
        choose = events.index("choose")
        self.assertLess(events.index("enter"), choose)
        self.assertLess(choose, events.index("exit"))
        self.assertLess(choose, events.index("read"))
        kinds = {kind for kind, _start, _end in chosen.calls}
        self.assertTrue(
            {MetricKind.WEIGHT, MetricKind.BODY_FAT, MetricKind.CTL, MetricKind.ATL}
            <= kinds
        )

    def test_closed_gate_keeps_body_history_legacy_and_reads_no_body_kinds(
        self,
    ) -> None:
        case = CASES[0]
        reader = BodyReader(_observations(case))
        source = CanonicalPerformanceSource(
            database_manager=lambda: RecordingManager([]),
            observation_reader=lambda: reader,
            serving=lambda: ServingGate(False),
        )
        state = _service(case.intervals, case.garmin, source).performance_state()
        legacy = _service(case.intervals, case.garmin, None).from_snapshot(
            case.intervals
        )
        self.assertEqual(
            legacy["performance"]["history"]["body"],
            state["performance"]["history"]["body"],
        )
        self.assertNotIn(BODY_FAT_WINDOW, reader.calls)
        self.assertNotIn(BODY_WEIGHT_WINDOW, reader.calls)
        self.assertNotIn(MetricKind.BODY_FAT, {kind for kind, _s, _e in reader.calls})

    def test_source_without_serving_never_reads_body_kinds(self) -> None:
        case = CASES[0]
        reader = BodyReader(_observations(case))
        source = CanonicalPerformanceSource(
            database_manager=lambda: RecordingManager([]),
            observation_reader=lambda: reader,
        )
        _service(case.intervals, case.garmin, source).performance_state()
        self.assertNotIn(BODY_FAT_WINDOW, reader.calls)
        self.assertNotIn(BODY_WEIGHT_WINDOW, reader.calls)
        self.assertNotIn(MetricKind.BODY_FAT, {kind for kind, _s, _e in reader.calls})


class CanonicalBodyFallbackTests(unittest.TestCase):
    """Days the canonical inputs lack keep the legacy value; canonical days override."""

    @staticmethod
    def _values(output: dict[str, Any], metric: str) -> list[Any]:
        series = output["windows"]["14d"]["metrics"][metric]
        return [point.get("value") for entry in series for point in entry["points"]]

    @staticmethod
    def _empty() -> CanonicalBodyInputs:
        return CanonicalBodyInputs(
            intervals_weight_kg={},
            intervals_body_fat_pct={},
            garmin_weight_kg={},
            garmin_body_fat_pct={},
        )

    def test_comma_decimal_day_keeps_the_legacy_value(self) -> None:
        # The canonical mapper stores dot decimals only, so a comma day is absent
        # from the canonical inputs and must keep the legacy 14.5.
        snapshot = {
            "synced_at": "2026-10-11T06:00:00+00:00",
            "raw_provider_data": {
                "wellness": [{"id": DAY.isoformat(), "bodyFat": "14,5"}]
            },
        }
        legacy = body_history(snapshot, None, TODAY)
        self.assertIn(14.5, self._values(legacy, "body_fat_pct"))
        self.assertEqual(
            legacy,
            body_history(snapshot, None, TODAY, canonical=self._empty()),
        )

    def test_comma_decimal_weight_keeps_the_legacy_value(self) -> None:
        snapshot = {
            "synced_at": "2026-10-11T06:00:00+00:00",
            "raw_provider_data": {
                "wellness": [{"id": DAY.isoformat(), "weight": "70,4"}]
            },
        }
        legacy = body_history(snapshot, None, TODAY)
        self.assertIn(70.4, self._values(legacy, "weight_kg"))
        self.assertEqual(
            legacy,
            body_history(snapshot, None, TODAY, canonical=self._empty()),
        )

    def test_canonical_value_overrides_the_legacy_value_for_the_same_day(self) -> None:
        snapshot = {
            "synced_at": "2026-10-11T06:00:00+00:00",
            "raw_provider_data": {
                "wellness": [{"id": DAY.isoformat(), "bodyFat": 14.0, "weight": 70.0}]
            },
        }
        canonical = CanonicalBodyInputs(
            intervals_weight_kg={DAY: 71.0},
            intervals_body_fat_pct={DAY: 15.0},
            garmin_weight_kg={},
            garmin_body_fat_pct={},
        )
        output = body_history(snapshot, None, TODAY, canonical=canonical)
        self.assertIn(15.0, self._values(output, "body_fat_pct"))
        self.assertNotIn(14.0, self._values(output, "body_fat_pct"))
        self.assertIn(71.0, self._values(output, "weight_kg"))
        self.assertNotIn(70.0, self._values(output, "weight_kg"))


class CanonicalBodyPopulatedDatabaseTests(CanonicalReadFixture):
    """The populated temporary database, read through the real selector."""

    def test_served_tables_match_legacy_body_history(self) -> None:
        # The shared fixture carries no body fat, so give the wellness rows some in
        # both the raw section (canonical source) and the compact projection (legacy).
        for index, row in enumerate(self.intervals["raw_provider_data"]["wellness"]):
            row["bodyFat"] = 14.0 + index
        for index, row in enumerate(self.intervals["recent_wellness"]):
            row["bodyFat"] = 14.0 + index
        populate(self)
        selector = make_selector(self)
        with self.manager.unit_of_work() as db:
            selector.refresh(db)
        # The shared wellness rows are dated 2026-10-08..10, after the fixture clock
        # (CLOCK_AT), so read as of the last recorded day to include them.
        today = date(2026, 10, 10)
        with self.manager.reader() as db:
            inputs = read_body_inputs(selector, selector, db, today)
        self.assertIsNotNone(inputs)
        assert inputs is not None
        self.assertEqual(
            {
                date(2026, 10, 8): 14.0,
                date(2026, 10, 9): 15.0,
                date(2026, 10, 10): 16.0,
            },
            inputs.intervals_body_fat_pct,
        )
        self.assertEqual(
            {
                date(2026, 10, 8): 70.4,
                date(2026, 10, 9): 70.2,
                date(2026, 10, 10): 70.1,
            },
            inputs.intervals_weight_kg,
        )
        self.assertEqual(
            body_history(self.intervals, self.garmin, today),
            body_history(self.intervals, self.garmin, today, canonical=inputs),
        )

    def test_unchecked_switch_serves_no_body_inputs(self) -> None:
        populate(self)
        selector = make_selector(self)
        with self.manager.reader() as db:
            self.assertIsNone(read_body_inputs(selector, selector, db, CLOCK_AT.date()))
