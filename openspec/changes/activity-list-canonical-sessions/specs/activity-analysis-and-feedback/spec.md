## ADDED Requirements

### Requirement: One activity list entry per canonical session
The activity list (`GET /api/activities`) and the Coach tool `list_recent_activities` SHALL list each live canonical session exactly once, from every provider, as its session summary keyed by the local session id, newest first. Paging SHALL use a version-3 keyset cursor; any other cursor SHALL restart at page one. `detail_error` SHALL name only an Intervals.icu failure note of the current summary fingerprint.

#### Scenario: Sessions from several providers
- **WHEN** the tables hold Intervals.icu-only sessions, a Garmin-only session, a bundled Intervals.icu and Garmin session, and an Intervals.icu duplicate pair bundled into one session
- **THEN** the list and the Coach tool contain each session once under its `act_` id, the Garmin-only session included, and paging with limit 1 walks all of them in the same order.

#### Scenario: Older cursor
- **WHEN** a client sends a version-2 cursor
- **THEN** the first page is returned.

#### Scenario: Failure note of another summary version
- **WHEN** a listed session's Intervals.icu record has a failure note whose fingerprint differs from the current one
- **THEN** its `detail_error` is null.

Evidence: `backend/activities/read_service.py:ActivityReadService.page`, `backend/activities/read_service.py:ActivityReadService.recent`; `tests/test_activity_canonical_reads.py:test_read_service_lists_nothing_until_the_tables_serve`, `tests/test_activity_canonical_reads.py:test_limit_one_pages_walk_every_session_and_old_cursors_restart`, `tests/test_activity_canonical_reads.py:test_garmin_only_session_is_listed_and_its_detail_loads`, `tests/test_activity_read_service.py:test_page_hides_a_failure_note_of_an_older_summary_version`; `e2e/activity-details.spec.js::@responsive analysis lists a Garmin-only indoor session and loads more`.

### Requirement: Summary fingerprints from one sync-owned port
Freshness checks outside the sync owner SHALL read current summary fingerprints only through the `summary_fingerprints` port, for the requested activities only. Intervals.icu fingerprints SHALL keep the value of `summary_fingerprint` of the stored payload; other providers SHALL use the payload hash of the active raw record.

#### Scenario: Stored fingerprints stay valid
- **WHEN** the port reads fingerprints for every stored Intervals.icu activity of a populated fixture and for a Garmin record
- **THEN** each Intervals.icu value equals `summary_fingerprint` of its stored row and the Garmin value equals its record's payload hash, so no stored detail, analysis or profile becomes stale.

Evidence: `backend/sync/canonical_table_reader.py:CanonicalTableReader.summary_fingerprints`; `tests/test_activity_canonical_reads.py:test_fingerprints_keep_the_stored_values`, `tests/test_canonical_detail_reader.py:CanonicalDetailStatusTests`.

## MODIFIED Requirements

### Requirement: Completed-activity summaries use provider-neutral keys over HTTP
Every completed-activity object that the HTTP API returns SHALL carry provider-neutral keys, and SHALL NOT carry the former Intervals.icu activity keys. Values SHALL be unchanged. Local planning records already carry the provider-neutral `starts_at_local` and `planned_duration_s` and receive only the metric renames.

#### Scenario: Activity list row
- **WHEN** `/api/activities` returns a session
- **THEN** it is the session summary with `id`, `started_at`, `started_at_local`, `sport`, `environment`, `record_ids` and the neutral metric names such as `moving_duration_s`, `distance_m` and `training_load`, and none of `start_date_local`, `moving_time`, `type`, `local_activity_id` or `icu_*` is present.

#### Scenario: Calendar actual activity
- **WHEN** `/api/bootstrap` or `/api/plan` returns, in `training_calendar`, `planned`, `calendar` or `planning_view.items`, a completed-activity calendar entry or a planned unit matched to an activity
- **THEN** the completed entry and `compliance.actual_activity` use the neutral keys. The planned unit keeps its own `starts_at_local` and `planned_duration_s` unchanged, and its `icu_training_load` appears as `training_load`.

#### Scenario: Neutral value already present
- **WHEN** a stored row carries both a provider key and its neutral counterpart, such as `icu_weighted_avg_watts` and `normalized_power`
- **THEN** the neutral value wins and the provider key is dropped.

#### Scenario: Browser shows unchanged values
- **WHEN** the activity analysis list renders a session summary, including one with `sport` `ride` and `environment` `virtual`, and the calendar renders its completed and matched entries
- **THEN** they show the same dates, durations, distances, heart rate, power and load as the summary, and the indoor ride is labelled "Rad indoor".

Detailed contract: the calendar key map is listed in `openspec/changes/archive/2026-10-30-neutral-activity-http-shape/design.md` (D1). A neutral key that is already present wins. `weighted_average_watts` stays separate from `normalized_power`. The activity detail document (`/api/activities/{id}`) is already neutral and stays unchanged. The provider-coupling ratchet records every module outside the provider, sync and canonical packages that imports a provider field-name module, and that record may only shrink.

Evidence: `backend/canonical/public_metrics.py:neutral_activity`, `backend/canonical/public_metrics.py:neutral_calendar_state`, `backend/activities/read_service.py:ActivityReadService.page`, `backend/http_api/public_plan.py:PublicPlanStateService.read_public`, `public/activity-analysis.js`, `public/performance-view.js`, `public/plan-views.js`; `tests/test_canonical_public_metrics.py:NeutralPublicMetricsTests`, `tests/test_activity_canonical_reads.py:test_list_rows_carry_neutral_names_only`, `tests/plan-views-sport-label.test.cjs`, `tests/test_provider_coupling_guard.py:OwnerReadGuardTests.test_consumers_cannot_import_provider_field_name_modules`; `e2e/contracts.spec.js`, `e2e/activity-details.spec.js`.
