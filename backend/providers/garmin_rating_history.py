"""Read the watch ratings of past Garmin activities for the one-off backfill (#1728).

One single-activity read per activity (``get_activity``, the ``summaryDTO`` with
``directWorkoutRpe``, ``directWorkoutFeel`` and ``minHR``), through the transport
client the caller passes, so the Personal API is used when a key is configured
and the SDK otherwise. The rows have the shape of the regular ``activity_ratings``
section, so the existing mapping and storage path applies.

A pause separates the calls (the Personal API rate limits are undocumented); the
caller's guard wraps each read only, never the pause. The sync owner injects the
error classification, like ``WellnessHistoryHooks``:

* a client error, an unreadable answer or a 403 on one activity skips only that
  activity (``on_skip``);
* a rate limit, a rejected Personal API key (a failed token exchange, which the
  client already flagged), a 401 on a data read (after the client's one renewal)
  or any other error ends the read with ``RatingReadStopped``, so the job is
  retried or stops and the cursor stays. Rows read before are already handed on.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Any, Final

from backend.canonical.garmin_payload import ACTIVITY_RATINGS_SECTION
from backend.providers import http as provider_http
from backend.providers.descriptors import GARMIN_ID
from backend.providers.garmin import ExternalCall, rating_row

CALL_DELAY_SECONDS: Final = 2.0
_SDK_NOT_FOUND: Final = "GarminConnectNotFoundError"
_FORBIDDEN: Final = 403

RATE_LIMITED: Final = "rate_limited"
KEY_REJECTED: Final = "key_rejected"
AUTH_FAILED: Final = "auth_failed"
FAILED: Final = "failed"


class RatingReadStopped(RuntimeError):
    """The read ended early; ``kind`` says why and ``activity_id`` where.

    The activity file read of the stream backfill ends the same way.
    """

    def __init__(self, kind: str, activity_id: str) -> None:
        super().__init__(kind)
        self.kind = kind
        self.activity_id = activity_id


@dataclass(frozen=True)
class RatingReadHooks:
    """Policy the sync owner supplies to one rating read.

    ``error_class`` maps an error to the job error class (``rate_limited``,
    ``auth_required``, ...); ``skippable`` names errors that only skip one
    activity; ``key_rejected`` says whether the Personal API key was rejected.
    """

    error_class: Callable[[BaseException], str]
    skippable: Callable[[BaseException], bool]
    key_rejected: Callable[[], bool] = lambda: False
    guard: Callable[[], AbstractContextManager[Any]] = nullcontext


def collect_activity_ratings(
    client: Any,
    activities: Sequence[tuple[str, str]],
    on_row: Callable[[dict[str, Any]], None],
    on_skip: Callable[[str], None],
    *,
    external_call: ExternalCall,
    hooks: RatingReadHooks,
    sleep: Callable[[float], None] = time.sleep,
    delay_seconds: float = CALL_DELAY_SECONDS,
) -> None:
    """Hand the rating row of each ``(activity_id, start)`` to ``on_row``.

    A skipped activity goes to ``on_skip``. Raises ``RatingReadStopped``.
    """
    fetch = getattr(client, "get_activity", None)
    if not callable(fetch):
        raise RatingReadStopped(FAILED, activities[0][0] if activities else "")
    for position, (activity_id, started) in enumerate(activities):
        if position:
            sleep(delay_seconds)
        try:
            with hooks.guard():
                value = read_one(fetch, activity_id, external_call)
        except ReadFailed as failed:
            if skips(failed.original, hooks):
                on_skip(activity_id)
                continue
            raise RatingReadStopped(
                stop_kind(failed.original, hooks), activity_id
            ) from None
        row = rating_row(value, activity_id, started)
        if row is None:
            on_skip(activity_id)
            continue
        on_row(row)


class ReadFailed(Exception):
    def __init__(self, original: BaseException) -> None:
        super().__init__()
        self.original = original


def read_one(
    fetch: Callable[[str], Any],
    activity_id: str,
    external_call: ExternalCall,
    operation: str = ACTIVITY_RATINGS_SECTION,
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
        return external_call(GARMIN_ID, operation, read, {"activity_id": activity_id})
    except Exception as exc:  # noqa: BLE001 - classified by the caller.
        raise ReadFailed(originals[0] if originals else exc) from None


def skips(error: BaseException, hooks: RatingReadHooks) -> bool:
    """Only a client error, an unreadable answer or a 403 skips one activity."""
    code = hooks.error_class(error)
    if code == "rate_limited":
        return False
    if code == "auth_required":
        # A failed token exchange fails every read: that is no activity's fault.
        return getattr(error, "status", None) == _FORBIDDEN and not hooks.key_rejected()
    if isinstance(error, provider_http.ProviderHTTPError):
        status = error.status
        return status is not None and 400 <= status < 500
    return hooks.skippable(error) or type(error).__name__ == _SDK_NOT_FOUND


def stop_kind(error: BaseException, hooks: RatingReadHooks) -> str:
    code = hooks.error_class(error)
    if code == "rate_limited":
        return RATE_LIMITED
    if code == "auth_required":
        return KEY_REJECTED if hooks.key_rejected() else AUTH_FAILED
    return FAILED
