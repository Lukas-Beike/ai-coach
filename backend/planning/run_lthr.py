"""The run threshold HR in effect on a date, for heart-rate caps.

Local zones first, then the dated Garmin watch zone set, then the other resolved
thresholds, as the resolved ``LoadThresholds`` of the run sport give it. Never
estimated: ``None`` when no threshold HR is known. Dependencies are explicit; the
owner reads the thresholds, this class only looks one date up; ``zones_resolver``
gives the whole run ``ZoneSettings`` of that date, for the Garmin run push, and
``resync`` names the pushed run units that resolve differently since (#2546).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from backend.activities.zone_settings import ZoneSettings
from backend.athlete.local_date import iso_date_prefix
from backend.canonical.vocabulary import Sport
from backend.errors import AppError
from backend.planning.load_checks import LoadThresholds
from backend.planning.push_state import (
    garmin_baselines,
    run_document,
    run_document_digest,
    run_sent_key,
)
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

    def zones_resolver(self) -> Callable[[Mapping[str, Any]], ZoneSettings | None]:
        """One snapshot of the resolved thresholds as a zones lookup for a unit's date."""
        today = self._today()
        thresholds = self._thresholds()

        def zones_for(unit: Mapping[str, Any]) -> ZoneSettings | None:
            if thresholds is None or thresholds.unavailable:
                return None
            day = _unit_day(unit) or today
            environment = planned_sport_environment(unit)[1]
            return thresholds.for_sport(Sport.RUN, environment, day)

        return zones_for

    def resolver(self) -> Callable[[Mapping[str, Any]], float | None]:
        """One snapshot of the resolved thresholds as a lookup for a unit's date."""
        zones_for = self.zones_resolver()

        def lthr_for(unit: Mapping[str, Any]) -> float | None:
            zones = zones_for(unit)
            return None if zones is None else zones.lthr

        return lthr_for

    def day_resolver(self) -> Callable[[date | None], float | None]:
        """One snapshot of the resolved thresholds as a lookup for a plain date."""
        lthr_for = self.resolver()
        today = self._today()
        return lambda day: lthr_for({"date": (day or today).isoformat()})

    def on(self, day: date | None) -> float | None:
        """The run threshold HR on ``day`` (today when None)."""
        return self.day_resolver()(day)

    def resync(self, db: Any, payloads: list[dict[str, Any]]) -> set[str]:
        """Run units linked at Garmin whose steps resolve differently than when pushed.

        A unit pushed before the digest was recorded, or whose document cannot be
        built now (the push reports that), is never flagged.
        """
        linked = garmin_baselines(db)
        zones_for = self.zones_resolver()
        moved: set[str] = set()
        for payload in payloads:
            local_id = str(payload.get("local_id") or "")
            if (
                local_id not in linked
                or planned_sport_environment(payload)[0] is not Sport.RUN
            ):
                continue
            sent = self._key_values.get(db, run_sent_key(local_id))
            if not sent:
                continue
            try:
                document = run_document(payload, zones_for(payload))
            except AppError, ValueError:
                continue
            if run_document_digest(document) != sent:
                moved.add(local_id)
        return moved


def _unit_day(unit: Mapping[str, Any]) -> date | None:
    try:
        return date.fromisoformat(
            iso_date_prefix(str(unit.get("date") or unit.get("starts_at_local") or ""))
        )
    except ValueError:
        return None
