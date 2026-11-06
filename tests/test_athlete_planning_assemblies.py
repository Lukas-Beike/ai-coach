from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock, Mock, patch

from backend.athlete.equipment import EquipmentService
from backend.athlete.measurements import number
from backend.errors import AppError
from backend.http_api.athlete_assembly import (
    AthleteDataAssembly,
    AthleteRepositories,
    AthleteRuntime,
)
from backend.performance.source_policy import PREFERENCE_PROFILE_FIELDS
from backend.planning.assembly import (
    PlanningDataAssembly,
    PlanningMutations,
    PlanningRepositories,
    PlanningRuntime,
)
from backend.sync.canonical_table_reader import CanonicalTableReader


class AthleteDataAssemblyTests(unittest.TestCase):
    def test_factories_use_active_manager_and_keep_shared_dependencies(self) -> None:
        manager = Mock(name="manager")
        event_buffer = Mock(name="event_buffer")
        repositories = [Mock(name=f"repository_{index}") for index in range(4)]
        row_reader = Mock(name="row_reader")
        serving = Mock(name="serving")
        now = Mock(name="utc_now")
        today = Mock(name="local_date")
        assembly = AthleteDataAssembly(
            dependencies=AthleteDataAssembly.Inputs(
                profile_mutation_coordinator=threading.RLock(),
                database_manager=lambda: manager,
                repositories=AthleteRepositories(
                    activity_feedback=repositories[0],
                    checkin=repositories[1],
                    profile=repositories[3],
                    key_values=Mock(name="key_values"),
                    activity_rows=lambda: row_reader,
                    table_serving=lambda: serving,
                    competition=repositories[2],
                ),
                runtime=AthleteRuntime(
                    utc_now=now,
                    local_date=today,
                    event_buffer=event_buffer,
                    normalize_profile=Mock(name="normalize_profile"),
                    normalize_competition=Mock(name="normalize_competition"),
                    uuid_factory=Mock(name="uuid_factory"),
                    load_inputs_changed=lambda: load_input_changes.append(True),
                ),
            )
        )
        load_input_changes: list[bool] = []

        feedback = assembly.activity_feedback()
        checkin = assembly.checkin()
        profile = assembly.profile()
        duplicate = assembly.duplicate_activity()

        self.assertIs(feedback._database_manager, manager)
        self.assertIs(feedback._feedback_repository, repositories[0])
        self.assertIs(checkin._manager, manager)
        self.assertIs(checkin._today, today)
        self.assertIs(profile._manager, manager)
        # The profile hook keeps the location invalidation and requests a local
        # load pass (card M6) only when a preferred threshold source or the time zone
        # changes.
        with patch(
            "backend.http_api.athlete_assembly.invalidate_for_location_change"
        ) as invalidate:
            profile._on_location_changed({"city": "a"}, {"city": "b"}, db=None)
            invalidate.assert_called_once_with({"city": "a"}, {"city": "b"}, db=None)
            self.assertEqual(load_input_changes, [])
            field = next(iter(PREFERENCE_PROFILE_FIELDS.values()))
            profile._on_location_changed({}, {field: "garmin"}, db=None)
            self.assertEqual(load_input_changes, [True])
            # A new time zone re-dates the stored loads (#1726).
            profile._on_location_changed(
                {"timezone": "Europe/Berlin"}, {"timezone": "UTC"}, db=None
            )
            self.assertEqual(load_input_changes, [True, True])
        self.assertIs(duplicate._database_manager, manager)
        self.assertIs(duplicate._event_buffer, event_buffer)
        self.assertFalse(hasattr(assembly, "activity_read"))
        self.assertIsInstance(duplicate._inspector._activities, CanonicalTableReader)
        self.assertIs(duplicate._inspector._serving, serving)


class EquipmentDependencyTests(unittest.TestCase):
    def test_assignment_uses_injected_session_summaries(self) -> None:
        read_summaries = Mock(return_value=())
        service = EquipmentService(MagicMock(), read_summaries, Mock(), Mock())
        with (
            patch(
                "backend.athlete.equipment.canonical_store.live_session_id",
                return_value=None,
            ),
            self.assertRaises(AppError) as raised,
        ):
            service.assign({"activity_id": "synthetic", "equipment_id": None})
        self.assertEqual(raised.exception.status, 404)
        read_summaries.assert_called_once_with()

    def test_usage_numbers_reject_invalid_values_and_preserve_zero(self) -> None:
        for value in (True, False, "12", None, -1, float("inf"), float("nan")):
            with self.subTest(value=value):
                self.assertIsNone(number(value))
        self.assertEqual(number(0), 0.0)
        self.assertEqual(number(12.5), 12.5)


class PlanningDataAssemblyTests(unittest.TestCase):
    def test_factories_retain_shared_revision_and_late_calendar_edge(self) -> None:
        manager = Mock(name="manager")
        revisions = Mock(name="revisions")
        local_date = Mock(name="local_date")
        conflict_factory = Mock(name="conflict_factory", return_value=Mock())
        publish = Mock(name="publish")
        competition_repository = Mock(name="competitions")
        assembly = PlanningDataAssembly(
            dependencies=PlanningDataAssembly.Inputs(
                database_manager=lambda: manager,
                repositories=PlanningRepositories(
                    competition=competition_repository,
                    training_plans=Mock(name="training_plans"),
                    key_values=Mock(name="key_values"),
                    plan_adjustments=Mock(name="adjustments"),
                ),
                runtime=PlanningRuntime(
                    revision=revisions,
                    event_buffer=Mock(name="events"),
                    utc_now=Mock(name="utc_now"),
                    local_date=local_date,
                    uuid_factory=Mock(name="uuid_factory"),
                    redact=Mock(name="redact"),
                ),
                mutations=PlanningMutations(
                    calendar_conflict_service=conflict_factory,
                    publish_change=publish,
                ),
            )
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
