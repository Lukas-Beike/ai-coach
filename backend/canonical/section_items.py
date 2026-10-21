"""Keyed items of a sectioned provider payload, in the form the raw layer stores.

A provider payload such as the Garmin collection is a mapping from section name
to a record or a list of records. The raw layer keeps one row per list element,
so a sync rewrites only the elements that changed. This module is pure and
stdlib-only: it names the identity of an element, the day it belongs to, and how
a section is split into and assembled from its elements. The merge of bounded
windows (``merge_records``) and the storage keys share one identity rule.

An element's identity is its first non-empty ``id``, ``activityId``,
``gearUUID``, ``calendarDate``, ``summaryDate``, ``date`` or ``startTime``. An element
without one is keyed by a digest of its content. Elements of a list that share a
key get an ordinal suffix, so a section replaced as a whole stays lossless.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

IDENTITY_KEYS: Final = (
    "id",
    "activityId",
    "gearUUID",
    "calendarDate",
    "summaryDate",
    "date",
    "startTime",
)
_DAY_KEYS: Final = (
    "calendarDate",
    "summaryDate",
    "date",
    "startTimeLocal",
    "startTimeGMT",
    "startTime",
)
_DAY_LENGTH: Final = 10
_MAX_KEY_LENGTH: Final = 160
# One record id is "<section>/<key>"; the raw layer limits ids to 256 characters.
SECTION_SEPARATOR: Final = "/"
WHOLE_KEY: Final = ""


@dataclass(frozen=True, slots=True)
class SectionItem:
    """One stored element of a section: its key, its day and the element itself."""

    key: str
    observed_on: str | None
    value: Any


def record_identity(value: object) -> str | None:
    """Return the identity of a record, or None when it carries none."""
    if not isinstance(value, Mapping):
        return None
    for key in IDENTITY_KEYS:
        found = value.get(key)
        if found not in (None, ""):
            return str(found)
    return None


def content_digest(value: object) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_day(value: object) -> str | None:
    """Return the ``YYYY-MM-DD`` day an element belongs to, or None when it has none."""
    if not isinstance(value, Mapping):
        return None
    for key in _DAY_KEYS:
        found = value.get(key)
        if isinstance(found, str) and _is_day(found[:_DAY_LENGTH]):
            return found[:_DAY_LENGTH]
    return None


def _is_day(text: str) -> bool:
    try:
        return date.fromisoformat(text).isoformat() == text
    except ValueError:
        return False


def merge_records(incoming: Any, previous: Any) -> list[Any]:
    """Merge bounded-window results without discarding older records.

    The incoming records win over earlier ones with the same identity.
    """
    values: list[Any] = []
    if isinstance(incoming, list):
        values.extend(incoming)
    if isinstance(previous, list):
        values.extend(previous)
    merged: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        if not isinstance(value, dict):
            merged.append(value)
            continue
        identity = record_identity(value)
        key = ("identity", identity) if identity else ("payload", content_digest(value))
        if key in seen:
            continue
        seen.add(key)
        merged.append(value)
    return merged


def is_item_section(value: object) -> bool:
    """Return True when a section is a non-empty list, stored one element per row."""
    return isinstance(value, list) and bool(value)


def split_section(value: object) -> list[SectionItem]:
    """Split a section into its stored elements.

    A list yields one item per element. Any other value (a record, a scalar) is one
    item under the whole-section key.
    """
    if not isinstance(value, list):
        return [SectionItem(WHOLE_KEY, record_day(value), value)]
    used: dict[str, int] = {}
    items: list[SectionItem] = []
    for element in value:
        base = _element_key(element)
        count = used.get(base, 0)
        used[base] = count + 1
        key = base if count == 0 else f"{base}#{count}"
        items.append(SectionItem(key, record_day(element), element))
    return items


def _element_key(element: object) -> str:
    identity = record_identity(element)
    if identity is not None and len(identity) <= _MAX_KEY_LENGTH:
        return identity
    return f"~{content_digest(element)[:32]}"


def record_id(section: str, key: str) -> str:
    """Return the raw-layer record id of one element of a section."""
    return f"{section}{SECTION_SEPARATOR}{key}" if key != WHOLE_KEY else section


def section_of(record_id_text: str) -> str:
    """Return the section a raw-layer record id belongs to."""
    return record_id_text.partition(SECTION_SEPARATOR)[0]


def key_of(record_id_text: str) -> str:
    return record_id_text.partition(SECTION_SEPARATOR)[2]


def assemble_section(items: Sequence[SectionItem]) -> Any:
    """Return the section value stored in ``items``, or None when there are none.

    A whole-section item returns its value as it is; otherwise the elements are
    returned as a list in the order of ``items``.
    """
    if not items:
        return None
    if len(items) == 1 and items[0].key == WHOLE_KEY:
        return items[0].value
    return [item.value for item in items]


def wrapped(section: str, item: SectionItem) -> dict[str, Any]:
    """Return the stored object of one element: the section holding that element.

    This is exactly the input a section mapper reads for that element.
    """
    if item.key == WHOLE_KEY:
        return {section: item.value}
    return {section: [item.value]}


def unwrapped(section: str, key: str, payload: Mapping[str, Any]) -> SectionItem | None:
    """Return the element a stored object holds, or None when its shape is not ours."""
    if section not in payload:
        return None
    value = payload[section]
    if key == WHOLE_KEY:
        return SectionItem(key, record_day(value), value)
    if not isinstance(value, list) or len(value) != 1:
        return None
    return SectionItem(key, record_day(value[0]), value[0])
