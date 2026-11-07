"""Local TSS-scale session load and intensity factor (card M6, #1725).

``session_local_load`` computes one session's load from its canonical summary and
the thresholds in effect on its local day, with the first complete branch of:

* power (ride, run): ``IF = NP / FTP``, ``TSS = hours × IF² × 100``;
* pace (run without power): ``IF = v / v_threshold`` with the grade-adjusted
  speed, else the average speed, ``TSS = hours × IF² × 100``;
* heart rate (other sports too, walking included; not strength, yoga or
  alpine ski): Banister TRIMP of the average HR, normalised so 60 minutes at the
  threshold HR is 100, with the constants of the athlete's profile sex (male
  when not set, marked ``sex_assumed``; method v3, #1774);
* session RPE (strength only): the session-RPE load (card M1, elapsed minutes x
  RPE) times the athlete's own TSS per AU at a similar RPE (method v4, #1771):
  the median of ``TSS / (TSS duration minutes x RPE)`` over the rated ride and
  run sessions with a local load of the 365 days up to the session day, rated
  locally or on the Garmin device, whose RPE lies within 1 of the strength
  session's (else within 2), at least 20 of them.

Only the power branch gives an intensity factor (percent of FTP). A provider
load or intensity is never an input. ``DatedThresholds`` resolves the thresholds
of a session day under the source policy of the current thresholds; a key with
no value on the day takes the earliest later value, flagged ``after_session``.

This module is pure: no database, no provider and no ``server.py`` access.
"""

from __future__ import annotations

import bisect
import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final

from backend.activities.zone_settings import effective_zone_configuration
from backend.canonical.activity_summary import (
    stored_activity_key,
    summary_duration_s,
    summary_is_indoor,
    summary_local_date,
)
from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.rating_scales import GARMIN_RPE_SCALE, LOCAL_SESSION_RPE_SCALE
from backend.canonical.records import Observation, fingerprint_inputs
from backend.canonical.validation import MAX_ACTIVITY_LOAD
from backend.canonical.vocabulary import (
    Environment,
    MetricKind,
    ProviderId,
    Sport,
    ZoneConfigurationMetric,
)
from backend.performance.current_thresholds import (
    local_thresholds,
    resolve_current_thresholds,
)
from backend.performance.session_rpe_load import session_load
from backend.performance.source_policy import NO_PREFERENCES, SourcePreferences

METHOD_ID: Final = "local-tss-load"
METHOD_VERSION: Final = 4
CARD: Final = "M6"

POWER_BRANCH: Final = "power"
PACE_BRANCH: Final = "pace"
HEART_RATE_BRANCH: Final = "heart_rate"
SESSION_RPE_BRANCH: Final = "session_rpe"

# Banister TRIMP prefactor and coefficient by profile sex (card M6 v3); an
# unset sex takes the male constants and marks the value ``sex_assumed``.
MALE: Final = "male"
FEMALE: Final = "female"
TRIMP_CONSTANTS: Final = {MALE: (0.64, 1.92), FEMALE: (0.86, 1.67)}
MAX_INTENSITY_FACTOR: Final = 2.0
RESTING_HR_LOOKBACK_DAYS: Final = 7
# Yoga and alpine ski get no value; strength only the session-RPE branch and
# walking the heart-rate branch (athlete decisions 2026-11-06, method v2).
NO_TSS_SPORTS: Final = frozenset({Sport.YOGA, Sport.ALPINE_SKI})
SESSION_RPE_SPORTS: Final = frozenset({Sport.STRENGTH})
# The sessions that calibrate TSS per AU, their window and minimum pairs.
CALIBRATION_SPORTS: Final = frozenset({Sport.RIDE, Sport.RUN})
CALIBRATION_WINDOW_DAYS: Final = 365
CALIBRATION_MIN_PAIRS: Final = 20
# The RPE distances of the calibration bands, tried in order (card M6 v4).
CALIBRATION_RPE_BANDS: Final = (1, 2)
# The RPE values of the detail table (factor per RPE of its +-1 band).
CALIBRATION_TABLE_RPES: Final = tuple(range(1, 11))
_RATING_SOURCES: Final = {
    LOCAL_SESSION_RPE_SCALE.scale_id: "local",
    GARMIN_RPE_SCALE.scale_id: "garmin",
}
_POWER_SPORTS: Final = frozenset({Sport.RIDE, Sport.RUN})
_RESTING_HR_ORDER: Final = (ProviderId.GARMIN, ProviderId.WAHOO)
THRESHOLD_KINDS: Final = (
    MetricKind.FTP,
    MetricKind.THRESHOLD_PACE,
    MetricKind.THRESHOLD_HR,
    MetricKind.MAX_HR,
)
LOCAL_SOURCE: Final = "local"
LOCAL_INDOOR_SOURCE: Final = "local_indoor"


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


