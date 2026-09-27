from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from backend.coach import local_assembly
from backend.coach.local_assembly import (
    CoachLocalAssembly,
    CoachLocalGarmin,
    CoachLocalPlanning,
    CoachLocalState,
)


class CoachLocalAssemblyTests(unittest.TestCase):
    def make_assembly(self):
        manager = Mock(name="database_manager")
        manager_factory = Mock(return_value=manager)
        dependencies = {
            "database_manager": manager_factory,
            "database_lock": Mock(name="database_lock"),
            "key_values": Mock(name="key_values"),
            "sync_job_queue": Mock(name="sync_job_queue"),
            "local_date": Mock(return_value="2026-09-26"),
            "adaptive_preview": Mock(name="adaptive_preview"),
            "planned_workout_label": "Planned workout",
            "garmin_sync": Mock(name="garmin_sync"),
            "garmin_payload": Mock(name="garmin_payload"),
            "morning_body_battery": Mock(name="morning_body_battery"),
            "logger": Mock(name="logger"),
        }
        assembly = CoachLocalAssembly(dependencies=CoachLocalAssembly.Inputs(
            state=CoachLocalState(
                dependencies["database_manager"], dependencies["database_lock"],
                dependencies["key_values"],
            ),
            planning=CoachLocalPlanning(
                dependencies["sync_job_queue"], dependencies["local_date"],
                dependencies["adaptive_preview"], dependencies["planned_workout_label"],
            ),
            garmin=CoachLocalGarmin(
                dependencies["garmin_sync"], dependencies["garmin_payload"],
                dependencies["morning_body_battery"], dependencies["logger"],
            ),
        ))
        return assembly, dependencies, manager

    def test_dialogue_and_checkin_factories_keep_shared_state(self):
        assembly, deps, manager = self.make_assembly()
        with (
            patch.object(local_assembly, "CoachDialogueActionService") as action,
            patch.object(local_assembly, "CoachClarificationService") as clarification,
            patch.object(local_assembly, "ManualMorningCheckinService") as morning,
        ):
            assembly.dialogue_action_service()
            assembly.clarification_service()
            assembly.manual_morning_checkin_service()

        self.assertIs(action.call_args.args[0], manager)
        self.assertIs(action.call_args.args[1], deps["database_lock"])
        self.assertIs(action.call_args.args[2], deps["sync_job_queue"])
        self.assertIs(clarification.call_args.args[1], deps["key_values"])
        self.assertIs(clarification.call_args.args[2], deps["database_lock"])
        self.assertIs(morning.call_args.args[0], deps["garmin_sync"].return_value)
        self.assertIs(morning.call_args.args[2], deps["morning_body_battery"].return_value)

    def test_quick_action_factory_uses_existing_preview_owner(self):
        assembly, deps, manager = self.make_assembly()
        with patch.object(local_assembly, "CoachQuickActionsService") as quick_actions:
            assembly.quick_actions_service()

        self.assertIs(quick_actions.call_args.args[0], manager)
        self.assertIs(quick_actions.call_args.args[2], deps["adaptive_preview"].return_value)
        self.assertEqual(quick_actions.call_args.args[3](), "2026-09-26")


if __name__ == "__main__":
    unittest.main()
