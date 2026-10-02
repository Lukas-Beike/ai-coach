"""Durable activity detail cache, independent of provider summary refreshes."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.activities.detail_projection import detailed_activity
from backend.performance.workout_profile import recorded_profile


def summary_fingerprint(activity: dict[str, Any]) -> str:
    summary = detailed_activity(activity)
    summary.pop("streams", None)
    summary.pop("laps", None)
    return hashlib.sha256(
        json.dumps(summary, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


class ActivityDetailStore:
    """Own atomic storage of one bounded, sanitized activity detail record."""

    def __init__(self, database_manager: Any):
        self._database_manager = database_manager

    @staticmethod
    def _key(activity_id: str) -> str:
        digest = hashlib.sha256(activity_id.encode()).hexdigest()
        return f"activity_detail:{digest}"

    def get(self, activity_id: str) -> dict[str, Any] | None:
        with self._database_manager.unit_of_work() as db:
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

    def calendar_profiles(self) -> dict[str, dict[str, Any]]:
        with self._database_manager.unit_of_work() as db:
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
        with self._database_manager.unit_of_work() as db:
            rows = db.execute(
                "SELECT json_extract(value, '$.activity_id') AS id, "
                "json_extract(value, '$.summary_sha256') AS fingerprint, "
                "json_extract(value, '$.observed_at') AS observed_at, "
                "json_extract(value, '$.session_analysis.aerobic') AS aerobic "
                ", json_extract(value, '$.session_analysis.power_profile') AS power_profile "
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
