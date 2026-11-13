"""HTTP route for explicitly confirmed local privacy deletion."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.route_table import Access, Route, RouteRequest
from backend.privacy import PrivacyDeleteService


class PrivacyDeletePostRoutes:
    """Dispatch the privacy deletion POST to its domain service."""

    def __init__(
        self,
        privacy_delete_service: Callable[[], PrivacyDeleteService],
    ) -> None:
        self._privacy_delete_service = privacy_delete_service

    def routes(self) -> list[Route]:
        return [
            Route("POST", "/api/privacy/delete", Access.SESSION_CSRF, self._delete),
            Route("POST", "/api/privacy/gps", Access.SESSION_CSRF, self._gps),
            Route(
                "POST", "/api/privacy/gps/delete", Access.SESSION_CSRF, self._delete_gps
            ),
        ]

    def _delete(self, handler: Any, _request: RouteRequest) -> None:
        """Delete the local athlete data after the typed confirmation (`confirm`).

        Request: JSON body `{"confirm": "LOKALE DATEN LÖSCHEN"}`, required and
        compared exactly.

        Response: 200 with `status` (`"ok"`), `local_data_deleted` (`true`),
        `deleted_categories` (record count per category, as in the preview),
        `recovery_copies_failed` and `log_files_failed` (what could not be
        erased), `remote_delete_attempted` and `remote_conversation_deleted`
        (the OpenAI conversation), `wahoo_revoke_attempted`, `wahoo_revoked` and
        `remote_untouched`. The deletion runs under the maintenance gate and also
        ends every session.

        Errors: 400 "Zum Löschen muss LOKALE DATEN LÖSCHEN bestätigt werden."; 409
        "Eine Datenbankwiederherstellung läuft bereits." while another restore or
        deletion runs; 409 `maintenance_drain_timeout` "Laufende Aufgaben, etwa
        eine Coach-Antwort, werden noch beendet. Es wurde nichts geändert. Bitte
        gleich erneut versuchen."
        """
        payload = handler.read_json()
        handler.send_json(
            200, self._privacy_delete_service().delete(payload.get("confirm"))
        )

    def _gps(self, handler: Any, _request: RouteRequest) -> None:
        """Turn GPS-track storage on or off (`enabled`).

        Request: JSON body `{"enabled": boolean}`, required. Tracks already stored
        stay.

        Response: 200 with `status` (`"ok"`), `enabled`, `stored_tracks` and
        `confirmation_text`, as in `GET /api/privacy/gps`.

        Errors: 400 "enabled muss true oder false sein." when `enabled` is not a
        boolean.
        """
        payload = handler.read_json()
        handler.send_json(
            200, self._privacy_delete_service().set_gps_tracks(payload.get("enabled"))
        )

    def _delete_gps(self, handler: Any, _request: RouteRequest) -> None:
        """Delete every stored GPS track and the routes derived from them after the typed confirmation (`confirm`).

        Request: JSON body `{"confirm": "GPS-SPUREN LÖSCHEN"}`, required and
        compared exactly.

        Response: 200 with `status` (`"ok"`), `deleted_tracks` (number deleted),
        `enabled`, `stored_tracks` and `confirmation_text`. The deletion runs
        under the maintenance gate.

        Errors: 400 "Zum Löschen muss GPS-SPUREN LÖSCHEN bestätigt werden."; 409
        "Eine Datenbankwiederherstellung läuft bereits." while another restore or
        deletion runs; 409 `maintenance_drain_timeout` as for
        `POST /api/privacy/delete`.
        """
        payload = handler.read_json()
        handler.send_json(
            200,
            self._privacy_delete_service().delete_gps_tracks(payload.get("confirm")),
        )
