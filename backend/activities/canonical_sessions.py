"""Bundle canonical activity records into sessions with the legacy duplicate rules.

This reproduces ``backend.activities.duplicates`` over ``ActivityRecord`` values:

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
merge. Candidate pairs are taken closest first, by the start gap as a share of
the window plus each compared measurement's gap as a share of its tolerance;
equal costs fall back to the deterministic order (start instant, then provider,
then activity id). A record is a duplicate of at most one primary, and every
input record appears in exactly one session. A Garmin-provider duplicate of a
Garmin-recorded Intervals copy joins that copy's Wahoo session.

Wahoo-provider records (direct Wahoo ingest) join the same bundling:

* a Wahoo-provider record duplicates an Intervals.icu record recorded by Wahoo when
  the starts are within 30 minutes, the sport families agree (or either is
  "other"), and every comparable measurement agrees (the Garmin-versus-Intervals
  tolerances apply). Canonical records carry no provider file key, so this link is
  always heuristic.
* a Garmin-provider cycling ride that matched no Intervals.icu record duplicates a
  Wahoo-provider cycling ride under the Wahoo/Garmin-copy rule above. A Wahoo
  record that is itself a duplicate passes its own primary on to the Garmin record,
  so Intervals.icu stays primary over Wahoo and Wahoo over Garmin.

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
from typing import Final

from backend.canonical.records import ActivityRecord
from backend.canonical.sports import legacy_activity_family
from backend.canonical.vocabulary import (
    ActivityLinkKind,
    ProviderId,
    RecordingOrigin,
    Sport,
)

__all__ = [
    "ActivitySession",
    "bundle_sessions",
    "garmin_duplicates_intervals",
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
    duplicate_of = _assign_duplicates(entries)
    return _sessions(entries, duplicate_of)


def wahoo_garmin_copy_match(
    wahoo: ActivityRecord, copy: ActivityRecord, *, zone: tzinfo
) -> bool:
    """Return True when ``copy`` is a Garmin-recorded copy of the Wahoo ride ``wahoo``.

    Applies the Wahoo/Garmin ride rule on the athlete's wall clock ``zone``; the
    caller decides which records are Wahoo- and Garmin-recorded Intervals.icu rides.
    """
    return _wahoo_and_garmin_copy_match(_entry(wahoo, zone), _entry(copy, zone))


def garmin_duplicates_intervals(
    garmin: ActivityRecord, intervals: ActivityRecord, *, zone: tzinfo
) -> bool:
    """Return True when the pairwise Garmin-versus-Intervals.icu duplicate rule holds.

    This is the rule alone, with the elapsed-time alternative, as the sync's raw
    duplicate check applies it; it ignores which session either record joined.
    """
    cost = _garmin_intervals_cost(
        _entry(garmin, zone), _entry(intervals, zone), elapsed=True
    )
    return cost is not None


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


def _assign_duplicates(entries: tuple[_Entry, ...]) -> dict[int, int]:
    """Map each duplicate's index to the index of its primary.

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
    # Sessions that already hold a Garmin-provider record.
    joined: set[int] = set()
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
    _assign_wahoo_provider_duplicates(entries, duplicate_of, intervals_window, joined)
    return duplicate_of


def _assign_wahoo_provider_duplicates(
    entries: tuple[_Entry, ...],
    duplicate_of: dict[int, int],
    intervals_window: _WallWindow,
    garmin_joined: set[int],
) -> None:
    """Join Wahoo-provider records to Intervals.icu copies, then Garmin records to Wahoo."""
    wahoo = [
        index
        for index, entry in enumerate(entries)
        if entry.record.provenance.provider is ProviderId.WAHOO
    ]
    _assign_pairs(
        entries, duplicate_of, wahoo, intervals_window, _wahoo_intervals_cost, set()
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
    """Join each source to at most one target session, closest pair first.

    ``cost`` returns None when the rule rejects the pair. A session in ``taken``
    already holds a record of the sources' kind and accepts no other; each join
    adds its session. Pairs are taken greedily by cost, ties by source then target
    order, which is start instant, provider and activity id. For the few records
    in one start window, greedy equals the optimal assignment in practice.
    """
    pairs = sorted(
        (pair_cost, source, target)
        for source in sources
        for target in targets.near(entries[source].wall)
        if (pair_cost := cost(entries[source], entries[target])) is not None
    )
    for _, source, target in pairs:
        primary = duplicate_of.get(target, target)
        if source in duplicate_of or primary in taken:
            continue
        duplicate_of[source] = primary
        taken.add(primary)


def _sessions(
    entries: tuple[_Entry, ...], duplicate_of: dict[int, int]
) -> tuple[ActivitySession, ...]:
    members: dict[int, list[ActivityRecord]] = {
        index: [] for index in range(len(entries)) if index not in duplicate_of
    }
    for index in range(len(entries)):
        if index in duplicate_of:
            members[duplicate_of[index]].append(entries[index].record)
    # Every rule is a heuristic comparison: provider records carry no shared file key.
    return tuple(
        ActivitySession(
            entries[primary].record,
            tuple(duplicates),
            (ActivityLinkKind.HEURISTIC,) * len(duplicates),
        )
        for primary, duplicates in members.items()
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
    measured = _garmin_measurements_cost(
        garmin.record, intervals.record, elapsed=elapsed
    )
    return None if measured is None else start + measured


def _wahoo_intervals_cost(wahoo: _Entry, intervals: _Entry) -> float | None:
    if intervals.record.provenance.recorded_by is not RecordingOrigin.WAHOO:
        return None
    # Same start, family and tolerance rules as a Garmin record against Intervals.
    return _garmin_intervals_cost(wahoo, intervals)


def _garmin_measurements_cost(
    garmin: ActivityRecord, intervals: ActivityRecord, *, elapsed: bool = False
) -> float | None:
    """Return the summed relative gaps, or None unless every comparison agrees."""
    gaps: list[float | None] = []
    # Garmin ``duration`` is elapsed time, while the Intervals.icu duration is
    # usually moving time (elapsed only when moving time is missing), so the
    # Garmin moving duration is a second candidate. The elapsed pass also accepts
    # the Garmin duration against the Intervals.icu elapsed time.
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
        if elapsed and garmin.duration_s is not None and elapsed_s is not None:
            candidates.append(
                _relative_gap(garmin.duration_s, elapsed_s, DURATION_FLOOR_S, elapsed_s)
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
    if not gaps or None in gaps:
        return None
    return sum(gap for gap in gaps if gap is not None)


def _wahoo_and_garmin_copy_match(wahoo: _Entry, copy: _Entry) -> bool:
    return _wahoo_copy_cost(wahoo, copy) is not None


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
    return start + duration + distance


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
