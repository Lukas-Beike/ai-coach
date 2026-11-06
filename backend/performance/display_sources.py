"""Provider the PWA prefers when several sources show the same metric.

A display key that names a metric kind takes the first provider of that kind's
``source_policy`` rule, so charts prefer the provider the selection prefers
(Garmin's night values for sleep, HRV and resting HR, Garmin's measurements for
weight and body fat); ``_DISPLAY_ONLY`` lists the keys whose charts follow
another rule. The table
says which provider's series a chart keeps, and which provider wins a tie
between equal dates. For ``cycling_w_per_kg`` the current value takes the preferred provider's
newest point across dates, like the current FTP. It changes no value.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance.source_policy import (
    NO_PREFERENCES,
    SourcePreferences,
    preferred_provider,
)

_DISPLAY_KINDS: Final[Mapping[str, MetricKind]] = {
    "weight_kg": MetricKind.WEIGHT,
    "body_fat_pct": MetricKind.BODY_FAT,
    "sleep": MetricKind.SLEEP_DURATION,
    "hrv": MetricKind.HRV_RMSSD,
    "resting_hr": MetricKind.RESTING_HR,
    "run_threshold_pace_seconds_per_km": MetricKind.THRESHOLD_PACE,
    "cycling_vo2max_ml_kg_min": MetricKind.VO2MAX,
    "running_vo2max_ml_kg_min": MetricKind.VO2MAX,
}
# Display keys that are not the selection order. The FTP history and the FTP-based
# W/kg series exist only for Garmin, so the charts keep Garmin.
_DISPLAY_ONLY: Final[Mapping[str, ProviderId]] = {
    "cycling_ftp_watts": ProviderId.GARMIN,
    "cycling_w_per_kg": ProviderId.GARMIN,
}


def _derived(
    preferences: SourcePreferences = NO_PREFERENCES,
) -> Mapping[str, ProviderId]:
    table: dict[str, ProviderId] = dict(_DISPLAY_ONLY)
    for key, kind in _DISPLAY_KINDS.items():
        provider = preferred_provider(kind, preferences)
        if provider is None:
            raise ValueError(f"{kind.value} has no source rule")
        table[key] = provider
    return MappingProxyType(table)


PREFERRED_PROVIDER: Final[Mapping[str, ProviderId]] = _derived()


def preferred_providers(
    preferences: SourcePreferences = NO_PREFERENCES,
) -> dict[str, str]:
    """Return the preference table as payload values: metric key to provider id.

    The athlete's preferred source of a metric group replaces the rule's first
    provider for that group's display keys.
    """
    return {key: provider.value for key, provider in _derived(preferences).items()}
