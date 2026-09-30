from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from backend.coach import context_assembly, read_tools_assembly
from backend.coach.context_assembly import (
    CoachContextAssembly,
    CoachContextDialogueSources,
    CoachContextPerformanceSources,
    CoachContextPlanningSources,
)
from backend.coach.read_tools_assembly import (
    CoachActivityReadSources,
    CoachPlanningReadSources,
    CoachReadToolPolicy,
    CoachReadToolsAssembly,
)


class CoachContextAssemblyTests(unittest.TestCase):
    def make_assembly(self):
        deps = {
            name: Mock(name=name)
            for name in (
                "sync_state", "checkins", "weather", "feedback", "planned_units",
                "daily_context", "calendar", "competitions", "training_plans",
                "adaptive_preview", "today", "profile", "garmin_payload",
                "garmin_projection", "local_date", "workout_library", "messages",
                "limits", "now",
            )
        }
        deps["settings"] = Mock(name="settings")
        deps["limits"].return_value = {
            "local_planned_limit": 20,
            "library_limit": 30,
            "library_description_limit": 200,
            "section_limits": {"planning": 1000},
            "total_char_limit": 10000,
            "activity_limit_per_sport": 5,
            "planned_event_limit": 25,
        }
        assembly = CoachContextAssembly(dependencies=CoachContextAssembly.Inputs(
            performance=CoachContextPerformanceSources(
                sync_state_repository=deps["sync_state"],
                weather_service=deps["weather"],
                garmin_payload_service=deps["garmin_payload"],
                garmin_projection_service=deps["garmin_projection"],
                activity_feedback_service=deps["feedback"],
                today=deps["today"],
                local_date=deps["local_date"],
                utc_now=deps["now"],
            ),
            planning=CoachContextPlanningSources(
                checkin_service=deps["checkins"],
                planned_unit_service=deps["planned_units"],
                daily_context_service=deps["daily_context"],
                external_calendar_reader=deps["calendar"],
                competition_service=deps["competitions"],
                training_plan_service=deps["training_plans"],
                adaptive_preview_service=deps["adaptive_preview"],
                workout_library_service=deps["workout_library"],
            ),
            dialogue=CoachContextDialogueSources(
                profile_service=deps["profile"],
                message_service=deps["messages"],
                settings=deps["settings"],
                limits=deps["limits"],
                default_max_output_tokens=Mock(return_value=5000),
            ),
        ))
        return assembly, deps

    def test_construction_is_lazy_and_structured_context_uses_named_domain_owners(self):
        assembly, deps = self.make_assembly()
        for name, callback in deps.items():
            if name not in {"settings", "limits", "now"}:
                callback.assert_not_called()

        with patch.object(context_assembly, "CoachStructuredContextService") as factory:
            assembly.structured_context_service()

        self.assertIs(factory.call_args.args[0], deps["sync_state"].return_value)
        planning = factory.call_args.args[4]
        performance = factory.call_args.args[5]
        self.assertIs(planning._planned_unit_service, deps["planned_units"].return_value)
        self.assertIs(planning._daily_planning_context_service, deps["daily_context"].return_value)
        self.assertIs(planning._external_calendar_reader, deps["calendar"].return_value)
        self.assertIs(performance._profile_service, deps["profile"].return_value)
        self.assertIs(performance._garmin_payload_service, deps["garmin_payload"].return_value)

    def test_training_preview_and_request_factories_resolve_limits_when_called(self):
        assembly, deps = self.make_assembly()
        with (
            patch.object(context_assembly, "CoachStructuredContextService", return_value="structured"),
            patch.object(context_assembly, "CoachTrainingContextService") as training_factory,
            patch.object(context_assembly, "CoachRequestPayloadService") as payload_factory,
        ):
            training = assembly.training_context_service()
            assembly.request_payload_service()

        self.assertIsNotNone(training)
        self.assertIs(training_factory.call_args.args[0], deps["sync_state"].return_value)
        self.assertEqual(training_factory.call_args.kwargs["total_char_limit"], 10000)
        self.assertEqual(training_factory.call_args.kwargs["section_limits"], {"planning": 1000})
        self.assertIs(payload_factory.call_args.args[1], deps["settings"])
        self.assertEqual(payload_factory.call_args.args[2], 5000)
        self.assertEqual(deps["limits"].call_count, 2)

        deps["limits"].return_value["total_char_limit"] = 12000
        with (
            patch.object(context_assembly, "CoachStructuredContextService", return_value="structured"),
            patch.object(context_assembly, "CoachTrainingContextService") as next_factory,
        ):
            assembly.training_context_service()
        self.assertEqual(next_factory.call_args.kwargs["total_char_limit"], 12000)


class CoachReadToolsAssemblyTests(unittest.TestCase):
    def test_dispatch_is_lazy_and_activity_reads_reuse_the_injected_providers(self):
        deps = {name: Mock(name=name) for name in (
            "activity", "garmin", "profile", "today", "training_state", "library",
            "planned", "history", "competitions", "training_plans", "nutrition", "limit",
        )}
        deps["limit"].return_value = 77
        assembly = CoachReadToolsAssembly(dependencies=CoachReadToolsAssembly.Inputs(
            activity=CoachActivityReadSources(
                deps["activity"], deps["garmin"], deps["profile"], deps["today"]
            ),
            planning=CoachPlanningReadSources(
                deps["training_state"], deps["library"], deps["planned"],
                deps["history"], deps["competitions"], deps["training_plans"],
            ),
            policy=CoachReadToolPolicy(deps["nutrition"], deps["limit"]),
        ))

        with (
            patch.object(read_tools_assembly, "CoachReadToolService") as read_factory,
            patch.object(read_tools_assembly, "CoachActivityReadToolService") as activity_factory,
        ):
            read_service = assembly.read_service()
            self.assertEqual(read_factory.call_args.args[8], 77)
            self.assertFalse(activity_factory.called)
            self.assertIs(read_factory.call_args.args[2].__self__, assembly)
            activity = assembly.activity_read_service()

        self.assertIs(activity_factory.call_args.args[0], deps["activity"].return_value)
        self.assertIs(activity_factory.call_args.args[1], deps["garmin"].return_value)
        self.assertIs(activity_factory.call_args.args[2], deps["profile"].return_value)


if __name__ == "__main__":
    unittest.main()
