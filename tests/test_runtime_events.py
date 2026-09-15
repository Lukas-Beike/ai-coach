import threading
import unittest

from backend.errors import AppError
from backend.runtime.events import StateEventBuffer


class StateEventBufferTests(unittest.TestCase):
    def test_publish_validates_events_and_copies_payload(self):
        buffer = StateEventBuffer()
        payload = {"status": "ready", "nested": {"value": 1}}

        published = buffer.publish("provider", payload)
        payload["status"] = "changed"

        self.assertEqual(published["event_id"], 1)
        self.assertEqual(published["data"]["status"], "ready")
        self.assertEqual(buffer.since()["events"][0]["data"]["status"], "ready")
        published["event"] = "mutated"
        self.assertEqual(buffer.since()["events"][0]["event"], "provider")
        self.assertEqual(buffer.publish("job", "not-a-dict")["data"], {})
        with self.assertRaises(ValueError):
            buffer.publish("unknown")
        with self.assertRaises(ValueError):
            buffer.publish([])  # type: ignore[arg-type]

    def test_retention_reports_gap_and_cursor_is_clamped(self):
        buffer = StateEventBuffer(maxlen=3)
        for index in range(5):
            buffer.publish("job", {"index": index})

        gap = buffer.since(0)
        self.assertEqual(gap["latest_event_id"], 5)
        self.assertTrue(gap["gap"])
        self.assertEqual(gap["events"], [])
        self.assertEqual([item["event_id"] for item in buffer.since(2)["events"]], [3, 4, 5])
        self.assertEqual([item["event_id"] for item in buffer.since(-10)["events"]], [])
        self.assertEqual([item["event_id"] for item in buffer.since("4")["events"]], [5])

    def test_invalid_cursor_is_app_error(self):
        buffer = StateEventBuffer()
        for cursor in ("not-a-number", None):
            with self.subTest(cursor=cursor):
                with self.assertRaises(AppError) as raised:
                    buffer.since(cursor)  # type: ignore[arg-type]
                self.assertEqual(raised.exception.status, 400)
                self.assertEqual(raised.exception.reason, "invalid_event_cursor")
        with self.assertRaises(OverflowError):
            buffer.since(float("inf"))

    def test_parallel_publish_assigns_unique_monotonic_ids(self):
        buffer = StateEventBuffer(maxlen=500)
        workers = 8
        events_per_worker = 20
        barrier = threading.Barrier(workers)

        def publish_events(worker: int) -> None:
            barrier.wait(timeout=2)
            for index in range(events_per_worker):
                buffer.publish("sync", {"worker": worker, "index": index})

        threads = [threading.Thread(target=publish_events, args=(worker,)) for worker in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        events = buffer.since()["events"]
        self.assertEqual(len(events), workers * events_per_worker)
        self.assertEqual([item["event_id"] for item in events], list(range(1, len(events) + 1)))

    def test_wait_is_notified_by_publish_and_times_out(self):
        buffer = StateEventBuffer()
        started = threading.Event()
        result: list[bool] = []

        def wait_for_event() -> None:
            with buffer._condition:
                started.set()
                result.append(buffer.wait(timeout=2))

        waiter = threading.Thread(target=wait_for_event)
        waiter.start()
        self.assertTrue(started.wait(timeout=1))
        buffer.publish("coach", {"status": "changed"})
        waiter.join(timeout=1)
        self.assertFalse(waiter.is_alive())
        self.assertEqual(result, [True])
        self.assertFalse(buffer.wait(timeout=0.05))

    def test_clear_resets_events_and_ids_atomically(self):
        buffer = StateEventBuffer()
        buffer.publish("planning", {"status": "changed"})

        buffer.clear()

        self.assertEqual(buffer.since(), {"events": [], "latest_event_id": 0, "gap": False})
        self.assertEqual(buffer.publish("planning")["event_id"], 1)


if __name__ == "__main__":
    unittest.main()
