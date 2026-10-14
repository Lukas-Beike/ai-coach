"""Wahoo Cloud API transport.

Reads the workout list, one workout summary and the user, and writes training
plans (create, update, delete) on explicit export. The bearer token comes from
injected callables owned by the connection use case, so this module never
stores, logs or returns a token. Every request goes through the shared JSON
client, which applies the timeout and the response size cap and records
request shapes only. Provider payloads, including plan files, are never copied
into exceptions.

Plan field names follow the official Wahoo Cloud API documentation
(https://cloud-api.wahooligan.com/, "Plans"): ``POST /v1/plans`` and
``PUT /v1/plans/:id`` take the form fields ``plan[file]`` (a base64 data URI of
the plan JSON), ``plan[filename]`` and ``plan[provider_updated_at]``; only
create takes ``plan[external_id]``. The plan JSON is described by
https://cloud-api.wahooligan.com/docs/plan-json-format.pdf.

Failure contract:

* A 401 triggers one forced token refresh and one retry. A second 401, or a
  refresh the provider rejects, raises ``WahooReconnectRequiredError``.
* A 429, a 408 or a 5xx raises ``WahooRetryableError``.
* Any other rejection raises a content-free ``AppError``.
"""

from __future__ import annotations

import base64
import json
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
PLANS_PATH: Final = "/v1/plans"
POWER_ZONES_PATH: Final = "/v1/power_zones"
# The OAuth scopes that allow reading the power zones and the user profile.
POWER_ZONES_SCOPE: Final = "power_zones_read"
USER_SCOPE: Final = "user_read"
FORM_CONTENT_TYPE: Final = "application/x-www-form-urlencoded"
PLAN_DATA_URI_PREFIX: Final = "data:application/json;base64,"
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


@dataclass(frozen=True, slots=True)
class _PageRows:
    """The rows of one page inside the window and whether it reached ``since``."""

    workouts: tuple[Mapping[str, Any], ...]
    skipped: int
    reached_window_start: bool


def _window_rows(
    rows: list[Any], *, since: datetime, until: datetime | None
) -> _PageRows:
    """Keep the page rows that started inside the window."""
    workouts: list[Mapping[str, Any]] = []
    skipped = 0
    reached_window_start = False
    for row in rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        started = _started_at(row)
        if started is None:
            # Unusable start: kept for the mapper to count, never filtered.
            workouts.append(row)
        elif started < since:
            reached_window_start = True
        elif until is None or started <= until:
            workouts.append(row)
    return _PageRows(tuple(workouts), skipped, reached_window_start)


def _invalid_response() -> AppError:
    return AppError(502, INVALID_RESPONSE_MESSAGE, reason="wahoo_invalid_response")


