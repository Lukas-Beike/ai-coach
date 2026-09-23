import json
import unittest
from unittest.mock import Mock

from backend.coach.context import CoachTrainingContextService
from backend.coach.prompt import COACH_PROMPT


class CoachTrainingContextServiceTests(unittest.TestCase):
    def make_service(
        self,
        structured_context,
        *,
        section_limits=None,
        total_char_limit=120_000,
        library=None,
    ):
        self.snapshot = {"synced_at": "2026-09-23T10:00:00Z"}
        self.repository = Mock()
        self.repository.latest_snapshot.return_value = self.snapshot
        self.structured = Mock()
        self.structured.build.return_value = structured_context
        self.library = Mock()
        self.library.list.return_value = library or []
        return CoachTrainingContextService(
            self.repository,
            self.structured,
            self.library,
            local_planned_limit=50,
            library_limit=12,
            library_description_limit=1500,
            section_limits=section_limits or {},
            total_char_limit=total_char_limit,
            activity_limit_per_sport=5,
            planned_event_limit=50,
        )

    def test_build_preserves_exact_prompt_and_projection_layout(self):
        structured = {
            "local_planned_workouts": [
                {
                    "id": "local-1",
                    "date": "2026-09-24",
                    "name": "Easy run",
                    "type": "Run",
                    "duration_minutes": 40,
                    "target": "Z1 HR",
                    "private_description": "not included",
                }
            ],
            "planning": {"status": "ready"},
            "intervals": {
                "recent_activities_by_sport": {"Run": [{"id": "a1"}]},
                "planned_workouts": [{"id": "event-1"}],
            },
        }
        library = [{"name": "Tempo", "type": "Run", "description": "warmup"}]
        service = self.make_service(
            structured,
            section_limits={"planning": 5000},
            library=library,
        )

        result = service.build()

        compacted_plans = [
            {
                "id": "local-1",
                "date": "2026-09-24",
                "name": "Easy run",
                "type": "Run",
                "duration_minutes": 40,
                "target": "Z1 HR",
            }
        ]
        prompt_context = {
            "projection": {
                "version": 1,
                "budgets": {"planning": 5000, "total": 120_000},
                "section_characters": {"planning": len('{"status":"ready"}')},
                "over_budget_sections": [],
                "truncated_sections": [],
                "planned_local_items": 1,
                "library_items": 1,
                "activity_limit_per_sport": 5,
                "planned_event_limit": 50,
                "local_planned_limit": 50,
            },
            "local_planned_workouts": compacted_plans,
            "planning": {"status": "ready"},
            "intervals": {
                "recent_activities_by_sport": {"Run": [{"id": "a1"}]},
                "planned_workouts": [{"id": "event-1"}],
            },
        }
        library_text = '[{"name":"Tempo","description":"warmup","type":"Run"}]'
        expected = (
            COACH_PROMPT
            + "\nBEGIN UNTRUSTED EXTERNAL DATA\nSTRUCTURED ATHLETE CONTEXT (authoritative for this turn):\n"
            + "LOCAL PLANNED WORKOUTS (compact projection, included once below):\n"
            + json.dumps(prompt_context, ensure_ascii=False, separators=(",", ":"))
            + "\nLOCAL TRAINING LIBRARY (bounded selection synced from Intervals.icu; templates available to the coach):\n"
            + library_text
            + "\nEND UNTRUSTED EXTERNAL DATA\n"
        )
        self.assertEqual(result, expected)
        self.assertNotIn("private_description", result)
        self.repository.latest_snapshot.assert_called_once_with()
        self.structured.build.assert_called_once_with(self.snapshot)

    def test_build_preserves_structured_intervals_until_section_bounding(self):
        intervals = {
            "recent_activities_by_sport": {
                "Run": [{"id": f"activity-{index}"} for index in range(6)]
            },
            "activity_rollups_by_sport": {
                "Run": {"last_7_days": {"count": 6}, "last_30_days": {"count": 6}}
            },
            "planned_workouts": [{"id": f"event-{index}"} for index in range(51)],
            "scope": "synthetic full intervals projection",
        }
        service = self.make_service(
            {"intervals": intervals, "local_planned_workouts": []},
            section_limits={"intervals": 100_000},
        )

        result = service.build()

        marker = "LOCAL PLANNED WORKOUTS (compact projection, included once below):\n"
        structured_start = result.index(marker) + len(marker)
        structured_end = result.index(
            "\nLOCAL TRAINING LIBRARY (bounded selection synced from Intervals.icu; templates available to the coach):\n",
            structured_start,
        )
        parsed = json.loads(result[structured_start:structured_end])
        self.assertEqual(parsed["intervals"], intervals)
        self.assertEqual(len(parsed["intervals"]["recent_activities_by_sport"]["Run"]), 6)
        self.assertEqual(len(parsed["intervals"]["planned_workouts"]), 51)
        self.assertEqual(
            parsed["projection"]["section_characters"]["intervals"],
            len(json.dumps(intervals, ensure_ascii=False, separators=(",", ":"))),
        )
        self.structured.build.assert_called_once_with(self.snapshot)

    def test_section_and_total_truncation_keep_valid_bounded_context(self):
        structured = {
            "planning": {"notes": "athlete note " * 800},
            "unbounded": "context value " * 5000,
            "local_planned_workouts": [],
        }
        service = self.make_service(
            structured,
            section_limits={"planning": 180},
            total_char_limit=11_000,
        )

        with self.assertLogs("intervals_coach", level="WARNING") as captured:
            result = service.build()

        self.assertLessEqual(len(result), 11_000)
        self.assertIn('"truncated_sections":[{"section":"planning"', result)
        self.assertEqual(captured.records[0].event, "coach_context_budget_applied")

        marker = "LOCAL PLANNED WORKOUTS (compact projection, included once below):\n"
        structured_start = result.index(marker) + len(marker)
        structured_end = result.index(
            "\nLOCAL TRAINING LIBRARY (bounded selection synced from Intervals.icu; templates available to the coach):\n",
            structured_start,
        )
        parsed = json.loads(result[structured_start:structured_end])
        self.assertIsInstance(parsed, dict)
        self.assertLessEqual(len(result), 11_000)


if __name__ == "__main__":
    unittest.main()
