"""Authenticated synchronization and activity GET routes."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from backend.activities.read_service import ActivityReadService
from backend.http_api.auth import SessionAuthService
from backend.sync.queue import SyncJobQueueService
from backend.sync.status import SyncPublicStateService

SYNC_JOB_RE = re.compile(r"^/api/sync/jobs/([0-9a-f-]+)$")
ACTIVITY_DETAIL_RE = re.compile(r"^/api/activities/([^/]+)$")


class SyncGetRoutes:
    """Dispatch authenticated sync and activity reads through state owners."""

    def __init__(
        self,
        session_auth_service: Callable[[], SessionAuthService],
        sync_job_queue_service: Callable[[], SyncJobQueueService],
        sync_public_state_service: Callable[[], SyncPublicStateService],
        activity_read_service: Callable[[], ActivityReadService],
        local_today: Callable[[], date],
        all_sync_days: int,
    ) -> None:
        self._session_auth_service = session_auth_service
        self._sync_job_queue_service = sync_job_queue_service
        self._sync_public_state_service = sync_public_state_service
        self._activity_read_service = activity_read_service
        self._local_today = local_today
        self._all_sync_days = all_sync_days

    def handle(self, handler: Any, path: str) -> bool:
        job_match = SYNC_JOB_RE.match(path)
        activity_match = ACTIVITY_DETAIL_RE.match(path)
        if (
            not job_match
            and not activity_match
            and path not in {"/api/sync/status", "/api/activities"}
        ):
            return False

        self._session_auth_service().require_auth(handler)
        if activity_match:
            payload = self._activity_read_service().detail(
                unquote(activity_match.group(1)),
                garmin_snapshot={},
                profile={},
                today=self._local_today(),
            )
            # Performance validation belongs to the Coach's complete context.
            payload.pop("activity_validation", None)
        elif job_match:
            payload = self._sync_job_queue_service().state(job_match.group(1))
        elif path == "/api/sync/status":
            payload = self._sync_public_state_service().state()
        else:
            query = parse_qs(urlparse(handler.path).query)
            payload = self._activity_read_service().page(
                query.get("cursor", [None])[0],
                query.get("limit", [None])[0],
                query.get("days", [self._all_sync_days])[0],
                today=self._local_today(),
            )

        handler.send_json(200, payload)
        return True
