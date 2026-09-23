"""Authorization and effect boundaries for structured Coach sync tools."""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from backend.coach.sync_tools import CoachSyncToolService
from backend.errors import AppError


class CoachSyncToolServiceTests(unittest.TestCase):
    def setUp(self):
        self.queue = Mock()
        self.authority = Mock()
        self.conflicts = Mock()
        self.plan_sync = Mock()
        self.plan_repair = Mock()
        self.plan_push = Mock()
        self.provider_refresh = Mock()
        self.service = CoachSyncToolService(
            self.queue, self.authority, self.conflicts,
            self.plan_sync, self.plan_repair, self.plan_push, self.provider_refresh,
        )

    def test_provider_refresh_checks_scope_and_preserves_cancel_and_job_tracking(self):
        intent = {"operation": "start_provider_refresh", "target_system": "garmin", "authorization_scope": []}
        jobs = []
        with self.assertRaises(AppError):
            self.service.execute("start_provider_refresh", {}, intent=intent, sync_job_ids=jobs)
        self.provider_refresh.start.assert_not_called()
        intent["authorization_scope"] = ["garmin_refresh"]
        self.provider_refresh.start.return_value = {"status": "queued", "sync_job_id": "job-2"}
        cancel = threading.Event()
        self.service.execute("start_provider_refresh", {"days": 3}, intent=intent, sync_job_ids=jobs, cancel_event=cancel)
        self.provider_refresh.start.assert_called_once_with("garmin", {"days": 3}, cancel_event=cancel)
        self.assertEqual(jobs, ["job-2"])
        self.provider_refresh.start.return_value = {"status": "complete"}
        self.service.execute("start_provider_refresh", {}, intent=intent, sync_job_ids=jobs)
        self.assertEqual(jobs, ["job-2"])

    def test_performance_refresh_requires_intervals_scope_before_enqueue(self):
        intent = {"operation": "refresh_current_performance", "target_system": "garmin", "authorization_scope": ["intervals_refresh"]}
        jobs = []
        with self.assertRaises(AppError):
            self.service.execute("refresh_current_performance", {}, intent=intent, sync_job_ids=jobs)
        self.provider_refresh.queue_performance_refresh.assert_not_called()
        intent["target_system"] = "intervals"
        self.provider_refresh.queue_performance_refresh.return_value = {"sync_job_id": "job-3"}
        self.service.execute("refresh_current_performance", {"reason": "now"}, intent=intent, sync_job_ids=jobs)
        self.provider_refresh.queue_performance_refresh.assert_called_once_with({"reason": "now"})
        self.assertEqual(jobs, ["job-3"])

    def test_plan_repair_checks_object_scopes_before_mutation(self):
        intent = {
            "operation": "start_intervals_plan_sync",
            "target_system": "intervals",
            "authorization_scope": ["intervals_sync"],
        }
        self.plan_repair.prepare.return_value = SimpleNamespace(
            required_scope_groups=[("planned_unit:unit-1",)]
        )
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "start_intervals_plan_sync", {"repair": True},
                intent=intent, sync_job_ids=[],
            )
        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "intent_scope_denied"))
        self.plan_repair.execute.assert_not_called()
        self.plan_push.enqueue.assert_not_called()

    def test_competition_push_marks_authority_only_after_scope_check(self):
        intent = {
            "operation": "sync_competitions", "target_system": "intervals",
            "authorization_scope": [],
        }
        with self.assertRaises(AppError):
            self.service.execute("sync_competitions", {}, intent=intent, sync_job_ids=[])
        self.authority.mark_competitions_authoritative.assert_not_called()
        self.queue.enqueue.assert_not_called()

        intent["authorization_scope"] = ["local_competitions"]
        self.queue.enqueue.return_value = {"id": "job-1"}
        jobs = []
        result = self.service.execute(
            "sync_competitions", {}, intent=intent, sync_job_ids=jobs,
        )
        self.assertEqual(result, {"ok": True, "status": "queued", "sync_job_id": "job-1"})
        self.assertEqual(jobs, ["job-1"])
        self.authority.mark_competitions_authoritative.assert_called_once_with()

    def test_retry_requires_matching_provider_and_remote_write_intent(self):
        intent = {
            "operation": "resolve_training_sync_conflict",
            "target_system": "intervals",
            "authorization_scope": ["sync_job:job-1", "intervals_sync"],
            "request": {"remote_write": False},
        }
        self.conflicts.job_state.return_value = {"provider": "intervals"}
        self.conflicts.is_push_job.return_value = True
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "resolve_training_sync_conflict", {"job_id": "job-1"},
                intent=intent, sync_job_ids=[],
            )
        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "request_target"))
        self.conflicts.retry_job.assert_not_called()

    def test_current_turn_job_can_be_read_without_extra_scope(self):
        self.queue.state.return_value = {"id": "job-1"}
        self.assertEqual(
            self.service.execute(
                "get_sync_job", {"job_id": "job-1"},
                intent={"authorization_scope": []}, sync_job_ids=["job-1"],
            ),
            {"ok": True, "job": {"id": "job-1"}},
        )
        with self.assertRaises(AppError):
            self.service.execute(
                "get_sync_job", {"job_id": "job-2"},
                intent={"authorization_scope": []}, sync_job_ids=["job-1"],
            )
        self.queue.state.assert_called_once_with("job-1")
