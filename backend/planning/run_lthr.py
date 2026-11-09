"""The run threshold HR in effect on a date, for heart-rate caps.

Local zones first, then the dated Garmin watch zone set, then the other resolved
thresholds, as the resolved ``LoadThresholds`` of the run sport give it. Never
estimated: ``None`` when no threshold HR is known. Dependencies are explicit; the
owner reads the thresholds, this class only looks one date up.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.vocabulary import Sport
from backend.planning.hr_cap_sync import resync_ids
from backend.planning.load_checks import LoadThresholds
from backend.planning.sport import planned_sport_environment


class RunLthr:
    """Look the run threshold HR up for a unit's date or for a plain date."""

    def __init__(
        self,
        thresholds: Callable[[], LoadThresholds | None],
        today: Callable[[], date],
        key_values: Any,
    ) -> None:
        self._thresholds = thresholds
        self._today = today
        self._key_values = key_values

    def resolver(self) -> Callable[[Mapping[str, Any]], float | None]:
        """One snapshot of the resolved thresholds as a lookup for a unit's date."""
        today = self._today()
        thresholds = self._thresholds()

        def lthr_for(unit: Mapping[str, Any]) -> float | None:
            if thresholds is None or thresholds.unavailable:
                return None
            day = _unit_day(unit) or today
            environment = planned_sport_environment(unit)[1]
            return thresholds.for_sport(Sport.RUN, environment, day).zones.lthr

        return lthr_for

    def on(self, day: date | None) -> float | None:
        """The run threshold HR on ``day`` (today when None)."""
        when = day or self._today()
        return self.resolver()({"date": when.isoformat()})

    def resync(self, db: Any, payloads: list[dict[str, Any]]) -> set[str]:
        """Synced capped run units whose bpm range moved only with the threshold HR."""
        if not any(payload.get("hr_cap") for payload in payloads):
            return set()
        return resync_ids(self._key_values, db, payloads, self.resolver())


def _unit_day(unit: Mapping[str, Any]) -> date | None:
    try:
        return date.fromisoformat(
            iso_date_prefix(str(unit.get("date") or unit.get("starts_at_local") or ""))
        )
    except ValueError:
        return None
