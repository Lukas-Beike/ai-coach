"""Ordered HTTP dispatch for authenticated and public POST routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.errors import AppError, NOT_FOUND_ERROR
from backend.http_api.auth_post import AuthPostRoutes
from backend.http_api.chat_cancel_post import ChatCancelPostRoutes
from backend.http_api.chat_post import ChatPostRoutes
from backend.http_api.chat_stream import CoachChatStreamTransport
from backend.http_api.coach_actions_post import CoachActionsPostRoutes
from backend.http_api.diagnostics_post import DiagnosticsCapturePostRoutes
from backend.http_api.feedback_post import FeedbackPostRoutes
from backend.http_api.history_undo_post import HistoryUndoPostRoutes
from backend.http_api.nutrition import NutritionPostRoutes
from backend.http_api.planning_commands_post import PlanningCommandsPostRoutes
from backend.http_api.privacy_delete_post import PrivacyDeletePostRoutes
from backend.http_api.privacy_restore_post import PrivacyRestorePostRoutes
from backend.http_api.sync_commands_post import SyncCommandPostRoute
from backend.http_api.transcribe_post import TranscribePostRoutes


@dataclass(frozen=True, slots=True)
class HttpAuthenticatedPostRoutes:
    """Concrete authenticated routes in their preserved handler order."""

    coach_actions: CoachActionsPostRoutes
    chat: ChatPostRoutes
    transcribe: TranscribePostRoutes
    planning_commands: PlanningCommandsPostRoutes
    feedback: FeedbackPostRoutes
    chat_stream: CoachChatStreamTransport
    sync_commands: SyncCommandPostRoute
    history_undo: HistoryUndoPostRoutes
    diagnostics_capture: DiagnosticsCapturePostRoutes
    privacy_delete: PrivacyDeletePostRoutes
    nutrition: NutritionPostRoutes


class HttpPostDispatcher:
    """Keep POST route ordering outside the socket-owning request handler."""

    def __init__(
        self,
        auth_routes: AuthPostRoutes,
        restore_route: PrivacyRestorePostRoutes,
        cancel_route: ChatCancelPostRoutes,
        authenticated_routes: HttpAuthenticatedPostRoutes,
    ) -> None:
        self._auth_routes = auth_routes
        self._restore_route = restore_route
        self._cancel_route = cancel_route
        self._coach_actions = authenticated_routes.coach_actions
        self._chat = authenticated_routes.chat
        self._transcribe = authenticated_routes.transcribe
        self._planning_commands = authenticated_routes.planning_commands
        self._feedback = authenticated_routes.feedback
        self._chat_stream = authenticated_routes.chat_stream
        self._sync_commands = authenticated_routes.sync_commands
        self._history_undo = authenticated_routes.history_undo
        self._diagnostics_capture = authenticated_routes.diagnostics_capture
        self._privacy_delete = authenticated_routes.privacy_delete
        self._nutrition = authenticated_routes.nutrition

    def handle_before_auth(self, handler: Any, path: str) -> bool:
        return self._auth_routes.handle(handler, path) or self._restore_route.handle(
            handler, path
        )

    def handle_before_maintenance(
        self, handler: Any, path: str, session: dict[str, Any]
    ) -> bool:
        return self._cancel_route.handle(handler, path, session)

    def handle_authenticated(
        self, handler: Any, path: str, session: dict[str, Any]
    ) -> None:
        if self._coach_actions.handle(handler, path, session):
            return
        if self._chat.handle(handler, path, session):
            return
        if self._transcribe.handle(handler, path):
            return
        if self._planning_commands.handle(handler, path, session):
            return
        if self._feedback.handle(handler, path):
            return
        if path == "/api/chat/stream":
            self._chat_stream.handle(handler, session)
            return
        if self._sync_commands.handle(handler, path):
            return
        if self._history_undo.handle(handler, path, session):
            return
        if self._diagnostics_capture.handle(handler, path):
            return
        if self._privacy_delete.handle(handler, path):
            return
        if self._nutrition.handle(handler, path):
            return
        raise AppError(404, NOT_FOUND_ERROR)
