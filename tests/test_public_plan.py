"""Focused regressions for the public planning-state service."""

from __future__ import annotations

import unittest
from datetime import date
from typing import Any, ClassVar
from unittest.mock import MagicMock, Mock, patch

from backend.activities.detail_store import summary_fingerprint
from backend.http_api.public_plan import PublicPlanDependencies, PublicPlanStateService


class PublicPlanStateServiceTests(unittest.TestCase):
    def make_service(self, weather_state: dict | None = None):
        activity_rows = Mock()
        activity_rows.compact.return_value = [
            {"id": str(index)} for index in range(1001)
        ]
        snapshot = {
            "recent_activities": activity_rows.compact.return_value,
            "provider_sync": {
                "calendar_window": {"start": "2026-01-01", "end": "2026-03-01"}
            },
        }
        planned = [{"id": "planned-1", "starts_at_local": "2026-01-02T07:00:00"}]
        competitions = [{"id": "competition-1"}]
        external_1000 = [{"id": f"external-{index}"} for index in range(1000)]
        external_window = [{"id": f"daily-{index}"} for index in range(60)]
        services: dict[str, Any] = {
            "sync": Mock(),
            "planned": Mock(),
            "feedback": Mock(),
            "weather": Mock(),
            "followup": Mock(),
            "manager": Mock(),
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
        services["sync"].sync_metadata.return_value = {
            "provider_sync": snapshot["provider_sync"]
        }
        services["planned"].list.return_value = planned
        services["feedback"].attach_to_activities.side_effect = lambda rows: rows
        services["weather"].state.return_value = weather_state or {
            "days": [],
            "_refreshed": False,
        }
        services["manager"].unit_of_work.return_value = MagicMock()
        services["manager"].reader.return_value = MagicMock()
        services["manager"].read_snapshot.return_value = MagicMock()
        services["manager_factory"] = Mock(return_value=services["manager"])
        services["key_values"].get.return_value = "{}"
        services["plans"].list.return_value = []
        services["external"].list_events.side_effect = [external_1000]
        services["external"].list_events_in_window.return_value = external_window
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
                activity_rows=activity_rows,
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
            external_window,
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
            external_window,
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
        services["external"].list_events.assert_called_once_with(
            1000, training_relevant_only=True
        )
        services["external"].list_events_in_window.assert_called_once_with(
            35, training_relevant_only=True
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
        self.assertEqual(services["daily"].build.call_args.args[-1], external_window)
        self.assertEqual(state["external_calendar"]["events"], external_1000[:300])

    def test_internal_read_keeps_stored_metrics_and_public_read_translates(self):
        service, services, *_ = self.make_service()
        services["external"].list_events.side_effect = None
        services["external"].list_events.return_value = []
        entry = {
            "id": "planned-1",
            "icu_training_load": 30,
            "planned_duration_s": 3600,
            "compliance": {
                "actual_activity": {"icu_training_load": 28, "moving_time": 3500}
            },
        }
        with patch(
            "backend.http_api.public_plan.calendar_read_model.project_planning_calendar",
            side_effect=lambda *args, **kwargs: {
                "planned": [dict(entry)],
                "training_calendar": [dict(entry)],
                "calendar": [dict(entry)],
                "planning_view": {"items": [dict(entry)]},
            },
        ):
            internal = service.read(local_only=True)
            public = service.read_public(local_only=True)

        # The training report and season scenarios read the stored keys.
        self.assertEqual(30, internal["planned"][0]["icu_training_load"])
        self.assertEqual(30, internal["training_calendar"][0]["icu_training_load"])
        expected = {
            "id": "planned-1",
            "training_load": 30,
            "planned_duration_s": 3600,
            "compliance": {
                "actual_activity": {"training_load": 28, "moving_duration_s": 3500}
            },
        }
        for key in ("planned", "training_calendar", "calendar"):
            self.assertEqual(expected, public[key][0])
        self.assertEqual(expected, public["planning_view"]["items"][0])
        actual = internal["calendar"][0]["compliance"]["actual_activity"]
        self.assertEqual(3500, actual["moving_time"])

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

    def test_refreshing_read_keeps_the_weather_write_outside_the_snapshot(self):
        service, services, _projection, *_ = self.make_service()
        open_snapshots = []
        snapshot = services["manager"].read_snapshot
        snapshot.return_value.__enter__.side_effect = lambda: open_snapshots.append(1)
        snapshot.return_value.__exit__.side_effect = lambda *_: open_snapshots.pop()
        during_refresh = []
        services["weather"].state.side_effect = lambda *a, **k: (
            during_refresh.append(len(open_snapshots)) or {"days": []}
        )
        with patch(
            "backend.http_api.public_plan.calendar_read_model.project_planning_calendar",
            return_value={},
        ):
            service.read()

        self.assertEqual(during_refresh, [0])
        self.assertEqual(snapshot.call_count, 2)
        services["manager"].unit_of_work.assert_not_called()

    def test_local_read_uses_one_snapshot_without_writer(self):
        service, services, _projection, *_ = self.make_service()
        with patch(
            "backend.http_api.public_plan.calendar_read_model.project_planning_calendar",
            return_value={},
        ):
            service.read(local_only=True)

        services["manager"].read_snapshot.assert_called_once_with()
        services["manager"].unit_of_work.assert_not_called()


class WorkoutProfileAttachmentTests(unittest.TestCase):
    ROW: ClassVar[dict[str, Any]] = {"id": "i7", "name": "Ride", "moving_time": 3600}
    SUMMARY: ClassVar[dict[str, Any]] = {
        "id": "act_1",
        "record_ids": {"intervals": "i7"},
        "started_at_local": "2026-01-01T07:00:00",
    }

    def profiles(self, fingerprint):
        return {"i7": {"fingerprint": fingerprint, "profile": {"zones": [1]}}}

    def test_profile_attaches_under_the_stored_key_when_the_raw_row_matches(self):
        fingerprint = summary_fingerprint(self.ROW)
        result = PublicPlanStateService._with_profile(
            self.SUMMARY, self.profiles(fingerprint), {"i7": fingerprint}
        )
        self.assertEqual(result["workout_profile"], {"zones": [1]})
        self.assertNotIn("workout_profile", self.SUMMARY)

    def test_stale_or_unverifiable_profile_is_not_attached(self):
        stale = self.profiles("old")
        current = {"i7": summary_fingerprint(self.ROW)}
        for profiles, fingerprints in ((stale, current), (stale, {}), ({}, current)):
            self.assertEqual(
                PublicPlanStateService._with_profile(
                    self.SUMMARY, profiles, fingerprints
                ),
                self.SUMMARY,
            )
