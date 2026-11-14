"""How the Garmin collection payload is split between raw-layer rows and small state.

The payload is a mapping from section name to a record or a list of records, plus
a few scalar and bookkeeping keys. Every section below is stored one raw-layer row
per element (see ``section_items``); every other key is small state that stays in
one key/value entry. This module is pure and stdlib-only so the schema migration,
the writer and the readers share one definition.

A *merge* section accumulates: an element of a read window is added or replaced
and elements of earlier windows stay. A *replace* section holds the provider's
current answer: a non-empty read replaces the stored elements, so elements it no
longer returns are removed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

GARMIN_PROVIDER: Final = "garmin"
ACTIVITIES_SECTION: Final = "activities"
# The Garmin sections the health mapper reads or the readers assemble; each
# element of one is a ``health`` raw record.
HEALTH_RECORD_KIND: Final = "health"
ACTIVITY_RECORD_KIND: Final = "activity"

# Bounded read windows accumulate across syncs.
MERGE_SECTIONS: Final = (
    "sleep",
    "hrv",
    "body_battery",
    "activities",
    "daily_stats",
    "resting_hr",
    "training_status",
    "training_load_activities",
    "activity_ratings",
    "cycling_ftp_history",
    "activity_matches",
    # Each changed zone set is kept with its first-fetch day (``fetchedOn``), so
    # the zones valid on an earlier day keep applying to the sessions of that day.
    "heart_rate_zones",
)
# The provider's current answer replaces the stored one.
REPLACE_SECTIONS: Final = (
    "training_load_balance",
    "daily_training_status",
    "gear",
    "readiness",
    "race_predictions",
    "personal_records",
    "max_metrics",
    "cycling_ftp",
    "running_threshold",
    "weight",
    "weigh_ins",
    "weighIns",
    "endurance_score",
    "running_tolerance",
    "training_readiness_history",
    "weekly_training_status",
    "performance_history",
)
SECTIONS: Final = frozenset((*MERGE_SECTIONS, *REPLACE_SECTIONS))
# The athlete's ratings of single activities (summaryDTO), read per activity.
ACTIVITY_RATINGS_SECTION: Final = "activity_ratings"
# Per-activity rows merged into the activity rows before mapping, in merge
# order: a later section's value wins.
DEDICATED_ACTIVITY_SECTIONS: Final = (
    ACTIVITY_RATINGS_SECTION,
    "training_load_activities",
)


def dedicated_activity_rows(payload: object) -> list[object]:
    """The payload's per-activity rows of every dedicated section, in merge order."""
    if not isinstance(payload, Mapping):
        return []
    rows: list[object] = []
    for section in DEDICATED_ACTIVITY_SECTIONS:
        value = payload.get(section)
        if isinstance(value, list):
            rows.extend(value)
    return rows


# Sections that are not raw health records: activities have their own record kind.
ITEM_SECTIONS: Final = SECTIONS - {ACTIVITIES_SECTION}

# The key/value entry that holds everything outside the sections.
STATE_KEY: Final = "garmin_state"
# The retired single-blob entry. A migrated database keeps it unread for one release.
LEGACY_SNAPSHOT_KEY: Final = "garmin_snapshot"
RETIRED_SNAPSHOT_KEY: Final = "garmin_snapshot_legacy"


def is_merge_section(section: str) -> bool:
    return section in MERGE_SECTIONS
