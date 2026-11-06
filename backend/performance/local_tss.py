"""Local TSS-scale session load and intensity factor (card M6, #1725).

``session_local_load`` computes one session's load from its canonical summary and
the thresholds in effect on its local day, with the first complete branch of:

* power (ride, run): ``IF = NP / FTP``, ``TSS = hours × IF² × 100``;
* pace (run without power): ``IF = v / v_threshold`` with the grade-adjusted
  speed, else the average speed, ``TSS = hours × IF² × 100``;
* heart rate (other sports too, except strength, yoga, alpine ski and walking): Banister
  TRIMP of the average HR, normalised so 60 minutes at the threshold HR is 100.

Only the power branch gives an intensity factor (percent of FTP). A provider
load or intensity is never an input. ``DatedThresholds`` resolves the thresholds
of a session day under the source policy of the current thresholds; a key with
no value on the day takes the earliest later value, flagged ``after_session``.

This module is pure: no database, no provider and no ``server.py`` access.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final

from backend.canonical.activity_summary import summary_duration_s, summary_local_date
from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.records import Observation, fingerprint_inputs
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.performance.current_thresholds import (
    local_thresholds,
    resolve_current_thresholds,
)
from backend.performance.source_policy import NO_PREFERENCES, SourcePreferences

METHOD_ID: Final = "local-tss-load"
METHOD_VERSION: Final = 1
CARD: Final = "M6"

POWER_BRANCH: Final = "power"
PACE_BRANCH: Final = "pace"
HEART_RATE_BRANCH: Final = "heart_rate"

TRIMP_PREFACTOR: Final = 0.64
TRIMP_COEFFICIENT: Final = 1.92
MAX_INTENSITY_FACTOR: Final = 2.0
RESTING_HR_LOOKBACK_DAYS: Final = 7
# Walking is everyday activity, not training load (athlete decision 2026-11-06).
NO_TSS_SPORTS: Final = frozenset(
    {Sport.STRENGTH, Sport.YOGA, Sport.ALPINE_SKI, Sport.WALK}
)
_POWER_SPORTS: Final = frozenset({Sport.RIDE, Sport.RUN})
_RESTING_HR_ORDER: Final = (ProviderId.GARMIN, ProviderId.INTERVALS, ProviderId.WAHOO)
THRESHOLD_KINDS: Final = (
    MetricKind.FTP,
    MetricKind.THRESHOLD_PACE,
    MetricKind.THRESHOLD_HR,
    MetricKind.MAX_HR,
)
LOCAL_SOURCE: Final = "local"


@dataclass(frozen=True, slots=True)
class Threshold:
    """One threshold value, its source, the day it was observed and its timing.

    ``after_session`` is True when no value was in effect on the session day and
    the earliest later value stands in for it.
    """

    value: float
    source: str
    observed_on: date | None
    after_session: bool = False

    def fingerprint_part(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "source": self.source,
            "observed_on": None
            if self.observed_on is None
            else self.observed_on.isoformat(),
            "after_session": self.after_session,
        }


@dataclass(frozen=True, slots=True)
class SessionThresholds:
    """The thresholds a session's branches read; None where unknown."""

    ftp: Threshold | None = None
    threshold_pace: Threshold | None = None
    threshold_hr: Threshold | None = None
    max_hr: Threshold | None = None
    resting_hr: Threshold | None = None


@dataclass(frozen=True, slots=True)
class LocalLoad:
    """One session's local load, its intensity (power only) and provenance."""

    load: float
    intensity_pct: float | None
    branch: str
    details: Mapping[str, Any]
    fingerprint: str


