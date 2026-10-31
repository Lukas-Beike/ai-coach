"""Body history read from canonical observations.

``body_history`` with canonical inputs must return the same output for the
observations the ledger projection makes as for the payload mapped directly, and
the Garmin values of the stored snapshot are never read. The cases cover the
recorded consumer inputs, the plausibility bounds, null days, athlete-record
exclusion, future days, the read window, unit-of-work order, and a populated
temporary database served through the real selector.
"""

from __future__ import annotations

import json
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import Mock

from canonical_consumer_cases import CASES, TODAY, _observations
from canonical_read_support import (
    CLOCK_AT,
    CanonicalReadFixture,
    make_selector,
    populate,
)
from performance_day_support import (
    days_from_rows,
    garmin_body_from_payload,
    garmin_metrics_from_payload,
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
    EMPTY_BODY_INPUTS,
    CanonicalBodyInputs,
    read_body_inputs,
)
from backend.performance.canonical_inputs import CanonicalPerformanceSource
from backend.performance.freshness import GarminSyncStatus
from backend.runtime.ports import ObservationReader
from backend.sync.canonical_backfill import STATE_KEY as BACKFILL_STATE_KEY

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

    @contextmanager
    def read_snapshot(self) -> Iterator[str]:
        """A read-only snapshot is recorded as the same lease."""
        with self.unit_of_work() as db:
            yield db


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


def _body(
    snapshot: dict[str, Any],
    garmin: dict[str, Any] | None,
    canonical: CanonicalBodyInputs,
) -> dict[str, Any]:
    return body_history(
        (snapshot or {}).get("synced_at"),
        GarminSyncStatus.from_state(garmin),
        TODAY,
        canonical=canonical,
        wellness_days=_days(snapshot),
        activities=(),
        garmin_ftp=garmin_metrics_from_payload(garmin or {}).performance_history.get(
            "cycling_ftp_watts", {}
        ),
    )


def _payload_body(case: Any) -> dict[str, Any]:
    """The body history of the payload mapped directly, without the ledger."""
    return _body(
        case.intervals, case.garmin, garmin_body_from_payload(case.garmin, TODAY)
    )


def _days(snapshot: dict[str, Any]):
    raw = snapshot.get("raw_provider_data")
    rows = list(raw.get("wellness") or ()) if isinstance(raw, dict) else []
    rows += list(snapshot.get("recent_wellness") or ())
    return days_from_rows(rows)


