"""CTL and ATL read from canonical observations match the legacy load context.

The load-context output is compared after one deliberate normalisation: CTL and ATL
are numbers on the canonical side, while legacy values pass through as the stored
JSON (an int, a numeric string). Both sides are converted with ``float`` before
comparison. The only intended value difference is a comma-decimal CTL such as
"58,2", which canonical reads as 58.2 once the Intervals mapper accepts it.
"""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from typing import Any
from unittest.mock import Mock, patch

from activity_row_support import SnapshotActivityRows
from canonical_detail_support import add_session_record, open_manager
from canonical_read_support import (
    CLOCK_AT,
    ZONE,
    CanonicalReadFixture,
    intervals_snapshot,
    make_selector,
    populate,
    store_garmin,
)
from performance_day_support import current_days

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
    load_performance_inputs,
    read_performance_inputs,
)
from backend.performance.canonical_recovery import (
    RECOVERY_KINDS,
    CanonicalRecoveryInputs,
)
from backend.performance.chart_history import analysis_history
from backend.performance.garmin_canonical import GarminCanonicalMetrics
from backend.performance.load_context import performance_load_context
from backend.providers.snapshot_projection import project_intervals_snapshot
from backend.runtime.ports import ObservationReader
from backend.sync.canonical_table_reader import CanonicalTableReader

PARITY_TODAY = date(2026, 9, 20)
PARITY_DAY = "2026-09-20"
EARLIER_DAY = "2026-09-19"
PARITY_PROFILE = {"timezone": "Europe/Berlin"}
_NO_RECOVERY = CanonicalRecoveryInputs(
    observations={kind: () for kind in RECOVERY_KINDS},
    latest_wellness_day=PARITY_TODAY,
)
# One unbounded read per kind: the wellness and current-metric kinds (with the four
# subjective ratings), then the Garmin performance kinds (with the twelve training
# load and load balance kinds and the four history-chart kinds), the daily totals
# (with resting energy) and the recovery kinds not read before (the weekly HRV
# average), the form and eFTP kinds (#1412), and the athlete-record kinds without
# an earlier read (zone-2 pace, height and W′, #1415).
_UNIT_READS = 51


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
    return {**intervals_snapshot(athlete_weight=False), "recent_wellness": rows}


def _observations(snapshot: dict[str, Any]) -> tuple[Observation, ...]:
    _activities, observations = project_intervals_snapshot(
        snapshot, zone=ZONE, retrieved_at=CLOCK_AT
    )
    return tuple(observations.records)


def _latest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return max(rows, key=lambda row: str(row.get("id") or ""), default={})


def _assert_load_inputs(
    case: unittest.TestCase, inputs: CanonicalPerformanceInputs | None
) -> None:
    """The latest row's load; the wellness rows and current metrics are extra."""
    case.assertEqual(
        replace(
            _present(inputs),
            current=NO_CURRENT_INPUTS,
            wellness_days=None,
            history_wellness_days=None,
            form_by_day=None,
            eftp_by_day=None,
            run_eftp_by_day=None,
        ),
        CanonicalPerformanceInputs(
            wellness_day=PARITY_TODAY,
            ctl=50.0,
            atl=60.0,
            recovery=_NO_RECOVERY,
            garmin=GarminCanonicalMetrics(),
            daily_health={},
        ),
    )


def _present(inputs: CanonicalPerformanceInputs | None) -> CanonicalPerformanceInputs:
    if inputs is None:
        raise AssertionError("expected canonical performance inputs")
    return inputs


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _normalized_load(load: dict[str, Any]) -> dict[str, Any]:
    return {**load, "ctl": _as_float(load["ctl"]), "atl": _as_float(load["atl"])}


# Form, ramp rate and eFTP come from canonical observations only (#1412), so the
# path without canonical inputs has none of them. ``_assert_load_metric_split`` and
# the load tests check the canonical values; the legacy-versus-canonical
# comparisons leave them out.
_LOAD_ONLY_KEYS = ("tsb", "ramp_rate", "ramp_rate_source")


def _without(load: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: value for key, value in load.items() if key not in keys}


