"""Pure response formatting shared by the HTTP handler.

The request handler, socket writes, authentication state, and application
configuration remain at the server boundary.  These helpers only format
already-authorized response values and headers.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import json
from typing import Any


HeaderValue = str | list[str] | tuple[str, ...]


def json_bytes(payload: Any) -> bytes:
    """Serialize an API payload with the existing UTF-8 JSON policy."""
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def header_items(headers: Mapping[str, HeaderValue] | None) -> Iterator[tuple[str, str]]:
    """Expand scalar and repeated headers without changing their order."""
    for key, value in (headers or {}).items():
        if isinstance(value, (list, tuple)):
            for item in value:
                yield key, str(item)
        else:
            yield key, value


def response_headers(content_type: str, content_length: int, *, cache_control: str = "no-store") -> tuple[tuple[str, str], ...]:
    """Return the common anti-caching and browser-hardening headers."""
    return (
        ("Content-Type", content_type),
        ("Content-Length", str(content_length)),
        ("Cache-Control", cache_control),
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
    )


def session_cookies(
    session_cookie: str,
    csrf_cookie: str,
    token: str = "",
    csrf: str = "",
    *,
    ttl_seconds: int,
    secure: bool = False,
    clear: bool = False,
) -> list[str]:
    """Create hardened session cookies from explicit policy inputs."""
    secure_flag = "; Secure" if secure else ""
    if clear:
        max_age = "; Max-Age=0"
        token = csrf = ""
    else:
        max_age = f"; Max-Age={ttl_seconds}"
    return [
        f"{session_cookie}={token}; Path=/; HttpOnly; SameSite=Strict{secure_flag}{max_age}",
        f"{csrf_cookie}={csrf}; Path=/; SameSite=Strict{secure_flag}{max_age}",
    ]
