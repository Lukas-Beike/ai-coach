"""Schema 11 -> 12 data step: the Garmin snapshot blob becomes keyed raw-layer rows.

Before schema 12 the whole Garmin collection lived in one ``garmin_snapshot``
value that every sync rewrote. This step moves it, inside the migration's
savepoint, into one ``health`` raw record per section element, one ``activity``
raw record for each Garmin activity that has none yet, and the small ``garmin_state``
value for everything else. New rows carry ``mapped_version`` 0, so the canonical
backfill projects them again with the current mapper. The source value stays
unread under ``garmin_snapshot_legacy`` as the way back; nothing is deleted.

The section elements are checked against what was written before the step
returns; any difference raises and rolls the whole migration back.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Final

from backend.canonical.garmin_payload import (
    ACTIVITIES_SECTION,
    ACTIVITY_RECORD_KIND,
    GARMIN_PROVIDER,
    HEALTH_RECORD_KIND,
    ITEM_SECTIONS,
    LEGACY_SNAPSHOT_KEY,
    RETIRED_SNAPSHOT_KEY,
)
from backend.canonical.section_items import (
    content_digest,
    record_day,
    record_id,
    split_section,
)
from backend.db import canonical_store, garmin_store
from backend.observability import sanitized_provider_payload

# Mapper version of a row no mapper has projected yet.
UNMAPPED_VERSION: Final = 0
_ACTIVITY_ID: Final = re.compile(r"[A-Za-z0-9_-]{1,64}")
_WEIGHT_SECTIONS: Final = frozenset({"weight", "weigh_ins", "weighIns"})


def split_garmin_snapshot(db: Any) -> None:
    """Move the stored Garmin snapshot into raw-layer rows; see the module docstring."""
    now = datetime.now(UTC).isoformat()
    legacy = db.execute(
        "SELECT value, updated_at FROM kv WHERE key = ?", (LEGACY_SNAPSHOT_KEY,)
    ).fetchone()
    blob = _decode(legacy["value"]) if legacy is not None else {}
    stored_at = str(legacy["updated_at"]) if legacy is not None else now
    old_rows = _whole_section_rows(db)
    sections = {name: value for name, (value, _at) in old_rows.items()}
    fetched = {name: at for name, (_value, at) in old_rows.items()}
    sections.update((name, blob[name]) for name in blob if name in ITEM_SECTIONS)
    freshness = blob.get("source_freshness")
    expected: dict[str, list[Any]] = {}
    created: set[str] = set()
    for name, value in sections.items():
        if value is None:
            continue
        items = split_section(value)
        expected[name] = [sanitized_provider_payload(item.value) for item in items]
        garmin_store.put_section(
            db,
            name,
            items,
            fetched_at=_fetched_at(name, fetched, freshness, blob, stored_at),
            now=now,
            mapper_version=UNMAPPED_VERSION,
            replace=False,
        )
        created.update(record_id(name, item.key) for item in items)
    _drop_whole_section_rows(db, keep=created)
    _store_activities(db, blob.get(ACTIVITIES_SECTION), now=now, fallback=stored_at)
    _stamp_activity_days(db)
    state = {
        key: value
        for key, value in blob.items()
        if key not in ITEM_SECTIONS and key != ACTIVITIES_SECTION
    }
    if state:
        garmin_store.write_state(db, state, now=now)
    _verify(db, expected)
    if legacy is not None:
        db.execute("DELETE FROM kv WHERE key = ?", (RETIRED_SNAPSHOT_KEY,))
        db.execute(
            "UPDATE kv SET key = ? WHERE key = ?",
            (RETIRED_SNAPSHOT_KEY, LEGACY_SNAPSHOT_KEY),
        )


def _decode(text: Any) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except TypeError, ValueError, RecursionError:
        return {}
    return value if isinstance(value, dict) else {}


def _whole_section_rows(db: Any) -> dict[str, tuple[Any, str]]:
    """Return the schema-11 section records: one row per section holding the whole value."""
    rows = db.execute(
        "SELECT source_record_id, payload, fetched_at FROM provider_records "
        "WHERE provider = ? AND record_kind = ? AND instr(source_record_id, '/') = 0",
        (GARMIN_PROVIDER, HEALTH_RECORD_KIND),
    ).fetchall()
    found: dict[str, tuple[Any, str]] = {}
    for row in rows:
        for name, value in _decode(row["payload"]).items():
            if name in ITEM_SECTIONS:
                found[name] = (value, str(row["fetched_at"]))
    return found


def _drop_whole_section_rows(db: Any, *, keep: set[str]) -> None:
    rows = db.execute(
        "SELECT id, source_record_id FROM provider_records WHERE provider = ? "
        "AND record_kind = ? AND instr(source_record_id, '/') = 0",
        (GARMIN_PROVIDER, HEALTH_RECORD_KIND),
    ).fetchall()
    for row in rows:
        if row["source_record_id"] not in keep:
            db.execute("DELETE FROM provider_records WHERE id = ?", (row["id"],))


def _fetched_at(
    name: str,
    fetched: dict[str, str],
    freshness: Any,
    blob: dict[str, Any],
    stored_at: str,
) -> str:
    """Return when a section was fetched: its own record, its freshness, else the sync."""
    if name in fetched:
        return fetched[name]
    if name in _WEIGHT_SECTIONS and "weight" in fetched:
        return fetched["weight"]
    detail = freshness.get(name) if isinstance(freshness, dict) else None
    for value in (
        detail.get("fetched_at") if isinstance(detail, dict) else None,
        blob.get("synced_at"),
    ):
        if isinstance(value, str) and value:
            return value
    return stored_at


def _store_activities(db: Any, activities: Any, *, now: str, fallback: str) -> None:
    """Add a raw record for each stored Garmin activity that has none."""
    if not isinstance(activities, list):
        return
    for activity in activities:
        identifier = _activity_id(activity)
        if identifier is None:
            continue
        present = db.execute(
            "SELECT 1 FROM provider_records WHERE provider = ? AND record_kind = ? "
            "AND source_record_id = ?",
            (GARMIN_PROVIDER, ACTIVITY_RECORD_KIND, identifier),
        ).fetchone()
        if present is None:
            canonical_store.upsert_provider_record(
                db,
                provider=GARMIN_PROVIDER,
                record_kind=ACTIVITY_RECORD_KIND,
                source_record_id=identifier,
                payload=sanitized_provider_payload(activity),
                mapper_version=UNMAPPED_VERSION,
                fetched_at=fallback,
                now=now,
                observed_on=record_day(activity),
            )


def _activity_id(activity: Any) -> str | None:
    if not isinstance(activity, dict):
        return None
    value = activity.get("activityId")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    text = str(value)
    return text if _ACTIVITY_ID.fullmatch(text) else None


def _stamp_activity_days(db: Any) -> None:
    """Give every activity raw record the athlete-local day of its activity row."""
    db.execute(
        "UPDATE provider_records SET observed_on = (SELECT r.local_date "
        "FROM activity_records AS r WHERE r.provider = provider_records.provider "
        "AND r.provider_activity_id = provider_records.source_record_id) "
        "WHERE record_kind = ? AND observed_on IS NULL AND EXISTS "
        "(SELECT 1 FROM activity_records AS r WHERE r.provider = "
        "provider_records.provider AND r.provider_activity_id = "
        "provider_records.source_record_id)",
        (ACTIVITY_RECORD_KIND,),
    )


def _verify(db: Any, expected: dict[str, list[Any]]) -> None:
    """Raise unless every section reads back exactly the elements that were split."""
    stored: dict[str, list[Any]] = {name: [] for name in expected}
    for name, item in garmin_store.iter_items(db, expected):
        stored[name].append(item.value)
    for name, values in expected.items():
        if Counter(map(content_digest, values)) != Counter(
            map(content_digest, stored[name])
        ):
            raise RuntimeError(
                "Die Garmin-Daten konnten bei der Migration nicht vollständig übernommen werden."
            )
