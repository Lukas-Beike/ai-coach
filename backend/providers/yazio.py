"""Read-only, bounded access to the unofficial Yazio product API.

Only food search terms and barcodes leave the server, together with the
configured account login. Tokens stay in memory and no payload is logged.
"""

from __future__ import annotations

import copy
import http.client
import json
import math
import re
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request

from backend.config import Config
from backend.errors import AppError
from backend.providers.http import (
    ProviderInvalidResponse,
    ProviderResponseTooLarge,
    request_json,
    urlopen,
)

BASE_URL = "https://yzapi.yazio.com/v22"
# Yazio answers 403 version_blocked to unrecognized clients; override with
# YAZIO_USER_AGENT when the shipped default is blocked.
DEFAULT_USER_AGENT = (
    "YAZIO/26.30.1 (com.yazio.ios.YAZIO; build:2607271240; iOS 27.0.0) Ktor"
)
# The mobile app's OAuth client. Every install ships the same public pair, so it
# identifies the app rather than the athlete and is not a credential.
CLIENT_ID = "3_5rbw4kehpugw8ogsc8ck8oo4ogswgckcskc04gcg8kk8k48ssw"
CLIENT_SECRET = "25gdtt1hvdi8gwowoww4oo88sgsw0oo04o0og0kkgwwks8k0k"
UNAVAILABLE = "Yazio ist momentan nicht verfügbar. Nächste Datenquelle verwenden."
THROTTLED = "Yazio begrenzt die Anfragen. Bitte später erneut versuchen."
SOURCE = "Yazio"
_PRODUCT_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)
_SEARCH_LIMIT = 8
_BARCODE_DETAILS = 3
_SERVING_LIMIT = 10
_LOGIN_BACKOFF_SECONDS = 900
_TOKEN_MARGIN_SECONDS = 60
_REQUESTS_PER_MINUTE = 20
_CACHE_SECONDS = 86400
_CACHE_ENTRIES = 256
# Yazio reports nutrients per one gram or millilitre, as kilocalories and grams.
_PER_100 = 100


