"""The one application context the domain builders read (#2069).

``server.py`` builds it once at startup. A domain builder
(``backend/<domain>/wiring.py``) constructs that domain's services from it,
with no ``Inputs`` bundle, no assembly class and no copied attributes.

``config`` and ``database`` are callables to the live value: saving provider
credentials replaces the configuration and a restore replaces the database
manager, so services ask on every use and never cache either.

The owner fields below the runtime owners are the domains whose builder step
has not run yet (#2099-#2103). A builder reads them when a service is used,
which keeps today's late edges; each becomes typed when its domain moves to a
builder.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.athlete.clock import AthleteLocalClock
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.observability import Redactor
from backend.runtime.maintenance import MaintenanceGate


@dataclass
class AppContext:
    config: Callable[[], Config]
    database: Callable[[], DatabaseManager]
    key_values: KeyValueRepository
    clock: AthleteLocalClock
    ids: Callable[[], str]
    logger: logging.Logger
    maintenance: MaintenanceGate
    redactor: Redactor
    # The current sync operation id, read by the provider refresh journals.
    operation_context: Any
    athlete: Any = None
    planning: Any = None
    planning_workflows: Any = None
    planning_revision: Any = None
    nutrition: Any = None
    provider_transport: Any = None
    provider_sync: Any = None
