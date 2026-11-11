"""One HTTP route table: method, path pattern, access level and handler.

The request handler checks the declared access level of every route before its
handler runs; a route cannot be registered without one, and a public API route
must be listed in ``PUBLIC_API_ROUTES``. Anything not in the table is rejected:
an unknown GET path outside ``/api/`` is served as a static asset, an unknown
API GET answers 404, and an unknown POST or PUT path answers 404 only after the
session and CSRF checks a registered route would get.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Access(StrEnum):
    PUBLIC = "public"
    SESSION = "session"
    SESSION_CSRF = "session+csrf"


# The reviewed list of API routes that answer without a session: health,
# readiness, login state, login and the Wahoo OAuth redirect, whose single-use
# server-stored state is its credential. Static assets, the manifest and the
# service worker are the non-API GET fallback.
PUBLIC_API_ROUTES = frozenset(
    {
        ("GET", "/api/health"),
        ("GET", "/api/readiness"),
        ("GET", "/api/auth/status"),
        ("GET", "/api/wahoo/callback"),
        ("POST", "/api/login"),
    }
)

_METHOD_ACCESS = {
    "GET": {Access.PUBLIC, Access.SESSION},
    "POST": {Access.PUBLIC, Access.SESSION_CSRF},
    "PUT": {Access.SESSION_CSRF},
}
# "{name}" matches one path segment; "{name:regex}" matches the regex.
_PARAMETER = re.compile(r"\{(\w+)(?::([^}]+))?\}")


@dataclass(frozen=True, slots=True)
class RouteRequest:
    """A matched request: path parameters, query and the checked session.

    ``session`` is empty for a public route.
    """

    path: str
    params: dict[str, str]
    query: dict[str, list[str]]
    session: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Route:
    method: str
    path: str
    access: Access
    handle: Callable[[Any, RouteRequest], None]
    # POST only: run inside the maintenance operation gate after re-checking the
    # session. Login, logout, restore and chat cancellation run outside it.
    gated: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.access, Access):
            raise TypeError(f"{self.method} {self.path} has no access level")
        if self.access not in _METHOD_ACCESS.get(self.method, ()):
            raise ValueError(f"{self.method} {self.path} cannot be {self.access}")
        if (self.access is Access.PUBLIC) != (
            (self.method, self.path) in PUBLIC_API_ROUTES
        ):
            raise ValueError(f"{self.method} {self.path} public status is not reviewed")


def _compile(path: str) -> re.Pattern[str]:
    pattern, position = "", 0
    for match in _PARAMETER.finditer(path):
        pattern += re.escape(path[position : match.start()])
        pattern += f"(?P<{match[1]}>{match[2] or '[^/]+'})"
        position = match.end()
    return re.compile(pattern + re.escape(path[position:]))


class RouteTable:
    """Find the one route registered for a method and request path."""

    def __init__(self, routes: Iterable[Route]) -> None:
        self.routes = tuple(routes)
        self._exact: dict[tuple[str, str], Route] = {}
        self._patterns: list[tuple[Route, re.Pattern[str]]] = []
        for route in self.routes:
            key = (route.method, route.path)
            if key in self._exact or any(
                (other.method, other.path) == key for other, _ in self._patterns
            ):
                raise ValueError(f"{route.method} {route.path} is registered twice")
            if _PARAMETER.search(route.path):
                self._patterns.append((route, _compile(route.path)))
            else:
                self._exact[key] = route

    def match(self, method: str, path: str) -> tuple[Route, dict[str, str]] | None:
        route = self._exact.get((method, path))
        if route is not None:
            return route, {}
        for route, pattern in self._patterns:
            if route.method == method and (found := pattern.fullmatch(path)):
                return route, found.groupdict()
        return None
