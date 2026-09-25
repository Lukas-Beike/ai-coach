"""Athlete-local wall-clock service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.athlete.profile import timezone_name


class AthleteLocalClock:
    """Resolve current local time using the athlete's saved timezone."""

    def __init__(
        self,
        profile_timezone: Callable[[], Any],
        now: Callable[..., datetime] = datetime.now,
    ) -> None:
        self._profile_timezone = profile_timezone
        self._now = now

    def now(self) -> datetime:
        timezone = timezone_name(self._profile_timezone())
        try:
            return self._now(ZoneInfo(timezone))
        except Exception:
            return self._now().astimezone()
