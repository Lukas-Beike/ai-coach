"""Reusable Coach turn primitives shared by HTTP and background execution."""

from __future__ import annotations

import json
from typing import Any


def command_receipt(value: Any) -> dict[str, Any]:
    """Decode a persisted receipt without allowing malformed state to escape."""
    try:
        receipt = json.loads(value or "{}") if not isinstance(value, dict) else dict(value)
    except (TypeError, ValueError):
        receipt = {}
    return receipt if isinstance(receipt, dict) else {}
