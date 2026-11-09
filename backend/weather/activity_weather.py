"""The weather during one activity, reduced from hourly Open-Meteo values (#1868).

Pure: no I/O, no coordinates. An hourly value at time ``h`` stands for the hour
around it (``h - 30 min`` to ``h + 30 min``), which is the linear interpolation
between two hours for a short activity; precipitation at ``h`` is the sum of the
preceding hour. The activity's value is the mean of the overlapping hours
weighted by overlap (precipitation: the amount that fell during the activity).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

from backend.providers.activity_weather import HOURLY_FIELDS

# The Historical Forecast API starts in 2022; earlier activities get no weather.
FIRST_DAY: Final = date(2022, 1, 1)
# Hours this close to now may still lack their stored forecast.
SETTLE: Final = timedelta(hours=48)
# Apparent temperature at which the Coach names heat (#1868).
HEAT_APPARENT_C: Final = 25.0
MIN_DURATION: Final = timedelta(minutes=1)
_HOUR: Final = timedelta(hours=1)
_HALF_HOUR: Final = timedelta(minutes=30)
_PRECIPITATION: Final = "precipitation"


@dataclass(frozen=True, slots=True)
class ActivityWeather:
    """Weather means over an activity; None where the hours had no value."""

    temperature_c: float | None
    apparent_temperature_c: float | None
    relative_humidity_pct: float | None
    wind_speed_mps: float | None
    precipitation_mm: float | None

    @property
    def has_value(self) -> bool:
        return any(
            value is not None
            for value in (
                self.temperature_c,
                self.apparent_temperature_c,
                self.relative_humidity_pct,
                self.wind_speed_mps,
                self.precipitation_mm,
            )
        )


def activity_window(
    start: datetime, duration_s: float | None
) -> tuple[datetime, datetime]:
    """The activity's UTC start and end; an unknown or tiny duration counts a minute."""
    first = start.astimezone(UTC)
    length = timedelta(seconds=max(duration_s or 0.0, MIN_DURATION.total_seconds()))
    return first, first + length


def utc_days(start: datetime, end: datetime) -> tuple[date, date]:
    """The UTC days to request: an hour's value reaches half an hour before the
    start, and the precipitation of the preceding hour up to an hour after the end."""
    return (start - _HALF_HOUR).date(), (end + _HOUR).date()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _overlap_s(
    first: datetime, last: datetime, start: datetime, end: datetime
) -> float:
    return max(0.0, (min(last, end) - max(first, start)).total_seconds())


def _mean(
    times: list[datetime | None],
    values: Any,
    start: datetime,
    end: datetime,
    field: str,
) -> float | None:
    if not isinstance(values, list) or len(values) != len(times):
        return None
    total = weight = 0.0
    for moment, raw in zip(times, values, strict=True):
        value = _number(raw)
        if moment is None or value is None:
            continue
        if field == _PRECIPITATION:
            span = (moment - _HOUR, moment)
            overlap = _overlap_s(*span, start, end)
            total += value * overlap / _HOUR.total_seconds()
        else:
            overlap = _overlap_s(moment - _HALF_HOUR, moment + _HALF_HOUR, start, end)
            total += value * overlap
        weight += overlap
    if weight <= 0:
        return None
    return round(total if field == _PRECIPITATION else total / weight, 2)


def _hour(text: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text)).replace(tzinfo=UTC)
    except ValueError:
        return None


def reduce_hourly(
    payload: Mapping[str, Any], start: datetime, end: datetime
) -> ActivityWeather | None:
    """Reduce the response's hourly rows to the activity, or None without any value."""
    hourly = payload.get("hourly")
    if not isinstance(hourly, Mapping) or not isinstance(hourly.get("time"), list):
        return None
    times = [_hour(text) for text in hourly["time"]]
    means = {
        field: _mean(times, hourly.get(field), start, end, field)
        for field in HOURLY_FIELDS
    }
    result = ActivityWeather(
        temperature_c=means["temperature_2m"],
        apparent_temperature_c=means["apparent_temperature"],
        relative_humidity_pct=means["relative_humidity_2m"],
        wind_speed_mps=means["wind_speed_10m"],
        precipitation_mm=means[_PRECIPITATION],
    )
    return result if result.has_value else None


def heat_note(apparent_temperature_c: float | None) -> str | None:
    """The Coach's heat note from an apparent temperature of 25 C on, else None."""
    if apparent_temperature_c is None or apparent_temperature_c < HEAT_APPARENT_C:
        return None
    value = f"{apparent_temperature_c:.1f}".replace(".", ",")
    return (
        f"Hitze: gefühlte Temperatur {value} °C (ab {HEAT_APPARENT_C:.0f} °C). "
        "Puls, Entkopplung und Tempo nicht als Fitnessänderung lesen."
    )
