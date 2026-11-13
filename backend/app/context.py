"""The one application context the domain builders read (#2069).

``server.py`` builds it once at startup. A domain builder
(``backend/<domain>/wiring.py``) constructs that domain's services from it,
with no ``Inputs`` bundle, no assembly class and no copied attributes.

``config`` and ``database`` are callables to the live value: saving provider
credentials replaces the configuration and a restore replaces the database
manager, so services ask on every use and never cache either.

The owner fields below the runtime owners are domain owners that server.py
sets as it creates them. A builder reads them when a service is used, which
keeps today's late edges. They stay untyped while server.py still assigns them
late (a typed field would add a package cycle); #2103 types them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.athlete.clock import AthleteLocalClock
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.observability import Redactor
from backend.providers.observed_opener import Opener
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
    database_lock: Any
    # Observed opener for a raw provider request (log and diagnostic capture).
    observed_opener: Callable[[str], Opener]
    # The live data directory, database path and cipher availability: tests
    # and a restore swap them, so they are read on every use.
    data_dir: Callable[[], Path]
    database_path: Callable[[], Path]
    sqlcipher_available: Callable[[], bool]
    sqlite_backend: Any
    profile_mutation_coordinator: Any
    # Recompute the configuration from the environment and stored credentials.
    refresh_config: Callable[[], Any]
    # The live log file path (tests and a restore swap it) and the release identity.
    log_path: Callable[[], Path]
    app_name: str
    app_version: str
    # The provider observability state bound to the active database.
    provider_state: Callable[[], Any]
    athlete: Any = None
    athlete_profile: Any = None
    canonical_read: Any = None
    planning: Any = None
    planning_workflows: Any = None
    planning_revision: Any = None
    performance: Any = None
    nutrition: Any = None
    provider_transport: Any = None
    provider_sync: Any = None
    settings: Any = None
    model_transport: Any = None
    diagnostic_capture: Any = None
    sync_job_queue: Any = None
    coach_background_jobs: Any = None
    coach_conversation: Any = None
    canonical_backfill: Any = None
    garmin: Any = None
    external_calendar: Any = None
    coach_local: Any = None
    workout_library_sync: Any = None
    # The structured Coach dialogue tool definitions; diagnostics lists their names.
    coach_dialogue_tools: Any = None
    weather: Any = None
    run_lthr: Any = None
    # Returns the cached morning body battery service of the active database.
    morning_body_battery_service: Any = None
