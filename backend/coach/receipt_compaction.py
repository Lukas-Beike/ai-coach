"""Reduce finished Coach receipts to the fields later turns and the UI read.

While a turn is open its receipt keeps every full tool result, because tool
replay and the next model round need them. A finished receipt keeps only
statuses, identifiers, proposed actions and the undo references.
"""

from __future__ import annotations

from typing import Any

_SCALAR_TEXT_LIMIT = 500
_ID_LIST_LIMIT = 50
_LOOKUP_GROUP_LIMIT = 24
_LOOKUP_ITEMS_PER_GROUP = 3
_KEPT_OBJECTS = frozenset({"proposed_action"})


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _clip(value: Any) -> Any:
    return value[:_SCALAR_TEXT_LIMIT] if isinstance(value, str) else value


def _is_id_key(key: str) -> bool:
    return key in {"id", "ids"} or key.endswith(("_id", "_ids"))


def _lookup_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict) or not isinstance(item.get("id"), str):
        return None
    return {"id": item["id"][:80], "name": str(item.get("name") or "")[:120]}


def _lookup_group(group: Any) -> dict[str, Any]:
    if not isinstance(group, dict):
        return {}
    compact: dict[str, Any] = {
        key: _clip(group[key])
        for key in ("ok", "query", "local")
        if key in group and _scalar(group[key])
    }
    for key in ("local_products", "foods"):
        items = group.get(key)
        if isinstance(items, list):
            compact[key] = [
                kept
                for kept in map(_lookup_item, items[:_LOOKUP_ITEMS_PER_GROUP])
                if kept
            ]
    return compact


def _compact_lookup(result: dict[str, Any]) -> dict[str, Any]:
    """Keep the foods a lookup found; the next turn reuses them."""
    groups = result.get("results")
    if isinstance(groups, list):
        return {"results": [_lookup_group(g) for g in groups[:_LOOKUP_GROUP_LIMIT]]}
    return _lookup_group(result)


def compact_tool_result(tool: Any, result: Any) -> Any:
    """Keep ok, status, ids, ``proposed_action`` and short scalar fields."""
    if not isinstance(result, dict):
        return result if _scalar(result) else None
    compact: dict[str, Any] = {}
    for key, value in result.items():
        name = str(key)
        if _scalar(value):
            compact[name] = _clip(value)
        elif name in _KEPT_OBJECTS and isinstance(value, dict):
            compact[name] = value
        elif _is_id_key(name) and isinstance(value, list):
            compact[name] = [
                _clip(item) for item in value[:_ID_LIST_LIMIT] if _scalar(item)
            ]
        elif name == "job" and isinstance(value, dict):
            compact[name] = {k: _clip(v) for k, v in value.items() if _scalar(v)}
    if tool == "lookup_food":
        compact.update(_compact_lookup(result))
    return compact


def compact_command_receipts(command_receipts: Any) -> Any:
    """Return the step list with every tool result reduced; other keys stay."""
    if not isinstance(command_receipts, list):
        return command_receipts
    return [
        {**step, "result": compact_tool_result(step.get("tool"), step.get("result"))}
        if isinstance(step, dict) and "result" in step
        else step
        for step in command_receipts
    ]


def compact_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Copy a receipt with its step results reduced (the input is unchanged)."""
    if "command_receipts" not in receipt:
        return receipt
    return {
        **receipt,
        "command_receipts": compact_command_receipts(receipt["command_receipts"]),
    }
