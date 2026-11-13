"""Heart-rate caps of recovery, easy and long run units (#1851).

The plan stores percentages only; bpm is resolved from the lactate threshold HR in
effect on the unit's date. Cap values come from the constants table in
``backend/activities/hr_cap.py``; only worked examples of the percent-to-bpm
arithmetic use literals of their own.
"""

from __future__ import annotations

import math
import unittest
from collections.abc import Sequence
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from canonical_domain_support import local_zone_configuration

from backend.activities.hr_cap import (
    EXPORT_FLOOR_BELOW_CAP_PCT,
    EXPORT_FLOOR_PERCENT,
    HR_CAP_PERCENT,
    LOW_PERCENT_KEY,
    MEASURED_MARGIN_PCT,
    PERCENT_KEY,
    RECOVERY_BELOW_EASY_PCT,
    SOURCE_DEFAULT,
    SOURCE_KEY,
    SOURCE_MEASURED,
    cap_label,
    cap_percents,
    cap_table_text,
    effective_caps,
    export_floor_percent,
    hr_cap,
    normalize_hr_cap,
    percent_text,
    resolve_bpm,
    resolved_range,
    stored_cap,
)
from backend.activities.zone_settings import ZoneSettings
from backend.athlete.profile import (
    COACH_READ_ONLY_FIELDS,
    FIRST_THRESHOLD_FIELD,
    ProfileService,
    normalize_profile,
)
from backend.canonical.first_threshold import (
    FIRST_THRESHOLD_BOUNDS,
    FIRST_THRESHOLD_DATE_FIELD,
    FIRST_THRESHOLD_ENTRY_FIELD,
    first_threshold_bpm,
    first_threshold_percent,
    percent_of_lthr,
)
from backend.canonical.vocabulary import Environment, Sport
from backend.coach.profile_update import CoachProfileUpdateService
from backend.coach.tool_schemas import HR_CAP_SCHEMA
from backend.errors import AppError
from backend.performance.current_metrics import coach_thresholds
from backend.performance.planned_targets import heart_rate_cap_execution
from backend.planning import plan_checks, run_hr_cap
from backend.planning.calendar_read_model import _resolved_hr_cap
from backend.planning.plan_guard_service import PlanCheckError, PlanGuardService
from backend.planning.planned_unit_load import estimate_planned_unit
from backend.planning.run_lthr import RunLthr
from backend.planning.session_focus import normalize_session_focus
from backend.providers.garmin_zone_mapping import map_garmin_heart_rate_zones

LTHR = 163.0
NEW_LTHR = 168.0
FIRST_PCT = 89.0  # a measured first threshold, percent of the LTHR
TODAY = date(2026, 11, 9)
BERLIN = ZoneInfo("Europe/Berlin")
FOCI = tuple(HR_CAP_PERCENT)


def unit(focus: str = FOCI[0], **overrides: Any) -> dict[str, Any]:
    return {
        "local_id": f"u-{focus}",
        "date": "2026-11-10",
        "sport": "run",
        "name": "Dauerlauf",
        "description": "- 40m Z2 HR",
        "planned_duration_s": 2400,
        "session_focus": focus,
        **overrides,
    }


def with_cap(
    focus: str, first: float | None = None, **overrides: Any
) -> dict[str, Any]:
    return unit(focus, hr_cap=effective_caps(first)[focus], **overrides)


def garmin_set(lthr: float, fetched_on: str, record: str) -> Any:
    """A dated Garmin watch zone set whose lactate threshold HR is ``lthr``."""
    node = {
        "sport": "DEFAULT",
        "trainingMethod": "LACTATE_THRESHOLD",
        "lactateThresholdHeartRateUsed": lthr,
        "maxHeartRateUsed": 190,
        "zone1Floor": 100,
        "zone2Floor": 120,
        "zone3Floor": 140,
        "zone4Floor": 155,
        "zone5Floor": 170,
        "fetchedOn": fetched_on,
    }
    return map_garmin_heart_rate_zones(
        node,
        source_record_id=record,
        retrieved_at=datetime(2026, 11, 1, 8, 0, tzinfo=UTC),
        zone=BERLIN,
    )


def lthr_on(configurations, day: date) -> float | None:
    return ZoneSettings.from_configurations(
        configurations, Sport.RUN, Environment.OUTDOOR, day
    ).lthr


