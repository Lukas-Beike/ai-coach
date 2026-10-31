"""Persistence of the Garmin collection payload as keyed raw-layer rows.

Each element of a Garmin section is one ``health`` raw record (id
``<section>/<key>``, see ``backend.canonical.section_items``), so a sync writes
only the elements that changed and a reader loads only the sections and days it
needs. Everything outside the sections stays in the small ``garmin_state`` value.
Activities keep their own ``activity`` raw records and the activity tables.

All functions run on the caller's connection and never commit.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from backend.canonical.garmin_payload import (
    ACTIVITIES_SECTION,
    ACTIVITY_RECORD_KIND,
    GARMIN_PROVIDER,
    HEALTH_RECORD_KIND,
    ITEM_SECTIONS,
    MERGE_SECTIONS,
    REPLACE_SECTIONS,
    SECTIONS,
    STATE_KEY,
)
from backend.canonical.section_items import (
    SectionItem,
    assemble_section,
    key_of,
    record_id,
    section_of,
    unwrapped,
    wrapped,
)
from backend.canonical.vocabulary import ProviderId
from backend.db import canonical_domain_store, canonical_store
from backend.db.canonical_store import WriteOutcome
from backend.observability import sanitized_provider_payload

_ACTIVE: Final = "active"


@dataclass(slots=True)
class ItemWrites:
    """How many element rows one write inserted, rewrote, kept or removed."""

    written: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0

    def add(self, other: ItemWrites) -> None:
        self.written += other.written
        self.updated += other.updated
        self.unchanged += other.unchanged
        self.removed += other.removed

    @property
    def changed(self) -> int:
        return self.written + self.updated + self.removed


def put_section(
    db: Any,
    section: str,
    items: Sequence[SectionItem],
    *,
    fetched_at: str,
    now: str,
    mapper_version: int,
    replace: bool,
) -> ItemWrites:
    """Upsert the elements of one section; with ``replace``, drop the ones not listed.

    An unchanged element is not rewritten. A replacing write with no elements
    changes nothing, because an empty answer never clears a stored section.
    """
    writes = ItemWrites()
    ids: set[str] = set()
    for item in items:
        identifier = record_id(section, item.key)
        ids.add(identifier)
        outcome = canonical_store.upsert_provider_record(
            db,
            provider=GARMIN_PROVIDER,
            record_kind=HEALTH_RECORD_KIND,
            source_record_id=identifier,
            payload=sanitized_provider_payload(wrapped(section, item)),
            mapper_version=mapper_version,
            fetched_at=fetched_at,
            now=now,
            observed_on=item.observed_on,
        )
        if outcome is WriteOutcome.WRITTEN:
            writes.written += 1
        elif outcome is WriteOutcome.UPDATED:
            writes.updated += 1
        else:
            writes.unchanged += 1
    if replace and ids:
        writes.removed = prune_section(db, section, ids)
    return writes


def prune_section(
    db: Any,
    section: str,
    keep: set[str],
    *,
    start: str | None = None,
    end: str | None = None,
) -> int:
    """Delete the stored elements of a section whose record id is not in ``keep``.

    With ``start`` and ``end`` (inclusive ISO days) only elements of that window go;
    an element without a day is then kept. The canonical domain rows (sleep periods,
    statuses, zones, gear) projected from a deleted element are retired with it.
    Returns how many rows were deleted.
    """
    prefix = f"{section}/"
    rows = db.execute(
        "SELECT id, source_record_id, observed_on FROM provider_records "
        "WHERE provider = ? AND record_kind = ? AND (source_record_id = ? "
        "OR substr(source_record_id, 1, ?) = ?)",
        (GARMIN_PROVIDER, HEALTH_RECORD_KIND, section, len(prefix), prefix),
    ).fetchall()
    windowed = start is not None and end is not None
    stale = [
        row["id"]
        for row in rows
        if row["source_record_id"] not in keep
        and (
            not windowed
            or (
                row["observed_on"] is not None
                and str(start) <= row["observed_on"] <= str(end)
            )
        )
    ]
    now = datetime.now(UTC).isoformat()
    for row in rows:
        if row["id"] in stale:
            canonical_domain_store.retire_source_rows(
                db,
                provider=ProviderId(GARMIN_PROVIDER),
                source_record_id=str(row["source_record_id"]),
                now=now,
            )
    for row_id in stale:
        db.execute("DELETE FROM provider_records WHERE id = ?", (row_id,))
    return len(stale)


def read_activities(
    db: Any,
    *,
    start: str | None = None,
    end: str | None = None,
    limit: int | None = None,
) -> list[Any]:
    """Return the stored raw Garmin activity rows of an inclusive ISO day window.

    Activities have their own raw records; an activity without a day is always
    returned. Rows come in day order, the newest ``limit`` of them when limited.
    """
    clauses = ["provider = ?", "record_kind = ?", "state = ?"]
    params: list[object] = [GARMIN_PROVIDER, ACTIVITY_RECORD_KIND, _ACTIVE]
    if start is not None:
        clauses.append("(observed_on IS NULL OR observed_on >= ?)")
        params.append(start)
    if end is not None:
        clauses.append("(observed_on IS NULL OR observed_on <= ?)")
        params.append(end)
    query = "SELECT payload FROM provider_records WHERE " + " AND ".join(clauses)
    if limit is not None:
        query += " ORDER BY observed_on DESC, source_record_id DESC LIMIT ?"
        params.append(limit)
    else:
        query += " ORDER BY observed_on IS NULL, observed_on, source_record_id"
    rows = db.execute(query, tuple(params)).fetchall()
    values = [_decoded(row["payload"]) for row in rows]
    found = [value for value in values if value is not None]
    return found[::-1] if limit is not None else found


def _decoded(text: Any) -> Any | None:
    try:
        return json.loads(text)
    except TypeError, ValueError, RecursionError:
        return None


def read_sections(
    db: Any,
    sections: Iterable[str] | None = None,
    *,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Return the requested sections assembled as the collection payload holds them.

    ``sections`` None reads every stored section. ``start`` and ``end`` are
    inclusive ISO days; an element without a day is always returned. Elements
    come in day order. A section without stored elements is absent.
    """
    grouped: dict[str, list[SectionItem]] = {}
    for section, item in _items(db, sections, start, end):
        grouped.setdefault(section, []).append(item)
    return {
        section: assemble_section(items) for section, items in grouped.items() if items
    }


