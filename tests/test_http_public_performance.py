import unittest
from datetime import date
from unittest.mock import Mock, patch

from backend.http_api.public_performance import (
    PublicFeedbackStateService,
    PublicPerformanceStateService,
)
from backend.performance.canonical_inputs import EMPTY_PERFORMANCE_INPUTS
from backend.performance.chart_history import analysis_history
from backend.performance.freshness import GarminSyncStatus
from backend.performance.training_focus import training_focus


class PublicPerformanceStateTests(unittest.TestCase):
    def test_performance_state_projects_existing_snapshot_and_garmin_reads(self):
        garmin = GarminSyncStatus.from_state({"synced_at": "2026-09-22T09:00:00Z"})
        profile = {"timezone": "Europe/Berlin"}
        performance = {"available": True, "source": "Intervals.icu"}
        garmin_state = {"available": True, "has_sleep": True}
        garmin_payload_service = Mock()
        garmin_payload_service.sync_status.return_value = garmin
        profile_service = Mock()
        profile_service.get.return_value = profile
        garmin_projection_service = Mock()
        garmin_projection_service.public_state.return_value = garmin_state
        today = date(2026, 9, 23)
        service = PublicPerformanceStateService(
            garmin_payload_service,
            profile_service,
            garmin_projection_service,
            lambda: today,
        )

        with patch(
            "backend.http_api.public_performance.performance_context.current_performance_context",
            return_value=performance,
        ) as project_performance:
            result = service.performance_state()

        self.assertEqual(
            result,
            {
                "performance": {
                    **performance,
                    "history": analysis_history(
                        garmin, today, canonical=EMPTY_PERFORMANCE_INPUTS
                    ),
                    "training_focus_periods": {
                        "fortnight": training_focus(
                            garmin,
                            today,
                            "Europe/Berlin",
                            activities=(),
                            days=14,
                        ),
                        "twelveWeeks": training_focus(
                            garmin,
                            today,
                            "Europe/Berlin",
                            activities=(),
                            days=84,
                        ),
                    },
                },
                "garmin": garmin_state,
            },
        )
        # Canonical reads (#1416): the context takes the Garmin sync status and
        # no snapshot.
        project_performance.assert_called_once_with(
            garmin, profile, today, canonical=EMPTY_PERFORMANCE_INPUTS
        )
        garmin_payload_service.sync_status.assert_called_once_with()
        garmin_payload_service.view.assert_not_called()
        profile_service.get.assert_called_once_with()
        garmin_projection_service.public_state.assert_called_once_with(garmin)

    def test_feedback_state_keeps_the_30_checkin_limit_and_existing_contexts(self):
        checkins = [{"checkin_date": "2026-09-23"}]
        local_feedback = {"today": checkins[0], "recent": checkins}
        activity_feedback = {"recent": [{"activity_id": "ride-1"}]}
        checkin_service = Mock()
        checkin_service.list.return_value = checkins
        checkin_service.context.return_value = local_feedback
        activity_feedback_service = Mock()
        activity_feedback_service.context.return_value = activity_feedback
        service = PublicFeedbackStateService(checkin_service, activity_feedback_service)

        result = service.feedback_state()

        self.assertEqual(
            result,
            {
                "checkins": checkins,
                "local_feedback": local_feedback,
                "activity_feedback": activity_feedback,
            },
        )
        checkin_service.list.assert_called_once_with(30)
        checkin_service.context.assert_called_once_with()
        activity_feedback_service.context.assert_called_once_with()

    def test_feedback_state_reuses_checkins_from_composite_state(self):
        checkin_service = Mock()
        checkin_service.context.return_value = {"recent": []}
        activity_feedback_service = Mock()
        activity_feedback_service.context.return_value = {"recent": []}
        checkins = [{"checkin_date": "2026-09-23"}]

        result = PublicFeedbackStateService(
            checkin_service, activity_feedback_service
        ).feedback_state(checkins)

        self.assertIs(result["checkins"], checkins)
        checkin_service.list.assert_not_called()

    def test_from_inputs_projects_the_composite_state_inputs(self):
        garmin_payload_service = Mock()
        garmin_payload_service.sync_status.return_value = GarminSyncStatus()
        profile_service = Mock()
        profile_service.get.return_value = {}
        service = PublicPerformanceStateService(
            garmin_payload_service,
            profile_service,
            Mock(),
            lambda: date(2026, 9, 23),
        )

        with patch(
            "backend.http_api.public_performance.performance_context.current_performance_context",
            return_value={},
        ):
            service.from_inputs(None)


if __name__ == "__main__":
    unittest.main()
