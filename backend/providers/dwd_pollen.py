"""DWD pollen-flight hazard index provider for German locations."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

DWD_POLLEN_URL = "https://opendata.dwd.de/climate_environment/health/alerts/s31fg.json"
DWD_GEOSERVER_URL = "https://maps.dwd.de/geoserver/dwd/ows?"
DWD_POLLEN_LEVELS = ("0", "0-1", "1", "1-2", "2", "2-3", "3")
DWD_POLLEN_SPECIES = {
    "Hasel": "Hasel",
    "Erle": "Erle",
    "Esche": "Esche",
    "Birke": "Birke",
    "Graeser": "Gräser",
    "Roggen": "Roggen",
    "Beifuss": "Beifuß",
    "Ambrosia": "Ambrosia",
}
_FORECAST_OFFSETS = (("today", 0), ("tomorrow", 1), ("dayafter_to", 2))


def pollen_region_params(location: dict[str, Any]) -> dict[str, Any]:
    """Build the WFS point query that resolves a DWD pollen region."""
    latitude = round(float(location["latitude"]), 4)
    longitude = round(float(location["longitude"]), 4)
    return {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": "dwd:Pollenfluggebiete",
        "outputFormat": "application/json",
        "propertyName": "GF",
        "CQL_FILTER": f"INTERSECTS(THE_GEOM,POINT({longitude} {latitude}))",
    }


def pollen_region_id(response: Any) -> int | None:
    """Return the DWD region id of the first matching region feature."""
    features = response.get("features") if isinstance(response, dict) else None
    for feature in features if isinstance(features, list) else []:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        value = properties.get("GF") if isinstance(properties, dict) else None
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value > 0
        ):
            return int(value)
    return None


def _feed_date(value: Any) -> date | None:
    match = re.match(r"(\d{4}-\d{2}-\d{2})\b", str(value or ""))
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _region_entry(feed: dict[str, Any], region_id: int) -> dict[str, Any] | None:
    content = feed.get("content")
    for entry in content if isinstance(content, list) else []:
        if not isinstance(entry, dict):
            continue
        partregion = entry.get("partregion_id")
        if partregion == region_id or (
            partregion == -1 and entry.get("region_id") == region_id
        ):
            return entry
    return None


def pollen_forecast(feed: Any, region_id: int) -> dict[str, Any] | None:
    """Project the DWD feed to validated per-date levels for one region.

    Unknown species and level values are ignored; feed text is data only.
    """
    if not isinstance(feed, dict):
        return None
    issued = _feed_date(feed.get("last_update"))
    entry = _region_entry(feed, region_id)
    pollen = entry.get("Pollen") if entry else None
    if issued is None or entry is None or not isinstance(pollen, dict):
        return None
    days: dict[str, dict[str, str]] = {}
    for key, offset in _FORECAST_OFFSETS:
        levels = {
            label: str(values.get(key))
            for source_name, label in DWD_POLLEN_SPECIES.items()
            if isinstance(values := pollen.get(source_name), dict)
            and str(values.get(key)) in DWD_POLLEN_LEVELS
        }
        if levels:
            days[(issued + timedelta(days=offset)).isoformat()] = levels
    if not days:
        return None
    region = str(entry.get("partregion_name") or entry.get("region_name") or "")
    return {
        "source": "DWD",
        "region": region.strip()[:100],
        "region_id": region_id,
        "issued": str(feed.get("last_update") or "")[:40],
        "days": days,
    }


class DwdPollenClient:
    """Resolve the DWD pollen region by coordinates and read its forecast."""

    def __init__(self, request: Callable[..., Any]) -> None:
        self._request = request

    def fetch(self, location: dict[str, Any]) -> dict[str, Any] | None:
        if location.get("country_code") != "DE":
            return None
        region_id = pollen_region_id(
            self._request(
                "GET",
                DWD_GEOSERVER_URL + urlencode(pollen_region_params(location)),
                timeout=10,
                service="dwd-pollen-region",
            )
        )
        if region_id is None:
            return None
        return pollen_forecast(
            self._request("GET", DWD_POLLEN_URL, timeout=10, service="dwd-pollen"),
            region_id,
        )
