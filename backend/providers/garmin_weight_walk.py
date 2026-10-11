"""Shared walk over Garmin weight payloads.

The legacy reader in ``backend/performance/garmin_weight`` and the health mapper in
``backend/providers/garmin_health_mapping`` search the same nested weight payload
with the same limits and skip rules. They differ only in how a record's day is typed
and how its value is read, so the walk lives here and each caller supplies its own
day resolver and value reader.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Final

from backend.providers.garmin_fields import GARMIN_DATE_ALIASES

WEIGHT_SECTIONS: Final = ("weight", "weigh_ins", "weighIns")
WALK_DATE_KEYS: Final = (*GARMIN_DATE_ALIASES, "timestampGMT", "timestamp")
WEIGHT_SKIP_KEYS: Final = frozenset({"minweight", "maxweight", "weightdelta"})
BODY_FAT_SKIP_KEYS: Final = frozenset({"minbodyfat", "maxbodyfat", "bodyfatdelta"})
WALK_MAX_DEPTH: Final = 20
WALK_MAX_VISITS: Final = 2000
WALK_MAX_LIST_ITEMS: Final = 500


def alnum_key(value: object) -> str:
    """Casefolded text with only letters and digits, used to compare keys."""
    return "".join(
        character for character in str(value).casefold() if character.isalnum()
    )


def weight_payload(sections: Mapping[str, object]) -> object:
    """First truthy weight section, as the legacy ``or`` chain picks it."""
    payload: object = None
    for name in WEIGHT_SECTIONS:
        payload = sections.get(name)
        if payload:
            break
    return payload


@dataclass(frozen=True, slots=True)
class WalkedRecord[DayT]:
    """One mapping visited by the walk.

    ``day`` is the record's own day, or its nearest dated ancestor's when it has none.
    ``ordinal`` counts mappings in pre-order. ``list_index`` is the index of the
    nearest enclosing list item, or None. ``marked`` is true below a marker key.
    """

    record: Mapping[str, Any]
    day: DayT | None
    ordinal: int
    list_index: int | None
    marked: bool


def walk_records[DayT](
    payload: object,
    *,
    skip_keys: frozenset[str],
    resolve_day: Callable[[Mapping[str, Any]], DayT],
    marker_keys: frozenset[str] = frozenset(),
) -> Iterator[WalkedRecord[DayT]]:
    """Yield every mapping under ``payload`` in pre-order, within the walk limits.

    ``resolve_day`` returns a record's own day, or None to inherit the nearest dated
    ancestor's day. A child whose ``alnum_key`` is in ``skip_keys`` is not entered.
    A child under a key in ``marker_keys`` is marked. Depth, visit and list limits
    match the legacy reader, and scalar values count as visits.
    """
    yield from _Walk(skip_keys, resolve_day, marker_keys).visit(
        payload, None, 0, None, False
    )


class _Walk[DayT]:
    def __init__(
        self,
        skip_keys: frozenset[str],
        resolve_day: Callable[[Mapping[str, Any]], DayT],
        marker_keys: frozenset[str],
    ) -> None:
        self._skip_keys = skip_keys
        self._resolve_day = resolve_day
        self._marker_keys = marker_keys
        self._visits = 0
        self._ordinal = 0

    def visit(
        self,
        value: object,
        inherited: DayT | None,
        depth: int,
        list_index: int | None,
        marked: bool,
    ) -> Iterator[WalkedRecord[DayT]]:
        if depth > WALK_MAX_DEPTH or self._visits >= WALK_MAX_VISITS:
            return
        self._visits += 1
        if isinstance(value, Mapping):
            ordinal = self._ordinal
            self._ordinal += 1
            day: DayT | None = self._resolve_day(value)
            if day is None:
                day = inherited
            yield WalkedRecord(value, day, ordinal, list_index, marked)
            for key, child in value.items():
                if alnum_key(key) not in self._skip_keys:
                    yield from self.visit(
                        child,
                        day,
                        depth + 1,
                        list_index,
                        marked or key in self._marker_keys,
                    )
        elif isinstance(value, list):
            for index, item in enumerate(value[:WALK_MAX_LIST_ITEMS]):
                yield from self.visit(item, inherited, depth + 1, index, marked)
