## MODIFIED Requirements

### Requirement: Durable Intervals detail cache and prefetch
The system SHALL fetch full-resolution Intervals detail only for a valid locally known activity, verify returned identity, normalize supported streams, laps, and zones, and store canonical detail sets and the canonical analysis payload atomically, without writing a kv detail document. Automatic prefetch SHALL initially establish its floor from the ten newest activities, thereafter load new activities at or above that fixed floor, and limit each pass to 25 provider loads. Frozen planned targets SHALL be reused from the stored canonical analysis payload of the session.

#### Scenario: Failed second detail request
- **WHEN** an activity's previous canonical detail exists and its next provider stream request fails
- **THEN** the previous canonical sets and analysis payload remain readable and no half-written new detail replaces them.

#### Scenario: Old known activity requested
- **WHEN** the athlete requests a valid known activity before the prefetch floor
- **THEN** explicit loading can populate its detail even though automatic prefetch leaves it alone.

#### Scenario: Successful refresh writes only canonical state
- **WHEN** an explicit or automatic Intervals.icu detail load succeeds
- **THEN** the canonical sets and analysis payload are written, the failure note of that activity is deleted in the same transaction, and no `activity_detail:<sha>` kv row is created or updated.

#### Scenario: Canonical write fails
- **WHEN** the canonical detail write raises inside the refresh transaction
- **THEN** no canonical set, analysis payload or failure-note deletion is committed.

#### Scenario: Prefetch settledness
- **WHEN** prefetch decides whether an activity still needs loading
- **THEN** it uses only the summary fingerprints stored with canonical detail sets and analysis payloads, plus failure notes for the same fingerprint. A remaining kv detail record does not mark an activity settled.

#### Scenario: Target reuse after reload
- **WHEN** a session already has a canonical analysis payload with a `target_snapshot` and its detail is reloaded
- **THEN** that frozen snapshot is reused instead of re-freezing targets from the current plan.

Detailed contract: Summary fingerprints SHALL prevent redundant loads and invalidate stale data/failure notes after corrections. Failure notes and the prefetch floor remain small kv keys. Older activities SHALL remain available for explicit detail loading. The refresh use case SHALL require a canonical detail writer.

Evidence: `backend/sync/activity_details.py:ActivityDetailRefreshService.refresh`, `backend/sync/activity_details.py:INITIAL_PREFETCH_ACTIVITIES`, `backend/activities/detail_store.py:ActivityDetailStore`, `backend/db/activity_detail_fingerprints.py:intervals_detail_fingerprints`; `tests/test_activity_detail_refresh.py:test_first_run_loads_the_ten_newest_activities_once`, `tests/test_activity_detail_refresh.py:test_changed_summary_is_loaded_again`, `tests/test_activity_detail_refresh.py:test_failed_canonical_write_leaves_neither_record_nor_rows`. Missing evidence (planned): tests that no kv detail row is written, that targets are reused from canonical payloads, and that settledness ignores kv records.

### Requirement: Local activity reads and pagination
The system SHALL read activity rows and sync metadata from one local read snapshot without refreshing providers, expose local activity references with feedback, and offer descending keyset pagination with versioned cursors and legacy cursor compatibility. Page limits SHALL default to 100 and clamp to 1 through 250. Reads SHALL retain summary rows whose detail failed and show only failure notes matching the current summary fingerprint. Production activity, detail, report and calendar reads SHALL NOT read `activity_detail:<sha>` kv records; only the backfill and retirement maintenance modules may read them.

#### Scenario: Next activity page
- **WHEN** the athlete requests a page after a valid cursor
- **THEN** results follow the stable descending local-time/id boundary and include a next cursor only when more rows remain.

#### Scenario: Detail failure or invalid cursor
- **WHEN** detail is unavailable or a cursor cannot be decoded
- **THEN** summary reading remains usable; a matching detail error is shown and an invalid cursor falls back to the first-page boundary.

#### Scenario: Guarded kv detail access
- **WHEN** the repository test suite runs
- **THEN** a guard test fails if any production module outside the backfill and retirement modules references the `activity_detail:` kv record prefix or the legacy detail record reader.

Detailed contract: Activity freshness SHALL remain independent of unrelated performance refresh timestamps.

Evidence: `backend/activities/read_service.py:ActivityReadService.page`, `backend/activities/read_service.py:ActivityReadService._read`; `tests/test_activity_read_service.py:test_page_filters_orders_attaches_feedback_and_uses_cursor`, `tests/test_activity_read_service.py:test_page_keeps_activities_with_failed_details_and_names_the_error`, `tests/test_activity_read_service.py:test_activity_refresh_timestamp_is_independent_of_performance_refresh`. Missing evidence (planned): the kv access guard test.

## ADDED Requirements

### Requirement: Verified kv detail retirement
The canonical backfill runner SHALL run a retirement stage after the activity detail backfill. Per kv detail record it SHALL map the record with the legacy mapper, refill canonical lap metrics that are missing, compare the defined fields with the canonical rows, and delete the kv record in the same transaction only when every comparison passes. It SHALL NOT request provider data, and unverifiable records SHALL stay unchanged and be counted.

#### Scenario: Verified record retired
- **WHEN** a kv record maps to canonical sets and an analysis payload that match on every compared field
- **THEN** the kv record is deleted in the batch transaction and the stage state counts it as retired.

#### Scenario: Missing lap metric refilled
- **WHEN** a canonical Intervals.icu lap set written before schema v13 has a NULL `max_speed_mps` or another NULL lap metric that the matching kv lap carries
- **THEN** that NULL is filled from the kv lap before the comparison, and non-NULL canonical values are never overwritten.

#### Scenario: Unverifiable record kept
- **WHEN** a record has no active Intervals.icu activity record, has no canonical set, fails a compared field, or holds downsampled streams that cannot be proven against the canonical streams
- **THEN** the kv record and its canonical rows are unchanged and the stage state counts it under its reason.

#### Scenario: Interrupted batch
- **WHEN** a retirement batch fails after some refills or deletions
- **THEN** the whole batch transaction rolls back, the stage is marked failed in its own transaction, and no kv record is lost without its verified canonical copy.

#### Scenario: Same-build restart
- **WHEN** the application restarts after a completed or interrupted retirement
- **THEN** the stage resumes from its stored cursor or reports completion, and repeating it changes no further rows.

#### Scenario: Upgrade from supported released schemas
- **WHEN** populated databases built from the frozen fixtures for schema v9 through v13 with seeded kv detail records are upgraded and the backfill and retirement stages run
- **THEN** every seeded detail remains readable as `activity_detail.v1`, verified kv records are retired, and unverifiable ones remain stored.

#### Scenario: Backup, restore and privacy export
- **WHEN** a database is backed up, restored or privacy-exported after retirement
- **THEN** the canonical detail sets, stream channels, laps, zone times and analysis payloads are present, and retired kv records are absent from the exported application state.

Evidence: Missing evidence (planned): the retirement stage module under `backend/sync/`, its wiring in `backend/sync/canonical_backfill_assembly.py`, and tests for refill, verified deletion, unverifiable retention, rollback, restart idempotency, upgrades from `tests/fixtures/schema_v9.sql.txt` through `tests/fixtures/schema_v13.sql.txt`, and backup/restore/export coverage through `backend/backup/export.py`. Related existing behavior: `backend/sync/activity_detail_backfill.py:ActivityDetailBackfill`, `backend/sync/canonical_backfill_worker.py`.
