"""Garmin daily totals mapped to observations, served by a date-filtering reader."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, Sport
from backend.performance.daily_health import (
    daily_energy_expenditure,
    read_daily_health_by_date,
)
from backend.providers.garmin_health_mapping import map_garmin_health

RETRIEVED = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)


class MappedDailyReader:
    """Serves the observations the Garmin mapper produces from ``snapshot``."""

    def __init__(self, snapshot: dict[str, Any], *, strict: bool = True) -> None:
        result = map_garmin_health(
            snapshot, zone=ZoneInfo("Europe/Berlin"), retrieved_at=RETRIEVED
        )
        if strict:
            assert not result.issues, result.issues
        self._by_kind: dict[MetricKind, list[Observation]] = defaultdict(list)
        for observation in result.records:
            self._by_kind[observation.kind].append(observation)
        self.calls: list[tuple[MetricKind, date | None, date | None]] = []

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        self.calls.append((kind, start, end))
        return tuple(
            item
            for item in self._by_kind[kind]
            if (start is None or item.observed_on >= start)
            and (end is None or item.observed_on <= end)
        )


def mapped_health(
    snapshot: dict[str, Any], *, strict: bool = True
) -> dict[str, dict[str, Any]]:
    """The canonical daily totals of the snapshot's mapped Garmin daily stats.

    ``strict`` fails on any mapping issue; tests of invalid input opt out.
    """
    return read_daily_health_by_date(MappedDailyReader(snapshot, strict=strict), None)


def mapped_expenditure(
    snapshot: dict[str, Any],
    requested_date: str,
    current_date: date,
    *,
    strict: bool = True,
) -> dict[str, Any]:
    """``daily_energy_expenditure`` with the snapshot's energy mapped first (#1415)."""
    health = mapped_health(snapshot, strict=strict)
    return daily_energy_expenditure(
        snapshot,
        requested_date,
        current_date,
        measured=health.get(requested_date, {}),
        measured_history=health,
    )
