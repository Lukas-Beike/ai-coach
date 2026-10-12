"""Read-only translation of stored equipment and competition sport tokens.

Equipment and competitions keep their sport tokens exactly as saved. These
tables give the canonical ``Sport`` for read-side decisions and never rewrite a
stored value. Lookups are exact-token only: a token that is not listed returns
``None`` (unknown), never a substring or fuzzy guess.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from backend.canonical.vocabulary import Sport

# Every token accepted by the equipment sport validator.
EQUIPMENT_SPORT_TOKENS: Final[Mapping[str, Sport]] = {
    "Ride": Sport.RIDE,
    "VirtualRide": Sport.RIDE,
    "Run": Sport.RUN,
    "Swim": Sport.SWIM,
    "WeightTraining": Sport.STRENGTH,
    "Other": Sport.OTHER,
}

# Every canonical competition token produced by the competition sport aliases.
COMPETITION_SPORT_TOKENS: Final[Mapping[str, Sport]] = {
    "Ride": Sport.RIDE,
    "VirtualRide": Sport.RIDE,
    "Run": Sport.RUN,
    "WeightTraining": Sport.STRENGTH,
}


def _lookup(table: Mapping[str, Sport], token: Any) -> Sport | None:
    if not isinstance(token, str):
        return None
    return table.get(token)


def equipment_canonical_sport(record: Mapping[str, Any]) -> Sport | None:
    """Return the canonical sport of a stored equipment record, or None if unknown."""
    return _lookup(EQUIPMENT_SPORT_TOKENS, record.get("sport"))


def competition_canonical_sport(row: Mapping[str, Any]) -> Sport | None:
    """Return the canonical sport of a stored competition row, or None if unknown."""
    return _lookup(COMPETITION_SPORT_TOKENS, row.get("sport"))
