"""Focused regressions for the public planning-state service."""

from __future__ import annotations

import unittest
from datetime import date
from threading import Lock
from unittest.mock import MagicMock, Mock, call, patch

from backend.http_api.public_plan import PublicPlanDependencies, PublicPlanStateService


class PublicPlanStateServiceTests(unittest.TestCase):
    def make_service(self, weather_state: dict | None = None):
        snapshot = {
            "recent_activities": [{"id": str(index)} for index in range(1001)],
            "provider_sync": {
                "calendar_window": {"start": "2026-01-01", "end": "2026-03-01"}
            },
        }
        planned = [{"id": "planned-1", "start_date_local": "2026-01-02T07:00:00"}]
        competitions = [{"id": "competition-1"}]
        external_1000 = [{"id": f"external-{index}"} for index in range(1000)]
        external_50 = [{"id": f"daily-{index}"} for index in range(50)]
        services = {
            "sync": Mock(),
            "planned": Mock(),
            "feedback": Mock(),
            "weather": Mock(),
            "followup": Mock(),
            "manager": Mock(),
            "db_lock": Lock(),
            "key_values": Mock(),
            "plans": Mock(),
            "external": Mock(),
            "external_sync": Mock(),
            "daily": Mock(),
            "checkins": Mock(),
            "competitions": Mock(),
            "adaptive": Mock(),
            "quick_actions": Mock(),
        }
        services["sync"].latest_snapshot.return_value = snapshot
        services["planned"].list.return_value = planned
        services["feedback"].attach_to_activities.side_effect = lambda rows: rows
        services["weather"].state.return_value = weather_state or {
            "days": [],
            "_refreshed": False,
        }
        services["manager"].unit_of_work.return_value = MagicMock()
        services["manager_factory"] = Mock(return_value=services["manager"])
        services["key_values"].get.return_value = "{}"
        services["plans"].list.return_value = []
        services["external"].list_events.side_effect = [external_1000, external_50]
        services["external"].state.return_value = {"events": external_1000[:300]}
        services["external_sync"].running.return_value = False
        services["daily"].build.return_value = []
        services["checkins"].list.return_value = []
        services["competitions"].list.return_value = competitions
        services["adaptive"].latest_preview.return_value = None
        services["adaptive"].status.return_value = {"status": "idle"}
        services["quick_actions"].state.return_value = []
        projection = Mock(return_value={"planned": planned, "training_calendar": []})
        service = PublicPlanStateService(
            PublicPlanDependencies(
                sync_state=services["sync"],
                planned_units=services["planned"],
                activity_feedback=services["feedback"],
                weather=services["weather"],
                adaptive_followup=services["followup"],
                database_manager_factory=services["manager_factory"],
                db_lock=services["db_lock"],
                key_values=services["key_values"],
                training_plans=services["plans"],
                external_calendar=services["external"],
                external_calendar_sync=services["external_sync"],
                daily_context=services["daily"],
                checkins=services["checkins"],
                competitions=services["competitions"],
                adaptive_preview=services["adaptive"],
                coach_quick_actions=services["quick_actions"],
                today=lambda: date(2026, 1, 1),
                external_calendar_configured=True,
                external_calendar_window_days=35,
                default_workout_name="Geplante Einheit",
            ),
        )
        return (
            service,
            services,
            projection,
            snapshot,
            planned,
            competitions,
            external_1000,
            external_50,
        )

    def test_local_read_keeps_bounds_calendar_scope_and_skips_weather_refresh(self):
        (
            service,
            services,
            projection,
            snapshot,
            planned,
            competitions,
            external_1000,
            external_50,
        ) = self.make_service()
        with patch(
            "backend.http_api.public_plan.calendar_read_model.project_planning_calendar",
            projection,
        ):
            state = service.read(local_only=True)

        services["planned"].list.assert_called_once_with(500)
        services["feedback"].attach_to_activities.assert_called_once_with(
            snapshot["recent_activities"][:1000]
        )
        services["weather"].state.assert_called_once_with(
            unittest.mock.ANY, refresh=False
        )
        services["followup"].check.assert_not_called()
        services["plans"].list.assert_called_once_with(limit=30)
        services["checkins"].list.assert_called_once_with(365)
        services["external"].list_events.assert_has_calls(
            [
                call(1000, training_relevant_only=True),
                call(50, training_relevant_only=True),
            ]
        )
        projection.assert_called_once()
        projected = projection.call_args.args
        self.assertEqual(projected[0], planned)
        self.assertEqual(len(projected[1]), 1000)
        self.assertEqual(projected[3], competitions)
        self.assertEqual(projected[4], external_1000)
        self.assertEqual(
            projection.call_args.kwargs["provider_window"],
            snapshot["provider_sync"]["calendar_window"],
        )
        self.assertEqual(services["daily"].build.call_args.args[-1], external_50)
        self.assertEqual(state["external_calendar"]["events"], external_1000[:300])

    def test_weather_refresh_followup_only_runs_when_weather_reports_refreshed(self):
        service, services, _projection, *_ = self.make_service(
            {"days": [], "_refreshed": True}
        )
        with patch(
            "backend.http_api.public_plan.calendar_read_model.project_planning_calendar",
            return_value={},
        ):
            service.read()

        services["weather"].state.assert_called_once_with(
            unittest.mock.ANY, refresh=True
        )
        services["followup"].check.assert_called_once_with("weather")

    def test_history_manager_factory_is_resolved_while_database_lock_is_held(self):
        service, services, _projection, *_ = self.make_service()
        resolved_while_locked = []

        def resolve_manager():
            resolved_while_locked.append(services["db_lock"].locked())
            return services["manager"]

        services["manager_factory"].side_effect = resolve_manager
        with patch(
            "backend.http_api.public_plan.calendar_read_model.project_planning_calendar",
            return_value={},
        ):
            service.read(local_only=True)

        services["manager_factory"].assert_called_once_with()
        self.assertEqual(resolved_while_locked, [True])
        self.assertFalse(services["db_lock"].locked())


if __name__ == "__main__":
    unittest.main()
