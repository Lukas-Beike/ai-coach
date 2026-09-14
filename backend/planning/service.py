"""Atomic planning application operations."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any


def _member_dates(db: Any, plan_id: str) -> list[str]:
    rows = db.execute(
        "SELECT payload FROM planned_units "
        "WHERE json_extract(payload, '$.plan_id') = ? "
        "AND COALESCE(json_extract(payload, '$.archived'), 0) = 0 "
        "AND COALESCE(json_extract(payload, '$.local_deleted'), 0) = 0",
        (plan_id,),
    ).fetchall()
    dates: list[str] = []
    for row in rows:
        try:
            payload = json.loads(row["payload"] or "{}")
        except (TypeError, ValueError, KeyError):
            payload = {}
        if isinstance(payload, dict) and str(payload.get("date") or "")[:10]:
            dates.append(str(payload["date"])[:10])
    return dates


def update_plan_bounds(
    db: Any,
    plan_ids: Iterable[str],
    *,
    get_plan: Callable[[Any, str], dict[str, Any] | None],
    update_plan: Callable[..., Any],
    record_change: Callable[..., Any],
    now: Callable[[], str],
) -> None:
    """Update all affected plan bounds inside the caller's transaction."""
    for plan_id in sorted(set(plan_ids)):
        plan = get_plan(db, plan_id)
        member_dates = _member_dates(db, plan_id)
        if not plan or not member_dates:
            continue
        start, end = min(member_dates), max(member_dates)
        if plan.get("start_date") == start and plan.get("end_date") == end:
            continue
        updated_at = now()
        updated_plan = {**plan, "start_date": start, "end_date": end, "updated_at": updated_at}
        update_plan(
            db, plan_id, updated_plan["name"], updated_plan.get("goal") or "",
            start, end, updated_plan.get("status") or "planned", updated_at,
        )
        record_change(db, "training_plan", plan_id, "update", plan, updated_plan, source="coach_apply")
