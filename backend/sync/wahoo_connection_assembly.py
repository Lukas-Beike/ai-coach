"""Lazy composition of the Wahoo connection service."""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.providers.wahoo_oauth import WahooOAuthClient
from backend.sync.wahoo_connection import WahooConnectionService


@dataclass(frozen=True)
class WahooConnectionInputs:
    config: Callable[[], Config]
    json_request: Callable[[], Callable[..., Any]]
    database_manager: Callable[[], DatabaseManager]
    database_lock: Callable[[], AbstractContextManager[Any]]
    key_values: KeyValueRepository
    utc_now: Callable[[], str]


class WahooConnectionAssembly:
    """Share one connection service so token refreshes stay serialized."""

    def __init__(self, inputs: WahooConnectionInputs) -> None:
        self._inputs = inputs
        self._service: WahooConnectionService | None = None
        self._lock = threading.Lock()

    def service(self) -> WahooConnectionService:
        with self._lock:
            if self._service is None:
                inputs = self._inputs
                self._service = WahooConnectionService(
                    config=inputs.config,
                    oauth=lambda: WahooOAuthClient(
                        inputs.config, inputs.json_request()
                    ),
                    database_manager=inputs.database_manager,
                    database_lock=inputs.database_lock,
                    key_values=inputs.key_values,
                    utc_now=inputs.utc_now,
                )
            return self._service
