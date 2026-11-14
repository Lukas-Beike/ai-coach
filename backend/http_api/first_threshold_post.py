"""Authenticated local route that adopts the first threshold estimate."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.athlete.profile import ProfileService
from backend.http_api.route_table import Access, Route, RouteRequest
from backend.performance.first_threshold_service import FirstThresholdService

ADOPT_PATH = "/api/profile/first-threshold/adopt"


class FirstThresholdPostRoutes:
    """Store the shown estimate as the first threshold on the athlete's request."""

    def __init__(
        self,
        first_threshold_service: Callable[[], FirstThresholdService],
        profile_service: Callable[[], ProfileService],
        database_manager: Callable[[], Any],
        database_lock: Any,
    ) -> None:
        self._first_threshold_service = first_threshold_service
        self._profile_service = profile_service
        self._database_manager = database_manager
        self._database_lock = database_lock

    def routes(self) -> list[Route]:
        return [Route("POST", ADOPT_PATH, Access.SESSION_CSRF, self._adopt)]

    def _adopt(self, handler: Any, _request: RouteRequest) -> None:
        """Adopt the shown first threshold estimate into the profile.

        Request: JSON body `{"percent_lthr": number, "replace_measured": boolean}`.
        `percent_lthr` is required and must equal the current estimate from
        `GET /api/profile`; `replace_measured: true` is needed to replace a value
        stored with origin `measured`.

        Response: 200 `{"profile": object, "first_threshold_estimate": object,
        "adopted": boolean}`. The estimate is stored as percent of the run
        threshold HR with origin `estimated`; `adopted` is `false` without a profile
        write when that value is already stored.

        Errors: 409 "Es liegt keine Schätzung der ersten Schwelle vor."; 409 "Die
        Schätzung hat sich geändert. Bitte die Anzeige aktualisieren." when
        `percent_lthr` differs from the current estimate; 409 "Ein gemessener Wert
        ist gespeichert. Zum Ersetzen bitte bestätigen." without
        `replace_measured`.
        """
        payload = handler.read_json()
        with (
            self._profile_service().mutation_coordinator,
            self._database_lock,
            self._database_manager().unit_of_work(),
        ):
            result = self._first_threshold_service().adopt(payload)
        handler.send_json(200, result)
