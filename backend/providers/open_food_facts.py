"""Read-only, bounded Open Food Facts access without credentials or payload logs."""

from __future__ import annotations

import copy
import math
import re
import threading
import time
from collections import OrderedDict, deque
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

from backend.errors import AppError
from backend.providers.http import (
    ProviderInvalidResponse,
    ProviderResponseTooLarge,
    request_json,
    urlopen,
)

BASE_URL = "https://world.openfoodfacts.org"
FIELDS = "code,product_name,product_name_de,brands,nutrition,nutriments,nutrition_data_per,last_modified_t"
UNAVAILABLE = "Open Food Facts ist momentan nicht verfügbar. Verpackungswerte verwenden oder Schätzung kennzeichnen."


def _number(value: Any, maximum: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return (
        round(number, 4) if math.isfinite(number) and 0 <= number <= maximum else None
    )


def _nutrition_values(
    raw: dict[str, Any],
) -> tuple[dict[str, Any], Any, dict[str, str], str]:
    nutrition = raw.get("nutrition")
    if isinstance(nutrition, dict):
        aggregate = nutrition.get("aggregated_set")
        if not isinstance(aggregate, dict):
            return {}, None, {}, "unknown"
        nutrients = aggregate.get("nutrients")
        if not isinstance(nutrients, dict):
            return {}, None, {}, "unknown"
        values = {}
        origins = {}
        for name, unit in (
            ("energy-kcal", "kcal"),
            ("energy", "kJ"),
            ("carbohydrates", "g"),
            ("proteins", "g"),
            ("fat", "g"),
        ):
            entry = nutrients.get(name)
            if not isinstance(entry, dict) or entry.get("unit") != unit:
                continue
            # OFF may fill gaps with AI estimates. Do not disguise these as label values.
            if entry.get("source") == "estimate" or entry.get("modifier"):
                continue
            key = "energy-kj" if name == "energy" else name
            values[key + "_100g"] = entry.get("value")
            origins[key] = str(entry.get("source") or "unknown")[:40]
        preparation = str(aggregate.get("preparation") or "unknown")[:40]
        return values, aggregate.get("per"), origins, preparation
    # The documented CGI text-search endpoint still returns the flat nutriments representation.
    nutrients = raw.get("nutriments")
    return (
        nutrients if isinstance(nutrients, dict) else {},
        raw.get("nutrition_data_per"),
        {},
        "as_sold",
    )


def project_product(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not re.fullmatch(
        r"\d{8,14}", str(raw.get("code", ""))
    ):
        return None
    nutrients, basis, origins, preparation = _nutrition_values(raw)
    kcal = _number(nutrients.get("energy-kcal_100g"), 1000)
    if kcal is None:
        kj = _number(nutrients.get("energy-kj_100g"), 4200)
        kcal = round(kj / 4.184, 4) if kj is not None else None
    # OFF uses *_100g for both grams and millilitres. Never guess the unit.
    unit = "ml" if basis == "100ml" else "g" if basis == "100g" else None
    return {
        "id": "off:" + str(raw["code"]),
        "name": str(raw.get("product_name_de") or raw.get("product_name") or "Produkt")[
            :160
        ],
        "brands": str(raw.get("brands") or "")[:120],
        "source": "Open Food Facts",
        "source_url": BASE_URL + "/product/" + str(raw["code"]),
        "license": "ODbL 1.0 / Database Contents License",
        "basis_amount": 100,
        "basis_unit": unit,
        "per_100": {
            "kcal": kcal,
            "carbs_g": _number(nutrients.get("carbohydrates_100g"), 100),
            "protein_g": _number(nutrients.get("proteins_100g"), 100),
            "fat_g": _number(nutrients.get("fat_100g"), 100),
        },
        "quality": "community_label_data",
        "origins": origins,
        "preparation": preparation,
        "last_modified": _number(raw.get("last_modified_t"), 10_000_000_000),
    }


class OpenFoodFactsClient:
    """Cache for 24 h; rolling per-process limits below the provider's IP limits."""

    def __init__(self, *, opener: Any = urlopen, clock: Any = time.monotonic) -> None:
        self._opener = opener
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._requests: dict[str, deque[float]] = {
            "product": deque(),
            "search": deque(),
        }
        self._blocked_until = 0.0

    def search(self, query: str) -> list[dict[str, Any]]:
        # Legacy CGI is OFF's documented text-search endpoint; v2 has no text search.
        params = urlencode(
            {
                "search_terms": query,
                "search_simple": 1,
                "action": "process",
                "json": 1,
                "page_size": 5,
                "fields": FIELDS,
                "tagtype_0": "countries",
                "tag_contains_0": "contains",
                "tag_0": "germany",
                "lc": "de",
            }
        )
        payload = self._get("search", "/cgi/search.pl?" + params)
        products = payload.get("products", []) if isinstance(payload, dict) else []
        if not isinstance(products, list):
            raise AppError(502, UNAVAILABLE, reason="food_database_invalid_response")
        return [
            food for raw in products[:5] if (food := project_product(raw)) is not None
        ]

    def product(self, barcode: str) -> dict[str, Any]:
        if not re.fullmatch(r"\d{8,14}", barcode):
            raise AppError(400, "Barcode muss 8 bis 14 Ziffern enthalten.")
        payload = self._get(
            "product",
            f"/api/v3.6/product/{barcode}.json?"
            + urlencode({"fields": FIELDS, "lc": "de"}),
        )
        food = (
            project_product(payload.get("product"))
            if isinstance(payload, dict)
            else None
        )
        if food is None:
            raise AppError(
                404, "Produkt oder Nährwerte nicht gefunden.", reason="food_not_found"
            )
        return food

    def _get(self, category: str, path: str) -> Any:
        # Keep reservation and request under one lock so concurrent Coach jobs cannot
        # exceed the limit or duplicate the same lookup. No athlete data is logged.
        with self._lock:
            now = self._clock()
            cached = self._cache.get(path)
            if cached and now - cached[0] < 86400:
                self._cache.move_to_end(path)
                return copy.deepcopy(cached[1])
            recent = self._requests[category]
            while recent and now - recent[0] >= 60:
                recent.popleft()
            limit = 14 if category == "product" else 9
            if now < self._blocked_until or len(recent) >= limit:
                raise AppError(
                    429,
                    "Lebensmittelsuche ist kurzzeitig begrenzt. Bitte später erneut versuchen.",
                    reason="food_database_rate_limited",
                )
            recent.append(now)
            request = Request(
                BASE_URL + path,
                headers={
                    "User-Agent": "IntervalsCoach/1.0 (private nutrition lookup; https://github.com/Lukas-Beike/ai-coach)",
                    "Accept": "application/json",
                },
            )
            try:
                response = request_json(
                    request, timeout=10, max_bytes=500_000, opener=self._opener
                )
            except HTTPError as exc:
                if exc.code == 404:
                    raise AppError(
                        404, "Produkt nicht gefunden.", reason="food_not_found"
                    ) from None
                if exc.code in (429, 503):
                    retry_after = _number(
                        exc.headers.get("Retry-After")
                        if exc.headers is not None
                        else None,
                        86400,
                    )
                    self._blocked_until = self._clock() + max(60, retry_after or 60)
                    raise AppError(
                        429,
                        "Open Food Facts begrenzt die Anfragen. Bitte später erneut versuchen.",
                        reason="food_database_rate_limited",
                    ) from None
                raise AppError(
                    502, UNAVAILABLE, reason="food_database_unavailable"
                ) from None
            except (
                URLError,
                OSError,
                ProviderInvalidResponse,
                ProviderResponseTooLarge,
            ):
                raise AppError(
                    502, UNAVAILABLE, reason="food_database_unavailable"
                ) from None
            if not isinstance(response.payload, dict):
                raise AppError(
                    502, UNAVAILABLE, reason="food_database_invalid_response"
                )
            self._cache[path] = (self._clock(), response.payload)
            self._cache.move_to_end(path)
            while len(self._cache) > 256:
                self._cache.popitem(last=False)
            return copy.deepcopy(response.payload)
