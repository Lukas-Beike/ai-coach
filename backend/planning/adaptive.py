"""Transaction-scoped application of adaptive plan changes."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AdaptiveDependencies:
    transaction: Callable[[], AbstractContextManager[Any]]
    repository: Any
    apply_changes: Callable[[Any, Any, str], tuple[int, list[dict[str, Any]]]]
    fill_checkins: Callable[[Any, dict[str, Any], str], int]
    bump_revision: Callable[[Any], None]
    now: Callable[[], str]


def apply_adaptive_changes(adjustment_id: str, dependencies: AdaptiveDependencies) -> dict[str, Any]:
    """Apply one preview atomically; the caller handles any remote side effect."""
    with dependencies.transaction() as db:
        row = dependencies.repository.get(db, adjustment_id)
        if not row:
            raise LookupError("Plananpassung nicht gefunden.")
        if row["status"] == "applied":
            return {"status": "already_applied", "id": adjustment_id}
        if row["status"] in {"stale", "partial"}:
            return {"status": "already_" + str(row["status"]), "id": adjustment_id}
        payload = json.loads(row["payload"])
        illness_pause = payload.get("illness_pause") if isinstance(payload.get("illness_pause"), dict) else None
        active_illness_pause = illness_pause if illness_pause and not illness_pause.get("approved") else None
        now = dependencies.now()
        updated, stale = dependencies.apply_changes(db, payload.get("changes"), now)
        updated_checkins = 0
        if updated:
            dependencies.bump_revision(db)
        if active_illness_pause:
            updated_checkins = dependencies.fill_checkins(db, active_illness_pause, now)
            payload["illness_pause"] = {**active_illness_pause, "approved": True}
        status = "stale" if stale and not updated else "partial" if stale else "applied"
        dependencies.repository.mark_applied(
            db, adjustment_id, json.dumps(payload, ensure_ascii=False), status, now,
        )
    return {
        "status": status, "id": adjustment_id, "updated": updated,
        "updated_checkins": updated_checkins, "stale": stale,
        "illness_pause": illness_pause,
    }
