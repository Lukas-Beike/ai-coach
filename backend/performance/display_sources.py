"""Provider the PWA prefers when several sources show the same metric.

A display key that names a metric kind takes the first provider of that kind's
``source_policy`` rule, so charts prefer the provider the selection prefers;
``_DISPLAY_ONLY`` lists the keys whose charts follow another rule. The table
says which provider's series a chart keeps, and which provider wins a tie
between equal dates. For ``cycling_w_per_kg`` the current value takes the preferred provider's
newest point across dates, like the current FTP. It changes no value.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance.source_policy import preferred_provider

_DISPLAY_KINDS: Final[Mapping[str, MetricKind]] = {
    "cycling_eftp_watts": MetricKind.EFTP,
    "run_threshold_pace_seconds_per_km": MetricKind.THRESHOLD_PACE,
    "cycling_vo2max_ml_kg_min": MetricKind.VO2MAX,
    "running_vo2max_ml_kg_min": MetricKind.VO2MAX,
}
# Display keys that are not the selection order. The FTP history and the FTP-based
# W/kg series exist only for Garmin (Intervals' W/kg series divides eFTP), so the
# charts keep Garmin. Body and recovery keep their display rules until their
# selection moves to the policy (later #1668 slices).
_DISPLAY_ONLY: Final[Mapping[str, ProviderId]] = {
    "cycling_ftp_watts": ProviderId.GARMIN,
    "cycling_w_per_kg": ProviderId.GARMIN,
    "weight_kg": ProviderId.GARMIN,
    "body_fat_pct": ProviderId.GARMIN,
    "sleep": ProviderId.INTERVALS,
    "hrv": ProviderId.INTERVALS,
    "resting_hr": ProviderId.INTERVALS,
}


def _derived() -> Mapping[str, ProviderId]:
    table: dict[str, ProviderId] = dict(_DISPLAY_ONLY)
    for key, kind in _DISPLAY_KINDS.items():
        provider = preferred_provider(kind)
        if provider is None:
            raise ValueError(f"{kind.value} has no source rule")
        table[key] = provider
    return MappingProxyType(table)


PREFERRED_PROVIDER: Final[Mapping[str, ProviderId]] = _derived()


def preferred_providers() -> dict[str, str]:
    """Return the preference table as payload values: metric key to provider id."""
    return {key: provider.value for key, provider in PREFERRED_PROVIDER.items()}