def _load_pair(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], CanonicalPerformanceInputs | None]:
    """Return loads without and with canonical inputs for mapped fixture rows."""
    snapshot = _snapshot(rows)
    canonical = read_performance_inputs(
        StubObservationReader(_observations(snapshot)),
        None,
        as_of=PARITY_TODAY,
    )
    days = current_days(rows)
    legacy = performance_load_context(
        [], days, PARITY_TODAY, canonical=EMPTY_PERFORMANCE_INPUTS
    )["load"]
    canonical_load = performance_load_context(
        [], days, PARITY_TODAY, canonical=_present(canonical)
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
    garmin_payload.recent_view.return_value = garmin_snapshot
    garmin_payload.recent_view_in.side_effect = lambda _db: garmin_snapshot
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


def _assert_load_metric_split(
    case: unittest.TestCase, canonical: dict[str, Any], legacy: dict[str, Any]
) -> None:
    """Canonical state shows eFTP, form and the derived ramp rate; the other none.

    The fixture's athlete Ride setting reports eFTP 258 and its latest wellness
    day (2026-10-10) a reported form of -3.6. No CTL exists seven days earlier,
    so the ramp rate stays unknown instead of using the carrier ``rampRate``.
    A no-source state without canonical values is unavailable and shows none.
    """
    served = canonical["performance"]
    absent = legacy["performance"]
    absent_load = absent.get("current_load", {})
    case.assertEqual(served["metrics"]["cycling_eftp_watts"]["value"], 258)
    case.assertIsNone(absent["metrics"].get("cycling_eftp_watts", {}).get("value"))
    case.assertEqual(served["current_load"]["tsb"], -3.6)
    case.assertIsNone(absent_load.get("tsb"))
    for load in (served["current_load"], absent_load):
        case.assertIsNone(load.get("ramp_rate"))
        case.assertIsNone(load.get("ramp_rate_source"))


def _assert_recovery_split(
    case: unittest.TestCase, canonical: dict[str, Any], legacy: dict[str, Any]
) -> None:
    """Canonical state shows recovery values; the no-source state shows none."""
    served = canonical["performance"]["recovery"]
    absent = legacy["performance"].get("recovery", {})
    for key in ("resting_hr_bpm", "hrv_ms", "sleep_score", "readiness", "sleep_hours"):
        case.assertIsNotNone(served[key], key)
        case.assertIsNone(absent.get(key), key)


class CanonicalLoadParityTests(unittest.TestCase):
    def test_canonical_load_keeps_mapped_goldens_without_snapshot_fallback(
        self,
    ) -> None:
        cases = {
            "aliases_and_strings": [
                {"id": EARLIER_DAY, "ctl": 40, "atl": 45},
                {"id": PARITY_DAY, "ctLoad": "55", "atlLoad": 65, "rampRate": "1.5"},
            ],
            "numbers_and_zero": [{"id": PARITY_DAY, "ctl": 50.25, "atl": 0}],
        }
        expected_form = {"aliases_and_strings": -10.0, "numbers_and_zero": 50.25}
        expected_load = {
            "aliases_and_strings": (55.0, 65.0),
            "numbers_and_zero": (50.25, 0.0),
        }
        for name, rows in cases.items():
            with self.subTest(name):
                legacy, canonical_load, canonical = _load_pair(rows)
                self.assertIsNotNone(canonical)
                self.assertEqual(
                    (canonical_load["ctl"], canonical_load["atl"]), expected_load[name]
                )
                self.assertIsNone(legacy["ctl"])
                self.assertIsNone(legacy["atl"])
                # Intended difference: the canonical form is the mapper's derived
                # CTL minus ATL (ctLoad/atlLoad aliases included); the carrier
                # rampRate is ignored and no earlier CTL day exists.
                self.assertEqual(canonical_load["tsb"], expected_form[name])
                self.assertIsNone(canonical_load["ramp_rate"])
                self.assertIsNone(legacy["tsb"])

    def test_comma_decimal_is_mapped_to_a_number(self) -> None:
        legacy_rows = [{"id": PARITY_DAY, "ctl": "58,2", "atl": 60}]
        legacy = performance_load_context(
            [],
            current_days(legacy_rows),
            PARITY_TODAY,
            canonical=EMPTY_PERFORMANCE_INPUTS,
        )["load"]
        # The canonical value is the number the comma-decimal mapper fix yields.
        canonical_rows = [{"id": PARITY_DAY, "ctl": 58.2, "atl": 60}]
        canonical = read_performance_inputs(
            StubObservationReader(_observations(_snapshot(canonical_rows))),
            None,
            as_of=PARITY_TODAY,
        )
        self.assertIsNone(legacy["ctl"])
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
        self.assertIsNone(legacy["atl"])
        self.assertIsNone(canonical_load["ctl"])
        self.assertEqual(canonical_load["atl"], 65.0)

    def test_older_observations_never_replace_the_latest_row(self) -> None:
        rows = [
            {"id": EARLIER_DAY, "ctl": 40, "atl": 45},
            {"id": PARITY_DAY, "ctl": 50, "atl": 60},
        ]
        _legacy, _canonical_load, canonical = _load_pair(rows)
        _assert_load_inputs(self, canonical)

    def test_every_kind_is_read_once_and_the_windows_are_applied_in_memory(
        self,
    ) -> None:
        rows = [
            {"id": EARLIER_DAY, "ctl": 40, "atl": 45},
            {"id": PARITY_DAY, "ctl": 50, "atl": 60},
        ]
        snapshot = _snapshot(rows)
        reader = StubObservationReader(_observations(snapshot))
        inputs = read_performance_inputs(reader, "db", as_of=PARITY_TODAY)
        kinds = [kind for kind, _start, _end in reader.calls]
        # Wellness fields and the current-metric kinds, each read once and unbounded.
        self.assertEqual(len(kinds), len(set(kinds)))
        self.assertIn(MetricKind.THRESHOLD_HR, kinds)
        self.assertEqual(
            {(start, end) for _k, start, end in reader.calls}, {(None, None)}
        )
        self.assertEqual(_present(inputs).wellness_day, PARITY_TODAY)
        self.assertEqual(_present(inputs).ctl, 50.0)

    def test_without_rows_activities_or_observations_there_are_no_inputs(
        self,
    ) -> None:
        self.assertIsNone(
            read_performance_inputs(StubObservationReader(), "db", as_of=PARITY_TODAY)
        )

    def test_a_snapshot_without_wellness_rows_is_rebuilt_from_observations(
        self,
    ) -> None:
        source = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        inputs = read_performance_inputs(
            StubObservationReader(_observations(source)),
            "db",
            as_of=PARITY_TODAY,
        )
        self.assertEqual(_present(inputs).wellness_day, PARITY_TODAY)
        self.assertEqual((_present(inputs).ctl, _present(inputs).atl), (50.0, 60.0))
        self.assertEqual(
            [day.day.isoformat() for day in _present(inputs).wellness_days or ()],
            [PARITY_DAY],
        )

    def test_unusable_ids_outside_the_latest_row_are_ignored_for_the_window(
        self,
    ) -> None:
        rows = [
            {"ctl": 40, "atl": 45},
            {"id": PARITY_DAY, "ctl": 50, "atl": 60},
        ]
        snapshot = _snapshot(rows)
        reader = StubObservationReader(_observations(snapshot))
        _assert_load_inputs(
            self, read_performance_inputs(reader, "db", as_of=PARITY_TODAY)
        )

    def test_non_mapping_wellness_entries_and_non_list_fields_are_ignored(
        self,
    ) -> None:
        rows = ["not-a-row", {"id": PARITY_DAY, "ctl": 50, "atl": 60}]
        inputs = read_performance_inputs(
            StubObservationReader(_observations(_snapshot([rows[1]]))),
            "db",
            as_of=PARITY_TODAY,
        )
        self.assertIsNotNone(inputs)
        self.assertEqual(_present(inputs).ctl, 50.0)
        self.assertIsNone(
            read_performance_inputs(
                StubObservationReader(),
                "db",
                as_of=PARITY_TODAY,
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

    def test_empty_performance_inputs_stand_for_no_canonical_values(self) -> None:
        rows = [{"id": PARITY_DAY, "ctl": "55", "atl": 65, "tsb": 3, "rampRate": "1.5"}]
        load = performance_load_context(
            [], current_days(rows), PARITY_TODAY, canonical=EMPTY_PERFORMANCE_INPUTS
        )["load"]
        self.assertEqual(
            (load["ctl"], load["atl"], load["tsb"], load["ramp_rate"]),
            (None, None, None, None),
        )

    def test_canonical_inputs_replace_only_ctl_and_atl_in_the_load_block(self) -> None:
        rows = [{"id": PARITY_DAY, "ctl": "55", "atl": 65, "tsb": 3, "rampRate": "1.5"}]
        inputs = CanonicalPerformanceInputs(wellness_day=PARITY_TODAY, ctl=1.0, atl=2.0)
        load = performance_load_context(
            [], current_days(rows), PARITY_TODAY, canonical=inputs
        )["load"]
        # Form and ramp rate are not row values: the carrier tsb and rampRate are
        # ignored (#1412), and the inputs hold no form or ramp rate.
        self.assertEqual(
            load,
            {
                "id": PARITY_DAY,
                "ctl": 1.0,
                "atl": 2.0,
                "tsb": None,
                "ramp_rate": None,
                "ramp_rate_source": None,
            },
        )

    def test_missing_canonical_value_does_not_read_the_latest_snapshot_row(
        self,
    ) -> None:
        rows = [{"id": PARITY_DAY, "ctl": "55", "atl": 65, "tsb": 3, "rampRate": "1.5"}]
        inputs = CanonicalPerformanceInputs(
            wellness_day=PARITY_TODAY, ctl=1.0, atl=None
        )
        load = performance_load_context(
            [], current_days(rows), PARITY_TODAY, canonical=inputs
        )["load"]
        self.assertEqual(
            load,
            {
                "id": PARITY_DAY,
                "ctl": 1.0,
                "atl": None,
                "tsb": None,
                "ramp_rate": None,
                "ramp_rate_source": None,
            },
        )
        inputs = CanonicalPerformanceInputs(
            wellness_day=PARITY_TODAY, ctl=None, atl=2.0
        )
        load = performance_load_context(
            [], current_days(rows), PARITY_TODAY, canonical=inputs
        )["load"]
        self.assertEqual((load["ctl"], load["atl"]), (None, 2.0))

    def test_missing_canonical_value_never_falls_back_to_unusable_or_absent(
        self,
    ) -> None:
        inputs = CanonicalPerformanceInputs(
            wellness_day=PARITY_TODAY, ctl=None, atl=None
        )
        cases: dict[str, list[dict[str, Any]]] = {
            "unusable_text": [{"id": PARITY_DAY, "ctl": "invalid", "atl": "n/a"}],
            "absent_in_latest_row": [
                {"id": EARLIER_DAY, "ctl": 40, "atl": 45},
                {"id": PARITY_DAY},
            ],
        }
        for name, rows in cases.items():
            with self.subTest(name):
                load = performance_load_context(
                    [], current_days(rows), PARITY_TODAY, canonical=inputs
                )["load"]
                self.assertEqual((load["ctl"], load["atl"]), (None, None))

    def test_partial_observations_leave_the_other_value_unknown(
        self,
    ) -> None:
        rows = [{"id": PARITY_DAY, "ctl": 50, "atl": 60}]
        snapshot = _snapshot(rows)
        reader = StubObservationReader(
            tuple(
                observation
                for observation in _observations(snapshot)
                if observation.kind is MetricKind.ATL
            )
        )
        canonical = read_performance_inputs(reader, "db", as_of=PARITY_TODAY)
        load = performance_load_context(
            [], current_days(rows), PARITY_TODAY, canonical=_present(canonical)
        )["load"]
        self.assertIsNone(_present(canonical).ctl)
        self.assertEqual((load["ctl"], load["atl"]), (None, 60.0))

    def test_missing_canonical_observation_yields_none_for_that_value(self) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        reader = StubObservationReader(
            tuple(
                observation
                for observation in _observations(snapshot)
                if observation.kind is MetricKind.ATL
            )
        )
        inputs = read_performance_inputs(reader, "db", as_of=PARITY_TODAY)
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
        self.assertEqual(manager.events, ["enter", *["read"] * _UNIT_READS, "exit"])
        self.assertEqual(reader.db_seen, ["db"] * _UNIT_READS)
        _assert_load_inputs(self, project.call_args.kwargs["canonical"])

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
        project.assert_called_once_with(
            snapshot,
            {},
            PARITY_PROFILE,
            PARITY_TODAY,
            canonical=EMPTY_PERFORMANCE_INPUTS,
        )
        self.assertEqual(manager.events, ["enter", "exit"])
        # Only the unbounded wellness reads happen; no windowed read follows.
        self.assertEqual({(s, e) for _k, s, e in reader.calls}, {(None, None)})

    def test_public_performance_without_a_source_uses_no_unit_of_work(self) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        service = _service(snapshot, None)
        with patch(
            "backend.http_api.public_performance.performance_context.current_performance_context",
            return_value={},
        ) as project:
            service.performance_state()
        project.assert_called_once_with(
            snapshot,
            {},
            PARITY_PROFILE,
            PARITY_TODAY,
            canonical=EMPTY_PERFORMANCE_INPUTS,
        )

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
        read_snapshot, canonical, _ = service._performance_inputs(PARITY_TODAY)
        self.assertIs(read_snapshot, snapshot)
        self.assertEqual(reader.db_seen, ["db"] * _UNIT_READS)
        self.assertEqual(_present(canonical).ctl, 50.0)

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
        service = ActivityAnalysisReadService(
            sessions,
            snapshot_reader,
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
            ["enter", "snapshot", *["read"] * _UNIT_READS, "exit"],
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
        performance.read_sources.return_value = (snapshot, inputs, None)
        repository = Mock()
        service = _structured_service(repository, performance)
        service.build(selection=_performance_selection())
        performance.read_sources.assert_called_once_with(repository.latest_snapshot)
        repository.latest_snapshot.assert_not_called()
        performance.current_performance.assert_called_once_with(snapshot, inputs)

    def test_structured_context_with_a_given_snapshot_uses_no_canonical_load(
        self,
    ) -> None:
        snapshot = _snapshot([{"id": PARITY_DAY, "ctl": 50, "atl": 60}])
        performance = Mock()
        service = _structured_service(Mock(), performance)
        service.build(snapshot, selection=_performance_selection())
        performance.read_sources.assert_not_called()
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
        self.assertEqual(manager.events, ["enter", *["read"] * _UNIT_READS, "exit"])
        _assert_load_inputs(self, prelude.performance_inputs)
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
        self.assertIsNone(_service(snapshot, None).canonical_inputs("db"))
        with patch(
            "backend.http_api.public_performance.performance_context.current_performance_context",
            return_value={},
        ) as project:
            _service(snapshot, None).from_snapshot(snapshot)
        project.assert_called_once_with(
            snapshot,
            {},
            PARITY_PROFILE,
            PARITY_TODAY,
            canonical=EMPTY_PERFORMANCE_INPUTS,
        )

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
        project.assert_called_once_with(
            snapshot,
            {},
            PARITY_PROFILE,
            PARITY_TODAY,
            canonical=EMPTY_PERFORMANCE_INPUTS,
        )


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
    garmin.recent_view.return_value = {}
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
        legacy = _service(self.intervals, None, self.garmin).performance_state()
        canonical = _service(self.intervals, source, self.garmin).performance_state()
        self.assertEqual(counting.calls, _UNIT_READS)
        self.assertEqual(canonical["performance"]["current_load"]["ctl"], 53.4)
        self.assertEqual(canonical["performance"]["current_load"]["atl"], 57.0)
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
            canonical = _service(
                self.intervals, source, self.garmin
            ).performance_state()
        read_state.assert_called_once()
        legacy = _service(self.intervals, None, self.garmin).performance_state()
        self.assertEqual(canonical["performance"]["current_load"]["ctl"], 53.4)
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
        snapshot, inputs = reader.read_snapshot(lambda: self.intervals)
        return reader.current_performance(snapshot, inputs)

    def test_before_the_first_backfill_performance_and_coach_are_pending(
        self,
    ) -> None:
        # The data is stored but the backfill never completed: no partial values.
        self.write(lambda db: store_garmin(self, db, self.garmin))
        source = self._source()

        public = _service(self.intervals, source, self.garmin).performance_state()
        coach = self._coach_performance(source)

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
            analysis_history({}, {}, PARITY_TODAY, canonical=EMPTY_PERFORMANCE_INPUTS),
        )
        self.assertNotEqual(
            pending["history"],
            analysis_history(
                self.intervals,
                self.garmin,
                PARITY_TODAY,
                canonical=EMPTY_PERFORMANCE_INPUTS,
            ),
        )
        for focus in pending["training_focus_periods"].values():
            self.assertEqual(focus["classified_sessions"], 0)
            self.assertEqual(focus["zones"], [])

        populate(self)
        served = _service(self.intervals, source, self.garmin).performance_state()
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

        public = _service(self.intervals, source, self.garmin).performance_state()
        self.assertTrue(public["performance"]["available"])
        self.assertTrue(public["performance"]["activities_need_refresh"])
        self.assertTrue(self._coach_performance(source)["activities_need_refresh"])

        self.intervals = raw
        refreshed = _service(self.intervals, source, self.garmin).performance_state()
        self.assertFalse(refreshed["performance"]["activities_need_refresh"])

    def test_activity_detail_inputs_carry_the_read_state(self) -> None:
        source = self._source()
        snapshot_reader = Mock()
        snapshot_reader.latest_snapshot.return_value = self.intervals
        service = ActivityAnalysisReadService(
            self.manager, snapshot_reader, Mock(), Mock(), canonical=source
        )

        _snapshot, pending, _rows = service._performance_inputs(PARITY_TODAY)
        self.assertIs(pending, PENDING_PERFORMANCE_INPUTS)

        populate(self)
        _snapshot, served, _rows = service._performance_inputs(PARITY_TODAY)
        self.assertIsNotNone(served)
        assert served is not None
        self.assertFalse(served.pending)
