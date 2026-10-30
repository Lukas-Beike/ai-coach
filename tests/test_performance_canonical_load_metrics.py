"""Form, ramp rate and cycling eFTP are read from canonical observations only.

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

from canonical_recovery_support import FilteringReader, NoActivityRows

from backend.canonical.records import FORM_METHOD, FORM_METHOD_VERSION, Observation
from backend.canonical.vocabulary import MetricKind, SourceKind
from backend.performance.canonical_inputs import (
    CanonicalPerformanceInputs,
    read_performance_inputs,
)
from backend.performance.chart_history import analysis_history
from backend.performance.context import current_performance_context
from backend.performance.current_metrics import current_performance_metrics
from backend.performance.garmin_metrics import garmin_performance_metrics
from backend.providers.snapshot_projection import project_intervals_snapshot

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


def _stripped(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The same snapshot without wellness rows and sport settings (the carriers)."""
    athlete = {k: v for k, v in snapshot["athlete"].items() if k != "sport_settings"}
    return {**snapshot, "athlete": athlete, "recent_wellness": []}


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
        as_of=DAY,
    )
    assert inputs is not None
    return inputs


def _context(
    snapshot: dict[str, Any], carrier: dict[str, Any] | None = None
) -> dict[str, Any]:
    canonical = _inputs(snapshot, carrier)
    return current_performance_context(
        _stripped(snapshot) if carrier is None else carrier,
        {},
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
                load = _context(_snapshot([row]))["current_load"]
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
        self.assertEqual(_context(snapshot)["current_load"]["tsb"], form.value.value)

    def test_the_carrier_form_is_never_read(self) -> None:
        mapped = _snapshot([_row(_day(), ctl=50, atl=60)])
        carrier = _snapshot([_row(_day(), ctl=50, atl=60, tsb=99, form=98)])
        self.assertEqual(_context(mapped, carrier)["current_load"]["tsb"], -10.0)

    def test_an_invalid_reported_form_is_unknown_not_derived(self) -> None:
        # Known deviation: the mapper rejects the invalid value and stores no form
        # for the day, where the snapshot reader derived CTL minus ATL.
        load = _context(_snapshot([_row(_day(), ctl=50, atl=60, tsb="fresh")]))
        self.assertIsNone(load["current_load"]["tsb"])

    def test_snapshot_only_latest_day_does_not_displace_observed_form(self) -> None:
        snapshot = _snapshot([_row(_day(1), ctl=50, atl=60), _row(_day())])
        load = _context(snapshot, copy.deepcopy(snapshot))["current_load"]
        self.assertEqual(load["tsb"], -10.0)

    def test_the_seven_day_comparison_averages_the_canonical_form_days(self) -> None:
        rows = [
            _row(_day(8), ctl=60, atl=40),  # outside the window
            _row(_day(6), tsb=-10),
            _row(_day(3), tsb=2),
            _row(_day(0), ctl=60, atl=62),
        ]
        comparison = _context(_snapshot(rows))["comparisons"]["form_tsb"]
        self.assertEqual(comparison["current"], -2.0)
        self.assertEqual(comparison["average"], -3.33)


class RampRateTests(unittest.TestCase):
    def test_ramp_rate_is_the_ctl_change_over_exactly_seven_days(self) -> None:
        rows = [_row(_day(7), ctl=54.1, atl=50), _row(_day(), ctl=58.4, atl=60)]
        snapshot = _snapshot(rows)
        self.assertEqual(_inputs(snapshot).ramp_rate, 4.3)
        load = _context(snapshot)["current_load"]
        self.assertEqual(load["ramp_rate"], 4.3)
        self.assertEqual(load["ramp_rate_source"], RAMP_LABEL)

    def test_ramp_rate_may_be_negative_and_is_rounded_to_two_decimals(self) -> None:
        rows = [_row(_day(7), ctl=60.333), _row(_day(), ctl=58.1)]
        self.assertEqual(_inputs(_snapshot(rows)).ramp_rate, -2.23)

    def test_a_missing_day_gives_no_ramp_rate_and_no_neighbour_is_used(self) -> None:
        rows = [
            _row(_day(8), ctl=50),
            _row(_day(6), ctl=52),
            _row(_day(), ctl=58),
        ]
        load = _context(_snapshot(rows))["current_load"]
        self.assertIsNone(load["ramp_rate"])
        self.assertIsNone(load["ramp_rate_source"])

    def test_eight_days_apart_is_not_a_ramp_rate(self) -> None:
        rows = [_row(_day(8), ctl=50), _row(_day(), ctl=58)]
        self.assertIsNone(_inputs(_snapshot(rows)).ramp_rate)

    def test_a_latest_day_without_ctl_gives_no_ramp_rate(self) -> None:
        snapshot = _snapshot(
            [_row(_day(7), ctl=50), _row(_day(1), ctl=55), _row(_day())]
        )
        self.assertIsNone(_inputs(snapshot, copy.deepcopy(snapshot)).ramp_rate)

    def test_no_wellness_day_gives_no_ramp_rate(self) -> None:
        # The only wellness row has an unusable id, so there is no wellness day.
        self.assertIsNone(
            read_performance_inputs(
                FilteringReader(()),
                None,
                as_of=DAY,
            )
        )

    def test_the_carrier_ramp_rate_is_never_read(self) -> None:
        rows = [_row(_day(7), ctl=54.1), _row(_day(), ctl=58.4, rampRate=9.9)]
        mapped = _snapshot(rows)
        load = _context(mapped, copy.deepcopy(mapped))["current_load"]
        self.assertEqual(load["ramp_rate"], 4.3)
        lone = _snapshot([_row(_day(), ctl=58.4, rampRate=9.9)])
        self.assertIsNone(
            _context(lone, copy.deepcopy(lone))["current_load"]["ramp_rate"]
        )


def _ride(eftp: float | None = None, **fields: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"types": ["Ride"], **fields}
    if eftp is not None:
        entry["eftp"] = eftp
    return entry


class EftpTests(unittest.TestCase):
    ACTIVITY: ClassVar[dict[str, Any]] = {
        "id": "ride-1",
        "type": "Ride",
        "start_date_local": f"{_day(2)}T07:00:00",
        "icu_eftp": 270,
    }

    def _eftp(self, snapshot: dict[str, Any]) -> Any:
        return _context(snapshot)["metrics"]["cycling_eftp_watts"]["value"]

    def test_current_eftp_follows_athlete_then_wellness_then_latest_ride(self) -> None:
        wellness = [_row(_day(), ctl=50, atl=60, sportInfo=[_ride(265)])]
        for name, settings, rows, expected in (
            ("athlete", [_ride(262)], wellness, 262),
            ("wellness", [_ride()], wellness, 265),
            ("latest ride", [_ride()], [_row(_day(), ctl=50, atl=60)], 270),
        ):
            with self.subTest(name):
                snapshot = _snapshot(
                    rows, settings=settings, activities=[self.ACTIVITY]
                )
                self.assertEqual(self._eftp(snapshot), expected)
                self.assertEqual(
                    _context(snapshot)["metrics"]["cycling_eftp_watts"]["source"],
                    INTERVALS,
                )
        none = _snapshot([_row(_day(), ctl=50, atl=60)], settings=[_ride()])
        self.assertIsNone(self._eftp(none))

    def test_the_snapshot_carriers_are_never_read(self) -> None:
        snapshot = _snapshot(
            [_row(_day(), ctl=50, atl=60, sportInfo=[_ride(265)])],
            settings=[_ride(262)],
            activities=[self.ACTIVITY],
        )
        mapped_only = _snapshot([_row(_day(), ctl=50, atl=60)], settings=[_ride()])
        carrier = _snapshot(
            [_row(_day(), ctl=50, atl=60, sportInfo=[_ride(111)])],
            settings=[_ride(222)],
        )
        # The observations decide, not the carrier rows or sport settings.
        carried = _context(mapped_only, carrier)
        self.assertIsNone(carried["metrics"]["cycling_eftp_watts"]["value"])
        stripped = _context(snapshot)
        full = _context(snapshot, copy.deepcopy(snapshot))
        # Other metrics (thresholds, VO2max) still read the carrier sport settings.
        self.assertEqual(stripped["current_load"], full["current_load"])
        self.assertEqual(
            stripped["metrics"]["cycling_eftp_watts"],
            full["metrics"]["cycling_eftp_watts"],
        )
        self.assertEqual(stripped["metrics"]["cycling_eftp_watts"]["value"], 262)
        for key in ("form_tsb", "cycling_eftp_30d"):
            self.assertEqual(stripped["comparisons"][key], full["comparisons"][key])

    def test_a_stale_newest_day_falls_back_to_the_ride_while_history_keeps_days(
        self,
    ) -> None:
        rows = [
            _row(_day(3), ctl=48, atl=50, sportInfo=[_ride(255)]),
            _row(_day(), ctl=50, atl=60),
        ]
        snapshot = _snapshot(rows, settings=[_ride()], activities=[self.ACTIVITY])
        inputs = _inputs(snapshot)
        self.assertEqual(inputs.eftp_by_day, {DAY - timedelta(days=3): 255.0})
        context = _context(snapshot)
        self.assertEqual(context["metrics"]["cycling_eftp_watts"]["value"], 270)
        # 30-day comparison: wellness day (255) and the ride's day (270).
        self.assertEqual(context["comparisons"]["cycling_eftp_30d"]["average"], 262.5)

    def test_run_and_virtual_ride_eftp_are_classified_by_sport(self) -> None:
        rows = [
            _row(
                _day(),
                ctl=50,
                atl=60,
                sportInfo=[
                    {"types": ["Run"], "eftp": 999},
                    {"types": ["VirtualRide"], "eftp": 258},
                    {"types": ["Ride"], "eftp": 240},
                ],
            )
        ]
        snapshot = _snapshot(
            rows,
            settings=[{"types": ["Run"], "eftp": 310}, _ride()],
        )
        self.assertEqual(self._eftp(snapshot), 258)
        self.assertEqual(_inputs(snapshot).eftp_by_day, {DAY: 258.0})

    def test_the_series_bounds_drop_implausible_wellness_values(self) -> None:
        rows = [
            _row(_day(2), ctl=40, sportInfo=[_ride(19)]),
            _row(_day(1), ctl=41, sportInfo=[_ride(2001)]),
            _row(_day(), ctl=42, sportInfo=[_ride(250)]),
        ]
        context = _context(_snapshot(rows))
        self.assertEqual(context["comparisons"]["cycling_eftp_30d"]["average"], 250)

    def test_the_athlete_record_eftp_needs_no_wellness_day(self) -> None:
        # An athlete-only snapshot: no wellness row, so no wellness day. The latest
        # sync's athlete eFTP still reaches the current metrics; the thresholds and
        # the wellness-day eFTP stay absent in this branch.
        snapshot = _snapshot([], settings=[_ride(262, lthr=168)])
        inputs = read_performance_inputs(
            FilteringReader(_observations(snapshot)),
            None,
            activity_reader=NoActivityRows(),
            as_of=DAY,
        )
        assert inputs is not None and inputs.current is not None
        self.assertIsNone(inputs.wellness_day)
        athlete_eftp = inputs.current.athlete_eftp
        assert athlete_eftp is not None
        self.assertEqual(athlete_eftp.value.value, 262)
        self.assertIsNone(inputs.current.wellness_eftp)
        self.assertEqual(inputs.current.bike_threshold_hr, ())
        metrics = current_performance_metrics(
            snapshot,
            {},
            garmin_performance_metrics({}, DAY),
            canonical=inputs.current,
        )
        self.assertEqual(metrics["cycling_eftp_watts"]["value"], 262)
        self.assertEqual(metrics["cycling_eftp_watts"]["source"], INTERVALS)

    def test_an_athlete_without_eftp_has_no_inputs_without_a_wellness_day(self) -> None:
        snapshot = _snapshot([], settings=[_ride(lthr=168)])
        inputs = read_performance_inputs(
            FilteringReader(_observations(snapshot)),
            None,
            activity_reader=NoActivityRows(),
            as_of=DAY,
        )
        assert inputs is not None
        self.assertIsNone(inputs.current)

    def test_without_canonical_inputs_only_the_ride_activity_remains(self) -> None:
        snapshot = _snapshot(
            [_row(_day(), sportInfo=[_ride(265)])],
            settings=[_ride(262)],
            activities=[self.ACTIVITY],
        )
        context = current_performance_context(snapshot, {}, {}, DAY)
        self.assertEqual(context["metrics"]["cycling_eftp_watts"]["value"], 270)
        self.assertEqual(context["comparisons"]["cycling_eftp_30d"]["average"], 270)
        self.assertIsNone(context["current_load"]["tsb"])

    def test_chart_and_body_history_read_the_canonical_series(self) -> None:
        rows = [
            _row(_day(1), weight=70, sportInfo=[_ride(250)]),
            _row(_day(), weight=70, sportInfo=[_ride(260)]),
        ]
        snapshot = _snapshot(rows)
        history = analysis_history(
            _stripped(snapshot), {}, DAY, canonical=_inputs(snapshot)
        )
        points = history["metrics"]["cycling_eftp_watts"][0]["points"]
        self.assertEqual([point["value"] for point in points[-2:]], [250.0, 260.0])
        weekly = next(
            item
            for item in history["body"]["windows"]["12w"]["metrics"]["cycling_w_per_kg"]
            if item["source"] == INTERVALS
        )
        self.assertEqual(weekly["points"][-1]["ftp_watts"], 260.0)


if __name__ == "__main__":
    unittest.main()