def _positive(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _sport(summary: Mapping[str, Any]) -> Sport | None:
    try:
        return Sport(str(summary.get("sport")))
    except ValueError:
        return None


def threshold_sport(sport: Sport) -> Sport:
    """The sport whose heart-rate thresholds a session of ``sport`` reads."""
    return Sport.RIDE if sport is Sport.RIDE else Sport.RUN


def _result(
    branch: str,
    load: float,
    intensity_factor: float | None,
    inputs: Mapping[str, Any],
    thresholds: Mapping[str, Threshold],
) -> LocalLoad:
    used = {name: item.fingerprint_part() for name, item in thresholds.items()}
    details: dict[str, Any] = {
        "branch": branch,
        "card": CARD,
        "inputs": dict(inputs),
        "thresholds": used,
    }
    if any(item.after_session for item in thresholds.values()):
        details["threshold_after_session"] = True
    fingerprint = fingerprint_inputs(
        {
            "method": METHOD_ID,
            "method_version": METHOD_VERSION,
            "branch": branch,
            "inputs": dict(inputs),
            "thresholds": used,
        }
    )
    return LocalLoad(
        load=load,
        intensity_pct=None if intensity_factor is None else intensity_factor * 100,
        branch=branch,
        details=details,
        fingerprint=fingerprint,
    )


def _squared_load(hours: float, intensity_factor: float) -> float:
    return hours * intensity_factor * intensity_factor * 100


def _power(
    summary: Mapping[str, Any], sport: Sport, seconds: float, ftp: Threshold | None
) -> LocalLoad | str | None:
    power = _positive(summary.get("normalized_power"))
    if sport not in _POWER_SPORTS or power is None:
        return None
    if ftp is None or ftp.value <= 0:
        return "no_ftp"
    factor = power / ftp.value
    if factor > MAX_INTENSITY_FACTOR:
        return "implausible_intensity"
    return _result(
        POWER_BRANCH,
        _squared_load(seconds / 3600, factor),
        factor,
        {"sport": sport.value, "duration_s": seconds, "normalized_power": power},
        {"ftp": ftp},
    )


def _pace(
    summary: Mapping[str, Any],
    sport: Sport,
    seconds: float,
    threshold: Threshold | None,
) -> LocalLoad | str | None:
    if sport is not Sport.RUN:
        return None
    graded = _positive(summary.get("grade_adjusted_speed_mps"))
    speed = graded or _positive(summary.get("avg_speed_mps"))
    if speed is None:
        return None
    if threshold is None or threshold.value <= 0:
        return "no_threshold_pace"
    factor = speed / threshold.value
    if factor > MAX_INTENSITY_FACTOR:
        return "implausible_intensity"
    basis = "grade_adjusted_speed" if graded is not None else "average_speed"
    return _result(
        PACE_BRANCH,
        _squared_load(seconds / 3600, factor),
        None,
        {
            "sport": sport.value,
            "duration_s": seconds,
            "speed_mps": speed,
            "pace_basis": basis,
        },
        {"threshold_pace": threshold},
    )


def _trimp(minutes: float, reserve: float) -> float:
    return minutes * reserve * TRIMP_PREFACTOR * math.exp(TRIMP_COEFFICIENT * reserve)


def _heart_rate(
    summary: Mapping[str, Any],
    sport: Sport,
    seconds: float,
    thresholds: SessionThresholds,
) -> LocalLoad | str | None:
    heart_rate = _positive(summary.get("avg_hr"))
    if heart_rate is None:
        return None
    rest, threshold, maximum = (
        thresholds.resting_hr,
        thresholds.threshold_hr,
        thresholds.max_hr,
    )
    if rest is None:
        return "no_resting_hr"
    if threshold is None:
        return "no_threshold_hr"
    if maximum is None:
        return "no_max_hr"
    if not rest.value < threshold.value < maximum.value:
        return "inconsistent_heart_rate_thresholds"
    span = maximum.value - rest.value
    reserve = (heart_rate - rest.value) / span
    if not 0 < reserve <= 1:
        return "heart_rate_outside_reserve"
    threshold_reserve = (threshold.value - rest.value) / span
    load = _trimp(seconds / 60, reserve) / _trimp(60, threshold_reserve) * 100
    return _result(
        HEART_RATE_BRANCH,
        load,
        None,
        {"sport": sport.value, "duration_s": seconds, "avg_hr": heart_rate},
        {"resting_hr": rest, "threshold_hr": threshold, "max_hr": maximum},
    )


def session_local_load(
    summary: Mapping[str, Any], thresholds: SessionThresholds
) -> LocalLoad | str:
    """Return the session's local load, or the reason it has none.

    The branches are tried in order; a branch without its session input is
    skipped, while a branch that has its input but no valid threshold falls
    through to the next one and its reason is kept if none succeeds.
    """
    sport = _sport(summary)
    if sport is None or sport in NO_TSS_SPORTS:
        return "sport_without_load"
    seconds = _positive(summary_duration_s(summary))
    if seconds is None:
        return "no_duration"
    reason = "no_inputs"
    for outcome in (
        _power(summary, sport, seconds, thresholds.ftp),
        _pace(summary, sport, seconds, thresholds.threshold_pace),
        _heart_rate(summary, sport, seconds, thresholds),
    ):
        if isinstance(outcome, LocalLoad):
            return outcome
        if isinstance(outcome, str) and reason == "no_inputs":
            reason = outcome
    return reason


def _source(observation: Observation | None) -> str:
    provider = None if observation is None else observation.provenance.provider
    return LOCAL_SOURCE if provider is None else provider.value


def _first_by_provider(
    window: Sequence[Observation], *, latest: bool
) -> Threshold | None:
    """The window's value of the first provider in resting-HR order that has one."""
    for provider in _RESTING_HR_ORDER:
        matches = [item for item in window if item.provenance.provider is provider]
        if matches:
            item = matches[-1] if latest else matches[0]
            return Threshold(float(item.value.value), provider.value, item.observed_on)
    return None


class DatedThresholds:
    """Thresholds in effect on a given day under the current-threshold policy.

    ``observations`` are every stored provider threshold observation; on a day,
    each provider's newest value observed on or before it competes under the
    source policy, with age limits counted from that day. Local confirmed zone
    configurations in effect on the day win. A key without a value on the day
    takes the earliest later value, flagged ``after_session``.
    """

    def __init__(
        self,
        observations: Iterable[Observation],
        configurations: Iterable[ZoneConfiguration] = (),
        resting_hr: Iterable[Observation] = (),
        *,
        preferences: SourcePreferences = NO_PREFERENCES,
    ) -> None:
        self._observations = tuple(
            sorted(
                (item for item in observations if item.kind in THRESHOLD_KINDS),
                key=lambda item: item.observed_on,
                reverse=True,
            )
        )
        self._configurations = tuple(configurations)
        self._preferences = preferences
        self._days: dict[date, dict[tuple[MetricKind, Sport], Threshold]] = {}
        self._later_days = sorted(
            {item.observed_on for item in self._observations}
            | {
                item.valid_from
                for item in self._configurations
                if item.provenance.provider is None and item.valid_from is not None
            }
        )
        rest = sorted(
            (item for item in resting_hr if item.kind is MetricKind.RESTING_HR),
            key=lambda item: item.observed_on,
        )
        self._rest_days = [item.observed_on for item in rest]
        self._rest = rest

    def _resolve(self, day: date) -> dict[tuple[MetricKind, Sport], Threshold]:
        cached = self._days.get(day)
        if cached is not None:
            return cached
        provider = [item for item in self._observations if item.observed_on <= day]
        resolved = resolve_current_thresholds(
            provider,
            local_thresholds(self._configurations, day),
            as_of=day,
            preferences=self._preferences,
        )
        values = {
            key: Threshold(
                result.winner.value,
                _source(result.winner.observation),
                result.winner.observed_on,
            )
            for key, result in resolved.items()
        }
        self._days[day] = values
        return values

    def threshold(self, kind: MetricKind, sport: Sport, day: date) -> Threshold | None:
        """The value of ``kind`` for ``sport`` on ``day``, or the earliest later one."""
        found = self._resolve(day).get((kind, sport))
        if found is not None:
            return found
        start = bisect.bisect_right(self._later_days, day)
        for later in self._later_days[start:]:
            found = self._resolve(later).get((kind, sport))
            if found is not None:
                return Threshold(
                    found.value, found.source, found.observed_on, after_session=True
                )
        return None

    def resting_hr(self, day: date) -> Threshold | None:
        """The resting HR of ``day`` or of the nearest earlier day within the window.

        Garmin's value wins over another provider's value of the same window.
        Without one, the earliest later value stands in, flagged ``after_session``
        (athlete decision 2026-11-06), Garmin first on that day.
        """
        start = bisect.bisect_left(
            self._rest_days, day - timedelta(days=RESTING_HR_LOOKBACK_DAYS)
        )
        end = bisect.bisect_right(self._rest_days, day)
        found = _first_by_provider(self._rest[start:end], latest=True)
        if found is not None:
            return found
        later = self._rest[end:]
        if not later:
            return None
        first_day = later[0].observed_on
        stand_in = _first_by_provider(
            [item for item in later if item.observed_on == first_day], latest=False
        )
        if stand_in is None:
            return None
        return Threshold(
            stand_in.value, stand_in.source, stand_in.observed_on, after_session=True
        )

    def for_session(self, sport: Sport, day: date) -> SessionThresholds:
        """The thresholds a session of ``sport`` on ``day`` reads."""
        heart = threshold_sport(sport)
        power_sport = sport if sport in _POWER_SPORTS else None
        return SessionThresholds(
            ftp=None
            if power_sport is None
            else self.threshold(MetricKind.FTP, power_sport, day),
            threshold_pace=self.threshold(MetricKind.THRESHOLD_PACE, Sport.RUN, day)
            if sport is Sport.RUN
            else None,
            threshold_hr=self.threshold(MetricKind.THRESHOLD_HR, heart, day),
            max_hr=self.threshold(MetricKind.MAX_HR, heart, day),
            resting_hr=self.resting_hr(day),
        )


def session_loads(
    summaries: Sequence[Mapping[str, Any]],
    thresholds: DatedThresholds,
) -> dict[str, LocalLoad | str]:
    """Each summary's local load or no-load reason, by session id."""
    result: dict[str, LocalLoad | str] = {}
    for summary in summaries:
        session_id = summary.get("id")
        sport = _sport(summary)
        try:
            day = date.fromisoformat(summary_local_date(summary))
        except ValueError:
            day = None
        if not isinstance(session_id, str):
            continue
        if day is None:
            result[session_id] = "no_date"
            continue
        if sport is None:
            result[session_id] = "sport_without_load"
            continue
        result[session_id] = session_local_load(
            summary, thresholds.for_session(sport, day)
        )
    return result