@dataclass(frozen=True, slots=True)
class CalibrationPair:
    """One rated ride or run: its day, RPE, ``TSS / AU`` and rating source.

    The AU uses the duration of the TSS, so both sides share one duration.
    """

    day: date
    rpe: float
    ratio: float
    source: str


@dataclass(frozen=True, slots=True)
class RpeCalibration:
    """The athlete's TSS per session-RPE AU at one RPE on one day.

    ``rpe_band`` is the RPE range of the pairs behind ``factor``;
    ``pairs_by_source`` splits them by rating source; ``by_rpe`` holds the
    factor (from enough pairs) and pair count of each RPE's +-1 band.
    """

    factor: float
    pairs: int
    window_start: date
    window_end: date
    rpe_band: tuple[float, float]
    pairs_by_source: Mapping[str, int]
    by_rpe: tuple[Mapping[str, Any], ...] = ()

    def fingerprint_part(self) -> dict[str, Any]:
        return {
            "tss_per_au": self.factor,
            "pairs": self.pairs,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "rpe_band": list(self.rpe_band),
            "pairs_by_source": dict(self.pairs_by_source),
            "by_rpe": [dict(item) for item in self.by_rpe],
        }


@dataclass(frozen=True, slots=True)
class SessionRating:
    """A strength session's session-RPE load (card M1) as the branch reads it."""

    au: float
    rpe: float
    rpe_scale: str | None


def _band(
    pairs: Sequence[CalibrationPair], rpe: float, distance: float
) -> list[CalibrationPair]:
    return [pair for pair in pairs if abs(pair.rpe - rpe) <= distance]


def _rpe_table(pairs: Sequence[CalibrationPair]) -> tuple[dict[str, Any], ...]:
    """Each table RPE's +-1 band: pair count and, from enough pairs, the factor."""
    table = []
    for rpe in CALIBRATION_TABLE_RPES:
        band = _band(pairs, rpe, CALIBRATION_RPE_BANDS[0])
        if not band:
            continue
        factor = (
            statistics.median(pair.ratio for pair in band)
            if len(band) >= CALIBRATION_MIN_PAIRS
            else None
        )
        table.append({"rpe": rpe, "tss_per_au": factor, "pairs": len(band)})
    return tuple(table)


def _calibration(
    band: Sequence[CalibrationPair],
    window: Sequence[CalibrationPair],
    rpe: float,
    distance: float,
    start: date,
    day: date,
) -> RpeCalibration:
    sources: dict[str, int] = {}
    for pair in band:
        sources[pair.source] = sources.get(pair.source, 0) + 1
    return RpeCalibration(
        factor=statistics.median(pair.ratio for pair in band),
        pairs=len(band),
        window_start=start,
        window_end=day,
        rpe_band=(max(rpe - distance, 0.0), min(rpe + distance, 10.0)),
        pairs_by_source=dict(sorted(sources.items())),
        by_rpe=_rpe_table(window),
    )


