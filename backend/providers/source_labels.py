"""Exact legacy source labels for canonical observations, one table for all views.

The PWA compares source labels as exact strings, and the legacy readers emit
German and English variants of the provider names. This module records, for each
legacy view, the label string that the view shows. Later units read canonical
observations through these functions and keep every label byte-for-byte.

``provider_label`` is the coarse label a view shows for a provider.
``observation_source_label`` refines it where a legacy view split one provider
into several labels: Garmin performance notes by kind, sport and section.

An unknown combination falls back to ``provider_label``. An observation without
a provider returns an empty string. Neither function raises for valid input.

Not mapped here, because no canonical observation carries the value or because
the value is not a provider label: "Manuell", "Aus Aktivitäten", the
Garmin activity-derived max-HR labels "Garmin Connect Radaktivitäten" and
"Garmin Connect Laufaktivitäten", "Garmin Connect Laufprognose", derived and estimated
labels (eFTP, planned-load estimates), and athlete-entered values. The pull
request description lists every mapped literal and every unmapped one.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.providers.garmin_health_mapping import GARMIN_LABEL
from backend.providers.wahoo_activity_mapping import WAHOO_LABEL

INTERVALS_LABEL: Final = "Intervals.icu"


class SourceView(StrEnum):
    """A legacy output that shows source labels, named by the reader that emits it."""

    CURRENT_METRIC = "current_metric"  # performance/current_metrics.py
    PERFORMANCE_NOTE = "performance_note"  # performance/garmin_metrics.py "note"
    BODY_HISTORY = "body_history"  # performance/body.py
    DAILY_HEALTH = "daily_health"  # performance/daily_health.py
    ACTIVITY_DETAIL = "activity_detail"  # performance/activity_read_service.py
    DUPLICATE = "duplicate"  # activities/duplicates.py
    SEASON_PREPARATION = "season_preparation"  # planning/season_preparation.py basis
    SEASON_PREPARATION_ACTIVITY = "season_preparation_activity"  # activity rows


# The providers whose recorded sessions the canonical analysis and charts read.
SESSION_SOURCES_LABEL: Final = f"{GARMIN_LABEL}, {WAHOO_LABEL}"

_GARMIN_DUPLICATE: Final = "Garmin"

_PROVIDER_LABELS: Final[Mapping[ProviderId, str]] = {
    ProviderId.INTERVALS: INTERVALS_LABEL,
    ProviderId.GARMIN: GARMIN_LABEL,
    ProviderId.WAHOO: WAHOO_LABEL,
}
# Only views whose coarse label differs from the provider's base label appear here.
_VIEW_LABELS: Final[Mapping[tuple[ProviderId, SourceView], str]] = {
    (ProviderId.GARMIN, SourceView.DUPLICATE): _GARMIN_DUPLICATE,
}


def provider_label(provider: ProviderId, view: SourceView) -> str:
    """Return the coarse label that ``view`` shows for ``provider``."""
    return _VIEW_LABELS.get((provider, view), _PROVIDER_LABELS[provider])


# Garmin notes that depend on the section that produced the value. The key's
# section is None for a record id that is not well formed, so it never matches.
_GARMIN_SECTION_NOTES: Final[Mapping[tuple[str | None, MetricKind], str]] = {
    ("heart_rate_zones", MetricKind.MAX_HR): "Garmin Connect Herzfrequenzzonen",
    ("max_metrics", MetricKind.VO2MAX): "Garmin Connect max metrics",
}
# Garmin notes that depend only on the kind and sport.
_GARMIN_KIND_NOTES: Final[Mapping[tuple[MetricKind, Sport | None], str]] = {
    (MetricKind.WEIGHT, None): "Garmin Connect Körpergewicht",
    (MetricKind.FTP, Sport.RIDE): "Garmin Connect FTP",
    (MetricKind.FTP, Sport.RUN): "Garmin Connect Lauf-Schwellenleistung",
    (MetricKind.THRESHOLD_PACE, Sport.RUN): "Garmin Connect Lauf-Schwellenpace",
    (MetricKind.THRESHOLD_HR, Sport.RUN): "Garmin Connect Lauf-Schwellenpuls",
    (MetricKind.THRESHOLD_HR, Sport.RIDE): "Garmin Connect Rad-Schwellenpuls",
}
# Garmin record ids are "<section>:<YYYY-MM-DD>", then optionally ":<index>" and
# ":<suffix>", as built by backend.providers.garmin_health_mapping._entry.
_GARMIN_RECORD_ID: Final = re.compile(r"([a-z_]+):\d{4}-\d{2}-\d{2}(?::|\Z)", re.ASCII)


def _garmin_section(record_id: str | None) -> str | None:
    """Return the section of a well-formed Garmin record id, else None."""
    if record_id is None:
        return None
    match = _GARMIN_RECORD_ID.match(record_id)
    return match.group(1) if match else None


def _garmin_fine(observation: Observation, view: SourceView) -> str | None:
    if view is not SourceView.PERFORMANCE_NOTE:
        return None
    kind = observation.kind
    section = _garmin_section(observation.provenance.source_record_id)
    section_note = _GARMIN_SECTION_NOTES.get((section, kind))
    if section_note is not None:
        return section_note
    return _GARMIN_KIND_NOTES.get((kind, observation.sport))


def observation_source_label(observation: Observation, view: SourceView) -> str:
    """Return the exact label that ``view`` shows for one canonical observation."""
    provider = observation.provenance.provider
    if provider is None:
        return ""
    # Only Garmin refines its label; Intervals.icu and Wahoo show the base label.
    fine = _garmin_fine(observation, view) if provider is ProviderId.GARMIN else None
    return provider_label(provider, view) if fine is None else fine
