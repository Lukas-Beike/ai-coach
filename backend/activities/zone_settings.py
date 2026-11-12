"""Zone limits and thresholds used to color plan steps and recordings.

Power and pace defaults follow Intervals.icu's standard zones, heart rate
Coggan's five zones. Canonical zone configurations replace them per metric: a
confirmed local configuration valid on the day wins, then the provider's (Garmin's
watch zones before Wahoo's). ``configured_threshold`` is the one place that decides
which stored configuration leads a threshold on a day (local first, then the dated
Garmin watch zone set for the lactate threshold heart rate); every consumer of a
dated threshold reads it, zones and the source-policy resolver alike. Absolute
bpm, watt or speed limits are used as they
are, whatever calculation basis the provider reports. A metric without any
configuration keeps the sport's canonical thresholds (``from_thresholds``) and
the default limits. ``power_source``, ``hr_source`` and ``pace_source`` name where
the limits come from.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Final

from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.records import Observation
from backend.canonical.vocabulary import (
    Environment,
    MetricKind,
    ProviderId,
    Sport,
    ZoneConfigurationMetric,
    ZonePercentBasis,
)

# Upper zone limits as percent of the threshold; everything above the last limit is
# the top zone. Power: Z1..Z6, above is Z7 (Intervals.icu). Heart rate: Coggan's five
# zones as percent of LTHR, Z1..Z4, above 105 % is Z5.
POWER_ZONE_LIMITS = (55, 75, 90, 105, 120, 150)
HR_ZONE_LIMITS = (68, 83, 94, 105)
PACE_ZONE_LIMITS = (77.5, 87.7, 94.3, 100, 103.4, 111.5)
# Heart-rate steps are usually written as percent of max HR; threshold HR is
# about 90 % of it.
LTHR_SHARE_OF_MAX_HR = 0.9
_MIN_ZONES = 3
_MAX_ZONES = 7
# A provider configuration valid only after a session day stands in for it when
# its first day is at most this many days later (``local_tss`` uses the same cap
# for thresholds).
ZONE_STAND_IN_MAX_DAYS: Final = 90
DEFAULT_ZONE_SOURCE: Final = "Standardzonen"
# The basis named in the source of absolute heart-rate limits converted without an LTHR.
HR_REFERENCE_BASIS: Final = "Bezug 90 % der Max-HF"
_PROVIDER_ZONE_SOURCES: Final = {
    ProviderId.GARMIN: "Garmin-Zonen",
    ProviderId.WAHOO: "Wahoo-Zonen",
    ProviderId.INTERVALS: "Intervals.icu-Zonen",
}
LOCAL_ZONE_SOURCE: Final = "lokale Zonen"


def zone_source_name(configuration: ZoneConfiguration | None) -> str:
    """The name of the source of a configuration's limits, for texts and reports."""
    if configuration is None:
        return DEFAULT_ZONE_SOURCE
    provider = configuration.provenance.provider
    return LOCAL_ZONE_SOURCE if provider is None else _PROVIDER_ZONE_SOURCES[provider]


def percent_zone(percent: float, limits: tuple[float, ...]) -> int:
    """Zone number for ``percent``; everything above the last limit is the top zone."""
    return next(
        (index for index, limit in enumerate(limits, 1) if percent <= limit),
        len(limits) + 1,
    )


