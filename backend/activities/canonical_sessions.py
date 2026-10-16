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
rules. That second pass only joins an Intervals.icu session that no Garmin
record joined yet: two short walks of similar length within 30 minutes would
otherwise each claim the earlier copy.

Assignment is first match wins in deterministic order (start instant, then
provider, then activity id). A record is a duplicate of at most one primary, and
every input record appears in exactly one session. A Garmin-provider duplicate
of a Garmin-recorded Intervals copy joins that copy's Wahoo session.

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
from collections.abc import Iterable, Sequence
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

__all__ = ["ActivitySession", "bundle_sessions"]

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
    entries = tuple(
        _Entry(record, _wall_clock(record, zone), legacy_activity_family(record.sport))
        for record in sorted(records, key=_order_key)
    )
    duplicate_of = _assign_duplicates(entries)
    return _sessions(entries, duplicate_of)


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

    Each search takes the lowest-indexed matching candidate. That is the first match
    in start order, which is what a scan over every candidate would have found.
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
    wahoo_window = _WallWindow(entries, wahoo_rides)
    for copy_index in garmin_ride_copies:
        copy = entries[copy_index]
        matches = [
            index
            for index in wahoo_window.near(copy.wall)
            if _wahoo_and_garmin_copy_match(entries[index], copy)
        ]
        if matches:
            duplicate_of[copy_index] = min(matches)

    intervals = [
        index for index, entry in enumerate(entries) if _is_intervals(entry.record)
    ]
    intervals_window = _WallWindow(entries, intervals)
    joined: set[int] = set()
    unmatched: list[int] = []
    for index, entry in enumerate(entries):
        if entry.record.provenance.provider is not ProviderId.GARMIN:
            continue
        matches = [
            target_index
            for target_index in intervals_window.near(entry.wall)
            if _garmin_matches_intervals(entry, entries[target_index])
        ]
        if matches:
            target_index = min(matches)
            duplicate_of[index] = duplicate_of.get(target_index, target_index)
            joined.add(duplicate_of[index])
        else:
            unmatched.append(index)
    for index in unmatched:
        entry = entries[index]
        matches = [
            target_index
            for target_index in intervals_window.near(entry.wall)
            if duplicate_of.get(target_index, target_index) not in joined
            and _garmin_matches_intervals(entry, entries[target_index], elapsed=True)
        ]
        if matches:
            target_index = min(matches)
            duplicate_of[index] = duplicate_of.get(target_index, target_index)
            joined.add(duplicate_of[index])
    _assign_wahoo_provider_duplicates(entries, duplicate_of, intervals_window)
    return duplicate_of


def _assign_wahoo_provider_duplicates(
    entries: tuple[_Entry, ...],
    duplicate_of: dict[int, int],
    intervals_window: _WallWindow,
) -> None:
    """Join Wahoo-provider records to Intervals.icu copies, then Garmin records to Wahoo."""
    for index, entry in enumerate(entries):
        if entry.record.provenance.provider is not ProviderId.WAHOO:
            continue
        matches = [
            target_index
            for target_index in intervals_window.near(entry.wall)
            if _wahoo_matches_intervals(entry, entries[target_index])
        ]
        if matches:
            target_index = min(matches)
            duplicate_of[index] = duplicate_of.get(target_index, target_index)
    wahoo_rides = [
        index
        for index, entry in enumerate(entries)
        if entry.record.provenance.provider is ProviderId.WAHOO
        and entry.record.sport is Sport.RIDE
    ]
    wahoo_window = _WallWindow(entries, wahoo_rides)
    for index, entry in enumerate(entries):
        if (
            entry.record.provenance.provider is not ProviderId.GARMIN
            or entry.record.sport is not Sport.RIDE
            or index in duplicate_of
        ):
            continue
        matches = [
            target_index
            for target_index in wahoo_window.near(entry.wall)
            if _wahoo_and_garmin_copy_match(entries[target_index], entry)
        ]
        if matches:
            target_index = min(matches)
            duplicate_of[index] = duplicate_of.get(target_index, target_index)


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


def _garmin_matches_intervals(
    garmin: _Entry, intervals: _Entry, *, elapsed: bool = False
) -> bool:
    if abs(garmin.wall - intervals.wall) > START_WINDOW:
        return False
    if garmin.family != intervals.family and _OTHER_FAMILY not in (
        garmin.family,
        intervals.family,
    ):
        return False
    return _garmin_measurements_agree(garmin.record, intervals.record, elapsed=elapsed)


def _wahoo_matches_intervals(wahoo: _Entry, intervals: _Entry) -> bool:
    if not _is_intervals(intervals.record):
        return False
    if intervals.record.provenance.recorded_by is not RecordingOrigin.WAHOO:
        return False
    # Same start, family and tolerance rules as a Garmin record against Intervals.
    return _garmin_matches_intervals(wahoo, intervals)


def _garmin_measurements_agree(
    garmin: ActivityRecord, intervals: ActivityRecord, *, elapsed: bool = False
) -> bool:
    compared = 0
    agreed = 0
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
        compared += 1
        if any(
            _close(value, intervals.duration_s, DURATION_FLOOR_S, intervals.duration_s)
            for value in garmin_durations
        ) or (elapsed and _elapsed_times_agree(garmin, intervals)):
            agreed += 1
    # Only the distance pair skips non-positive values, as the legacy rule does.
    if garmin.distance_m and intervals.distance_m:
        compared += 1
        if _close(
            garmin.distance_m,
            intervals.distance_m,
            DISTANCE_FLOOR_M,
            intervals.distance_m,
        ):
            agreed += 1
    return compared > 0 and agreed == compared


def _elapsed_times_agree(garmin: ActivityRecord, intervals: ActivityRecord) -> bool:
    elapsed = intervals.elapsed_duration_s
    return (
        garmin.duration_s is not None
        and elapsed is not None
        and _close(garmin.duration_s, elapsed, DURATION_FLOOR_S, elapsed)
    )


def _wahoo_and_garmin_copy_match(wahoo: _Entry, copy: _Entry) -> bool:
    if abs(wahoo.wall - copy.wall) > START_WINDOW:
        return False
    left, right = wahoo.record, copy.record
    if (
        left.duration_s is None
        or right.duration_s is None
        or left.distance_m is None
        or right.distance_m is None
    ):
        return False
    if min(left.duration_s, right.duration_s) <= 0:
        return False
    if min(left.distance_m, right.distance_m) <= 0:
        return False
    return _close(
        left.duration_s,
        right.duration_s,
        DURATION_FLOOR_S,
        max(left.duration_s, right.duration_s),
    ) and _close(
        left.distance_m,
        right.distance_m,
        DISTANCE_FLOOR_M,
        max(left.distance_m, right.distance_m),
    )


def _close(value: float, other: float, floor: float, base: float) -> bool:
    return abs(value - other) <= max(floor, base * RELATIVE_TOLERANCE)
