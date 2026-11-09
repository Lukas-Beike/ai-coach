"""Recognise repeated outdoor routes from coarse, privacy-safe track fingerprints (#1868).

A track is reduced to its start and end cell, its distance and the set of grid
cells (about 500 m) that points sampled every 150 m along it fall in. Two
sessions are the same route when their distances differ by at most 10 %, one
starts (or, reversed, ends) near where the other starts, and the Jaccard
overlap of their cell sets is at least 0.6. A set ignores the direction, so a
reversed track matches; Jaccard is symmetric and punishes a track that merely
shares its first kilometres or is a long detour of a short loop.

The index (routes with a reference fingerprint, and per session its input hash and
route) lives in one kv value and is private: only ``route_block`` is meant for
read models and carries a label, a repeat count and an opaque id, never a
coordinate, a cell or a fingerprint.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

CELL_M: Final = 500.0
SAMPLE_M: Final = 150.0
# A jump this long between two fixes is a signal gap, not distance travelled.
MAX_GAP_M: Final = 1000.0
MIN_DISTANCE_M: Final = 3000.0
MIN_CELLS: Final = 4
DISTANCE_TOLERANCE: Final = 0.10
MIN_OVERLAP: Final = 0.6
MAX_NAME_LENGTH: Final = 60
_METRES_PER_DEGREE: Final = 111_320.0
_LATITUDE_STEP: Final = CELL_M / _METRES_PER_DEGREE

type Cell = tuple[int, int]
type Coordinates = tuple[float, float]


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """The coarse shape of one track; never leaves the route index."""

    start: Cell
    end: Cell
    distance_m: float
    cells: frozenset[Cell]


def valid_position(latitude: object, longitude: object) -> Coordinates | None:
    """A finite position on Earth; the origin is what a device without a fix reports."""
    if not isinstance(latitude, (int, float)) or not isinstance(
        longitude, (int, float)
    ):
        return None
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    if latitude == 0 and longitude == 0:
        return None
    return float(latitude), float(longitude)


def cell_of(latitude: float, longitude: float) -> Cell:
    """The grid cell of a position; a cell is about 500 m wide at any latitude.

    The longitude step is fixed per degree of latitude, so a cell never changes
    shape within a band.
    """
    band_centre = math.floor(latitude) + 0.5
    scale = max(math.cos(math.radians(band_centre)), 0.01)
    longitude_step = _LATITUDE_STEP / scale
    return (
        math.floor(latitude / _LATITUDE_STEP),
        math.floor(longitude / longitude_step),
    )


def _step_m(a: Coordinates, b: Coordinates) -> float:
    dy = (b[0] - a[0]) * _METRES_PER_DEGREE
    dx = (b[1] - a[1]) * _METRES_PER_DEGREE * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


def fingerprint(
    latitudes: Sequence[object],
    longitudes: Sequence[object],
    distance_m: float | None = None,
) -> Fingerprint | None:
    """Fingerprint a track, or None when it is too short or covers too few cells.

    Fixes that are missing, invalid or at the origin are skipped. The distance
    is ``distance_m`` when given, else the length of the track without gaps.
    """
    cells: set[Cell] = set()
    first: Cell | None = None
    last: Cell | None = None
    previous: Coordinates | None = None
    anchor: Coordinates | None = None
    length = 0.0
    for latitude, longitude in zip(latitudes, longitudes, strict=False):
        position = valid_position(latitude, longitude)
        if position is None:
            continue
        cell = cell_of(*position)
        if first is None:
            first = cell
        last = cell
        if previous is not None and _step_m(previous, position) > MAX_GAP_M:
            # Both sides of a signal gap count as cells, the jump as no distance.
            cells.add(cell)
            anchor = position
        elif anchor is None:
            cells.add(cell)
            anchor = position
        elif (chord := _step_m(anchor, position)) >= SAMPLE_M:
            # Chords between samples measure the track without the GPS jitter.
            length += chord
            cells.add(cell)
            anchor = position
        previous = position
    if first is None or last is None:
        return None
    cells.update((first, last))
    total = (
        float(distance_m)
        if isinstance(distance_m, (int, float)) and 0 < distance_m < math.inf
        else length
    )
    if total < MIN_DISTANCE_M or len(cells) < MIN_CELLS:
        return None
    return Fingerprint(first, last, total, frozenset(cells))


def _near(a: Cell, b: Cell) -> bool:
    return abs(a[0] - b[0]) <= 1 and abs(a[1] - b[1]) <= 1


def overlap(a: Fingerprint, b: Fingerprint) -> float:
    """The Jaccard overlap of the cell sets, 0 to 1."""
    union = len(a.cells | b.cells)
    return len(a.cells & b.cells) / union if union else 0.0


def same_route(a: Fingerprint, b: Fingerprint) -> bool:
    """Whether two tracks are the same route, in either direction."""
    if abs(a.distance_m - b.distance_m) > DISTANCE_TOLERANCE * max(
        a.distance_m, b.distance_m
    ):
        return False
    # The start may sit on the border of its cell, so a neighbour counts.
    if not (_near(a.start, b.start) or _near(a.start, b.end) or _near(a.end, b.start)):
        return False
    return overlap(a, b) >= MIN_OVERLAP


def encode(print_: Fingerprint) -> dict[str, Any]:
    return {
        "s": list(print_.start),
        "e": list(print_.end),
        "d": round(print_.distance_m, 1),
        "c": sorted([list(cell) for cell in print_.cells]),
    }


def decode(value: object) -> Fingerprint | None:
    """Read a stored reference fingerprint; None when it is malformed."""
    if not isinstance(value, Mapping):
        return None
    try:
        cells = frozenset((int(r), int(c)) for r, c in value["c"])
        start, end = value["s"], value["e"]
        return Fingerprint(
            (int(start[0]), int(start[1])),
            (int(end[0]), int(end[1])),
            float(value["d"]),
            cells,
        )
    except KeyError, TypeError, ValueError, IndexError:
        return None


def empty_index() -> dict[str, Any]:
    """A new index: routes by id and, per session, its input hash and route."""
    return {"next": 1, "routes": {}, "sessions": {}}


def place(index: dict[str, Any], session_id: str, track: Fingerprint | None) -> None:
    """Put one session on the route it repeats, a new route, or no route.

    A session keeps its route while it still matches the route's reference, so
    a re-recorded track never loses the athlete's name. Otherwise the most
    similar matching route wins; ties go to the older route.
    """
    entry = index["sessions"][session_id]
    if track is None:
        entry["route"] = None
        return
    routes = index["routes"]
    current = entry.get("route")
    if current in routes:
        reference = decode(routes[current].get("ref"))
        if reference is not None and same_route(track, reference):
            return
    best: tuple[float, int, str] | None = None
    for route_id, route in routes.items():
        reference = decode(route.get("ref"))
        if reference is None or not same_route(track, reference):
            continue
        candidate = (-overlap(track, reference), _sequence(route_id), route_id)
        if best is None or candidate < best:
            best = candidate
    if best is not None:
        entry["route"] = best[2]
        return
    number = int(index["next"])
    index["next"] = number + 1
    route_id = f"r{number}"
    routes[route_id] = {"name": None, "ref": encode(track)}
    entry["route"] = route_id


def prune(index: dict[str, Any], live: Iterable[str]) -> None:
    """Forget sessions that are gone, then routes without a session."""
    keep = set(live)
    sessions = index["sessions"]
    for session_id in [key for key in sessions if key not in keep]:
        del sessions[session_id]
    used = {entry.get("route") for entry in sessions.values()}
    for route_id in [key for key in index["routes"] if key not in used]:
        del index["routes"][route_id]


def _sequence(route_id: str) -> int:
    return int(route_id[1:]) if route_id[1:].isdigit() else 0


def label_of(index: Mapping[str, Any], route_id: str) -> str:
    """The athlete's name of a route, or "Strecke <n>" until it has one."""
    name = index["routes"][route_id].get("name")
    return name if isinstance(name, str) and name else f"Strecke {_sequence(route_id)}"


def route_block(index: Mapping[str, Any], session_id: str) -> dict[str, Any] | None:
    """The compact block of one session: label, repeat count and opaque id."""
    entry = index["sessions"].get(session_id)
    route_id = entry.get("route") if isinstance(entry, Mapping) else None
    if not isinstance(route_id, str) or route_id not in index["routes"]:
        return None
    members = sorted(
        (str(item.get("at") or ""), key)
        for key, item in index["sessions"].items()
        if item.get("route") == route_id
    )
    own = (str(entry.get("at") or ""), session_id)
    return {
        "label": label_of(index, route_id),
        "repeat_index": sum(1 for member in members if member <= own),
        "repeat_count": len(members),
        "route_id": route_id,
    }


def clean_name(value: object) -> str | None:
    """A trimmed plain-text name of 1 to 60 characters without control characters."""
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not 1 <= len(name) <= MAX_NAME_LENGTH:
        return None
    if any(
        ord(char) < 32 or ord(char) == 127 or not char.isprintable() for char in name
    ):
        return None
    return name
