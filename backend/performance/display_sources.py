"""Provider the PWA prefers when several sources show the same metric.

Each display key names the metric kind whose ``source_policy`` rule decides it,
so charts and tiles prefer the provider the current selection prefers: which
provider's series a chart keeps, and which provider wins a tie between equal
dates. For ``cycling_w_per_kg`` the current value takes the preferred provider's
newest point across dates, like the current FTP. It changes no value.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance.source_policy import preferred_provider

_DISPLAY_KINDS: Final[Mapping[str, MetricKind]] = {
    "cycling_ftp_watts": MetricKind.FTP,
    "cycling_eftp_watts": MetricKind.EFTP,
    "run_threshold_pace_seconds_per_km": MetricKind.THRESHOLD_PACE,
    "cycling_vo2max_ml_kg_min": MetricKind.VO2MAX,
    "running_vo2max_ml_kg_min": MetricKind.VO2MAX,
    "weight_kg": MetricKind.WEIGHT,
    "body_fat_pct": MetricKind.BODY_FAT,
    # W/kg divides the current FTP, so it follows the FTP source.
    "cycling_w_per_kg": MetricKind.FTP,
    "sleep": MetricKind.SLEEP_DURATION,
    "hrv": MetricKind.HRV_RMSSD,
    "resting_hr": MetricKind.RESTING_HR,
}


def _derived() -> Mapping[str, ProviderId]:
    table: dict[str, ProviderId] = {}
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
