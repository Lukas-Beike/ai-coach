"""CTL and ATL read from canonical observations match the legacy load context.

The load-context output is compared after one deliberate normalisation: CTL and ATL
are numbers on the canonical side, while legacy values pass through as the stored
JSON (an int, a numeric string). Both sides are converted with ``float`` before
comparison. The only intended value difference is a comma-decimal CTL such as
"58,2", which canonical reads as 58.2 once the Intervals mapper accepts it.
"""

from __future__ import annotations

import unittest
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import date
from typing import Any
from unittest.mock import Mock, patch

from canonical_read_support import (
    CLOCK_AT,
    ZONE,
    CanonicalReadFixture,
    intervals_snapshot,
    make_selector,
    populate,
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
from backend.performance.canonical_inputs import (
    CanonicalPerformanceInputs,
    CanonicalPerformanceSource,
    load_performance_inputs,
    performance_options,
    read_performance_inputs,
)
from backend.performance.canonical_personal_recovery import (
    CanonicalPersonalRecoveryInputs,
)
from backend.performance.canonical_recovery import CanonicalRecoveryInputs
from backend.performance.canonical_recovery_averages import (
    CanonicalRecoveryAverageInputs,
)
from backend.performance.load_context import performance_load_context
from backend.providers.snapshot_projection import project_intervals_snapshot
from backend.runtime.ports import ObservationReader

PARITY_TODAY = date(2026, 9, 20)
PARITY_DAY = "2026-09-20"
EARLIER_DAY = "2026-09-19"
PARITY_PROFILE = {"timezone": "Europe/Berlin"}
_NO_RECOVERY = CanonicalRecoveryInputs(
    sleep_score=None, resting_hr=None, readiness=None
)
_NO_PERSONAL_RECOVERY = CanonicalPersonalRecoveryInputs(
    resting_hr={ProviderId.INTERVALS: {}, ProviderId.GARMIN: {}}
)
_NO_RECOVERY_AVERAGES = CanonicalRecoveryAverageInputs(resting_hr=(), readiness=())


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
    def reader(self) -> Iterator[str]:
        self.events.append("reader")
        try:
            yield "db"
        finally:
            self.events.append("reader_exit")


def _snapshot(rows: list[Any]) -> dict[str, Any]:
    return {**intervals_snapshot(athlete_weight=False), "recent_wellness": rows}


def _observations(snapshot: dict[str, Any]) -> tuple[Observation, ...]:
    _activities, observations = project_intervals_snapshot(
        snapshot, zone=ZONE, retrieved_at=CLOCK_AT
    )
    return tuple(observations.records)


def _latest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return max(rows, key=lambda row: str(row.get("id") or ""), default={})


def _present(inputs: CanonicalPerformanceInputs | None) -> CanonicalPerformanceInputs:
    if inputs is None:
        raise AssertionError("expected canonical performance inputs")
    return inputs


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _normalized_load(load: dict[str, Any]) -> dict[str, Any]:
    return {**load, "ctl": _as_float(load["ctl"]), "atl": _as_float(load["atl"])}


def _load_pair(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], CanonicalPerformanceInputs | None]:
    """Return the legacy load, the canonical load, and the canonical inputs."""
    snapshot = _snapshot(rows)
    legacy = performance_load_context([], rows, _latest(rows), PARITY_TODAY)["load"]
    canonical = read_performance_inputs(
        StubObservationReader(_observations(snapshot)), None, snapshot
    )
    canonical_load = performance_load_context(
        [], rows, _latest(rows), PARITY_TODAY, canonical=canonical
    )["load"]
    return legacy, canonical_load, canonical


def _service(
    snapshot: dict[str, Any],
    source: CanonicalPerformanceSource | None,
    garmin: dict[str, Any] | None = None,
) -> PublicPerformanceStateService:
    sync_state = Mock()
    sync_state.latest_snapshot.return_value = snapshot
    garmin_snapshot = garmin if garmin is not None else {}
    garmin_payload = Mock()
    garmin_payload.snapshot.return_value = garmin_snapshot
    garmin_payload.snapshot_in.side_effect = lambda _db: garmin_snapshot
    profile = Mock()
    profile.get.return_value = PARITY_PROFILE
    projection = Mock()
    projection.public_state.return_value = {}
    return PublicPerformanceStateService(
        sync_state,
        garmin_payload,
        profile,
        projection,
        lambda: PARITY_TODAY,
        source,
    )


