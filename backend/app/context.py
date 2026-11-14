"""The one application context the domain builders read (#2069).

``server.py`` builds it once at startup. A domain builder
(``backend/<domain>/wiring.py``) constructs that domain's services from it,
with no ``Inputs`` bundle, no assembly class and no copied attributes.

``config`` and ``database`` are the live holders (``ConfigHolder``,
``DatabaseHolder``): saving provider credentials replaces the configuration and
a restore replaces the database manager, so services call them on every use and
never cache either.

The owner fields below the runtime owners are domain owners that server.py
sets as it creates them. Most builders read them when a service is used, which
keeps today's late edges; ``build_http_api`` reads its owners while it builds
the routes, so they are set before it runs. A field is typed when its owner sits in a package that
does not import ``backend.app`` (an import here would close a package cycle,
and the architecture guard counts type-only imports); the others stay ``Any``:
their owners are the sync, coach, planning, performance, nutrition and weather
builders, which all read this context. A typed late field is set before its
first use and has no default.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from backend.athlete.clock import AthleteLocalClock
from backend.athlete.profile import ProfileService
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.observability import DiagnosticCapture, Redactor
from backend.providers.model_wiring import ModelTransportServices
from backend.providers.observed_opener import Opener
from backend.providers.state import ProviderStateService
from backend.providers.transport_wiring import ProviderTransportServices
from backend.runtime.maintenance import MaintenanceGate
from backend.settings import SettingsService


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
    operation_context: ContextVar[dict[str, str] | None]
    database_lock: threading.RLock
    # Observed opener for a raw provider request (log and diagnostic capture).
    observed_opener: Callable[[str], Opener]
    # The live data directory, database path and cipher availability: tests
    # and a restore swap them, so they are read on every use.
    data_dir: Callable[[], Path]
    database_path: Callable[[], Path]
    sqlcipher_available: Callable[[], bool]
    sqlite_backend: ModuleType
    profile_mutation_coordinator: threading.RLock
    # Recompute the configuration from the environment and stored credentials.
    refresh_config: Callable[[], Config]
    # The live log file path (tests and a restore swap it) and the release identity.
    log_path: Callable[[], Path]
    app_name: str
    app_version: str
    # The provider observability state bound to the active database.
    provider_state: Callable[[], ProviderStateService]
    athlete: Any
    athlete_profile: ProfileService
    planning_revision: Any
    # Returns the cached morning body battery service of the active database.
    morning_body_battery_service: Any
    provider_transport: ProviderTransportServices = field(init=False, repr=False)
    settings: SettingsService = field(init=False, repr=False)
    model_transport: ModelTransportServices = field(init=False, repr=False)
    diagnostic_capture: DiagnosticCapture = field(init=False, repr=False)
    canonical_read: Any = None
    planning: Any = None
    planning_workflows: Any = None
    performance: Any = None
    nutrition: Any = None
    provider_sync: Any = None
    sync_job_queue: Any = None
    coach_background_jobs: Any = None
    coach_conversation: Any = None
    canonical_backfill: Any = None
    garmin: Any = None
    wahoo: Any = None
    sync_persistence: Any = None
    external_calendar: Any = None
    coach_local: Any = None
    coach_context: Any = None
    coach_read_tools: Any = None
    coach_proposals: Any = None
    coach_planning_tools: Any = None
    coach_command_tools: Any = None
    coach_tool_dispatch: Any = None
    coach_tool_rounds: Any = None
    coach_turns: Any = None
    workout_library_sync: Any = None
    # The structured Coach dialogue tool definitions; diagnostics lists their names.
    coach_dialogue_tools: Any = None
    weather: Any = None
    run_lthr: Any = None
    # The owners the HTTP routes read (build_http_api).
    public_state: Any = None
    activity_reads: Any = None
    activity_routes: Any = None
    history: Any = None
    backup: Any = None
    privacy: Any = None
    diagnostics: Any = None
    provider_resync: Any = None
    provider_credential_service: Any = None
    provider_connection_checks: Any = None
    wahoo_connection: Any = None
    metric_export: Any = None
    garmin_login: Any = None
