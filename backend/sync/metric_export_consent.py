"""Per-field consent for the automatic Garmin to Intervals.icu metric export.

The athlete consents per exported field. Consent is stored as a JSON list of field
keys under ``FIELDS_KEY``. The earlier single flag ``LEGACY_FLAG_KEY`` means "all
fields, as before" until the athlete saves per-field consent; it is kept in step
(true while any field is enabled) so an older build still honours a revocation.
A new consent starts with ``DEFAULT_FIELDS``: every field except cycling FTP,
which the athlete maintains at Intervals.icu (#1668).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any, Final

from backend.canonical.vocabulary import MetricKind

FIELDS_KEY: Final = "garmin_metric_export_fields"
LEGACY_FLAG_KEY: Final = "garmin_metric_export_enabled"

# Field key (the metric kind) -> label, in display order.
EXPORT_FIELDS: Final[dict[str, str]] = {
    MetricKind.WEIGHT.value: "Gewicht",
    MetricKind.BODY_FAT.value: "Körperfett",
    MetricKind.RESTING_HR.value: "Ruhepuls",
    MetricKind.THRESHOLD_PACE.value: "Lauf-Schwellenpace",
    MetricKind.THRESHOLD_HR.value: "Schwellen-Herzfrequenz",
    MetricKind.MAX_HR.value: "Maximale Herzfrequenz",
    MetricKind.FTP.value: "Rad-FTP",
}
DEFAULT_FIELDS: Final = frozenset(EXPORT_FIELDS) - {MetricKind.FTP.value}


def enabled_fields(get: Callable[[str], str | None]) -> frozenset[str]:
    """Return the consented field keys; the legacy flag alone means all fields.

    A legacy flag other than "true" is no consent even with a stored field list,
    so a revocation by an older build holds after an upgrade. An unreadable list
    is no consent.
    """
    if get(LEGACY_FLAG_KEY) != "true":
        return frozenset()
    raw = get(FIELDS_KEY)
    if raw is None:
        return frozenset(EXPORT_FIELDS)
    try:
        stored = json.loads(raw)
    except ValueError:
        return frozenset()
    if not isinstance(stored, list):
        return frozenset()
    return frozenset(
        item for item in stored if isinstance(item, str) and item in EXPORT_FIELDS
    )


def store_fields(set_value: Callable[[str, str], Any], fields: Iterable[str]) -> None:
    """Persist the consented fields and keep the legacy flag in step."""
    ordered = [key for key in EXPORT_FIELDS if key in set(fields)]
    set_value(FIELDS_KEY, json.dumps(ordered))
    set_value(LEGACY_FLAG_KEY, "true" if ordered else "false")


def fields_view(fields: Iterable[str]) -> list[dict[str, Any]]:
    """Return every exportable field with its label and consent, in order."""
    chosen = set(fields)
    return [
        {"key": key, "label": label, "enabled": key in chosen}
        for key, label in EXPORT_FIELDS.items()
    ]