def iter_items(
    db: Any, sections: Iterable[str] | None = None
) -> Iterator[tuple[str, SectionItem]]:
    """Yield every stored element in storage order without holding them all."""
    yield from _items(db, sections, None, None)


def _section_clause(names: list[str]) -> tuple[str, list[object]]:
    matches = " OR ".join(
        "(source_record_id = ? OR substr(source_record_id, 1, ?) = ?)" for _ in names
    )
    params: list[object] = []
    for name in names:
        params.extend((name, len(name) + 1, f"{name}/"))
    return f"({matches})", params


def _decoded_item(row: Any) -> tuple[str, SectionItem] | None:
    identifier = str(row["source_record_id"])
    section = section_of(identifier)
    if section not in ITEM_SECTIONS:
        return None
    try:
        payload = json.loads(row["payload"])
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    item = unwrapped(section, key_of(identifier), payload)
    return None if item is None else (section, item)


def _items(
    db: Any,
    sections: Iterable[str] | None,
    start: str | None,
    end: str | None,
) -> Iterator[tuple[str, SectionItem]]:
    clauses = ["provider = ?", "record_kind = ?", "state = ?"]
    params: list[object] = [GARMIN_PROVIDER, HEALTH_RECORD_KIND, _ACTIVE]
    if sections is not None:
        names = sorted(set(sections) & ITEM_SECTIONS)
        if not names:
            return
        clause, values = _section_clause(names)
        clauses.append(clause)
        params.extend(values)
    if start is not None:
        clauses.append("(observed_on IS NULL OR observed_on >= ?)")
        params.append(start)
    if end is not None:
        clauses.append("(observed_on IS NULL OR observed_on <= ?)")
        params.append(end)
    cursor = db.execute(
        "SELECT source_record_id, payload FROM provider_records WHERE "
        + " AND ".join(clauses)
        + " ORDER BY observed_on IS NULL, observed_on, source_record_id",
        tuple(params),
    )
    for row in cursor:
        decoded = _decoded_item(row)
        if decoded is not None:
            yield decoded


