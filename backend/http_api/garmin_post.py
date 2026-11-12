"""Garmin login routes: credentials, MFA code and disconnect (session and CSRF checked)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.route_table import Access, Route, RouteRequest
from backend.sync.garmin_login import GarminLoginService

LOGIN_PATH = "/api/garmin/login"
MFA_PATH = "/api/garmin/login/mfa"
DISCONNECT_PATH = "/api/garmin/disconnect"


class GarminPostRoutes:
    """Authenticated Garmin commands. Request bodies are never echoed back."""

    def __init__(self, garmin_login: Callable[[], GarminLoginService]) -> None:
        self._garmin_login = garmin_login

    def routes(self) -> list[Route]:
        return [
            Route("POST", path, Access.SESSION_CSRF, self._handle)
            for path in (LOGIN_PATH, MFA_PATH, DISCONNECT_PATH)
        ]

    def _handle(self, handler: Any, request: RouteRequest) -> None:
        """Connect Garmin with credentials or an MFA code, or disconnect it.

        Request: `POST /api/garmin/login` takes `{"email": string, "password":
        string}`, each non-blank and at most 512 characters; the password is used
        once, never stored. `POST /api/garmin/login/mfa` takes `{"code": string}`
        of 4 to 10 digits. `POST /api/garmin/disconnect` reads no field (an empty
        object).

        Response: 200 `{"status", "connected", "source", "mfa_pending"}`. `status`
        is `connected` or `mfa_required` (login, the challenge stays pending for 10
        minutes until a code is submitted or a new login starts), `connected` (MFA)
        or `disconnected`. Disconnect deletes the stored Garmin tokens and discards
        a pending login; stored Garmin data is kept.

        Errors: 400 "Ungültige Garmin-Eingabe." for a missing, non-string, blank
        or too long `email`, `password` or `code`; 400 "Der MFA-Code ist ungültig.
        Bitte erneut eingeben." for a `code` that is not 4 to 10 digits. Login: 422
        "Garmin-Anmeldung fehlgeschlagen. Bitte E-Mail und Passwort prüfen." for
        rejected credentials, 502 "Garmin ist derzeit nicht erreichbar. Bitte
        später erneut versuchen." for any other Garmin failure, 502
        "Garmin-Tokens konnten nicht übernommen werden." when the tokens cannot be
        taken from the Garmin session. Login and MFA: 409 "Die Garmin-Anmeldung wurde
        inzwischen getrennt oder neu gestartet." when a disconnect or newer login
        superseded this one. MFA: 409 "Keine Garmin-Anmeldung mit MFA aktiv. Bitte erneut
        anmelden." without a pending login, 409 "Die MFA-Anmeldung ist abgelaufen.
        Bitte erneut anmelden." after expiry, 422 "Der MFA-Code ist ungültig.
        Bitte erneut eingeben." for a wrong code (the login stays pending), 409
        "Zu viele falsche MFA-Codes. Bitte die Garmin-Anmeldung neu starten." on
        the fifth wrong code, which discards it.
        """
        body = handler.read_json()
        service = self._garmin_login()
        if request.path == LOGIN_PATH:
            result = service.login(body)
        elif request.path == MFA_PATH:
            result = service.submit_mfa(body)
        else:
            result = service.disconnect()
        handler.send_json(200, result)
