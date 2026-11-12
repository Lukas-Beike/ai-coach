"""Authenticated Coach action confirmation and execution POST routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.proposal_execution import CoachProposalExecutionService
from backend.coach.proposal_read import CoachProposalConfirmationService
from backend.http_api.route_table import Access, Route, RouteRequest


class CoachActionsPostRoutes:
    """Dispatch confirmed Coach action requests through their owning services."""

    def __init__(
        self,
        coach_proposal_confirmation_service: Callable[
            [], CoachProposalConfirmationService
        ],
        coach_proposal_execution_service: Callable[[], CoachProposalExecutionService],
    ) -> None:
        self._coach_proposal_confirmation_service = coach_proposal_confirmation_service
        self._coach_proposal_execution_service = coach_proposal_execution_service

    def routes(self) -> list[Route]:
        return [
            Route(
                "POST", "/api/coach/actions/confirm", Access.SESSION_CSRF, self._confirm
            ),
            Route(
                "POST", "/api/coach/actions/cancel", Access.SESSION_CSRF, self._cancel
            ),
            Route(
                "POST", "/api/coach/actions/execute", Access.SESSION_CSRF, self._execute
            ),
        ]

    def _confirm(self, handler: Any, request: RouteRequest) -> None:
        """Confirm a Coach proposal.

        Request: JSON body `{"proposal_id": string}`, the `id` of an open proposal
        of this session (36 characters, `0-9`, `a-f`, `-`).

        Response: 200 `{"status": "ready", "action_token": string,
        "proposed_action": object}`. The token is shown once and is what
        `POST /api/coach/actions/execute` takes; `proposed_action` has `id`,
        `action_type`, `target_system`, `object_ids`, `diff`, `payload_hash`,
        `expires_at` and `status`. Confirming a `ready` proposal again issues a new
        token.

        Errors: 400 "Ungültige Aktionsvorschau." for a malformed id; 404
        `proposal_unavailable` "Aktionsvorschau nicht gefunden."; 409
        `proposal_used` "Die Aktionsvorschau wurde bereits verwendet." or "Die
        Aktionsvorschau wurde bereits bestätigt."; 409 `proposal_expired` "Die
        Aktionsvorschau ist abgelaufen.".
        """
        payload = handler.read_json()
        handler.send_json(
            200,
            self._coach_proposal_confirmation_service().confirm(
                payload.get("proposal_id"), request.session["csrf_hash"]
            ),
        )

    def _cancel(self, handler: Any, request: RouteRequest) -> None:
        """Cancel a Coach proposal.

        Request: JSON body `{"proposal_id": string}`, as for confirming.

        Response: 200 `{"status": "cancelled", "proposal_id": string}`; its token,
        if any, stops working.

        Errors: 400 "Ungültige Aktionsvorschau." for a malformed id; 409 "Die
        Aktionsvorschau ist nicht mehr offen." when the proposal is not of this
        session or is no longer `preview` or `ready`.
        """
        payload = handler.read_json()
        handler.send_json(
            200,
            self._coach_proposal_confirmation_service().cancel(
                payload.get("proposal_id"), request.session["csrf_hash"]
            ),
        )

    def _execute(self, handler: Any, request: RouteRequest) -> None:
        """Execute a confirmed Coach proposal.

        Request: JSON body `{"action_token": string, "payload_hash": string}`.
        `action_token` is required, the token from the confirmation (at least 32
        characters, single use). `payload_hash` is optional and, when sent, must
        equal the proposal's `payload_hash`.

        Response: 200 with the action's result: for `undo_change` the undo result
        (`status` `undone`, ...); for a local Coach write the tool result with `ok`
        `true` and `status` `applied`; for a remote Coach write the tool result,
        with `sync_job_ids` when sync jobs were queued.

        Errors: 400 "Ungültiges Coach-Aktionstoken." for a token shorter than 32
        characters; 409 `proposal_invalid` "Das Coach-Aktionstoken ist ungültig,
        abgelaufen oder bereits verwendet."; 409 `proposal_expired` "Das
        Coach-Aktionstoken ist abgelaufen."; 409 `proposal_payload_changed` "Der
        bestätigte Aktions-Payload wurde verändert."; 409 `proposal_used` "Das
        Coach-Aktionstoken wurde bereits verwendet."; 400 `unknown_coach_action`
        "Unbekannte Coach-Aktion."; 409 when the proposal's origin no longer checks
        out, "Der freigegebene Coach-Auftrag ist ungültig.", "Der freigegebene
        Coach-Auftrag ist nicht mehr gültig.", "Der freigegebene Coach-Auftrag
        gehört nicht mehr zu dieser Sitzung." or "Der ursprüngliche Nutzerauftrag
        ist nicht mehr verfügbar."; 503 "Die Coach-Aktionsausführung ist nicht
        verfügbar.". Validation errors of the underlying write are passed through.
        """
        payload = handler.read_json()
        handler.send_json(
            200,
            self._coach_proposal_execution_service().execute(
                payload.get("action_token"),
                request.session["csrf_hash"],
                payload.get("payload_hash"),
            ),
        )
