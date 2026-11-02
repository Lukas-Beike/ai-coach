## MODIFIED Requirements

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
- **WHEN** populated databases built from the frozen fixtures for schema v16 through v18 with seeded kv detail records are upgraded and the backfill and retirement stages run
- **THEN** every seeded detail remains readable as `activity_detail.v1`, verified kv records are retired, and unverifiable ones remain stored.

#### Scenario: Legacy target basis
- **WHEN** a preserved kv detail record uses the former FTP key in its frozen target basis
- **THEN** canonical backfill stores the equivalent neutral basis, and retirement compares normalized values without discarding conflicting data.

#### Scenario: Backup, restore and privacy export
- **WHEN** a database is backed up, restored or privacy-exported after retirement
- **THEN** the canonical detail sets, stream channels, laps, zone times and analysis payloads are present, and retired kv records are absent from the exported application state.

Evidence: `backend/sync/activity_detail_retirement.py:ActivityDetailRetirement`, `backend/db/activity_detail_store.py:refill_lap_metrics`, `backend/sync/canonical_backfill_assembly.py`; `tests/test_activity_detail_retirement.py:test_proven_record_is_deleted_and_other_keys_are_kept`, `tests/test_activity_detail_retirement.py:test_missing_lap_speed_is_refilled_before_the_record_is_retired`, `tests/test_activity_detail_retirement.py:test_lap_metric_that_differs`, `tests/test_activity_detail_retirement.py:test_failed_batch_rolls_back_refills_and_deletions`, `tests/test_activity_detail_retirement.py:test_restart_resumes_from_the_cursor_and_repeats_nothing`, `tests/test_activity_detail_retirement_upgrade.py:test_released_schemas_upgrade_and_retire_proven_records` (the SQLCipher variant is skipped without SQLCipher), `tests/test_activity_detail_retirement_backup.py:test_restored_backup_serves_the_same_document`, `tests/test_activity_detail_retirement_backup.py:test_privacy_export_holds_the_retired_detail_in_the_canonical_files`. Related existing behavior: `backend/sync/activity_detail_backfill.py:ActivityDetailBackfill`, `backend/sync/canonical_backfill_worker.py`.

Additional evidence: `tests/test_activity_detail_canonical.py::test_legacy_target_basis_is_normalized_without_changing_source`; `tests/test_activity_detail_retirement.py::test_legacy_target_basis_is_compared_after_normalization`; `tests/test_activity_detail_retirement.py::test_conflicting_legacy_target_basis_is_not_retired`.
