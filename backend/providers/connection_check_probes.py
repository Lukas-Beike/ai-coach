"""Read-only probes behind the explicit provider connection checks.

Each probe performs one bounded GET (Garmin: a token-only login) and returns
nothing; the caller classifies failures. Probes use no athlete data and never
write remotely. Calendar feeds and Open Food Facts have no probe: a feed check
would be the full feed fetch, and Open Food Facts needs no credentials.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlencode

from backend.config import Config
from backend.errors import AppError
from backend.providers import openai_requests
from backend.providers.connection_checks import (
    MISCONFIGURED_REASON,
    SCOPE_MISSING_REASON,
    UNSUPPORTED_REASON,
    ProviderProbe,
    simple_probe,
)

OPENAI_MODELS_PATH = "/models"
# Fixed public coordinates: the check never sends the athlete's location.
_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast?" + urlencode(
    {"latitude": 52.52, "longitude": 13.41, "current": "temperature_2m"}
)
_TIMEOUT_SECONDS = 15


def _identity(*values: object) -> str:
    return "\x1f".join(str(value or "") for value in values)


def _openai_check(
    current: Config, request: Callable[..., Any], default_base_url: str
) -> None:
    try:
        url = openai_requests.endpoint(
            current.openai_base_url,
            OPENAI_MODELS_PATH,
            default_base_url=default_base_url,
        )
    except AppError as error:
        raise AppError(
            400, "Ungültige Konfiguration.", reason=MISCONFIGURED_REASON
        ) from error
    try:
        request(
            "GET",
            url,
            headers={"Authorization": f"Bearer {current.openai_api_key.strip()}"},
            timeout=_TIMEOUT_SECONDS,
            service="openai-check",
        )
    except AppError as error:
        # Compatible endpoints may not implement the model listing.
        if error.upstream_status in {404, 405, 501}:
            raise AppError(
                502, "Prüfung nicht unterstützt.", reason=UNSUPPORTED_REASON
            ) from error
        raise


def _intervals_check(current: Config, intervals_get: Callable[[str], Any]) -> None:
    athlete = quote(str(current.intervals_athlete_id).strip(), safe="")
    try:
        intervals_get(f"/athlete/{athlete}")
    except AppError as error:
        if error.upstream_status == 404:
            raise AppError(
                400, "Ungültige Konfiguration.", reason=MISCONFIGURED_REASON
            ) from error
        raise


def build_probes(
    *,
    config: Callable[[], Config],
    request: Callable[..., Any],
    default_openai_base_url: str,
    intervals_get: Callable[[str], Any],
    wahoo_status: Callable[[], dict[str, Any]],
    wahoo_user: Callable[[], Any],
    garmin_connected: Callable[[], bool],
    garmin_fingerprint: Callable[[], str],
    garmin_login: Callable[[], None],
) -> dict[str, ProviderProbe]:
    """Return the probes for the providers that support a safe explicit check."""

    def openai() -> None:
        _openai_check(config(), request, default_openai_base_url)

    def intervals() -> None:
        _intervals_check(config(), intervals_get)

    def weather() -> None:
        request(
            "GET",
            _OPEN_METEO_URL,
            timeout=_TIMEOUT_SECONDS,
            service="open-meteo-check",
        )

    def wahoo() -> None:
        # The profile read needs user_read; a grant without it is still usable.
        if "user_read" not in str(wahoo_status().get("scope") or "").split():
            raise AppError(502, "Berechtigung fehlt.", reason=SCOPE_MISSING_REASON)
        wahoo_user()

    def garmin_check() -> str:
        # The login may rotate the stored token; report the identity that now holds.
        garmin_login()
        return _identity(True, garmin_fingerprint())

    def garmin_snapshot() -> tuple[bool, str]:
        connected = garmin_connected()
        return connected, _identity(connected, garmin_fingerprint())

    def wahoo_snapshot() -> tuple[bool, str]:
        current = config()
        status = wahoo_status()
        return (
            bool(current.wahoo_configured and status.get("connected")),
            _identity(
                current.wahoo_client_id,
                current.wahoo_client_secret,
                status.get("connected_at"),
            ),
        )

    return {
        "openai": simple_probe(
            configured=lambda: bool(str(config().openai_api_key).strip()),
            identity=lambda: _identity(
                config().openai_api_key, config().openai_base_url
            ),
            check=openai,
            auth_hint="Anmeldung abgelehnt – API-Schlüssel und Basis-URL prüfen",
        ),
        "intervals": simple_probe(
            configured=lambda: bool(
                str(config().intervals_api_key).strip()
                and str(config().intervals_athlete_id).strip()
            ),
            identity=lambda: _identity(
                config().intervals_api_key, config().intervals_athlete_id
            ),
            check=intervals,
            auth_hint="Anmeldung abgelehnt – API-Schlüssel und Athlete-ID prüfen",
        ),
        "garmin": ProviderProbe(
            snapshot=garmin_snapshot,
            check=garmin_check,
            auth_hint="Anmeldung fehlgeschlagen – später erneut prüfen oder neu anmelden",
        ),
        "wahoo": ProviderProbe(
            snapshot=wahoo_snapshot,
            check=wahoo,
            auth_hint="Zugriff abgelehnt – Wahoo neu verbinden",
        ),
        "weather": simple_probe(
            configured=lambda: True,
            identity=lambda: "open-meteo",
            check=weather,
        ),
    }
