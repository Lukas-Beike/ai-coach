"""Shared error policy of the Garmin history reads (activity files).

``read_one`` reads one activity through the caller's external-call wrapper and keeps
the original error; ``skips`` and ``stop_kind`` classify it with the hooks the sync
owner injects, like ``WellnessHistoryHooks``:

* a client error, an unreadable answer or a 403 on one activity skips only that
  activity;
* a rate limit, a rejected Personal API key (a failed token exchange, which the
  client already flagged), a 401 on a data read (after the client's one renewal)
  or any other error ends the read with ``RatingReadStopped``, so the job is
  retried or stops and the cursor stays. Rows read before are already handed on.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Any, Final

from backend.providers import http as provider_http
from backend.providers.descriptors import GARMIN_ID
from backend.providers.garmin import ExternalCall

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
    """Policy the sync owner supplies to one history read.

    ``error_class`` maps an error to the job error class (``rate_limited``,
    ``auth_required``, ...); ``skippable`` names errors that only skip one
    activity; ``key_rejected`` says whether the Personal API key was rejected.
    """

    error_class: Callable[[BaseException], str]
    skippable: Callable[[BaseException], bool]
    key_rejected: Callable[[], bool] = lambda: False
    guard: Callable[[], AbstractContextManager[Any]] = nullcontext


class ReadFailed(Exception):
    def __init__(self, original: BaseException) -> None:
        super().__init__()
        self.original = original


def read_one(
    fetch: Callable[[str], Any],
    activity_id: str,
    external_call: ExternalCall,
    operation: str,
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
