## MODIFIED Requirements

### Requirement: Nutrition export is an explicit queued operation
The system SHALL start a nutrition export only from a sync the athlete names in the Coach, queued without a card and bound to the manifest frozen when the request ran, and SHALL NOT expose a direct HTTP route that queues it. Ordinary diary reads, edits, product lookup, and view refresh SHALL not implicitly export nutrition.

#### Scenario: No direct export route
- **WHEN** a client posts to `/api/nutrition/sync`
- **THEN** the nutrition routes do not handle it and no nutrition-export job is enqueued.

#### Scenario: Export on the job route
- **WHEN** a client posts a `nutrition_sync` job for Intervals.icu to `/api/sync/jobs`, with a `date`, a `pending_limit`, a client-built `approval_manifest` or nothing
- **THEN** the route answers 400 and no nutrition-export job is enqueued; only the Coach's named sync enqueues the export, directly through the queue.

#### Scenario: Export pending dates
- **WHEN** the named Coach sync covers pending dates
- **THEN** service execution accepts only a limit from one through thirty-one.

#### Scenario: Refresh the diary
- **WHEN** the athlete refreshes a nutrition view
- **THEN** the narrow read-refresh path is used and no nutrition-export job is enqueued.

Evidence: `backend/http_api/nutrition.py::NutritionPostRoutes.routes`, `backend/http_api/sync_commands.py::SyncCommandEndpoint._enqueue_job`, `backend/nutrition/sync.py::IntervalsNutritionSyncService.sync_pending`; `tests/test_nutrition_api_and_sync.py::NutritionHttpApiTests.test_the_removed_sync_route_is_not_handled`, `tests/test_http_sync_commands.py::SyncCommandEndpointTests.test_confirmation_bound_requests_start_nothing_without_it`, `tests/test_nutrition_api_and_sync.py::NutritionHttpApiTests.test_nutrition_refresh_diary_reads_local_meals_and_only_daily_energy`.
