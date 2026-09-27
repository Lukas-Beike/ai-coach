# S6 composition interface review

This map records the post-redesign composition boundary. The generated
`server-extraction-inventory.md` remains a symbol ownership inventory; this
document records the assembly graph, shared process identities, and late edges.

| Owner | Assembly interfaces | Direct assembly consumers | Test and fixture lookup sites |
| --- | --- | --- | --- |
| Athlete and planning | `AthleteDataAssembly`, `PlanningDataAssembly`, `PlanningWorkflowAssembly` | Sync calendar/library paths, Coach context/tools, public state, diagnostics, backup/privacy | `tests/test_athlete_planning_assemblies.py`, `tests/test_server_athlete.py`, `tests/test_server_planning.py`, `tests/test_server_weather_calendar.py` |
| History and durable state | `HistoryAssembly`, `PrivacyAssembly`, `BackupAssembly` | Coach proposal execution, HTTP history/privacy routes, restore lifecycle | `tests/test_history_assembly.py`, `tests/test_privacy_backup_assemblies.py`, `tests/test_server_database.py`, `tests/test_audit_remediation.py` |
| Providers and synchronization | `ProviderTransportAssembly`, `ProviderSyncAssembly`, `SyncJobQueueAssembly`, `GarminAssembly`, `ExternalCalendarAssembly`, `IntervalsSyncAssembly`, planned-unit/calendar and library sync assemblies, `SelectedWorkoutSyncAssembly`, `ProviderResyncAssembly`, `SyncJobExecutionAssembly`, `SyncJobWorkerAssembly`, `SyncSchedulerAssembly`, `SyncCommandAssembly`, `WeatherAssembly` | Coach sync tools and jobs, public state, diagnostics, HTTP sync routes, `main()` worker lifecycle | `tests/test_server_providers.py`, `tests/test_intervals_sync_assembly.py`, `tests/test_provider_resync_assembly.py`, `tests/test_selected_assembly.py`, `tests/test_server_sync.py`, `tests/test_server_runtime.py`, `tests/test_weather_service.py`, `e2e/fixture_runtime.py` does not patch these factories |
| Coach and model | `ModelTransportAssembly`, `CoachConversationAssembly`, `CoachLocalAssembly`, `CoachContextAssembly`, read/planning/command/tool-dispatch assemblies, structured-round/turn assemblies, `CoachProposalAssembly`, `CoachBackgroundJobsAssembly` | HTTP chat routes, public state projections, diagnostics, sync/planning follow-ups, startup worker lifecycle | `tests/test_coach_*_assembly.py`, `tests/test_server_coach.py`, `tests/test_coach_dialogue.py`, `tests/test_coach_review.py`, `tests/test_server_providers.py` |
| HTTP and projections | `PublicStateAssembly`, `DiagnosticsAssembly`, `NutritionAssembly`, `HttpApiAssembly` | `main()` creates the request handler from `HTTP_API`; its ordered dispatchers call the domain route owners | `tests/test_public_state_assembly.py`, `tests/test_diagnostics_assembly.py`, `tests/test_nutrition_assembly.py`, `tests/test_server_http.py`, `tests/server_test_support.py`, `e2e/fixture_runtime.py` |

## Shared identity and lookup timing

- `database_manager()` remains the one current-manager adapter. The shared
  database lock, repositories, key-value repository, state-event buffer,
  maintenance gate, interval sync lock, provider resync gates, and Coach
  conversation gate are passed through unchanged to their consumers.
- Sync queue, sync wake event, Coach worker, Coach job store, chat stream
  registry, and provider/weather/auth caches remain owned by their existing
  backend modules. Restore and worker assemblies receive those same owners.
- Manager/config access, provider HTTP and Intervals clients, planned-calendar
  and workout-library provider lookups, adaptive previews, selected Coach
  response/tool services, and the proposal clock remain late-bound at the
  service call site. Assembly import and construction do not open the database,
  contact a provider, or start a worker.
- `tests/test_server_http.py` patches the nested handler identity at the
  `HttpHandlerConfiguration` lookup site. Provider and sync tests patch or
  inspect the actual provider/sync owner modules. `tests/server_test_support.py`
  keeps only explicit temporary-storage setup; `e2e/fixture_runtime.py` builds
  its handler from `HTTP_API` and no longer patches removed root factories.

## Root-size decision

`server.py` has 39 assembly construction sites across these five ownership
groups. Their order is required by real cross-domain edges: provider transport
feeds sync and model owners; planning and sync services feed Coach tools and
jobs; public projections and diagnostics consume those owners; HTTP is wired
last. Several edges are intentionally lazy to preserve this order without
moving domain orchestration back into the root. Combining these sites into one
generic application object would hide those owners and recreate the broad
dependency bag rejected by the redesign. The root therefore retains the
concrete, named connections and the explicit process lifecycle.

Measured after the redesign: 1,830 physical / 1,693 nonblank lines, 108 import
statements, eight top-level definitions. This remains above the practical
300–500-line guide. The excess is the visible concrete assembly graph and
imports, not domain implementation or compressed formatting. S6 closes only
with the boundary, lazy-lookup, shared-identity, behavior, and quality checks
passing; the inventory count alone is not a completion signal.