@dataclass(frozen=True)
class ZoneSettings:
    """Thresholds and zone limits (percent of threshold) of one sport."""

    ftp: float | None = None
    lthr: float | None = None
    max_hr: float | None = None
    # Threshold running speed in m/s; pace limits are percent of it.
    threshold_pace: float | None = None
    # The bpm reference of absolute heart-rate limits when no LTHR is known: the
    # share of the max HR that ``hr_zone_of_max`` assumes for the LTHR.
    hr_reference_bpm: float | None = None
    power_limits: tuple[float, ...] = POWER_ZONE_LIMITS
    hr_limits: tuple[float, ...] = HR_ZONE_LIMITS
    pace_limits: tuple[float, ...] = PACE_ZONE_LIMITS
    # Where the limits come from: names for texts, not part of the zones' identity.
    power_source: str = field(default=DEFAULT_ZONE_SOURCE, compare=False)
    hr_source: str = field(default=DEFAULT_ZONE_SOURCE, compare=False)
    pace_source: str = field(default=DEFAULT_ZONE_SOURCE, compare=False)

    @classmethod
    def from_thresholds(
        cls, observations: Iterable[Observation], sport: Sport
    ) -> ZoneSettings:
        """Thresholds of ``sport`` from its canonical athlete settings, default limits.

        ``observations`` are the sport-scoped FTP, threshold pace, threshold and
        maximum heart rate winners; the first of each kind for ``sport`` is used.
        """
        values: dict[MetricKind, float] = {}
        for observation in observations:
            if observation.sport is sport:
                values.setdefault(observation.kind, float(observation.value.value))
        return cls(
            ftp=values.get(MetricKind.FTP),
            lthr=values.get(MetricKind.THRESHOLD_HR),
            max_hr=values.get(MetricKind.MAX_HR),
            threshold_pace=values.get(MetricKind.THRESHOLD_PACE),
        )

    @classmethod
    def from_configurations(
        cls,
        configurations: Iterable[ZoneConfiguration],
        sport: Sport,
        environment: Environment = Environment.UNKNOWN,
        day: date | None = None,
        *,
        fallback: ZoneSettings | None = None,
    ) -> ZoneSettings:
        """Zone settings of ``sport`` from the effective canonical configurations.

        Lists keep the open top entry, which the percent limits leave out, as the
        sport settings do. Each metric is decided on its own: one without an
        applicable configuration keeps the ``fallback`` value, or the default
        limits and no threshold when there is none. A local configuration's
        threshold wins; a provider configuration only fills a threshold the
        ``fallback`` (the source-policy winners) leaves empty, and gives its limits.
        """
        chosen = list(configurations)
        indoor = environment in {Environment.INDOOR, Environment.VIRTUAL}
        base = fallback or cls()
        power = effective_zone_configuration(
            chosen, ZoneConfigurationMetric.POWER, sport, indoor=indoor, day=day
        )
        heart_rate = effective_zone_configuration(
            chosen, ZoneConfigurationMetric.HEART_RATE, sport, indoor=indoor, day=day
        )
        pace = effective_zone_configuration(
            chosen, ZoneConfigurationMetric.PACE, sport, indoor=indoor, day=day
        )
        ftp = _threshold(power, base.ftp, MetricKind.FTP, day)
        lthr = _threshold(heart_rate, base.lthr, MetricKind.THRESHOLD_HR, day)
        max_hr = _threshold(heart_rate, base.max_hr, MetricKind.MAX_HR, day)
        threshold_pace = _threshold(
            pace, base.threshold_pace, MetricKind.THRESHOLD_PACE, day
        )
        hr_reference = _hr_reference(heart_rate, lthr, max_hr)
        # Limits are percent of the threshold the settings carry, so the zone of
        # a measured value is the one the provider reported in absolute terms.
        power_limits = _percent_limits(power, ftp)
        hr_limits = _percent_limits(heart_rate, lthr or hr_reference)
        pace_limits = _percent_limits(pace, threshold_pace)
        return cls(
            ftp=ftp,
            lthr=lthr,
            max_hr=max_hr,
            threshold_pace=threshold_pace,
            hr_reference_bpm=hr_reference if hr_limits else None,
            power_limits=power_limits or base.power_limits,
            hr_limits=hr_limits or base.hr_limits,
            pace_limits=pace_limits or base.pace_limits,
            power_source=zone_source_name(power) if power_limits else base.power_source,
            hr_source=_hr_source(heart_rate, hr_limits, hr_reference, base.hr_source),
            pace_source=zone_source_name(pace) if pace_limits else base.pace_source,
        )

    def power_zone(self, percent_of_ftp: float) -> int:
        return percent_zone(percent_of_ftp, self.power_limits)

    def pace_zone(self, percent_of_threshold: float) -> int:
        return percent_zone(percent_of_threshold, self.pace_limits)

    @property
    def hr_zone_reference(self) -> float | None:
        """The bpm the heart-rate limits are percent of: the LTHR, else the max-HR share."""
        return self.lthr or self.hr_reference_bpm

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
        if unit == "bpm" and (reference := self.hr_zone_reference):
            return self.hr_zone_of_lthr(value / reference * 100)
        return None


# The kinds whose threshold a Garmin configuration also leads: the watch's own
# lactate threshold HR (``lactateThresholdHeartRateUsed``) updates automatically.
_WATCH_FIRST_KINDS: Final = frozenset({MetricKind.THRESHOLD_HR})
_KIND_METRICS: Final = {
    MetricKind.FTP: ZoneConfigurationMetric.POWER,
    MetricKind.THRESHOLD_PACE: ZoneConfigurationMetric.PACE,
    MetricKind.THRESHOLD_HR: ZoneConfigurationMetric.HEART_RATE,
    MetricKind.MAX_HR: ZoneConfigurationMetric.HEART_RATE,
}


