"""Garmin daily totals mapped to observations, served by a date-filtering reader."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, Sport
from backend.providers.garmin_health_mapping import map_garmin_health

RETRIEVED = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)


class MappedDailyReader:
    """Serves the observations the Garmin mapper produces from ``snapshot``."""

    def __init__(self, snapshot: dict[str, Any]) -> None:
        result = map_garmin_health(
            snapshot, zone=ZoneInfo("Europe/Berlin"), retrieved_at=RETRIEVED
        )
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
