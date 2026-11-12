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

from backend.config import DEFAULT_ANTHROPIC_BASE_URL, Config
from backend.errors import AppError
from backend.providers import openai_requests
from backend.providers.claude_requests import CLAUDE_MODELS_PATH, claude_headers
from backend.providers.connection_checks import (
    MISCONFIGURED_REASON,
    SCOPE_MISSING_REASON,
    UNSUPPORTED_REASON,
    ProviderProbe,
    simple_probe,
)
from backend.providers.garmin_personal import PERSONAL_KEY_REJECTED_REASON

OPENAI_MODELS_PATH = "/models"
# Fixed public coordinates: the check never sends the athlete's location.
_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast?" + urlencode(
    {"latitude": 52.52, "longitude": 13.41, "current": "temperature_2m"}
)
_TIMEOUT_SECONDS = 15


def _identity(*values: object) -> str:
    return "\x1f".join(str(value or "") for value in values)


def _models_check(
    request: Callable[..., Any],
    *,
    base_url: str,
    default_base_url: str,
    path: str,
    headers: dict[str, str],
    service: str,
) -> None:
    """List the models of a model provider: the cheapest authenticated read."""
    try:
        url = openai_requests.endpoint(
            base_url, path, default_base_url=default_base_url
        )
    except AppError as error:
        raise AppError(
            400, "Ungültige Konfiguration.", reason=MISCONFIGURED_REASON
        ) from error
    try:
        request("GET", url, headers=headers, timeout=_TIMEOUT_SECONDS, service=service)
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
        current = config()
        _models_check(
            request,
            base_url=current.openai_base_url,
            default_base_url=default_openai_base_url,
            path=OPENAI_MODELS_PATH,
            headers={"Authorization": f"Bearer {current.openai_api_key.strip()}"},
            service="openai-check",
        )

    def anthropic() -> None:
        current = config()
        _models_check(
            request,
            base_url=current.anthropic_base_url,
            default_base_url=DEFAULT_ANTHROPIC_BASE_URL,
            path=CLAUDE_MODELS_PATH,
            headers=claude_headers(current.anthropic_api_key),
            service="anthropic-check",
        )

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

    def personal_key() -> str:
        return str(getattr(config(), "garmin_personal_api_key", "") or "").strip()

    def garmin_identity(connected: bool) -> str:
        return _identity(connected, garmin_fingerprint(), personal_key())

    def garmin_check() -> str:
        # The login may rotate the stored token; report the identity that now holds.
        garmin_login()
        return garmin_identity(garmin_connected())

    def garmin_snapshot() -> tuple[bool, str]:
        # The Personal API key alone is a checkable Garmin connection.
        connected = garmin_connected()
        return connected or bool(personal_key()), garmin_identity(connected)

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
        "anthropic": simple_probe(
            configured=lambda: bool(str(config().anthropic_api_key).strip()),
            identity=lambda: _identity(
                config().anthropic_api_key, config().anthropic_base_url
            ),
            check=anthropic,
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
            reason_hints={
                PERSONAL_KEY_REJECTED_REASON: (
                    "Personal-API-Schlüssel abgelehnt – in Garmin Connect Web "
                    "erneuern und in der Garmin-Karte unter Personal API speichern"
                )
            },
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