class WahooClient:
    """Read Wahoo workouts and write plans with an injected, refreshable token."""

    def __init__(
        self,
        *,
        request: JsonRequest,
        access_token: Callable[[], str],
        refresh_access_token: Callable[[str], str],
        invalidate_access_token: Callable[[str], None] | None = None,
    ) -> None:
        self._request = request
        self._access_token = access_token
        self._invalidate_access_token = invalidate_access_token
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
            page_rows = _window_rows(rows, since=since, until=until)
            workouts.extend(page_rows.workouts)
            skipped += page_rows.skipped
            if page_rows.reached_window_start or len(rows) < _page_size(payload):
                return WahooWorkoutFetch(tuple(workouts), skipped)
        return WahooWorkoutFetch(tuple(workouts), skipped, truncated=True)

    def workout_summary(self, workout_id: int) -> Mapping[str, Any]:
        """Return the summary object of one workout."""
        payload = self._get(f"{WORKOUTS_PATH}/{_remote_id(workout_id)}/workout_summary")
        if not isinstance(payload, dict):
            raise _invalid_response()
        return payload

    def user(self) -> Mapping[str, Any]:
        """Return the connected Wahoo user."""
        payload = self._get(USER_PATH)
        if not isinstance(payload, dict):
            raise _invalid_response()
        return payload

    def create_plan(
        self,
        plan: Mapping[str, Any],
        *,
        filename: str,
        external_id: str,
        provider_updated_at: datetime,
    ) -> Mapping[str, Any]:
        """Upload a new plan and return the saved plan object."""
        fields = _plan_fields(plan, filename, provider_updated_at)
        fields["plan[external_id]"] = external_id
        return self._plan_object(self._write("POST", PLANS_PATH, fields))

    def update_plan(
        self,
        plan_id: int,
        plan: Mapping[str, Any],
        *,
        filename: str,
        provider_updated_at: datetime,
    ) -> Mapping[str, Any]:
        """Replace one plan this app created and return the saved plan object."""
        fields = _plan_fields(plan, filename, provider_updated_at)
        return self._plan_object(
            self._write("PUT", f"{PLANS_PATH}/{_remote_id(plan_id)}", fields)
        )

    def delete_plan(self, plan_id: int) -> None:
        """Delete one plan; workouts that used it keep existing without the link."""
        self._write("DELETE", f"{PLANS_PATH}/{_remote_id(plan_id)}", None)

    def list_plans(self) -> tuple[Mapping[str, Any], ...]:
        """Return the plans this app uploaded."""
        payload = self._get(PLANS_PATH)
        if not isinstance(payload, list) or not all(
            isinstance(row, dict) for row in payload
        ):
            raise _invalid_response()
        return tuple(payload)

    def power_zones(self) -> tuple[Mapping[str, Any], ...]:
        """Return the athlete's power zone sets, one row per zone set."""
        payload = self._get(POWER_ZONES_PATH)
        if not isinstance(payload, list) or not all(
            isinstance(row, dict) for row in payload
        ):
            raise _invalid_response()
        return tuple(payload)

    @staticmethod
    def _plan_object(payload: Any) -> Mapping[str, Any]:
        if not isinstance(payload, dict):
            raise _invalid_response()
        return payload

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        url = f"{WAHOO_API_BASE}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        return self._call("GET", url, None)

    def _write(self, method: str, path: str, fields: Mapping[str, str] | None) -> Any:
        body = urlencode(fields).encode("ascii") if fields is not None else None
        return self._call(method, f"{WAHOO_API_BASE}{path}", body)

    def _call(self, method: str, url: str, body: bytes | None) -> Any:
        rejected = self._access_token()
        try:
            return self._send(method, url, rejected, body)
        except AppError as exc:
            if exc.upstream_status != 401:
                raise _translated(exc) from None
        # One forced refresh and one retry; a refresh the provider rejects raises
        # the reconnect error from the connection use case.
        token = self._refresh_access_token(rejected)
        try:
            return self._send(method, url, token, body)
        except AppError as exc:
            if exc.upstream_status == 401:
                # A freshly refreshed token was rejected too: drop the grant so
                # scheduled jobs stop retrying until the athlete reconnects.
                if self._invalidate_access_token is not None:
                    self._invalidate_access_token(token)
                raise WahooReconnectRequiredError from None
            raise _translated(exc) from None

    def _send(self, method: str, url: str, token: str, body: bytes | None) -> Any:
        headers = {"Authorization": f"Bearer {token}"}
        if body is None:
            return self._request(
                method,
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
                service=WAHOO_SERVICE,
            )
        return self._request(
            method,
            url,
            headers=headers,
            raw_body=body,
            content_type=FORM_CONTENT_TYPE,
            timeout=REQUEST_TIMEOUT_SECONDS,
            service=WAHOO_SERVICE,
        )


def _plan_fields(
    plan: Mapping[str, Any], filename: str, provider_updated_at: datetime
) -> dict[str, str]:
    if provider_updated_at.utcoffset() is None:
        raise ValueError("provider_updated_at must be timezone-aware")
    document = json.dumps(plan, separators=(",", ":"), ensure_ascii=True)
    encoded = base64.b64encode(document.encode("utf-8")).decode("ascii")
    return {
        "plan[file]": f"{PLAN_DATA_URI_PREFIX}{encoded}",
        "plan[filename]": filename,
        "plan[provider_updated_at]": provider_updated_at.astimezone(UTC).isoformat(),
    }


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


def _remote_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("remote id must be an integer")  # noqa: TRY004 - bad value, not a type contract
    if not 0 < value <= MAX_WORKOUT_ID:
        raise ValueError("remote id is out of range")
    return value


def _started_at(row: object) -> datetime | None:
    if not isinstance(row, dict):
        return None
    parsed = parse_provider_datetime(row.get("starts"), UTC)
    return parsed.astimezone(UTC) if parsed is not None else None
