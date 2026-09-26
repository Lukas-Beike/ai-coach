from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.athlete.assembly import AthleteDataAssembly
from backend.planning.assembly import PlanningDataAssembly


class AthleteDataAssemblyTests(unittest.TestCase):
    def test_factories_use_active_manager_and_keep_shared_dependencies(self) -> None:
        manager = Mock(name="manager")
        event_buffer = Mock(name="event_buffer")
        repositories = [Mock(name=f"repository_{index}") for index in range(5)]
        now = Mock(name="utc_now")
        today = Mock(name="local_date")
        assembly = AthleteDataAssembly(
            database_manager=lambda: manager,
            activity_feedback_repository=repositories[0],
            checkin_repository=repositories[1],
            profile_repository=repositories[3],
            key_value_repository=Mock(name="key_values"),
            snapshot_repository=repositories[4],
            utc_now=now,
            local_date=today,
            event_buffer=event_buffer,
            competition_repository=repositories[2],
            normalize_profile=Mock(name="normalize_profile"),
            normalize_competition=Mock(name="normalize_competition"),
            uuid_factory=Mock(name="uuid_factory"),
        )

        feedback = assembly.activity_feedback()
        checkin = assembly.checkin()
        profile = assembly.profile()
        duplicate = assembly.duplicate_activity()

        self.assertIs(feedback._database_manager, manager)
        self.assertIs(feedback._feedback_repository, repositories[0])
        self.assertIs(checkin._manager, manager)
        self.assertIs(checkin._today, today)
        self.assertIs(profile._manager, manager)
        self.assertIs(duplicate._database_manager, manager)
        self.assertIs(duplicate._event_buffer, event_buffer)


class PlanningDataAssemblyTests(unittest.TestCase):
    def test_factories_retain_shared_revision_and_late_calendar_edge(self) -> None:
        manager = Mock(name="manager")
        revisions = Mock(name="revisions")
        local_date = Mock(name="local_date")
        conflict_factory = Mock(name="conflict_factory", return_value=Mock())
        publish = Mock(name="publish")
        competition_repository = Mock(name="competitions")
        assembly = PlanningDataAssembly(
            database_manager=lambda: manager,
            competition_repository=competition_repository,
            training_plan_repository=Mock(name="training_plans"),
            key_value_repository=Mock(name="key_values"),
            planning_revision_service=revisions,
            event_buffer=Mock(name="events"),
            utc_now=Mock(name="utc_now"),
            local_date=local_date,
            uuid_factory=Mock(name="uuid_factory"),
            redact=Mock(name="redact"),
            calendar_conflict_service=conflict_factory,
            publish_change=publish,
            plan_adjustment_repository=Mock(name="adjustments"),
        )

        self.assertEqual(conflict_factory.call_count, 0)
        self.assertEqual(manager.call_count, 0)
        planned = assembly.planned_unit()
        library = assembly.workout_library()
        plan = assembly.training_plan()
        competition = assembly.competition()

        self.assertEqual(conflict_factory.call_count, 1)
        self.assertIs(planned._database_manager, manager)
        self.assertIs(planned._planning_revision_service, revisions)
        self.assertIs(planned._today, local_date)
        self.assertIs(library._database_manager, manager)
        self.assertIs(library._publish_change, publish)
        self.assertIs(plan._database_manager, manager)
        self.assertIs(plan._revisions, revisions)
        self.assertIs(competition._database_manager, manager)
        self.assertIs(competition._repository, competition_repository)


if __name__ == "__main__":
    unittest.main()
