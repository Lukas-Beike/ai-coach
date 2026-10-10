from __future__ import annotations

import threading
import unittest
from unittest.mock import Mock

from backend.coach.response_transport import (
    CoachResponseTransport,
    raise_if_chat_cancelled,
)
from backend.errors import AppError


class CoachResponseTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.openai = Mock()
        self.openai_stream = Mock()
        self.transport = CoachResponseTransport(
            lambda: self.openai,
            lambda: self.openai_stream,
        )

    def test_transport_uses_openai_responses_adapter(self) -> None:
        openai_factory = Mock(return_value=self.openai)
        stream_factory = Mock(return_value=self.openai_stream)
        transport = CoachResponseTransport(openai_factory, stream_factory)
        self.openai.responses.return_value = {"output_text": "OpenAI"}

        self.assertEqual(transport.request({}), {"output_text": "OpenAI"})

        openai_factory.assert_called_once_with()
        stream_factory.assert_not_called()

    def test_background_forwards_resume_id_checkpoint_and_cancel_event(self) -> None:
        payload = {}
        cancel_event = threading.Event()
        checkpoint = Mock()
        expected = {"id": "resp_synthetic", "status": "completed"}
        self.openai.background.return_value = expected

        self.assertIs(
            self.transport.background_request(
                payload,
                response_id="resp_resume",
                on_response_id=checkpoint,
                cancel_event=cancel_event,
            ),
            expected,
        )
        self.openai.background.assert_called_once_with(
            payload,
            response_id="resp_resume",
            on_response_id=checkpoint,
            cancel_event=cancel_event,
        )

    def test_stream_forwards_delta_callback_cancel_and_response_id(self) -> None:
        payload = {}
        cancel_event = threading.Event()
        on_delta = Mock()
        on_response_id = Mock()
        expected = {"status": "completed"}
        self.openai_stream.stream.return_value = expected

        self.assertIs(
            self.transport.stream_request(
                payload, on_delta, cancel_event, on_response_id
            ),
            expected,
        )
        self.openai_stream.stream.assert_called_once_with(
            payload,
            on_delta,
            cancel_event=cancel_event,
            on_response_id=on_response_id,
        )

    def test_cancel_helper_is_noop_without_cancel_and_raises_when_set(self) -> None:
        raise_if_chat_cancelled(None)
        raise_if_chat_cancelled(threading.Event())
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(AppError) as raised:
            raise_if_chat_cancelled(cancelled)
        self.assertEqual(
            (raised.exception.status, raised.exception.reason), (499, "chat_cancelled")
        )


if __name__ == "__main__":
    unittest.main()
