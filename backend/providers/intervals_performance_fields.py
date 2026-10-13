"""Intervals.icu wire field names that performance code reads from payloads.

The performance package must not know Intervals.icu payload keys.  It imports
these names so wire-format knowledge stays inside the provider adapter.  The
``TRAINING_LOAD``, ``CONFIGURED_FTP`` and ``W_PRIME`` values are also keys of
the app's own performance JSON, which the PWA consumes, so they must not change.
"""

from typing import Final

TRAINING_LOAD: Final = "icu_training_load"
CONFIGURED_FTP: Final = "icu_ftp"
W_PRIME: Final = "icu_w_prime"
INTENSITY: Final = "icu_intensity"
WEIGHTED_AVG_WATTS: Final = "icu_weighted_avg_watts"
WEIGHTED_AVG_SPEED: Final = "icu_weighted_avg_speed"
PACE: Final = "icu_pace"
RPE: Final = "icu_rpe"
ZONE_TIMES: Final = "icu_zone_times"
HEART_RATE_ZONE_TIMES: Final = "icu_hr_zone_times"

# Activity field aliases; each tuple keeps the lookup order it replaces.
TRAINING_LOAD_ALIASES: Final = (TRAINING_LOAD,)
INTENSITY_ALIASES: Final = ("icu_intensity",)
RPE_ALIASES: Final = ("icu_rpe", "rpe")
PACE_ALIASES: Final = ("icu_pace", "average_pace", "pace")
SPEED_ALIASES: Final = ("average_speed", "icu_weighted_avg_speed")
WEIGHTED_POWER_ALIASES: Final = (
    "icu_weighted_avg_watts",
    "weighted_average_watts",
    "normalized_power",
)
VO2_MAX_ALIASES: Final = (
    "vo2max",
    "vo2_max",
    "vO2MaxValue",
    "vo2MaxValue",
    "icu_vo2max",
)
CONFIGURED_FTP_ALIASES: Final = (CONFIGURED_FTP,)
ESTIMATED_FTP_ALIASES: Final = ("icu_eftp", "eftp", "eFTP")
DIRECT_ESTIMATED_FTP_ALIASES: Final = ("eftp", "eFTP", "icu_eftp")
