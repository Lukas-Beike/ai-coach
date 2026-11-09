"""Flag synced run units whose exported heart-rate range moved only with the LTHR.

Garmin gets the cap as a bpm range resolved at export time (a Garmin workout step
cannot hold a percent of the lactate threshold HR). The bpm range sent last is
remembered per unit; when the athlete's threshold HR later moves, the unit's
range differs from it and the unit counts as changed, so the calendar sync button
offers it again. Nothing is sent without that explicit sync. Only percentages are
stored on the unit; the remembered range is bookkeeping about what was sent.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, Final

from backend.activities.hr_cap import resolved_range, stored_cap

SENT_PREFIX: Final = "hr_cap_sent:"
# Resolves the run threshold HR in effect on a unit's date, or None.
type LthrFor = Callable[[Mapping[str, Any]], float | None]


def sent_key(local_id: str) -> str:
    return f"{SENT_PREFIX}{local_id}"


def range_text(resolved: tuple[int, int] | None) -> str:
    return "" if resolved is None else f"{resolved[0]}-{resolved[1]}"


def record_sent(
    key_values: Any, db: Any, local_id: str, resolved: tuple[int, int] | None
) -> None:
    """Remember the bpm range sent for a unit; forget it when none was sent."""
    if resolved is None:
        key_values.delete(db, sent_key(local_id))
    else:
        key_values.set(db, sent_key(local_id), range_text(resolved))


def resync_ids(
    key_values: Any,
    db: Any,
    payloads: Iterable[Mapping[str, Any]],
    lthr_for: LthrFor,
) -> set[str]:
    """Local ids of synced capped units whose resolved range differs from the one sent."""
    changed: set[str] = set()
    for payload in payloads:
        cap = stored_cap(payload)
        local_id = str(payload.get("local_id") or "")
        if cap is None or not local_id or payload.get("sync_status") != "synced":
            continue
        sent = key_values.get(db, sent_key(local_id))
        if not sent:
            continue
        current = range_text(resolved_range(cap, lthr_for(payload)))
        if current and current != sent:
            changed.add(local_id)
    return changed
