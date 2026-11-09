"""Beat-to-beat (RR) intervals of a FIT activity file, from its ``hrv`` messages.

Message 78 (``hrv``) holds field 0 ``time``: up to five RR intervals in seconds
(scale 1000, 0xFFFF invalid). Garmin writes it only while HRV logging is enabled
for the heart rate sensor. The intervals are returned in file order and in
milliseconds as gap-free segments; they are an input of the DFA-a1 calculation
and are never stored, logged or returned to a caller outside the mapper. A
dropout starts a new segment, so it is never spliced: an invalid slot between
valid ones in one message, and a stretch of the file clock (the latest
timestamp, for example of the record messages) that the intervals do not
account for. Invalid slots after the last valid one pad a message and are no
dropout. The module is pure and never raises for malformed content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from backend.providers.fit_file import FitMessage, fit_scaled_array

HRV_MESSAGE: Final = 78
_TIME_FIELD: Final = 0
_TIMESTAMP_FIELD: Final = 253
# A day of beats at 100 bpm; longer series belong to no single activity.
MAX_RR_INTERVALS: Final = 150_000
# The file clock may run this far ahead of the intervals before a dropout is assumed.
MAX_UNACCOUNTED_S: Final = 10.0


@dataclass
class _Segmenter:
    """Collects the intervals into gap-free segments while it follows the file clock."""

    segments: list[list[float]] = field(default_factory=lambda: [[]])
    total: int = 0
    clock: int | None = None
    segment_start: int | None = None
    elapsed_s: float = 0.0

    def observe_clock(self, fields: dict[int, object]) -> None:
        stamp = fields.get(_TIMESTAMP_FIELD)
        if isinstance(stamp, int) and not isinstance(stamp, bool):
            self.clock = stamp

    def _break(self) -> None:
        self.segments.append([])
        self.segment_start, self.elapsed_s = self.clock, 0.0

    def check_clock_gap(self) -> None:
        """Break when the file clock ran ahead of the intervals by more than a dropout."""
        if self.clock is None:
            return
        if self.segment_start is None:
            self.segment_start = self.clock
        elif self.clock - self.segment_start - self.elapsed_s > MAX_UNACCOUNTED_S:
            self._break()

    def add_message(self, fields: dict[int, object]) -> bool:
        """Add one hrv message; False once the interval limit is reached."""
        slots = fit_scaled_array(fields, HRV_MESSAGE, _TIME_FIELD)
        while slots and slots[-1] is None:
            slots.pop()
        for slot in slots:
            if slot is None:
                if self.segments[-1]:
                    self._break()
                continue
            self.segments[-1].append(slot * 1000.0)
            self.elapsed_s += slot
            self.total += 1
            if self.total >= MAX_RR_INTERVALS:
                return False
        return True

    def result(self) -> list[list[float]]:
        return [segment for segment in self.segments if segment]


def rr_intervals_ms(messages: list[FitMessage]) -> list[list[float]]:
    """Return the file's RR intervals in milliseconds as gap-free segments, oldest first."""
    segmenter = _Segmenter()
    for number, fields in messages:
        segmenter.observe_clock(fields)
        if number != HRV_MESSAGE:
            continue
        segmenter.check_clock_gap()
        if not segmenter.add_message(fields):
            break
    return segmenter.result()
