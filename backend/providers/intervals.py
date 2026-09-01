"""Dependency-light pagination for the Intervals.icu provider."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
from typing import Any


JsonGetter = Callable[[str, dict[str, Any]], Any]
ErrorFactory = Callable[[str], Exception]


def fetch_paged_collection(
    get: JsonGetter,
    path: str,
    params: Mapping[str, Any] | None,
    collection: str,
    error: ErrorFactory,
    page_size: int = 500,
    max_pages: int = 100,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read a bounded provider collection through an injected GET operation.

    The helper owns only provider pagination and validation. HTTP transport,
    authentication, application errors, and operation metadata remain at the
    application boundary so this module has no dependency on ``server.py``.
    """
    rows: list[dict[str, Any]] = []
    offset = 0
    pages = 0
    fingerprints: set[str] = set()
    while True:
        page = get(path, {**(dict(params) if params else {}), "limit": page_size, "offset": offset})
        if not isinstance(page, list):
            raise error(f"Intervals.icu hat keine gültige {collection}-Seite zurückgegeben.")
        page_rows = [item for item in page if isinstance(item, dict)]
        if len(page_rows) != len(page):
            raise error(f"Intervals.icu liefert ungültige Datensätze in der {collection}-Seite.")
        pages += 1
        fingerprint = hashlib.sha256(
            json.dumps(page_rows, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()
        if fingerprint in fingerprints and page_rows:
            raise error(f"Intervals.icu liefert wiederholt dieselbe {collection}-Seite.")
        fingerprints.add(fingerprint)
        rows.extend(page_rows)
        if len(page) < page_size:
            break
        offset += len(page)
        if pages >= max_pages:
            raise error(f"Die {collection}-Synchronisierung überschreitet das Seitenlimit.")
    return rows, {"pages": pages, "records": len(rows), "complete": True}