def _normalized_state(state: dict[str, Any]) -> dict[str, Any]:
    performance = state["performance"]
    return {
        **state,
        "performance": {
            **performance,
            "current_load": _normalized_load(performance["current_load"]),
        },
    }


class CanonicalLoadParityTests(unittest.TestCase):
    def test_canonical_load_matches_legacy_after_numeric_normalisation(self) -> None:
        cases = {
            "aliases_and_strings": [
                {"id": EARLIER_DAY, "ctl": 40, "atl": 45},
                {"id": PARITY_DAY, "ctLoad": "55", "atlLoad": 65, "rampRate": "1.5"},
            ],
            "numbers_and_zero": [{"id": PARITY_DAY, "ctl": 50.25, "atl": 0}],
        }
        for name, rows in cases.items():
            with self.subTest(name):
                legacy, canonical_load, canonical = _load_pair(rows)
                self.assertIsNotNone(canonical)
                self.assertEqual(
                    _normalized_load(canonical_load), _normalized_load(legacy)
                )

    def test_comma_decimal_is_the_one_intended_difference(self) -> None:
        legacy_rows = [{"id": PARITY_DAY, "ctl": "58,2", "atl": 60}]
        legacy = performance_load_context(
            [], legacy_rows, _latest(legacy_rows), PARITY_TODAY
        )["load"]
        # The canonical value is the number the comma-decimal mapper fix yields.
        canonical_rows = [{"id": PARITY_DAY, "ctl": 58.2, "atl": 60}]
        canonical = read_performance_inputs(
            StubObservationReader(_observations(_snapshot(canonical_rows))),
            None,
            _snapshot(canonical_rows),
        )
        self.assertEqual(legacy["ctl"], "58,2")
        self.assertIsNotNone(canonical)
        self.assertIs(type(_present(canonical).ctl), float)
        self.assertEqual(_present(canonical).ctl, 58.2)


