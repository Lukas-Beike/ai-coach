"""Intervals.icu form is read from canonical observations only; eFTP is not read.

Since #1726 the Intervals.icu CTL, ATL and form are only a labelled history
(``intervals_load_history``); the current load is the local curve (M7) and no
ramp rate is derived.

The observations come from the real Intervals.icu mappers, applied to synthetic
snapshots; the snapshot handed to the performance context is stripped of its
wellness rows and sport settings to prove that no carrier row is read (#1412). The
expected values are those the snapshot readers produced for the same data. All
storage is mocked and every provider payload is synthetic.
"""

from __future__ import annotations

import copy
import unittest
from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from canonical_recovery_support import (
    FilteringReader,
    NoActivityRows,
    SnapshotActivityRows,
)
from performance_day_support import snapshot_metrics

from backend.canonical.records import FORM_METHOD, FORM_METHOD_VERSION, Observation
from backend.canonical.vocabulary import MetricKind, SourceKind
from backend.performance.canonical_inputs import (
    EMPTY_PERFORMANCE_INPUTS,
    CanonicalPerformanceInputs,
    read_performance_inputs,
)
from backend.performance.chart_history import analysis_history
from backend.performance.context import current_performance_context
from backend.performance.freshness import GarminSyncStatus
from backend.providers.snapshot_projection import project_intervals_snapshot
from backend.sync.garmin_payload_metrics import garmin_payload_performance_metrics

DAY = date(2026, 9, 20)
RETRIEVED_AT = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
ZONE = ZoneInfo("Europe/Berlin")
RAMP_LABEL = "Intervals.icu CTL (berechnet)"
INTERVALS = "Intervals.icu"


def _day(offset: int = 0) -> str:
    return (DAY - timedelta(days=offset)).isoformat()


