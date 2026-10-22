"""Intervals.icu summary scalars that ``ActivityRecord`` does not carry.

Pure mapping from the current Intervals.icu summary row to metric entries of the
``activity_detail.v1`` document. Entries keep the Intervals.icu source label and
name provider-neutral keys; no wire key leaves this module.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Final

from backend.canonical.vocabulary import ProviderId
from backend.providers.intervals_activity_keys import (
    CONFIGURED_FTP,
    INTENSITY,
    LACTATE_THRESHOLD_HR,
    ROLLING_FTP,
    RPE,
)
from backend.providers.source_labels import SourceView, provider_label

# (document key, summary key, unit, source kind)
_SUMMARY_METRICS: Final[tuple[tuple[str, str, str | None, str], ...]] = (
    ("avg_speed_mps", "average_speed", "m/s", "measured"),
    ("calories_kcal", "calories", "kcal", "measured"),
    ("avg_temp_c", "average_temp", "°C", "measured"),
    ("min_temp_c", "min_temp", "°C", "measured"),
    ("max_temp_c", "max_temp", "°C", "measured"),
    ("max_cadence", "max_cadence", "rpm", "measured"),
    ("elevation_loss_m", "total_elevation_loss", "m", "measured"),
    ("rpe", RPE, None, "measured"),
    ("feel", "feel", None, "measured"),
    ("intensity", INTENSITY, None, "derived"),
    ("ftp_w", CONFIGURED_FTP, "W", "derived"),
    ("rolling_ftp_w", ROLLING_FTP, "W", "derived"),
    ("lthr_bpm", LACTATE_THRESHOLD_HR, "bpm", "derived"),
    ("decoupling_pct", "decoupling", "%", "derived"),
)


def intervals_summary_metrics(summary: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the metric entries of the finite numeric scalars of one summary row."""
    label = provider_label(ProviderId.INTERVALS, SourceView.ACTIVITY_DETAIL)
    metrics: dict[str, dict[str, Any]] = {}
    for key, summary_key, unit, kind in _SUMMARY_METRICS:
        value = summary.get(summary_key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        if not math.isfinite(value):
            continue
        metrics[key] = {
            "value": value,
            "unit": unit,
            "source": {
                "provider": ProviderId.INTERVALS.value,
                "label": label,
                "kind": kind,
            },
            "alternatives": [],
        }
    return metrics
