import unittest

from backend.errors import AppError, ClientDisconnected
from backend.http_api.state_events_transport import StateEventTransport


class FakeEventBuffer:
    def __init__(self, batches):
        self.batches = iter(batches)
        self.wait_timeouts = []

    def since(self, _since):
        return next(self.batches)

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        return True


class StateEventTransportTests(unittest.TestCase):
    def test_invalid_cursor_fails_before_opening_stream(self):
        transport = StateEventTransport(FakeEventBuffer([]))
        calls = []

        with self.assertRaises(AppError) as raised:
            transport.handle(
                "/api/state/events?since=invalid",
                send_headers=lambda: calls.append("headers"),
                send_event=lambda *args: calls.append(args),
                set_connection_timeout=lambda value: calls.append(("timeout", value)),
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (400, "invalid_event_cursor"))
        self.assertEqual(calls, [])

    def test_initial_events_are_sent_before_ready_and_disconnect_ends_loop(self):
        buffer = FakeEventBuffer([
            {
                "events": [
                    {"event_id": 4, "event": "provider", "data": {"status": "running"}},
                    {"event_id": 5, "event": "job", "data": {"status": "completed"}},
                ],
                "latest_event_id": 5,
                "gap": False,
            },
            {"events": [], "latest_event_id": 5, "gap": False},
        ])
        events = []

        def send_event(*event):
            events.append(event)
            if event[0] == "heartbeat":
                raise ClientDisconnected()

        timeouts = []
        headers = []
        StateEventTransport(buffer).handle(
            "/api/state/events?since=3",
            send_headers=lambda: headers.append(True),
            send_event=send_event,
            set_connection_timeout=timeouts.append,
        )

        self.assertEqual(timeouts, [None])
        self.assertEqual(headers, [True])
        self.assertEqual(
            events,
            [
                ("provider", {"status": "running"}, 4),
                ("job", {"status": "completed"}, 5),
                ("ready", {"latest_event_id": 5}, 5),
                ("heartbeat", {"latest_event_id": 5}),
            ],
        )
        self.assertEqual(buffer.wait_timeouts, [15])

    def test_gap_reset_and_heartbeat_preserve_cursor_sequence(self):
        buffer = FakeEventBuffer([
            {"events": [], "latest_event_id": 3, "gap": False},
            {"events": [], "latest_event_id": 9, "gap": True},
            {"events": [], "latest_event_id": 9, "gap": False},
        ])
        events = []

        def send_event(*event):
            events.append(event)
            if event[0] == "heartbeat":
                raise ClientDisconnected()

        StateEventTransport(buffer).handle(
            "/api/state/events?since=3",
            send_headers=lambda: None,
            send_event=send_event,
            set_connection_timeout=lambda _value: None,
        )

        self.assertEqual(
            events,
            [
                ("ready", {"latest_event_id": 3}, 3),
                ("reset", {"reason": "gap", "latest_event_id": 9}, 9),
                ("heartbeat", {"latest_event_id": 9}),
            ],
        )
        self.assertEqual(buffer.wait_timeouts, [15, 15])

    def test_disconnect_while_sending_headers_is_swallowed(self):
        timeout_calls = []

        StateEventTransport(FakeEventBuffer([])).handle(
            "/api/state/events",
            send_headers=lambda: (_ for _ in ()).throw(ClientDisconnected()),
            send_event=lambda *_args: self.fail("no event should be sent"),
            set_connection_timeout=timeout_calls.append,
        )

        self.assertEqual(timeout_calls, [None])


if __name__ == "__main__":
    unittest.main()
