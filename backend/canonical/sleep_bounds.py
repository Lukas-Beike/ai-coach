"""Sleep start and end instants in stored provider rows.

One definition for the canonical sleep-period mappers and the sleep-regularity
method (``sleep-regularity-v1``), so both read the same intervals: the same field
aliases in the same precedence, the same timestamp parsing and the same walk over
nested objects and lists.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from backend.canonical.decimal_text import comma_decimal_float

SLEEP_START_FIELDS: Final = (
    "sleepStartTimestampGMT",
    "sleepStartTimestamp",
    "sleep_start_at",
    "sleepStart",
    "sleep_start",
    "onset_at",
)
SLEEP_END_FIELDS: Final = (
    "sleepEndTimestampGMT",
    "sleepEndTimestamp",
    "sleep_end_at",
    "sleepEnd",
    "sleep_end",
    "wake_at",
)
MAX_SLEEP_INTERVAL: Final = timedelta(hours=24)
# The walk limits of sleep-regularity-v1.
_VISIT_LIMIT: Final = 2000
_LIST_LIMIT: Final = 500
_EPOCH_MILLISECONDS_ABOVE: Final = 10_000_000_000


def utc_timestamp(value: Any) -> datetime | None:
    """Read epoch seconds or milliseconds or ISO text as a UTC instant.

    Naive ISO text is read as UTC. Anything else, or an instant outside the
    datetime range, is None.
    """
    try:
        number = comma_decimal_float(value)
    except TypeError, ValueError:
        number = None
    if number is not None and math.isfinite(number):
        try:
            seconds = number / 1000 if number > _EPOCH_MILLISECONDS_ABOVE else number
            return datetime.fromtimestamp(seconds, UTC)
        except OSError, OverflowError, ValueError:
            return None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    try:
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)
    except OverflowError:
        # An offset at the edge of the datetime range has no UTC instant.
        return None


@dataclass(frozen=True, slots=True)
class SleepInterval:
    """A valid interval found in a row, with the fields it was read from.

    ``record`` is the object that holds both fields; ``depth`` is 0 for the row
    itself and grows with each nested object or list.
    """

    start: datetime
    end: datetime
    start_field: str
    end_field: str
    record: Mapping[str, Any]
    depth: int


def _first_field(record: Mapping[str, Any], fields: tuple[str, ...]) -> str | None:
    return next((key for key in fields if record.get(key) not in (None, "")), None)


def sleep_intervals(payload: Any) -> Iterator[SleepInterval]:
    """Yield the valid sleep intervals of a stored payload, in walk order.

    Every object with a start and an end field yields one interval when the end
    is after the start and at most 24 hours later. The walk visits at most 2000
    nodes and the first 500 items of each list, as sleep-regularity-v1 does.
    """
    pending: list[tuple[Any, int]] = [(payload, 0)]
    visited = 0
    while pending and visited < _VISIT_LIMIT:
        current, depth = pending.pop()
        visited += 1
        if isinstance(current, Mapping):
            start_field = _first_field(current, SLEEP_START_FIELDS)
            end_field = _first_field(current, SLEEP_END_FIELDS)
            if start_field is not None and end_field is not None:
                start = utc_timestamp(current[start_field])
                end = utc_timestamp(current[end_field])
                if (
                    start is not None
                    and end is not None
                    and timedelta(0) < end - start <= MAX_SLEEP_INTERVAL
                ):
                    yield SleepInterval(
                        start, end, start_field, end_field, current, depth
                    )
            pending.extend(
                (value, depth + 1)
                for value in current.values()
                if isinstance(value, (dict, list))
            )
        elif isinstance(current, list):
            pending.extend((value, depth + 1) for value in current[:_LIST_LIMIT])


def bounds_method(start_field: str, end_field: str) -> str:
    """Return the stored identifier of a field pair, such as ``sleepstarttimestampgmt.sleependtimestampgmt``."""
    return f"{start_field.lower()}.{end_field.lower()}"


_FIELD_BY_LOWER: Final = {
    field.lower(): field for field in (*SLEEP_START_FIELDS, *SLEEP_END_FIELDS)
}


def bounds_fields(method: str) -> tuple[str, str] | None:
    """Return the field pair a ``bounds_method`` identifier names, or None."""
    start, _, end = method.partition(".")
    start_field = _FIELD_BY_LOWER.get(start)
    end_field = _FIELD_BY_LOWER.get(end)
    if start_field is None or end_field is None:
        return None
    return start_field, end_field
