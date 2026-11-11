"""Authenticated synchronization and activity GET routes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from typing import Any
from urllib.parse import unquote

from backend.http_api.route_table import Access, Route, RouteRequest
from backend.performance.activity_read_service import ActivityAnalysisReadService
from backend.performance.freshness import NO_GARMIN_SYNC_STATUS
from backend.sync.queue import SyncJobQueueService
from backend.sync.status import SyncPublicStateService


class SyncGetRoutes:
    """Dispatch authenticated sync and activity reads through state owners."""

    def __init__(
        self,
        sync_job_queue_service: Callable[[], SyncJobQueueService],
        sync_public_state_service: Callable[[], SyncPublicStateService],
        activity_read_service: Callable[[], ActivityAnalysisReadService],
        local_today: Callable[[], date],
        all_sync_days: int,
        session_corrections: Callable[[], Any] | None = None,
        full_resync: Callable[[], Any] | None = None,
        full_resync_providers: Mapping[str, str] | None = None,
    ) -> None:
        self._sync_job_queue_service = sync_job_queue_service
        self._sync_public_state_service = sync_public_state_service
        self._activity_read_service = activity_read_service
        self._local_today = local_today
        self._all_sync_days = all_sync_days
        self._session_corrections = session_corrections
        self._full_resync = full_resync
        # Full-resync path to provider id; the browser polls a started resync here.
        self._full_resync_providers = dict(full_resync_providers or {})

    def routes(self) -> list[Route]:
        routes = [
            Route("GET", "/api/sync/jobs/{id:[0-9a-f-]+}", Access.SESSION, self._job),
            Route("GET", "/api/sync/status", Access.SESSION, self._status),
            Route("GET", "/api/activities", Access.SESSION, self._activities),
            Route("GET", "/api/activities/{id}", Access.SESSION, self._activity),
        ]
        if (full_resync := self._full_resync) is not None:

            def progress(handler: Any, request: RouteRequest) -> None:
                provider = self._full_resync_providers[request.path]
                handler.send_json(200, full_resync().progress(provider))

            routes += [
                Route("GET", path, Access.SESSION, progress)
                for path in self._full_resync_providers
            ]
        return routes

    def _activity(self, handler: Any, request: RouteRequest) -> None:
        payload = self._activity_read_service().detail(
            unquote(request.params["id"]),
            garmin_status=NO_GARMIN_SYNC_STATUS,
            profile={},
            today=self._local_today(),
        )
        # Performance validation belongs to the Coach's complete context.
        payload.pop("activity_validation", None)
        session_id = (payload.get("session") or {}).get("activity_id")
        if self._session_corrections is not None and session_id:
            payload["session_bundle"] = self._session_corrections().bundle(
                str(session_id)
            )
        handler.send_json(200, payload)

    def _job(self, handler: Any, request: RouteRequest) -> None:
        handler.send_json(
            200, self._sync_job_queue_service().state(request.params["id"])
        )

    def _status(self, handler: Any, _request: RouteRequest) -> None:
        handler.send_json(200, self._sync_public_state_service().state())

    def _activities(self, handler: Any, request: RouteRequest) -> None:
        query = request.query
        handler.send_json(
            200,
            self._activity_read_service().page(
                query.get("cursor", [None])[0],
                query.get("limit", [None])[0],
                query.get("days", [self._all_sync_days])[0],
                today=self._local_today(),
            ),
        )
