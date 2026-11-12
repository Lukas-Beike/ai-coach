"""Authenticated activity feedback and session correction POST routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.errors import AppError
from backend.http_api.route_table import Access, Route, RouteRequest
from backend.http_api.session_load_response import with_session_load


class FeedbackPostRoutes:
    """Dispatch activity feedback and session corrections to their domain services."""

    def __init__(
        self,
        activity_feedback_service: Callable[[], Any] | None = None,
        session_rpe_load: Callable[[str], Any] | None = None,
        session_corrections: Callable[[], Any] | None = None,
    ) -> None:
        self._activity_feedback_service = activity_feedback_service
        self._session_rpe_load = session_rpe_load
        self._session_corrections = session_corrections

    def routes(self) -> list[Route]:
        routes = []
        if self._session_corrections is not None:
            routes.append(
                Route(
                    "POST",
                    "/api/activities/{id}/session",
                    Access.SESSION_CSRF,
                    self._session,
                )
            )
        if self._activity_feedback_service is not None:
            routes.append(
                Route(
                    "POST",
                    "/api/activities/{id}/feedback",
                    Access.SESSION_CSRF,
                    self._feedback,
                )
            )
        return routes

    def _session(self, handler: Any, request: RouteRequest) -> None:
        """Confirm, split, merge or delete one session bundle, with a change receipt.

        Request: path `{id}`, a local session id (`act_...`; a merged alias leads to
        its survivor); JSON body `{"action": string}` with `action` one of
        `confirm`, `split` (`member_id`: session id of the provider copy to detach),
        `merge` (`other_id`: session id of the other session) or `delete`
        (`confirmed: true` required). Records and provider data are not changed;
        nothing is deleted at a provider.

        Response: 200 `{"status", "activity_id", "change", "session_bundle"}`.
        `status` is `confirmed`, `split`, `merged` or `deleted`; `change` is the
        undo reference; `session_bundle` is the current bundle of `activity_id`
        (`activity_id`, `link_kind`, `athlete_confirmed`, `members`,
        `merge_candidates`), `null` when that session is no longer live.

        Errors: 400 "Unbekannte Korrektur." for a missing or unknown `action`; 409
        "Das Löschen muss bestätigt werden." for `delete` without `confirmed:
        true`; 404 "Diese Aktivität ist nicht (mehr) vorhanden." when `id` (or
        `other_id`) names no live session. Split: 409 "Diese Aufzeichnung gehört
        nicht zu der Aktivität." for a `member_id` outside the bundle, 409 "Die
        Aktivität besteht nur aus einer Aufzeichnung." for a single copy. Merge:
        409 "Beide Angaben bezeichnen dieselbe Aktivität." for one session, 409
        "Nur Aktivitäten desselben Tages können zusammengeführt werden.", 409
        "Beide Aktivitäten enthalten eine Aufzeichnung derselben Quelle und können
        nicht zusammengeführt werden." Any action: 409 "Diese Aktivität ist zu
        groß für eine rücknehmbare Korrektur." beyond 16 touched sessions.
        """
        handler.send_json(
            200, self._correct_session(request.params["id"], handler.read_json())
        )

    def _feedback(self, handler: Any, request: RouteRequest) -> None:
        """Save, edit or clear the athlete's feedback of one activity.

        Request: path `{id}`, a local session id or the provider activity id of one
        of the session's records; the feedback is stored under the live session.
        JSON body, every field optional, an omitted field keeps its stored value:
        `notes` (string, trimmed, cut to 4000 characters), `session_rpe` (number 0
        to 10 or `null`), `deviation_reason` (string, cut to 500 characters),
        `purpose` (`training`, `race`, `commute`, `warmup`, `cooldown`, or `null`
        or `""` to clear), `activity_name` (cut to 200) and `activity_date` (cut
        to 40). Clearing every content field removes the feedback.

        Response: 200 `{"status": "ok", "activity_feedback", "change",
        "session_rpe_load"}`. `activity_feedback` is the effective feedback
        (`activity_id`, `activity_name`, `activity_date`, `notes`, `session_rpe`,
        `deviation_reason`, `created_at`, `updated_at`, `session_rpe_rated_at`,
        `purpose`), `null` after clearing; `change` is the undo reference;
        `session_rpe_load` is left out when its read fails.

        Errors: 400 "Der Aktivitäts-RPE muss zwischen 0 und 10 liegen."; 400 "Die
        Art der Einheit ist unbekannt." for another `purpose`; 400 "Die Aktivität
        konnte nicht eindeutig zugeordnet werden." for an id longer than 200
        characters; 409 "Die Aktivität lässt sich keiner Einheit eindeutig
        zuordnen; die Art der Einheit kann nicht markiert werden." for a `purpose`
        on an id that leads to no single session; 409 "Zu viele Rückmeldungen für
        diese Einheit, um sie mit Undo zu ändern." A body with non-empty
        `notes`, a non-null `session_rpe`, a non-empty `deviation_reason` or a
        `purpose` is a save only for a live session: 404 "Die Aktivität ist im
        aktuellen lokalen Trainingssnapshot nicht vorhanden." otherwise.
        """
        if self._activity_feedback_service is None:
            raise AppError(404, "Nicht gefunden.")
        activity_id = request.params["id"]
        payload = handler.read_json()
        feedback = self._activity_feedback_service()
        has_feedback = isinstance(payload, dict) and bool(
            str(payload.get("notes") or "").strip()
            or payload.get("session_rpe") is not None
            or str(payload.get("deviation_reason") or "").strip()
            or payload.get("purpose") not in (None, "")
        )
        result = (
            feedback.save_coach(activity_id, payload)
            if has_feedback
            else feedback.save(activity_id, payload)
        )
        result = with_session_load(result, self._session_rpe_load, activity_id)
        handler.send_json(200, result)

    def _correct_session(self, activity_id: str, payload: Any) -> dict[str, Any]:
        """Confirm, split or merge one session; the response carries its new bundle."""
        if not isinstance(payload, dict):
            raise AppError(400, "Die Korrektur muss ein Objekt sein.")
        if self._session_corrections is None:
            raise AppError(404, "Nicht gefunden.")
        service = self._session_corrections()
        action = payload.get("action")
        if action == "confirm":
            result = service.confirm(activity_id)
        elif action == "split":
            result = service.split(activity_id, str(payload.get("member_id") or ""))
        elif action == "delete":
            if payload.get("confirmed") is not True:
                raise AppError(409, "Das Löschen muss bestätigt werden.")
            result = service.delete(activity_id)
        elif action == "merge":
            result = service.merge(activity_id, str(payload.get("other_id") or ""))
        else:
            raise AppError(400, "Unbekannte Korrektur.")
        return {**result, "session_bundle": service.bundle(result["activity_id"])}
