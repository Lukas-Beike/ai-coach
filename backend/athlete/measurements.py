"""Validation of nonnegative recorded athlete measurements."""

import math
from typing import Any


def number(value: Any) -> float | None:
    if type(value) not in {float, int} or not math.isfinite(value) or value < 0:
        return None
    return float(value)
