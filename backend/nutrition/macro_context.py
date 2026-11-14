"""Gather optional local inputs for nutrition reference ranges."""

import logging
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.errors import AppError
from backend.performance.current_metrics import PROFILE_SOURCE_LABEL, as_number


def body_weight(
    performance_service: Callable[[], Any], profile_service: Callable[[], Any]
) -> dict[str, Any] | None:
    """The resolved weight metric (``value``, ``source``), else the profile weight.

    Shared by the nutrition ranges and the race plan (#2803).
    """
    try:
        performance = performance_service().performance_state()["performance"]
        weight = performance.get("metrics", {}).get("weight_kg")
    except AppError, OSError, RuntimeError, ValueError:
        logging.getLogger("intervals_coach").warning(
            "Nutrition performance data unavailable"
        )
        weight = None
    if isinstance(weight, dict) and weight.get("value") is not None:
        return weight
    value = as_number(profile_service().get().get("weight_kg"))
    return None if value is None else {"value": value, "source": PROFILE_SOURCE_LABEL}


def macro_context(
    performance_service: Callable[[], Any],
    plan_service: Callable[[], Any],
    profile_service: Callable[[], Any],
    day: str,
) -> tuple[Any, Any]:
    """Weight and the training calendar around ``day`` (an ISO date)."""
    weight = (body_weight(performance_service, profile_service) or {}).get("value")
    try:
        calendar = plan_service().read_training_day(date.fromisoformat(day))
    except AppError, OSError, RuntimeError, ValueError:
        logging.getLogger("intervals_coach").warning(
            "Nutrition training data unavailable"
        )
        calendar = None
    return weight, calendar
