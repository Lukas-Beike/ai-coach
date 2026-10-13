"""Comma decimal text read the same way by the canonical mappers and legacy readers.

Some providers send numbers as text with a comma decimal mark, such as ``"80,4"``.
A comma followed by exactly three digits after one to three leading digits, such as
``"1,200"`` or ``"-12,345"``, could instead be grouped thousands. That text is
ambiguous, so it is rejected rather than read as a small decimal. A leading zero,
as in ``"0,500"``, cannot start a grouped number and stays a decimal.
"""

from __future__ import annotations

import math
import re
from typing import Final

_GROUPED_THOUSANDS: Final = re.compile(r"[+-]?[1-9]\d{0,2},\d{3}", re.ASCII)


def is_grouped_thousands(text: str) -> bool:
    """Return whether stripped ``text`` could be a number with grouped thousands."""
    return _GROUPED_THOUSANDS.fullmatch(text.strip()) is not None


def comma_decimal_float(value: object) -> float:
    """Return ``float`` of ``value``'s text with a comma read as the decimal mark.

    Raises ``ValueError`` for text that ``float`` rejects after the swap and for
    ambiguous grouped thousands, so callers keep their ``float`` error handling.
    """
    text = str(value)
    if is_grouped_thousands(text):
        raise ValueError("ambiguous grouped thousands")
    return float(text.replace(",", "."))


def provider_number(value: object) -> float | int | None:
    """Return a finite provider number from ``value``, or None.

    Comma decimal text is read as by ``comma_decimal_float``. Whole numbers become
    ``int`` and other values are rounded to two decimals.
    """
    try:
        number = comma_decimal_float(value)
    except TypeError, ValueError:
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)
