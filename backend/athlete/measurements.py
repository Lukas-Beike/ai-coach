"""Validation of recorded athlete measurements and other plain numbers."""

import math
from typing import Any, TypeGuard


def number(value: Any) -> float | None:
    if type(value) not in {float, int} or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def finite_float(value: Any) -> float | None:
    """A finite ``int`` or ``float`` (never ``bool`` or text) as ``float``."""
    return (
        float(value) if type(value) in {int, float} and math.isfinite(value) else None
    )


def is_finite_number(value: Any) -> TypeGuard[float | int]:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def is_positive_number(value: Any) -> bool:
    return is_finite_number(value) and value > 0
