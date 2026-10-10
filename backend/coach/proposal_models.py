"""Coach proposal values and safe database projections."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

COACH_ACTION_TYPES = {
    "undo_change",
    "delete_duplicate_intervals_activity",
    "remote_coach_write",
    "local_coach_write",
}


REMOTE_COACH_WRITE_TOOLS = frozenset(
    {
        "start_intervals_plan_sync",
        "sync_competitions",
        "delete_duplicate_intervals_activity",
        "sync_nutrition",
        "resolve_training_sync_conflict",
        "apply_adaptive_replan",
    }
)


LOCAL_COACH_WRITE_TOOLS = frozenset(
    {"save_nutrition_template", "save_nutrition_product"}
)


COACH_ACTION_TTL_SECONDS = 600


def _preview_nutrient(value: Any) -> str:
    return str(value) if value is not None else "unbekannt"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def coach_action_hash(payload: Any) -> str:
    """Return the canonical SHA-256 identity used for Coach action payloads."""
    serialized = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def coach_action_view(row: dict[str, Any]) -> dict[str, Any]:
    """Expose proposal metadata without returning its private action payload."""
    return {
        "id": row["id"],
        "action_type": row["action_type"],
        "target_system": row["target_system"],
        "object_ids": json.loads(row["object_ids"]),
        "diff": json.loads(row["diff"]),
        "payload_hash": row["payload_hash"],
        "expires_at": row["expires_at"],
        "status": row["status"],
    }


def prune_expired_coach_proposals(db: Any, now: float) -> int:
    """Delete expired authorization artifacts, leaving durable plan drafts alone."""
    return db.execute(
        "DELETE FROM coach_action_proposals WHERE expires_at<=?", (now,)
    ).rowcount
