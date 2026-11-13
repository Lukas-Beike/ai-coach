"""HTTP transport for explicit synchronization commands."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.route_table import Access, Route, RouteRequest
from backend.http_api.sync_commands import SYNC_ROUTE_SURFACE, SyncCommandEndpoint


class SyncCommandPostRoute:
    """Read the request body and write the result for a sync command."""

    def __init__(self, endpoint: Callable[[], SyncCommandEndpoint]) -> None:
        self._endpoint = endpoint

    def routes(self) -> list[Route]:
        routes = []
        for path in sorted(SYNC_ROUTE_SURFACE.paths()):
            route = SYNC_ROUTE_SURFACE.route(path)
            if route is not None and route.full_resync_provider is not None:
                handle = self._full_resync
            elif route is not None and route.manual is not None:
                handle = self._manual_sync
            else:
                handle = self._execute
            routes.append(Route("POST", path, Access.SESSION_CSRF, handle))
        return routes

    def _full_resync(self, handler: Any, request: RouteRequest) -> None:
        """Start the confirmed full resync in the background (`202` with `operation_id`; `200` `already_running` while one runs).

        Request: JSON body `{"confirm": "FULL_RESYNC"}`, required. Registered for
        `/api/garmin/full-resync` and `/api/wahoo/full-resync`; the path names the
        provider.

        Response: 202 with `status` (`"started"`), `source` (the provider id) and
        `operation_id`; or 200 with `status` `"already_running"`, `source` and the
        `operation_id` of the run in progress. Progress is read with the GET
        route of the same path.

        Errors: 400 "Zum vollständigen Resync muss FULL_RESYNC bestätigt werden."
        when `confirm` is not `FULL_RESYNC`; 503 `not_configured` when the
        provider is not set up: "Garmin ist nicht konfiguriert. Unter Mehr →
        Anbindungen bei Garmin anmelden oder einen Schlüssel der Garmin Personal
        API hinterlegen." or "Wahoo ist nicht verbunden. Bitte Wahoo in den
        Einstellungen verbinden."
        """
        self._execute(handler, request)

    def _manual_sync(self, handler: Any, request: RouteRequest) -> None:
        """Queue a provider synchronization, or a targeted refresh of the external calendars or the weather.

        Request: registered for `/api/garmin/sync`, `/api/wahoo/sync`,
        `/api/weather/sync` and `/api/external-calendar/sync`. Only
        `/api/garmin/sync` reads a JSON object body (required, `{}` suffices):
        optional `days` (integer, `-1` for all history or 1 to 90; default the
        stored Garmin sync period), which is also stored as the new period. The
        other three take no body.

        Response: 202 with the queued job (as `GET /api/sync/jobs/{id}`: `id`,
        `provider`, `type`, `status`, `progress`, `items`, ...), a `refresh` job
        requested by `user`. Its payload holds `reason` (`manual` for Garmin and
        Wahoo, `manuell` for the calendar and the weather), for Garmin the
        applied `days`, and for the weather `force: true`.

        Errors: 400 "Der Synchronisationszeitraum muss eine ganze Zahl sein." when
        `days` is not an integer, or "Der Zeitraum für garmin muss -1 oder
        zwischen 1 und 90 Tagen liegen." when it is out of range; 409
        `not_configured` for Garmin ("Garmin ist nicht konfiguriert. Unter Mehr →
        Anbindungen bei Garmin anmelden oder einen Schlüssel der Garmin Personal
        API hinterlegen.") and Wahoo ("Wahoo ist nicht verbunden. Bitte Wahoo in
        den Einstellungen verbinden.") when the provider is not set up.
        """
        self._execute(handler, request)

    def _execute(self, handler: Any, request: RouteRequest) -> None:
        """Queue a sync job.

        Request: `POST /api/sync/jobs` with JSON body `{"provider": string,
        "type": string, "payload": object}`. `provider` is a registered provider
        id (case-insensitive); `type` is optional (default `refresh`) and one of
        `refresh`, `activity_details`, `plan_push`, `competition_push`,
        `nutrition_sync`, `historical_backfill`, `wellness_backfill` or
        `stream_backfill`, as far as the provider supports it. Without `payload`,
        the top-level `days`, `force` and `reason` fields are used as the payload.
        The payload fields are validated per provider and job type; a refresh
        takes `days` (`-1` or 1 up to the provider's window, at most 365 for
        Intervals.icu and 90 for the others), `force` (boolean), `reason` and
        `end_date`.

        Response: 202 with the queued job (as `GET /api/sync/jobs/{id}`),
        requested by `user`.

        Errors: 400 `invalid_job_request` with the validation text, for example
        "Unsupported provider.", "Unsupported job type.", "Job payload must be an
        object." or "Der Job enthält nicht unterstützte Felder."; 400
        `invalid_job_request` "Der Ernährungs-Export braucht eine bestätigte
        Vorschau." for `nutrition_sync`; 409 `not_configured` with the provider's
        setup message for `garmin`, `wahoo` and `intervals`.
        """
        payload = (
            handler.read_json()
            if SyncCommandEndpoint.needs_body(request.path)
            else None
        )
        status, result = self._endpoint().execute(request.path, payload)
        handler.send_json(status, result)
