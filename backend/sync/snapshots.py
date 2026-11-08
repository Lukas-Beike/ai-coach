"""Stored provider snapshot reads."""

from __future__ import annotations

import json
from typing import Any


def latest_snapshot(db: Any, repository: Any) -> dict[str, Any] | None:
    payload = repository.latest_payload(db)
    return json.loads(payload) if payload else None
