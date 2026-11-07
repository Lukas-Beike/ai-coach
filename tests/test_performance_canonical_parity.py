"""Canonical performance inputs: reads, wiring and the served read state.

Intervals.icu CTL, ATL, form and ratings are never read (athlete decision
2026-11-07); the fixtures still carry Intervals rows to show that they change
no input.
"""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from typing import Any, cast
from unittest.mock import Mock, patch

from activity_row_support import SnapshotActivityRows
from canonical_detail_support import add_session_record, open_manager
from canonical_read_support import (
    CLOCK_AT,
    ZONE,
    CanonicalReadFixture,
    intervals_snapshot,
    make_selector,
    new_backfill,
    populate,
    store_garmin,
)

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.coach.context import (
    CoachPerformanceContextReader,
    CoachStructuredContextService,
)
from backend.http_api.public_performance import PublicPerformanceStateService
from backend.http_api.state_prelude import (
    CalendarWindowRange,
    PublicStateLocalPrelude,
)
from backend.performance.activity_read_service import ActivityAnalysisReadService
from backend.performance.canonical_current import NO_CURRENT_INPUTS
from backend.performance.canonical_inputs import (
    EMPTY_PERFORMANCE_INPUTS,
    PENDING_PERFORMANCE_INPUTS,
    CanonicalPerformanceInputs,
    CanonicalPerformanceSource,
    read_performance_inputs,
)
from backend.performance.canonical_recovery import (
    RECOVERY_KINDS,
    CanonicalRecoveryInputs,
)
from backend.performance.chart_history import analysis_history
from backend.performance.freshness import NO_GARMIN_SYNC_STATUS, GarminSyncStatus
from backend.performance.garmin_canonical import GarminCanonicalMetrics
from backend.providers.snapshot_projection import project_intervals_snapshot
from backend.runtime.ports import ObservationReader
from backend.sync.canonical_table_reader import CanonicalTableReader

PARITY_TODAY = date(2026, 9, 20)
PARITY_DAY = "2026-09-20"
EARLIER_DAY = "2026-09-19"
PARITY_PROFILE = {"timezone": "Europe/Berlin"}
_NO_RECOVERY = CanonicalRecoveryInputs(
    observations={kind: () for kind in RECOVERY_KINDS}
)
# One unbounded read per kind: the body-history kinds, the current-metric kinds,
# the Garmin performance kinds (with the twelve training load and load balance
# kinds and the four history-chart kinds), the daily totals (with resting energy)
# and the recovery kinds not read before (the weekly HRV average).
_UNIT_READS = 40


class StubObservationReader(ObservationReader):
    """Serves observations the way the canonical port does: by kind and window."""

    def __init__(
        self,
        observations: tuple[Observation, ...] = (),
        events: list[str] | None = None,
    ) -> None:
        self._observations = observations
        self._events = events
        self.calls: list[tuple[MetricKind, date | None, date | None]] = []
        self.db_seen: list[object] = []

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
        self.db_seen.append(db)
        if self._events is not None:
            self._events.append("read")
        return tuple(
            observation
            for observation in self._observations
            if observation.kind is kind
            and (start is None or start <= observation.observed_on)
            and (end is None or observation.observed_on <= end)
            and (sport is None or observation.sport is sport)
        )


class CountingObservationReader(ObservationReader):
    """Delegates to the real selector and counts the calls it serves."""

    def __init__(self, inner: ObservationReader) -> None:
        self._inner = inner
        self.calls = 0

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        self.calls += 1
        return self._inner.observations(db, kind, start=start, end=end, sport=sport)


class RecordingManager:
    """Records unit and reader leases; the yielded string stands in for a connection."""

    def __init__(self) -> None:
        self.events: list[str] = []

    @contextmanager
    def unit_of_work(self) -> Iterator[str]:
        self.events.append("enter")
        try:
            yield "db"
        finally:
            self.events.append("exit")

    @contextmanager
    def read_snapshot(self) -> Iterator[str]:
        """A read-only snapshot is recorded as the same lease."""
        with self.unit_of_work() as db:
            yield db

    @contextmanager
    def reader(self) -> Iterator[str]:
        self.events.append("reader")
        try:
            yield "db"
        finally:
            self.events.append("reader_exit")


