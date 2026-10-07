"""Tolerant detection of calendar constraint markers such as [NO_TRAINING]."""

from __future__ import annotations

import re
from typing import Any


def has_marker(text: Any, marker: str) -> bool:
    """Match [NAME] ignoring case and tolerating spaces, hyphens or underscores."""
    name = marker.strip("[]")
    words = [re.escape(part) for part in re.split(r"[_\s\-]+", name) if part]
    pattern = r"[\[\(]\s*" + r"[\s_\-]*".join(words) + r"\s*[\]\)]"
    return re.search(pattern, str(text or ""), re.IGNORECASE) is not None
