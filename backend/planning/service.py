"""Atomic planning application operations."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from datetime import date
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


TRAINING_PLAN_STATUS_ALIASES = {
    "entwurf": "draft", "geplant": "planned", "aktiv": "active",
    "abgeschlossen": "completed", "archiviert": "archived", "abgebrochen": "cancelled",
    "pausiert": "paused",
}
TRAINING_PLAN_STATUSES = frozenset({"draft", "planned", "active", "completed", "archived", "cancelled", "paused"})


def _candidate(current: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    status = str(values.get("status") or current.get("status") or "planned").strip().casefold()
    candidate = {
        "id": current["id"],
        "name": str(values.get("name") or current.get("name") or "").strip()[:200],
        "goal": str(values.get("goal") or current.get("goal") or "").strip()[:2000],
        "start_date": str(values.get("start_date") or current.get("start_date") or "").strip(),
        "end_date": str(values.get("end_date") or current.get("end_date") or "").strip(),
        "status": TRAINING_PLAN_STATUS_ALIASES.get(status, status),
    }
    if not candidate["name"]:
        raise ValueError("Ein Trainingsplan benötigt einen Namen.")
    if candidate["status"] not in TRAINING_PLAN_STATUSES:
        raise ValueError("Ungültiger Trainingsplanstatus.")
    try:
        start, end = date.fromisoformat(candidate["start_date"]), date.fromisoformat(candidate["end_date"])
    except ValueError as exc:
        raise ValueError("Start- und Enddatum müssen das Format JJJJ-MM-TT haben.") from exc
    if start > end:
        raise ValueError("Das Startdatum darf nicht nach dem Enddatum liegen.")
    return candidate


def update_plan_metadata(
    plan_id: str,
    values: Any,
    *,
    transaction: Callable[[], AbstractContextManager[Any]],
    repository: Any,
    record_change: Callable[..., Any],
    bump_revision: Callable[[Any], None],
    now: Callable[[], str],
) -> dict[str, Any]:
    """Update or remove plan metadata atomically in the caller-supplied store."""
    if not isinstance(values, dict):
        raise ValueError("Der Trainingsplan muss als Objekt gesendet werden.")
    action = str(values.get("action") or "update").strip().casefold()
    with transaction() as db:
        current = repository.get(db, plan_id)
        if not current:
            raise LookupError("Trainingsplan nicht gefunden.")
        if action == "delete":
            repository.delete(db, plan_id)
            record_change(db, "training_plan", plan_id, "delete", current, None)
            bump_revision(db)
            return {"status": "deleted", "plan_id": plan_id, "plan": None}
        if action != "update":
            raise ValueError("Unbekannte Aktion für den Trainingsplan.")
        candidate = _candidate(current, values)
        updated_at = now()
        repository.update(db, plan_id, candidate["name"], candidate["goal"], candidate["start_date"], candidate["end_date"], candidate["status"], updated_at)
        updated = {**current, **candidate, "updated_at": updated_at}
        record_change(db, "training_plan", plan_id, "update", current, updated)
        bump_revision(db)
        return {"status": "updated", "plan_id": plan_id, "plan": updated}
