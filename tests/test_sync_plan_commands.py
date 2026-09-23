"""Focused contracts for Coach planned-workout push commands."""

import unittest
from unittest.mock import Mock

from backend.sync.plan_commands import PlanPushCommandService
from backend.sync.queue import SyncJobQueueService


class PlanPushCommandServiceTests(unittest.TestCase):
    def setUp(self):
        self.queue = Mock(spec=SyncJobQueueService)
        self.queue.enqueue.side_effect = lambda *args, **kwargs: {
            "id": f"job-{self.queue.enqueue.call_count}"
        }
        self.service = PlanPushCommandService(self.queue)

    @staticmethod
    def entries(count):
        return [
            {
                "library_workout_id": f"workout-{index}",
                "expected_payload_hash": f"hash-{index}",
            }
            for index in range(count)
        ]

    def test_empty_selection_completes_without_enqueuing(self):
        sync_job_ids = []
        result = self.service.enqueue([], sync_job_ids, reason="Coach-Anfrage")

        self.assertEqual(
            result,
            {
                "ok": True,
                "status": "completed",
                "sync_job_id": None,
                "sync_job_ids": [],
                "entries": 0,
            },
        )
        self.queue.enqueue.assert_not_called()

    def test_chunk_boundaries_preserve_entry_and_job_id_order(self):
        for count, chunk_sizes in ((1, [1]), (28, [28]), (29, [28, 1]), (56, [28, 28])):
            with self.subTest(count=count):
                self.queue.reset_mock()
                self.queue.enqueue.side_effect = lambda *args, **kwargs: {
                    "id": f"job-{self.queue.enqueue.call_count}"
                }
                entries = self.entries(count)

                sync_job_ids = []
                result = self.service.enqueue(
                    entries, sync_job_ids, reason="plan update"
                )

                self.assertEqual(result["status"], "queued")
                self.assertEqual(result["entries"], count)
                self.assertEqual(
                    result["sync_job_ids"],
                    [f"job-{index}" for index in range(1, len(chunk_sizes) + 1)],
                )
                self.assertEqual(sync_job_ids, result["sync_job_ids"])
                self.assertEqual(
                    result["sync_job_id"],
                    result["sync_job_ids"][0] if len(chunk_sizes) == 1 else None,
                )
                self.assertEqual(self.queue.enqueue.call_count, len(chunk_sizes))
                self.assertEqual(
                    [
                        len(call.args[2]["entries"])
                        for call in self.queue.enqueue.call_args_list
                    ],
                    chunk_sizes,
                )
                self.assertEqual(
                    [
                        entry
                        for call in self.queue.enqueue.call_args_list
                        for entry in call.args[2]["entries"]
                    ],
                    entries,
                )

    def test_payload_hash_operations_reason_repair_and_requester_contract(self):
        entries = self.entries(2)

        result = self.service.enqueue(
            entries, [], reason="r" * 205, repair=True
        )

        self.assertEqual(result["sync_job_ids"], ["job-1"])
        self.queue.enqueue.assert_called_once_with(
            "intervals",
            "plan_push",
            {"entries": entries, "reason": "r" * 200, "repair": True},
            requested_by="coach",
            item_operations=[
                {
                    "item_key": entry["library_workout_id"],
                    "operation": "plan_push",
                    "payload_hash": entry["expected_payload_hash"],
                }
                for entry in entries
            ],
        )

    def test_empty_reason_defaults_to_coach_and_repair_is_omitted(self):
        self.service.enqueue(self.entries(1), [], reason="")

        self.assertEqual(self.queue.enqueue.call_args.args[2]["reason"], "coach")
        self.assertNotIn("repair", self.queue.enqueue.call_args.args[2])

    def test_enqueue_error_propagates_without_a_success_result(self):
        sync_job_ids = []
        self.queue.enqueue.side_effect = [
            {"id": "job-first"},
            RuntimeError("queue unavailable"),
        ]

        with self.assertRaisesRegex(RuntimeError, "queue unavailable"):
            self.service.enqueue(
                self.entries(29), sync_job_ids, reason="plan update"
            )

        self.assertEqual(self.queue.enqueue.call_count, 2)
        self.assertEqual(sync_job_ids, ["job-first"])


if __name__ == "__main__":
    unittest.main()
