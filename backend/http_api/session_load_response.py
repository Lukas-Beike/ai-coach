"""Best-effort session-RPE load for a committed feedback save or undo response."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

_LOGGER = logging.getLogger(__name__)


def with_session_load(
    result: dict[str, Any],
    session_rpe_load: Callable[[str], Any] | None,
    activity_id: str,
) -> dict[str, Any]:
    """Add ``session_rpe_load`` to a committed result; omit it if the read fails.

    The change is already committed, so a failed read must not turn the response
    into an error. The client refetches the detail when the key is missing.
    """
    if session_rpe_load is None:
        return result
    try:
        return {**result, "session_rpe_load": session_rpe_load(activity_id)}
    except Exception as exc:  # noqa: BLE001 - the committed change stands
        _LOGGER.warning(
            "Session load could not be read after a feedback change",
            extra={
                "event": "session_load_read_failed",
                "error_class": type(exc).__name__,
            },
        )
        return result
