"""Wahoo Cloud API read transport.

Only reads: the workout list, one workout summary and the user. The bearer token
comes from injected callables owned by the connection use case, so this module
never stores, logs or returns a token. Every request goes through the shared
JSON client, which applies the timeout and the response size cap and records
request shapes only. Provider payloads are never copied into exceptions.

Failure contract:

* A 401 triggers one forced token refresh and one retry. A second 401, or a
  refresh the provider rejects, raises ``WahooReconnectRequiredError``.
* A 429, a 408 or a 5xx raises ``WahooRetryableError``.
* Any other rejection raises a content-free ``AppError``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import urlencode

from backend.canonical.local_time import parse_provider_datetime
from backend.errors import AppError
from backend.providers.wahoo_oauth import WAHOO_API_BASE, WAHOO_SERVICE

WORKOUTS_PATH: Final = "/v1/workouts"
USER_PATH: Final = "/v1/user"
REQUEST_TIMEOUT_SECONDS: Final = 30
WORKOUTS_PER_PAGE: Final = 50
# Bounds one sync at 1000 workouts however the provider paginates.
MAX_WORKOUT_PAGES: Final = 20
MAX_WORKOUT_ID: Final = 2**63 - 1

RECONNECT_REASON: Final = "wahoo_reconnect_required"
RECONNECT_MESSAGE: Final = (
    "Die Wahoo-Verbindung ist abgelaufen. Bitte Wahoo neu verbinden."
)
INVALID_RESPONSE_MESSAGE: Final = "Wahoo hat eine ungültige Antwort gesendet."
REJECTED_MESSAGE: Final = "Wahoo hat die Anfrage abgelehnt."
RETRYABLE_MESSAGE: Final = "Wahoo ist vorübergehend nicht erreichbar."
RATE_LIMITED_MESSAGE: Final = "Wahoo begrenzt die Anfragen vorübergehend."

_RETRYABLE_STATUSES: Final = frozenset({408, 429})

JsonRequest = Callable[..., Any]


class WahooReconnectRequiredError(AppError):
    """The Wahoo authorization is no longer usable and must be renewed."""

    def __init__(self) -> None:
        super().__init__(409, RECONNECT_MESSAGE, reason=RECONNECT_REASON)


class WahooRetryableError(AppError):
    """A temporary Wahoo failure: rate limit, timeout or server error."""

    def __init__(
        self, upstream_status: int, retry_after_seconds: int | None = None
    ) -> None:
        limited = upstream_status == 429
        super().__init__(
            429 if limited else 503,
            RATE_LIMITED_MESSAGE if limited else RETRYABLE_MESSAGE,
            reason="wahoo_rate_limited" if limited else "wahoo_unavailable",
            upstream_status=upstream_status,
            retry_after_seconds=retry_after_seconds,
        )


@dataclass(frozen=True, slots=True)
class WahooWorkoutFetch:
    """Workout rows of one window plus how much of the response was unusable."""

    workouts: tuple[Mapping[str, Any], ...]
    skipped: int = 0
    truncated: bool = False


def _invalid_response() -> AppError:
    return AppError(502, INVALID_RESPONSE_MESSAGE, reason="wahoo_invalid_response")


class WahooClient:
    """Read Wahoo workouts with an injected, refreshable bearer token."""

    def __init__(
        self,
        *,
        request: JsonRequest,
        access_token: Callable[[], str],
        refresh_access_token: Callable[[str], str],
    ) -> None:
        self._request = request
        self._access_token = access_token
        self._refresh_access_token = refresh_access_token

    def list_workouts(
        self, *, since: datetime, until: datetime | None = None
    ) -> WahooWorkoutFetch:
        """Return workouts that started inside the window, newest first.

        Wahoo sorts by start time, newest first, and embeds the workout summary
        in the list, so the walk stops at the first page that reaches back past
        ``since`` and no per-workout call is needed.
        """
        if since.utcoffset() is None:
            raise ValueError("since must be timezone-aware")
        workouts: list[Mapping[str, Any]] = []
        skipped = 0
        for page in range(1, MAX_WORKOUT_PAGES + 1):
            payload = self._get(
                WORKOUTS_PATH, {"page": page, "per_page": WORKOUTS_PER_PAGE}
            )
            rows = payload.get("workouts") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise _invalid_response()
            reached_window_start = False
            for row in rows:
                started = _started_at(row)
                if not isinstance(row, dict):
                    skipped += 1
                    continue
                if started is None:
                    # Unusable start: kept for the mapper to count, never filtered.
                    workouts.append(row)
                    continue
                if started < since:
                    reached_window_start = True
                    continue
                if until is not None and started > until:
                    continue
                workouts.append(row)
            if reached_window_start or len(rows) < _page_size(payload):
                return WahooWorkoutFetch(tuple(workouts), skipped)
        return WahooWorkoutFetch(tuple(workouts), skipped, truncated=True)

    def workout_summary(self, workout_id: int) -> Mapping[str, Any]:
        """Return the summary object of one workout."""
        payload = self._get(
            f"{WORKOUTS_PATH}/{_workout_id(workout_id)}/workout_summary"
        )
        if not isinstance(payload, dict):
            raise _invalid_response()
        return payload

    def user(self) -> Mapping[str, Any]:
        """Return the connected Wahoo user."""
        payload = self._get(USER_PATH)
        if not isinstance(payload, dict):
            raise _invalid_response()
        return payload

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        url = f"{WAHOO_API_BASE}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        rejected = self._access_token()
        try:
            return self._send(url, rejected)
        except AppError as exc:
            if exc.upstream_status != 401:
                raise _translated(exc) from None
        # One forced refresh and one retry; a refresh the provider rejects raises
        # the reconnect error from the connection use case.
        token = self._refresh_access_token(rejected)
        try:
            return self._send(url, token)
        except AppError as exc:
            if exc.upstream_status == 401:
                raise WahooReconnectRequiredError from None
            raise _translated(exc) from None

    def _send(self, url: str, token: str) -> Any:
        return self._request(
            "GET",
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
            service=WAHOO_SERVICE,
        )


def _translated(error: AppError) -> AppError:
    """Replace a provider error by a content-free typed error."""
    status = error.upstream_status
    if status is None:
        # Transport failures and oversized responses already carry safe text.
        if isinstance(error, WahooReconnectRequiredError | WahooRetryableError):
            return error
        return AppError(
            error.status, error.message, reason=error.reason or "wahoo_request_failed"
        )
    if status in _RETRYABLE_STATUSES or status >= 500:
        return WahooRetryableError(status, error.retry_after_seconds)
    return AppError(
        502, REJECTED_MESSAGE, reason="wahoo_request_rejected", upstream_status=status
    )


def _page_size(payload: object) -> int:
    """Return the page size Wahoo applied, which may be below the requested one."""
    applied = payload.get("per_page") if isinstance(payload, dict) else None
    if isinstance(applied, int) and not isinstance(applied, bool):
        return min(max(applied, 1), WORKOUTS_PER_PAGE)
    return WORKOUTS_PER_PAGE


def _workout_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("workout id must be an integer")  # noqa: TRY004 - bad value, not a type contract
    if not 0 < value <= MAX_WORKOUT_ID:
        raise ValueError("workout id is out of range")
    return value


def _started_at(row: object) -> datetime | None:
    if not isinstance(row, dict):
        return None
    parsed = parse_provider_datetime(row.get("starts"), UTC)
    return parsed.astimezone(UTC) if parsed is not None else None
