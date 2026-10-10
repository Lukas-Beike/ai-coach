from __future__ import annotations

import unittest
from unittest.mock import MagicMock, Mock

from backend.athlete.equipment import EquipmentService
from backend.athlete.measurements import number
from backend.errors import AppError
from backend.http_api.athlete_assembly import (
    AthleteDataAssembly,
    AthleteRepositories,
    AthleteRuntime,
)
from backend.performance.training_report import canonical_rows
from backend.planning.assembly import (
    PlanningDataAssembly,
    PlanningMutations,
    PlanningRepositories,
    PlanningRuntime,
)
from backend.weather.cache import invalidate_for_location_change


class AthleteDataAssemblyTests(unittest.TestCase):
    def test_factories_use_active_manager_and_keep_shared_dependencies(self) -> None:
        manager = Mock(name="manager")
        event_buffer = Mock(name="event_buffer")
        repositories = [Mock(name=f"repository_{index}") for index in range(5)]
        snapshot_reader = Mock(name="snapshot_reader")
        now = Mock(name="utc_now")
        today = Mock(name="local_date")
        assembly = AthleteDataAssembly(
            dependencies=AthleteDataAssembly.Inputs(
                database_manager=lambda: manager,
                repositories=AthleteRepositories(
                    activity_feedback=repositories[0],
                    checkin=repositories[1],
                    profile=repositories[3],
                    key_values=Mock(name="key_values"),
                    snapshot=repositories[4],
                    snapshot_reader=snapshot_reader,
                    competition=repositories[2],
                ),
                runtime=AthleteRuntime(
                    utc_now=now,
                    local_date=today,
                    event_buffer=event_buffer,
                    normalize_profile=Mock(name="normalize_profile"),
                    normalize_competition=Mock(name="normalize_competition"),
                    uuid_factory=Mock(name="uuid_factory"),
                ),
            )
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
        self.assertIs(profile._on_location_changed, invalidate_for_location_change)
        self.assertIs(assembly.equipment()._canonical_rows, canonical_rows)
        self.assertIs(duplicate._database_manager, manager)
        self.assertIs(duplicate._event_buffer, event_buffer)
        self.assertIs(feedback._snapshot_reader, snapshot_reader)
        self.assertFalse(hasattr(assembly, "activity_read"))
        self.assertIs(duplicate._snapshot_reader, snapshot_reader)

    def test_training_snapshot_uses_injected_reader_without_changing_provenance(self):
        manager = MagicMock()
        db = manager.unit_of_work.return_value.__enter__.return_value
        snapshot = {
            "synced_at": "2026-09-20T08:00:00+00:00",
            "source_freshness": {"intervals": {"freshness": "current"}},
            "provider_sync": {"source": "intervals", "cursor": "synthetic"},
        }
        reader = Mock(latest_snapshot=Mock(return_value=snapshot))
        assembly = AthleteDataAssembly(
            dependencies=AthleteDataAssembly.Inputs(
                database_manager=lambda: manager,
                repositories=AthleteRepositories(
                    activity_feedback=Mock(),
                    checkin=Mock(),
                    profile=Mock(),
                    key_values=Mock(),
                    snapshot=Mock(),
                    snapshot_reader=reader,
                    competition=Mock(),
                ),
                runtime=AthleteRuntime(
                    utc_now=Mock(),
                    local_date=Mock(),
                    event_buffer=Mock(),
                    normalize_profile=Mock(),
                    normalize_competition=Mock(),
                    uuid_factory=Mock(),
                ),
            )
        )

        self.assertIs(assembly.training_snapshot(), snapshot)
        reader.latest_snapshot.assert_called_once_with(db)


class EquipmentDependencyTests(unittest.TestCase):
    def test_assignment_uses_injected_canonical_activity_rows(self) -> None:
        snapshot = {"recent_activities": [{"id": "synthetic"}]}
        rows = Mock(return_value=([], 0))
        service = EquipmentService(Mock(), lambda: snapshot, Mock(), Mock(), rows)
        with self.assertRaises(AppError) as raised:
            service.assign({"activity_id": "synthetic", "equipment_id": None})
        self.assertEqual(raised.exception.status, 404)
        rows.assert_called_once_with(snapshot)

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
