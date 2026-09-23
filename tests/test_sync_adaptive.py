from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from backend.athlete.checkins import CHECKIN_TEXT_LIMITS
from backend.calendar.canonical import ISO_MIDNIGHT_SUFFIX
from backend.config import load_config
from backend.errors import INTERVALS_API_KEY_ERROR, AppError
from backend.sync.adaptive import (
    AdaptivePreviewFollowupService,
    ILLNESS_CALENDAR_CATEGORY,
    ILLNESS_EVENT_EXTERNAL_PREFIX,
    IllnessPauseSyncService,
)


class AdaptivePreviewFollowupServiceTests(unittest.TestCase):
    def test_check_returns_replan_state_from_preview_changes(self):
        preview_service = Mock()
        preview_service.preview.return_value = {"changes": [{"id": "one"}, {}]}
        service = AdaptivePreviewFollowupService(preview_service, Mock())

        result = service.check("weather")

        self.assertEqual(result, {"needs_replan": True, "replan_changes": 2})
        preview_service.preview.assert_called_once_with()
        preview_service.status.assert_not_called()

    def test_check_uses_empty_changes_for_non_dict_preview(self):
        preview_service = Mock()
        preview_service.preview.return_value = [{"changes": [1]}]
        service = AdaptivePreviewFollowupService(preview_service, Mock())

        self.assertEqual(
            service.check("weather"),
            {"needs_replan": False, "replan_changes": 0},
        )

    def test_check_counts_only_list_changes(self):
        preview_service = Mock()
        preview_service.preview.return_value = {"changes": {"one": True}}
        service = AdaptivePreviewFollowupService(preview_service, Mock())

        self.assertEqual(
            service.check("weather"),
            {"needs_replan": True, "replan_changes": 0},
        )

    def test_preview_failure_logs_and_returns_current_status(self):
        preview_service = Mock()
        preview_service.preview.side_effect = RuntimeError("preview failed")
        preview_service.status.return_value = {"needs_replan": True, "replan_changes": 4}
        logger = Mock()
        service = AdaptivePreviewFollowupService(preview_service, logger)

        result = service.check("intervals")

        self.assertEqual(result, {"needs_replan": True, "replan_changes": 4})
        logger.warning.assert_called_once_with(
            "Adaptive preview after provider sync failed",
            extra={
                "event": "adaptive_replan_preview_failed",
                "context": {"reason": "intervals"},
            },
            exc_info=True,
        )
        preview_service.status.assert_called_once_with()

    def test_status_failure_propagates_after_preview_failure(self):
        preview_service = Mock()
        preview_error = RuntimeError("preview failed")
        status_error = RuntimeError("status failed")
        preview_service.preview.side_effect = preview_error
        preview_service.status.side_effect = status_error
        service = AdaptivePreviewFollowupService(preview_service, Mock())

        with self.assertRaises(RuntimeError) as raised:
            service.check("weather")

        self.assertIs(raised.exception, status_error)
        preview_service.status.assert_called_once_with()


class IllnessPauseSyncServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def make_config(self, intervals_api_key: str = "fake-intervals-key"):
        return load_config(self.root, self.root, {"INTERVALS_API_KEY": intervals_api_key})

    def make_apply_service(self, result):
        apply_service = Mock()
        apply_service.apply.return_value = result
        competitions = Mock()
        competitions.list.return_value = [{"name": "race", "event_date": "2026-10-01", "priority": 1}]
        preview = Mock()
        preview.latest_preview.return_value = {"id": "preview"}
        preview.status.return_value = {"illness_pause_pending": False}
        redactor = Mock()
        redactor.redact_text.side_effect = lambda value: value
        return apply_service, competitions, preview, redactor

    def make_service(self, result):
        apply_service, competitions, preview, redactor = self.make_apply_service(result)
        service = IllnessPauseSyncService(
            self.make_config(),
            Mock(),
            adaptive_replan_apply_service=apply_service,
            competition_service=competitions,
            adaptive_replan_preview_service=preview,
            redactor=redactor,
            today=lambda: date(2026, 9, 23),
        )
        return service, apply_service, competitions, preview, redactor

    def test_missing_api_key_raises_exact_service_unavailable_error(self):
        writer = Mock()
        service = IllnessPauseSyncService(self.make_config(""), writer)

        with self.assertRaises(AppError) as raised:
            service.sync({"illness": "flu"})

        self.assertEqual(raised.exception.status, 503)
        self.assertEqual(str(raised.exception), INTERVALS_API_KEY_ERROR)
        writer.upsert_calendar_events.assert_not_called()

    def test_sync_passes_exact_event_builder_arguments_and_returns_exact_result(self):
        pause = {"start_date": "2026-09-21", "end_date": "2026-09-22", "illness": " flu "}
        events = [{"event": "one"}, {"event": "two"}]
        pushed = [{"id": "remote-one"}, {"id": "remote-two"}, {"id": "remote-three"}]
        writer = Mock()
        writer.upsert_calendar_events.return_value = pushed
        service = IllnessPauseSyncService(self.make_config(), writer)

        with patch(
            "backend.sync.adaptive.planning_adaptive.illness_calendar_events",
            return_value=events,
        ) as build_events:
            result = service.sync(pause)

        build_events.assert_called_once_with(
            pause,
            "flu",
            category="SICK",
            external_prefix="intervals-coach-sick-",
            midnight_suffix=ISO_MIDNIGHT_SUFFIX,
        )
        writer.upsert_calendar_events.assert_called_once_with(events)
        self.assertEqual(
            result,
            {"status": "ok", "synced": 3, "category": "SICK"},
        )
        self.assertEqual(ILLNESS_CALENDAR_CATEGORY, "SICK")
        self.assertEqual(ILLNESS_EVENT_EXTERNAL_PREFIX, "intervals-coach-sick-")

    def test_whitespace_only_illness_remains_empty_after_trimming(self):
        writer = Mock()
        writer.upsert_calendar_events.return_value = []
        service = IllnessPauseSyncService(self.make_config(), writer)

        with patch(
            "backend.sync.adaptive.planning_adaptive.illness_calendar_events",
            return_value=[],
        ) as build_events:
            service.sync({"illness": "  "})

        self.assertEqual(build_events.call_args.args[1], "")

    def test_illness_is_trimmed_and_limited_to_checkin_text_limit(self):
        writer = Mock()
        writer.upsert_calendar_events.return_value = []
        service = IllnessPauseSyncService(self.make_config(), writer)
        raw_illness = "  " + "x" * (CHECKIN_TEXT_LIMITS["illness"] + 25) + "  "

        with patch(
            "backend.sync.adaptive.planning_adaptive.illness_calendar_events",
            return_value=[],
        ) as build_events:
            service.sync({"illness": raw_illness})

        normalized_illness = build_events.call_args.args[1]
        self.assertEqual(len(normalized_illness), CHECKIN_TEXT_LIMITS["illness"])
        self.assertEqual(normalized_illness, "x" * CHECKIN_TEXT_LIMITS["illness"])

    def test_provider_error_propagates_without_reclassification(self):
        provider_error = RuntimeError("fake provider failure")
        writer = Mock()
        writer.upsert_calendar_events.side_effect = provider_error
        service = IllnessPauseSyncService(self.make_config(), writer)

        with self.assertRaises(RuntimeError) as raised:
            service.sync(
                {
                    "start_date": "2026-09-21",
                    "end_date": "2026-09-22",
                    "illness": "flu",
                }
            )

        self.assertIs(raised.exception, provider_error)
        writer.upsert_calendar_events.assert_called_once()

    def test_apply_keeps_local_result_and_status_without_explicit_remote_approval(self):
        applied = {
            "status": "applied",
            "id": "adjustment",
            "updated": 2,
            "updated_checkins": 3,
            "stale": [],
            "illness_pause": {"illness": "flu", "approved": False},
        }
        service, apply_service, competitions, preview, _ = self.make_service(applied)

        result = service.apply("adjustment")

        apply_service.apply.assert_called_once_with("adjustment")
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["intervals_sync"])
        self.assertEqual(result["planning"]["latest_replan"], {"id": "preview"})
        competitions.list.assert_called_once_with()
        preview.latest_preview.assert_called_once_with()
        preview.status.assert_called_once_with()

    def test_apply_writes_remote_pause_only_when_explicitly_requested(self):
        applied = {
            "status": "applied",
            "id": "adjustment",
            "updated": 2,
            "updated_checkins": 3,
            "stale": [],
            "illness_pause": {"illness": "flu", "approved": False},
        }
        service, _, _, _, _ = self.make_service(applied)
        service.sync = Mock(return_value={"status": "ok", "synced": 2, "category": "SICK"})

        result = service.apply("adjustment", sync_illness_to_intervals=True)

        service.sync.assert_called_once_with(applied["illness_pause"])
        self.assertEqual(result["intervals_sync"]["synced"], 2)

    def test_apply_redacts_remote_failure_and_keeps_local_apply_result(self):
        applied = {
            "status": "applied",
            "id": "adjustment",
            "updated": 2,
            "updated_checkins": 3,
            "stale": [],
            "illness_pause": {"illness": "flu", "approved": False},
        }
        service, _, _, _, redactor = self.make_service(applied)
        service.sync = Mock(side_effect=RuntimeError("provider detail"))
        redactor.redact_text.side_effect = lambda value: "redacted detail"

        result = service.apply("adjustment", sync_illness_to_intervals=True)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            result["intervals_sync"],
            {"status": "error", "error": "redacted detail"},
        )
        redactor.redact_text.assert_called_once_with("provider detail")

    def test_apply_returns_already_applied_status_without_remote_sync(self):
        applied = {"status": "already_applied", "id": "adjustment"}
        service, apply_service, competitions, _, _ = self.make_service(applied)
        service.sync = Mock()

        result = service.apply("adjustment", sync_illness_to_intervals=True)

        self.assertEqual(result, applied)
        service.sync.assert_not_called()
        competitions.list.assert_not_called()


if __name__ == "__main__":
    unittest.main()