def _value(configuration: ZoneConfiguration, kind: MetricKind) -> float | None:
    return (
        configuration.maximum if kind is MetricKind.MAX_HR else configuration.threshold
    )


def _leading_value(
    configuration: ZoneConfiguration | None, kind: MetricKind, day: date | None
) -> float | None:
    """The value of a configuration that leads the source-policy values, else None.

    A confirmed local configuration leads every kind; a Garmin configuration
    leads the kinds in ``_WATCH_FIRST_KINDS`` only while it is valid on ``day``.
    A later stand-in (``_later_stand_in``) and other providers only fill a gap
    the source-policy values leave.
    """
    if configuration is None:
        return None
    provider = configuration.provenance.provider
    if provider is None or (
        provider is ProviderId.GARMIN
        and kind in _WATCH_FIRST_KINDS
        and _valid_on(configuration, day)
    ):
        return _value(configuration, kind) or None
    return None


def configured_threshold(
    configurations: Iterable[ZoneConfiguration],
    kind: MetricKind,
    sport: Sport,
    day: date | None,
    *,
    indoor: bool = False,
) -> tuple[float, ZoneConfiguration] | None:
    """The stored threshold that leads the source-policy values on ``day``, with its source.

    The precedence for a sport and kind on a day: (1) the locally confirmed zone
    configuration in effect, (2) the Garmin watch zone set in effect (lactate
    threshold heart rate only), then, outside this function, (3) the source-policy
    observations. Returns None when no stored configuration leads, so the caller
    falls through to (3). Zone settings, session load, current metrics, plan load,
    exports and the staleness hint all read the threshold through this function.
    """
    chosen = effective_zone_configuration(
        configurations, _KIND_METRICS[kind], sport, indoor=indoor, day=day
    )
    value = _leading_value(chosen, kind, day)
    return None if chosen is None or value is None else (float(value), chosen)


def _threshold(
    configuration: ZoneConfiguration | None,
    fallback: float | None,
    kind: MetricKind,
    day: date | None,
) -> float | None:
    """The leading configured value (``configured_threshold``), else the fallback.

    A configuration that does not lead only fills a gap the fallback (the
    source-policy winners) leaves. An Intervals.icu configuration gives its limits
    only, never a threshold.
    """
    lead = _leading_value(configuration, kind, day)
    if lead is not None:
        return lead
    if (
        configuration is None
        or configuration.provenance.provider is ProviderId.INTERVALS
    ):
        return fallback
    return fallback if fallback is not None else _value(configuration, kind)


def _hr_reference(
    configuration: ZoneConfiguration | None,
    lthr: float | None,
    max_hr: float | None,
) -> float | None:
    """The bpm reference of absolute heart-rate limits that have no LTHR to convert with.

    ``max_hr`` times ``LTHR_SHARE_OF_MAX_HR``, as for a percent-of-max target;
    None when the LTHR is known, the limits are percent of the threshold already
    or there is no max HR.
    """
    if (
        configuration is None
        or lthr
        or not max_hr
        or configuration.limits is None
        or (
            configuration.percent_limits is not None
            and configuration.percent_basis is ZonePercentBasis.THRESHOLD
        )
    ):
        return None
    return max_hr * LTHR_SHARE_OF_MAX_HR


def _hr_source(
    configuration: ZoneConfiguration | None,
    limits: tuple[float, ...] | None,
    reference: float | None,
    default: str,
) -> str:
    """The source name of the heart-rate limits, marking a max-HR reference basis."""
    if not limits:
        return default
    name = zone_source_name(configuration)
    return name if reference is None else f"{name} ({HR_REFERENCE_BASIS})"


def _valid_on(configuration: ZoneConfiguration, day: date | None) -> bool:
    if day is None:
        return True
    return (configuration.valid_from is None or configuration.valid_from <= day) and (
        configuration.valid_until is None or day <= configuration.valid_until
    )


# Threshold sources after the confirmed local values: Garmin is curated by the
# athlete, Wahoo follows, and output-only Intervals.icu ranks last.
_PROVIDER_ORDER: Final = (ProviderId.GARMIN, ProviderId.WAHOO, ProviderId.INTERVALS)


def _source_rank(configuration: ZoneConfiguration) -> int:
    """Confirmed local values first, then the provider order."""
    provider = configuration.provenance.provider
    if provider is None:
        return 0
    return 1 + _PROVIDER_ORDER.index(provider)