def _snapshot(rows: list[Any]) -> dict[str, Any]:
    """A snapshot whose rows carry a stored weight, so each row is a history day."""
    return {
        **intervals_snapshot(athlete_weight=False),
        "recent_wellness": [{"weight": 71.5, **row} for row in rows],
    }


def _observations(snapshot: dict[str, Any]) -> tuple[Observation, ...]:
    _activities, observations = project_intervals_snapshot(
        snapshot, zone=ZONE, retrieved_at=CLOCK_AT
    )
    return tuple(observations.records)


def _assert_load_inputs(
    case: unittest.TestCase, inputs: CanonicalPerformanceInputs | None
) -> None:
    """The inputs hold no Intervals.icu load; the rest is extra."""
    case.assertEqual(
        replace(
            _present(inputs), current=NO_CURRENT_INPUTS, history_wellness_days=None
        ),
        CanonicalPerformanceInputs(
            recovery=_NO_RECOVERY, garmin=GarminCanonicalMetrics(), daily_health={}
        ),
    )


def _present(inputs: CanonicalPerformanceInputs | None) -> CanonicalPerformanceInputs:
    if inputs is None:
        raise AssertionError("expected canonical performance inputs")
    return inputs


def _service(
    source: CanonicalPerformanceSource | None,
    garmin: dict[str, Any] | None = None,
) -> PublicPerformanceStateService:
    garmin_snapshot = garmin if garmin is not None else {}
    garmin_payload = Mock()
    garmin_payload.sync_status.return_value = GarminSyncStatus.from_state(
        garmin_snapshot
    )
    garmin_payload.sync_status_in.side_effect = lambda _db: GarminSyncStatus.from_state(
        garmin_snapshot
    )
    profile = Mock()
    profile.get.return_value = PARITY_PROFILE
    projection = Mock()
    projection.public_state.return_value = {}
    return PublicPerformanceStateService(
        garmin_payload,
        profile,
        projection,
        lambda: PARITY_TODAY,
        source,
    )


def _assert_load_metric_split(
    case: unittest.TestCase, canonical: dict[str, Any], legacy: dict[str, Any]
) -> None:
    """Neither state shows an eFTP, a stored Intervals.icu form or a ramp rate."""
    served = canonical["performance"]
    absent = legacy["performance"]
    absent_load = absent.get("current_load", {})
    case.assertNotIn("cycling_eftp_watts", served["metrics"])
    case.assertNotIn("cycling_eftp_watts", absent["metrics"])
    case.assertNotIn("intervals_load_history", served)
    case.assertIsNone(served["current_load"]["tsb"])
    case.assertIsNone(absent_load.get("tsb"))
    for load in (served["current_load"], absent_load):
        case.assertNotIn("ramp_rate", load)


def _assert_recovery_split(
    case: unittest.TestCase, canonical: dict[str, Any], legacy: dict[str, Any]
) -> None:
    """Canonical state shows recovery values; the no-source state shows none."""
    served = canonical["performance"]["recovery"]
    absent = legacy["performance"].get("recovery", {})
    for key in ("resting_hr_bpm", "hrv_ms", "sleep_score", "readiness", "sleep_hours"):
        case.assertIsNotNone(served[key], key)
        case.assertIsNone(absent.get(key), key)