class CanonicalLoadEdgeTests(unittest.TestCase):
    def test_latest_row_without_ctl_yields_none_even_when_an_older_row_has_it(
        self,
    ) -> None:
        rows = [
            {"id": EARLIER_DAY, "ctl": 40, "atl": 45},
            {"id": PARITY_DAY, "atl": 65},
        ]
        legacy, canonical_load, canonical = _load_pair(rows)
        self.assertIsNotNone(canonical)
        self.assertIsNone(_present(canonical).ctl)
        self.assertEqual(_present(canonical).atl, 65.0)
        self.assertIsNone(legacy["ctl"])
        self.assertEqual(_normalized_load(canonical_load), _normalized_load(legacy))

    def test_older_observations_never_replace_the_latest_row(self) -> None:
        rows = [
            {"id": EARLIER_DAY, "ctl": 40, "atl": 45},
            {"id": PARITY_DAY, "ctl": 50, "atl": 60},
        ]
        _legacy, _canonical_load, canonical = _load_pair(rows)
        self.assertEqual(
            canonical,
            CanonicalPerformanceInputs(
                wellness_day=PARITY_TODAY,
                ctl=50.0,
                atl=60.0,
                recovery=_NO_RECOVERY,
                personal_recovery=_NO_PERSONAL_RECOVERY,
                recovery_averages=_NO_RECOVERY_AVERAGES,
            ),
        )

    def test_reader_window_spans_the_snapshot_rows_and_ends_at_the_latest_day(
        self,
    ) -> None:
        rows = [
            {"id": EARLIER_DAY, "ctl": 40, "atl": 45},
            {"id": PARITY_DAY, "ctl": 50, "atl": 60},
        ]
        snapshot = _snapshot(rows)
        reader = StubObservationReader(_observations(snapshot))
        read_performance_inputs(reader, "db", snapshot)
        earliest = date(2026, 9, 19)
        # Current sport values are read for the sync day of the snapshot, +/- 1 day.
        sync_window = (date(2026, 10, 9), date(2026, 10, 11))
        self.assertEqual(
            reader.calls,
            [
                (MetricKind.CTL, earliest, PARITY_TODAY),
                (MetricKind.ATL, earliest, PARITY_TODAY),
                (MetricKind.THRESHOLD_HR, *sync_window),
                (MetricKind.VO2MAX, *sync_window),
                # Weight also reaches back to the latest wellness day it selects.
                (MetricKind.WEIGHT, PARITY_TODAY, sync_window[1]),
                # Recovery values are selected from the earliest wellness day on.
                (MetricKind.SLEEP_SCORE, earliest, None),
                (MetricKind.RESTING_HR, earliest, None),
                (MetricKind.READINESS, earliest, None),
                # Personal recovery: resting HR from 83 days before the wellness day.
                (MetricKind.RESTING_HR, date(2026, 6, 29), None),
            ],
        )

    def test_no_wellness_rows_never_reach_the_reader(self) -> None:
        for snapshot in (_snapshot([]), None):
            with self.subTest(snapshot=snapshot is None):
                reader = StubObservationReader()
                self.assertIsNone(read_performance_inputs(reader, "db", snapshot))
                self.assertEqual(reader.calls, [])

    def test_invalid_latest_day_keeps_the_legacy_values(self) -> None:
        # The latest row is the lexicographic maximum of the ids, so each invalid id
        # is chosen to sort after the valid older row.
        for rows in (
            [{"id": "2026-01-01", "ctl": 50}, {"id": "latest", "ctl": 1}],
            [{"id": "2026-01-01", "ctl": 50}, {"id": "2026-02-30", "ctl": 1}],
            [{"id": "2026-01-01", "ctl": 50}, {"id": "2026-13-01", "ctl": 1}],
            [{"id": "2026-01-01", "ctl": 50}, {"id": "20260920", "ctl": 1}],
        ):
            with self.subTest(rows=rows):
                reader = StubObservationReader()
                self.assertIsNone(
                    read_performance_inputs(reader, "db", _snapshot(rows))
                )
                self.assertEqual(reader.calls, [])

    def test_unusable_ids_outside_the_latest_row_are_ignored_for_the_window(
        self,
    ) -> None:
        rows = [
            {"ctl": 40, "atl": 45},
            {"id": PARITY_DAY, "ctl": 50, "atl": 60},
        ]
        snapshot = _snapshot(rows)
        reader = StubObservationReader(_observations(snapshot))
        inputs = read_performance_inputs(reader, "db", snapshot)
        self.assertEqual(
            inputs,
            CanonicalPerformanceInputs(
                wellness_day=PARITY_TODAY,
                ctl=50.0,
                atl=60.0,
                recovery=_NO_RECOVERY,
                personal_recovery=_NO_PERSONAL_RECOVERY,
                recovery_averages=_NO_RECOVERY_AVERAGES,
            ),
        )
        self.assertEqual(reader.calls[0][1], PARITY_TODAY)

    def test_non_mapping_wellness_entries_and_non_list_fields_are_ignored(
        self,
    ) -> None:
        rows = ["not-a-row", {"id": PARITY_DAY, "ctl": 50, "atl": 60}]
        snapshot = _snapshot(rows)
        inputs = read_performance_inputs(
            StubObservationReader(_observations(_snapshot([rows[1]]))),
            "db",
            snapshot,
        )
        self.assertIsNotNone(inputs)
        self.assertEqual(_present(inputs).ctl, 50.0)
        self.assertIsNone(
            read_performance_inputs(
                StubObservationReader(), "db", {"recent_wellness": "text"}
            )
        )

    def test_load_performance_inputs_reads_each_kind_once_with_the_given_window(
        self,
    ) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        reader = StubObservationReader(_observations(snapshot))
        inputs = load_performance_inputs(
            reader,
            "db",
            latest_wellness_day=PARITY_TODAY,
            start=date(2026, 9, 19),
            end=PARITY_TODAY,
        )
        self.assertEqual(
            inputs,
            CanonicalPerformanceInputs(wellness_day=PARITY_TODAY, ctl=50.0, atl=60.0),
        )
        self.assertEqual(
            reader.calls,
            [
                (MetricKind.CTL, date(2026, 9, 19), PARITY_TODAY),
                (MetricKind.ATL, date(2026, 9, 19), PARITY_TODAY),
            ],
        )
        self.assertEqual(reader.db_seen, ["db", "db"])

    def test_performance_options_is_empty_without_canonical_inputs(self) -> None:
        self.assertEqual(performance_options(None), {})
        inputs = CanonicalPerformanceInputs(wellness_day=PARITY_TODAY, ctl=1.0, atl=2.0)
        self.assertEqual(performance_options(inputs), {"canonical": inputs})

    def test_canonical_inputs_replace_only_ctl_and_atl_in_the_load_block(self) -> None:
        rows = [{"id": PARITY_DAY, "ctl": "55", "atl": 65, "tsb": 3, "rampRate": "1.5"}]
        inputs = CanonicalPerformanceInputs(
            wellness_day=PARITY_TODAY, ctl=1.0, atl=None
        )
        load = performance_load_context(
            [], rows, _latest(rows), PARITY_TODAY, canonical=inputs
        )["load"]
        self.assertEqual(
            load,
            {"id": PARITY_DAY, "ctl": 1.0, "atl": None, "tsb": 3, "rampRate": "1.5"},
        )

    def test_missing_canonical_observation_yields_none_for_that_value(self) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        reader = StubObservationReader(
            tuple(
                observation
                for observation in _observations(snapshot)
                if observation.kind is MetricKind.ATL
            )
        )
        inputs = read_performance_inputs(reader, "db", snapshot)
        self.assertIsNotNone(inputs)
        self.assertIsNone(_present(inputs).ctl)
        self.assertEqual(_present(inputs).atl, 60.0)


