"""Zone limits and thresholds used to color plan steps and recordings.

Defaults follow Intervals.icu's standard zones. Intervals.icu sport settings
replace them when they carry valid custom zone limits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from backend.canonical.sports import classify_sport_text
from backend.canonical.vocabulary import Sport

# Upper zone limits (Z1..Z6; everything above is Z7) as percent of the threshold.
POWER_ZONE_LIMITS = (55, 75, 90, 105, 120, 150)
HR_ZONE_LIMITS = (68, 83, 94, 105, 120, 150)
PACE_ZONE_LIMITS = (77.5, 87.7, 94.3, 100, 103.4, 111.5)
# Heart-rate steps are usually written as percent of max HR; threshold HR is
# about 90 % of it.
LTHR_SHARE_OF_MAX_HR = 0.9
_ZONE_COUNT = len(POWER_ZONE_LIMITS)


def percent_zone(percent: float, limits: tuple[float, ...]) -> int:
    return next((index for index, limit in enumerate(limits, 1) if percent <= limit), 7)


def _number(value: Any) -> float | None:
    return (
        float(value)
        if type(value) in {int, float} and math.isfinite(value) and value > 0
        else None
    )


def _limits(value: Any, divisor: float = 1.0) -> tuple[float, ...] | None:
    """The six ascending zone limits of an Intervals.icu zone list, or None.

    The seventh entry is the open upper end (999) and is not needed.
    """
    if not isinstance(value, list) or len(value) < _ZONE_COUNT:
        return None
    numbers = [_number(item) for item in value[:_ZONE_COUNT]]
    if any(item is None for item in numbers):
        return None
    limits = tuple(item / divisor for item in numbers if item is not None)
    ascending = all(left < right for left, right in pairwise(limits))
    return limits if ascending else None


@dataclass(frozen=True)
class ZoneSettings:
    """Thresholds and zone limits (percent of threshold) of one sport."""

    ftp: float | None = None
    lthr: float | None = None
    max_hr: float | None = None
    power_limits: tuple[float, ...] = POWER_ZONE_LIMITS
    hr_limits: tuple[float, ...] = HR_ZONE_LIMITS
    pace_limits: tuple[float, ...] = PACE_ZONE_LIMITS

    @classmethod
    def from_sport_settings(cls, settings: Any, sport: Sport) -> ZoneSettings:
        """Zone settings of the first Intervals.icu sport setting for ``sport``."""
        for setting in settings if isinstance(settings, list) else ():
            types = setting.get("types") if isinstance(setting, dict) else None
            if isinstance(types, list) and any(
                isinstance(item, str) and classify_sport_text(item) == sport
                for item in types
            ):
                return cls._from_setting(setting)
        return cls()

    @classmethod
    def _from_setting(cls, setting: dict[str, Any]) -> ZoneSettings:
        lthr = _number(setting.get("lthr"))
        # Heart-rate zones arrive as bpm limits; they need a threshold to become
        # a percentage of it.
        hr_limits = _limits(setting.get("hr_zones"), lthr / 100) if lthr else None
        return cls(
            ftp=_number(setting.get("ftp")),
            lthr=lthr,
            max_hr=_number(setting.get("max_hr")),
            power_limits=_limits(setting.get("power_zones")) or POWER_ZONE_LIMITS,
            hr_limits=hr_limits or HR_ZONE_LIMITS,
            pace_limits=_limits(setting.get("pace_zones")) or PACE_ZONE_LIMITS,
        )

    def power_zone(self, percent_of_ftp: float) -> int:
        return percent_zone(percent_of_ftp, self.power_limits)

    def pace_zone(self, percent_of_threshold: float) -> int:
        return percent_zone(percent_of_threshold, self.pace_limits)

    def hr_zone_of_lthr(self, percent_of_lthr: float) -> int:
        return percent_zone(percent_of_lthr, self.hr_limits)

    def hr_zone_of_max(self, percent_of_max_hr: float) -> int:
        """Zone of a percent-of-max-HR target, via bpm when the athlete's HR is known."""
        if self.max_hr:
            threshold = self.lthr or self.max_hr * LTHR_SHARE_OF_MAX_HR
            return self.hr_zone_of_lthr(percent_of_max_hr * self.max_hr / threshold)
        return self.hr_zone_of_lthr(percent_of_max_hr / LTHR_SHARE_OF_MAX_HR)

    def absolute_zone(self, unit: str, value: float) -> int | None:
        """Zone of an absolute watt or bpm target; needs the matching threshold."""
        if unit == "W" and self.ftp:
            return self.power_zone(value / self.ftp * 100)
        if unit == "bpm" and self.lthr:
            return self.hr_zone_of_lthr(value / self.lthr * 100)
        return None
