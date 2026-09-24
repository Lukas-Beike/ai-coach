"""Direct contracts for the shared Coach conversation gate."""

from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from backend.coach.conversation_gate import (
    CHAT_LOCK_TIMEOUT_SECONDS,
    CHAT_QUEUE_LIMIT,
    CoachConversationGate,
)
from backend.errors import AppError


class CoachConversationGateTests(unittest.TestCase):
    def test_defaults_keep_queue_and_lock_timeout_bounded(self) -> None:
        gate = CoachConversationGate()

        self.assertEqual(CHAT_QUEUE_LIMIT, 3)
        self.assertEqual(CHAT_LOCK_TIMEOUT_SECONDS, 30)
        self.assertIs(gate.lock, gate.lock)

    def test_full_queue_returns_429_and_queue_full_reason(self) -> None:
        gate = CoachConversationGate()
        acquired = [gate._queue.acquire(blocking=False) for _ in range(CHAT_QUEUE_LIMIT)]
        self.assertTrue(all(acquired))
        try:
            with self.assertRaises(AppError) as raised:
                gate.wrap(lambda: "unreachable")()
            self.assertEqual(raised.exception.status, 429)
            self.assertEqual(raised.exception.reason, "chat_queue_full")
        finally:
            for was_acquired in acquired:
                if was_acquired:
                    gate._queue.release()

    def test_lock_timeout_returns_409_and_releases_queue_slot(self) -> None:
        gate = CoachConversationGate(lock_timeout_seconds=0.02)
        wrapped = gate.wrap(lambda: "completed")
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            with gate.lock:
                future = executor.submit(wrapped)
                with self.assertRaises(AppError) as raised:
                    future.result(timeout=1)
        finally:
            executor.shutdown(wait=True)
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.reason, "chat_request_timeout")
        self.assertEqual(wrapped(), "completed")

    def test_exception_from_chat_releases_lock_and_queue(self) -> None:
        gate = CoachConversationGate()

        def fail() -> None:
            raise RuntimeError("synthetic failure")

        with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
            gate.wrap(fail)()

        self.assertEqual(gate.wrap(lambda: "completed")(), "completed")

    def test_lock_property_supports_shared_reset_lock(self) -> None:
        gate = CoachConversationGate()
        reset_service_lock = gate.lock
        lock_acquired = threading.Event()

        def acquire_lock() -> None:
            with reset_service_lock:
                lock_acquired.set()

        executor = ThreadPoolExecutor(max_workers=1)
        try:
            with gate.lock:
                future = executor.submit(acquire_lock)
                self.assertFalse(lock_acquired.wait(0.01))
        finally:
            executor.shutdown(wait=True)
        future.result(timeout=1)
        self.assertTrue(lock_acquired.is_set())


if __name__ == "__main__":
    unittest.main()
