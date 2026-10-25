"""Seed and read the retired ``activity_detail:<sha>`` kv records, as released builds wrote them."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.activities.workout_profile import recorded_profile


def key(activity_id: str) -> str:
    return f"activity_detail:{hashlib.sha256(activity_id.encode()).hexdigest()}"


def save_in(db: Any, activity_id: str, value: dict[str, Any]) -> None:
    value = {
        **value,
        "calendar_profile": recorded_profile(value.get("activity") or {}),
    }
    db.execute(
        "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
        "updated_at=excluded.updated_at",
        (
            key(activity_id),
            json.dumps(value, ensure_ascii=False, allow_nan=False),
            value["observed_at"],
        ),
    )


def save(manager: Any, activity_id: str, value: dict[str, Any]) -> None:
    with manager.unit_of_work() as db:
        save_in(db, activity_id, value)


def get(manager: Any, activity_id: str) -> dict[str, Any] | None:
    with manager.reader() as db:
        row = db.execute(
            "SELECT value FROM kv WHERE key=?", (key(activity_id),)
        ).fetchone()
    return None if row is None else json.loads(row["value"])


def calendar_profiles(manager: Any) -> dict[str, dict[str, Any]]:
    with manager.reader() as db:
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


def analysis_summaries(manager: Any) -> list[dict[str, Any]]:
    with manager.reader() as db:
        rows = db.execute(
            "SELECT json_extract(value, '$.activity_id') AS id, "
            "json_extract(value, '$.summary_sha256') AS fingerprint, "
            "json_extract(value, '$.observed_at') AS observed_at, "
            "json_extract(value, '$.session_analysis.aerobic') AS aerobic, "
            "json_extract(value, '$.session_analysis.power_profile') AS power_profile, "
            "json_extract(value, '$.session_analysis.running_profile') AS running_profile, "
            "json_extract(value, '$.target_snapshot') AS targets, "
            "json_extract(value, '$.session_analysis.interval_quality') AS interval_quality "
            "FROM kv WHERE key LIKE 'activity_detail:%' ORDER BY updated_at DESC LIMIT 100"
        ).fetchall()

    def load(raw: str | None) -> Any:
        return json.loads(raw) if raw else None

    return [
        {
            "activity_id": row["id"],
            "summary_sha256": row["fingerprint"],
            "observed_at": row["observed_at"],
            "aerobic": json.loads(row["aerobic"]),
            "power_profile": load(row["power_profile"]),
            "running_profile": load(row["running_profile"]),
            "target_snapshot": load(row["targets"]),
            "interval_quality": load(row["interval_quality"]),
        }
        for row in rows
        if row["aerobic"]
    ]
