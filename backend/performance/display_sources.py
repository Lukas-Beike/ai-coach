"""Provider the PWA prefers when several sources show the same metric.

The table records the display rules the PWA applied to source labels: which
provider's series a chart keeps, and which provider wins a tie between equal
dates. It is read-only policy in the payload and changes no value.
"""

from collections.abc import Mapping
from typing import Final

from backend.canonical.vocabulary import ProviderId

PREFERRED_PROVIDER: Final[Mapping[str, ProviderId]] = {
    "cycling_ftp_watts": ProviderId.GARMIN,
    "cycling_eftp_watts": ProviderId.INTERVALS,
    "run_threshold_pace_seconds_per_km": ProviderId.GARMIN,
    "cycling_vo2max_ml_kg_min": ProviderId.GARMIN,
    "running_vo2max_ml_kg_min": ProviderId.GARMIN,
    "weight_kg": ProviderId.GARMIN,
    "body_fat_pct": ProviderId.GARMIN,
    "cycling_w_per_kg": ProviderId.GARMIN,
    "sleep": ProviderId.INTERVALS,
    "hrv": ProviderId.INTERVALS,
    "resting_hr": ProviderId.INTERVALS,
}


def preferred_providers() -> dict[str, str]:
    """Return the preference table as payload values: metric key to provider id."""
    return {key: provider.value for key, provider in PREFERRED_PROVIDER.items()}