def read_item(db: Any, section: str, key: str) -> Any | None:
    """Return the stored element ``key`` of ``section``, or None when none is stored."""
    row = db.execute(
        "SELECT source_record_id, payload FROM provider_records "
        "WHERE provider = ? AND record_kind = ? AND state = ? AND source_record_id = ?",
        (GARMIN_PROVIDER, HEALTH_RECORD_KIND, _ACTIVE, record_id(section, key)),
    ).fetchone()
    decoded = None if row is None else _decoded_item(row)
    return None if decoded is None else decoded[1].value


def section_names(db: Any) -> frozenset[str]:
    """Return the sections that hold at least one stored element."""
    rows = db.execute(
        "SELECT DISTINCT CASE WHEN instr(source_record_id, '/') > 0 "
        "THEN substr(source_record_id, 1, instr(source_record_id, '/') - 1) "
        "ELSE source_record_id END AS section FROM provider_records "
        "WHERE provider = ? AND record_kind = ? AND state = ?",
        (GARMIN_PROVIDER, HEALTH_RECORD_KIND, _ACTIVE),
    ).fetchall()
    return frozenset(row["section"] for row in rows) & ITEM_SECTIONS


def stored_sources(db: Any) -> frozenset[str]:
    """Return the sections with stored elements, activities included."""
    found = section_names(db)
    has_activity = db.execute(
        "SELECT 1 FROM provider_records WHERE provider = ? AND record_kind = ? "
        "AND state = ? LIMIT 1",
        (GARMIN_PROVIDER, ACTIVITY_RECORD_KIND, _ACTIVE),
    ).fetchone()
    return found | {ACTIVITIES_SECTION} if has_activity else found


def split_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the keys of a collection payload that are not stored as sections."""
    return {key: value for key, value in payload.items() if key not in SECTIONS}


def read_view(
    db: Any,
    sources: Iterable[str] | None = None,
    *,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Return the Garmin state plus the requested sections as one payload-shaped view.

    The bounded read-window sections (and the activities) honour ``start`` and
    ``end``, inclusive ISO days; the sections holding the provider's current answer
    are always read whole. ``sources`` None reads every section, which only the
    export and the privacy tools should do.
    """
    wanted = SECTIONS if sources is None else SECTIONS & set(sources)
    view = read_state(db)
    view.update(read_sections(db, wanted & set(MERGE_SECTIONS), start=start, end=end))
    view.update(read_sections(db, wanted & set(REPLACE_SECTIONS)))
    if ACTIVITIES_SECTION in wanted:
        view[ACTIVITIES_SECTION] = read_activities(db, start=start, end=end)
    return view


def write_state(db: Any, state: dict[str, Any], *, now: str) -> bool:
    """Store the non-section Garmin state; return False when it is unchanged."""
    text = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    row = db.execute("SELECT value FROM kv WHERE key = ?", (STATE_KEY,)).fetchone()
    if row is not None and row["value"] == text:
        return False
    db.execute(
        "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
        "updated_at=excluded.updated_at",
        (STATE_KEY, text, now),
    )
    return True


def read_state(db: Any) -> dict[str, Any]:
    """Return the stored non-section Garmin state; unreadable state reads as empty."""
    row = db.execute("SELECT value FROM kv WHERE key = ?", (STATE_KEY,)).fetchone()
    if row is None:
        return {}
    try:
        value = json.loads(row["value"])
    except ValueError, RecursionError:
        return {}
    return value if isinstance(value, dict) else {}