def effective_zone_configuration(
    configurations: Iterable[ZoneConfiguration],
    metric: ZoneConfigurationMetric,
    sport: Sport,
    *,
    indoor: bool = False,
    day: date | None = None,
) -> ZoneConfiguration | None:
    """The configuration of one metric that applies to ``sport`` on ``day``.

    Local configurations win over every provider. Within one source a
    configuration of the sport wins over Garmin's sport-free (default) set, an
    indoor configuration applies to indoor and virtual sessions, an
    environment-free one to every session, and the latest ``valid_from`` wins.
    A day before every provider configuration is stood in for by the earliest
    one that starts at most ``ZONE_STAND_IN_MAX_DAYS`` days later.
    """
    environments = (Environment.INDOOR, None) if indoor else (None,)
    matching = [
        configuration
        for configuration in configurations
        if configuration.metric is metric
        and configuration.environment in environments
        and (
            configuration.sport is sport
            or (
                configuration.sport is None
                and configuration.provenance.provider is ProviderId.GARMIN
            )
        )
    ]
    candidates = [item for item in matching if _valid_on(item, day)]
    if candidates:
        return min(
            candidates,
            key=lambda configuration: (
                _source_rank(configuration),
                configuration.sport is None,
                environments.index(configuration.environment),
                -(configuration.valid_from or date.min).toordinal(),
            ),
        )
    return _later_stand_in(matching, day) if day is not None else None


def zone_two_top(
    configuration: ZoneConfiguration, threshold_pace: float | None = None
) -> float | None:
    """The upper limit of zone 2: bpm, watts, or seconds per km for pace.

    Percent pace limits are percent of the threshold speed: the configuration's
    own threshold (m/s), else ``threshold_pace`` (s/km). None when it cannot be
    resolved.
    """
    percent = (configuration.percent_limits or ())[1:2]
    absolute = (configuration.limits or ())[1:2]
    if configuration.metric is ZoneConfigurationMetric.PACE:
        if absolute and absolute[0] > 0:
            return 1000 / absolute[0]
        if percent and percent[0] > 0 and configuration.threshold:
            return 1000 / (configuration.threshold * percent[0] / 100)
        if percent and percent[0] > 0 and threshold_pace:
            return threshold_pace * 100 / percent[0]
        return None
    if absolute:
        return absolute[0]
    basis = configuration.percent_basis
    if basis is ZonePercentBasis.RESERVE:
        maximum, resting = configuration.maximum, configuration.resting
        if not (percent and maximum and resting is not None):
            return None
        return resting + (maximum - resting) * percent[0] / 100
    base = (
        configuration.maximum
        if basis is ZonePercentBasis.MAXIMUM
        else configuration.threshold
    )
    return base * percent[0] / 100 if percent and base else None


def _later_stand_in(
    matching: list[ZoneConfiguration], day: date
) -> ZoneConfiguration | None:
    """The provider configuration starting within the cap after ``day``.

    The source order is the one of a valid day; within it the earliest start wins.
    """
    last = day + timedelta(days=ZONE_STAND_IN_MAX_DAYS)
    later = [
        item
        for item in matching
        if item.provenance.provider is not None
        and item.valid_from is not None
        and day < item.valid_from <= last
    ]
    return min(
        later,
        key=lambda item: (
            _source_rank(item),
            item.sport is None,
            item.environment is None,
            item.valid_from,
        ),
        default=None,
    )


def _percent_limits(
    configuration: ZoneConfiguration | None, reference: float | None = None
) -> tuple[float, ...] | None:
    """Upper limits as percent of the threshold, without the open top entry.

    Percent limits count only with the threshold as their basis. Absolute limits
    are converted with ``reference``, the threshold the settings carry (else the
    configuration's own), whatever calculation basis the provider reports.
    """
    if configuration is None:
        return None
    if (
        configuration.percent_limits is not None
        and configuration.percent_basis is ZonePercentBasis.THRESHOLD
    ):
        limits = configuration.percent_limits[:-1]
    elif configuration.limits is not None and (
        threshold := reference or configuration.threshold
    ):
        # Same operation order as the zone lookup, so a value on a limit stays on it.
        # Garmin's floors are whole bpm; a value rounds to the zone it displays.
        half = 0.5 if configuration.provenance.provider is ProviderId.GARMIN else 0.0
        limits = tuple(
            (limit + half) / threshold * 100 for limit in configuration.limits[:-1]
        )
    else:
        return None
    if len(limits) < _MIN_ZONES - 1:
        return None
    return limits
