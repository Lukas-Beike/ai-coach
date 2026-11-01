"""Pure Garmin sleep-freshness helpers.

The Garmin snapshot synchronizer owns persistence and freshness state.  This
module only reads the supplied sync state and never reaches into that state.
The ingest-time observation-date parser lives in
``backend.sync.garmin_payload_metrics``.
"""

from datetime import date, datetime
from typing import Any

from backend.athlete.local_date import iso_date_prefix


def garmin_sleep_observation_date(
    snapshot: dict[str, Any], observed_day: str | None
) -> str | None:
    """Return the authoritative sleep observation date.

    Stored freshness stays authoritative. Without it the date is ``observed_day``,
    the latest canonical Garmin sleep observation day (an ISO date string or None);
    the snapshot's raw sleep records are not read.
    """
    if not isinstance(snapshot, dict):
        return None
    freshness = snapshot.get("source_freshness")
    if isinstance(freshness, dict):
        sleep_freshness = freshness.get("sleep")
        if isinstance(sleep_freshness, dict):
            observed_at = sleep_freshness.get("observed_at")
            if observed_at not in (None, ""):
                # Preserve the source-owned value exactly; malformed values
                # must remain authoritative and must not fall back to raw data.
                return iso_date_prefix(str(observed_at))
    return observed_day


def garmin_sleep_ready_for_checkin(
    checkin_date: date, snapshot: dict[str, Any], observed_day: str | None
) -> bool:
    """Allow a check-in only for current-day sleep with usable freshness."""
    if not isinstance(checkin_date, date) or isinstance(checkin_date, datetime):
        return False
    if not isinstance(snapshot, dict):
        return False
    if (
        garmin_sleep_observation_date(snapshot, observed_day)
        != checkin_date.isoformat()
    ):
        return False
    freshness = snapshot.get("source_freshness")
    if not isinstance(freshness, dict) or not isinstance(freshness.get("sleep"), dict):
        return True
    return freshness["sleep"].get("freshness") in {"current", "partial"}
