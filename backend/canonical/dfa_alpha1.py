"""First threshold heart rate from chest-strap RR intervals (DFA-a1), research grade.

Short-term detrended fluctuation analysis of beat-to-beat intervals gives the
scaling exponent alpha1. It falls from about 1 at easy effort towards 0.5 at hard
effort, and the heart rate at which it crosses 0.75 is reported to agree with the
first ventilatory threshold (Gronwald et al. 2020; Rogers et al. 2021,
Frontiers in Physiology). The result is an estimate for the athlete to review,
never a lab value.

The method, version ``METHOD_VERSION``:

* Segments: the RR series arrives as gap-free segments (a dropout of the sensor
  starts a new one). Windows never span two segments, so a gap is never spliced.
* Artifacts: RR values outside 300 to 2000 ms and values that differ by more than
  20 % from the last accepted beat are dropped.
* Windows: rolling 2-minute windows (30 s apart) on the recording's own beat
  clock. A window with more than 5 % artifacts is rejected; the rest are analysed
  without their artifacts. A window is steady or ramping when its second half's
  mean heart rate differs from the first half's by at most 8 bpm; intervals and
  recoveries are left out.
* Detrending: before windowing, each segment's artifact-free series is detrended
  with smoothness priors (Tarvainen et al. 2002, lambda 500, second-difference
  penalty, solved with a banded O(N) LDL solver), as Kubios and the DFA-a1
  studies do, so a slow drift of the RR level (a ramp) does not inflate alpha1.
* alpha1 is the slope of log F(n) against log n for box sizes n of 4 to 16 beats,
  where F(n) is the root-mean-square fluctuation of the integrated, detrended
  series after a linear detrend per box.
* The window mean heart rate is 60 000 / mean RR. alpha1 is regressed on it
  linearly; the estimate is the heart rate where the line reaches 0.75. A
  recording yields an estimate only with enough windows, a heart rate and alpha1
  range that crosses 0.75, a falling line, and a crossing inside the heart rates
  it observed. The RR series is an input only and is never kept.

Pure; stdlib and canonical records only.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from backend.canonical.activity_detail import ActivityDfaAlpha1
from backend.canonical.vocabulary import DfaQuality

METHOD_VERSION: Final = 2

MIN_RR_MS: Final = 300.0
MAX_RR_MS: Final = 2000.0
MAX_BEAT_CHANGE: Final = 0.20
# After this many beats in a row rejected only for their change, the new level is
# taken as real: a bad first beat must not reject the whole recording.
REANCHOR_AFTER: Final = 5
# Smoothness priors detrending strength (Kubios and the DFA-a1 studies use 500).
DETREND_LAMBDA: Final = 500.0
WINDOW_S: Final = 120.0
STRIDE_S: Final = 30.0
BOX_SIZES: Final = tuple(range(4, 17))
MAX_WINDOW_ARTIFACT_SHARE: Final = 0.05
MIN_WINDOW_BEATS: Final = 100
MAX_HALF_HR_STEP_BPM: Final = 8.0
THRESHOLD_ALPHA1: Final = 0.75
# The lowest alpha1 must reach this far below the threshold and the highest this
# far above it, so a recording that never crosses 0.75 gives no estimate.
CROSSING_MARGIN: Final = 0.1
MIN_WINDOWS: Final = 10
MIN_HR_SPREAD_BPM: Final = 10.0
GOOD_MIN_WINDOWS: Final = 20
GOOD_MAX_ARTIFACT_SHARE: Final = 0.03
GOOD_MIN_R_SQUARED: Final = 0.5


@dataclass(frozen=True, slots=True)
class Window:
    """One analysed window: its mean heart rate and its alpha1."""

    heart_rate_bpm: float
    alpha1: float


def artifact_flags(rr_ms: Sequence[float]) -> list[bool]:
    """Mark each beat that standard artifact correction drops.

    A beat is an artifact when it is not a finite number in 300 to 2000 ms or
    when it differs by more than 20 % from the last accepted beat.
    """
    flags: list[bool] = []
    reference: float | None = None
    rejected_in_a_row = 0
    for value in rr_ms:
        if not math.isfinite(value) or not MIN_RR_MS <= value <= MAX_RR_MS:
            flags.append(True)
            continue
        if reference is None or abs(value - reference) <= MAX_BEAT_CHANGE * reference:
            reference = value
            rejected_in_a_row = 0
            flags.append(False)
            continue
        rejected_in_a_row += 1
        if rejected_in_a_row >= REANCHOR_AFTER:
            reference = value
            rejected_in_a_row = 0
            flags.append(False)
            continue
        flags.append(True)
    return flags


def alpha1(series: Sequence[float]) -> float | None:
    """The short-term DFA scaling exponent of ``series``, or None if undefined.

    None when the series is shorter than two boxes of the largest size or has no
    fluctuation at some box size.
    """
    count = len(series)
    if count < 2 * BOX_SIZES[-1]:
        return None
    mean = math.fsum(series) / count
    profile: list[float] = []
    total = 0.0
    for value in series:
        total += value - mean
        profile.append(total)
    log_sizes: list[float] = []
    log_fluctuations: list[float] = []
    for size in BOX_SIZES:
        boxes = count // size
        offsets = [index - (size - 1) / 2 for index in range(size)]
        offset_ss = size * (size * size - 1) / 12
        residual = 0.0
        for box in range(boxes):
            segment = profile[box * size : (box + 1) * size]
            box_mean = math.fsum(segment) / size
            cross = math.fsum(o * y for o, y in zip(offsets, segment, strict=True))
            spread = math.fsum((y - box_mean) ** 2 for y in segment)
            residual += max(spread - cross * cross / offset_ss, 0.0)
        mean_square = residual / (boxes * size)
        if mean_square <= 0.0:
            return None
        log_sizes.append(math.log(size))
        log_fluctuations.append(0.5 * math.log(mean_square))
    fit = _fit_line(log_sizes, log_fluctuations)
    return None if fit is None else fit[0]


def _fit_line(
    xs: Sequence[float], ys: Sequence[float]
) -> tuple[float, float, float] | None:
    """Least-squares slope, intercept and R squared; None for a vertical or empty set."""
    count = len(xs)
    if count < 2:
        return None
    mean_x = math.fsum(xs) / count
    mean_y = math.fsum(ys) / count
    sxx = math.fsum((x - mean_x) ** 2 for x in xs)
    if sxx <= 0.0:
        return None
    sxy = math.fsum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    syy = math.fsum((y - mean_y) ** 2 for y in ys)
    slope = sxy / sxx
    r_squared = 1.0 if syy <= 0.0 else min(1.0, sxy * sxy / (sxx * syy))
    return slope, mean_y - slope * mean_x, r_squared


def _mean_heart_rate(rr_ms: Sequence[float]) -> float:
    return 60_000.0 * len(rr_ms) / math.fsum(rr_ms)


def _penalty_bands(
    count: int, weight: float
) -> tuple[list[float], list[float], list[float]]:
    """Main, first and second sub-diagonal of ``I + weight * D'D`` for ``count`` values."""
    diag = [1.0] * count
    sub1 = [0.0] * (count - 1)
    sub2 = [0.0] * (count - 2)
    for row in range(count - 2):
        diag[row] += weight
        diag[row + 1] += 4.0 * weight
        diag[row + 2] += weight
        sub1[row] -= 2.0 * weight
        sub1[row + 1] -= 2.0 * weight
        sub2[row] += weight
    return diag, sub1, sub2


