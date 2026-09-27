"""Application errors and safe provider error mapping."""

from collections.abc import Callable
import re


INTERVALS_API_KEY_ERROR = "INTERVALS_API_KEY ist nicht konfiguriert."
OPENAI_API_KEY_ERROR = "OPENAI_API_KEY ist nicht konfiguriert."
GEMINI_API_KEY_ERROR = "GEMINI_API_KEY ist nicht konfiguriert."
NOT_FOUND_ERROR = "Nicht gefunden."
INTERNAL_SERVER_ERROR = "Interner Serverfehler."
COMPETITION_NOT_FOUND_ERROR = "Wettkampf nicht gefunden."
COACH_ABORTED_ERROR = "Die Coach-Anfrage wurde abgebrochen."
STRUCTURED_AUTHORIZATION_ERROR = "Die strukturierte Coach-Autorisierung erlaubt diesen Schritt nicht."
INVALID_PLANNING_ID_ERROR = "Ungültige lokale Planungs-ID."
CORRUPT_PLANNING_ERROR = "Die lokale Planung ist beschädigt."
INVALID_LIBRARY_ID_ERROR = "Ungültige lokale Bibliothekseinheiten-ID."
CORRUPT_LIBRARY_ERROR = "Die lokale Bibliothekseinheit ist beschädigt."
INVALID_PLANNING_DATE_ERROR = "Das Planungsdatum muss das Format JJJJ-MM-TT haben."
STALE_PLANNING_REVISION_ERROR = "Die lokale Planrevision ist inzwischen veraltet."
UNSUPPORTED_BYDAY_ERROR = "BYDAY der Kalender-Wiederholung wird nicht unterstützt."
PLANNED_CALENDAR_RECHECK_ERROR = "Die Planung wurde waehrend der Reparatur geaendert. Bitte erneut abgleichen."


class AppError(Exception):
    def __init__(
        self, status: int, message: str, *, reason: str | None = None,
        retry_after: int | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.message = message
        self.reason = reason
        self.retry_after = retry_after


def public_error_payload(error: AppError, redact: Callable[[str], str]) -> dict[str, object]:
    """Build the shared, redacted HTTP error envelope."""
    reason = error.reason or "request_failed"
    if not re.fullmatch(r"[a-z0-9_]{1,80}", reason):
        reason = "request_failed"
    payload: dict[str, object] = {
        "error": redact(error.message)[:1000],
        "reason": reason,
    }
    if type(error.retry_after) is int:
        payload["retry_after"] = max(0, error.retry_after)
    return payload


def public_app_error_status(error: AppError) -> int:
    """Keep upstream authentication failures separate from local sessions."""
    if error.status == 401 and error.reason == "authentication_or_permission":
        return 502
    return error.status


class ClientDisconnected(Exception):
    pass


def provider_error(service: str | None, category: str, *, status: int | None = None) -> AppError:
    """Create a short, classified provider error without forwarding exception text."""
    service_key = str(service or "").casefold()
    label = {
        "garmin": "Garmin",
        "intervals": "Intervals.icu",
        "openai": "OpenAI",
        "calendar": "Der externe Kalender",
    }.get(service_key, "Der externe Dienst")
    if category == "network":
        message = f"{label} ist nicht erreichbar."
        reason = "network_error" if service_key == "openai" else "provider_network_error"
    elif category == "http":
        suffix = f" (HTTP {status})" if status else ""
        message = f"{label} konnte die Anfrage nicht verarbeiten{suffix}."
        reason = "http_error" if service_key == "openai" else "provider_http_error"
    else:
        message = f"Die Antwort von {label} konnte nicht verarbeitet werden."
        reason = "client_error" if service_key == "openai" else "provider_client_error"
    return AppError(502, message, reason=reason)