class CapTableTests(unittest.TestCase):
    def test_worked_examples_of_the_percent_to_bpm_arithmetic(self) -> None:
        cap = {PERCENT_KEY: 80.0, LOW_PERCENT_KEY: 65.0, SOURCE_KEY: SOURCE_DEFAULT}
        self.assertEqual(120, resolve_bpm(80.0, 150.0))
        self.assertEqual((98, 120), resolved_range(cap, 150.0))  # 97.5 rounds up
        self.assertEqual((104, 128), resolved_range(cap, 160.0))
        self.assertEqual(142, resolve_bpm(87.0, 163.0))  # 141.81
        self.assertEqual(128, resolve_bpm(80.0, 160.0))

    def test_a_cap_is_percentages_and_a_source_only(self) -> None:
        for focus, percent in HR_CAP_PERCENT.items():
            with self.subTest(focus=focus):
                cap = hr_cap(percent)
                self.assertEqual({PERCENT_KEY, LOW_PERCENT_KEY, SOURCE_KEY}, set(cap))
                self.assertEqual(percent, cap[PERCENT_KEY])
                self.assertEqual(export_floor_percent(percent), cap[LOW_PERCENT_KEY])
                self.assertEqual(
                    cap, stored_cap({"hr_cap": cap, "session_focus": focus})
                )

    def test_the_lower_bound_is_the_table_percent_but_never_above_the_cap_gap(
        self,
    ) -> None:
        for percent in HR_CAP_PERCENT.values():
            self.assertEqual(
                min(EXPORT_FLOOR_PERCENT, percent - EXPORT_FLOOR_BELOW_CAP_PCT),
                export_floor_percent(percent),
            )
        close = EXPORT_FLOOR_PERCENT + EXPORT_FLOOR_BELOW_CAP_PCT - 5
        self.assertEqual(
            close - EXPORT_FLOOR_BELOW_CAP_PCT, export_floor_percent(close)
        )

    def test_bpm_is_never_invented(self) -> None:
        percent = HR_CAP_PERCENT[FOCI[0]]
        for lthr in (None, 0.0, -3.0):
            self.assertIsNone(resolve_bpm(percent, lthr))
            self.assertIsNone(resolved_range(hr_cap(percent), lthr))

    def test_the_card_label_is_percent_then_the_current_bpm_then_the_source(
        self,
    ) -> None:
        cap = hr_cap(HR_CAP_PERCENT[FOCI[0]])
        bpm = resolve_bpm(cap[PERCENT_KEY], LTHR)
        self.assertEqual(
            f"≤ {percent_text(cap[PERCENT_KEY])} % LSHF · {bpm} bpm · Standard",
            cap_label(cap, LTHR),
        )
        self.assertEqual(
            f"≤ {percent_text(cap[PERCENT_KEY])} % LSHF · Standard", cap_label(cap)
        )
        measured = hr_cap(HR_CAP_PERCENT[FOCI[0]], SOURCE_MEASURED)
        self.assertTrue(cap_label(measured, LTHR).endswith("gemessen"))

    def test_a_cap_left_over_from_another_focus_does_not_apply(self) -> None:
        cap = hr_cap(HR_CAP_PERCENT[FOCI[0]])
        for focus in ("threshold", "tempo", None):
            item = {
                "hr_cap": cap,
                **({} if focus is None else {"session_focus": focus}),
            }
            self.assertIsNone(stored_cap(item))

    def test_a_measured_threshold_that_no_cap_can_satisfy_falls_back_to_the_defaults(
        self,
    ) -> None:
        percents, source = cap_percents(40.0)
        self.assertEqual((dict(HR_CAP_PERCENT), SOURCE_DEFAULT), (percents, source))
        for percent in effective_caps(40.0).values():
            normalize_hr_cap(percent)  # every expected value is storable

    def test_malformed_caps_are_rejected(self) -> None:
        good = hr_cap(HR_CAP_PERCENT[FOCI[0]])
        for value in (
            "81",
            {PERCENT_KEY: 81},
            {**good, "bpm": 132},
            {**good, SOURCE_KEY: "guessed"},
            {**good, PERCENT_KEY: "x"},
            {**good, PERCENT_KEY: True},
            {**good, PERCENT_KEY: 500.0},
            {**good, LOW_PERCENT_KEY: good[PERCENT_KEY] + 1},
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_hr_cap(value)
        self.assertIsNone(stored_cap({"hr_cap": {PERCENT_KEY: 81}}))

    def test_the_tool_schema_names_every_cap_from_the_table_and_no_bpm(self) -> None:
        self.assertIn(cap_table_text(), HR_CAP_SCHEMA["description"])
        self.assertEqual(
            {PERCENT_KEY, LOW_PERCENT_KEY, SOURCE_KEY}, set(HR_CAP_SCHEMA["properties"])
        )

    def test_the_coach_thresholds_carry_each_cap_in_percent_and_the_current_bpm(
        self,
    ) -> None:
        metrics = {
            key: {"value": value, "source": "Garmin Connect"}
            for key, value in {
                "cycling_ftp_watts": 250,
                "max_hr_bpm": 190,
                "bike_threshold_hr_bpm": 160,
                "run_threshold_hr_bpm": LTHR,
            }.items()
        }
        caps = coach_thresholds(metrics)["run_hr_caps"]
        self.assertEqual(set(FOCI), set(caps))
        for focus, cap in effective_caps(None).items():
            low, high = resolved_range(cap, LTHR) or (0, 0)
            self.assertEqual({**cap, "low_bpm": low, "bpm": high}, caps[focus])
        measured = coach_thresholds(metrics, FIRST_PCT)["run_hr_caps"]
        self.assertEqual(
            {SOURCE_MEASURED}, {item[SOURCE_KEY] for item in measured.values()}
        )
        metrics["run_threshold_hr_bpm"]["value"] = None
        unknown = coach_thresholds(metrics)["run_hr_caps"]
        self.assertEqual(effective_caps(None), unknown)  # percent only, no bpm


class LthrChangeTests(unittest.TestCase):
    """The watch's own LTHR moves between dated zone sets; the stored percent stays."""

    def configurations(self):
        return [
            *garmin_set(LTHR, "2026-11-01", "heart_rate_zones/2026-11-01-default"),
            *garmin_set(NEW_LTHR, "2026-11-20", "heart_rate_zones/2026-11-20-default"),
        ]

    def test_the_dated_garmin_set_decides_the_threshold_on_each_day(self) -> None:
        configurations = self.configurations()
        self.assertEqual(LTHR, lthr_on(configurations, date(2026, 11, 10)))
        self.assertEqual(NEW_LTHR, lthr_on(configurations, date(2026, 11, 21)))

    def test_local_zones_come_first(self) -> None:
        local = local_zone_configuration(
            sport=Sport.RUN, threshold=150.0, limits=(120.0, 130.0, 140.0, 150.0, 190.0)
        )
        configurations = [*self.configurations(), local]
        self.assertEqual(150.0, lthr_on(configurations, date(2026, 11, 21)))

    def test_the_bpm_moves_with_the_lthr_while_the_percent_stays(self) -> None:
        cap = hr_cap(HR_CAP_PERCENT[FOCI[1]])
        before = resolved_range(cap, lthr_on(self.configurations(), date(2026, 11, 10)))
        after = resolved_range(cap, lthr_on(self.configurations(), date(2026, 11, 21)))
        assert before is not None and after is not None
        self.assertGreater(after[1], before[1])
        self.assertGreater(after[0], before[0])
        self.assertEqual(hr_cap(HR_CAP_PERCENT[FOCI[1]]), cap)  # nothing was rewritten

    def test_the_card_reads_the_bpm_of_the_unit_day_without_an_edit(self) -> None:
        row = with_cap(FOCI[1], date="2026-11-21")
        entry = _resolved_hr_cap(row, [], self.configurations())
        low, high = resolved_range(row["hr_cap"], NEW_LTHR) or (0, 0)
        self.assertEqual({"hr_cap_bpm": {"low": low, "high": high}}, entry)
        earlier = _resolved_hr_cap(
            {**row, "date": "2026-11-10"}, [], self.configurations()
        )
        self.assertEqual(
            (resolved_range(row["hr_cap"], LTHR) or (0, 0))[1],
            earlier["hr_cap_bpm"]["high"],
        )

    def test_without_a_threshold_the_card_shows_percent_only(self) -> None:
        self.assertEqual({}, _resolved_hr_cap(with_cap(FOCI[0]), [], []))


class MeasuredFirstThresholdTests(unittest.TestCase):
    def test_easy_and_long_follow_the_threshold_minus_the_margin(self) -> None:
        percents, source = cap_percents(FIRST_PCT)
        self.assertEqual(SOURCE_MEASURED, source)
        easy = math.floor((FIRST_PCT - MEASURED_MARGIN_PCT) * 10) / 10
        self.assertEqual(easy, percents["easy"])
        self.assertEqual(easy, percents["long"])

    def test_recovery_is_the_lower_of_its_default_and_easy_minus_the_gap(self) -> None:
        percents, _ = cap_percents(FIRST_PCT)
        gap = percents["easy"] - RECOVERY_BELOW_EASY_PCT
        self.assertAlmostEqual(
            min(HR_CAP_PERCENT["recovery"], gap), percents["recovery"]
        )
        high, _ = cap_percents(99.0)
        self.assertEqual(HR_CAP_PERCENT["recovery"], high["recovery"])
        low, _ = cap_percents(70.0)
        self.assertLess(low["recovery"], HR_CAP_PERCENT["recovery"])

    def test_without_one_or_with_an_implausible_one_the_defaults_apply(self) -> None:
        for value in (None, 5.0, 130.0):
            percents, source = cap_percents(value)
            self.assertEqual((dict(HR_CAP_PERCENT), SOURCE_DEFAULT), (percents, source))

    def test_a_measured_cap_passes_and_a_default_one_does_not(self) -> None:
        self.assertIsNone(
            run_hr_cap.cap_problem(with_cap("easy", FIRST_PCT), FIRST_PCT)
        )
        problem = run_hr_cap.cap_problem(with_cap("easy"), FIRST_PCT)
        assert problem is not None
        self.assertIn(
            problem["reason"], {run_hr_cap.TOO_HIGH, run_hr_cap.SOURCE_MISMATCH}
        )
        self.assertEqual(SOURCE_MEASURED, problem["cap_source"])
        self.assertEqual(effective_caps(FIRST_PCT)["easy"], problem["expected"])

    def test_a_measured_cap_without_a_measured_threshold_is_a_source_mismatch(
        self,
    ) -> None:
        measured = effective_caps(FIRST_PCT)["easy"]
        lower = hr_cap(measured[PERCENT_KEY] - 20, SOURCE_MEASURED)
        problem = run_hr_cap.cap_problem(unit("easy", hr_cap=lower), None)
        assert problem is not None
        self.assertEqual(run_hr_cap.SOURCE_MISMATCH, problem["reason"])


class FirstThresholdConversionTests(unittest.TestCase):
    """The athlete enters bpm; the profile stores percent of the LTHR on that date."""

    def service(self, lthr_by_day: dict[date | None, float | None]) -> ProfileService:
        return ProfileService(
            MagicMock(),
            MagicMock(),
            MagicMock(),
            on_location_changed=MagicMock(),
            mutation_coordinator=MagicMock(),
            run_lthr_on=lambda day: lthr_by_day.get(day),
        )

    def test_bpm_becomes_percent_of_the_lthr_on_the_measurement_date(self) -> None:
        service = self.service({None: 160.0, date(2026, 10, 1): 150.0})
        entered = service._with_first_threshold({FIRST_THRESHOLD_ENTRY_FIELD: "144"})
        self.assertEqual("90", entered[FIRST_THRESHOLD_FIELD])  # 144 / 160
        dated = service._with_first_threshold(
            {
                FIRST_THRESHOLD_ENTRY_FIELD: "144",
                FIRST_THRESHOLD_DATE_FIELD: "2026-10-01",
            }
        )
        self.assertEqual("96", dated[FIRST_THRESHOLD_FIELD])  # 144 / 150
        stored = normalize_profile(dated)
        # The entry fields are consumed; a stored profile never has them.
        self.assertNotIn(FIRST_THRESHOLD_ENTRY_FIELD, stored)
        self.assertNotIn(FIRST_THRESHOLD_DATE_FIELD, stored)
        self.assertEqual("96", stored[FIRST_THRESHOLD_FIELD])
        self.assertEqual(90.0, percent_of_lthr(144.0, 160.0))

    def test_no_entry_leaves_the_stored_percent_alone(self) -> None:
        profile = {FIRST_THRESHOLD_FIELD: "88"}
        self.assertEqual(profile, self.service({})._with_first_threshold(profile))

    def test_without_a_known_threshold_the_entry_is_refused(self) -> None:
        with self.assertRaises(AppError):
            self.service({})._with_first_threshold({FIRST_THRESHOLD_ENTRY_FIELD: "145"})

    def test_implausible_entries_are_refused(self) -> None:
        service = self.service({None: LTHR})
        low, high = FIRST_THRESHOLD_BOUNDS
        for text in ("x", str(low - 1), str(high + 1)):
            with self.subTest(text=text), self.assertRaises(AppError):
                service._with_first_threshold({FIRST_THRESHOLD_ENTRY_FIELD: text})
        with self.assertRaises(AppError):
            service._with_first_threshold(
                {FIRST_THRESHOLD_ENTRY_FIELD: "145", FIRST_THRESHOLD_DATE_FIELD: "x"}
            )

    def test_the_profile_keeps_a_plausible_percent_and_rejects_others(self) -> None:
        kept = normalize_profile({FIRST_THRESHOLD_FIELD: "88"})
        self.assertEqual("88", kept[FIRST_THRESHOLD_FIELD])
        self.assertEqual("", normalize_profile({})[FIRST_THRESHOLD_FIELD])
        cleared = normalize_profile({FIRST_THRESHOLD_FIELD: "9"})
        self.assertEqual("", cleared[FIRST_THRESHOLD_FIELD])
        with self.assertRaises(AppError):
            normalize_profile({FIRST_THRESHOLD_FIELD: "9"}, validate_timezone=True)

    def test_parsers_read_profile_text(self) -> None:
        self.assertEqual(145.0, first_threshold_bpm(" 145 "))
        self.assertEqual(145.5, first_threshold_bpm("145,5"))
        self.assertEqual(88.0, first_threshold_percent("88"))
        for text in ("", "x", "nan", "5", "300"):
            self.assertIsNone(first_threshold_bpm(text))
        self.assertIsNone(first_threshold_percent("5"))

    def test_the_coach_can_read_but_never_write_it(self) -> None:
        self.assertIn(FIRST_THRESHOLD_FIELD, COACH_READ_ONLY_FIELDS)
        # The entry fields are no profile fields at all.
        for field in (
            FIRST_THRESHOLD_FIELD,
            FIRST_THRESHOLD_ENTRY_FIELD,
            FIRST_THRESHOLD_DATE_FIELD,
        ):
            service = CoachProfileUpdateService(MagicMock(), MagicMock(), MagicMock())
            change = {"field": field, "expected_value": "", "value": "150"}
            with (
                patch(
                    "backend.coach.profile_update.authorized_operations",
                    return_value={"update_profile"},
                ),
                patch("backend.coach.profile_update.require_coach_scope"),
                self.assertRaises(AppError) as raised,
            ):
                service.apply({"changes": [change]}, {})
            self.assertEqual("tool_arguments_invalid", raised.exception.reason)


class CapProblemTests(unittest.TestCase):
    def test_a_right_cap_has_no_problem(self) -> None:
        for focus in FOCI:
            with self.subTest(focus=focus):
                self.assertIsNone(run_hr_cap.cap_problem(with_cap(focus)))

    def test_a_missing_cap_is_named_with_the_value_to_write(self) -> None:
        for focus in FOCI:
            with self.subTest(focus=focus):
                problem = run_hr_cap.cap_problem(unit(focus))
                assert problem is not None
                self.assertEqual(run_hr_cap.MISSING, problem["reason"])
                value = hr_cap(HR_CAP_PERCENT[focus])
                self.assertEqual(value, problem["expected"])
                text = run_hr_cap.message(problem)
                self.assertIn(percent_text(value[PERCENT_KEY]), text)
                self.assertIn(percent_text(value[LOW_PERCENT_KEY]), text)

    def test_a_percent_above_the_table_value_is_too_high(self) -> None:
        for focus in FOCI:
            with self.subTest(focus=focus):
                high = unit(focus, hr_cap=hr_cap(HR_CAP_PERCENT[focus] + 1))
                problem = run_hr_cap.cap_problem(high)
                assert problem is not None
                self.assertEqual(run_hr_cap.TOO_HIGH, problem["reason"])
                self.assertEqual(hr_cap(HR_CAP_PERCENT[focus]), problem["expected"])

    def test_a_lower_percent_with_its_matching_lower_bound_is_allowed(self) -> None:
        low = unit(FOCI[0], hr_cap=hr_cap(HR_CAP_PERCENT[FOCI[0]] - 3))
        self.assertIsNone(run_hr_cap.cap_problem(low))

    def test_a_lower_bound_that_does_not_belong_to_the_percent_is_named(self) -> None:
        cap = hr_cap(HR_CAP_PERCENT[FOCI[0]])
        wrong = unit(FOCI[0], hr_cap={**cap, LOW_PERCENT_KEY: cap[LOW_PERCENT_KEY] - 5})
        problem = run_hr_cap.cap_problem(wrong)
        assert problem is not None
        self.assertEqual(run_hr_cap.LOW_MISMATCH, problem["reason"])

    def test_a_malformed_cap_is_named(self) -> None:
        problem = run_hr_cap.cap_problem(unit(FOCI[0], hr_cap={"percent_lthr": "x"}))
        assert problem is not None
        self.assertEqual(run_hr_cap.MALFORMED, problem["reason"])

    def test_other_units_have_no_cap_to_check(self) -> None:
        unset = unit(FOCI[0])
        del unset["session_focus"]
        for item in (
            unit("threshold"),
            unit(FOCI[0], sport="ride"),
            unit("upper", sport="strength"),
            unset,
        ):
            self.assertIsNone(run_hr_cap.cap_problem(item))


class CapFindingTests(unittest.TestCase):
    def test_the_code_blocks_like_strength_incomplete_and_can_not_be_accepted(
        self,
    ) -> None:
        self.assertIn("hr_cap_invalid", plan_checks.REQUIRED_CODES)
        self.assertNotIn("hr_cap_invalid", plan_checks.BLOCKING_CODES)
        self.assertIn("hr_cap_invalid", plan_checks.FINDING_CODES)
        (finding,) = plan_checks.hr_cap_invalid([unit(FOCI[0])])
        self.assertTrue(finding["blocking"])
        self.assertEqual(["u-" + FOCI[0]], finding["local_ids"])
        self.assertIn("hr_cap", finding["message"])

    def test_only_a_changed_unit_is_a_new_finding(self) -> None:
        old = unit(FOCI[0])
        before = plan_checks.hr_cap_invalid([old])
        edited = plan_checks.hr_cap_invalid([{**old, "description": "- 50m Z2 HR"}])
        self.assertEqual([], plan_checks.new_findings(before, before))
        self.assertEqual(1, len(plan_checks.new_findings(before, edited)))


class GuardTests(unittest.TestCase):
    def guard(
        self, units: list[dict[str, Any]], first: float | None = None
    ) -> PlanGuardService:
        return PlanGuardService(
            planned_units=lambda: list(units),
            completed_activities=list,
            competitions=list,
            illness=lambda: "",
            progress=lambda: {"week_list": []},
            training_model=lambda: "pyramidal",
            today=lambda: TODAY,
            estimate_unit=lambda item: estimate_planned_unit(item, ZoneSettings()),
            profile=lambda: (
                {} if first is None else {FIRST_THRESHOLD_FIELD: str(first)}
            ),
        )

    def test_a_coach_write_without_a_cap_is_rejected_with_the_percentages(self) -> None:
        before = self.guard([]).findings()
        with self.assertRaises(PlanCheckError) as raised:
            self.guard([unit(FOCI[0])]).verify(before, accepted=["hr_cap_invalid"])
        (finding,) = [
            item
            for item in raised.exception.findings
            if item["code"] == "hr_cap_invalid"
        ]
        self.assertIn(percent_text(HR_CAP_PERCENT[FOCI[0]]), finding["message"])

    def test_a_right_cap_passes_even_without_any_known_threshold(self) -> None:
        self.guard([with_cap(FOCI[0])]).verify([], accepted=[])

    def test_the_measured_threshold_changes_what_is_right(self) -> None:
        with self.assertRaises(PlanCheckError):
            self.guard([with_cap(FOCI[1])], FIRST_PCT).verify([], accepted=[])
        self.guard([with_cap(FOCI[1], FIRST_PCT)], FIRST_PCT).verify([], accepted=[])


class NormalizeTests(unittest.TestCase):
    def test_a_run_unit_keeps_a_valid_cap(self) -> None:
        record = with_cap(FOCI[0])
        normalize_session_focus(record)
        self.assertEqual(hr_cap(HR_CAP_PERCENT[FOCI[0]]), record["hr_cap"])

    def test_other_sports_and_malformed_caps_are_rejected(self) -> None:
        with self.assertRaises(AppError):
            normalize_session_focus(unit("upper", sport="strength", hr_cap={}))
        with self.assertRaises(AppError):
            normalize_session_focus(unit(FOCI[0], hr_cap={"percent_lthr": 81}))


class AnalysisTests(unittest.TestCase):
    @staticmethod
    def streams(values: Sequence[float]) -> dict[str, Any]:
        return {
            "time_s": [float(i) for i in range(len(values))],
            "channels": {"heart_rate_bpm": {"values": values}},
        }

    def test_the_session_is_judged_against_the_stored_cap_in_bpm_of_its_day(
        self,
    ) -> None:
        cap = hr_cap(HR_CAP_PERCENT[FOCI[1]])
        bpm = resolve_bpm(cap[PERCENT_KEY], LTHR) or 0
        cases = {
            "within_target": [bpm - 15] * 600,
            "upper_edge": [bpm - 3] * 600,
            "above_cap": [bpm + 6] * 600,
        }
        for verdict, values in cases.items():
            with self.subTest(verdict=verdict):
                result = heart_rate_cap_execution(cap, LTHR, self.streams(values))
                self.assertEqual(verdict, result["verdict"])
                self.assertEqual(cap_label(cap, LTHR), result["cap_label"])
                self.assertEqual(bpm, result["cap_bpm"])

    def test_the_same_run_is_judged_by_the_new_threshold_after_it_moved(self) -> None:
        cap = hr_cap(HR_CAP_PERCENT[FOCI[1]])
        bpm = resolve_bpm(cap[PERCENT_KEY], LTHR) or 0
        run = self.streams([bpm + 3] * 600)
        self.assertEqual(
            "above_cap", heart_rate_cap_execution(cap, LTHR, run)["verdict"]
        )
        self.assertNotEqual(
            "above_cap", heart_rate_cap_execution(cap, NEW_LTHR, run)["verdict"]
        )

    def test_time_above_the_cap_counts_even_with_a_low_mean(self) -> None:
        cap = hr_cap(HR_CAP_PERCENT[FOCI[1]])
        bpm = resolve_bpm(cap[PERCENT_KEY], LTHR) or 0
        values = [bpm - 25] * 400 + [bpm + 4] * 200
        result = heart_rate_cap_execution(cap, LTHR, self.streams(values))
        self.assertEqual("above_cap", result["verdict"])
        self.assertGreater(result["time_above_cap_pct"], 10)

    def test_without_a_stream_or_a_threshold_it_is_not_covered(self) -> None:
        cap = hr_cap(HR_CAP_PERCENT[FOCI[0]])
        self.assertEqual(
            "not_covered", heart_rate_cap_execution(cap, LTHR, None)["status"]
        )
        unknown = heart_rate_cap_execution(cap, None, self.streams([120.0] * 60))
        self.assertEqual("not_covered", unknown["status"])
        self.assertNotIn("cap_bpm", unknown)


class RunLthrTests(unittest.TestCase):
    """One snapshot of the run thresholds answers per unit date, as zones or as LTHR."""

    def lookup(self, thresholds: Any) -> RunLthr:
        return RunLthr(lambda: thresholds, lambda: date(2026, 11, 9), None)

    def test_zones_resolver_gives_the_run_zones_of_the_units_day(self) -> None:
        days: list[Any] = []
        zones = ZoneSettings(lthr=170.0, max_hr=190.0)

        def for_sport(sport: Any, environment: Any, day: date) -> Any:
            days.append((sport, day))
            return zones

        run_lthr = self.lookup(SimpleNamespace(unavailable=False, for_sport=for_sport))
        zones_for = run_lthr.zones_resolver()

        self.assertIs(zones, zones_for({"sport": "Run", "date": "2026-11-12"}))
        self.assertIs(zones, zones_for({"sport": "Run"}))
        self.assertEqual(
            [(Sport.RUN, date(2026, 11, 12)), (Sport.RUN, date(2026, 11, 9))], days
        )
        self.assertEqual(170.0, run_lthr.resolver()({"date": "2026-11-12"}))

    def test_unavailable_thresholds_give_no_zones(self) -> None:
        for thresholds in (None, SimpleNamespace(unavailable=True)):
            with self.subTest(thresholds=thresholds):
                run_lthr = self.lookup(thresholds)

                self.assertIsNone(run_lthr.zones_resolver()({"sport": "Run"}))
                self.assertIsNone(run_lthr.resolver()({"sport": "Run"}))


if __name__ == "__main__":
    unittest.main()
