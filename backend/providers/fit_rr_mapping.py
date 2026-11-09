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

from typing import Final

from backend.providers.fit_file import FitMessage, fit_scaled_array

HRV_MESSAGE: Final = 78
_TIME_FIELD: Final = 0
_TIMESTAMP_FIELD: Final = 253
# A day of beats at 100 bpm; longer series belong to no single activity.
MAX_RR_INTERVALS: Final = 150_000
# The file clock may run this far ahead of the intervals before a dropout is assumed.
MAX_UNACCOUNTED_S: Final = 10.0


def rr_intervals_ms(messages: list[FitMessage]) -> list[list[float]]:
    """Return the file's RR intervals in milliseconds as gap-free segments, oldest first."""
    segments: list[list[float]] = [[]]
    total = 0
    clock: int | None = None
    segment_start: int | None = None
    elapsed_s = 0.0
    for number, fields in messages:
        stamp = fields.get(_TIMESTAMP_FIELD)
        if isinstance(stamp, int) and not isinstance(stamp, bool):
            clock = stamp
        if number != HRV_MESSAGE:
            continue
        if clock is not None:
            if segment_start is None:
                segment_start = clock
            elif clock - segment_start - elapsed_s > MAX_UNACCOUNTED_S:
                segments.append([])
                segment_start, elapsed_s = clock, 0.0
        slots = fit_scaled_array(fields, HRV_MESSAGE, _TIME_FIELD)
        while slots and slots[-1] is None:
            slots.pop()
        for slot in slots:
            if slot is None:
                if segments[-1]:
                    segments.append([])
                    segment_start, elapsed_s = clock, 0.0
                continue
            segments[-1].append(slot * 1000.0)
            elapsed_s += slot
            total += 1
            if total >= MAX_RR_INTERVALS:
                return [segment for segment in segments if segment]
    return [segment for segment in segments if segment]
