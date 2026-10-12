"""Content-free parity check: the legacy projection and the canonical tables must agree.

The check reads both sources over their full range and compares them by identity.
Activities are identified by (provider, provider activity id). Observations are
identified by their natural key, which the tables enforce as unique. Results are
counts only. A report never carries ids, names, dates or values.

Rules:

- Identities are counted once each. The tables keep one row per natural key, so
  identical served values on one key (for example two Garmin FTP sections with the
  same number on the same day) are one identity. Different served values on one key
  are ``differing``, because the tables cannot represent both.
- Served content is what a reader returns: for activities the whole record, for
  observations the value, observed time, sport, source label, source kind and
  recording origin. The source fields are user-visible, so a changed label fails.
- ``retrieved_at`` is not compared for observations, and Garmin fetch times are
  normalised before activities are compared. The legacy projection serves the
  snapshot's sync time, while the tables serve each row's own fetch time. That
  difference is intended.
- History: the backfill and dual-write keep records that the newest snapshot no
  longer holds, for activities and observations alike. Table identities dated
  outside the range the legacy projection covers for that provider (athlete-local
  date for activities, observed day for observations) are counted as
  ``table_history`` and do not fail the check. A provider with no legacy records
  for that kind has no range, so its table identities are ``extra_in_table``
  (fail closed). Table identities inside the range that the legacy projection
  lacks are also ``extra_in_table``.
- Fingerprints: for each Intervals.icu activity present in both the stored raw record
  and the newest snapshot, ``summary_fingerprint`` of the two must agree. Stored
  analyses are keyed by that fingerprint, so a changed raw activity must fail.
- The check passes only when every counter that is not ``matched`` or
  ``table_history`` is zero, the shared order is identical, and no fingerprint
  differs.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, tzinfo
from typing import Any, Final, Protocol

from backend.canonical.local_time import local_date
from backend.canonical.records import ActivityRecord, Observation
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.db import canonical_store
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND
from backend.runtime.ports import (
    ActivityReader,
    ActivityRowReader,
    ObservationReader,
    ProviderSnapshotReader,
)

_RAW_ACTIVITIES_KEY: Final = "raw_provider_data"
_ACTIVITY_LIST_KEY: Final = "activities"
type _Ranges = Mapping[str, tuple[date, date]]


class CanonicalReader(ActivityReader, ActivityRowReader, ObservationReader, Protocol):
    """The reads a canonical source serves: activities, raw rows and observations.

    The parity check compares activities and observations only.
    """


@dataclass(slots=True)
class ComparisonCounts:
    """How many identities matched, were missing, extra, or differing."""

    matched: int = 0
    missing_in_table: int = 0
    extra_in_table: int = 0
    differing: int = 0
    table_history: int = 0

    @property
    def failures(self) -> int:
        return self.missing_in_table + self.extra_in_table + self.differing

    def as_dict(self) -> dict[str, int]:
        return {
            "matched": self.matched,
            "missing_in_table": self.missing_in_table,
            "extra_in_table": self.extra_in_table,
            "differing": self.differing,
            "table_history": self.table_history,
        }


@dataclass(frozen=True, slots=True)
class ParityReport:
    """Counts for every provider's activities and every metric kind's observations."""

    activities: Mapping[str, ComparisonCounts]
    observations: Mapping[str, ComparisonCounts]
    ordering_equal: bool
    fingerprint_checked: int
    fingerprint_mismatches: int

    @property
    def passed(self) -> bool:
        counts = (*self.activities.values(), *self.observations.values())
        return (
            self.ordering_equal
            and self.fingerprint_mismatches == 0
            and all(item.failures == 0 for item in counts)
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "ordering_equal": self.ordering_equal,
            "fingerprint": {
                "checked": self.fingerprint_checked,
                "mismatches": self.fingerprint_mismatches,
            },
            "activities": {
                name: counts.as_dict() for name, counts in self.activities.items()
            },
            "observations": {
                name: counts.as_dict() for name, counts in self.observations.items()
            },
        }


class CanonicalParity:
    """Compares the legacy projection with the tables. The caller owns the transaction."""

    def __init__(
        self,
        *,
        legacy: CanonicalReader,
        table: CanonicalReader,
        snapshots: ProviderSnapshotReader,
        fingerprint: Callable[[dict[str, Any]], str],
        zone: Callable[[Any], tzinfo],
    ) -> None:
        self._legacy = legacy
        self._table = table
        self._snapshots = snapshots
        self._fingerprint = fingerprint
        self._zone = zone

    def check(self, db: Any) -> ParityReport:
        activities, activity_order_ok = _compare_activities(
            self._legacy.activities(db),
            self._table.activities(db),
            self._zone(db),
        )
        observations: dict[str, ComparisonCounts] = {}
        observation_order_ok = True
        for kind in MetricKind:
            counts, ordered = _compare_observations(
                self._legacy.observations(db, kind),
                self._table.observations(db, kind),
            )
            observations[kind.value] = counts
            observation_order_ok = observation_order_ok and ordered
        checked, mismatches = self._fingerprints(db)
        return ParityReport(
            activities=activities,
            observations=observations,
            ordering_equal=activity_order_ok and observation_order_ok,
            fingerprint_checked=checked,
            fingerprint_mismatches=mismatches,
        )

    def _fingerprints(self, db: Any) -> tuple[int, int]:
        stored = canonical_store.active_record_payloads(
            db, provider=ProviderId.INTERVALS.value, record_kind=ACTIVITY_RECORD_KIND
        )
        raw = _raw_activities(self._snapshots.latest_snapshot(db))
        checked = 0
        mismatches = 0
        for activity_id, text in stored.items():
            if activity_id not in raw:
                continue
            checked += 1
            if self._fingerprint(json.loads(text)) != self._fingerprint(
                raw[activity_id]
            ):
                mismatches += 1
        return checked, mismatches


def _raw_activities(snapshot: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Return the newest snapshot's raw activities by provider id text."""
    if not isinstance(snapshot, Mapping):
        return {}
    raw = snapshot.get(_RAW_ACTIVITIES_KEY)
    rows = raw.get(_ACTIVITY_LIST_KEY) if isinstance(raw, Mapping) else None
    if not isinstance(rows, list):
        return {}
    return {
        str(row["id"]): row
        for row in rows
        if isinstance(row, dict) and row.get("id") is not None
    }


