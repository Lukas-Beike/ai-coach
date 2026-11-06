"""Garmin Connect Personal API transport.

Garmin's official, read-only Personal API serves the Connect service paths and a
subset of the same JSON shapes as the unofficial SDK. This module exposes the
families it serves under the SDK's method names, so the existing collectors and
mappers read either transport, and routes every other method to the SDK when it
is connected.

The Personal API also serves the original FIT file of an activity
(``download_activity_fit``), which the SDK families do not read.

The Personal API key is exchanged for a 24-hour bearer token on demand; there is
no refresh token. Neither the key nor the token is logged, returned or stored.
"""

from __future__ import annotations

import base64
import io
import json
import threading
import time
import zipfile
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from typing import Any, Final
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request

from backend.providers import http as provider_http
from backend.providers.descriptors import GARMIN_ID

PERSONAL_BASE_URL: Final = "https://personal.connectapi.garmin.com"
TOKEN_PATH: Final = "/personalapitoken-service/personal-api/personal-api-key/token"
# Garmin documents a 24 h token lifetime; renew a little earlier.
TOKEN_LIFETIME_SECONDS: Final = 24 * 3600
TOKEN_REFRESH_MARGIN_SECONDS: Final = 600
REQUEST_TIMEOUT_SECONDS: Final = 45
MAX_RESPONSE_BYTES: Final = 10_000_000
# An activity archive and the FIT file in it; long rides stay far below this.
MAX_ACTIVITY_FILE_BYTES: Final = 50_000_000
_FIT_SIGNATURE: Final = b".FIT"
ACTIVITY_PAGE_SIZE: Final = 20
MAX_ACTIVITY_PAGES: Final = 500
# Per-request day limits of the Personal API ranges (inclusive days).
SLEEP_RANGE_DAYS: Final = 31
DAILY_SUMMARY_RANGE_DAYS: Final = 31
BODY_BATTERY_RANGE_DAYS: Final = 31

# SDK method names the Personal API serves. With a Personal key these families
# always use it; every other method stays on the SDK.
PERSONAL_METHODS: Final = frozenset(
    {
        "get_activities_by_date",
        "get_activity",
        "get_activity_details",
        "get_sleep_daily",
        "get_sleep_data",
        "get_hrv_data_range",
        "get_daily_summaries",
        "get_user_summary",
        "get_heart_rates",
        "get_body_battery",
        "get_weigh_ins",
        # Not an SDK method: the original FIT file is read only through Personal.
        "download_activity_fit",
    }
)

Opener = Callable[[Request, float], Any]


def _windows(start: str, end: str, days: int) -> Iterator[tuple[str, str]]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if last < first:
        raise ValueError("Garmin range ends before it starts")
    while first <= last:
        chunk_end = min(first + timedelta(days=days - 1), last)
        yield first.isoformat(), chunk_end.isoformat()
        first = chunk_end + timedelta(days=1)


def _day(value: str) -> str:
    return date.fromisoformat(value).isoformat()


def _token_expiry(token: str, now: float) -> float:
    """Return the JWT ``exp`` claim, or the documented lifetime when unreadable.

    The signature is not verified; the claim only schedules the next exchange.
    """
    parts = token.split(".")
    if len(parts) == 3:
        try:
            padded = parts[1] + "=" * (-len(parts[1]) % 4)
            claims = json.loads(base64.urlsafe_b64decode(padded))
            exp = float(claims["exp"])
            if exp > now:
                return exp
        except ValueError, KeyError, TypeError:
            pass
    return now + TOKEN_LIFETIME_SECONDS


def wrap_daily_sleep(value: Any) -> dict[str, Any] | None:
    """Return one flat Personal ``dailySleep`` record in the SDK element shape.

    The Personal API returns the ``dailySleepDTO`` fields at top level. Wrapping
    them as ``{"calendarDate": ..., "dailySleepDTO": ...}`` keys the night by its
    date, as the SDK sleep reads do, so the Garmin sleep id never decides the
    record identity and both transports write one element per night.
    """
    if not isinstance(value, dict) or not value:
        return None
    day = value.get("calendarDate")
    if not isinstance(day, str) or not day:
        return None
    return {"calendarDate": day[:10], "dailySleepDTO": value}


def _is_fit(data: bytes) -> bool:
    return len(data) >= 12 and data[8:12] == _FIT_SIGNATURE


