"""Immutable calendar dates for athlete and provider boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BASIC_DATE_PATTERN = re.compile(r"^\d{8}$")
_DATETIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}[T ].+$")


class LocalDateError(ValueError):
    """Raised when a value is not a supported calendar date."""


def iso_date_prefix(value: Any) -> str:
    """Normalize ISO date or timestamp values to their calendar date.

    Invalid legacy values retain their previous ten-character projection.
    """
    try:
        return LocalDate.parse(value).isoformat()
    except TypeError, ValueError:
        return str(value or "")[:10]


@dataclass(frozen=True, slots=True)
class LocalDate:
    """A validated calendar date, without timezone or persistence policy."""

    value: date

    @classmethod
    def parse(
        cls,
        value: Any,
        *,
        allow_datetime: bool = True,
        allow_basic: bool = False,
    ) -> LocalDate:
        if isinstance(value, cls):
            return value
        if isinstance(value, datetime):
            return cls(value.date())
        if isinstance(value, date):
            return cls(value)
        if not isinstance(value, str):
            raise LocalDateError("expected an ISO calendar date")
        text = value.strip()
        if _DATE_PATTERN.fullmatch(text):
            return cls(date.fromisoformat(text))
        if allow_basic and _BASIC_DATE_PATTERN.fullmatch(text):
            return cls(date.fromisoformat(text))
        if not allow_datetime or not _DATETIME_PATTERN.fullmatch(text):
            raise LocalDateError("expected an ISO calendar date or datetime")
        try:
            return cls(datetime.fromisoformat(text).date())
        except ValueError as exc:
            raise LocalDateError(
                "expected a valid ISO calendar date or datetime"
            ) from exc

    def to_date(self) -> date:
        return self.value

    def isoformat(self) -> str:
        return self.value.isoformat()

    def __str__(self) -> str:
        return self.isoformat()
