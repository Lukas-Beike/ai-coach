"""Stable contracts shared by nutrition use cases and synchronization."""

from __future__ import annotations

import hashlib
import json
from typing import Any

NUTRITION_APPROVAL_FIELDS = (
    "date",
    "revision",
    "total_kcal",
    "total_carbs_g",
    "total_protein_g",
    "total_fat_g",
    "entry_count",
)


def nutrition_approval_item(snapshot: dict[str, Any]) -> dict[str, Any]:
    item = {
        "date": str(snapshot["date"]),
        "revision": int(snapshot.get("sync_revision") or 0),
        "total_kcal": int(snapshot.get("total_kcal") or 0),
        "total_carbs_g": snapshot.get("total_carbs_g"),
        "total_protein_g": snapshot.get("total_protein_g"),
        "total_fat_g": snapshot.get("total_fat_g"),
        "entry_count": int(snapshot.get("entry_count") or 0),
    }
    digest_values = {
        key: item[key] for key in NUTRITION_APPROVAL_FIELDS if key != "revision"
    }
    serialized = json.dumps(
        digest_values, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return {**item, "sha256": hashlib.sha256(serialized).hexdigest()}


def nutrition_approval_item_matches(
    expected: dict[str, Any], actual: dict[str, Any]
) -> bool:
    if expected == actual:
        return True
    return (
        expected.get("revision") == 0
        and actual.get("revision") == 1
        and expected.get("entry_count") == actual.get("entry_count") == 0
        and expected.get("sha256") == actual.get("sha256")
    )
