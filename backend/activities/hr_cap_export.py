"""A unit's heart-rate cap as the target of its steps, for the watch export.

The unit stores percentages of the lactate threshold HR only. Every step with a
heart-rate target (a zone, a percent or bpm), warm-up and cool-down included, is
sent as one wide custom range from the exported lower bound up to the cap, never
as a zone number or a narrow band, so the watch alerts only above the cap; steps
with a pace or power target keep theirs.

* Wahoo takes the range as percent of the threshold HR (``% LTHR``), so the head
  unit resolves it with the reference in the plan header.
* Garmin goes through the Intervals.icu calendar, and a Garmin workout step cannot
  hold a percent of the lactate threshold HR (its relative heart-rate targets are
  percent of maximum HR only; an absolute target is bpm). The range is therefore
  sent as bpm, resolved at export time from the threshold HR in effect on the
  unit's date. Without a known threshold HR the percent form is sent instead.

The stored unit text is never changed: this renders the text that is sent. Pure.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final

from backend.activities.hr_cap import (
    LOW_PERCENT_KEY,
    PERCENT_KEY,
    percent_text,
    resolved_range,
    stored_cap,
)
from backend.activities.workout_text import _target_match, _workout_quantity

_RAMP: Final = re.compile(r"ramp[ \t]+", re.IGNORECASE)
_HEART_RATE: Final = re.compile(r"HR|BPM", re.IGNORECASE)


def export_target(
    cap: Mapping[str, Any], lthr: float | None, *, percent_basis: bool
) -> str | None:
    """The step target of the exported range.

    Wahoo: percent of the threshold HR (the plan header carries the reference).
    Garmin through Intervals.icu: bpm resolved from ``lthr``; None without a known
    threshold HR, because a percent would be resolved with Intervals.icu's own,
    possibly stale, LTHR.
    """
    if percent_basis:
        low, high = cap[LOW_PERCENT_KEY], cap[PERCENT_KEY]
        return f"{percent_text(low)}-{percent_text(high)}% LTHR"
    resolved = resolved_range(cap, lthr)
    return None if resolved is None else f"{resolved[0]}-{resolved[1]}bpm"


def capped_description(
    description: str,
    unit: Mapping[str, Any],
    *,
    lthr: float | None = None,
    percent_basis: bool = False,
) -> str:
    """The description with the unit's cap as the heart-rate range; unchanged without a cap."""
    cap = stored_cap(unit)
    if cap is None:
        return description
    target = export_target(cap, lthr, percent_basis=percent_basis)
    if target is None:
        return description
    return "\n".join(_capped_line(line, target) for line in description.split("\n"))


def _capped_line(line: str, target: str) -> str:
    stripped = line.strip()
    if not stripped.startswith("-"):
        return line
    try:
        _, rest = _workout_quantity(stripped, 0)
    except ValueError:
        return line
    ramp = _RAMP.match(rest)
    body = rest[ramp.end() :] if ramp else rest
    found = _target_match(body)
    if found is None or not _HEART_RATE.search(found[0]) or "PACE" in found[0].upper():
        return line
    start = len(stripped) - len(body) + found.start()
    end = len(stripped) - len(body) + found.end()
    suffix = stripped[end:]
    # A trailing "HR" belongs to the replaced target.
    suffix = re.sub(r"^[ \t]+HR\b", "", suffix, flags=re.IGNORECASE)
    indent = line[: len(line) - len(line.lstrip())]
    return indent + stripped[:start] + target + suffix
