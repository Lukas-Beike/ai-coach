"""Public weather endpoint state projection."""

from __future__ import annotations

from typing import Any


class PublicWeatherStateService:
    """Refresh weather state as requested and omit its internal refresh marker."""

    def __init__(self, weather_service: Any) -> None:
        self._weather_service = weather_service

    def state(self, local_only: bool = False) -> dict[str, Any]:
        result = self._weather_service.state(refresh=not local_only)
        result.pop("_refreshed", None)
        return result
