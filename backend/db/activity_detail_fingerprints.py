"""Summary fingerprints stored with canonical Intervals activity details."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from backend.canonical.vocabulary import ProviderId

_INTERVALS: Final = ProviderId.INTERVALS.value


def intervals_detail_fingerprints(
    db: Any, activity_ids: Sequence[str], *, batch_size: int
) -> dict[str, set[str]]:
    """Return per Intervals id the summary hashes its canonical rows were loaded for.

    The hashes come from the detail sets and from the analysis payload; ids
    without canonical details are absent. Ids are read ``batch_size`` at a time.
    """
    found: dict[str, set[str]] = {}
    for start in range(0, len(activity_ids), batch_size):
        batch = tuple(activity_ids[start : start + batch_size])
        marks = ",".join("?" * len(batch))
        rows = db.execute(
            "SELECT provider_activity_id AS id, summary_sha256 AS hash "
            f"FROM activity_detail_sets WHERE provider = ? AND provider_activity_id IN ({marks}) "
            "UNION ALL "
            "SELECT r.provider_activity_id, json_extract(a.payload, '$.summary_sha256') "
            "FROM activity_records r JOIN activity_detail_analysis a "
            "ON a.activity_id = r.activity_id "
            f"WHERE r.provider = ? AND r.provider_activity_id IN ({marks})",
            (_INTERVALS, *batch, _INTERVALS, *batch),
        ).fetchall()
        for row in rows:
            if row["hash"] is not None:
                found.setdefault(row["id"], set()).add(row["hash"])
    return found
