"""Read-only queries for public calendar sources and event candidates."""

from typing import Any


def list_sources(db: Any) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT id, name, url, last_sync_at, last_error, created_at, updated_at "
        "FROM public_event_sources ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def list_candidates(db: Any, limit: Any = 100) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT c.id, c.source_id, s.name AS source_name, c.uid, c.name, c.event_date, c.sport, "
        "c.distance, c.location, c.url, c.description, c.imported_competition_id, c.created_at, c.updated_at "
        "FROM public_event_candidates c JOIN public_event_sources s ON s.id = c.source_id "
        "ORDER BY c.event_date, c.name LIMIT ?",
        (max(1, min(int(limit), 500)),),
    ).fetchall()
    return [dict(row) for row in rows]


def state(db: Any) -> dict[str, Any]:
    return {"sources": list_sources(db), "candidates": list_candidates(db)}
