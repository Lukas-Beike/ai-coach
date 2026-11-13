"""Bundle canonical activity records into sessions.

A Garmin-provider record duplicates a Wahoo-provider record (the "provider copy"
rule): the starts must be within 30 minutes, or within 10 minutes unless both
records carry a positive distance that agrees within max(500 m, 10 % of the
larger value). The sports must be the same or either must be "other". Some
duration pair must agree within max(120 s, 10 % of the larger value): the two
durations, a moving time against either duration, or the two elapsed times. A
distance is compared only when both are positive.

Starts are compared on the athlete's wall clock, as the legacy rules compare
naive local times. A zone is therefore required: records carry only instants.
Records must be representable in ``zone``, as mapper output is.

Every pass assigns one to one: a session takes at most one Garmin-provider record
of each recording origin, so a watch recording and a relayed copy of the Wahoo
ride both join it, and two separate sessions close together never merge. Each
pass joins as many records as possible and, among those assignments, prefers the
lowest total pair cost: the mean of the start gap as a share of the window and
each compared measurement's gap as a share of its tolerance; equal costs fall
back to the deterministic order (start instant, then provider, then activity
id). Every input record appears in exactly one session.

The primary of each session is its Wahoo-provider record, else its
Garmin-provider record. Stored Intervals.icu activity copies are never bundled:
session linking leaves them out (#2148), so they stay stored but count nowhere.

Candidates are found by a sorted wall-clock window (``_WallWindow``) instead of a
scan over every record. The window contains exactly the candidates the start rule
accepts, so the sessions are the ones the full comparison would produce.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from math import inf
from typing import Final

from backend.canonical.records import ActivityRecord
from backend.canonical.vocabulary import (
    PROVIDER_PRECEDENCE,
    ActivityLinkKind,
    ProviderId,
    RecordingOrigin,
    Sport,
)

__all__ = [
    "ActivitySession",
    "bundle_sessions",
]

START_WINDOW: Final = timedelta(minutes=30)
# A provider copy without a distance to corroborate it must start this close.
UNCORROBORATED_START_WINDOW: Final = timedelta(minutes=10)
DURATION_FLOOR_S: Final = 120.0
DISTANCE_FLOOR_M: Final = 500.0
RELATIVE_TOLERANCE: Final = 0.10


@dataclass(frozen=True, slots=True)
class ActivitySession:
    """One activity and the records that duplicate it.

    ``link_kinds`` runs parallel to ``duplicates``. It describes how each duplicate
    was joined and does not take part in equality.
    """

    primary: ActivityRecord
    duplicates: tuple[ActivityRecord, ...]
    link_kinds: tuple[ActivityLinkKind, ...] = field(default=(), compare=False)


@dataclass(frozen=True, slots=True)
class _Entry:
    record: ActivityRecord
    wall: datetime


def bundle_sessions(
    records: Iterable[ActivityRecord], *, zone: tzinfo
) -> tuple[ActivitySession, ...]:
    """Group records into sessions, with the primary first in each session."""
    entries = tuple(_entry(record, zone) for record in sorted(records, key=_order_key))
    return _sessions(entries, _assign_duplicates(entries))


def _entry(record: ActivityRecord, zone: tzinfo) -> _Entry:
    return _Entry(record, _wall_clock(record, zone))


def _order_key(record: ActivityRecord) -> tuple[datetime, str, str]:
    provider = record.provenance.provider
    provider_text = "" if provider is None else provider.value
    return (record.started_at, provider_text, record.activity_id)


def _wall_clock(record: ActivityRecord, zone: tzinfo) -> datetime:
    """Return the start as a naive wall-clock time in ``zone``."""
    return record.started_at.astimezone(zone).replace(tzinfo=None)


def _window_bounds(wall: datetime) -> tuple[datetime, datetime]:
    """Return the inclusive wall-clock bounds of START_WINDOW around ``wall``.

    A bound that would leave the datetime range saturates at the range limit. Every
    representable wall clock then still lies inside the window on that side.
    """
    try:
        low = wall - START_WINDOW
    except OverflowError:
        low = datetime.min  # noqa: DTZ901 - wall clocks are naive by design
    try:
        high = wall + START_WINDOW
    except OverflowError:
        high = datetime.max  # noqa: DTZ901 - wall clocks are naive by design
    return low, high


class _WallWindow:
    """Entry indices ordered by wall clock, for the START_WINDOW candidate search.

    The start rules compare naive wall-clock times, so the index is ordered on the
    wall clock itself rather than on the instant. An instant window would need a
    bound on the UTC-offset change between two starts, which a zone does not
    promise: DST shifts the wall clock by that change, and the autumn hour occurs
    twice. The wall-clock range ``[wall - START_WINDOW, wall + START_WINDOW]`` is
    exactly the set that ``abs(wall difference) <= START_WINDOW`` accepts, so the
    search misses no match. The rule predicates still decide every candidate.
    """

    def __init__(self, entries: Sequence[_Entry], indices: Iterable[int]) -> None:
        self._indices = sorted(indices, key=lambda index: entries[index].wall)
        self._walls = [entries[index].wall for index in self._indices]

    def near(self, wall: datetime) -> list[int]:
        """Return the indices whose wall clock lies within START_WINDOW of ``wall``."""
        low, high = _window_bounds(wall)
        return self._indices[
            bisect_left(self._walls, low) : bisect_right(self._walls, high)
        ]


def _assign_duplicates(entries: tuple[_Entry, ...]) -> dict[int, int]:
    """Map each Garmin-provider duplicate's index to its Wahoo-provider primary.

    Each recording origin is one one-to-one pass (see ``_assign_pairs``).
    """
    duplicate_of: dict[int, int] = {}
    wahoo = [
        index
        for index, entry in enumerate(entries)
        if entry.record.provenance.provider is ProviderId.WAHOO
    ]
    wahoo_window = _WallWindow(entries, wahoo)
    garmin_by_origin: dict[RecordingOrigin, list[int]] = {}
    for index, entry in enumerate(entries):
        if entry.record.provenance.provider is ProviderId.GARMIN:
            garmin_by_origin.setdefault(entry.record.provenance.recorded_by, []).append(
                index
            )
    for origin in sorted(garmin_by_origin, key=lambda item: item.value):
        _assign_pairs(
            entries,
            duplicate_of,
            garmin_by_origin[origin],
            wahoo_window,
            lambda garmin, wahoo_record: _provider_copy_cost(wahoo_record, garmin),
            set(),
        )
    return duplicate_of


def _assign_pairs(
    entries: tuple[_Entry, ...],
    duplicate_of: dict[int, int],
    sources: Sequence[int],
    targets: _WallWindow,
    cost: Callable[[_Entry, _Entry], float | None],
    taken: set[int],
) -> None:
    """Join as many sources as possible to distinct target sessions, closest overall.

    ``cost`` returns None when the rule rejects the pair. A session in ``taken``
    already holds a record of the sources' kind and accepts no other; each join
    adds its session. Among the assignments joining the most sources, the one
    with the lowest total cost wins, so a close pair never leaves another source
    without its only partner. Each group of connected candidates is matched on
    its own; ties follow source then target order (start instant, provider and
    activity id).
    """
    edges: dict[int, dict[int, float]] = {}
    for source in sources:
        if source in duplicate_of:
            continue
        for target in targets.near(entries[source].wall):
            primary = duplicate_of.get(target, target)
            if primary in taken:
                continue
            pair_cost = cost(entries[source], entries[target])
            if pair_cost is None:
                continue
            options = edges.setdefault(source, {})
            options[primary] = min(pair_cost, options.get(primary, pair_cost))
    for group in _candidate_groups(edges):
        for source, primary in _min_cost_matching(group, edges).items():
            duplicate_of[source] = primary
            taken.add(primary)


def _candidate_groups(edges: dict[int, dict[int, float]]) -> list[list[int]]:
    """Split the sources into groups that share no candidate session."""
    owner: dict[int, int] = {}
    groups: dict[int, list[int]] = {}
    for source in sorted(edges):
        roots = {owner[primary] for primary in edges[source] if primary in owner}
        merged = [source]
        for root in sorted(roots):
            merged.extend(groups.pop(root))
        root = min(merged)
        groups[root] = sorted(merged)
        for member in merged:
            for primary in edges[member]:
                owner[primary] = root
    return [groups[root] for root in sorted(groups)]


_Node = tuple[str, int]
# Smaller cost gains are float noise: a zero-cost residual cycle must not
# rewrite predecessors, or the path walk could circle.
_COST_EPSILON: Final = 1e-9


def _min_cost_matching(
    sources: list[int], edges: dict[int, dict[int, float]]
) -> dict[int, int]:
    """Return a maximum one-to-one matching of minimum total cost.

    Successive shortest augmenting paths (Bellman-Ford over the residual graph):
    each round adds one pair along the cheapest path, so every intermediate
    matching is the cheapest of its size, and the last is maximal.
    """
    match_of: dict[int, int] = {}
    source_of: dict[int, int] = {}
    while True:
        distance, previous = _cheapest_paths(
            _residual_arcs(sources, edges, match_of),
            {("s", source): 0.0 for source in sources if source not in match_of},
        )
        free = sorted(
            (cost, node[1])
            for node, cost in distance.items()
            if node[0] == "p" and node[1] not in source_of
        )
        if not free:
            return match_of
        _augment(("p", free[0][1]), previous, match_of, source_of)


def _residual_arcs(
    sources: list[int], edges: dict[int, dict[int, float]], match_of: dict[int, int]
) -> list[tuple[_Node, _Node, float]]:
    """Return unmatched pairs forward and matched pairs backward at negated cost."""
    arcs: list[tuple[_Node, _Node, float]] = []
    for source in sources:
        for primary in sorted(edges[source]):
            pair_cost = edges[source][primary]
            if match_of.get(source) == primary:
                arcs.append((("p", primary), ("s", source), -pair_cost))
            else:
                arcs.append((("s", source), ("p", primary), pair_cost))
    return arcs


def _cheapest_paths(
    arcs: list[tuple[_Node, _Node, float]], distance: dict[_Node, float]
) -> tuple[dict[_Node, float], dict[_Node, _Node]]:
    """Relax ``arcs`` Bellman-Ford style from the start nodes in ``distance``."""
    previous: dict[_Node, _Node] = {}
    for _ in range(len(arcs) + 1):
        changed = False
        for start, end, pair_cost in arcs:
            reached = distance.get(start)
            if reached is None or reached + pair_cost >= (
                distance.get(end, inf) - _COST_EPSILON
            ):
                continue
            distance[end] = reached + pair_cost
            previous[end] = start
            changed = True
        if not changed:
            break
    return distance, previous


def _augment(
    node: _Node,
    previous: dict[_Node, _Node],
    match_of: dict[int, int],
    source_of: dict[int, int],
) -> None:
    """Flip the pairs along the path that ends at the free session ``node``."""
    seen: set[_Node] = set()
    while node in previous and node not in seen:
        seen.add(node)
        source_node = previous[node]
        match_of[source_node[1]] = node[1]
        source_of[node[1]] = source_node[1]
        if source_node not in previous:
            return
        node = previous[source_node]


def _sessions(
    entries: tuple[_Entry, ...], duplicate_of: dict[int, int]
) -> tuple[ActivitySession, ...]:
    members: dict[int, list[int]] = {
        index: [] for index in range(len(entries)) if index not in duplicate_of
    }
    for index in range(len(entries)):
        if index in duplicate_of:
            members[duplicate_of[index]].append(index)
    sessions = []
    for anchor, duplicates in members.items():
        lead = min((anchor, *duplicates), key=lambda index: _lead_key(entries, index))
        others = [index for index in sorted((anchor, *duplicates)) if index != lead]
        sessions.append(
            ActivitySession(
                entries[lead].record,
                tuple(entries[index].record for index in others),
                (ActivityLinkKind.HEURISTIC,) * len(others),
            )
        )
    return tuple(sessions)


_LEAD_PROVIDER_RANK: Final = {
    provider: rank for rank, provider in enumerate(PROVIDER_PRECEDENCE)
}


def _lead_key(entries: tuple[_Entry, ...], index: int) -> tuple[int, int, int]:
    """Order a session's records for its primary: Wahoo, then Garmin.

    Among one provider's copies the recording origin decides (Wahoo before
    Garmin); the input order breaks the rest.
    """
    provenance = entries[index].record.provenance
    provider = provenance.provider
    return (
        len(_LEAD_PROVIDER_RANK) if provider is None else _LEAD_PROVIDER_RANK[provider],
        0 if provenance.recorded_by is RecordingOrigin.WAHOO else 1,
        index,
    )


def _provider_copy_cost(wahoo: _Entry, garmin: _Entry) -> float | None:
    """Return the pair cost of a Garmin-provider copy of a Wahoo-provider record.

    None unless the sports are compatible, the starts agree (closer when no
    distance corroborates the pair) and some duration pair agrees; a distance
    disagrees only when both are positive.
    """
    start = _start_cost(wahoo, garmin)
    if start is None:
        return None
    left, right = wahoo.record, garmin.record
    if left.sport is not right.sport and Sport.OTHER not in (left.sport, right.sport):
        return None
    duration = _duration_gap(left, right)
    if duration is None:
        return None
    gaps = [start, duration]
    if (
        left.distance_m
        and right.distance_m
        and min(left.distance_m, right.distance_m) > 0
    ):
        distance = _relative_gap(
            left.distance_m,
            right.distance_m,
            DISTANCE_FLOOR_M,
            max(left.distance_m, right.distance_m),
        )
        if distance is None:
            return None
        gaps.append(distance)
    elif abs(wahoo.wall - garmin.wall) > UNCORROBORATED_START_WINDOW:
        return None
    return _mean(gaps)


def _duration_gap(left: ActivityRecord, right: ActivityRecord) -> float | None:
    """Return the smallest agreeing duration gap, None when no duration pair agrees."""
    left_durations = _positive(left.duration_s, left.moving_duration_s)
    right_durations = _positive(right.duration_s, right.moving_duration_s)
    pairs = [(a, b) for a in left_durations for b in right_durations]
    pairs.extend(
        (a, b)
        for a in _positive(left.elapsed_duration_s)
        for b in _positive(right.elapsed_duration_s)
    )
    gaps = [
        gap
        for a, b in pairs
        if (gap := _relative_gap(a, b, DURATION_FLOOR_S, max(a, b))) is not None
    ]
    return min(gaps) if gaps else None


def _positive(*values: float | None) -> list[float]:
    return [value for value in values if value is not None and value > 0]


def _mean(gaps: Sequence[float]) -> float:
    """Return the mean gap, so a pair is not cheaper for comparing fewer values."""
    return sum(gaps) / len(gaps)


def _start_cost(left: _Entry, right: _Entry) -> float | None:
    """Return the wall-clock start gap as a share of START_WINDOW, None outside it."""
    gap = abs(left.wall - right.wall)
    return None if gap > START_WINDOW else gap / START_WINDOW


def _relative_gap(
    value: float, other: float, floor: float, base: float
) -> float | None:
    """Return the gap as a share of its tolerance, None when the values disagree."""
    gap = abs(value - other)
    tolerance = max(floor, base * RELATIVE_TOLERANCE)
    return gap / tolerance if gap <= tolerance else None
