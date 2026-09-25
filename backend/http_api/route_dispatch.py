"""Transport-level routing across concrete HTTP API route owners."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from backend.errors import AppError, NOT_FOUND_ERROR



class GetRoute(Protocol):
    def handle(self, handler: Any, path: str) -> bool: ...


class PutRoute(Protocol):
    def handle(self, handler: Any, path: str) -> bool: ...


class HttpRouteDispatcher:
    """Keep route ordering and unmatched-path behavior outside the handler."""

    def __init__(
        self,
        get_routes: Sequence[GetRoute],
        put_routes: Sequence[PutRoute],
    ) -> None:
        self._get_routes = tuple(get_routes)
        self._put_routes = tuple(put_routes)

    def handle_get(self, handler: Any, path: str) -> None:
        if any(route.handle(handler, path) for route in self._get_routes):
            return
        if path.startswith("/api/"):
            raise AppError(404, NOT_FOUND_ERROR)
        handler.send_static(path)

    def handle_put(self, handler: Any, path: str) -> None:
        if not any(route.handle(handler, path) for route in self._put_routes):
            raise AppError(404, NOT_FOUND_ERROR)
