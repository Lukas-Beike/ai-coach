"""Pure projections for archived and planned calendar weather."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from backend.weather import projection


def decode_history(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value.copy()
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, RecursionError):
        return {}
    return parsed.copy() if isinstance(parsed, dict) else {}


def remember_forecasts(history: Any, *caches: Any) -> dict[str, Any]:
    result = decode_history(history)
    for cached in caches:
        if not isinstance(cached, dict) or not isinstance(cached.get("forecast"), dict):
            continue
        location = cached.get("location")
        location_name = location.get("name") if isinstance(location, dict) else None
        for row in projection.daily_summary(cached["forecast"]):
            result[row["date"]] = {
                **row,
                "forecast_saved_at": cached.get("fetched_at"),
                "forecast_location": location_name or cached.get("query"),
            }
    return result


def calendar_state(history: Any, weather: Any, *, today: date) -> dict[str, Any]:
    source_weather = weather if isinstance(weather, dict) else {}
    today_text = today.isoformat()
    days = {
        day: {**row, "archived_forecast": True}
        for day, row in decode_history(history).items()
        if isinstance(day, str) and day < today_text and isinstance(row, dict)
    }
    location = source_weather.get("location")
    location_name = location.get("name") if isinstance(location, dict) else None
    weather_days = source_weather.get("days")
    for row in weather_days if isinstance(weather_days, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("date"), str):
            continue
        day = row["date"]
        days[day] = {
            **row,
            "archived_forecast": day < today_text,
            "forecast_saved_at": source_weather.get("fetched_at"),
            "forecast_location": location_name,
        }
    return {**source_weather, "days": [days[day] for day in sorted(days)]}


def _date_name(item: dict[str, Any], default_name: str) -> tuple[str, str]:
    day = str(item.get("start_date_local") or item.get("date") or "")[:10]
    name = str(item.get("name") or default_name)[:200]
    return day, name


def add_to_planned(
    planned: list[dict[str, Any]],
    weather: Any,
    *,
    default_name: str = "Geplante Einheit",
) -> list[dict[str, Any]]:
    recommendations = (
        weather.get("recommendations") if isinstance(weather, dict) else None
    )
    if not isinstance(recommendations, list):
        recommendations = []

    by_id: dict[str, dict[str, Any]] = {}
    by_date_name: dict[tuple[Any, Any], dict[str, Any]] = {}
    for recommendation in recommendations:
        if not isinstance(recommendation, dict):
            continue
        if recommendation.get("event_id"):
            by_id[str(recommendation.get("event_id"))] = recommendation
        by_date_name[(recommendation.get("date"), recommendation.get("event_name"))] = (
            recommendation
        )

    enriched = []
    for event in planned:
        if not isinstance(event, dict):
            continue
        copy = event.copy()
        recommendation = by_id.get(str(event.get("id"))) or by_date_name.get(
            _date_name(event, default_name)
        )
        if recommendation is not None:
            copy["weather_recommendation"] = recommendation
        enriched.append(copy)
    return enriched
