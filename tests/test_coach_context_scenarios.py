import json
import pathlib
import unittest

from backend.coach.context_selection import FULL_SECTIONS, select_coach_context

FIXTURE = (
    pathlib.Path(__file__).resolve().parent
    / "fixtures"
    / "coach_context_scenarios.json"
)
DATED_SECTIONS = {
    "calendar",
    "local_planned_workouts",
    "daily_planning_context",
    "weather",
}
ANALYSIS_NAMES = {"activity_analysis", "attachment_analysis"}
COMPARISON_SECTION = "current_performance:comparisons"
EXPECTED_SCENARIO_COUNT = 39


def _satisfied(need, selection):
    for alternative in need["sections"]:
        if alternative == COMPARISON_SECTION:
            if "current_performance" in selection.sections and (
                selection.horizon_days is None or selection.name in ANALYSIS_NAMES
            ):
                return True
            continue
        if alternative not in selection.sections:
            continue
        days = need["min_horizon_days"]
        if (
            alternative in DATED_SECTIONS
            and days is not None
            and selection.horizon_days is not None
            and selection.horizon_days < days
        ):
            continue
        activities = need["min_activities"]
        if (
            activities
            and selection.horizon_days is not None
            and selection.activity_limit < activities
        ):
            continue
        return True
    return False


class CoachContextScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.scenarios = payload["scenarios"]

    def test_fixture_has_expected_unique_scenarios(self):
        ids = [scenario["id"] for scenario in self.scenarios]
        self.assertEqual(EXPECTED_SCENARIO_COUNT, len(ids))
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_scenario_receives_its_required_context(self):
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario["id"]):
                selection = select_coach_context(
                    scenario["message"],
                    scenario["dialogue"],
                    attachments=scenario["attachments"],
                )
                for need in scenario["needs"]:
                    self.assertTrue(
                        _satisfied(need, selection),
                        f"{scenario['id']} missing {need['label']}: "
                        f"name={selection.name} horizon={selection.horizon_days} "
                        f"activities={selection.activity_limit}",
                    )

    def test_pending_request_retention_matches_expectation(self):
        for scenario in self.scenarios:
            expected = scenario["retain_pending_request"]
            if expected is None:
                continue
            with self.subTest(scenario=scenario["id"]):
                selection = select_coach_context(
                    scenario["message"],
                    scenario["dialogue"],
                    attachments=scenario["attachments"],
                )
                self.assertEqual(expected, selection.retain_pending_request)

    def test_full_context_scenarios_use_all_sections(self):
        selection = select_coach_context("Synchronisiere den Plan", {})
        self.assertIsNone(selection.horizon_days)
        self.assertEqual(FULL_SECTIONS, selection.sections)


if __name__ == "__main__":
    unittest.main()
