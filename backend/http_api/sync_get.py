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
                """State and outcome of the full resync started in the background.

                Request: no body; registered for `/api/garmin/full-resync` and
                `/api/wahoo/full-resync`, the path names the provider.

                Response: 200 with `running`, `status` (progress text while
                running, else null), `last_resync_at`, `last_error` and `outcome`
                (null until a run of this process ends, then `operation_id`,
                `status` and, after a failure, `reason`).

                Errors: none beyond the common ones.
                """
                provider = self._full_resync_providers[request.path]
                handler.send_json(200, full_resync().progress(provider))

            routes += [
                Route("GET", path, Access.SESSION, progress)
                for path in self._full_resync_providers
            ]
        return routes

    def _activity(self, handler: Any, request: RouteRequest) -> None:
        """The `activity_detail.v1` document of one session (local or provider id).

        Request: path `id`, URL-decoded: the local session id (`act_...`) or the
        provider activity id of one of the session's records, as long as it
        names one session; no body.

        Response: 200 with `ok`, the document (`contract`, `session`, `metrics`,
        `streams`, `laps`, `zones`, `strength_sets`, `analysis`, `detail_data`
        and more, plus `weather` and `route` when stored, and `data_scope`),
        `planned_adherence` for a run or ride with a matched local planned
        unit (each step's time in target, the score and zone times), and `session_bundle` (the session's provider copies and merge
        candidates; null when the session is not live).

        Errors: 400 `invalid_activity_request` "Die Aktivität konnte nicht
        eindeutig zugeordnet werden." when the id is empty or longer than 200
        characters; 404 `activity_details_not_found` "Diese Aktivität ist lokal
        nicht vorhanden." when the id is unknown, ambiguous or has no records.
        """
        service = self._activity_read_service()
        payload = service.detail(
            unquote(request.params["id"]),
            garmin_status=NO_GARMIN_SYNC_STATUS,
            profile={},
            today=self._local_today(),
        )
        adherence = service.planned_adherence(payload)
        if adherence is not None:
            payload["planned_adherence"] = adherence
        # Performance validation belongs to the Coach's complete context.
        payload.pop("activity_validation", None)
        session_id = (payload.get("session") or {}).get("activity_id")
        if self._session_corrections is not None and session_id:
            payload["session_bundle"] = self._session_corrections().bundle(
                str(session_id)
            )
        handler.send_json(200, payload)

    def _job(self, handler: Any, request: RouteRequest) -> None:
        """Result of one sync job.

        Request: path `id`, the job id (lowercase hexadecimal and `-`); no body.

        Response: 200 with `id`, `provider`, `type`, `status`, `payload`,
        `requested_by`, `attempts`, `progress` (`completed`, `total`),
        `available_at`, `started_at`, `finished_at`, `error_class`,
        `error_detail`, `items` (per item `id`, `item_key`, `operation`,
        `remote_id`, `status`, `attempts`, `error_class`, `error_detail`,
        `created_at`, `updated_at`), `created_at` and `updated_at`.

        Errors: 404 `sync_job_not_found` "Synchronisationsjob nicht gefunden."
        when no such job exists (an id with other characters matches no route).
        """
        handler.send_json(
            200, self._sync_job_queue_service().state(request.params["id"])
        )

    def _status(self, handler: Any, _request: RouteRequest) -> None:
        """Synchronization status.

        Request: no body.

        Response: 200 with `status`, `phase`, `progress` (0 to 100),
        `operation_id`, `running`, `message`, `started_at`, `finished_at`,
        `last_error`, `state_versions`, `provider_freshness`, `maintenance`
        (`active`, `running_operations`) and `jobs` (the recent sync jobs).

        Errors: none beyond the common ones.
        """
        handler.send_json(200, self._sync_public_state_service().state())

    def _activities(self, handler: Any, request: RouteRequest) -> None:
        """Activity list page; items carry the local session `id` and `record_ids`.

        Request: query `cursor` (opaque `next_cursor` of the previous page,
        base64url JSON `{"v": 3, "after": [started_at, id], "day": "YYYY-MM-DD"}`;
        any other version or an unrecognized cursor returns the first page),
        `limit` (1 to 250, default 100; unparsable gives 100) and `days` (-1 for
        all, else clamped to 1 to 3650; default and unparsable value -1).

        Response: 200 with `snapshot_synced_at`, `activities` (newest session
        first; per item the local session `id`, `record_ids` mapping each provider
        to its activity id, and the attached feedback), `next_cursor` (null on the
        last page), `limit` and `days`.

        Errors: none beyond the common ones.
        """
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
