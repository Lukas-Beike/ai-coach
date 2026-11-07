"""Read the stored local session metrics (card M8) for summaries and the detail view.

The values are derived observations owned by their canonical session, written by
``backend.sync.session_metrics``. Readers never compute them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

from backend.canonical.vocabulary import MetricKind
from backend.db import canonical_store
from backend.performance.session_metrics import METHOD_ID

DERIVED_LABEL: Final = "derived"
# Summary and detail-document key, metric kind and fixed unit (None: per value).
SUMMARY_KEYS: Final[tuple[tuple[str, MetricKind, str | None], ...]] = (
    ("efficiency_factor", MetricKind.EFFICIENCY_FACTOR, None),
    ("variability_index", MetricKind.VARIABILITY_INDEX, None),
    ("work_kj", MetricKind.MECHANICAL_WORK, "kJ"),
    ("decoupling_pct", MetricKind.AEROBIC_DECOUPLING, "%"),
)


def stored_session_metrics(
    db: Any, session_ids: Iterable[str] | None = None
) -> dict[str, dict[str, dict[str, Any]]]:
    """Map each session id to its stored metric rows by metric name.

    ``session_ids`` limits the read to those owners; None reads every row.
    """
    owners = None if session_ids is None else list(session_ids)
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for row in canonical_store.derived_observation_rows(db, METHOD_ID, owners=owners):
        owner = row.get("owner_record_id")
        if isinstance(owner, str):
            result.setdefault(owner, {})[row["metric"]] = row
    return result


def with_session_metrics(
    summaries: Iterable[Mapping[str, Any]],
    stored: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> tuple[dict[str, Any], ...]:
    """Return the summaries with the stored local metrics, labelled derived."""
    result = []
    for summary in summaries:
        item = dict(summary)
        rows = stored.get(str(item.get("id")), {})
        if rows:
            sources = dict(item.get("sources") or {})
            for key, kind, _unit in SUMMARY_KEYS:
                row = rows.get(kind.value)
                if row is None:
                    continue
                item[key] = row["value"]
                sources[key] = DERIVED_LABEL
                if kind is MetricKind.EFFICIENCY_FACTOR:
                    item["efficiency_factor_unit"] = row["derivation"].get("unit")
            item["sources"] = sources
        result.append(item)
    return tuple(result)


def detail_metric_entries(
    rows: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return ``activity_detail.v1`` metric entries of one session's stored rows."""
    entries: dict[str, dict[str, Any]] = {}
    for key, kind, unit in SUMMARY_KEYS:
        row = rows.get(kind.value)
        if row is None:
            continue
        derivation = row["derivation"]
        entry: dict[str, Any] = {
            "value": row["value"],
            "unit": unit if unit is not None else derivation.get("unit"),
            "source": {
                "provider": None,
                "label": DERIVED_LABEL,
                "kind": "derived",
                "method": METHOD_ID,
                "method_version": row.get("method_version"),
            },
            "alternatives": [],
        }
        if basis := derivation.get("basis"):
            entry["basis"] = basis
        entries[key] = entry
    return entries
