"""Keys and purge-state helpers of the retired Intervals.icu ingest.

Intervals.icu is output only and is not read any more. The purge of the stored
Intervals.icu data (#1728) sets the retired switch key to "0", records its
completion and writes a marker file; nothing else reads the switch.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from backend.db.repositories import KeyValueRepository

INGEST_ENABLED_KEY: Final = "intervals_ingest_enabled"
# The completion marker of the Intervals.icu ingest purge (#1728).
PURGE_STATE_KEY: Final = "intervals_purge_state"
PURGE_VERSION: Final = 1
PURGE_DONE: Final = "done"
# Written beside the database after the purge: a restored pre-purge database
# has no marker of its own, so the file keeps the purge from running again.
PURGE_MARKER_FILE: Final = f"intervals-purge-v{PURGE_VERSION}.done"


def purge_marker_exists(data_dir: Path) -> bool:
    """Whether the data directory holds the marker file of a completed purge."""
    return (data_dir / PURGE_MARKER_FILE).is_file()


def purge_state_value(raw: object) -> dict[str, Any]:
    """Decode a stored purge state; a missing or corrupt value reads as empty."""
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        state = json.loads(raw)
    except ValueError:
        return {}
    return state if isinstance(state, dict) else {}


def purge_state(key_values: KeyValueRepository, db: Any) -> dict[str, Any]:
    """Return the stored purge state; a missing or corrupt record reads as empty."""
    return purge_state_value(key_values.get(db, PURGE_STATE_KEY))


def purge_done(state: Mapping[str, Any]) -> bool:
    """Whether a purge state records a completed purge of this version or later."""
    version = state.get("version")
    return (
        state.get("status") == PURGE_DONE
        and isinstance(version, int)
        and version >= PURGE_VERSION
    )