class CanonicalWiringTests(unittest.TestCase):
    def test_public_performance_reads_snapshot_and_load_inside_one_unit(self) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        manager = RecordingManager()
        reader = StubObservationReader(_observations(snapshot), events=manager.events)
        source = CanonicalPerformanceSource(
            database_manager=lambda: manager,
            observation_reader=lambda: reader,
        )
        service = _service(snapshot, source)
        with patch(
            "backend.http_api.public_performance.performance_context.current_performance_context",
            return_value={},
        ) as project:
            service.performance_state()
        self.assertEqual(manager.events, ["enter", *["read"] * 9, "exit"])
        self.assertEqual(reader.db_seen, ["db"] * 9)
        self.assertEqual(
            project.call_args.kwargs["canonical"],
            CanonicalPerformanceInputs(
                wellness_day=PARITY_TODAY,
                ctl=50.0,
                atl=60.0,
                recovery=_NO_RECOVERY,
                personal_recovery=_NO_PERSONAL_RECOVERY,
                recovery_averages=_NO_RECOVERY_AVERAGES,
            ),
        )

    def test_public_performance_keeps_the_legacy_call_without_wellness(self) -> None:
        snapshot = _snapshot([])
        manager = RecordingManager()
        reader = StubObservationReader()
        source = CanonicalPerformanceSource(
            database_manager=lambda: manager,
            observation_reader=lambda: reader,
        )
        service = _service(snapshot, source)
        with patch(
            "backend.http_api.public_performance.performance_context.current_performance_context",
            return_value={},
        ) as project:
            service.performance_state()
        project.assert_called_once_with(snapshot, {}, PARITY_PROFILE, PARITY_TODAY)
        self.assertEqual(manager.events, ["enter", "exit"])
        self.assertEqual(reader.calls, [])

    def test_public_performance_without_a_source_uses_no_unit_of_work(self) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        service = _service(snapshot, None)
        with patch(
            "backend.http_api.public_performance.performance_context.current_performance_context",
            return_value={},
        ) as project:
            service.performance_state()
        project.assert_called_once_with(snapshot, {}, PARITY_PROFILE, PARITY_TODAY)

    def test_activity_performance_inputs_share_the_snapshot_unit(self) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        manager = RecordingManager()
        reader = StubObservationReader(_observations(snapshot))
        snapshot_reader = Mock()
        snapshot_reader.latest_snapshot.return_value = snapshot
        service = ActivityAnalysisReadService(
            manager,
            snapshot_reader,
            Mock(),
            Mock(),
            canonical=CanonicalPerformanceSource(
                database_manager=lambda: manager,
                observation_reader=lambda: reader,
            ),
        )
        read_snapshot, canonical = service._performance_inputs()
        self.assertIs(read_snapshot, snapshot)
        self.assertEqual(reader.db_seen, ["db"] * 9)
        self.assertEqual(_present(canonical).ctl, 50.0)

    def test_activity_performance_inputs_without_a_source_read_nothing_extra(
        self,
    ) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        manager = RecordingManager()
        snapshot_reader = Mock()
        snapshot_reader.latest_snapshot.return_value = snapshot
        service = ActivityAnalysisReadService(manager, snapshot_reader, Mock(), Mock())
        read_snapshot, canonical = service._performance_inputs()
        self.assertIs(read_snapshot, snapshot)
        self.assertIsNone(canonical)
        # Only the legacy snapshot read's own unit of work runs.
        self.assertEqual(manager.events, ["enter", "exit"])

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
        manager = RecordingManager()
        reader = StubObservationReader(_observations(snapshot))
        snapshot_reader = Mock()
        snapshot_reader.latest_snapshot.return_value = snapshot
        feedback = Mock()
        feedback.list.return_value = []
        service = ActivityAnalysisReadService(
            manager,
            snapshot_reader,
            Mock(),
            feedback,
            canonical=CanonicalPerformanceSource(
                database_manager=lambda: manager,
                observation_reader=lambda: reader,
            ),
        )
        with patch(
            "backend.performance.activity_read_service.current_performance_context",
            return_value={},
        ) as project:
            service.detail("a1", garmin_snapshot={}, profile={}, today=PARITY_TODAY)
        self.assertEqual(project.call_args.kwargs["canonical"].ctl, 50.0)

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

        def read_snapshot() -> dict[str, Any]:
            manager.events.append("snapshot")
            return snapshot

        read, canonical = coach.read_snapshot(read_snapshot)
        self.assertIs(read, snapshot)
        self.assertEqual(
            manager.events,
            ["enter", "snapshot", *["read"] * 9, "exit"],
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
            self.assertEqual(coach.current_performance(snapshot, canonical), {})
        self.assertEqual(project.call_args.kwargs["canonical"].ctl, 50.0)

    def test_coach_without_a_source_reads_only_the_snapshot(self) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        coach = CoachPerformanceContextReader(
            _profile_stub(), _garmin_stub(), Mock(), lambda: PARITY_TODAY
        )
        self.assertEqual(coach.read_snapshot(lambda: snapshot), (snapshot, None))

    def test_structured_context_pairs_load_with_the_snapshot_it_reads(self) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        inputs = CanonicalPerformanceInputs(
            wellness_day=PARITY_TODAY, ctl=50.0, atl=60.0
        )
        performance = Mock()
        performance.read_snapshot.return_value = (snapshot, inputs)
        repository = Mock()
        service = _structured_service(repository, performance)
        service.build(selection=_performance_selection())
        performance.read_snapshot.assert_called_once_with(repository.latest_snapshot)
        repository.latest_snapshot.assert_not_called()
        performance.current_performance.assert_called_once_with(snapshot, inputs)

    def test_structured_context_with_a_given_snapshot_uses_no_canonical_load(
        self,
    ) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        performance = Mock()
        service = _structured_service(Mock(), performance)
        service.build(snapshot, selection=_performance_selection())
        performance.read_snapshot.assert_not_called()
        performance.current_performance.assert_called_once_with(snapshot, None)

    def test_public_state_prelude_reads_load_inside_its_snapshot_unit(self) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        manager = RecordingManager()
        reader = StubObservationReader(_observations(snapshot), events=manager.events)
        service = _service(
            snapshot,
            CanonicalPerformanceSource(
                database_manager=lambda: manager,
                observation_reader=lambda: reader,
            ),
        )
        prelude = _prelude(snapshot, manager, service.canonical_inputs).read(True)
        self.assertEqual(manager.events, ["enter", *["read"] * 9, "exit"])
        self.assertEqual(
            prelude.performance_inputs,
            CanonicalPerformanceInputs(
                wellness_day=PARITY_TODAY,
                ctl=50.0,
                atl=60.0,
                recovery=_NO_RECOVERY,
                personal_recovery=_NO_PERSONAL_RECOVERY,
                recovery_averages=_NO_RECOVERY_AVERAGES,
            ),
        )
        with patch(
            "backend.http_api.public_performance.performance_context.current_performance_context",
            return_value={},
        ) as project:
            service.from_snapshot(snapshot, prelude.performance_inputs)
        self.assertEqual(project.call_args.kwargs["canonical"].atl, 60.0)

    def test_public_state_prelude_without_inputs_keeps_the_legacy_read(self) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        manager = RecordingManager()
        self.assertIsNone(
            _prelude(snapshot, manager, None).read(True).performance_inputs
        )
        self.assertIsNone(_service(snapshot, None).canonical_inputs("db", snapshot))
        with patch(
            "backend.http_api.public_performance.performance_context.current_performance_context",
            return_value={},
        ) as project:
            _service(snapshot, None).from_snapshot(snapshot)
        project.assert_called_once_with(snapshot, {}, PARITY_PROFILE, PARITY_TODAY)

    def test_coach_performance_without_a_source_keeps_the_legacy_call(self) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
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
            coach.current_performance(snapshot)
        project.assert_called_once_with(snapshot, {}, PARITY_PROFILE, PARITY_TODAY)


def _performance_selection() -> Mock:
    selection = Mock()
    selection.sections = frozenset({"current_performance"})
    return selection


def _structured_service(
    repository: Mock, performance: Mock
) -> CoachStructuredContextService:
    return CoachStructuredContextService(
        repository, Mock(), Mock(), Mock(), Mock(), performance
    )


def _prelude(
    snapshot: dict[str, Any], manager: RecordingManager, inputs: Any
) -> PublicStateLocalPrelude:
    state = Mock()
    state.latest_snapshot.return_value = snapshot
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
        nullcontext(),
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
    garmin.snapshot.return_value = {}
    return garmin


class CanonicalLoadEndToEndTests(CanonicalReadFixture):
    def test_public_performance_from_tables_matches_legacy_after_normalisation(
        self,
    ) -> None:
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)
        self.assertEqual(self.write(selector.summary)["serving"], "tables")
        counting = CountingObservationReader(selector)
        source = CanonicalPerformanceSource(
            database_manager=lambda: self.manager,
            observation_reader=lambda: counting,
        )
        legacy = _service(self.intervals, None, self.garmin).performance_state()
        canonical = _service(self.intervals, source, self.garmin).performance_state()
        self.assertEqual(counting.calls, 9)
        self.assertEqual(_normalized_state(canonical), _normalized_state(legacy))

    def test_selector_chooses_its_source_once_for_both_load_reads(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)
        source = CanonicalPerformanceSource(
            database_manager=lambda: self.manager,
            observation_reader=lambda: selector,
        )
        with patch.object(
            selector, "_serves_tables", wraps=selector._serves_tables
        ) as serves_tables:
            canonical = _service(
                self.intervals, source, self.garmin
            ).performance_state()
        serves_tables.assert_called_once()
        legacy = _service(self.intervals, None, self.garmin).performance_state()
        self.assertEqual(_normalized_state(canonical), _normalized_state(legacy))