def _ldl_factor(
    diag: list[float], sub1: list[float], sub2: list[float]
) -> tuple[list[float], list[float], list[float]]:
    """LDL' of a symmetric pentadiagonal matrix: pivots, L[i][i-1] and L[i][i-2]."""
    count = len(diag)
    pivot = [0.0] * count
    low1 = [0.0] * count
    low2 = [0.0] * count
    for i in range(count):
        pivot[i] = diag[i]
        if i >= 1:
            pivot[i] -= low1[i] * low1[i] * pivot[i - 1]
        if i >= 2:
            pivot[i] -= low2[i] * low2[i] * pivot[i - 2]
        if i + 1 < count:
            cross = low2[i + 1] * low1[i] * pivot[i - 1] if i >= 1 else 0.0
            low1[i + 1] = (sub1[i] - cross) / pivot[i]
        if i + 2 < count:
            low2[i + 2] = sub2[i] / pivot[i]
    return pivot, low1, low2


def _ldl_solve(
    rhs: Sequence[float],
    pivot: list[float],
    low1: list[float],
    low2: list[float],
) -> list[float]:
    """Solve ``L D L' x = rhs`` by forward and back substitution."""
    count = len(rhs)
    forward = [0.0] * count
    for i in range(count):
        value = rhs[i]
        if i >= 1:
            value -= low1[i] * forward[i - 1]
        if i >= 2:
            value -= low2[i] * forward[i - 2]
        forward[i] = value
    solution = [0.0] * count
    for i in range(count - 1, -1, -1):
        value = forward[i] / pivot[i]
        if i + 1 < count:
            value -= low1[i + 1] * solution[i + 1]
        if i + 2 < count:
            value -= low2[i + 2] * solution[i + 2]
        solution[i] = value
    return solution


