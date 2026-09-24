"""Execute one claimed durable Coach job and publish its stream outcome."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any, Protocol

from backend.coach.chat_turn import CoachChatTurnService
from backend.coach.job_store import CoachJobStore
from backend.coach.morning import ManualMorningCheckinService
from backend.coach.morning_completion import MorningCoachJobCompletionService
from backend.coach.streams import ChatStreamRegistry
from backend.coach.turn_failures import CoachTurnFailureService
from backend.errors import INTERNAL_SERVER_ERROR, AppError
from backend.observability import Redactor
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.observation import operation_error_code


class CoachSessionBinding(Protocol):
    """Narrow session-key read needed by a claimed Coach job."""

    def restore_coach_session_csrf_hash(self, session_key: str) -> str: ...


class CoachBackgroundJobRunner:
    """Own claim-generation execution, retry, cancellation and SSE publication."""

    def __init__(
        self,
        jobs: CoachJobStore,
        chat_turn: Callable[[], CoachChatTurnService],
        sessions: Callable[[], CoachSessionBinding],
        streams: ChatStreamRegistry,
        morning: Callable[[], ManualMorningCheckinService],
        morning_completion: Callable[[], MorningCoachJobCompletionService],
        failures: Callable[[], CoachTurnFailureService],
        maintenance: MaintenanceGate,
        redactor: Redactor,
        logger: logging.Logger,
    ) -> None:
        self._jobs = jobs
        self._chat_turn = chat_turn
        self._sessions = sessions
        self._streams = streams
        self._morning = morning
        self._morning_completion = morning_completion
        self._failures = failures
        self._maintenance = maintenance
        self._redactor = redactor
        self._logger = logger

    def run(self, job: dict[str, Any]) -> None:
        """Discard generations invalidated by restore without failure writes."""
        try:
            with self._maintenance.operation(job["_maintenance_generation"]):
                self._run_claimed(job)
        except AppError as exc:
            if exc.reason not in {"operation_invalidated", "maintenance"}:
                raise

    def _run_claimed(self, job: dict[str, Any]) -> None:
        receipt = job.get("receipt") if isinstance(job.get("receipt"), dict) else {}
        operation_id = str(receipt.get("operation_id") or "")
        client_turn_id = str(job.get("client_turn_id") or "")
        session_csrf_hash = self._sessions().restore_coach_session_csrf_hash(receipt.get("session_key"))
        cancel_event = self._streams.get_or_create_background_event(operation_id)
        if self._jobs.cancel_requested(client_turn_id):
            self._streams.cancel_background_event(operation_id)
        stream_attached = self._streams.events(session_csrf_hash, operation_id) is not None
        try:
            result = self._execute(
                job, receipt, operation_id, client_turn_id, session_csrf_hash, cancel_event, stream_attached,
            )
            self._publish_receipt(operation_id, result)
        except AppError as exc:
            self._handle_app_error(client_turn_id, operation_id, exc)
        except Exception as exc:  # noqa: BLE001 - terminal worker boundary must persist unexpected failures
            self._handle_exception(client_turn_id, operation_id, exc)
        finally:
            self._streams.remove_background_event(operation_id)

    def _delta_callback(
        self, operation_id: str, receipt: dict[str, Any], stream_attached: bool,
    ) -> Any:
        if not stream_attached or receipt.get("openai_response_id"):
            return None
        def publish_delta(text: str) -> None:
            self._streams.publish(operation_id, "delta", {"text": text})

        return publish_delta

    def _publish_receipt(self, operation_id: str, value: dict[str, Any]) -> None:
        self._streams.publish(
            operation_id, "completed", {key: item for key, item in value.items() if key != "session_key"},
        )

    def _execute(
        self, job: dict[str, Any], receipt: dict[str, Any], operation_id: str, client_turn_id: str,
        session_csrf_hash: str, cancel_event: threading.Event, stream_attached: bool,
    ) -> dict[str, Any]:
        if not session_csrf_hash:
            raise AppError(401, "Die Sitzung des Coach-Auftrags ist abgelaufen.", reason="session_expired")
        message = self._jobs.message(job)
        worker_phase = {"status": "running"}
        if not receipt.get("openai_response_id"):
            worker_phase["phase"] = "preparing"
        self._jobs.merge_receipt(client_turn_id, worker_phase)
        if receipt.get("request_kind") == "morning_checkin":
            self._morning().prepare()
        result = self._chat_turn().run(
            message,
            on_text_delta=self._delta_callback(operation_id, receipt, stream_attached),
            cancel_event=cancel_event,
            session_csrf_hash=session_csrf_hash,
            client_turn_id=client_turn_id,
            background_job=True,
        )
        if (
            receipt.get("request_kind") == "morning_checkin"
            and result.get("status") == "completed"
            and result.get("message")
            and not result.get("awaiting_clarification")
        ):
            result = self._morning_completion().complete(client_turn_id) or result
        return result

    def _handle_app_error(self, client_turn_id: str, operation_id: str, exc: AppError) -> None:
        if exc.reason in {"chat_queue_full", "chat_request_timeout"}:
            self._jobs.requeue(client_turn_id, exc.reason)
            self._logger.warning(
                "Persistent Coach background job requeued after contention",
                extra={"event": "coach_background_job_requeued", "context": {"operation_id": operation_id, "reason": exc.reason}},
            )
            self._streams.publish(operation_id, "background", {
                "status": "queued", "mode": "background", "operation_id": operation_id,
            })
            return
        failed = self._failures().persist(client_turn_id, {}, exc)
        if failed:
            self._publish_receipt(operation_id, failed)
            return
        self._streams.publish(operation_id, "error", {
            "reason": exc.reason or "request_failed", "message": self._redactor.redact_text(exc.message)[:1000],
        })

    def _handle_exception(self, client_turn_id: str, operation_id: str, exc: Exception) -> None:
        failed = self._failures().persist(client_turn_id, {}, exc)
        if failed:
            self._publish_receipt(operation_id, failed)
        else:
            self._streams.publish(operation_id, "error", {
                "reason": "internal_error", "message": INTERNAL_SERVER_ERROR,
            })
        self._logger.exception(
            "Persistent Coach background job failed",
            extra={"event": "coach_background_job_failed", "context": {
                "operation_id": operation_id, "error_code": operation_error_code(exc),
            }},
        )