def fit_from_archive(data: bytes) -> bytes:
    """Return the FIT file of a Garmin activity download.

    Garmin answers with a zip archive that holds the original upload; a bare FIT
    file is accepted as is. An archive without a FIT member, or one whose FIT
    member exceeds the size limit, raises ``ProviderInvalidResponse``.
    """
    if _is_fit(data):
        return data
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                if member.is_dir() or not member.filename.lower().endswith(".fit"):
                    continue
                if member.file_size > MAX_ACTIVITY_FILE_BYTES:
                    break
                with archive.open(member) as handle:
                    content = handle.read(MAX_ACTIVITY_FILE_BYTES + 1)
                if len(content) <= MAX_ACTIVITY_FILE_BYTES and _is_fit(content):
                    return content
                break
    except zipfile.BadZipFile, OSError, ValueError, EOFError:
        pass
    raise provider_http.ProviderInvalidResponse(
        "Garmin activity download holds no FIT file"
    )


class GarminPersonalClient:
    """Read Garmin data through the official Personal API under SDK method names."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = PERSONAL_BASE_URL,
        opener: Opener | None = None,
        clock: Callable[[], float] = time.time,
        user_agent: str = "IntervalsCoach",
    ) -> None:
        if not api_key.strip():
            raise ValueError("The Garmin Personal API key is empty.")
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._opener = opener or provider_http.urlopen
        self._clock = clock
        self._user_agent = user_agent
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "GarminPersonalClient()"

    # -- transport -------------------------------------------------------------

    def _open(self, request: Request, max_bytes: int = MAX_RESPONSE_BYTES) -> bytes:
        try:
            response = self._opener(request, REQUEST_TIMEOUT_SECONDS)
        except HTTPError as error:
            error.close()
            # The body may echo request data; only the status leaves this module.
            raise provider_http.classify_provider_status(
                int(error.code), GARMIN_ID
            ) from None
        try:
            return provider_http.read_bounded_response(response, max_bytes)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def _bearer(self, *, renew: bool = False) -> str:
        with self._lock:
            now = self._clock()
            if (
                renew
                or self._token is None
                or now >= self._token_expires_at - TOKEN_REFRESH_MARGIN_SECONDS
            ):
                request = Request(
                    self._base_url + TOKEN_PATH,
                    data=b"",
                    method="POST",
                    headers={
                        "Authorization": f"ApiKey {self._api_key}",
                        "Accept": "*/*",
                        "User-Agent": self._user_agent,
                    },
                )
                raw = self._open(request).decode("utf-8", "replace")
                token = raw.strip().strip('"')
                if not token or any(char.isspace() for char in token):
                    raise provider_http.ProviderInvalidResponse(
                        "Garmin Personal API returned no access token"
                    )
                self._token = token
                self._token_expires_at = _token_expiry(token, now)
            return self._token

    def _read(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        accept: str = "application/json",
        max_bytes: int = MAX_RESPONSE_BYTES,
    ) -> bytes:
        url = self._base_url + path
        if params:
            url += "?" + urlencode(params)
        for attempt in (0, 1):
            request = Request(
                url,
                method="GET",
                headers={
                    "Authorization": f"Bearer {self._bearer(renew=attempt == 1)}",
                    "Accept": accept,
                    "User-Agent": self._user_agent,
                },
            )
            try:
                return self._open(request, max_bytes)
            except provider_http.ProviderHTTPError as error:
                # One fresh exchange when a cached token was rejected early.
                if error.status == 401 and attempt == 0:
                    continue
                raise
        raise AssertionError("unreachable")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        raw = self._read(path, params)
        if not raw.strip():
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError, json.JSONDecodeError:
            raise provider_http.ProviderInvalidResponse(
                "Garmin Personal API response is not valid JSON"
            ) from None

    # -- activities ------------------------------------------------------------

    def get_activities_by_date(
        self,
        startdate: str,
        enddate: str | None = None,
        activitytype: str | None = None,
        sortorder: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"startDate": _day(startdate)}
        if enddate:
            params["endDate"] = _day(enddate)
        if activitytype:
            params["activityType"] = activitytype
        if sortorder:
            params["sortOrder"] = sortorder
        activities: list[dict[str, Any]] = []
        for page in range(MAX_ACTIVITY_PAGES):
            rows = self._get(
                "/activitylist-service/activities/search/activities",
                {
                    **params,
                    "start": page * ACTIVITY_PAGE_SIZE,
                    "limit": ACTIVITY_PAGE_SIZE,
                },
            )
            if not rows:
                return activities
            if not isinstance(rows, list):
                raise provider_http.ProviderInvalidResponse(
                    "Invalid Garmin activity page"
                )
            activities.extend(rows)
        raise provider_http.ProviderInvalidResponse("Garmin activity paging exceeded")

    def get_activity(self, activity_id: str) -> Any:
        return self._get(f"/activity-service/activity/{quote(str(int(activity_id)))}")

    def get_activity_details(
        self, activity_id: str, maxchart: int = 2000, maxpoly: int = 4000
    ) -> Any:
        return self._get(
            f"/activity-service/activity/{quote(str(int(activity_id)))}/details",
            {"maxChartSize": int(maxchart), "maxPolylineSize": int(maxpoly)},
        )

    def download_activity_fit(self, activity_id: str) -> bytes:
        """Return the original FIT file of one activity (see ``fit_from_archive``)."""
        raw = self._read(
            f"/download-service/files/activity/{quote(str(int(activity_id)))}",
            accept="*/*",
            max_bytes=MAX_ACTIVITY_FILE_BYTES,
        )
        return fit_from_archive(raw)

    # -- wellness --------------------------------------------------------------

    def get_sleep_daily(self, start: str, end: str) -> list[dict[str, Any]]:
        """Return one wrapped sleep element per night (see ``wrap_daily_sleep``)."""
        nights: dict[str, dict[str, Any]] = {}
        for first, last in _windows(start, end, SLEEP_RANGE_DAYS):
            rows = self._get(
                "/sleep-service/sleep/dailySleepSummariesByDate",
                {"startDate": first, "endDate": last},
            )
            if rows is None:
                continue
            if not isinstance(rows, list):
                raise provider_http.ProviderInvalidResponse(
                    "Invalid Garmin sleep range"
                )
            for row in rows:
                element = wrap_daily_sleep(row)
                if element is not None:
                    nights.setdefault(element["calendarDate"], element)
        return [nights[day] for day in sorted(nights)]

    def get_sleep_data(self, cdate: str) -> dict[str, Any]:
        """Return the night of ``cdate`` as ``{"dailySleepDTO": ...}`` like the SDK."""
        value = self._get("/sleep-service/sleep/dailySleep", {"date": _day(cdate)})
        if isinstance(value, dict) and value:
            return {"dailySleepDTO": value}
        return {}

    def get_hrv_data_range(self, start: str, end: str) -> Any:
        return self._get(f"/hrv-service/hrv/daily/{_day(start)}/{_day(end)}")

    def get_daily_summaries(self, start: str, end: str) -> dict[str, Any]:
        rows: list[Any] = []
        for first, last in _windows(start, end, DAILY_SUMMARY_RANGE_DAYS):
            value = self._get(
                "/usersummary-service/v2/dailysummaries",
                {"startDate": first, "endDate": last},
            )
            data = value.get("data") if isinstance(value, dict) else value
            if data is None:
                continue
            if not isinstance(data, list):
                raise provider_http.ProviderInvalidResponse(
                    "Invalid Garmin daily summaries"
                )
            rows.extend(data)
        return {"data": rows}

    def get_user_summary(self, cdate: str) -> Any:
        return self._get(
            "/usersummary-service/usersummary/daily", {"calendarDate": _day(cdate)}
        )

    def get_heart_rates(self, cdate: str) -> Any:
        return self._get(
            "/wellness-service/wellness/dailyHeartRate", {"date": _day(cdate)}
        )

    def get_body_battery(self, startdate: str, enddate: str | None = None) -> list[Any]:
        rows: list[Any] = []
        for first, last in _windows(
            startdate, enddate or startdate, BODY_BATTERY_RANGE_DAYS
        ):
            value = self._get(
                "/wellness-service/wellness/bodyBattery/reports/daily",
                {"startDate": first, "endDate": last},
            )
            if value is None:
                continue
            if not isinstance(value, list):
                raise provider_http.ProviderInvalidResponse(
                    "Invalid Garmin body battery range"
                )
            rows.extend(value)
        return rows

    def get_weigh_ins(self, startdate: str, enddate: str) -> Any:
        return self._get(
            f"/weight-service/weight/range/{_day(startdate)}/{_day(enddate)}",
            {"includeAll": "true"},
        )


class GarminTransportClient:
    """Route each SDK method to the Personal API or the unofficial SDK.

    Families in ``PERSONAL_METHODS`` use the Personal client when a key is
    configured. Every other method goes to the SDK client when one is connected;
    otherwise it is absent, so collectors treat it as an unsupported capability.
    """

    def __init__(self, personal: GarminPersonalClient | None, sdk: Any | None) -> None:
        if personal is None and sdk is None:
            raise ValueError("A Garmin transport needs the Personal API or the SDK.")
        self.personal = personal
        self.sdk = sdk

    def __repr__(self) -> str:
        return (
            f"GarminTransportClient(personal={self.personal is not None}, "
            f"sdk={self.sdk is not None})"
        )

    def login(self, tokenstore: str | None = None) -> tuple[Any, Any]:
        """Log the SDK in when present; the Personal API needs no login."""
        if self.sdk is None:
            return None, None
        return self.sdk.login(tokenstore)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if self.personal is not None and name in PERSONAL_METHODS:
            return getattr(self.personal, name)
        if self.sdk is not None:
            return getattr(self.sdk, name)
        raise AttributeError(name)
