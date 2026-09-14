"""Transaction-scoped application of structured planning changes."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlanningChangeDependencies:
    transaction: Callable[[], AbstractContextManager[Any]]
    prepare: Callable[[dict[str, Any]], list[dict[str, Any]]]
    validate: Callable[[list[dict[str, Any]], dict[str, Any], Any, bool], int]
    derive_plan: Callable[[list[dict[str, Any]], str | None, Any], tuple[dict[str, str], set[str]]]
    apply_rows: Callable[[list[dict[str, Any]], dict[str, str], Any], list[dict[str, Any]]]
    bump_revision: Callable[[Any], None]
    update_bounds: Callable[[Any, set[str]], None]
    read_revision: Callable[[Any], int]


def apply_structured_changes(
    arguments: dict[str, Any], dependencies: PlanningChangeDependencies, *,
    require_revision: bool = False, authorized_plan_id: str | None = None,
) -> dict[str, Any]:
    """Validate and apply a structured change set in one caller-visible transaction."""
    with dependencies.transaction() as db:
        changes = dependencies.prepare(arguments)
        current_revision = dependencies.validate(changes, arguments, db, require_revision)
        derived_plan, plans_needing_bounds = dependencies.derive_plan(changes, authorized_plan_id, db)
        applied = dependencies.apply_rows(changes, derived_plan, db)
        dependencies.bump_revision(db)
        dependencies.update_bounds(db, plans_needing_bounds)
        revision = dependencies.read_revision(db)
    result_changes = [{"local_id": item.get("local_id"), "status": item.get("status")} for item in applied]
    return {
        "ok": True,
        "status": "applied",
        "planning_revision": revision or current_revision,
        "changes": result_changes,
        "library_entry_ids": list(dict.fromkeys(item["local_id"] for item in result_changes if item.get("local_id"))),
    }
