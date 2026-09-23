"""Shared encoding and bounds for HTTP API page cursors."""

from __future__ import annotations

import base64
import json
from typing import Any

API_PAGE_DEFAULT = 100
API_PAGE_MAX = 250


def api_page_limit(
    raw: Any, default: int = API_PAGE_DEFAULT, maximum: int = API_PAGE_MAX
) -> int:
    try:
        return max(1, min(int(raw), maximum))
    except (TypeError, ValueError):
        return default


def encode_page_cursor(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_page_cursor(value: Any) -> Any | None:
    if not value:
        return None
    try:
        padding = "=" * (-len(str(value)) % 4)
        return json.loads(base64.urlsafe_b64decode(f"{value}{padding}"))
    except (TypeError, ValueError):
        return None
