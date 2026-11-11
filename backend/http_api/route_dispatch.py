"""Transport-level routing across concrete HTTP API PUT route owners."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from backend.errors import NOT_FOUND_ERROR, AppError


class PutRoute(Protocol):
    def handle(self, handler: Any, path: str) -> bool: ...


class HttpRouteDispatcher:
    """Keep PUT route ordering and unmatched-path behavior outside the handler."""

    def __init__(self, put_routes: Sequence[PutRoute]) -> None:
        self._put_routes = tuple(put_routes)

    def handle_put(self, handler: Any, path: str) -> None:
        if not any(route.handle(handler, path) for route in self._put_routes):
            raise AppError(404, NOT_FOUND_ERROR)
