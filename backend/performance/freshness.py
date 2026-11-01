"""Pure Garmin measurement-age and freshness projections, and the Garmin sync status.

``GarminSyncStatus`` is the only Garmin input of the performance projections that
is not canonical: per-section freshness and fetch times, the sync time, the read
windows and the fetch outcome of the provider charts. It never carries a measured
value; the values come from the canonical model (#1416).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Final

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.garmin_payload import SECTIONS

# The read windows of the stored sync state: the latest run's and the day's first.
_READ_WINDOW_KEYS: Final = ("read_window", "daily_read_window")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _stored_sections(state: Mapping[str, Any]) -> frozenset[str]:
    """The sections a payload-shaped mapping holds elements of."""
    return frozenset(
        str(key)
        for key, value in state.items()
        if key in SECTIONS and isinstance(value, (list, Mapping)) and value
    )


@dataclass(frozen=True, slots=True)
class GarminSyncStatus:
    """The stored Garmin sync status, never a measured value.

    ``source_freshness`` maps a section to its freshness, ``observed_at`` and
    ``fetched_at``; ``read_windows`` holds the latest and the day's first read
    window (``{"start", "end"}``) by name; ``chart_status`` maps a provider chart
    to its cached fetch outcome; ``stored_sections`` names the sections that
    hold stored elements, whatever the last run fetched.
    """

    synced_at: str | None = None
    start: str | None = None
    end: str | None = None
    source: str | None = None
    source_freshness: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    read_windows: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    pagination: Mapping[str, Any] = field(default_factory=dict)
    chart_status: Mapping[str, str] = field(default_factory=dict)
    stored_sections: frozenset[str] = frozenset()
    errors: tuple[Any, ...] = ()

    @classmethod
    def from_state(
        cls,
        state: Mapping[str, Any] | None,
        *,
        stored_sections: frozenset[str] | None = None,
    ) -> GarminSyncStatus:
        """Extract the sync status from the stored Garmin state or a fetched payload.

        Only status keys are read; measured values are ignored. ``stored_sections``
        names the sections with stored elements; without it they are the sections a
        payload-shaped ``state`` holds.
        """
        state = _mapping(state)
        provider_sync = _mapping(state.get("provider_sync"))
        pagination = _mapping(provider_sync.get("pagination"))
        charts = _mapping(state.get("provider_metrics"))
        errors = state.get("errors")
        return cls(
            synced_at=_text(state.get("synced_at")),
            start=_text(state.get("start")),
            end=_text(state.get("end")),
            source=_text(state.get("source")),
            source_freshness={
                str(key): dict(value)
                for key, value in _mapping(state.get("source_freshness")).items()
                if isinstance(value, Mapping)
            },
            read_windows={
                key: dict(window)
                for key in _READ_WINDOW_KEYS
                if isinstance(window := provider_sync.get(key), Mapping)
            },
            pagination=dict(pagination),
            chart_status={
                str(key): status
                for key, chart in charts.items()
                if isinstance(chart, Mapping)
                and isinstance(status := chart.get("status"), str)
            },
            stored_sections=(
                _stored_sections(state) if stored_sections is None else stored_sections
            ),
            errors=tuple(errors) if isinstance(errors, list) else (),
        )


NO_GARMIN_SYNC_STATUS: Final = GarminSyncStatus()


def measurement_age(observed_at: Any, current_date: date) -> dict[str, Any]:
    """Describe observation age independently of a successful provider read."""
    try:
        days = (
            current_date - date.fromisoformat(iso_date_prefix(str(observed_at)))
        ).days
    except TypeError, ValueError:
        return {"measurement_status": "unknown", "measurement_age_days": None}
    if days == 0:
        measurement_status = "today"
    elif days > 0:
        measurement_status = "earlier"
    else:
        measurement_status = "future"
    return {"measurement_status": measurement_status, "measurement_age_days": days}


def garmin_source_freshness(
    status: GarminSyncStatus, current_date: date
) -> dict[str, Any]:
    return {
        source: {**details, **measurement_age(details.get("observed_at"), current_date)}
        for source, details in status.source_freshness.items()
    }


def garmin_metric_freshness(
    status: GarminSyncStatus,
    source: str,
    value: dict[str, Any],
    current_date: date,
) -> dict[str, Any]:
    """Expose observation and retrieval dates without treating a retained value as a new reading."""
    freshness = status.source_freshness.get(source) or {}
    status_name = freshness.get("freshness", "unknown")
    observed_at = value.get("observed_at", freshness.get("observed_at"))
    result = {
        **value,
        "freshness": status_name,
        "fetched_at": freshness.get("fetched_at"),
        "observed_at": observed_at,
        **measurement_age(observed_at, current_date),
    }
    if result["measurement_status"] == "earlier":
        result["note"] = "; ".join(
            part
            for part in (
                str(result.get("note") or ""),
                f"Messung ist {result['measurement_age_days']} Tage alt; das Abrufdatum ist keine neue Messung.",
            )
            if part
        )
    if status_name in {"stale", "partial"} and value.get("value") is not None:
        label = (
            "Letzter guter Wert; Quelle nicht aktualisiert"
            if status_name == "stale"
            else "Quelle nur teilweise aktualisiert"
        )
        result["note"] = "; ".join(
            part for part in (str(result.get("note") or ""), label) if part
        )
    return result