def _activity_content(record: ActivityRecord) -> tuple[Hashable, ...]:
    """What a reader is served for one activity, without the Garmin fetch time."""
    provenance = record.provenance
    fetched = (
        None if provenance.provider is ProviderId.GARMIN else provenance.retrieved_at
    )
    return (
        record.sport,
        record.environment,
        record.started_at,
        record.duration_s,
        record.distance_m,
        record.load,
        record.load_model,
        record.avg_hr,
        record.avg_power,
        record.name,
        provenance.source_kind,
        provenance.source_record_id,
        provenance.recorded_by,
        provenance.label,
        fetched,
    )


def _observation_content(observation: Observation) -> tuple[Hashable, ...]:
    """What a reader is served for one observation.

    Value, observed time, sport and the user-visible source (label, source kind and
    recording origin) are compared. ``retrieved_at`` is not, for the reason in the
    module docstring: the legacy projection and the tables stamp fetch times
    differently by design.
    """
    provenance = observation.provenance
    return (
        observation.value,
        observation.observed_at,
        observation.sport,
        provenance.label,
        provenance.source_kind,
        provenance.recorded_by,
    )


def _provider_name(provider: ProviderId | None) -> str:
    return "" if provider is None else provider.value


def _activity_key(record: ActivityRecord) -> tuple[str, str]:
    return _provider_name(record.provenance.provider), record.activity_id


def _group[K: Hashable, T](
    items: Iterable[T], key: Callable[[T], K]
) -> dict[K, list[T]]:
    groups: dict[K, list[T]] = defaultdict(list)
    for item in items:
        groups[key(item)].append(item)
    return groups