class CanonicalInputEdgeTests(unittest.TestCase):
    def test_intervals_load_kinds_are_never_read(self) -> None:
        rows = [
            {"id": EARLIER_DAY, "ctl": 40, "atl": 45},
            {"id": PARITY_DAY, "ctl": 50, "atl": 60, "tsb": -10},
        ]
        reader = StubObservationReader(_observations(_snapshot(rows)))
        inputs = read_performance_inputs(reader, "db", as_of=PARITY_TODAY)
        kinds = [kind for kind, _start, _end in reader.calls]
        # Each kind is read once and unbounded.
        self.assertEqual(len(kinds), len(set(kinds)))
        self.assertIn(MetricKind.THRESHOLD_HR, kinds)
        for kind in (MetricKind.CTL, MetricKind.ATL, MetricKind.FORM):
            self.assertNotIn(kind, kinds)
        self.assertEqual(
            {(start, end) for _k, start, end in reader.calls}, {(None, None)}
        )
        for name in ("wellness_day", "ctl", "atl", "form_by_day", "wellness_days"):
            self.assertFalse(hasattr(_present(inputs), name), name)

    def test_without_rows_activities_or_observations_there_are_no_inputs(
        self,
    ) -> None:
        self.assertIsNone(
            read_performance_inputs(StubObservationReader(), "db", as_of=PARITY_TODAY)
        )

    def test_stored_body_history_days_remain_the_history_only(self) -> None:
        source = _snapshot([{"id": PARITY_DAY, "weight": 71.5, "ctl": 50, "atl": 60}])
        inputs = read_performance_inputs(
            StubObservationReader(_observations(source)), "db", as_of=PARITY_TODAY
        )
        self.assertEqual(
            [
                day.day.isoformat()
                for day in _present(inputs).history_wellness_days or ()
            ],
            [PARITY_DAY],
        )
        self.assertEqual(_present(inputs).current, NO_CURRENT_INPUTS)

    def test_empty_performance_inputs_stand_for_no_canonical_values(self) -> None:
        self.assertEqual(EMPTY_PERFORMANCE_INPUTS, CanonicalPerformanceInputs())
        self.assertIsNone(EMPTY_PERFORMANCE_INPUTS.recovery)
        self.assertIsNone(EMPTY_PERFORMANCE_INPUTS.activities)


