"""Durable activity detail cache, independent of provider summary refreshes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from backend.activities.detail_projection import detailed_activity
from backend.activities.workout_profile import recorded_profile
from backend.providers.intervals_performance_fields import (
    HEART_RATE_ZONE_TIMES,
    ZONE_TIMES,
)

# A separate key keeps failures out of the `activity_detail:%` detail scans.
_FAILURE = "activity_detail_failure"


def summary_fingerprint(activity: dict[str, Any]) -> str:
    summary = detailed_activity(activity)
    # Recorded zone times were added to the projection later; excluding them
    # keeps fingerprints of already stored detail records valid.
    for key in ("streams", "laps", HEART_RATE_ZONE_TIMES, ZONE_TIMES):
        summary.pop(key, None)
    return hashlib.sha256(
        json.dumps(summary, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


class ActivityDetailStore:
    """Own atomic storage of one bounded, sanitized activity detail record."""

    def __init__(self, database_manager: Any):
        self._database_manager = database_manager

    @staticmethod
    def _key(activity_id: str, prefix: str = "activity_detail") -> str:
        digest = hashlib.sha256(activity_id.encode()).hexdigest()
        return f"{prefix}:{digest}"

    def get(self, activity_id: str) -> dict[str, Any] | None:
        with self._database_manager.reader() as db:
            row = db.execute(
                "SELECT value FROM kv WHERE key=?", (self._key(activity_id),)
            ).fetchone()
        if row is None:
            return None
        value = json.loads(row["value"])
        return value if isinstance(value, dict) else None

    def save(self, activity_id: str, value: dict[str, Any]) -> None:
        value = {
            **value,
            "calendar_profile": recorded_profile(value.get("activity") or {}),
        }
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False)
        with self._database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (self._key(activity_id), payload, value["observed_at"]),
            )
            db.execute(
                "DELETE FROM kv WHERE key=?", (self._key(activity_id, _FAILURE),)
            )

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
                (self._key(activity_id, _FAILURE), payload, observed_at),
            )

    def failures(self, activity_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        """Return the recorded load failure per activity id."""
        keys = {self._key(item, _FAILURE): item for item in set(activity_ids)}
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

    def calendar_profiles(self) -> dict[str, dict[str, Any]]:
        with self._database_manager.reader() as db:
            rows = db.execute(
                "SELECT json_extract(value, '$.activity_id') AS id, "
                "json_extract(value, '$.summary_sha256') AS fingerprint, "
                "json_extract(value, '$.calendar_profile') AS profile "
                "FROM kv WHERE key LIKE 'activity_detail:%' "
                "ORDER BY updated_at DESC LIMIT 100"
            ).fetchall()
        return {
            row["id"]: {
                "fingerprint": row["fingerprint"],
                "profile": json.loads(row["profile"]),
            }
            for row in rows
            if row["profile"]
        }

    def analysis_summaries(self) -> list[dict[str, Any]]:
        """Read bounded scalar analyses without transferring full sensor arrays."""
        with self._database_manager.reader() as db:
            rows = db.execute(
                "SELECT json_extract(value, '$.activity_id') AS id, "
                "json_extract(value, '$.summary_sha256') AS fingerprint, "
                "json_extract(value, '$.observed_at') AS observed_at, "
                "json_extract(value, '$.session_analysis.aerobic') AS aerobic "
                ", json_extract(value, '$.session_analysis.power_profile') AS power_profile "
                ", json_extract(value, '$.session_analysis.running_profile') AS running_profile "
                ", json_extract(value, '$.target_snapshot') AS targets "
                ", json_extract(value, '$.session_analysis.interval_quality') AS interval_quality "
                "FROM kv WHERE key LIKE 'activity_detail:%' ORDER BY updated_at DESC LIMIT 100"
            ).fetchall()
        return [
            {
                "activity_id": row["id"],
                "summary_sha256": row["fingerprint"],
                "observed_at": row["observed_at"],
                "aerobic": json.loads(row["aerobic"]),
                "power_profile": json.loads(row["power_profile"])
                if row["power_profile"]
                else None,
                "running_profile": json.loads(row["running_profile"])
                if row["running_profile"]
                else None,
                "target_snapshot": json.loads(row["targets"])
                if row["targets"]
                else None,
                "interval_quality": json.loads(row["interval_quality"])
                if row["interval_quality"]
                else None,
            }
            for row in rows
            if row["aerobic"]
        ]