class RpeCalibrations:
    """TSS per AU by day and RPE from dated calibration pairs (see the module doc)."""

    def __init__(self, pairs: Iterable[CalibrationPair]) -> None:
        self._pairs = sorted(pairs, key=lambda pair: pair.day)
        self._days = [pair.day for pair in self._pairs]
        self._by_key: dict[tuple[date, float], RpeCalibration | None] = {}

    def on(self, day: date, rpe: float) -> RpeCalibration | None:
        key = (day, rpe)
        if key not in self._by_key:
            self._by_key[key] = self._calibrate(day, rpe)
        return self._by_key[key]

    def _calibrate(self, day: date, rpe: float) -> RpeCalibration | None:
        start = day - timedelta(days=CALIBRATION_WINDOW_DAYS - 1)
        low = bisect.bisect_left(self._days, start)
        high = bisect.bisect_right(self._days, day)
        window = self._pairs[low:high]
        for distance in CALIBRATION_RPE_BANDS:
            band = _band(window, rpe, distance)
            if len(band) >= CALIBRATION_MIN_PAIRS:
                return _calibration(band, window, rpe, distance, start, day)
        return None


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
    calibration: RpeCalibration | None = None,
) -> LocalLoad:
    used = {name: item.fingerprint_part() for name, item in thresholds.items()}
    details: dict[str, Any] = {
        "branch": branch,
        "card": CARD,
        "inputs": dict(inputs),
        "thresholds": used,
    }
    if calibration is not None:
        details["calibration"] = calibration.fingerprint_part()
    if any(item.after_session for item in thresholds.values()):
        details["threshold_after_session"] = True
    fingerprint = fingerprint_inputs(
        {
            "method": METHOD_ID,
            "method_version": METHOD_VERSION,
            "branch": branch,
            "inputs": dict(inputs),
            "thresholds": used,
            "calibration": details.get("calibration"),
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


def _trimp(minutes: float, reserve: float, sex: str) -> float:
    prefactor, coefficient = TRIMP_CONSTANTS[sex]
    return minutes * reserve * prefactor * math.exp(coefficient * reserve)


def trimp_sex(sex: str | None) -> tuple[str, bool]:
    """The sex whose TRIMP constants apply and whether it was assumed."""
    if sex in TRIMP_CONSTANTS:
        return str(sex), False
    return MALE, True


def _heart_rate(
    summary: Mapping[str, Any],
    sport: Sport,
    seconds: float,
    thresholds: SessionThresholds,
    sex: str | None,
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
    used_sex, assumed = trimp_sex(sex)
    load = (
        _trimp(seconds / 60, reserve, used_sex)
        / _trimp(60, threshold_reserve, used_sex)
        * 100
    )
    inputs: dict[str, Any] = {
        "sport": sport.value,
        "duration_s": seconds,
        "avg_hr": heart_rate,
        "sex": used_sex,
    }
    if assumed:
        inputs["sex_assumed"] = True
    return _result(
        HEART_RATE_BRANCH,
        load,
        None,
        inputs,
        {"resting_hr": rest, "threshold_hr": threshold, "max_hr": maximum},
    )


def _session_rpe(
    sport: Sport,
    rating: SessionRating | str | None,
    calibration: RpeCalibration | None,
) -> LocalLoad | str:
    if rating is None:
        return "no_rating"
    if isinstance(rating, str):
        return rating
    if calibration is None and rating.au > 0:
        return "not_calibrated"
    # An RPE of 0 gives 0 AU and so 0 TSS without a factor.
    return _result(
        SESSION_RPE_BRANCH,
        0.0 if calibration is None else rating.au * calibration.factor,
        None,
        {
            "sport": sport.value,
            "session_rpe_au": rating.au,
            "rpe": rating.rpe,
            "rpe_scale": rating.rpe_scale,
        },
        {},
        calibration,
    )


def session_local_load(
    summary: Mapping[str, Any],
    thresholds: SessionThresholds,
    *,
    rating: SessionRating | str | None = None,
    calibration: RpeCalibration | None = None,
    sex: str | None = None,
) -> LocalLoad | str:
    """Return the session's local load, or the reason it has none.

    The branches are tried in order; a branch without its session input is
    skipped, while a branch that has its input but no valid threshold falls
    through to the next one and its reason is kept if none succeeds. A strength
    session reads only the session-RPE branch with its ``rating`` and the
    ``calibration`` of its day. ``sex`` (profile value, None or empty when not
    set) chooses the heart-rate branch's TRIMP constants.
    """
    sport = _sport(summary)
    if sport is None or sport in NO_TSS_SPORTS:
        return "sport_without_load"
    if sport in SESSION_RPE_SPORTS:
        return _session_rpe(sport, rating, calibration)
    seconds = _positive(summary_duration_s(summary))
    if seconds is None:
        return "no_duration"
    reason = "no_inputs"
    for outcome in (
        _power(summary, sport, seconds, thresholds.ftp),
        _pace(summary, sport, seconds, thresholds.threshold_pace),
        _heart_rate(summary, sport, seconds, thresholds, sex),
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
                (
                    item
                    for item in observations
                    if item.kind in THRESHOLD_KINDS
                    # Stored Intervals.icu thresholds are never a source.
                    and item.provenance.provider is not ProviderId.INTERVALS
                ),
                key=lambda item: item.observed_on,
            )
        )
        # Each provider's series of one kind and sport, oldest first, so a day
        # finds its newest value by bisection instead of a scan.
        groups: dict[tuple[Any, ...], list[Observation]] = {}
        for item in self._observations:
            key = (item.provenance.provider, item.kind, item.sport)
            groups.setdefault(key, []).append(item)
        self._series = tuple(
            ([item.observed_on for item in series], series)
            for series in groups.values()
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
        provider = [
            series[index - 1]
            for days, series in self._series
            if (index := bisect.bisect_right(days, day))
        ]
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

    def indoor_ftp(self, day: date) -> Threshold | None:
        """The local indoor ride FTP in effect on ``day``, if one is configured.

        Only an athlete-confirmed configuration for the indoor environment
        counts (athlete decision 2026-11-06); a provider indoor FTP is not read.
        """
        local = [
            item for item in self._configurations if item.provenance.provider is None
        ]
        chosen = effective_zone_configuration(
            local, ZoneConfigurationMetric.POWER, Sport.RIDE, indoor=True, day=day
        )
        if (
            chosen is None
            or chosen.environment is not Environment.INDOOR
            or not chosen.threshold
        ):
            return None
        return Threshold(
            float(chosen.threshold), LOCAL_INDOOR_SOURCE, chosen.valid_from
        )

    def for_session(
        self, sport: Sport, day: date, *, indoor: bool = False
    ) -> SessionThresholds:
        """The thresholds a session of ``sport`` on ``day`` reads.

        An indoor or virtual ride uses the local indoor FTP of the day when one
        is configured.
        """
        heart = threshold_sport(sport)
        power_sport = sport if sport in _POWER_SPORTS else None
        indoor_ftp = (
            self.indoor_ftp(day) if indoor and power_sport is Sport.RIDE else None
        )
        return SessionThresholds(
            ftp=None
            if power_sport is None
            else indoor_ftp or self.threshold(MetricKind.FTP, power_sport, day),
            threshold_pace=self.threshold(MetricKind.THRESHOLD_PACE, Sport.RUN, day)
            if sport is Sport.RUN
            else None,
            threshold_hr=self.threshold(MetricKind.THRESHOLD_HR, heart, day),
            max_hr=self.threshold(MetricKind.MAX_HR, heart, day),
            resting_hr=self.resting_hr(day),
        )


def _rating(
    summary: Mapping[str, Any], feedback: Mapping[str, Any] | None
) -> SessionRating | str:
    """The session-RPE load (card M1), or its no-value reason (``no_rating`` etc.).

    RPE 0 is a valid rating and gives 0 AU.
    """
    entry, au = session_load(summary, feedback)
    if au is None or entry["rpe"] is None:
        reason = str(entry.get("reason") or "no_rating")
        return "no_rating" if reason == "no_rating" else reason
    return SessionRating(au=au, rpe=float(entry["rpe"]), rpe_scale=entry["rpe_scale"])


def _session_day(summary: Mapping[str, Any]) -> date | None:
    try:
        return date.fromisoformat(summary_local_date(summary))
    except ValueError:
        return None


def rated_sessions(
    summaries: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """The sessions whose feedback the strength branch reads; none without strength."""
    if not any(_sport(summary) in SESSION_RPE_SPORTS for summary in summaries):
        return []
    sports = SESSION_RPE_SPORTS | CALIBRATION_SPORTS
    return [summary for summary in summaries if _sport(summary) in sports]


def _calibration_pair(
    summary: Mapping[str, Any],
    load: LocalLoad,
    day: date,
    feedback: Mapping[str, Any] | None,
) -> CalibrationPair | None:
    rating = _rating(summary, feedback)
    if isinstance(rating, str) or rating.rpe <= 0:
        return None
    source = _RATING_SOURCES.get(rating.rpe_scale or "")
    seconds = _positive(summary_duration_s(summary))
    if source is None or seconds is None:
        return None
    au = seconds / 60 * rating.rpe
    return CalibrationPair(day, rating.rpe, load.load / au, source)


def calibration_pairs(
    summaries: Sequence[Mapping[str, Any]],
    loads: Mapping[str, LocalLoad | str],
    feedback: Mapping[str, Mapping[str, Any]],
) -> list[CalibrationPair]:
    """The calibration pairs of rated ride and run sessions with a local load.

    Only a local or Garmin rating counts; a rating relayed by Intervals.icu does
    not (athlete decision 2026-11-06). The AU uses the TSS duration (moving,
    else elapsed; card M6 v4).
    """
    pairs = []
    for summary in summaries:
        load = loads.get(str(summary.get("id")))
        day = _session_day(summary)
        if not isinstance(load, LocalLoad) or day is None:
            continue
        # A load the store rejects as outside the canonical bounds never
        # calibrates (``invalid_value`` in the stage).
        if _sport(summary) not in CALIBRATION_SPORTS or load.load > MAX_ACTIVITY_LOAD:
            continue
        pair = _calibration_pair(
            summary, load, day, feedback.get(stored_activity_key(summary))
        )
        if pair is not None:
            pairs.append(pair)
    return pairs


def session_loads(
    summaries: Sequence[Mapping[str, Any]],
    thresholds: DatedThresholds,
    feedback: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    sex: str | None = None,
) -> dict[str, LocalLoad | str]:
    """Each summary's local load or no-load reason, by session id.

    ``feedback`` maps a summary's stored key to its session's effective local
    feedback (``feedback_by_session``). Strength sessions come last, with the
    calibration from the other sessions' loads. ``sex`` is the profile sex the
    heart-rate branch reads.
    """
    ratings = feedback or {}
    result: dict[str, LocalLoad | str] = {}
    strength: list[tuple[str, Mapping[str, Any], date]] = []
    for summary in summaries:
        session_id = summary.get("id")
        sport = _sport(summary)
        day = _session_day(summary)
        if not isinstance(session_id, str):
            continue
        if day is None:
            result[session_id] = "no_date"
            continue
        if sport is None:
            result[session_id] = "sport_without_load"
            continue
        if sport in SESSION_RPE_SPORTS:
            strength.append((session_id, summary, day))
            continue
        result[session_id] = session_local_load(
            summary,
            thresholds.for_session(sport, day, indoor=summary_is_indoor(summary)),
            sex=sex,
        )
    calibrations = RpeCalibrations(calibration_pairs(summaries, result, ratings))
    for session_id, summary, day in strength:
        rating = _rating(summary, ratings.get(stored_activity_key(summary)))
        result[session_id] = session_local_load(
            summary,
            SessionThresholds(),
            rating=rating,
            calibration=None
            if isinstance(rating, str)
            else calibrations.on(day, rating.rpe),
        )
    return result
