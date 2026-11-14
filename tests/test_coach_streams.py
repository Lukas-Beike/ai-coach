"""Chat stream registry: one stream per session, isolated and ordered events."""

import unittest

from backend.coach.streams import ChatStreamRegistry
from backend.errors import AppError


class ChatStreamRegistryTests(unittest.TestCase):
    def test_a_second_stream_of_one_session_is_rejected(self):
        registry = ChatStreamRegistry()
        operation_id, _ = registry.register("session")
        try:
            with self.assertRaises(AppError) as duplicate:
                registry.register("session")
            self.assertEqual(duplicate.exception.reason, "chat_already_running")
        finally:
            registry.unregister("session", operation_id)

    def test_sessions_are_isolated_and_events_keep_their_order(self):
        registry = ChatStreamRegistry()
        first_operation, _ = registry.register("session-one")
        second_operation, _ = registry.register("session-two")
        try:
            self.assertNotEqual(first_operation, second_operation)
            self.assertIsNone(registry.events("session-two", first_operation))
            self.assertTrue(registry.publish(first_operation, "delta", {"text": "one"}))
            self.assertTrue(
                registry.publish(first_operation, "completed", {"status": "done"})
            )
            first_events = registry.events("session-one", first_operation)
            self.assertEqual(first_events.get_nowait(), ("delta", {"text": "one"}))
            self.assertEqual(
                first_events.get_nowait(), ("completed", {"status": "done"})
            )
            self.assertFalse(registry.publish("unknown-operation", "error", {}))
        finally:
            registry.unregister("session-one", first_operation)
            registry.unregister("session-two", second_operation)
        self.assertFalse(
            registry.publish(first_operation, "delta", {"text": "after detach"})
        )


if __name__ == "__main__":
    unittest.main()
