"""Dependency-light pagination for the Intervals.icu provider."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
from typing import Any
from urllib.parse import urlencode


JsonGetter = Callable[[str, dict[str, Any]], Any]
ErrorFactory = Callable[[str], Exception]
Request = Callable[..., Any]


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

