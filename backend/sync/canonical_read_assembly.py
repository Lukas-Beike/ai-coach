"""Compose the canonical read selector over the table readers.

The selector takes the athlete's time zone from the saved profile, the zone the
backfill state records, and asks the snapshot reader only whether the stored
Intervals.icu snapshot has a compact-only activity gap.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import tzinfo
from functools import partial
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from backend.athlete.profile import timezone_name
from backend.db.repositories import KeyValueRepository
from backend.sync.canonical_backfill import completed_observation_versions
from backend.sync.canonical_read_selector import CanonicalReadSelector
from backend.sync.canonical_table_reader import CanonicalTableReader


class AthleteTimezoneReader(Protocol):
    def get(self) -> dict[str, Any]: ...


def build_canonical_read(
    *,
    key_values: KeyValueRepository,
    profile: AthleteTimezoneReader,
    compact_only: Callable[[Any], bool],
) -> CanonicalReadSelector:
    return CanonicalReadSelector(
        table=CanonicalTableReader(),
        reprojecting_table=CanonicalTableReader(
            oldest_versions=partial(completed_observation_versions, key_values)
        ),
        key_values=key_values,
        zone=_athlete_zone(profile),
        compact_only=compact_only,
    )


def _athlete_zone(profile: AthleteTimezoneReader) -> Callable[[Any], tzinfo]:
    def zone(_db: Any) -> tzinfo:
        return ZoneInfo(timezone_name(profile.get().get("timezone")))

    return zone