def detrend(series: Sequence[float], smoothing: float = DETREND_LAMBDA) -> list[float]:
    """Remove the slow trend of ``series`` with smoothness priors.

    The trend ``x`` solves ``(I + smoothing^2 D'D) x = z`` where ``D`` is the
    second-difference operator; the result is ``z - x``. ``I + smoothing^2 D'D``
    is symmetric positive definite and pentadiagonal, so an LDL' factorization
    with two sub-diagonals solves it in O(N). A series shorter than three values
    has no second difference and is returned unchanged.
    """
    count = len(series)
    if count < 3:
        return list(series)
    pivot, low1, low2 = _ldl_factor(*_penalty_bands(count, smoothing * smoothing))
    trend = _ldl_solve(series, pivot, low1, low2)
    return [series[i] - trend[i] for i in range(count)]


def _segment_windows(rr_ms: Sequence[float]) -> tuple[list[Window], int]:
    """The steady windows of one gap-free segment and its number of artifacts."""
    flags = artifact_flags(rr_ms)
    artifacts = sum(flags)
    kept_index = [i for i, flagged in enumerate(flags) if not flagged]
    residual_at: dict[int, float] = dict(
        zip(kept_index, detrend([rr_ms[i] for i in kept_index]), strict=True)
    )
    ends: list[float] = []
    elapsed = 0.0
    for value in rr_ms:
        elapsed += min(max(value, MIN_RR_MS), MAX_RR_MS) / 1000.0
        ends.append(elapsed)
    windows: list[Window] = []
    start = 0.0
    while start + WINDOW_S <= elapsed:
        low = bisect_right(ends, start)
        high = bisect_right(ends, start + WINDOW_S)
        start += STRIDE_S
        beats = high - low
        if beats < MIN_WINDOW_BEATS:
            continue
        if sum(flags[low:high]) / beats > MAX_WINDOW_ARTIFACT_SHARE:
            continue
        kept = [i for i in range(low, high) if not flags[i]]
        if len(kept) < MIN_WINDOW_BEATS:
            continue
        rates = [rr_ms[i] for i in kept]
        middle = len(rates) // 2
        step = abs(_mean_heart_rate(rates[middle:]) - _mean_heart_rate(rates[:middle]))
        if step > MAX_HALF_HR_STEP_BPM:
            continue
        exponent = alpha1([residual_at[i] for i in kept])
        if exponent is not None:
            windows.append(Window(_mean_heart_rate(rates), exponent))
    return windows, artifacts


def rolling_windows(
    segments: Sequence[Sequence[float]],
) -> tuple[list[Window], float]:
    """The steady or ramping windows of a recording and its artifact share (0 to 1).

    ``segments`` are gap-free runs of RR intervals; a window lies inside one
    segment, so a gap is never spliced. Windows are 2 minutes long on the
    segment's beat clock (the running sum of the intervals, each limited to
    0.3 to 2 s) and start 30 seconds apart.
    """
    windows: list[Window] = []
    artifacts = beats = 0
    for segment in segments:
        found, flagged = _segment_windows(segment)
        windows.extend(found)
        artifacts += flagged
        beats += len(segment)
    return windows, (artifacts / beats if beats else 0.0)


def first_threshold(
    segments: Sequence[Sequence[float]],
) -> ActivityDfaAlpha1 | None:
    """The first threshold heart rate one recording gives, or None without a crossing."""
    windows, share = rolling_windows(segments)
    if len(windows) < MIN_WINDOWS:
        return None
    rates = [window.heart_rate_bpm for window in windows]
    exponents = [window.alpha1 for window in windows]
    if max(rates) - min(rates) < MIN_HR_SPREAD_BPM:
        return None
    if (
        min(exponents) > THRESHOLD_ALPHA1 - CROSSING_MARGIN
        or max(exponents) < THRESHOLD_ALPHA1 + CROSSING_MARGIN
    ):
        return None
    fit = _fit_line(rates, exponents)
    if fit is None:
        return None
    slope, intercept, r_squared = fit
    if slope >= 0.0:
        return None
    estimate = (THRESHOLD_ALPHA1 - intercept) / slope
    if not min(rates) <= estimate <= max(rates):
        return None
    good = (
        len(windows) >= GOOD_MIN_WINDOWS
        and share <= GOOD_MAX_ARTIFACT_SHARE
        and r_squared >= GOOD_MIN_R_SQUARED
    )
    try:
        return ActivityDfaAlpha1(
            estimate_bpm=round(estimate, 1),
            windows=len(windows),
            artifact_share=round(share, 4),
            quality=DfaQuality.GOOD if good else DfaQuality.LOW,
            method=METHOD_VERSION,
        )
    except TypeError, ValueError:
        return None
