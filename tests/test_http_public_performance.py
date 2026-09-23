import unittest
from datetime import date
from unittest.mock import Mock, patch

from backend.http_api.public_performance import (
    PublicFeedbackStateService,
    PublicPerformanceStateService,
)


class PublicPerformanceStateTests(unittest.TestCase):
    def test_performance_state_projects_existing_snapshot_and_garmin_reads(self):
        snapshot = {"synced_at": "2026-09-22T10:00:00Z"}
        garmin = {"sleep": [{"date": "2026-09-22"}]}
        profile = {"timezone": "Europe/Berlin"}
        performance = {"available": True, "source": "Intervals.icu"}
        garmin_state = {"available": True, "has_sleep": True}
        sync_state_repository = Mock()
        sync_state_repository.latest_snapshot.return_value = snapshot
        garmin_payload_service = Mock()
        garmin_payload_service.snapshot.return_value = garmin
        profile_service = Mock()
        profile_service.get.return_value = profile
        garmin_projection_service = Mock()
        garmin_projection_service.public_state.return_value = garmin_state
        today = date(2026, 9, 23)
        service = PublicPerformanceStateService(
            sync_state_repository,
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

        self.assertEqual(result, {"performance": performance, "garmin": garmin_state})
        project_performance.assert_called_once_with(snapshot, garmin, profile, today)
        sync_state_repository.latest_snapshot.assert_called_once_with()
        garmin_payload_service.snapshot.assert_called_once_with()
        profile_service.get.assert_called_once_with()
        garmin_projection_service.public_state.assert_called_once_with()

    def test_feedback_state_keeps_the_30_checkin_limit_and_existing_contexts(self):
        checkins = [{"checkin_date": "2026-09-23"}]
        local_feedback = {"today": checkins[0], "recent": checkins}
        activity_feedback = {"recent": [{"activity_id": "ride-1"}]}
        checkin_service = Mock()
        checkin_service.list.return_value = checkins
        checkin_service.context.return_value = local_feedback
        activity_feedback_service = Mock()
        activity_feedback_service.context.return_value = activity_feedback
        service = PublicFeedbackStateService(
            checkin_service, activity_feedback_service
        )

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


if __name__ == "__main__":
    unittest.main()
