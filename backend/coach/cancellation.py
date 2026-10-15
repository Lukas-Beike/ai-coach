"""Session-scoped cancellation of attached and durable Coach turns."""

from __future__ import annotations

from typing import Any

from backend.coach.job_store import CoachJobStore
from backend.coach.job_submission import CoachJobSubmissionService
from backend.coach.streams import ChatStreamRegistry


class CoachCancellationService:
    """Coordinate cancellation without owning stream or durable job state."""

    def __init__(
        self,
        submissions: CoachJobSubmissionService,
        jobs: CoachJobStore,
        streams: ChatStreamRegistry,
    ) -> None:
        self._submissions = submissions
        self._jobs = jobs
        self._streams = streams

    def cancel(
        self, session_csrf_hash: str, operation_id: Any = None
    ) -> dict[str, Any]:
        result, response = self._streams.cancel_attached(
            session_csrf_hash, operation_id
        )
        if result is not None:
            # An attached stream may be the live face of a queued durable job with
            # the same operation; persist its cancel so a restart cannot resume it.
            job = self._submissions.active(
                session_csrf_hash, str(result["operation_id"] or "") or None
            )
            if job:
                self._persist_cancel(job)
            self._close_response(response)
            return result

        job = self._submissions.active(
            session_csrf_hash, str(operation_id or "") or None
        )
        if not job:
            return {"status": "not_running"}
        receipt = job["receipt"]
        self._persist_cancel(job)
        _, response = self._streams.cancel_existing_background_event(
            str(receipt.get("operation_id") or "")
        )
        self._close_response(response)
        return {"status": "cancelling", "operation_id": receipt.get("operation_id")}

    def _persist_cancel(self, job: dict[str, Any]) -> None:
        self._jobs.merge_receipt(
            job["client_turn_id"],
            {"cancel_requested": True, "phase": "cancelling"},
        )

    @staticmethod
    def _close_response(response: Any) -> None:
        if response is None:
            return
        try:
            response.close()
        except OSError, ValueError:
            pass