class CanonicalWiringTests(unittest.TestCase):
    def test_public_performance_reads_snapshot_and_load_inside_one_unit(self) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        manager = RecordingManager()
        reader = StubObservationReader(_observations(snapshot), events=manager.events)
        source = CanonicalPerformanceSource(
            database_manager=lambda: manager,
            observation_reader=lambda: reader,
        )
        service = _service(source)
        with patch(
            "backend.http_api.public_performance.performance_context.current_performance_context",
            return_value={},
        ) as project:
            service.performance_state()
        self.assertEqual(manager.events, ["enter", *["read"] * _UNIT_READS, "exit"])
        self.assertEqual(reader.db_seen, ["db"] * _UNIT_READS)
        _assert_load_inputs(self, project.call_args.kwargs["canonical"])

    def test_public_performance_keeps_the_legacy_call_without_wellness(self) -> None:
        manager = RecordingManager()
        reader = StubObservationReader()
        source = CanonicalPerformanceSource(
            database_manager=lambda: manager,
            observation_reader=lambda: reader,
        )
        service = _service(source)
        with patch(
            "backend.http_api.public_performance.performance_context.current_performance_context",
            return_value={},
        ) as project:
            service.performance_state()
        # Canonical reads (#1416): the Garmin sync status, no snapshot.
        project.assert_called_once_with(
            GarminSyncStatus(),
            PARITY_PROFILE,
            PARITY_TODAY,
            canonical=EMPTY_PERFORMANCE_INPUTS,
            session_feedback=None,
        )
        self.assertEqual(manager.events, ["enter", "exit"])
        # Only the unbounded wellness reads happen; no windowed read follows.
        self.assertEqual({(s, e) for _k, s, e in reader.calls}, {(None, None)})

    def test_public_performance_without_a_source_uses_no_unit_of_work(self) -> None:
        service = _service(None)
        with patch(
            "backend.http_api.public_performance.performance_context.current_performance_context",
            return_value={},
        ) as project:
            service.performance_state()
        # Canonical reads (#1416): the Garmin sync status, no snapshot.
        project.assert_called_once_with(
            GarminSyncStatus(),
            PARITY_PROFILE,
            PARITY_TODAY,
            canonical=EMPTY_PERFORMANCE_INPUTS,
            session_feedback=None,
        )

    def test_activity_performance_inputs_share_the_snapshot_unit(self) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        manager = RecordingManager()
        reader = StubObservationReader(_observations(snapshot))
        service = ActivityAnalysisReadService(
            manager,
            Mock(),
            Mock(),
            canonical=CanonicalPerformanceSource(
                database_manager=lambda: manager,
                observation_reader=lambda: reader,
            ),
        )
        canonical, _ = service._performance_inputs(PARITY_TODAY)
        self.assertEqual(reader.db_seen, ["db"] * _UNIT_READS)
        self.assertIsNotNone(canonical)

    def test_activity_detail_passes_canonical_inputs_to_the_load_context(self) -> None:
        activity = {
            "id": "a1",
            "start_date_local": "2026-09-20T08:00:00",
            "moving_time": 3600,
        }
        snapshot = {
            **_snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}]),
            "raw_provider_data": {"activities": [activity]},
        }
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        sessions = open_manager(directory.name)
        self.addCleanup(sessions.close)
        add_session_record(sessions, ProviderId.INTERVALS, "a1", "act_a1")
        manager = RecordingManager()
        reader = StubObservationReader(_observations(snapshot))
        snapshot_reader = Mock()
        snapshot_reader.latest_snapshot.return_value = snapshot
        feedback = Mock()
        feedback.list.return_value = []
        feedback.for_activity_ids.return_value = []
        service = ActivityAnalysisReadService(
            sessions,
            Mock(),
            feedback,
            canonical=CanonicalPerformanceSource(
                database_manager=lambda: manager,
                observation_reader=lambda: reader,
                activity_summaries=lambda: SnapshotActivityRows(snapshot_reader),
            ),
            session_records=CanonicalTableReader().session_activities,
        )
        with patch(
            "backend.performance.activity_read_service.current_performance_context",
            return_value={},
        ) as project:
            service.detail(
                "a1",
                garmin_status=NO_GARMIN_SYNC_STATUS,
                profile={},
                today=PARITY_TODAY,
            )
        self.assertIsNotNone(project.call_args.kwargs["canonical"])

    def test_coach_reads_snapshot_and_load_inside_one_unit(self) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        manager = RecordingManager()
        reader = StubObservationReader(_observations(snapshot), events=manager.events)
        coach = CoachPerformanceContextReader(
            _profile_stub(),
            _garmin_stub(),
            Mock(),
            lambda: PARITY_TODAY,
            CanonicalPerformanceSource(
                database_manager=lambda: manager,
                observation_reader=lambda: reader,
            ),
        )

        # Canonical reads (#1416): the Coach reads only the canonical inputs.
        canonical = coach.read_inputs()
        self.assertEqual(
            manager.events,
            ["enter", *["read"] * _UNIT_READS, "exit"],
        )
        with (
            patch(
                "backend.coach.context.performance_context.current_performance_context",
                return_value={},
            ) as project,
            patch(
                "backend.coach.context.coach_performance_projection",
                side_effect=lambda value: value,
            ),
        ):
            self.assertEqual(coach.current_performance(canonical), {})
        self.assertIsNotNone(project.call_args.kwargs["canonical"])

    def test_coach_without_a_source_reads_no_inputs(self) -> None:
        coach = CoachPerformanceContextReader(
            _profile_stub(), _garmin_stub(), Mock(), lambda: PARITY_TODAY
        )
        self.assertIsNone(coach.read_inputs())

    def test_structured_context_reads_its_load_inputs_once(self) -> None:
        inputs = CanonicalPerformanceInputs()
        performance = Mock()
        performance.read_sources.return_value = (inputs, None)
        service = _structured_service(performance)
        service.build(selection=_performance_selection())
        performance.read_sources.assert_called_once_with()
        performance.current_performance.assert_called_once_with(inputs)

    def test_public_state_prelude_reads_load_inside_its_snapshot_unit(self) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        manager = RecordingManager()
        reader = StubObservationReader(_observations(snapshot), events=manager.events)
        service = _service(
            CanonicalPerformanceSource(
                database_manager=lambda: manager,
                observation_reader=lambda: reader,
            ),
        )
        prelude = _prelude(snapshot, manager, service.canonical_inputs).read(True)
        self.assertEqual(manager.events, ["enter", *["read"] * _UNIT_READS, "exit"])
        _assert_load_inputs(self, prelude.performance_inputs)
        with patch(
            "backend.http_api.public_performance.performance_context.current_performance_context",
            return_value={},
        ) as project:
            service.from_inputs(prelude.performance_inputs)
        self.assertIs(project.call_args.kwargs["canonical"], prelude.performance_inputs)

    def test_public_state_prelude_without_inputs_keeps_the_legacy_read(self) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        manager = RecordingManager()
        self.assertIsNone(
            _prelude(snapshot, manager, None).read(True).performance_inputs
        )
        self.assertIsNone(_service(None).canonical_inputs("db"))
        with patch(
            "backend.http_api.public_performance.performance_context.current_performance_context",
            return_value={},
        ) as project:
            _service(None).from_inputs(None)
        # Canonical reads (#1416): the Garmin sync status, no snapshot.
        project.assert_called_once_with(
            GarminSyncStatus(),
            PARITY_PROFILE,
            PARITY_TODAY,
            canonical=EMPTY_PERFORMANCE_INPUTS,
            session_feedback=None,
        )

    def test_coach_performance_without_a_source_keeps_the_legacy_call(self) -> None:
        coach = CoachPerformanceContextReader(
            _profile_stub(), _garmin_stub(), Mock(), lambda: PARITY_TODAY
        )
        with (
            patch(
                "backend.coach.context.performance_context.current_performance_context",
                return_value={},
            ) as project,
            patch(
                "backend.coach.context.coach_performance_projection",
                side_effect=lambda value: value,
            ),
        ):
            coach.current_performance()
        # Canonical reads (#1416): the Garmin sync status, no snapshot.
        project.assert_called_once_with(
            GarminSyncStatus(),
            PARITY_PROFILE,
            PARITY_TODAY,
            canonical=EMPTY_PERFORMANCE_INPUTS,
            session_feedback=None,
        )