def _service(
    snapshot: dict[str, Any],
    garmin: dict[str, Any],
    source: CanonicalPerformanceSource | None,
    *,
    events: list[str] | None = None,
) -> PublicPerformanceStateService:
    sync_state = Mock()
    sync_state.latest_snapshot.return_value = snapshot

    def capture_garmin(_db: Any) -> GarminSyncStatus:
        if events is not None:
            events.append("garmin")
        return GarminSyncStatus.from_state(garmin)

    # Canonical reads (#1416): only the Garmin sync status is read.
    garmin_payload = Mock()
    garmin_payload.sync_status_in.side_effect = capture_garmin
    garmin_payload.sync_status.return_value = GarminSyncStatus.from_state(garmin)
    if events is not None:
        # With an event log, any read outside the captured transaction fails.
        garmin_payload.sync_status.side_effect = AssertionError(
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
    def test_every_ledger_case_matches_the_directly_mapped_payload(self) -> None:
        for case in CASES:
            with self.subTest(case=case.name):
                inputs = read_body_inputs(BodyReader(_observations(case)), "db", TODAY)
                self.assertEqual(
                    _body(case.intervals, case.garmin, inputs), _payload_body(case)
                )

    def test_garmin_body_values_are_those_of_the_canonical_inputs(self) -> None:
        case = next(item for item in CASES if item.name == "complete")
        day = date(2026, 10, 11)
        inputs = read_body_inputs(BodyReader(_observations(case)), "db", TODAY)
        self.assertEqual({day: 80.1}, inputs.garmin_weight_kg)
        self.assertEqual({day: 15.2}, inputs.garmin_body_fat_pct)


class CanonicalBodyInputTests(unittest.TestCase):
    def test_reads_weight_and_body_fat_for_their_windows_ending_today(self) -> None:
        reader = BodyReader()
        read_body_inputs(reader, "db", TODAY)
        # Weight looks back 7 extra days for the quotient; body fat covers the chart.
        self.assertEqual(
            [
                (MetricKind.WEIGHT, TODAY - timedelta(days=90), TODAY),
                (MetricKind.BODY_FAT, TODAY - timedelta(days=83), TODAY),
            ],
            reader.calls,
        )

    def test_bounds_and_rounding_follow_the_plausibility_limits(self) -> None:
        # The bounds are checked before rounding, so 300.004 is out and 299.996
        # is in and rounds to 300.0.
        days = [TODAY - timedelta(days=offset) for offset in range(1, 6)]
        observations = (
            _measure(MetricKind.BODY_FAT, 1.99, days[0], provider=ProviderId.GARMIN),
            _measure(MetricKind.BODY_FAT, 2.0, days[1], provider=ProviderId.GARMIN),
            _measure(MetricKind.BODY_FAT, 69.996, days[2], provider=ProviderId.GARMIN),
            _measure(MetricKind.BODY_FAT, 70.01, days[3], provider=ProviderId.GARMIN),
            _measure(MetricKind.BODY_FAT, 14.456, days[4], provider=ProviderId.GARMIN),
            _measure(MetricKind.WEIGHT, 29.99, days[0], provider=ProviderId.GARMIN),
            _measure(MetricKind.WEIGHT, 30.0, days[1], provider=ProviderId.GARMIN),
            _measure(MetricKind.WEIGHT, 300.004, days[2], provider=ProviderId.GARMIN),
            _measure(MetricKind.WEIGHT, 299.996, days[3], provider=ProviderId.GARMIN),
        )
        inputs = read_body_inputs(BodyReader(observations), "db", TODAY)
        self.assertEqual(
            {days[1]: 2.0, days[2]: 70.0, days[4]: 14.46},
            inputs.garmin_body_fat_pct,
        )
        self.assertEqual(
            {days[1]: 30.0, days[3]: 300.0},
            inputs.garmin_weight_kg,
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
        inputs = read_body_inputs(BodyReader(observations), "db", TODAY)
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
        inputs = read_body_inputs(BodyReader(observations), "db", TODAY)
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
        inputs = read_body_inputs(BodyReader(observations), "db", TODAY)
        self.assertEqual({DAY: 80.0}, inputs.garmin_weight_kg)

    def test_intervals_values_are_not_body_inputs(self) -> None:
        # Intervals.icu body values reach body history through the wellness days.
        observations = (
            _measure(MetricKind.BODY_FAT, 12.0, DAY, record="athlete-42"),
            _measure(MetricKind.BODY_FAT, 14.0, DAY),
        )
        inputs = read_body_inputs(BodyReader(observations), "db", TODAY)
        self.assertEqual(EMPTY_BODY_INPUTS, inputs)

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
            BodyReader(observations, honour_window=False), "db", TODAY
        )
        self.assertEqual(
            CanonicalBodyInputs(
                garmin_weight_kg={},
                garmin_body_fat_pct={},
            ),
            inputs,
        )


# The body-history windows. Current-metric reads also read WEIGHT (U5) over other
# windows, so the window assertions check these exact body windows.
BODY_WEIGHT_WINDOW = (MetricKind.WEIGHT, TODAY - timedelta(days=90), TODAY)
BODY_FAT_WINDOW = (MetricKind.BODY_FAT, TODAY - timedelta(days=83), TODAY)


class CanonicalBodyPublicStateTests(unittest.TestCase):
    def assert_wellness_boundary(
        self, legacy: dict[str, Any], state: dict[str, Any]
    ) -> None:
        def intervals_values(result):
            body = result["performance"]["history"]["body"]
            series = next(
                item
                for item in body["windows"]["14d"]["metrics"]["weight_kg"]
                if item["source"] == "Intervals.icu Wellness"
            )
            return [
                point["value"]
                for point in series["points"]
                if point["value"] is not None
            ]

        self.assertEqual(intervals_values(legacy), [])
        self.assertTrue(intervals_values(state))

    def test_body_history_reads_inside_the_unit_of_work(self) -> None:
        case = CASES[0]
        events: list[str] = []
        reader = BodyReader(_observations(case), events=events)
        source = CanonicalPerformanceSource(
            database_manager=lambda: RecordingManager(events),
            observation_reader=lambda: reader,
        )
        state = _service(case.intervals, case.garmin, source).performance_state()
        legacy = _service(case.intervals, case.garmin, None).from_inputs(
            None, case.intervals
        )
        self.assert_wellness_boundary(legacy, state)
        # Body reads happen inside the single lease.
        enter, exit_ = events.index("enter"), events.index("exit")
        self.assertEqual(1, events.count("enter"))
        self.assertEqual(1, events.count("exit"))
        self.assertTrue(
            all(enter < i < exit_ for i, e in enumerate(events) if e == "read")
        )
        kinds = {kind for kind, _s, _e in reader.calls}
        self.assertIn(MetricKind.BODY_FAT, kinds)
        self.assertIn(MetricKind.WEIGHT, kinds)

    def test_garmin_status_is_captured_once_inside_the_unit_of_work(self) -> None:
        case = CASES[0]
        events: list[str] = []
        reader = BodyReader(_observations(case), events=events)
        source = CanonicalPerformanceSource(
            database_manager=lambda: RecordingManager(events),
            observation_reader=lambda: reader,
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
        legacy = _service(case.intervals, case.garmin, None).from_inputs(
            None, case.intervals
        )
        self.assert_wellness_boundary(legacy, state)

    def test_body_and_load_reads_share_one_selected_source(self) -> None:
        case = CASES[0]
        events: list[str] = []
        chosen = BodyReader(_observations(case), events=events)
        selector = SelectingReader(chosen, events)
        source = CanonicalPerformanceSource(
            database_manager=lambda: RecordingManager(events),
            observation_reader=lambda: selector,
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

    def test_source_without_observations_shows_no_garmin_body_values(self) -> None:
        case = CASES[0]
        state = _service(case.intervals, case.garmin, None).from_inputs(
            None, case.intervals
        )
        body = state["performance"]["history"]["body"]
        for metric in ("weight_kg", "body_fat_pct"):
            for series in body["windows"]["12w"]["metrics"][metric]:
                if series["source"] == "Garmin Connect":
                    self.assertTrue(
                        all(point["value"] is None for point in series["points"])
                    )


class CanonicalBodyFallbackTests(unittest.TestCase):
    """Intervals.icu values come from the wellness days, Garmin from canonical."""

    @staticmethod
    def _values(output: dict[str, Any], metric: str) -> list[Any]:
        series = output["windows"]["14d"]["metrics"][metric]
        return [point.get("value") for entry in series for point in entry["points"]]

    def test_comma_decimal_day_comes_from_the_wellness_days(self) -> None:
        snapshot = {
            "synced_at": "2026-10-11T06:00:00+00:00",
            "raw_provider_data": {
                "wellness": [{"id": DAY.isoformat(), "bodyFat": "14,5"}]
            },
        }
        output = _body(snapshot, None, EMPTY_BODY_INPUTS)
        self.assertIn(14.5, self._values(output, "body_fat_pct"))

    def test_comma_decimal_weight_comes_from_the_wellness_days(self) -> None:
        snapshot = {
            "synced_at": "2026-10-11T06:00:00+00:00",
            "raw_provider_data": {
                "wellness": [{"id": DAY.isoformat(), "weight": "70,4"}]
            },
        }
        output = _body(snapshot, None, EMPTY_BODY_INPUTS)
        self.assertIn(70.4, self._values(output, "weight_kg"))

    def test_intervals_body_values_come_from_the_history_wellness_days(
        self,
    ) -> None:
        snapshot = {
            "synced_at": "2026-10-11T06:00:00+00:00",
            "raw_provider_data": {
                "wellness": [{"id": DAY.isoformat(), "bodyFat": 14.0, "weight": 70.0}]
            },
        }
        output = _body(snapshot, None, EMPTY_BODY_INPUTS)
        self.assertIn(14.0, self._values(output, "body_fat_pct"))
        self.assertIn(70.0, self._values(output, "weight_kg"))

    def test_snapshot_garmin_values_are_ignored_without_canonical_values(self) -> None:
        garmin = {"weight": [{"calendarDate": DAY.isoformat(), "weight": 80.4}]}
        output = _body({}, garmin, EMPTY_BODY_INPUTS)
        self.assertEqual(
            [], [v for v in self._values(output, "weight_kg") if v is not None]
        )


class CanonicalBodyPopulatedDatabaseTests(CanonicalReadFixture):
    """The populated temporary database, read through the real selector."""

    def test_served_tables_match_the_directly_mapped_payload(self) -> None:
        # The shared fixture carries no body fat, so give the wellness rows some in
        # both the raw section (canonical source) and the compact projection.
        for index, row in enumerate(self.intervals["raw_provider_data"]["wellness"]):
            row["bodyFat"] = 14.0 + index
        for index, row in enumerate(self.intervals["recent_wellness"]):
            row["bodyFat"] = 14.0 + index
        populate(self)
        selector = make_selector(self)
        # The shared wellness rows are dated 2026-10-08..10, after the fixture clock
        # (CLOCK_AT), so read as of the last recorded day to include them.
        today = date(2026, 10, 10)
        with self.manager.reader() as db:
            inputs = read_body_inputs(selector, db, today)
        self.assertEqual(
            body_history(
                (self.intervals or {}).get("synced_at"),
                GarminSyncStatus.from_state(self.garmin),
                today,
                canonical=garmin_body_from_payload(self.garmin, today),
                wellness_days=_days(self.intervals),
                activities=(),
                garmin_ftp={},
            ),
            body_history(
                (self.intervals or {}).get("synced_at"),
                GarminSyncStatus.from_state(self.garmin),
                today,
                canonical=inputs,
                wellness_days=_days(self.intervals),
                activities=(),
                garmin_ftp={},
            ),
        )

    def test_never_completed_backfill_reads_the_projected_snapshot(self) -> None:
        populate(self)
        selector = make_selector(self)
        today = CLOCK_AT.date()
        with self.manager.reader() as db:
            served = read_body_inputs(selector, db, today)
        with self.manager.unit_of_work() as db:
            state = json.loads(self.key_values.get(db, BACKFILL_STATE_KEY) or "{}")
            self.key_values.set(
                db,
                BACKFILL_STATE_KEY,
                json.dumps({**state, "status": "running", "completed_once": False}),
            )
        selector = make_selector(self)
        with self.manager.reader() as db:
            self.assertEqual(served, read_body_inputs(selector, db, today))
