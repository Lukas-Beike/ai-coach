"""Seven-day mean of ln(RMSSD) against the athlete's earlier nights (M2, #1772).

Method ``rolling-lnrmssd-v1`` (card M2 version 4): the nightly RMSSD values of
the seven days ending with the latest night are log-transformed and averaged.
The comparison range is the mean ± 0.5 SD of ln(RMSSD) over the 42 days before
that seven-day window, so the current week never compares with itself. Within
one series only nights since the latest measurement change count. Values are
served back-transformed to ms; the range is a description of the athlete's own
history, not a readiness or health range.
"""

import math
from datetime import date, timedelta
from statistics import fmean, stdev
from typing import Any, Final

METHOD: Final = "rolling-lnrmssd-v1"
WINDOW_DAYS: Final = 7
BASELINE_DAYS: Final = 42
MIN_WINDOW_NIGHTS: Final = 3
OK_WINDOW_NIGHTS: Final = 5
MIN_BASELINE_NIGHTS: Final = 14
OK_BASELINE_NIGHTS: Final = 28
RANGE_SD: Final = 0.5


def _days(records: dict[str, float], first: date, last: date) -> list[float]:
    return [
        math.log(value)
        for day, value in records.items()
        if first.isoformat() <= day <= last.isoformat()
    ]


def _reason(*, window: int, changed: bool) -> str:
    if window < MIN_WINDOW_NIGHTS:
        return "Mindestens 3 Nächte in den letzten 7 Tagen erforderlich."
    if changed:
        return (
            "Messkontext geändert; mindestens 14 passende Nächte vor den "
            "letzten 7 Tagen seitdem erforderlich."
        )
    return "Mindestens 14 frühere passende Nächte vor den letzten 7 Tagen erforderlich."


def rolling_lnrmssd(
    records: dict[str, float],
    observed: str,
    *,
    current: bool,
    segment_start: str | None,
) -> dict[str, Any]:
    """Return the seven-day ln(RMSSD) comparison for one RMSSD series.

    ``records`` maps ISO days to positive RMSSD values in ms, ``observed`` is
    the latest day and ``segment_start`` the first day after the latest
    measurement change, or None without a change.
    """
    end = date.fromisoformat(observed)
    window_start = end - timedelta(days=WINDOW_DAYS - 1)
    baseline_start = window_start - timedelta(days=BASELINE_DAYS)
    # Only a change after the earliest baseline night limits this comparison.
    changed = segment_start is not None and segment_start > baseline_start.isoformat()
    if segment_start is not None and changed:
        start = date.fromisoformat(segment_start)
        window_start = max(window_start, start)
        baseline_start = max(baseline_start, start)
    window = _days(records, window_start, end)
    baseline = _days(records, baseline_start, end - timedelta(days=WINDOW_DAYS))
    result: dict[str, Any] = {
        "method": METHOD,
        "status": "insufficient_data",
        "window_days": WINDOW_DAYS,
        "window_nights": len(window),
        "baseline_days": BASELINE_DAYS,
        "baseline_nights": len(baseline),
    }
    if not current:
        result["reason"] = "Messung veraltet."
        return result
    if len(window) < MIN_WINDOW_NIGHTS or len(baseline) < MIN_BASELINE_NIGHTS:
        result["reason"] = _reason(
            window=len(window),
            changed=changed,
        )
        return result
    mean_ln = fmean(window)
    center, spread = fmean(baseline), stdev(baseline)
    lower_ln, upper_ln = center - RANGE_SD * spread, center + RANGE_SD * spread
    position = "within"
    if mean_ln < lower_ln:
        position = "below"
    elif mean_ln > upper_ln:
        position = "above"
    settled = len(window) >= OK_WINDOW_NIGHTS and len(baseline) >= OK_BASELINE_NIGHTS
    result.update(
        status="ok" if settled else "provisional",
        mean_ms=round(math.exp(mean_ln), 1),
        lower_ms=round(math.exp(lower_ln), 1),
        upper_ms=round(math.exp(upper_ln), 1),
        position=position,
        cv_pct=round(stdev(window) / mean_ln * 100, 1) if mean_ln > 0 else None,
    )
    return result