def _performance_selection() -> Mock:
    selection = Mock()
    selection.sections = frozenset({"current_performance"})
    return selection


def _structured_service(performance: Mock) -> CoachStructuredContextService:
    return CoachStructuredContextService(Mock(), Mock(), Mock(), Mock(), performance)


def _prelude(
    snapshot: dict[str, Any], manager: RecordingManager, inputs: Any
) -> PublicStateLocalPrelude:
    state = Mock()
    state.sync_metadata.return_value = {
        "provider_sync": snapshot.get("provider_sync", {})
    }
    feedback = Mock()
    feedback.attach_to_activities.return_value = []
    planned = Mock()
    planned.list.return_value = []
    weather = Mock()
    weather.state.return_value = {}
    return PublicStateLocalPrelude(
        state,
        feedback,
        planned,
        weather,
        manager,  # type: ignore[arg-type]
        lambda: PARITY_TODAY,
        CalendarWindowRange(35, 35),
        inputs,
    )


def _profile_stub() -> Mock:
    profile = Mock()
    profile.get.return_value = PARITY_PROFILE
    return profile


def _garmin_stub() -> Mock:
    garmin = Mock()
    garmin.sync_status.return_value = GarminSyncStatus()
    return garmin


class CanonicalLoadEndToEndTests(CanonicalReadFixture):
    def test_public_performance_from_tables_keeps_wellness_without_snapshot_adapter(
        self,
    ) -> None:
        populate(self)
        selector = make_selector(self)
        self.assertEqual(self.write(selector.summary)["serving"], "tables")
        counting = CountingObservationReader(selector)
        source = CanonicalPerformanceSource(
            database_manager=lambda: self.manager,
            observation_reader=lambda: counting,
        )
        legacy = _service(None, self.garmin).performance_state()
        canonical = _service(source, self.garmin).performance_state()
        self.assertEqual(counting.calls, _UNIT_READS)
        # Without a canonical source there are no canonical values: unavailable.
        self.assertFalse(legacy["performance"]["available"])
        self.assertNotIn("current_load", legacy["performance"])
        _assert_recovery_split(self, canonical, legacy)
        _assert_load_metric_split(self, canonical, legacy)

    def test_selector_chooses_its_source_once_for_both_load_reads(self) -> None:
        populate(self)
        selector = make_selector(self)
        source = CanonicalPerformanceSource(
            database_manager=lambda: self.manager,
            observation_reader=lambda: selector,
        )
        with patch.object(
            selector, "_read_state", wraps=selector._read_state
        ) as read_state:
            canonical = _service(source, self.garmin).performance_state()
        read_state.assert_called_once()
        legacy = _service(None, self.garmin).performance_state()
        self.assertNotIn("intervals_load_history", canonical["performance"])
        self.assertFalse(legacy["performance"]["available"])
        _assert_load_metric_split(self, canonical, legacy)


