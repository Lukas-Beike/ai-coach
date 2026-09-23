import threading
import unittest
from unittest.mock import Mock

from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.observation import (
    OPERATION_CONTEXT,
    SyncOperationObserver,
    observed_sync,
    operation_context,
    operation_error_code,
    operation_result_count,
    operation_trigger,
    refresh_status,
)


class RecordingLogger:
    def __init__(self):
        self.records = []

    def log(self, level, message, *, extra):
        self.records.append((level, message, extra))


class SyncOperationObserverTests(unittest.TestCase):
    def make_observer(self):
        tracker = Mock()
        tracker.start.return_value = "refresh-1"
        logger = RecordingLogger()
        ticks = iter(range(20))
        observer = SyncOperationObserver(
            tracker,
            MaintenanceGate(),
            logger,
            monotonic=lambda: next(ticks),
            operation_id_factory=lambda: "generated-operation",
        )
        return observer, tracker, logger

    def test_helpers_preserve_safe_legacy_mappings(self):
        self.assertEqual(operation_trigger("Manuell"), "manual")
        self.assertEqual(operation_trigger("athlete secret"), "background")
        self.assertEqual(
            operation_error_code(AppError(409, "x", reason="Unsafe Value!")),
            "unsafe_value",
        )
        self.assertEqual(operation_error_code(TimeoutError()), "timeout")
        self.assertEqual(operation_result_count({"updated": 3}), 3)
        self.assertIsNone(operation_result_count({"updated": -1}))
        self.assertEqual(refresh_status({"status": "not_configured"}), "skipped")
        self.assertEqual(refresh_status({"status": "partial"}), "partial")
        self.assertEqual(refresh_status({"status": "ok"}), "success")

    def test_success_records_one_correlated_lifecycle_and_restores_context(self):
        observer, tracker, logger = self.make_observer()

        with observer.observe("intervals", "activities", "manual") as scope:
            self.assertEqual(
                operation_context(),
                {"operation_id": "generated-operation", "trigger": "manual"},
            )
            scope.result = {"status": "partial", "activities": 4}

        tracker.start.assert_called_once_with(
            "intervals", "activities", "generated-operation", "manual"
        )
        tracker.finish.assert_called_once_with("refresh-1", "partial", "complete")
        self.assertIsNone(operation_context())
        self.assertEqual(
            [record[2]["event"] for record in logger.records],
            ["operation_started", "operation_count", "operation_completed"],
        )
        self.assertEqual(logger.records[1][2]["context"]["count"], 4)

    def test_nested_observation_reuses_parent_correlation(self):
        observer, tracker, _ = self.make_observer()
        token = OPERATION_CONTEXT.set(
            {"operation_id": "parent-operation", "trigger": "checkin"}
        )
        try:
            with observer.observe(
                "garmin", "data", "manual", "ignored-explicit-id"
            ) as scope:
                self.assertEqual(scope.operation_id, "ignored-explicit-id")
                self.assertEqual(scope.trigger, "checkin")
        finally:
            OPERATION_CONTEXT.reset(token)

        tracker.start.assert_called_once_with(
            "garmin", "data", "ignored-explicit-id", "checkin"
        )

    def test_failure_finishes_refresh_and_logs_only_safe_code(self):
        observer, tracker, logger = self.make_observer()

        with (
            self.assertRaisesRegex(RuntimeError, "secret payload"),
            observer.observe("garmin", "data", "manual"),
        ):
            raise RuntimeError("secret payload")

        tracker.finish.assert_called_once_with(
            "refresh-1",
            "error",
            "failed",
            error_code="provider_error",
        )
        event = logger.records[-1][2]
        self.assertEqual(event["event"], "operation_failed")
        self.assertEqual(event["context"]["error_code"], "internal_error")
        self.assertNotIn("secret", str(event).casefold())
        self.assertIsNone(operation_context())

    def test_chat_cancellation_is_skipped(self):
        observer, tracker, _ = self.make_observer()

        with self.assertRaises(AppError), observer.observe("intervals", "activities"):
            raise AppError(499, "cancel", reason="chat_cancelled")

        tracker.finish.assert_called_once_with("refresh-1", "skipped", "cancelled")

    def test_context_is_isolated_between_threads(self):
        observer, _, _ = self.make_observer()
        barrier = threading.Barrier(2)
        seen = []
        identifiers = iter(("operation-a", "operation-b"))
        observer._operation_id_factory = lambda: next(identifiers)

        def run():
            with observer.observe("test", "data", "manual") as scope:
                seen.append((scope.operation_id, operation_context()["operation_id"]))
                barrier.wait(timeout=5)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        self.assertEqual(len(seen), 2)
        self.assertEqual(
            {left for left, right in seen if left == right},
            {"operation-a", "operation-b"},
        )
        self.assertIsNone(operation_context())

    def test_tracker_start_failure_is_logged_and_context_is_reset(self):
        observer, tracker, logger = self.make_observer()
        tracker.start.side_effect = RuntimeError("database secret")

        with (
            self.assertRaisesRegex(RuntimeError, "database secret"),
            observer.observe("garmin", "data"),
        ):
            self.fail("body must not run")

        self.assertEqual(logger.records[-1][2]["event"], "operation_failed")
        self.assertIsNone(operation_context())

    def test_transitional_decorator_extracts_reason_and_records_result(self):
        observer, tracker, _ = self.make_observer()

        @observed_sync(lambda: observer, "garmin", "data")
        def synchronize(reason, *, operation_id=None):
            self.assertEqual(operation_context()["operation_id"], operation_id)
            return {"status": "ok", "records": 2, "reason": reason}

        result = synchronize("manual", operation_id="explicit-operation")

        self.assertEqual(result["records"], 2)
        tracker.start.assert_called_once_with(
            "garmin", "data", "explicit-operation", "manual"
        )
        tracker.finish.assert_called_once_with("refresh-1", "success", "complete")


if __name__ == "__main__":
    unittest.main()