def _same_shared_order[K: Hashable](legacy: Sequence[K], table: Sequence[K]) -> bool:
    """Compare the order of the identities that both sides hold, each identity once."""
    in_table = set(table)
    in_legacy = set(legacy)
    shared_legacy = dict.fromkeys(key for key in legacy if key in in_table)
    shared_table = dict.fromkeys(key for key in table if key in in_legacy)
    return list(shared_legacy) == list(shared_table)


def _ranges(entries: Iterable[tuple[str, date]]) -> dict[str, tuple[date, date]]:
    """Return the first and last day per provider name."""
    days: dict[str, list[date]] = defaultdict(list)
    for name, day in entries:
        days[name].append(day)
    return {name: (min(values), max(values)) for name, values in days.items()}


def _outside_legacy_range(
    ranges: _Ranges, provider: ProviderId | None, day: date
) -> bool:
    """True when legacy covers this provider and the day falls outside its range.

    No legacy range for the provider means no allowance: the identity is extra.
    """
    bounds = ranges.get(_provider_name(provider))
    return bounds is not None and not (bounds[0] <= day <= bounds[1])


def _compare_activities(
    legacy: Sequence[ActivityRecord],
    table: Sequence[ActivityRecord],
    zone: tzinfo,
) -> tuple[dict[str, ComparisonCounts], bool]:
    counts = {
        provider.value: ComparisonCounts()
        for provider in (ProviderId.INTERVALS, ProviderId.GARMIN)
    }
    legacy_groups = _group(legacy, _activity_key)
    table_groups = _group(table, _activity_key)
    ranges = _ranges(
        (_provider_name(r.provenance.provider), local_date(r.started_at, zone))
        for r in legacy
    )
    for key in legacy_groups.keys() | table_groups.keys():
        bucket = counts.setdefault(key[0], ComparisonCounts())
        table_items = table_groups.get(key, [])
        outside = bool(table_items) and _outside_legacy_range(
            ranges,
            table_items[0].provenance.provider,
            local_date(table_items[0].started_at, zone),
        )
        _tally(
            bucket,
            [_activity_content(r) for r in legacy_groups.get(key, [])],
            [_activity_content(r) for r in table_items],
            outside_legacy_range=outside,
        )
    ordered = _same_shared_order(
        [_activity_key(r) for r in legacy], [_activity_key(r) for r in table]
    )
    return counts, ordered


def _compare_observations(
    legacy: Sequence[Observation], table: Sequence[Observation]
) -> tuple[ComparisonCounts, bool]:
    ranges = _ranges(
        (_provider_name(o.provenance.provider), o.observed_on) for o in legacy
    )
    legacy_groups = _group(legacy, canonical_store.observation_natural_key)
    table_groups = _group(table, canonical_store.observation_natural_key)
    counts = ComparisonCounts()
    for key in legacy_groups.keys() | table_groups.keys():
        table_items = table_groups.get(key, [])
        outside = bool(table_items) and _outside_legacy_range(
            ranges, table_items[0].provenance.provider, table_items[0].observed_on
        )
        _tally(
            counts,
            [_observation_content(o) for o in legacy_groups.get(key, [])],
            [_observation_content(o) for o in table_items],
            outside_legacy_range=outside,
        )
    ordered = _same_shared_order(
        [canonical_store.observation_natural_key(o) for o in legacy],
        [canonical_store.observation_natural_key(o) for o in table],
    )
    return counts, ordered


def _tally[T: Hashable](
    counts: ComparisonCounts,
    legacy_items: Sequence[T],
    table_items: Sequence[T],
    *,
    outside_legacy_range: bool = False,
) -> None:
    """Count one identity by comparing what each side serves for it as sets."""
    if not table_items:
        counts.missing_in_table += 1
    elif not legacy_items:
        if outside_legacy_range:
            counts.table_history += 1
        else:
            counts.extra_in_table += 1
    elif set(legacy_items) == set(table_items):
        counts.matched += 1
    else:
        counts.differing += 1
