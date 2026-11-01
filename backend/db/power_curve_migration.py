"""Schema 16 -> 17 data step: the stored power curve becomes a raw-layer record.

Before schema 17 the Intervals.icu cycling power curve lived only in the stored
snapshot (``cycling_power_profile``). After the empty ``power_curve_points``
table is created, this step copies the curve of the newest stored snapshot into
one Intervals.icu ``power_curve`` raw record with ``mapped_version`` 0, so the
canonical backfill projects it with the current mapper. A snapshot without a
curve, or without any parseable fetch time, adds nothing, and a raw record that
already exists is kept. The snapshot itself stays unchanged.

The names are frozen with the release, so the step does not import the mapper.
"""

from __future__ import annotations

import json
from datetime import UTC
from typing import Any, Final

from backend.canonical.local_time import parse_provider_datetime
from backend.canonical.vocabulary import ProviderId
from backend.db import canonical_store
from backend.observability import sanitized_provider_payload

INTERVALS_PROVIDER: Final = ProviderId.INTERVALS.value
POWER_CURVE_RECORD_KIND: Final = "power_curve"
POWER_CURVE_RECORD_ID: Final = "power_curve"
SNAPSHOT_KEY: Final = "cycling_power_profile"
# Mapper version of a row no mapper has projected yet.
UNMAPPED_VERSION: Final = 0


def copy_power_curve_to_raw_record(db: Any) -> None:
    """Store the newest snapshot's power curve as a raw record; see the module docstring."""
    row = db.execute(
        "SELECT payload, created_at FROM snapshots ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return
    snapshot = _decode(row["payload"])
    curve = snapshot.get(SNAPSHOT_KEY)
    if not isinstance(curve, dict) or not curve:
        return
    # The backfill parses the fetch time to re-project the record, so the first
    # parseable candidate is kept; the zone does not change what parses.
    candidates = (snapshot.get("synced_at"), curve.get("synced_at"), row["created_at"])
    fetched_at = next(
        (
            value
            for value in candidates
            if isinstance(value, str) and parse_provider_datetime(value, UTC)
        ),
        None,
    )
    if fetched_at is None:
        return
    canonical_store.insert_provider_record_if_absent(
        db,
        provider=INTERVALS_PROVIDER,
        record_kind=POWER_CURVE_RECORD_KIND,
        source_record_id=POWER_CURVE_RECORD_ID,
        payload=sanitized_provider_payload(curve),
        mapper_version=UNMAPPED_VERSION,
        fetched_at=fetched_at,
        now=fetched_at,
    )


def _decode(text: Any) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except TypeError, ValueError, RecursionError:
        return {}
    return value if isinstance(value, dict) else {}
