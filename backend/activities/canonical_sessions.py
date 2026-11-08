"""Bundle canonical activity records into sessions with the legacy duplicate rules.

Exact links come before every pass that joins a Garmin- or Wahoo-provider
record (only the Intervals.icu-internal Wahoo/Garmin copy pass runs earlier): an
Intervals.icu record whose external reference names a
stored Garmin- or Wahoo-provider record (``source`` with ``external_id``) joins
that record whatever the times and measurements say. The heuristic rules below
decide only the records left without an exact link; an Intervals.icu record whose
upstream record is not among the inputs stays open to them.

The pairwise rules are those of ``backend.activities.duplicates`` over
``ActivityRecord`` values; the one-to-one assignment below is canonical only (the
raw-row helpers still accept any match):

* a Garmin-provider record duplicates an Intervals.icu record when the starts are
  within 30 minutes, the sport families agree (or either is "other"), and every
  comparable measurement agrees with at least one comparison made. Duration
  tolerance is max(120 s, 10 % of the Intervals value). Distance tolerance is
  max(500 m, 10 % of the Intervals value); a missing or zero distance is skipped.
* within Intervals.icu, a Garmin-recorded cycling ride duplicates a Wahoo-recorded
  cycling ride when the starts are within 30 minutes and both duration and
  distance are present and positive, agreeing within max(120 s, 10 % of the
  larger value) and max(500 m, 10 % of the larger value) respectively.

Starts are compared on the athlete's wall clock, as the legacy rules compare
naive local times. A zone is therefore required: records carry only instants.
Records must be representable in ``zone``, as mapper output is.

Garmin often sends no moving time (walks), so its elapsed duration cannot agree
with the Intervals.icu moving time. A Garmin-provider record that matched no
Intervals.icu record under the rule above may then duplicate one whose elapsed
time agrees with the Garmin duration, with the same start, family and distance
rules.

Every pass assigns one to one: a session takes at most one record of the joining
provider and recording origin, so two separate sessions close together never
merge. Each pass joins as many records as possible and, among those
assignments, prefers the lowest total pair cost: the mean of the start gap as a
share of the window and each compared measurement's gap as a share of its
tolerance;
equal costs fall back to the deterministic order (start instant, then provider,
then activity id). A record is a duplicate of at most one primary, and every
input record appears in exactly one session. A Garmin-provider duplicate of a
Garmin-recorded Intervals copy joins that copy's Wahoo session.

Wahoo-provider records (direct Wahoo ingest) join the same bundling:

* a Wahoo-provider record duplicates an Intervals.icu record recorded by Wahoo when
  the starts are within 30 minutes, the sport families agree (or either is
  "other"), and every comparable measurement agrees (the Garmin-versus-Intervals
  tolerances apply).
* a Garmin-provider cycling ride that matched no Intervals.icu record duplicates a
  Wahoo-provider cycling ride under the Wahoo/Garmin-copy rule above. A Wahoo
  record that is itself a duplicate passes its own anchor on to the Garmin record.

Intervals.icu is output only and ranks last: the primary of each session is its
Wahoo-provider record, else its Garmin-provider record, else the Intervals.icu
record (a Wahoo-recorded copy before a Garmin-recorded one). The pairing passes
above only decide which records belong together.

Each duplicate carries the kind of link that joined it to its session.

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
from backend.canonical.sports import legacy_activity_family
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
    "wahoo_garmin_copy_match",
]

START_WINDOW: Final = timedelta(minutes=30)
DURATION_FLOOR_S: Final = 120.0
DISTANCE_FLOOR_M: Final = 500.0
RELATIVE_TOLERANCE: Final = 0.10
_OTHER_FAMILY: Final = "other"


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
    family: str


def bundle_sessions(
    records: Iterable[ActivityRecord], *, zone: tzinfo
) -> tuple[ActivitySession, ...]:
    """Group records into sessions, with the primary first in each session."""
    entries = tuple(_entry(record, zone) for record in sorted(records, key=_order_key))
    duplicate_of, exact = _assign_duplicates(entries)
    return _sessions(entries, duplicate_of, exact)


def wahoo_garmin_copy_match(
    wahoo: ActivityRecord, copy: ActivityRecord, *, zone: tzinfo
) -> bool:
    """Return True when ``copy`` is a Garmin-recorded copy of the Wahoo ride ``wahoo``.

    Applies the Wahoo/Garmin ride rule on the athlete's wall clock ``zone``; the
    caller decides which records are Wahoo- and Garmin-recorded Intervals.icu rides.
    """
    return _wahoo_copy_cost(_entry(wahoo, zone), _entry(copy, zone)) is not None


def _entry(record: ActivityRecord, zone: tzinfo) -> _Entry:
    return _Entry(
        record, _wall_clock(record, zone), legacy_activity_family(record.sport)
    )


def _order_key(record: ActivityRecord) -> tuple[datetime, str, str]:
    provider = record.provenance.provider
    provider_text = "" if provider is None else provider.value
    return (record.started_at, provider_text, record.activity_id)


def _wall_clock(record: ActivityRecord, zone: tzinfo) -> datetime:
    """Return the start as a naive wall-clock time in ``zone``."""
    return record.started_at.astimezone(zone).replace(tzinfo=None)


def _is_intervals(record: ActivityRecord) -> bool:
    return record.provenance.provider is ProviderId.INTERVALS


def _is_intervals_ride(record: ActivityRecord, origin: RecordingOrigin) -> bool:
    return (
        _is_intervals(record)
        and record.sport is Sport.RIDE
        and record.provenance.recorded_by is origin
    )


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


def _assign_duplicates(entries: tuple[_Entry, ...]) -> tuple[dict[int, int], set[int]]:
    """Map each duplicate's index to the index of its primary; return the exact ones.

    Every pass is a one-to-one assignment: a session takes at most one record of
    the joining kind, and the closest candidate pair wins (see ``_assign_pairs``).
    """
    duplicate_of: dict[int, int] = {}
    wahoo_rides = [
        index
        for index, entry in enumerate(entries)
        if _is_intervals_ride(entry.record, RecordingOrigin.WAHOO)
    ]
    garmin_ride_copies = [
        index
        for index, entry in enumerate(entries)
        if _is_intervals_ride(entry.record, RecordingOrigin.GARMIN)
    ]
    _assign_pairs(
        entries,
        duplicate_of,
        garmin_ride_copies,
        _WallWindow(entries, wahoo_rides),
        lambda copy, wahoo: _wahoo_copy_cost(wahoo, copy),
        set(),
    )

    intervals = [
        index for index, entry in enumerate(entries) if _is_intervals(entry.record)
    ]
    intervals_window = _WallWindow(entries, intervals)
    garmin = [
        index
        for index, entry in enumerate(entries)
        if entry.record.provenance.provider is ProviderId.GARMIN
    ]
    # Sessions that already hold a Garmin-provider, or a Wahoo-provider, record.
    joined: set[int] = set()
    wahoo_joined: set[int] = set()
    exact = _assign_exact(
        entries,
        duplicate_of,
        {ProviderId.GARMIN: joined, ProviderId.WAHOO: wahoo_joined},
    )
    _assign_pairs(
        entries, duplicate_of, garmin, intervals_window, _garmin_intervals_cost, joined
    )
    _assign_pairs(
        entries,
        duplicate_of,
        [index for index in garmin if index not in duplicate_of],
        intervals_window,
        lambda garmin, intervals: _garmin_intervals_cost(
            garmin, intervals, elapsed=True
        ),
        joined,
    )
    _assign_wahoo_provider_duplicates(
        entries, duplicate_of, intervals_window, joined, wahoo_joined
    )
    return duplicate_of, exact


def _assign_exact(
    entries: tuple[_Entry, ...],
    duplicate_of: dict[int, int],
    taken: dict[ProviderId, set[int]],
) -> set[int]:
    """Join each upstream record to the Intervals.icu copy that names it.

    ``taken`` holds, per upstream provider, the sessions that already have a
    record of it. Copies are visited in record order; an upstream record named by
    several copies joins the first, and a session takes one record per provider.
    """
    upstream_index = {
        (entry.record.provenance.provider, entry.record.activity_id): index
        for index, entry in enumerate(entries)
        if entry.record.provenance.provider in taken
    }
    exact: set[int] = set()
    for index, entry in enumerate(entries):
        ref = entry.record.external_ref
        if ref is None or not _is_intervals(entry.record):
            continue
        source = upstream_index.get((ref.upstream, ref.upstream_id))
        if source is None or source in duplicate_of:
            continue
        primary = duplicate_of.get(index, index)
        if primary in taken[ref.upstream]:
            continue
        duplicate_of[source] = primary
        taken[ref.upstream].add(primary)
        exact.add(source)
    return exact


def _assign_wahoo_provider_duplicates(
    entries: tuple[_Entry, ...],
    duplicate_of: dict[int, int],
    intervals_window: _WallWindow,
    garmin_joined: set[int],
    wahoo_joined: set[int],
) -> None:
    """Join Wahoo-provider records to Intervals.icu copies, then Garmin records to Wahoo."""
    wahoo = [
        index
        for index, entry in enumerate(entries)
        if entry.record.provenance.provider is ProviderId.WAHOO
    ]
    _assign_pairs(
        entries,
        duplicate_of,
        wahoo,
        intervals_window,
        _wahoo_intervals_cost,
        wahoo_joined,
    )
    wahoo_rides = [
        index for index in wahoo if entries[index].record.sport is Sport.RIDE
    ]
    garmin_rides = [
        index
        for index, entry in enumerate(entries)
        if entry.record.provenance.provider is ProviderId.GARMIN
        and entry.record.sport is Sport.RIDE
        and index not in duplicate_of
    ]
    _assign_pairs(
        entries,
        duplicate_of,
        garmin_rides,
        _WallWindow(entries, wahoo_rides),
        lambda garmin, wahoo_ride: _wahoo_copy_cost(wahoo_ride, garmin),
        garmin_joined,
    )


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
    entries: tuple[_Entry, ...], duplicate_of: dict[int, int], exact: set[int]
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
        # The record that joined the lead to the group sets the old anchor's kind.
        lead_kind = (
            ActivityLinkKind.EXACT if lead in exact else ActivityLinkKind.HEURISTIC
        )
        others = [index for index in sorted((anchor, *duplicates)) if index != lead]
        sessions.append(
            ActivitySession(
                entries[lead].record,
                tuple(entries[index].record for index in others),
                tuple(
                    lead_kind
                    if index == anchor and lead != anchor
                    else (
                        ActivityLinkKind.EXACT
                        if index in exact
                        else ActivityLinkKind.HEURISTIC
                    )
                    for index in others
                ),
            )
        )
    return tuple(sessions)


_LEAD_PROVIDER_RANK: Final = {
    provider: rank for rank, provider in enumerate(PROVIDER_PRECEDENCE)
}


def _lead_key(entries: tuple[_Entry, ...], index: int) -> tuple[int, int, int]:
    """Order a session's records for its primary: Wahoo, Garmin, Intervals.icu last.

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


