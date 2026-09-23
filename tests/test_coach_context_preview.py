import unittest
from datetime import date, datetime, timezone
from unittest.mock import Mock

from backend.coach.context import (
    CoachContextPreviewLimits,
    CoachContextPreviewService,
    CoachIntervalsContextService,
)


class CoachContextPreviewServiceTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "synced_at": "2026-09-23T08:00:00Z",
            "access_token": "must-not-be-projected",
            "recent_activities": [
                {
                    "id": 7,
                    "start_date_local": "2026-09-22T07:00:00",
                    "name": "Easy run",
                    "type": "Run",
                    "distance": 5000,
                    "private_note": "must-not-be-projected",
                }
            ],
        }
        self.sync_state = Mock()
        self.sync_state.latest_snapshot.return_value = self.snapshot
        self.messages = Mock()
        self.messages.list.return_value = [
            {"role": "assistant", "content": "Earlier response"},
            {"role": "user", "content": "Plan tomorrow"},
        ]
        self.training_context = Mock()
        self.training_context.build.return_value = "exact assembled context"
        self.structured_context = Mock()
        self.structured_context.build.return_value = {
            "local_planned_workouts": [
                {
                    "id": "plan-1",
                    "date": "2026-09-24",
                    "name": "Intervals",
                    "duration_minutes": 45,
                }
            ],
            "activity_feedback": {"note": "x" * 200},
            "intervals": CoachIntervalsContextService().project(
                self.snapshot, [], date(2026, 9, 23)
            ),
        }
        self.library = Mock()
        self.library.list.return_value = [
            {
                "id": "library-1",
                "name": "Tempo",
                "type": "Ride",
                "description": "d" * 40,
                "tags": ["tempo"],
                "athlete_email": "must-not-be-projected@example.test",
            },
            {"id": "library-2", "name": "Unused", "type": "Run"},
        ]
        self.service = CoachContextPreviewService(
            self.sync_state,
            self.messages,
            self.training_context,
            self.structured_context,
            self.library,
            CoachContextPreviewLimits(
                library_limit=1,
                library_description_limit=12,
                section_limits={"activity_feedback": 32},
                total_char_limit=100,
                local_planned_limit=1,
                activity_limit_per_sport=5,
                planned_event_limit=50,
            ),
            utc_now=lambda: datetime(2026, 9, 23, 10, 30, tzinfo=timezone.utc),
        )

    def test_preview_layout_snapshot_last_message_and_read_calls(self):
        preview = self.service.preview("openai")

        self.assertEqual(
            list(preview),
            [
                "generated_at",
                "snapshot_truncated",
                "snapshot_compacted",
                "assembly",
                "conversation",
                "chat_prompt",
                "structured_athlete_context",
                "latest_intervals_snapshot",
                "projection",
                "context_text",
                "local_training_library",
            ],
        )
        self.assertEqual(preview["generated_at"], "2026-09-23T10:30:00+00:00")
        self.assertFalse(preview["snapshot_truncated"])
        self.assertTrue(preview["snapshot_compacted"])
        self.assertEqual(preview["chat_prompt"]["content"], "Plan tomorrow")
        self.assertEqual(preview["context_text"], "exact assembled context")
        self.sync_state.latest_snapshot.assert_called_once_with()
        self.messages.list.assert_called_once_with()
        self.structured_context.build.assert_called_once_with(self.snapshot)
        self.assertIs(
            preview["latest_intervals_snapshot"],
            preview["structured_athlete_context"]["intervals"],
        )

    def test_projection_bounds_and_privacy(self):
        preview = self.service.preview("openai")

        self.assertEqual(preview["local_training_library"][0]["description"], "d" * 12)
        self.assertEqual(preview["projection"]["library_items"], 1)
        self.assertEqual(preview["projection"]["planned_local_items"], 1)
        self.assertEqual(preview["projection"]["budgets"], {
            "activity_feedback": 32,
            "total": 100,
        })
        projected_plan = preview["projection"]
        self.assertGreaterEqual(len(projected_plan["truncated_sections"]), 1)
        self.assertEqual(
            preview["latest_intervals_snapshot"]["recent_activities_by_sport"]["Laufen"][0],
            {
                "id": "7",
                "start_date_local": "2026-09-22T07:00:00",
                "name": "Easy run",
                "type": "Run",
                "distance": 5000,
            },
        )
        serialized = str(preview)
        self.assertNotIn("must-not-be-projected", serialized)
        self.assertNotIn("athlete_email", serialized)
        self.assertEqual(self.training_context.build.call_count, 1)
        self.assertEqual(self.library.list.call_count, 2)

    def test_provider_mode_is_selected_by_argument(self):
        self.assertEqual(
            self.service.preview("gemini")["conversation"]["mode"],
            "Gemini local conversation history",
        )
        self.assertEqual(
            self.service.preview("openai")["conversation"]["mode"],
            "Bounded local dialogue with per-command Responses chain",
        )


if __name__ == "__main__":
    unittest.main()
