"""The heart-rate cap as the target of the exported steps (#1851).

No real Garmin, Wahoo or Intervals.icu account is called; the exports are built
and read as data. Cap values come from the constants table; the worked examples
use literals of their own.

Garmin goes through the Intervals.icu calendar as bpm resolved at export time
(a Garmin workout step cannot hold a percent of the lactate threshold HR); Wahoo
takes the percent of the threshold HR with the plan-header reference.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import MagicMock, Mock

from backend.activities.hr_cap import (
    HR_CAP_PERCENT,
    LOW_PERCENT_KEY,
    PERCENT_KEY,
    SOURCE_DEFAULT,
    SOURCE_KEY,
    effective_caps,
    hr_cap,
    resolved_range,
)
from backend.activities.hr_cap_export import capped_description
from backend.activities.workout_text import structured_steps
from backend.errors import AppError
from backend.planning.hr_cap_sync import record_sent, resync_ids, sent_key
from backend.planning.planned_units import planned_unit_payload_hash
from backend.planning.push_state import attach_push_state
from backend.planning.workout_export import build_planned_workout_export
from backend.providers.intervals_workouts import intervals_event_payload
from backend.providers.wahoo_plan_mapping import WahooPlanReferences
from backend.sync.intervals_workout_export import IntervalsWorkoutExport
from backend.sync.planned_calendar import PlannedCalendarSyncService
from backend.sync.wahoo_workout_export import WahooWorkoutExport

TODAY = date(2026, 11, 9)
LTHR = 163.0
NEW_LTHR = 168.0
FIRST_PCT = 89.0
FOCI = tuple(HR_CAP_PERCENT)
TEXT = "- 10m Z1 HR\n- 40m 75-85% LTHR\n- 2m Z2 Pace"
WORKED_CAP = {PERCENT_KEY: 80.0, LOW_PERCENT_KEY: 65.0, SOURCE_KEY: SOURCE_DEFAULT}


def unit(**overrides: Any) -> dict[str, Any]:
    return {
        "local_id": "u1",
        "date": TODAY.isoformat(),
        "sport": "Run",
        "name": "Dauerlauf",
        "description": TEXT,
        "duration_minutes": 52,
        "target": "AUTO",
        "session_focus": FOCI[0],
        "hr_cap": hr_cap(HR_CAP_PERCENT[FOCI[0]]),
        **overrides,
    }


def every_type():
    for first in (None, FIRST_PCT):
        for focus, cap in effective_caps(first).items():
            yield first, focus, cap


class GarminBpmExportTests(unittest.TestCase):
    def test_worked_example_of_the_exported_range(self) -> None:
        text = capped_description(
            "- 10m Z1 HR\n- 40m Z2 HR", unit(hr_cap=WORKED_CAP), lthr=150.0
        )
        self.assertEqual("- 10m 98-120bpm\n- 40m 98-120bpm", text)  # 97.5 rounds up

    def test_every_type_exports_a_wide_range_up_to_the_cap_in_bpm(self) -> None:
        for first, focus, cap in every_type():
            with self.subTest(focus=focus, measured=first is not None):
                low, high = resolved_range(cap, LTHR) or (0, 0)
                text = capped_description(
                    "- 10m Z1 HR\n- 40m Z2 HR\n- 10m 60-70% LTHR",
                    unit(session_focus=focus, hr_cap=cap),
                    lthr=LTHR,
                )
                self.assertEqual(
                    [
                        f"- 10m {low}-{high}bpm",
                        f"- 40m {low}-{high}bpm",
                        f"- 10m {low}-{high}bpm",
                    ],
                    text.split("\n"),
                )
                self.assertNotIn("Z1", text)
                self.assertNotIn("Z2", text)
                self.assertNotIn("%", text)  # never a percent for Intervals.icu
                steps = structured_steps(text)
                self.assertEqual({"hr"}, {step["kind"] for step in steps})

    def test_pace_and_power_steps_keep_their_targets(self) -> None:
        text = capped_description(TEXT, unit(), lthr=LTHR)
        self.assertTrue(text.endswith("- 2m Z2 Pace"))

    def test_the_exported_bpm_follows_the_lthr_with_the_percent_unchanged(self) -> None:
        item = unit()
        before = capped_description(TEXT, item, lthr=LTHR)
        after = capped_description(TEXT, item, lthr=NEW_LTHR)
        self.assertNotEqual(before, after)
        self.assertEqual(hr_cap(HR_CAP_PERCENT[FOCI[0]]), item["hr_cap"])
        low, high = resolved_range(item["hr_cap"], NEW_LTHR) or (0, 0)
        self.assertIn(f"{low}-{high}bpm", after)

    def test_without_a_known_threshold_the_text_is_sent_as_written(self) -> None:
        for lthr in (None, 0.0):
            self.assertEqual(TEXT, capped_description(TEXT, unit(), lthr=lthr))

    def test_a_unit_without_a_valid_cap_is_sent_as_written(self) -> None:
        for item in (
            unit(hr_cap=None),
            unit(hr_cap={"bpm": 120}),
            {"description": TEXT},
        ):
            self.assertEqual(TEXT, capped_description(TEXT, item, lthr=LTHR))

    def test_ramps_repeats_and_absolute_targets_are_handled(self) -> None:
        text = "- 5m ramp 60-70% LTHR\n\n3x\n- 2m 160-170bpm HR\n- 1m Z1 Pace"
        low, high = resolved_range(unit()["hr_cap"], LTHR) or (0, 0)
        capped = capped_description(text, unit(), lthr=LTHR)
        self.assertEqual(
            f"- 5m ramp {low}-{high}bpm\n\n3x\n- 2m {low}-{high}bpm\n- 1m Z1 Pace",
            capped,
        )
        structured_steps(capped)

    def test_the_intervals_event_carries_the_range_for_every_type(self) -> None:
        for first, focus, cap in every_type():
            with self.subTest(focus=focus, measured=first is not None):
                low, high = resolved_range(cap, LTHR) or (0, 0)
                model = build_planned_workout_export(
                    unit(session_focus=focus, hr_cap=cap), today=TODAY, run_lthr=LTHR
                )
                event = intervals_event_payload("u1", model)
                self.assertIn(f"{low}-{high}bpm", event["description"])
                self.assertNotIn("hr_cap", event)

    def test_the_intervals_event_follows_a_moved_threshold(self) -> None:
        old = build_planned_workout_export(unit(), today=TODAY, run_lthr=LTHR)
        new = build_planned_workout_export(unit(), today=TODAY, run_lthr=NEW_LTHR)
        self.assertNotEqual(old.description, new.description)

    def test_a_unit_without_a_cap_exports_unchanged(self) -> None:
        model = build_planned_workout_export(
            unit(hr_cap=None), today=TODAY, run_lthr=LTHR
        )
        self.assertEqual(TEXT, model.description)


class WahooPercentExportTests(unittest.TestCase):
    """Wahoo resolves the percent with the threshold Pacecraft puts in the plan header."""

    @staticmethod
    def export(threshold_hr: int | None = round(LTHR)) -> WahooWorkoutExport:
        return WahooWorkoutExport(
            Mock(),
            now=lambda: datetime(2026, 11, 9, tzinfo=UTC),
            references=lambda _sport: WahooPlanReferences(threshold_hr=threshold_hr),
        )

    def test_every_type_exports_the_percent_range_on_the_lthr_basis(self) -> None:
        for first, focus, cap in every_type():
            with self.subTest(focus=focus, measured=first is not None):
                payload = self.export().serialize_library(
                    unit(
                        session_focus=focus,
                        hr_cap=cap,
                        description="- 10m Z1 HR\n- 40m Z2 HR\n- 10m Z1 HR",
                    )
                )
                self.assertEqual(round(LTHR), payload["plan"]["header"]["threshold_hr"])
                for interval in payload["plan"]["intervals"]:
                    (entry,) = [
                        t for t in interval["targets"] if t["type"] == "threshold_hr"
                    ]
                    self.assertAlmostEqual(cap[LOW_PERCENT_KEY] / 100, entry["low"])
                    self.assertAlmostEqual(cap[PERCENT_KEY] / 100, entry["high"])

    def test_a_moved_threshold_changes_the_plan_header_and_so_the_unit(self) -> None:
        text = unit(description="- 10m Z1 HR\n- 40m Z2 HR")
        first = self.export(round(LTHR)).serialize_library(text)
        second = self.export(round(NEW_LTHR)).serialize_library(text)
        self.assertNotEqual(
            first["plan"]["header"]["threshold_hr"],
            second["plan"]["header"]["threshold_hr"],
        )

    def test_without_the_threshold_reference_the_plan_is_refused(self) -> None:
        with self.assertRaises(AppError):
            self.export(None).serialize_library(unit(description="- 40m Z2 HR"))


class IntervalsLibraryExportTests(unittest.TestCase):
    """The Intervals.icu library carries the same cap range as the Wahoo export."""

    DESCRIPTION = "- 10m Z1 HR\n- 40m Z2 HR"

    def capped(self) -> dict[str, Any]:
        return unit(description=self.DESCRIPTION, duration_minutes=50)

    @staticmethod
    def percent_range(cap: dict[str, Any]) -> str:
        return f"{cap[LOW_PERCENT_KEY]:g}-{cap[PERCENT_KEY]:g}% LTHR"

    def test_the_library_payload_and_the_wahoo_plan_carry_the_same_range(self) -> None:
        for _first, focus, cap in every_type():
            with self.subTest(focus=focus):
                item = unit(
                    description=self.DESCRIPTION,
                    duration_minutes=50,
                    session_focus=focus,
                    hr_cap=cap,
                )
                payload = IntervalsWorkoutExport(Mock()).serialize_library(item)
                self.assertEqual(
                    f"- 10m {self.percent_range(cap)}\n- 40m {self.percent_range(cap)}",
                    payload["description"],
                )
                wahoo = WahooPercentExportTests.export().serialize_library(item)
                for interval in wahoo["plan"]["intervals"]:
                    (entry,) = [
                        t for t in interval["targets"] if t["type"] == "threshold_hr"
                    ]
                    self.assertAlmostEqual(cap[LOW_PERCENT_KEY] / 100, entry["low"])
                    self.assertAlmostEqual(cap[PERCENT_KEY] / 100, entry["high"])

    def test_the_library_calendar_event_carries_the_range(self) -> None:
        item = self.capped()
        client = Mock()
        client.local_today.return_value = TODAY
        IntervalsWorkoutExport(lambda: client).library_plan(
            "lib1", item, TODAY.isoformat(), today=TODAY
        )
        (event,) = client.plan_library_workout.call_args.args
        self.assertIn(self.percent_range(item["hr_cap"]), event["description"])
        self.assertNotIn("Z2", event["description"])

    def test_the_readback_is_checked_against_the_text_that_was_sent(self) -> None:
        item = self.capped()
        cap = item["hr_cap"]
        step = {
            "units": "%lthr",
            "start": cap[LOW_PERCENT_KEY],
            "end": cap[PERCENT_KEY],
        }
        remote = {
            "type": "Run",
            "moving_time": 3000,
            "icu_training_load": 20,
            "workout_doc": {
                "duration": 3000,
                "steps": [
                    {"duration": 600, "hr": step},
                    {"duration": 2400, "hr": step},
                ],
            },
        }
        export = IntervalsWorkoutExport(Mock())
        export.verify_library_readback(item, remote)
        with self.assertRaises(AppError):
            export.verify_library_readback({**item, "hr_cap": None}, remote)

    def test_a_unit_without_a_cap_is_sent_as_written(self) -> None:
        payload = IntervalsWorkoutExport(Mock()).serialize_library(
            unit(description=self.DESCRIPTION, duration_minutes=50, hr_cap=None)
        )
        self.assertEqual(self.DESCRIPTION, payload["description"])


class CalendarSyncTests(unittest.TestCase):
    """The Intervals.icu calendar push resolves the range and remembers what it sent."""

    @staticmethod
    def service(
        lthr: float | None, kv: Any, export: Any = None
    ) -> PlannedCalendarSyncService:
        export = export or MagicMock()
        export.serialize.side_effect = lambda local_id, model: intervals_event_payload(
            local_id, model
        )
        export.event_external_id.return_value = ""
        return PlannedCalendarSyncService(
            MagicMock(),
            MagicMock(),
            export,
            MagicMock(),
            lambda: "2026-11-09T08:00:00+00:00",
            lambda: TODAY,
            run_lthr_for=lambda _unit: lthr,
            key_values=kv,
        )

    def test_the_event_carries_the_range_resolved_for_the_unit_day(self) -> None:
        item = unit()
        for lthr in (LTHR, NEW_LTHR):
            payload = self.service(lthr, None)._event_payload("u1", item, lthr)
            low, high = resolved_range(item["hr_cap"], lthr) or (0, 0)
            self.assertIn(f"{low}-{high}bpm", payload["description"])

    def test_the_sent_range_is_remembered_so_a_later_threshold_move_is_seen(
        self,
    ) -> None:
        kv = ChangedFlagTests.kv()
        item = unit()
        service = self.service(LTHR, kv)
        service._remember_sent_range("u1", item, LTHR)
        low, high = resolved_range(item["hr_cap"], LTHR) or (0, 0)
        self.assertEqual({sent_key("u1"): f"{low}-{high}"}, kv.store)
        flagged = resync_ids(
            kv, None, [{**item, "sync_status": "synced"}], lambda _u: NEW_LTHR
        )
        self.assertEqual({"u1"}, flagged)

    def test_the_readback_is_checked_against_the_text_that_was_sent(self) -> None:
        item = unit()
        export = MagicMock()
        service = self.service(LTHR, None, export)
        payload = service._event_payload("u1", item, LTHR)
        export.upsert.return_value = [{"id": "e1"}]
        export.event_identity.return_value = "e1"
        service._remote_event("u1", item, payload, "{}")
        sent = export.verify_readback.call_args.args[0]
        self.assertEqual(payload["description"], sent["description"])
        self.assertNotEqual(item["description"], sent["description"])

    def test_a_capped_unit_sent_without_a_threshold_remembers_none(self) -> None:
        kv = ChangedFlagTests.kv()
        self.service(None, kv)._remember_sent_range("u1", unit(), None)
        self.assertEqual({sent_key("u1"): "none"}, kv.store)

    def test_a_unit_without_a_cap_remembers_nothing(self) -> None:
        kv = ChangedFlagTests.kv()
        self.service(LTHR, kv)._remember_sent_range("u1", unit(hr_cap=None), LTHR)
        self.assertEqual({}, kv.store)


class ChangedFlagTests(unittest.TestCase):
    """Garmin's bpm path: a synced unit is changed when only the LTHR moved."""

    @staticmethod
    def kv(sent: dict[str, str] | None = None) -> MagicMock:
        store = dict(sent or {})
        kv = MagicMock()
        kv.get.side_effect = lambda _db, key: store.get(key)
        kv.set.side_effect = lambda _db, key, value: store.__setitem__(key, value)
        kv.delete.side_effect = lambda _db, key: store.pop(key, None)
        kv.store = store
        return kv

    def payload(self, **overrides: Any) -> dict[str, Any]:
        return unit(sync_status="synced", **overrides)

    def test_the_sent_range_is_remembered_and_none_when_no_range_resolved(self) -> None:
        kv = self.kv()
        record_sent(kv, None, "u1", (98, 120))
        self.assertEqual({sent_key("u1"): "98-120"}, kv.store)
        record_sent(kv, None, "u1", None)
        self.assertEqual({sent_key("u1"): "none"}, kv.store)

    def test_a_unit_sent_without_a_threshold_is_flagged_once_one_is_known(
        self,
    ) -> None:
        kv = self.kv()
        item = self.payload()
        record_sent(kv, None, "u1", resolved_range(item["hr_cap"], None))
        self.assertEqual(set(), resync_ids(kv, None, [item], lambda _u: None))
        self.assertEqual({"u1"}, resync_ids(kv, None, [item], lambda _u: LTHR))

    def test_only_a_moved_lthr_flags_a_synced_unit(self) -> None:
        item = self.payload()
        low, high = resolved_range(item["hr_cap"], LTHR) or (0, 0)
        kv = self.kv({sent_key("u1"): f"{low}-{high}"})
        self.assertEqual(set(), resync_ids(kv, None, [item], lambda _u: LTHR))
        self.assertEqual({"u1"}, resync_ids(kv, None, [item], lambda _u: NEW_LTHR))

    def test_nothing_is_flagged_without_a_remembered_range_a_threshold_or_a_sync(
        self,
    ) -> None:
        item = self.payload()
        self.assertEqual(
            set(), resync_ids(self.kv(), None, [item], lambda _u: NEW_LTHR)
        )
        kv = self.kv({sent_key("u1"): "1-2"})
        self.assertEqual(set(), resync_ids(kv, None, [item], lambda _u: None))
        local = unit(sync_status="local")
        self.assertEqual(set(), resync_ids(kv, None, [local], lambda _u: NEW_LTHR))
        plain = self.payload(hr_cap=None)
        self.assertEqual(set(), resync_ids(kv, None, [plain], lambda _u: NEW_LTHR))

    def test_the_calendar_sync_button_returns_for_a_flagged_unit(self) -> None:
        row = {"local_id": "u1", "payload": "{}", "sync_state": "synced"}
        flagged: dict[str, Any] = {}
        attach_push_state([(row, flagged)], {}, {}, {"u1"})
        self.assertTrue(flagged["push_pending"]["intervals"])
        steady: dict[str, Any] = {}
        attach_push_state([(row, steady)], {}, {}, set())
        self.assertFalse(steady["push_pending"]["intervals"])

    def test_a_percent_change_changes_the_unit_hash_but_a_focus_edit_does_not(
        self,
    ) -> None:
        other = unit(hr_cap=hr_cap(HR_CAP_PERCENT[FOCI[0]] - 3))
        self.assertNotEqual(
            planned_unit_payload_hash(unit()), planned_unit_payload_hash(other)
        )
        self.assertEqual(
            planned_unit_payload_hash(unit()),
            planned_unit_payload_hash(unit(session_focus=FOCI[-1])),
        )


if __name__ == "__main__":
    unittest.main()
