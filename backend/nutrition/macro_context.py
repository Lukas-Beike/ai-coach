"""Gather optional local inputs for nutrition reference ranges."""

import logging
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.errors import AppError
from backend.performance.current_metrics import as_number


def macro_context(
    performance_service: Callable[[], Any],
    plan_service: Callable[[], Any],
    profile_service: Callable[[], Any],
    day: str,
) -> tuple[Any, Any]:
    """Weight and the training calendar around ``day`` (an ISO date)."""
    try:
        performance = performance_service().performance_state()["performance"]
        weight = performance.get("metrics", {}).get("weight_kg", {}).get("value")
    except AppError, OSError, RuntimeError, ValueError:
        logging.getLogger("intervals_coach").warning(
            "Nutrition performance data unavailable"
        )
        weight = None
    if weight is None:
        weight = as_number(profile_service().get().get("weight_kg"))
    try:
        calendar = plan_service().read_training_day(date.fromisoformat(day))
    except AppError, OSError, RuntimeError, ValueError:
        logging.getLogger("intervals_coach").warning(
            "Nutrition training data unavailable"
        )
        calendar = None
    return weight, calendar
