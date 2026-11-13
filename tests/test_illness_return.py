"""Stepwise return to training after an illness pause (#2042): rule and guard."""

from __future__ import annotations

import unittest
from datetime import date
from typing import Any

from backend.activities.zone_settings import ZoneSettings
from backend.planning import illness_return, plan_checks
from backend.planning.plan_guard_service import PlanGuardService
from backend.planning.planned_unit_load import estimate_planned_unit

PAUSE = {"start_date": "2026-10-27", "end_date": "2026-11-01", "approved": True}
GOOD_CHECKIN = {"checkin_date": "2026-11-04", "pain": "", "illness": "", "soreness": 3}
GOOD_NIGHT = {
    "hrv": {"source": "Garmin", "value": 55, "position": "within", "lower": 50},
    "resting_hr": {"source": "Garmin", "value": 50, "median": 48, "unit": "bpm"},
}


def _state(stage: int = 1, since: str = "2026-11-02") -> dict[str, Any]:
    return {"pause_end": "2026-11-01", "stage": stage, "since": since, "history": []}


def _decide(
    state: dict[str, Any],
    today: str = "2026-11-04",
    checkin: dict[str, Any] | None = None,
    night: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return illness_return.decide(
        state,
        date.fromisoformat(today),
        {**GOOD_CHECKIN, "checkin_date": today, **(checkin or {})},
        GOOD_NIGHT if night is None else night,
    )


class ReturnStateTests(unittest.TestCase):
    def test_return_starts_at_stage_one_the_day_after_the_pause(self) -> None:
        state = illness_return.current_state(PAUSE, None, date(2026, 11, 2))

        assert state is not None
        self.assertEqual((1, "2026-11-02"), (state["stage"], state["since"]))

    def test_no_return_inside_the_pause_or_without_approval(self) -> None:
        self.assertIsNone(illness_return.current_state(PAUSE, None, date(2026, 11, 1)))
        unapproved = {**PAUSE, "approved": False}
        self.assertIsNone(
            illness_return.current_state(unapproved, None, date(2026, 11, 4))
        )

    def test_stored_state_of_another_pause_is_ignored(self) -> None:
        other = {**_state(2), "pause_end": "2026-10-01"}

        state = illness_return.current_state(PAUSE, other, date(2026, 11, 4))

        assert state is not None
        self.assertEqual(1, state["stage"])

    def test_return_expires_after_four_weeks(self) -> None:
        self.assertIsNone(illness_return.current_state(PAUSE, None, date(2026, 12, 2)))

    def test_normal_plan_stage_enforces_nothing(self) -> None:
        self.assertIsNone(illness_return.enforced_stage(_state(3)))
        self.assertEqual(2, illness_return.enforced_stage(_state(2)))


class StageDecisionTests(unittest.TestCase):
    def test_two_days_per_stage_with_good_signals(self) -> None:
        state = _state(1, "2026-11-02")
        self.assertEqual(["stage_days"], _decide(state, "2026-11-03")["reasons"])
        first = _decide(state, "2026-11-04")
        self.assertEqual(("advance", 2), (first["action"], first["stage"]))
        state = illness_return.state_after(state, first, date(2026, 11, 4))
        self.assertEqual("2026-11-04", state["since"])
        self.assertEqual("hold", _decide(state, "2026-11-05")["action"])
        second = _decide(state, "2026-11-06")
        self.assertEqual(("advance", 3), (second["action"], second["stage"]))

    def test_at_most_one_stage_per_morning(self) -> None:
        result = _decide(_state(1, "2026-10-01"))

        self.assertEqual(2, result["stage"])

    def test_normal_plan_stage_only_holds(self) -> None:
        result = _decide(_state(3, "2026-10-01"))

        self.assertEqual(
            ("hold", 3, ["complete"]),
            tuple(result[k] for k in ("action", "stage", "reasons")),
        )

    def test_hrv_below_the_usual_range_holds(self) -> None:
        night = {**GOOD_NIGHT, "hrv": {**GOOD_NIGHT["hrv"], "position": "below"}}

        result = _decide(_state(1, "2026-10-30"), night=night)

        self.assertEqual(("hold", 1), (result["action"], result["stage"]))
        self.assertEqual(["hrv_below_range"], result["reasons"])

    def test_resting_hr_more_than_five_above_the_usual_value_holds(self) -> None:
        state = _state(1, "2026-10-30")
        usual = {"median": 48, "source": "Garmin"}
        high = {**GOOD_NIGHT, "resting_hr": {**usual, "value": 54}}
        edge = {**GOOD_NIGHT, "resting_hr": {**usual, "value": 53}}

        self.assertEqual(["resting_hr_high"], _decide(state, night=high)["reasons"])
        self.assertEqual("advance", _decide(state, night=edge)["action"])

    def test_poor_body_feel_holds(self) -> None:
        state = _state(1, "2026-10-30")

        self.assertEqual(
            ["body_feel"], _decide(state, checkin={"soreness": 6})["reasons"]
        )
        self.assertEqual("advance", _decide(state, checkin={"soreness": 5})["action"])

    def test_new_complaint_steps_back_one_stage(self) -> None:
        result = _decide(_state(3, "2026-10-30"), checkin={"pain": "Knie"})
        low = _decide(_state(2, "2026-10-30"), checkin={"pain": "Knie"})
        floor = _decide(_state(1, "2026-10-30"), checkin={"pain": "Knie"})

        self.assertEqual(("step_back", 2), (result["action"], result["stage"]))
        self.assertEqual(("step_back", 1), (low["action"], low["stage"]))
        self.assertEqual(("hold", 1), (floor["action"], floor["stage"]))
        stepped = illness_return.state_after(_state(2), low, date(2026, 11, 4))
        self.assertEqual("2026-11-04", stepped["since"])

    def test_missing_overnight_values_leave_the_check_in_alone(self) -> None:
        result = _decide(_state(1, "2026-10-30"), night={})

        self.assertEqual(("advance", 2), (result["action"], result["stage"]))
        missing = [item["label"] for item in result["evidence"] if item.get("missing")]
        self.assertEqual(["hrv", "resting_hr"], missing)

    def test_missing_overnight_value_does_not_excuse_a_complaint(self) -> None:
        result = _decide(_state(2, "2026-10-30"), checkin={"pain": "Wade"}, night={})

        self.assertEqual("step_back", result["action"])

    def test_without_todays_check_in_the_stage_holds(self) -> None:
        state = _state(1, "2026-10-30")

        result = illness_return.decide(state, date(2026, 11, 4), None, GOOD_NIGHT)

        self.assertEqual(
            ("hold", ["no_checkin"]), (result["action"], result["reasons"])
        )

    def test_evidence_names_its_sources(self) -> None:
        result = _decide(_state(1, "2026-10-30"))

        sources = {item["source"] for item in result["evidence"]}
        self.assertEqual({"Check-in (lokal)", "Garmin"}, sources)


def _unit(local_id: str, day: str, **fields: Any) -> dict[str, Any]:
    return {
        "local_id": local_id,
        "date": day,
        "sport": "run",
        "planned_duration_s": 3000,
        **fields,
    }


TODAY = date(2026, 11, 4)


class SessionLevelTests(unittest.TestCase):
    def test_levels_follow_focus_and_length(self) -> None:
        cases = [
            (_unit("a", "2026-11-04", session_focus="easy"), 0),
            (_unit("b", "2026-11-04", session_focus="recovery"), 0),
            (_unit("c", "2026-11-04", session_focus="endurance"), 1),
            (_unit("d", "2026-11-04", session_focus="threshold"), 2),
            (
                _unit("e", "2026-11-04", session_focus="easy", planned_duration_s=5400),
                1,
            ),
            (
                _unit(
                    "f",
                    "2026-11-04",
                    sport="strength",
                    strength_intensity="light",
                    session_focus="mobility",
                ),
                0,
            ),
            (
                _unit(
                    "g",
                    "2026-11-04",
                    sport="strength",
                    strength_intensity="heavy",
                    session_focus="legs",
                ),
                2,
            ),
        ]
        for unit, level in cases:
            with self.subTest(unit["local_id"]):
                self.assertEqual(level, plan_checks.session_level(unit))


class ReturnGuardTests(unittest.TestCase):
    def _findings(self, units: list[dict[str, Any]], stage: int | None, **extra: Any):
        return plan_checks.check_plan(
            today=TODAY,
            units=units,
            completed=[],
            competitions=[],
            return_stage=stage,
            **extra,
        )

    def test_stage_one_blocks_moderate_and_hard_today_and_tomorrow(self) -> None:
        units = [
            _unit("easy", "2026-11-04", session_focus="easy"),
            _unit("mod", "2026-11-04", session_focus="endurance"),
            _unit("hard", "2026-11-05", session_focus="threshold"),
            _unit("later", "2026-11-06", session_focus="threshold"),
        ]

        findings = self._findings(units, 1)

        flagged = [item for item in findings if item["code"] == "illness_hard"]
        self.assertEqual([["mod"], ["hard"]], [item["local_ids"] for item in flagged])
        self.assertTrue(all(item["blocking"] for item in flagged))
        self.assertEqual({1}, {item["evidence"]["return_stage"] for item in flagged})

    def test_stage_two_allows_moderate_but_not_hard(self) -> None:
        units = [
            _unit("mod", "2026-11-04", session_focus="endurance"),
            _unit("hard", "2026-11-05", session_focus="vo2max"),
        ]

        findings = self._findings(units, 2)

        self.assertEqual(
            [["hard"]],
            [item["local_ids"] for item in findings if item["code"] == "illness_hard"],
        )

    def test_no_return_means_no_stage_finding(self) -> None:
        units = [_unit("hard", "2026-11-04", session_focus="threshold")]

        self.assertEqual(
            [], [i for i in self._findings(units, None) if i["code"] == "illness_hard"]
        )

    def test_reported_illness_is_not_flagged_twice(self) -> None:
        units = [_unit("hard", "2026-11-04", session_focus="threshold")]

        findings = self._findings(units, 1, illness="Infekt")

        self.assertEqual(1, len([i for i in findings if i["code"] == "illness_hard"]))

    def test_easing_a_flagged_session_is_not_a_new_finding(self) -> None:
        before = self._findings(
            [_unit("a", "2026-11-04", session_focus="threshold")], 1
        )
        after = self._findings([_unit("a", "2026-11-04", session_focus="endurance")], 1)

        self.assertEqual([], plan_checks.new_findings(before, after))

    def test_guard_service_passes_the_stage_to_the_checks(self) -> None:
        units = [_unit("mod", "2026-11-04", session_focus="endurance")]
        guard = PlanGuardService(
            planned_units=lambda: units,
            completed_activities=list,
            competitions=list,
            illness=lambda: "",
            progress=lambda: {"week_list": []},
            training_model=lambda: "pyramidal",
            today=lambda: TODAY,
            estimate_unit=lambda unit: estimate_planned_unit(unit, ZoneSettings()),
        ).with_return_stage(lambda: 1)

        codes = [item["code"] for item in guard.findings()]

        self.assertIn("illness_hard", codes)
        self.assertIn("illness_hard", plan_checks.BLOCKING_CODES)


if __name__ == "__main__":
    unittest.main()