def _snapshot(
    rows: list[dict[str, Any]],
    *,
    settings: list[dict[str, Any]] | None = None,
    activities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    athlete: dict[str, Any] = {"id": "athlete-1"}
    if settings is not None:
        athlete["sport_settings"] = settings
    return {
        "synced_at": RETRIEVED_AT.isoformat(),
        "athlete": athlete,
        "recent_wellness": rows,
        "recent_activities": activities or [],
    }


def _observations(snapshot: dict[str, Any]) -> tuple[Observation, ...]:
    _activities, mapped = project_intervals_snapshot(
        snapshot, zone=ZONE, retrieved_at=RETRIEVED_AT
    )
    return tuple(mapped.records)


def _inputs(
    snapshot: dict[str, Any], carrier: dict[str, Any] | None = None
) -> CanonicalPerformanceInputs:
    inputs = read_performance_inputs(
        FilteringReader(_observations(snapshot)),
        None,
        activity_reader=SnapshotActivityRows(snapshot),
        as_of=DAY,
    )
    assert inputs is not None
    return inputs


def _context(
    snapshot: dict[str, Any], carrier: dict[str, Any] | None = None
) -> dict[str, Any]:
    canonical = _inputs(snapshot, carrier)
    return current_performance_context(
        GarminSyncStatus.from_state({}),
        {},
        DAY,
        canonical=canonical,
    )


def _row(day: str, **fields: Any) -> dict[str, Any]:
    return {"id": day, **fields}


class FormTests(unittest.TestCase):
    def test_reported_and_derived_form_match_the_snapshot_readers(self) -> None:
        for name, row, expected in (
            ("reported", _row(_day(), ctl=50, atl=60, tsb=3), 3),
            ("form alias", _row(_day(), ctl=50, atl=60, form="-2,5"), -2.5),
            ("zero is a value", _row(_day(), ctl=50, atl=60, freshness=0), 0),
            ("derived", _row(_day(), ctl=52.1, atl=60.43), -8.33),
        ):
            with self.subTest(name):
                load = _context(_snapshot([row]))["intervals_load_history"]
                self.assertEqual(load["tsb"], expected)

    def test_a_derived_form_keeps_its_value_and_kind_with_its_method_metadata(
        self,
    ) -> None:
        snapshot = _snapshot([_row(_day(), ctl=52.1, atl=60.43)])
        (form,) = [
            record
            for record in _observations(snapshot)
            if record.kind is MetricKind.FORM
        ]
        self.assertIs(form.provenance.source_kind, SourceKind.DERIVED)
        self.assertEqual(form.method, FORM_METHOD)
        self.assertEqual(form.method_version, FORM_METHOD_VERSION)
        self.assertIsNotNone(form.input_fingerprint)
        self.assertEqual(
            _context(snapshot)["intervals_load_history"]["tsb"], form.value.value
        )

    def test_the_carrier_form_is_never_read(self) -> None:
        mapped = _snapshot([_row(_day(), ctl=50, atl=60)])
        carrier = _snapshot([_row(_day(), ctl=50, atl=60, tsb=99, form=98)])
        self.assertEqual(
            _context(mapped, carrier)["intervals_load_history"]["tsb"], -10.0
        )

    def test_an_invalid_reported_form_is_unknown_not_derived(self) -> None:
        # Known deviation: the mapper rejects the invalid value and stores no form
        # for the day, where the snapshot reader derived CTL minus ATL.
        load = _context(_snapshot([_row(_day(), ctl=50, atl=60, tsb="fresh")]))
        self.assertIsNone(load["intervals_load_history"]["tsb"])

    def test_snapshot_only_latest_day_does_not_displace_observed_form(self) -> None:
        snapshot = _snapshot([_row(_day(1), ctl=50, atl=60), _row(_day())])
        load = _context(snapshot, copy.deepcopy(snapshot))["intervals_load_history"]
        self.assertEqual(load["tsb"], -10.0)

    def test_intervals_form_never_feeds_the_current_load_or_comparison(
        self,
    ) -> None:
        rows = [_row(_day(7), ctl=54.1, atl=50), _row(_day(), ctl=58.4, atl=60)]
        context = _context(_snapshot(rows))
        self.assertIsNone(context["current_load"]["tsb"])
        self.assertIsNone(context["comparisons"]["form_tsb"])
        self.assertNotIn("ramp_rate", context["current_load"])
        self.assertEqual(context["intervals_load_history"]["ctl"], 58.4)


def _ride(eftp: float | None = None, **fields: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"types": ["Ride"], **fields}
    if eftp is not None:
        entry["eftp"] = eftp
    return entry


class EftpTests(unittest.TestCase):
    """Stored Intervals.icu eFTP observations feed no view (#1727)."""

    ACTIVITY: ClassVar[dict[str, Any]] = {
        "id": "ride-1",
        "type": "Ride",
        "start_date_local": f"{_day(2)}T07:00:00",
        "icu_eftp": 270,
    }

    def _snapshot(self) -> dict[str, Any]:
        return _snapshot(
            [
                _row(_day(1), ctl=48, atl=50, weight=70, sportInfo=[_ride(255)]),
                _row(_day(), ctl=50, atl=60, weight=70, sportInfo=[_ride(265)]),
            ],
            settings=[_ride(262, lthr=168), {"types": ["Run"], "eftp": 310}],
            activities=[self.ACTIVITY],
        )

    def test_eftp_observations_are_still_stored(self) -> None:
        eftps = [
            item
            for item in _observations(self._snapshot())
            if item.kind is MetricKind.EFTP
        ]
        self.assertTrue(eftps)

    def test_canonical_eftp_feeds_no_metric_or_comparison(self) -> None:
        context = _context(self._snapshot())
        self.assertTrue(context["available"])
        self.assertNotIn("cycling_eftp_watts", context["metrics"])
        self.assertNotIn("cycling_eftp_30d", context["comparisons"])
        self.assertFalse(
            any("eftp" in key for key in (*context["metrics"], *context["comparisons"]))
        )

    def test_the_canonical_inputs_carry_no_eftp(self) -> None:
        inputs = _inputs(self._snapshot())
        for name in ("eftp_by_day", "run_eftp_by_day", "power_curve"):
            self.assertFalse(hasattr(inputs, name), name)
        assert inputs.current is not None
        for name in ("athlete_eftp", "wellness_eftp"):
            self.assertFalse(hasattr(inputs.current, name), name)

    def test_the_athlete_record_thresholds_need_no_wellness_day(self) -> None:
        # An athlete-only snapshot: no wellness row, so no wellness day. The latest
        # sync's athlete thresholds still reach the current metrics; its eFTP not.
        snapshot = _snapshot([], settings=[_ride(262, lthr=168)])
        inputs = read_performance_inputs(
            FilteringReader(_observations(snapshot)),
            None,
            activity_reader=NoActivityRows(),
            as_of=DAY,
        )
        assert inputs is not None and inputs.current is not None
        self.assertIsNone(inputs.wellness_day)
        self.assertEqual(
            [item.value.value for item in inputs.current.bike_threshold_hr], [168]
        )
        metrics = snapshot_metrics(
            snapshot,
            {},
            garmin_payload_performance_metrics({}, DAY),
            canonical=inputs.current,
        )
        self.assertNotIn("cycling_eftp_watts", metrics)

    def test_without_canonical_inputs_no_eftp_remains(self) -> None:
        # Canonical reads (#1416): the context takes no snapshot at all.
        context = current_performance_context(
            GarminSyncStatus.from_state({}), {}, DAY, canonical=EMPTY_PERFORMANCE_INPUTS
        )
        # Without canonical values the context is unavailable (#1416).
        self.assertFalse(context["available"])
        self.assertEqual(context["metrics"], {})
        self.assertNotIn("comparisons", context)
        self.assertNotIn("current_load", context)

    def test_chart_and_body_history_have_no_eftp_series(self) -> None:
        history = analysis_history(
            GarminSyncStatus.from_state({}),
            DAY,
            canonical=_inputs(self._snapshot()),
        )
        self.assertNotIn("cycling_eftp_watts", history["metrics"])
        self.assertNotIn("cycling_power_profile", history)
        for window in history["body"]["windows"].values():
            sources = [item["source"] for item in window["metrics"]["cycling_w_per_kg"]]
            self.assertNotIn(INTERVALS, sources)


if __name__ == "__main__":
    unittest.main()
