"""Garmin capability pause state: which failures count and how it is cleared.

The state is one ``garmin_capability_<source>`` key/value row per source (or
detail part). A source is paused for a day after ``GARMIN_CAPABILITY_FAILURE_LIMIT``
failures in a row of the same capability class. The wellness history backfill
keeps its own rows (``WELLNESS_BACKFILL_PREFIX``) so it cannot pause the regular
sync.
"""

from __future__ import annotations

from typing import Any, Final

GARMIN_CAPABILITY_KEY_PREFIX: Final = "garmin_capability_"
# Prefix of the source name the wellness history backfill pauses under.
WELLNESS_BACKFILL_PREFIX: Final = "wellness_backfill_"

RATE_LIMITED: Final = "rate_limited"
NOT_FOUND: Final = "not_found"
UNSUPPORTED: Final = "unsupported"

_SDK_RATE_LIMITED: Final = "GarminConnectTooManyRequestsError"
_SDK_NOT_FOUND: Final = "GarminConnectNotFoundError"
# ``external_call`` re-raises every provider error as one generic error with the
# original as ``__cause__``; the chain is short, but bound the walk anyway.
_MAX_CAUSE_DEPTH: Final = 5


def capability_key(source: str) -> str:
    return f"{GARMIN_CAPABILITY_KEY_PREFIX}{source}"


def _http_status(error: BaseException) -> int | None:
    for name in ("upstream_status", "status"):
        value = getattr(error, name, None)
        if type(value) is int:
            return value
    return None


def _failure_class(error: BaseException) -> str | None:
    status = _http_status(error)
    name = type(error).__name__
    if status == 429 or name == _SDK_RATE_LIMITED:
        return RATE_LIMITED
    if status == 404 or name == _SDK_NOT_FOUND:
        return NOT_FOUND
    if isinstance(error, NotImplementedError):
        return UNSUPPORTED
    reason = str(getattr(error, "reason", "") or "").casefold()
    message = str(getattr(error, "message", "") or "").casefold()
    if reason == RATE_LIMITED or "rate limit" in message:
        return RATE_LIMITED
    return None


def capability_failure_class(error: BaseException) -> str | None:
    """The capability class of a failure, or None when it must not count.

    Only failures that say the endpoint is limited, missing or unsupported by
    the connected transport count toward a pause: rate limited (HTTP 429), not
    found (HTTP 404) and unsupported (``NotImplementedError``). Network errors,
    timeouts, server errors (5xx), rejected logins (401/403) and unreadable
    answers say nothing about the capability; a rejected login is fixed by a new
    key, which clears the state instead.
    """
    current: BaseException | None = error
    for _ in range(_MAX_CAUSE_DEPTH):
        if current is None:
            return None
        failure = _failure_class(current)
        if failure is not None:
            return failure
        current = current.__cause__
    return None


def clear_capability_state(db: Any, key_values: Any) -> None:
    """Drop every Garmin capability pause, the wellness backfill's included.

    Runs inside the caller's transaction: a new key or login, a passed stored
    login check and a reconnect all start with no inherited pause.
    """
    key_values.delete_prefix(db, GARMIN_CAPABILITY_KEY_PREFIX)
