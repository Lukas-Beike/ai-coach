import copy
import unittest

from backend.calendar.local import (
    LOCAL_INTERVALS_SCOPE,
    _local_calendar_competition,
    _local_calendar_external_event,
    local_calendar_events,
)


class LocalCalendarTests(unittest.TestCase):
    def test_complete_read_model_uses_explicit_inputs(self):
        planned = [
            {"id": "planned-1", "date": "2026-09-22", "name": "Workout"},
            {"id": "planned-2", "date": "2026-09-19", "name": "Easy"},
        ]
        competitions = [
            {
                "id": "competition-1",
                "event_date": "2026-09-20",
                "sport": "Run",
                "external_id": "remote-competition-1",
            }
        ]
        external_events = [
            {
                "id": "external-1",
                "event_date": "2026-09-21",
                "name": "Relevant",
                "training_relevant": 1,
            },
            {
                "id": "external-2",
                "event_date": "2026-09-18",
                "name": "Ignored",
                "training_relevant": 0,
            },
            "malformed",
        ]

        result = local_calendar_events(planned, competitions, external_events)
        self.assertEqual(
            [item["id"] for item in result],
            ["planned-2", "competition-1", "external-1", "planned-1"],
        )
        self.assertEqual(LOCAL_INTERVALS_SCOPE, "local+intervals")

    def test_local_entries_are_copied_and_inputs_are_not_mutated(self):
        planned = [{"id": "planned-1", "date": "2026-09-22", "meta": {"keep": 1}}]
        competitions = [{"id": "competition-1", "event_date": "2026-09-20"}]
        external_events = [
            {"id": "external-1", "event_date": "2026-09-21", "training_relevant": 1}
        ]
        before = copy.deepcopy((planned, competitions, external_events))

        result = local_calendar_events(planned, competitions, external_events)

        self.assertEqual((planned, competitions, external_events), before)
        planned_result = next(item for item in result if item["id"] == "planned-1")
        self.assertIsNot(planned_result, planned[0])
        self.assertEqual(planned_result, planned[0])

    def test_competition_and_external_event_fields_preserve_contract(self):
        competition = {
            "id": "competition-1",
            "event_date": "2026-09-20T12:30:00",
            "sport": "Ride",
            "external_id": "remote-1",
        }
        event = {
            "id": "external-1",
            "event_date": "2026-09-21T12:30:00",
            "training_relevant": "1",
        }

        competition_result = _local_calendar_competition(competition)
        event_result = _local_calendar_external_event(event)

        self.assertEqual(competition_result["date"], "2026-09-20")
        self.assertEqual(competition_result["start_date_local"], "2026-09-20T00:00:00")
        self.assertEqual(competition_result["sync_source"], LOCAL_INTERVALS_SCOPE)
        self.assertEqual(competition_result["sync_status"], "local")
        self.assertEqual(event_result["date"], "2026-09-21")
        self.assertEqual(event_result["sync_source"], "external-calendar")
        self.assertEqual(event_result["sync_status"], "read-only")


if __name__ == "__main__":
    unittest.main()
