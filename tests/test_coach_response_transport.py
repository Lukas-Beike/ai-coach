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
        self.settings = Mock()
        self.settings.selected_ai_provider.return_value = "openai"
        self.openai = Mock()
        self.openai_stream = Mock()
        self.gemini = Mock()
        self.transport = CoachResponseTransport(
            self.settings,
            lambda: self.openai,
            lambda: self.openai_stream,
            lambda: self.gemini,
        )

    def test_provider_routes_explicit_selection_and_falls_back_to_settings(self) -> None:
        payload = {"_ai_provider": "GEMINI", "model": "gemini-test"}
        self.gemini.request.return_value = {"output_text": "Gemini"}

        self.assertEqual(self.transport.provider(payload), "gemini")
        self.assertEqual(self.transport.request(payload), {"output_text": "Gemini"})
        self.gemini.request.assert_called_once_with(payload)
        self.openai.responses.assert_not_called()

        self.settings.selected_ai_provider.return_value = "gemini"
        self.gemini.request.reset_mock()
        self.assertEqual(self.transport.provider({"_ai_provider": "unexpected"}), "gemini")
        self.transport.request({"_ai_provider": "unexpected"})
        self.settings.selected_ai_provider.assert_called()
        self.gemini.request.assert_called_once_with({"_ai_provider": "unexpected"})

    def test_request_routes_openai_and_gemini_by_captured_provider(self) -> None:
        payload = {"_ai_provider": "openai", "model": "gpt-test"}
        expected = {"output_text": "OpenAI"}
        self.openai.responses.return_value = expected

        self.assertIs(self.transport.request(payload), expected)

        self.openai.responses.assert_called_once_with(payload)
        self.gemini.request.assert_not_called()

    def test_transport_constructs_only_the_selected_provider_adapter(self) -> None:
        openai_factory = Mock(return_value=self.openai)
        stream_factory = Mock(return_value=self.openai_stream)
        gemini_factory = Mock(return_value=self.gemini)
        transport = CoachResponseTransport(
            self.settings, openai_factory, stream_factory, gemini_factory
        )
        payload = {"_ai_provider": "gemini"}

        transport.request(payload)

        openai_factory.assert_not_called()
        stream_factory.assert_not_called()
        gemini_factory.assert_called_once_with()

    def test_background_forwards_resume_id_checkpoint_and_cancel_event(self) -> None:
        payload = {"_ai_provider": "openai"}
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
        payload = {"_ai_provider": "openai"}
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

    def test_gemini_background_checks_cancel_before_and_after_provider_call(self) -> None:
        payload = {"_ai_provider": "gemini"}
        already_cancelled = threading.Event()
        already_cancelled.set()
        with self.assertRaises(AppError) as before:
            self.transport.background_request(payload, cancel_event=already_cancelled)
        self.assertEqual((before.exception.status, before.exception.reason), (499, "chat_cancelled"))
        self.gemini.request.assert_not_called()

        during_request = threading.Event()

        def finish_after_cancel(*_args, **_kwargs):
            during_request.set()
            return {"output_text": "ignored"}

        self.gemini.request.side_effect = finish_after_cancel
        with self.assertRaises(AppError) as after:
            self.transport.background_request(payload, cancel_event=during_request)
        self.assertEqual((after.exception.status, after.exception.reason), (499, "chat_cancelled"))
        self.gemini.request.assert_called_once_with(payload, cancel_event=during_request)

    def test_gemini_stream_checks_cancel_and_propagates_provider_errors(self) -> None:
        payload = {"_ai_provider": "gemini"}
        pre_cancelled = threading.Event()
        pre_cancelled.set()
        gemini_factory = Mock(return_value=self.gemini)
        transport = CoachResponseTransport(
            self.settings,
            lambda: self.openai,
            lambda: self.openai_stream,
            gemini_factory,
        )
        with self.assertRaises(AppError) as before:
            transport.stream_request(payload, Mock(), pre_cancelled)
        self.assertEqual(before.exception.reason, "chat_cancelled")
        gemini_factory.assert_not_called()

        cancel_event = threading.Event()

        def stream_then_cancel(*_args, **_kwargs):
            cancel_event.set()
            return {"output_text": "ignored"}

        self.gemini.stream.side_effect = stream_then_cancel
        with self.assertRaises(AppError) as after:
            self.transport.stream_request(payload, Mock(), cancel_event)
        self.assertEqual(after.exception.reason, "chat_cancelled")
        self.gemini.stream.assert_called_once_with(payload, unittest.mock.ANY, cancel_event)

        expected_error = RuntimeError("synthetic provider failure")
        self.gemini.request.side_effect = expected_error
        with self.assertRaisesRegex(RuntimeError, "synthetic provider failure"):
            self.transport.request(payload)

    def test_cancel_helper_is_noop_without_cancel_and_raises_when_set(self) -> None:
        raise_if_chat_cancelled(None)
        raise_if_chat_cancelled(threading.Event())
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(AppError) as raised:
            raise_if_chat_cancelled(cancelled)
        self.assertEqual((raised.exception.status, raised.exception.reason), (499, "chat_cancelled"))


if __name__ == "__main__":
    unittest.main()