def _garmin_intervals_cost(
    garmin: _Entry, intervals: _Entry, *, elapsed: bool = False
) -> float | None:
    start = _start_cost(garmin, intervals)
    if start is None:
        return None
    if garmin.family != intervals.family and _OTHER_FAMILY not in (
        garmin.family,
        intervals.family,
    ):
        return None
    gaps = _garmin_measurement_gaps(garmin.record, intervals.record, elapsed=elapsed)
    return None if gaps is None else _mean((start, *gaps))


def _wahoo_intervals_cost(wahoo: _Entry, intervals: _Entry) -> float | None:
    if intervals.record.provenance.recorded_by is not RecordingOrigin.WAHOO:
        return None
    # Same start, family and tolerance rules as a Garmin record against Intervals.
    return _garmin_intervals_cost(wahoo, intervals)


def _garmin_measurement_gaps(
    garmin: ActivityRecord, intervals: ActivityRecord, *, elapsed: bool = False
) -> list[float] | None:
    """Return the relative gap of each comparison, or None unless every one agrees."""
    gaps: list[float | None] = []
    # Both durations follow the canonical rule (moving time first). Providers
    # measure moving time differently, so the Garmin moving duration stays a
    # second candidate, and the elapsed pass compares the two elapsed times.
    garmin_durations = [
        value
        for value in (garmin.duration_s, garmin.moving_duration_s)
        if value is not None
    ]
    if garmin_durations and intervals.duration_s is not None:
        base = intervals.duration_s
        candidates = [
            _relative_gap(value, base, DURATION_FLOOR_S, base)
            for value in garmin_durations
        ]
        elapsed_s = intervals.elapsed_duration_s
        own_elapsed_s = garmin.elapsed_duration_s
        if elapsed and own_elapsed_s is not None and elapsed_s is not None:
            candidates.append(
                _relative_gap(own_elapsed_s, elapsed_s, DURATION_FLOOR_S, elapsed_s)
            )
        agreeing = [gap for gap in candidates if gap is not None]
        gaps.append(min(agreeing) if agreeing else None)
    # Only the distance pair skips non-positive values, as the legacy rule does.
    if garmin.distance_m and intervals.distance_m:
        gaps.append(
            _relative_gap(
                garmin.distance_m,
                intervals.distance_m,
                DISTANCE_FLOOR_M,
                intervals.distance_m,
            )
        )
    agreed = [gap for gap in gaps if gap is not None]
    if not gaps or len(agreed) < len(gaps):
        return None
    return agreed


def _wahoo_copy_cost(wahoo: _Entry, copy: _Entry) -> float | None:
    start = _start_cost(wahoo, copy)
    if start is None:
        return None
    left, right = wahoo.record, copy.record
    if (
        left.duration_s is None
        or right.duration_s is None
        or left.distance_m is None
        or right.distance_m is None
    ):
        return None
    if min(left.duration_s, right.duration_s) <= 0:
        return None
    if min(left.distance_m, right.distance_m) <= 0:
        return None
    duration = _relative_gap(
        left.duration_s,
        right.duration_s,
        DURATION_FLOOR_S,
        max(left.duration_s, right.duration_s),
    )
    distance = _relative_gap(
        left.distance_m,
        right.distance_m,
        DISTANCE_FLOOR_M,
        max(left.distance_m, right.distance_m),
    )
    if duration is None or distance is None:
        return None
    return _mean((start, duration, distance))


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