class CanonicalReadStatusEndToEndTests(CanonicalReadFixture):
    """The selector's read state reaches the performance and Coach contexts."""

    def _source(self) -> CanonicalPerformanceSource:
        selector = make_selector(self)
        return CanonicalPerformanceSource(
            database_manager=lambda: self.manager,
            observation_reader=lambda: selector,
            serving=lambda: selector,
            activity_summaries=lambda: selector,
        )

    def _coach_performance(self, source: CanonicalPerformanceSource) -> Any:
        reader = CoachPerformanceContextReader(
            _profile_stub(),
            _garmin_stub(),
            Mock(),
            lambda: PARITY_TODAY,
            canonical=source,
        )
        return reader.current_performance(reader.read_inputs())

    def test_failed_first_backfill_is_visible_but_completed_data_stays_available(
        self,
    ) -> None:
        backfill = new_backfill(self)
        self.write(backfill.mark_failed)
        source = self._source()
        for result in (
            _service(source, self.garmin).performance_state()["performance"],
            self._coach_performance(source),
        ):
            self.assertEqual(result["reason"], "canonical_pending")
            self.assertIn("fehlgeschlagen", result["status"])
        completed = populate(self)
        self.write(completed.mark_failed)
        self.assertTrue(self._coach_performance(source)["available"])

    def test_before_the_first_backfill_performance_and_coach_are_pending(
        self,
    ) -> None:
        # The data is stored but the backfill never completed: no partial values.
        self.write(lambda db: store_garmin(self, db, self.garmin))
        source = self._source()

        service = _service(source, self.garmin)
        public = service.performance_state()
        coach = self._coach_performance(source)

        # While values are withheld the Garmin card gets the empty sync status:
        # no freshness, source or pagination, only the connection status.
        projection = cast(Mock, service._garmin_projection_service)
        self.assertEqual(
            projection.public_state.call_args.args[0], NO_GARMIN_SYNC_STATUS
        )
        for performance in (public["performance"], coach):
            self.assertFalse(performance["available"])
            self.assertEqual(performance["reason"], "canonical_pending")
            self.assertEqual(performance["status"], "Daten werden vorbereitet")
            self.assertEqual(performance["metrics"], {})
            self.assertIsNone(performance["as_of"])
        # Neither the stored snapshot nor the raw Garmin view feeds the charts.
        pending = public["performance"]
        self.assertEqual(
            pending["history"],
            {
                **analysis_history(
                    GarminSyncStatus.from_state({}),
                    PARITY_TODAY,
                    canonical=EMPTY_PERFORMANCE_INPUTS,
                ),
                "session_rpe_load": None,
                "smoothed_session_load": None,
                "local_fitness_fatigue": None,
            },
        )
        self.assertNotEqual(
            pending["history"],
            analysis_history(
                GarminSyncStatus.from_state(self.garmin),
                PARITY_TODAY,
                canonical=EMPTY_PERFORMANCE_INPUTS,
            ),
        )
        for focus in pending["training_focus_periods"].values():
            self.assertEqual(focus["classified_sessions"], 0)
            self.assertEqual(focus["zones"], [])

        populate(self)
        served_service = _service(source, self.garmin)
        served = served_service.performance_state()
        served_projection = cast(Mock, served_service._garmin_projection_service)
        self.assertEqual(
            served_projection.public_state.call_args.args[0],
            GarminSyncStatus.from_state(self.garmin),
        )
        self.assertTrue(served["performance"]["available"])
        self.assertNotIn("reason", served["performance"])
        self.assertTrue(self._coach_performance(source)["available"])

    def test_compact_only_snapshot_marks_the_activity_gap_until_a_raw_sync(
        self,
    ) -> None:
        raw = self.intervals
        self.intervals = {
            key: value for key, value in raw.items() if key != "raw_provider_data"
        }
        populate(self)
        source = self._source()

        public = _service(source, self.garmin).performance_state()
        self.assertTrue(public["performance"]["available"])
        self.assertTrue(public["performance"]["activities_need_refresh"])
        self.assertTrue(self._coach_performance(source)["activities_need_refresh"])

        self.intervals = raw
        refreshed = _service(source, self.garmin).performance_state()
        self.assertFalse(refreshed["performance"]["activities_need_refresh"])

    def test_activity_detail_inputs_carry_the_read_state(self) -> None:
        source = self._source()
        service = ActivityAnalysisReadService(
            self.manager, Mock(), Mock(), canonical=source
        )

        pending, _rows = service._performance_inputs(PARITY_TODAY)
        self.assertIs(pending, PENDING_PERFORMANCE_INPUTS)

        populate(self)
        served, _rows = service._performance_inputs(PARITY_TODAY)
        self.assertIsNotNone(served)
        assert served is not None
        self.assertFalse(served.pending)