def _number(value: Any, maximum: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except TypeError, ValueError:
        return None
    return (
        round(number, 4) if math.isfinite(number) and 0 <= number <= maximum else None
    )


def _per_100(nutrients: dict[str, Any], key: str, maximum: float) -> float | None:
    value = _number(nutrients.get(key), maximum / _PER_100)
    return None if value is None else round(value * _PER_100, 4)


def _servings(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    servings = []
    for item in raw[:_SERVING_LIMIT]:
        if not isinstance(item, dict):
            continue
        amount = _number(item.get("amount"), 100_000)
        label = str(item.get("serving") or "").strip()[:60]
        if amount and label:
            servings.append({"label": label, "amount": amount})
    return servings


def _nutrition(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Per-100 values, or None when the record has none or looks mis-scaled."""
    nutrients = raw.get("nutrients")
    nutrients = nutrients if isinstance(nutrients, dict) else {}
    kcal = _per_100(nutrients, "energy.energy", 1000)
    macros = {
        "carbs_g": _per_100(nutrients, "nutrient.carb", 100),
        "protein_g": _per_100(nutrients, "nutrient.protein", 100),
        "fat_g": _per_100(nutrients, "nutrient.fat", 100),
    }
    known = [value for value in macros.values() if value is not None]
    # A scale error shows as macros above 100 g per 100 g; never guess a value.
    if sum(known) > 110 or (kcal is None and not known):
        return None
    return {
        "kcal": kcal,
        **macros,
        "sugar_g": _per_100(nutrients, "nutrient.sugar", 100),
        "fiber_g": _per_100(nutrients, "nutrient.dietaryfiber", 100),
        "salt_g": _per_100(nutrients, "nutrient.salt", 100),
    }


def _barcode(raw: dict[str, Any]) -> str | None:
    eans = raw.get("eans")
    if not isinstance(eans, list):
        return None
    return next((str(e) for e in eans if re.fullmatch(r"\d{8,14}", str(e))), None)


def project_product(raw: Any, product_id: Any = None) -> dict[str, Any] | None:
    """Project a search hit or product detail to the shared food record."""
    if not isinstance(raw, dict):
        return None
    identifier = str(product_id or raw.get("product_id") or "")
    name = str(raw.get("name") or "").strip()
    if not _PRODUCT_ID.fullmatch(identifier) or not name:
        return None
    if raw.get("is_deleted") or raw.get("is_private"):
        return None
    per_100 = _nutrition(raw)
    if per_100 is None:
        return None
    unit = {"g": "g", "ml": "ml"}.get(str(raw.get("base_unit") or "").lower())
    food: dict[str, Any] = {
        "id": "yazio:" + identifier.lower(),
        "name": name[:160],
        "brands": str(raw.get("producer") or "")[:120],
        "source": SOURCE,
        "source_url": "https://www.yazio.com/",
        "license": "Yazio, inoffizielle Schnittstelle, nur zur privaten Nutzung",
        "basis_amount": 100,
        "basis_unit": unit,
        "per_100": per_100,
        "quality": "verified_product"
        if raw.get("is_verified")
        else "community_label_data",
        "origins": {},
        "preparation": "unknown",
        "last_modified": None,
    }
    if barcode := _barcode(raw):
        food["barcode"] = barcode
    if servings := _servings(raw.get("servings")):
        food["servings"] = servings
    return food


def _throttled() -> AppError:
    return AppError(429, THROTTLED, reason="food_database_rate_limited")


def _retry_after(headers: Any) -> float:
    value = headers.get("Retry-After") if headers is not None else None
    return max(60.0, _number(value, 86400) or 60.0)


class YazioClient:
    """Authenticate, search and read products; in-memory tokens and caches."""

    def __init__(
        self,
        config: Callable[[], Config],
        *,
        opener: Any = urlopen,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._opener = opener
        self._clock = clock
        self._lock = threading.Lock()
        self._network = threading.Lock()
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._requests: deque[float] = deque()
        self._blocked_until = 0.0
        self._login_blocked_until = 0.0
        self._identity: tuple[str, ...] = ()
        self._identity_generation = 0
        self._access_token = ""
        self._refresh_token = ""
        self._expires_at = 0.0
        self._last_check: dict[str, Any] | None = None

    @property
    def configured(self) -> bool:
        return self._config().yazio_configured

    def connection_status(self) -> dict[str, Any]:
        """Read only local verification state; never contact the provider."""
        with self._lock:
            self._follow_credentials()
            if not self._config().yazio_configured:
                return {"status": "not_configured", "checked_at": None}
            return dict(self._last_check or {"status": "unchecked", "checked_at": None})

    def check_connection(self) -> dict[str, Any]:
        """Check authentication through the same token, limits and backoff as lookup."""
        with self._network:
            with self._lock:
                self._follow_credentials()
                config = self._config()
                if not config.yazio_configured:
                    return {"status": "not_configured", "checked_at": None}
                identity = self._identity
                identity_generation = self._identity_generation
                tokens = (self._access_token, self._refresh_token, self._expires_at)
            try:
                now = self._clock()
                if now < self._blocked_until:
                    raise _throttled()
                if now < self._login_blocked_until:
                    raise AppError(503, UNAVAILABLE, reason="food_database_auth_failed")
                self._grant(
                    {
                        "grant_type": "password",
                        "username": config.yazio_email,
                        "password": config.yazio_password,
                    },
                    now,
                    sign_in=True,
                )
                result = "success"
            except AppError as exc:
                with self._lock:
                    self._follow_credentials()
                    if identity_generation == self._identity_generation:
                        self._access_token, self._refresh_token, self._expires_at = (
                            tokens
                        )
                result = {
                    "food_database_auth_failed": "auth_failed",
                    "food_database_rate_limited": "rate_limited",
                }.get(exc.reason or "", "unavailable")
            with self._lock:
                self._follow_credentials()
                if (
                    identity != self._identity
                    or identity_generation != self._identity_generation
                ):
                    return {
                        "status": "unchecked"
                        if self._config().yazio_configured
                        else "not_configured",
                        "checked_at": None,
                    }
                self._last_check = {
                    "status": result,
                    "checked_at": datetime.now(UTC).isoformat(),
                }
                return dict(self._last_check)

    def search(self, query: str) -> list[dict[str, Any]]:
        params = urlencode(
            {
                "query": query,
                "sex": "male",
                "countries": self._country(),
                "locales": "de_" + self._country(),
            }
        )
        payload = self._get("/products/search?" + params)
        if not isinstance(payload, list):
            raise AppError(502, UNAVAILABLE, reason="food_database_invalid_response")
        return [
            food
            for raw in payload[:_SEARCH_LIMIT]
            if (food := project_product(raw)) is not None
        ]

    def _country(self) -> str:
        country = self._config().yazio_country.strip().upper()
        return country if re.fullmatch(r"[A-Z]{2}", country) else "DE"

    def product(self, product_id: str) -> dict[str, Any]:
        if not _PRODUCT_ID.fullmatch(product_id):
            raise AppError(400, "Ungültige Yazio-Produkt-ID.")
        payload = self._get("/products/" + quote(product_id.lower(), safe=""))
        food = project_product(payload, product_id)
        if food is None:
            raise AppError(
                404, "Produkt oder Nährwerte nicht gefunden.", reason="food_not_found"
            )
        return food

    def barcode(self, barcode: str) -> dict[str, Any] | None:
        """Return the product whose EAN equals the barcode, if Yazio has one."""
        for hit in self.search(barcode)[:_BARCODE_DETAILS]:
            try:
                detail = self._get("/products/" + quote(hit["id"][6:], safe=""))
            except AppError as exc:
                # A deleted or hidden candidate must not hide the next one.
                if exc.reason == "food_not_found":
                    continue
                raise
            eans = detail.get("eans") if isinstance(detail, dict) else None
            if isinstance(eans, list) and barcode in {str(ean) for ean in eans}:
                return project_product(detail, hit["id"][6:])
        return None

    def _get(self, path: str) -> Any:
        # Cached reads only take the short state lock. Requests are serialized by
        # the network lock so concurrent Coach jobs cannot exceed the limit or log
        # in twice, and a slow Yazio call never blocks a cache hit.
        with self._lock:
            self._follow_credentials()
            if not self._config().yazio_configured:
                raise AppError(
                    409,
                    "Yazio ist nicht konfiguriert.",
                    reason="not_configured",
                )
            if (cached := self._cached(path)) is not None:
                return cached
        with self._network:
            with self._lock:
                if (cached := self._cached(path)) is not None:
                    return cached
                self._reserve(self._clock())
            identity = self._identity
            payload = self._authorized_get(path)
            with self._lock:
                if identity != self._identity:
                    # The account changed meanwhile; do not cache its answer.
                    return copy.deepcopy(payload)
                self._cache[path] = (self._clock(), payload)
                self._cache.move_to_end(path)
                while len(self._cache) > _CACHE_ENTRIES:
                    self._cache.popitem(last=False)
            return copy.deepcopy(payload)

    def _cached(self, path: str) -> Any:
        cached = self._cache.get(path)
        if cached and self._clock() - cached[0] < _CACHE_SECONDS:
            self._cache.move_to_end(path)
            return copy.deepcopy(cached[1])
        return None

    def _reserve(self, now: float) -> None:
        while self._requests and now - self._requests[0] >= 60:
            self._requests.popleft()
        if now < self._blocked_until or len(self._requests) >= _REQUESTS_PER_MINUTE:
            raise AppError(
                429,
                "Yazio-Suche ist kurzzeitig begrenzt. Bitte später erneut versuchen.",
                reason="food_database_rate_limited",
            )
        self._requests.append(now)

    def _authorized_get(self, path: str) -> Any:
        for attempt in (1, 2):
            if attempt == 2:
                self._reserve(self._clock())
            token = self._token()
            request = Request(
                BASE_URL + path,
                headers={
                    **self._headers(),
                    "Authorization": "Bearer " + token,
                    "Accept-Language": "de",
                },
            )
            try:
                return self._call(request)
            except HTTPError as exc:
                # An expired or revoked token is renewed once.
                if exc.code == 401 and attempt == 1:
                    self._access_token = ""
                    continue
                self._raise_http_error(exc)
        raise AppError(502, UNAVAILABLE, reason="food_database_unavailable")

    def _headers(self) -> dict[str, str]:
        agent = self._config().yazio_user_agent.strip() or DEFAULT_USER_AGENT
        return {"User-Agent": agent, "Accept": "application/json"}

    def _call(self, request: Request) -> Any:
        try:
            response = request_json(
                request, timeout=10, max_bytes=500_000, opener=self._opener
            )
        except HTTPError:
            raise
        except (
            URLError,
            OSError,
            http.client.HTTPException,
            ProviderInvalidResponse,
            ProviderResponseTooLarge,
        ):
            raise AppError(
                502, UNAVAILABLE, reason="food_database_unavailable"
            ) from None
        return response.payload

    def _raise_http_error(self, exc: HTTPError) -> None:
        if exc.code == 403:
            try:
                raw = exc.read(4097)
                payload = json.loads(raw) if len(raw) <= 4096 else None
            except OSError, http.client.HTTPException, ValueError, TypeError:
                payload = None
            if isinstance(payload, dict) and payload.get("error") == "version_blocked":
                raise AppError(
                    502,
                    "Yazio lehnt die App-Version ab. YAZIO_USER_AGENT prüfen.",
                    reason="food_database_version_blocked",
                ) from None
        if exc.code == 404:
            raise AppError(
                404, "Produkt nicht gefunden.", reason="food_not_found"
            ) from None
        if exc.code == 429:
            self._blocked_until = self._clock() + _retry_after(exc.headers)
            raise _throttled() from None
        raise AppError(502, UNAVAILABLE, reason="food_database_unavailable") from None

    def _follow_credentials(self) -> None:
        """Forget tokens, pauses and cached results of a replaced account."""
        config = self._config()
        identity = (
            config.yazio_email,
            config.yazio_password,
            str(config.yazio_credential_generation),
        )
        if identity != self._identity:
            self._identity = identity
            self._identity_generation += 1
            self._last_check = None
            self._access_token = self._refresh_token = ""
            self._login_blocked_until = 0.0
            self._cache.clear()

    def _token(self) -> str:
        self._follow_credentials()
        config = self._config()
        now = self._clock()
        if self._access_token and now < self._expires_at - _TOKEN_MARGIN_SECONDS:
            return self._access_token
        if self._refresh_token and self._grant(
            {"grant_type": "refresh_token", "refresh_token": self._refresh_token},
            now,
            sign_in=False,
        ):
            return self._access_token
        if now < self._blocked_until:
            raise _throttled()
        if self._refresh_token:
            # The refresh failed without a rejection: an outage, not a bad login.
            raise AppError(502, UNAVAILABLE, reason="food_database_unavailable")
        if now < self._login_blocked_until:
            raise AppError(
                503,
                "Yazio-Anmeldung ist pausiert. Zugangsdaten prüfen.",
                reason="food_database_auth_failed",
            )
        self._grant(
            {
                "grant_type": "password",
                "username": config.yazio_email,
                "password": config.yazio_password,
            },
            now,
            sign_in=True,
        )
        return self._access_token

    def _grant(self, fields: dict[str, str], now: float, *, sign_in: bool) -> bool:
        identity = self._identity
        identity_generation = self._identity_generation
        body = json.dumps(
            {
                **fields,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            }
        ).encode("utf-8")
        request = Request(
            BASE_URL + "/oauth/token",
            data=body,
            method="POST",
            headers={**self._headers(), "Content-Type": "application/json"},
        )
        self._reserve(now)
        try:
            payload = self._call(request)
        except HTTPError as exc:
            with self._lock:
                self._follow_credentials()
                if (
                    identity != self._identity
                    or identity_generation != self._identity_generation
                ):
                    return self._grant_unusable(sign_in, "food_database_unavailable")
                return self._grant_rejected(exc, now, sign_in=sign_in)
        with self._lock:
            self._follow_credentials()
            if (
                identity != self._identity
                or identity_generation != self._identity_generation
            ):
                # The account changed during the login; its token is not wanted.
                return self._grant_unusable(sign_in, "food_database_unavailable")
            token = payload.get("access_token") if isinstance(payload, dict) else None
            lifetime = _number(
                payload.get("expires_in") if isinstance(payload, dict) else None,
                31_536_000,
            )
            if not isinstance(token, str) or not token or not lifetime:
                return self._grant_unusable(sign_in, "food_database_invalid_response")
            self._access_token = token
            self._expires_at = now + lifetime
            refresh = payload.get("refresh_token")
            self._refresh_token = refresh if isinstance(refresh, str) else ""
            return True

    def _grant_unusable(self, sign_in: bool, reason: str) -> bool:
        self._access_token = ""
        if sign_in:
            raise AppError(502, UNAVAILABLE, reason=reason)
        return False

    def _grant_rejected(self, exc: HTTPError, now: float, *, sign_in: bool) -> bool:
        self._access_token = ""
        if exc.code == 429:
            self._blocked_until = self._clock() + _retry_after(exc.headers)
        rejected = exc.code in {400, 401, 403}
        if not sign_in:
            if rejected:
                self._refresh_token = ""
            return False
        if exc.code == 429:
            raise _throttled() from None
        if rejected:
            self._login_blocked_until = now + _LOGIN_BACKOFF_SECONDS
            raise AppError(
                503,
                "Yazio hat die Anmeldung abgelehnt. Zugangsdaten prüfen.",
                reason="food_database_auth_failed",
            ) from None
        raise AppError(502, UNAVAILABLE, reason="food_database_unavailable") from None
