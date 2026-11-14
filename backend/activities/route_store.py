"""The stored route index: reads for the detail view, rename and removal (#1868).

The index is one kv value written by ``backend.sync.activity_routes`` and
described in ``backend.activities.routes``. It is derived from stored GPS tracks
and removed with them; readers get ``route_block`` only.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Final

from backend.activities import routes
from backend.db.repositories import KeyValueRepository
from backend.errors import NOT_FOUND_ERROR, AppError

INDEX_KEY: Final = "activity_routes"
STATE_KEY: Final = "activity_routes_state"


def load_index(db: Any) -> dict[str, Any]:
    """The stored index; an empty one when absent or malformed."""
    row = db.execute("SELECT value FROM kv WHERE key = ?", (INDEX_KEY,)).fetchone()
    try:
        index = json.loads(row["value"]) if row else None
    except ValueError:
        index = None
    if (
        isinstance(index, dict)
        and isinstance(index.get("routes"), dict)
        and isinstance(index.get("sessions"), dict)
        and isinstance(index.get("next"), int)
    ):
        # A malformed entry is dropped so one bad row cannot fail a stage pass.
        for part in ("routes", "sessions"):
            index[part] = {
                key: entry
                for key, entry in index[part].items()
                if isinstance(entry, dict)
            }
        return index
    return routes.empty_index()


def save_index(key_values: KeyValueRepository, db: Any, index: dict[str, Any]) -> None:
    key_values.set(
        db, INDEX_KEY, json.dumps(index, sort_keys=True, separators=(",", ":"))
    )


def clear_routes(key_values: KeyValueRepository, db: Any) -> None:
    """Delete every route with its names, as the stored tracks they come from."""
    key_values.delete(db, INDEX_KEY)
    key_values.delete(db, STATE_KEY)


def stored_route_block(db: Any, session_id: str) -> dict[str, Any] | None:
    """The route block of one session, or None without a recognised route."""
    return routes.route_block(load_index(db), session_id)


class ActivityRouteService:
    """Rename a route; the only write of the athlete's own to the index."""

    def __init__(
        self,
        database: Callable[[], Any],
        key_values: KeyValueRepository,
    ) -> None:
        self._database = database
        self._key_values = key_values

    def rename(self, route_id: Any, name: Any) -> dict[str, Any]:
        clean = routes.clean_name(name)
        if clean is None:
            raise AppError(
                400,
                f"Der Name muss aus 1 bis {routes.MAX_NAME_LENGTH} "
                "Zeichen ohne Steuerzeichen bestehen.",
            )
        with self._database().unit_of_work() as db:
            index = load_index(db)
            route = index["routes"].get(route_id) if isinstance(route_id, str) else None
            if route is None:
                raise AppError(404, NOT_FOUND_ERROR)
            route["name"] = clean
            save_index(self._key_values, db, index)
        return {"status": "ok", "route_id": route_id, "label": clean}
