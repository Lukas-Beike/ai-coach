"""Finite SSE transport for a durable Coach chat submission."""

from __future__ import annotations

import queue
from collections.abc import Callable
from typing import Any

from backend.coach.job_submission import CoachJobSubmissionService
from backend.coach.receipt_reads import CoachCommandReceiptService
from backend.coach.streams import ChatStreamRegistry
from backend.errors import INTERNAL_SERVER_ERROR, AppError, ClientDisconnected


class CoachChatStreamTransport:
    """Own the attached SSE lifecycle without owning the durable Coach job."""

    def __init__(
        self,
        registry: ChatStreamRegistry,
        submission_service: Callable[[], CoachJobSubmissionService],
        receipt_service: Callable[[], CoachCommandReceiptService],
        redact_text: Callable[[str], str],
        logger: Any,
        *,
        max_request_bytes: int,
        response_timeout_seconds: int,
    ) -> None:
        self._registry = registry
        self._submission_service = submission_service
        self._receipt_service = receipt_service
        self._redact_text = redact_text
        self._logger = logger
        self._max_request_bytes = max_request_bytes
        self._response_timeout_seconds = response_timeout_seconds

    def handle(self, handler: Any, session: dict[str, Any]) -> None:
        payload = handler.read_json(self._max_request_bytes)
        message = str(payload.get("message", ""))
        client_turn_id = str(payload.get("client_turn_id") or "").strip()
        request_kind = payload.get("request_kind")
        if not client_turn_id:
            raise AppError(
                400,
                "client_turn_id ist für Coach-Nachrichten erforderlich.",
                reason="invalid_client_turn",
            )
        session_hash = session["csrf_hash"]
        operation_id, cancel_event = self._registry.register(session_hash)
        client_connected = True

        def disconnect() -> None:
            nonlocal client_connected
            client_connected = False

        def send_event(event: str, data: Any) -> None:
            if not client_connected:
                return
            try:
                handler.send_sse_event(event, data)
            except ClientDisconnected:
                # A detached browser must not cancel the durable Coach job.
                disconnect()

        try:
            self._stream_job(
                handler, payload, message, client_turn_id, request_kind,
                session_hash, operation_id, cancel_event, send_event, disconnect,
            )
        except AppError as exc:
            send_event("error", self._app_error(exc))
        except Exception:
            self._logger.exception(
                "Unhandled coach stream error",
                extra={
                    "event": "chat_stream_error",
                    "context": {"request_id": handler.request_id},
                },
            )
            send_event("error", {"reason": "internal_error", "message": INTERNAL_SERVER_ERROR})
        finally:
            self._registry.unregister(session_hash, operation_id)
            handler.close_connection = True

    def _stream_job(
        self,
        handler: Any,
        payload: dict[str, Any],
        message: str,
        client_turn_id: str,
        request_kind: Any,
        session_hash: str,
        operation_id: str,
        cancel_event: Any,
        send_event: Callable[[str, Any], None],
        disconnect: Callable[[], None],
    ) -> None:
        handler.connection.settimeout(self._response_timeout_seconds + 30)
        try:
            handler.send_sse_headers(persistent=False)
            send_event("started", {"operation_id": operation_id})
        except ClientDisconnected:
            # The job remains durable even if headers cannot reach the client.
            disconnect()
        job = self._submission_service().enqueue(
            message,
            client_turn_id,
            session_hash,
            operation_id=operation_id,
            cancel_event=cancel_event,
            request_kind=request_kind,
            attachments=payload.get("attachments"),
        )
        persisted_operation_id = str(job.get("operation_id") or "")
        if persisted_operation_id and persisted_operation_id != operation_id:
            send_event("background", job)
            return
        events = self._registry.events(session_hash, operation_id)
        if events is None:
            send_event("background", job)
            return
        self._relay_events(events, client_turn_id, session_hash, operation_id, send_event)

    def _relay_events(
        self,
        events: queue.Queue,
        client_turn_id: str,
        session_hash: str,
        operation_id: str,
        send_event: Callable[[str, Any], None],
    ) -> None:
        while True:
            try:
                event, data = events.get(timeout=15)
            except queue.Empty:
                active = self._submission_service().active(session_hash, operation_id)
                if active:
                    send_event("heartbeat", {"operation_id": operation_id})
                    continue
                try:
                    receipt = self._receipt_service().read(client_turn_id, session_hash)
                    send_event("completed", receipt)
                except AppError as exc:
                    send_event("error", self._app_error(exc))
                break
            send_event(event, data)
            if event in {"completed", "error", "background"}:
                break

    def _app_error(self, exc: AppError) -> dict[str, str]:
        return {
            "reason": exc.reason or "request_failed",
            "message": self._redact_text(exc.message)[:1000],
        }
