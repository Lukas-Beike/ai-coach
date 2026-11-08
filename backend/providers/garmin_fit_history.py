"""Download the FIT files of past Garmin activities for the stream backfill (#1763).

One download per activity (``download_activity_fit``), through the transport client
the caller passes. Only the Personal API serves the original file; the SDK has no
such call, so without a Personal API key the client has no method and the read
ends with ``FitTransportMissing`` before any request.

A pause separates the calls; the caller's guard wraps each download only, never
the pause. Errors are classified exactly like the rating backfill (the sync owner
injects the policy through ``RatingReadHooks``):

* a client error, an unreadable answer or a 403 on one activity skips only that
  activity (``on_skip``);
* a rate limit, a rejected Personal API key, a 401 on a data read or any other
  error ends the read with ``RatingReadStopped``; files already handed on stay.

``on_file`` receives the file bytes, or ``None`` when Garmin holds no FIT file for
the activity (no original upload, or a GPX/TCX upload).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any, Final

from backend.providers.garmin import ExternalCall
from backend.providers.garmin_rating_history import (
    CALL_DELAY_SECONDS,
    FAILED,
    RatingReadHooks,
    RatingReadStopped,
    ReadFailed,
    read_one,
    skips,
    stop_kind,
)

FIT_OPERATION: Final = "activity_fit"

type FileSink = Callable[[str, bytes | None], None]
type SkipSink = Callable[[str], None]


class FitTransportMissing(RuntimeError):
    """The transport client cannot download activity files (no Personal API key)."""


def collect_activity_fit_files(
    client: Any,
    activity_ids: Sequence[str],
    on_file: FileSink,
    on_skip: SkipSink,
    *,
    external_call: ExternalCall,
    hooks: RatingReadHooks,
    sleep: Callable[[float], None] = time.sleep,
    delay_seconds: float = CALL_DELAY_SECONDS,
) -> None:
    """Hand the FIT file of each activity to ``on_file``; skips go to ``on_skip``.

    Raises ``FitTransportMissing`` or ``RatingReadStopped``.
    """
    fetch = getattr(client, "download_activity_fit", None)
    if not callable(fetch):
        raise FitTransportMissing
    for position, activity_id in enumerate(activity_ids):
        if position:
            sleep(delay_seconds)
        try:
            with hooks.guard():
                data = read_one(fetch, activity_id, external_call, FIT_OPERATION)
        except ReadFailed as failed:
            if skips(failed.original, hooks):
                on_skip(activity_id)
                continue
            raise RatingReadStopped(
                stop_kind(failed.original, hooks), activity_id
            ) from None
        if data is not None and not isinstance(data, bytes | bytearray):
            # An unreadable answer is nobody's fault but this activity's.
            on_skip(activity_id)
            continue
        on_file(activity_id, None if data is None else bytes(data))


__all__ = [
    "FAILED",
    "FIT_OPERATION",
    "FitTransportMissing",
    "collect_activity_fit_files",
]
