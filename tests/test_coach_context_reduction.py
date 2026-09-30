"""Request-level reduction, provenance and on-demand read contracts."""

import json
import unittest
from unittest.mock import Mock

from backend.coach.context import (
    CoachTrainingContextService,
    bounded_coach_context_value,
    coach_context_json_size,
)
from backend.coach.context_selection import CoachContextSelection, select_coach_context
from backend.coach.read_tools import CoachReadToolService
from backend.errors import AppError
from tests import test_coach_request_payload as payload_tests
from tests import test_coach_structured_context as context_tests
from tests import test_coach_structured_tool_round as round_tests


class CoachContextReductionTests(unittest.TestCase):
    def test_oversized_single_section_retains_useful_prefix(self):
        result = bounded_coach_context_value(
            {"garmin": {"history": "synthetic " * 5000}}, 40_000
        )
        self.assertTrue(result["garmin"]["history"])
        self.assertLessEqual(coach_context_json_size(result), 40_000)

    def test_scoped_assembly_skips_unnecessary_reads(self):
        fixture = context_tests.CoachStructuredContextServiceTests()
        fixture.setUp()
        selection = select_coach_context("How is recovery?", {})
        result = fixture.service.build(selection=selection)
        self.assertEqual(set(result), selection.sections)
        fixture.garmin_projection_service.coach_context.assert_not_called()
        fixture.training_plan_service.list.assert_not_called()
        fixture.adaptive_replan_preview_service.latest_preview.assert_not_called()
        self.assertIn("current_performance", result)
        self.assertIn("daily_planning_context", result)

    def test_on_demand_assembly_only_reads_requested_domain(self):
        fixture = context_tests.CoachStructuredContextServiceTests()
        fixture.setUp()
        result = fixture.service.build(
            selection=CoachContextSelection(
                "requested_details",
                frozenset({"garmin"}),
                include_library=False,
            )
        )
        self.assertEqual(set(result), {"garmin"})
        fixture.weather_service.state.assert_not_called()
        fixture.profile_service.get.assert_not_called()
        fixture.planned_unit_service.list.assert_not_called()
        fixture.checkin_service.context.assert_not_called()

    @staticmethod
    def read_service(context):
        return CoachReadToolService(
            *(Mock() for _index in range(8)),
            training_change_limit=366,
            context_service=lambda: context,
        )

    def test_detail_read_bounds_output_and_rejects_unknown_sections(self):
        context = Mock()
        context.build.return_value = {
            "garmin": {"source": "Garmin", "notes": "synthetic " * 8000}
        }
        service = self.read_service(context)
        result = service.execute("read_coach_context", {"sections": ["garmin"]})
        self.assertTrue(result["ok"])
        self.assertFalse(result["projection"]["complete"])
        self.assertLessEqual(result["projection"]["characters"], 40_000)
        self.assertEqual(result["context"]["garmin"]["source"], "Garmin")
        self.assertEqual(
            context.build.call_args.kwargs["selection"].sections, frozenset({"garmin"})
        )
        for sections in (None, [], ["raw_snapshot"], [1], ["garmin"] * 16):
            with self.subTest(sections=sections), self.assertRaises(AppError):
                service.execute("read_coach_context", {"sections": sections})

    def test_pending_request_preserves_full_dialogue(self):
        fixture = payload_tests.CoachRequestPayloadTests()
        fixture.setUp()
        context = {**fixture.context, "pending_request": {"source_message_ids": [1]}}
        _, payload = fixture.build(message="Auf Freitag", context=context)
        self.assertIsNone(
            fixture.training_context.build.call_args.kwargs["selection"].horizon_days
        )
        self.assertEqual(json.loads(payload["input"])["dialogue"], context)

    def test_request_filters_tools_and_telemetry_contains_no_athlete_content(self):
        fixture = payload_tests.CoachRequestPayloadTests()
        fixture.setUp()
        tools = [
            {"name": name}
            for name in (
                "read_coach_context",
                "read_profile",
                "start_intervals_plan_sync",
            )
        ]
        context = {
            **fixture.context,
            "messages": [
                {"id": index, "content": "synthetic private note"}
                for index in range(24)
            ],
        }
        with self.assertLogs("intervals_coach", level="INFO") as captured:
            _, payload = fixture.build(
                message="How is recovery?", context=context, tools=tools
            )
        self.assertNotIn(
            "start_intervals_plan_sync", {tool["name"] for tool in payload["tools"]}
        )
        self.assertLessEqual(
            len(json.loads(payload["input"])["dialogue"]["messages"]), 8
        )
        record = captured.records[-1]
        self.assertEqual(record.event, "coach_request_sizes")
        self.assertNotIn("synthetic private note", str(record.__dict__))

    def test_successful_read_expands_only_tools_allowed_for_turn(self):
        fixture = round_tests.StructuredToolRoundTests()
        fixture.setUp()
        state = fixture.state()
        state.tools = [{"name": "read_coach_context"}, {"name": "read_profile"}]
        state.request_payload["tools"] = [{"name": "read_coach_context"}]
        state.command_receipts = [
            {"tool": "read_coach_context", "result": {"ok": True}}
        ]
        fixture.service._followup_response(
            {"id": "response-one"},
            outputs=[],
            state=state,
            question="",
            cancelled=False,
            rounds=0,
        )
        followup = fixture.response.respond.call_args.args[0]
        self.assertEqual(followup["tools"], state.tools)
        self.assertEqual(followup["previous_response_id"], "response-one")
        self.assertFalse(state.allow_mutations)

    def test_routine_context_reduction_preserves_sources_and_illness(self):
        structured = {
            "durable_profile": {"constraints": "no intensity while ill"},
            "target_competitions": [{"id": "race-1"}],
            "daily_planning_context": [
                {"date": "2026-09-30", "checkin": {"illness": True}}
            ],
            "local_feedback": {"recent": []},
            "local_planned_workouts": [],
            "current_performance": {"source": "Garmin", "metrics": {"vo2max": 50}},
            "garmin": {"history": "synthetic history " * 2000},
            "weather": {"history": "synthetic weather " * 1000},
            "external_calendar": {"history": "synthetic events " * 1000},
        }
        repository, structured_service, library = Mock(), Mock(), Mock()
        repository.latest_snapshot.return_value = {}
        structured_service.build.return_value = structured
        library.list.return_value = []
        service = CoachTrainingContextService(
            repository,
            structured_service,
            library,
            local_planned_limit=50,
            library_limit=12,
            library_description_limit=1500,
            section_limits={},
            total_char_limit=120_000,
            activity_limit_per_sport=5,
            planned_event_limit=50,
        )
        full_size = len(service.build())
        library.reset_mock()
        result = service.build(
            selection=select_coach_context("How is recovery?", {}),
            local_date="2026-09-30",
        )
        marker = "LOCAL PLANNED WORKOUTS (compact projection, included once below):\n"
        start = result.index(marker) + len(marker)
        parsed = json.loads(
            result[start : result.index("\nLOCAL TRAINING LIBRARY", start)]
        )
        self.assertLess(len(result), full_size * 0.5)
        self.assertEqual(parsed["current_performance"]["source"], "Garmin")
        self.assertTrue(parsed["daily_planning_context"][0]["checkin"]["illness"])
        self.assertEqual(
            parsed["target_competitions"], structured["target_competitions"]
        )
        library.list.assert_not_called()
