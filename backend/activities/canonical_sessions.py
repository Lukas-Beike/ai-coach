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

Assignment is first match wins in deterministic order (start instant, then
provider, then activity id). A record is a duplicate of at most one primary, and
every input record appears in exactly one session. A Garmin-provider duplicate
of a Garmin-recorded Intervals copy joins that copy's Wahoo session.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from typing import Final

from backend.canonical.records import ActivityRecord
from backend.canonical.sports import legacy_activity_family
from backend.canonical.vocabulary import ProviderId, RecordingOrigin, Sport

__all__ = ["ActivitySession", "bundle_sessions"]

START_WINDOW: Final = timedelta(minutes=30)
DURATION_FLOOR_S: Final = 120.0
DISTANCE_FLOOR_M: Final = 500.0
RELATIVE_TOLERANCE: Final = 0.10
_OTHER_FAMILY: Final = "other"


@dataclass(frozen=True, slots=True)
class ActivitySession:
    """One activity and the records that duplicate it."""

    primary: ActivityRecord
    duplicates: tuple[ActivityRecord, ...]


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


def _assign_duplicates(entries: tuple[_Entry, ...]) -> dict[int, int]:
    """Map each duplicate's index to the index of its primary."""
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
    for copy_index in garmin_ride_copies:
        for wahoo_index in wahoo_rides:
            if _wahoo_and_garmin_copy_match(entries[wahoo_index], entries[copy_index]):
                duplicate_of[copy_index] = wahoo_index
                break

    for index, entry in enumerate(entries):
        if entry.record.provenance.provider is not ProviderId.GARMIN:
            continue
        for target_index, target in enumerate(entries):
            if _is_intervals(target.record) and _garmin_matches_intervals(
                entry, target
            ):
                duplicate_of[index] = duplicate_of.get(target_index, target_index)
                break
    return duplicate_of


def _sessions(
    entries: tuple[_Entry, ...], duplicate_of: dict[int, int]
) -> tuple[ActivitySession, ...]:
    members: dict[int, list[ActivityRecord]] = {
        index: [] for index in range(len(entries)) if index not in duplicate_of
    }
    for index in range(len(entries)):
        if index in duplicate_of:
            members[duplicate_of[index]].append(entries[index].record)
    return tuple(
        ActivitySession(entries[primary].record, tuple(duplicates))
        for primary, duplicates in members.items()
    )


def _garmin_matches_intervals(garmin: _Entry, intervals: _Entry) -> bool:
    if abs(garmin.wall - intervals.wall) > START_WINDOW:
        return False
    if garmin.family != intervals.family and _OTHER_FAMILY not in (
        garmin.family,
        intervals.family,
    ):
        return False
    return _garmin_measurements_agree(garmin.record, intervals.record)


def _garmin_measurements_agree(
    garmin: ActivityRecord, intervals: ActivityRecord
) -> bool:
    compared = 0
    agreed = 0
    if garmin.duration_s is not None and intervals.duration_s is not None:
        compared += 1
        if _close(
            garmin.duration_s,
            intervals.duration_s,
            DURATION_FLOOR_S,
            intervals.duration_s,
        ):
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
