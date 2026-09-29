"""Athlete-local wall-clock service."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from backend.athlete.profile import timezone_name


class AthleteProfileReader(Protocol):
    """Read the athlete's current local profile."""

    def get(self) -> dict[str, str]: ...


class AthleteLocalClock:
    """Resolve current local time using the athlete's saved timezone."""

    def __init__(
        self,
        profile: AthleteProfileReader,
        now: Callable[..., datetime] = datetime.now,
        database_lock: Any | None = None,
    ) -> None:
        self._profile = profile
        self._now = now
        self._database_lock = database_lock

    def now(self) -> datetime:
        lock = self._database_lock or nullcontext()
        with lock:
            timezone = timezone_name(self._profile.get().get("timezone"))
        try:
            return self._now(ZoneInfo(timezone))
        except Exception:
            return self._now().astimezone()
