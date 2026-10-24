"""Activity detail failure notes, prefetch floor and retired kv record scan."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from backend.activities.detail_projection import detailed_activity
from backend.providers.intervals_activity_keys import LACTATE_THRESHOLD_HR
from backend.providers.intervals_performance_fields import (
    HEART_RATE_ZONE_TIMES,
    ZONE_TIMES,
)

# A separate key keeps failures out of the `activity_detail:` record scans.
_FAILURE = "activity_detail_failure"
_RECORD_PREFIX = "activity_detail:"
PREFETCH_FLOOR_KEY = "activity_detail_prefetch_floor"


def _json_or_none(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return None


def summary_fingerprint(activity: dict[str, Any]) -> str:
    summary = detailed_activity(activity)
    # Recorded zone times and the threshold heart rate were added to the
    # projection later; excluding them keeps fingerprints of already stored
    # detail records valid.
    for key in (
        "streams",
        "laps",
        HEART_RATE_ZONE_TIMES,
        ZONE_TIMES,
        LACTATE_THRESHOLD_HR,
    ):
        summary.pop(key, None)
    return hashlib.sha256(
        json.dumps(summary, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


class ActivityDetailStore:
    """Own the detail failure notes, the prefetch floor and the retired-record scan."""

    def __init__(self, database_manager: Any):
        self._database_manager = database_manager

    @staticmethod
    def _key(activity_id: str) -> str:
        digest = hashlib.sha256(activity_id.encode()).hexdigest()
        return f"{_FAILURE}:{digest}"

    def save_failure(
        self, activity_id: str, summary_sha256: str, message: str, observed_at: str
    ) -> None:
        """Remember why the newest summary has no details; stored details stay."""
        payload = json.dumps(
            {
                "summary_sha256": summary_sha256,
                "message": message,
                "observed_at": observed_at,
            },
            ensure_ascii=False,
        )
        with self._database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (self._key(activity_id), payload, observed_at),
            )

    def clear_failure(self, activity_id: str) -> None:
        """Forget a recorded failure once the stored details match again."""
        with self._database_manager.unit_of_work() as db:
            self.clear_failure_in(db, activity_id)

    def clear_failure_in(self, db: Any, activity_id: str) -> None:
        """Forget a recorded failure inside the caller's unit of work."""
        db.execute("DELETE FROM kv WHERE key=?", (self._key(activity_id),))

    def failures(self, activity_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        """Return the recorded load failure per activity id."""
        keys = {self._key(item): item for item in set(activity_ids)}
        if not keys:
            return {}
        with self._database_manager.reader() as db:
            rows = db.execute(
                f"SELECT key, value FROM kv WHERE key IN ({','.join('?' * len(keys))})",
                tuple(keys),
            ).fetchall()
        result = {}
        for row in rows:
            value = json.loads(row["value"])
            if isinstance(value, dict):
                result[keys[row["key"]]] = value
        return result

    def prefetch_floor(self) -> str | None:
        """Start time from which every new activity is loaded automatically."""
        with self._database_manager.reader() as db:
            row = db.execute(
                "SELECT value FROM kv WHERE key=?", (PREFETCH_FLOOR_KEY,)
            ).fetchone()
        return None if row is None else str(row["value"])

    def save_prefetch_floor(self, value: str, observed_at: str) -> None:
        """Set the floor once; an existing floor is never moved."""
        with self._database_manager.unit_of_work() as db:
            db.execute(
                "INSERT OR IGNORE INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
                (PREFETCH_FLOOR_KEY, value, observed_at),
            )

    @staticmethod
    def records_after(db: Any, after_key: str, limit: int) -> list[tuple[str, Any]]:
        """Return up to ``limit`` stored detail records after a kv key, in key order.

        Only ``activity_detail:`` keys are read, never the failure notes. The prefix
        is compared exactly: LIKE would treat ``_`` as a wildcard. A value that is
        not JSON comes back as None, so the caller counts it and moves on.
        """
        rows = db.execute(
            "SELECT key, value FROM kv WHERE substr(key, 1, ?) = ? "
            "AND key > ? ORDER BY key LIMIT ?",
            (len(_RECORD_PREFIX), _RECORD_PREFIX, after_key, limit),
        ).fetchall()
        return [(row["key"], _json_or_none(row["value"])) for row in rows]
