"""Read the watch ratings of past Garmin activities for the one-off backfill (#1728).

One single-activity read per activity (``get_activity``, the ``summaryDTO`` with
``directWorkoutRpe``, ``directWorkoutFeel`` and ``minHR``), through the transport
client the caller passes, so the Personal API is used when a key is configured
and the SDK otherwise. The rows have the shape of the regular ``activity_ratings``
section, so the existing mapping and storage path applies.

A pause separates the calls (the Personal API rate limits are undocumented). A
client error or an unreadable answer skips only that activity; a rate limit, a
rejected login or any other error ends the read so the job is retried or stops.
Rows read before the failure are already handed to ``sink``.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any, Final

from backend.canonical.garmin_payload import ACTIVITY_RATINGS_SECTION
from backend.providers import http as provider_http
from backend.providers.descriptors import GARMIN_ID
from backend.providers.garmin import ExternalCall, rating_row

CALL_DELAY_SECONDS: Final = 2.0
_SERVER_ERROR_FROM: Final = 500
_SDK_NOT_FOUND: Final = "GarminConnectNotFoundError"
_SDK_RATE_LIMITED: Final = "GarminConnectTooManyRequestsError"
_SDK_AUTH: Final = "GarminConnectAuthenticationError"


class RatingReadRateLimited(RuntimeError):
    """Garmin limited the requests; the cursor stays and a later run retries."""


class RatingReadRejected(RuntimeError):
    """Garmin rejected the login or the Personal API key; the backfill stops."""


def collect_activity_ratings(
    client: Any,
    activities: Sequence[tuple[str, str]],
    sink: Callable[[dict[str, Any]], None],
    *,
    external_call: ExternalCall,
    sleep: Callable[[float], None] = time.sleep,
    delay_seconds: float = CALL_DELAY_SECONDS,
) -> int:
    """Hand the rating row of each ``(activity_id, start)`` to ``sink``; return skips.

    Raises ``RatingReadRateLimited`` or ``RatingReadRejected`` for those answers
    and the original error for any other that is not skippable.
    """
    fetch = getattr(client, "get_activity", None)
    if not callable(fetch):
        raise RatingReadRejected("get_activity is not available")
    skipped = 0
    for position, (activity_id, started) in enumerate(activities):
        if position:
            sleep(delay_seconds)
        try:
            value = _read_one(fetch, activity_id, external_call)
        except _ReadFailed as failed:
            if _skippable(failed.original):
                skipped += 1
                continue
            _raise_stop(failed.original, failed.wrapped)
        row = rating_row(value, activity_id, started)
        if row is None:
            skipped += 1
            continue
        sink(row)
    return skipped


class _ReadFailed(Exception):
    def __init__(self, original: BaseException, wrapped: BaseException) -> None:
        super().__init__()
        self.original = original
        self.wrapped = wrapped


def _read_one(
    fetch: Callable[[str], Any], activity_id: str, external_call: ExternalCall
) -> Any:
    """Read one activity; a failure carries the original error, not external_call's."""
    originals: list[BaseException] = []

    def read() -> Any:
        try:
            return fetch(activity_id)
        except Exception as exc:
            # external_call turns every error into one class; keep the original.
            originals.append(exc)
            raise

    try:
        return external_call(
            GARMIN_ID, ACTIVITY_RATINGS_SECTION, read, {"activity_id": activity_id}
        )
    except Exception as exc:  # noqa: BLE001 - classified by the caller.
        raise _ReadFailed(originals[0] if originals else exc, exc) from None


def _skippable(error: BaseException) -> bool:
    """Only a client error or an unreadable answer may skip one activity."""
    if isinstance(error, provider_http.ProviderHTTPError):
        status = error.status
        return (
            status is not None
            and status not in {401, 403, 429}
            and status < _SERVER_ERROR_FROM
        )
    return (
        isinstance(
            error, (TypeError, ValueError, provider_http.ProviderInvalidResponse)
        )
        or type(error).__name__ == _SDK_NOT_FOUND
    )


def _raise_stop(original: BaseException, wrapped: BaseException) -> None:
    status = getattr(original, "status", None)
    name = type(original).__name__
    if status == 429 or name == _SDK_RATE_LIMITED:
        raise RatingReadRateLimited from None
    if status in {401, 403} or name == _SDK_AUTH:
        raise RatingReadRejected from None
    raise wrapped
