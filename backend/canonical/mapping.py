"""Shared result and issue types for pure provider mappers.

Mappers never raise on malformed provider input. Anything that cannot be mapped
is reported as a MappingIssue that names the record, the field and a reason.
Issues carry identifiers and field names only, never the raw provider value, so
they can be logged or shown without repeating provider content.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from backend.canonical.decimal_text import is_grouped_thousands
from backend.canonical.validation import (
    optional_text,
    require_instance,
    require_text,
)

MAX_ISSUE_TEXT_LENGTH: Final = 200
MAX_NUMBER_TEXT_LENGTH: Final = 64
# Plain decimal notation with a dot separator. Restricting the characters before
# float() rejects Python-only spellings such as underscores, non-ASCII digits,
# "nan"/"inf" words and locale comma decimals.
_DECIMAL_CHARACTERS: Final = frozenset("0123456789+-.eE")


class IssueReason(StrEnum):
    MISSING = "missing"
    INVALID_TYPE = "invalid_type"
    INVALID_NUMBER = "invalid_number"
    OUT_OF_RANGE = "out_of_range"
    UNKNOWN_VALUE = "unknown_value"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class MappingIssue:
    """A bounded, value-free note that one provider field was not mapped."""

    record_ref: str | None
    field: str
    reason: IssueReason

    def __post_init__(self) -> None:
        optional_text(self.record_ref, "record_ref", max_length=MAX_ISSUE_TEXT_LENGTH)
        require_text(self.field, "field", max_length=MAX_ISSUE_TEXT_LENGTH)
        require_instance(self.reason, IssueReason, "reason")


@dataclass(frozen=True, slots=True)
class MappingResult[T]:
    """Records that mapped cleanly, plus the issues met while mapping."""

    records: tuple[T, ...] = ()
    issues: tuple[MappingIssue, ...] = ()

    def __post_init__(self) -> None:
        require_instance(self.records, tuple, "records")
        require_instance(self.issues, tuple, "issues")
        for issue in self.issues:
            require_instance(issue, MappingIssue, "issues")


def coerce_number(value: object) -> float | None:
    """Return a finite float for a number or dot-decimal text, otherwise None.

    Booleans, comma decimals, NaN, infinities, overflowing integers, other types
    and text longer than ``MAX_NUMBER_TEXT_LENGTH`` yield None. Never raises.
    """
    if isinstance(value, str):
        text = value.strip()
        if len(text) > MAX_NUMBER_TEXT_LENGTH or not set(text) <= _DECIMAL_CHARACTERS:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    elif isinstance(value, bool) or not isinstance(value, int | float):
        return None
    else:
        try:
            number = float(value)
        except OverflowError:
            return None
    return number if math.isfinite(number) else None


def coerce_comma_decimal_number(value: object) -> float | None:
    """Return ``coerce_number`` of a value whose text may use a comma as decimal mark.

    Text has every comma read as a dot before the ``coerce_number`` rules apply, so
    ``"80,4"`` is 80.4 and ``"1,2,3"`` is still rejected. Ambiguous grouped
    thousands such as ``"1,200"`` yield None, as in the provider readers (see
    ``backend.canonical.decimal_text``). Numbers, booleans and every other type
    follow ``coerce_number`` unchanged. Only providers whose readers accept comma
    decimals should use it; ``coerce_number`` stays strict for the rest.
    """
    if isinstance(value, str):
        if is_grouped_thousands(value):
            return None
        return coerce_number(value.replace(",", "."))
    return coerce_number(value)


def selected(item: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    """Return the non-null ``fields`` of a mapping, or an empty dict for non-mappings."""
    if not isinstance(item, dict):
        return {}
    return {key: item[key] for key in fields if key in item and item[key] is not None}
