"""Dependency-light pagination for the Intervals.icu provider."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode

from backend.errors import AppError

JsonGetter = Callable[[str, dict[str, Any]], Any]
ErrorFactory = Callable[[str], Exception]
Request = Callable[..., Any]
INTERVALS_API_BASE_URL = "https://intervals.icu/api/v1"


class IntervalsApiClient:
    """Own authenticated Intervals.icu transport and collection pagination state."""

    def __init__(
        self,
        *,
        api_key: str,
        request: Callable[..., Any],
        base_url: str = INTERVALS_API_BASE_URL,
    ):
        credentials = base64.b64encode(f"API_KEY:{api_key}".encode()).decode()
        headers = {"Authorization": f"Basic {credentials}"}
        base = base_url.rstrip("/")
        self._read_transport = IntervalsReadTransport(base, headers, request)
        self._write_transport = IntervalsWriteTransport(base, headers, request)
        self._pagination: dict[str, dict[str, Any]] = {}

    @property
    def pagination(self) -> Mapping[str, Mapping[str, Any]]:
        """Return a JSON-serializable defensive snapshot of pagination metadata."""
        return {
            collection: metadata.copy()
            for collection, metadata in self._pagination.items()
        }

    def get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        cancel_event: Any = None,
    ) -> Any:
        if cancel_event is None:
            return self._read_transport.get(path, params)
        return self._read_transport.get(path, params, cancel_event=cancel_event)

    def get_paged_collection(
        self,
        path: str,
        params: Mapping[str, Any] | None,
        collection: str,
        page_size: int = 500,
        cancel_event: Any = None,
    ) -> list[dict[str, Any]]:
        rows, page_metadata = fetch_paged_collection(
            self.get,
            path,
            params,
            collection,
            error=lambda message: AppError(502, message),
            page_size=page_size,
            cancel_event=cancel_event,
        )
        previous = self._pagination.get(collection) or {
            "pages": 0,
            "records": 0,
            "complete": True,
        }
        self._pagination[collection] = {
            "pages": int(previous["pages"]) + int(page_metadata["pages"]),
            "records": int(previous["records"]) + int(page_metadata["records"]),
            "complete": bool(previous["complete"]) and bool(page_metadata["complete"]),
        }
        return rows

    def post(self, path: str, payload: Any, params: Mapping[str, Any] | None = None) -> Any:
        return self._write_transport.post(path, payload, params)

    def put(self, path: str, payload: Any, params: Mapping[str, Any] | None = None) -> Any:
        return self._write_transport.put(path, payload, params)

    def delete(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return self._write_transport.delete(path, params)


class IntervalsReadTransport:
    """Build authenticated read requests without owning application state."""

    def __init__(self, base: str, headers: Mapping[str, str], request: Request):
        self._base = base
        self._headers = headers
        self._request = request

    def get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        cancel_event: Any = None,
    ) -> Any:
        query = "?" + urlencode(params, doseq=True) if params else ""
        request_kwargs = {
            "headers": self._headers,
            "service": "intervals",
        }
        if cancel_event is not None:
            request_kwargs["cancel_event"] = cancel_event
        return self._request(
            "GET",
            self._base + path + query,
            **request_kwargs,
        )


class IntervalsWriteTransport:
    """Build explicit authenticated write requests without application state."""

    def __init__(self, base: str, headers: Mapping[str, str], request: Request):
        self._base = base
        self._headers = headers
        self._request = request

    def post(self, path: str, payload: Any, params: Mapping[str, Any] | None = None) -> Any:
        query = "?" + urlencode(params, doseq=True) if params else ""
        return self._request(
            "POST",
            self._base + path + query,
            payload,
            self._headers,
            service="intervals",
        )

    def put(self, path: str, payload: Any, params: Mapping[str, Any] | None = None) -> Any:
        query = "?" + urlencode(params, doseq=True) if params else ""
        return self._request(
            "PUT",
            self._base + path + query,
            payload,
            self._headers,
            service="intervals",
        )

    def delete(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        query = "?" + urlencode(params, doseq=True) if params else ""
        return self._request(
            "DELETE",
            self._base + path + query,
            headers=self._headers,
            service="intervals",
        )


def _fetch_page(get: JsonGetter, path: str, params: Mapping[str, Any] | None, collection: str,
                error: ErrorFactory, offset: int, page_size: int, cancel_event: Any) -> list[dict[str, Any]]:
    page_params = {**(dict(params) if params else {}), "limit": page_size, "offset": offset}
    page = get(path, page_params) if cancel_event is None else get(path, page_params, cancel_event=cancel_event)
    if not isinstance(page, list):
        raise error(f"Invalid {collection} page")
    page_rows = [item for item in page if isinstance(item, dict)]
    if len(page_rows) != len(page):
        raise error(f"Invalid {collection} records")
    return page_rows


def _page_fingerprint(page_rows: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(page_rows, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _remember_page(fingerprints: set[str], fingerprint: str, page_rows: list[dict[str, Any]],
                   collection: str, error: ErrorFactory) -> None:
    if fingerprint in fingerprints and page_rows:
        raise error(f"Repeated {collection} page")
    fingerprints.add(fingerprint)


def fetch_paged_collection(
    get: JsonGetter,
    path: str,
    params: Mapping[str, Any] | None,
    collection: str,
    error: ErrorFactory,
    page_size: int = 500,
    max_pages: int = 100,
    cancel_event: Any = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read and validate a bounded provider collection through pagination."""
    rows: list[dict[str, Any]] = []
    offset = 0
    pages = 0
    fingerprints: set[str] = set()
    while True:
        page_rows = _fetch_page(get, path, params, collection, error, offset, page_size, cancel_event)
        pages += 1
        fingerprint = _page_fingerprint(page_rows)
        _remember_page(fingerprints, fingerprint, page_rows, collection, error)
        rows.extend(page_rows)
        if len(page_rows) < page_size:
            break
        offset += len(page_rows)
        if pages >= max_pages:
            raise error(f"Page limit exceeded for {collection}.")
    return rows, {"pages": pages, "records": len(rows), "complete": True}

