## Why

Several activity use cases still read, or even rewrite, the stored Intervals.icu snapshot instead of the canonical `activity_records` / `activity_sessions` tables. Once the tables serve reads the snapshot is stored without its activity sections, so these paths are either dead fallbacks or they corrupt freshness: confirming a duplicate delete today restamps the whole Intervals snapshot `synced_at` with the delete time. Issue #1414 (Epic A #1407) removes these bypasses so that the next metrics (Epic S) and the removal of the selector fallback (#1416) rest on canonical data only.

## What Changes

Existing behavior (verified in source on origin/develop `6eab8617d`):

- Duplicate flow. The only duplicate resolution is the Coach action `delete_duplicate_intervals_activity` (read-only `inspect_activity_duplicates`, a `coach_action_proposals` preview, the athlete's confirmation, then execution). There is no HTTP duplicate route, no merge or undo flow, no change-history entry for it, and no code writes `activity_sessions.athlete_confirmed`.
  - `backend/activities/duplicate_inspection.py:DuplicateInspector.latest` already reads rows through the injected `ActivityRowReader` (raw Intervals payloads of the canonical table source) and reads the snapshot only for `synced_at`. The pair rule works on those raw payloads (`backend/activities/duplicates.py:latest_wahoo_garmin_duplicate_from_rows`, `intervals_cycling_activities_match`).
  - `backend/activities/duplicates.py:latest_wahoo_garmin_duplicate(snapshot)` is the only caller of `intervals_activity_rows` there and has no production caller, only tests.
  - `backend/activities/duplicate_service.py:DuplicateActivityService.delete` revalidates the pair and the `snapshot_synced_at` token, calls `intervals_client.delete_activity` once, then in one unit of work runs `remove_activity_from_snapshot`, `canonical_store.mark_activity_deleted` and a snapshot save, and publishes `duplicate_deleted`. For a stripped snapshot (`snapshot_storage.py`) `remove_activity_from_snapshot` only sets `synced_at` to the delete time and the save adds a snapshot row, so a delete makes the Intervals data look freshly synced.
  - The manifest token `snapshot_synced_at` is the snapshot sync time. It is copied into the stored proposal payload (`proposal_creation.py:_duplicate_approval_arguments`) and compared on execution (`validate_duplicate_delete`, `sync_tools.py:_delete_duplicate_activity`).
- Canonical sync already writes heuristic duplicate links (`activity_sessions.state='duplicate'`, `merged_into`, `link_kind='heuristic'`) through `backend/activities/session_linking.py:link_activity_sessions`; `backend/activities/canonical_sessions.py` holds the same Wahoo/Garmin ride rule over `ActivityRecord` values.
- Lookup. `backend/performance/activity_read_service.py:ActivityAnalysisReadService.detail` falls back to `_snapshot_activities(snapshot)` (`raw_provider_data.activities`) when no canonical rows were read. Production always wires the canonical source and row reader, so the fallback is reachable only through optional wiring.
- Training reports. `backend/performance/training_report.py:canonical_rows(snapshot)` reads `raw_provider_data.activities` (or `recent_activities`). It has four callers that fall back to it when `canonical_inputs.activity_rows_for` returns None (no source or no row reader): `report_service.py:TrainingRecordsService.observations`, `training_report.py:training_report`, `tag_impact.py:_day_loads` and `training_focus.py:training_focus`. The report also reports `observed_at` from `snapshot["synced_at"]`.
- Garmin status. `backend/sync/garmin_projection_service.py:GarminProjectionService._intervals_rows_legacy` reads `recent_activities` from the snapshot when no `GarminCanonicalSources` is injected; production always injects it.
- Freshness. `backend/activities/read_service.py:ActivityReadService._read` returns `snapshot["activities_synced_at"]` (else `synced_at`) as `snapshot_synced_at` of `/api/activities`, and `backend/coach/context.py:CoachIntervalsContextService.project` labels the Coach `activities` section with `snapshot["synced_at"]`. Canonical provider coverage (`ProviderCoverage.activities_retrieved_at`, persisted at ingest, served by `CanonicalReadSelector.coverage`) already carries the activity fetch time.

Proposed behavior:

- Duplicate detection and inspection read canonical Intervals.icu activity records (recorded by Wahoo or Garmin) and apply the canonical Wahoo/Garmin ride rule. The result keeps the manifest shape (`canonical_id`, `canonical_name`, `duplicate_id`, `duplicate_name`, `start_date_local`, `moving_time`, `distance`, `snapshot_synced_at`). Wahoo stays the kept recording.
- **BREAKING (internal contract value)** The manifest key `snapshot_synced_at` is kept, but its value is the newest canonical `fetched_at` of the two records, not the snapshot sync time. A proposal created before the upgrade carries the old value and fails with the existing 409 stale response; the athlete re-analyses.
- The confirmed delete keeps the remote behavior exactly: same gate, same approval proposal, same receipts, one `delete_activity` call. Locally it only tombstones the canonical records and session, in one transaction, and publishes the event. It no longer rewrites or saves a snapshot, so the Intervals snapshot `synced_at` is unchanged.
- `remove_activity_from_snapshot` and `latest_wahoo_garmin_duplicate(snapshot)` are removed.
- Single-activity lookup, the four training-report callers and the Garmin projection read canonical rows only. `canonical` becomes a required dependency of these services; the snapshot fallbacks and `canonical_rows` are removed. `filter_garmin_activities` keeps comparing the raw Garmin payload with the canonical Intervals rows.
- The `snapshot_synced_at` of `/api/activities`, the Coach `activities.synced_at` and `activities.source.synced_at`, and the report `observed_at` are read from canonical provider coverage (`activities_retrieved_at`). Keys do not change. Without stored coverage (before the first completed backfill) the value is None; there is no snapshot fallback.
- Deleting a surviving session (the confirmed Garmin copy, or a provider disappearance) re-points its live aliases: the oldest alias becomes the active survivor and the others merge into it, so the kept Wahoo ride keeps resolving to a live session for detail, lists and feedback. Before, the alias stayed merged into the deleted session and its detail read as not found.
- Merge and undo flows, an `athlete_confirmed` writer, and any new remote write are out of scope and would be a separate issue.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `activity-ingestion-and-storage`: local activity reads take their sync time from canonical coverage; duplicate deletion no longer rewrites the snapshot and its pair detection and confirmation token read canonical records; Garmin status compares against canonical Intervals rows only.
- `activity-analysis-and-feedback`: single-activity lookup reads canonical rows only.
- `performance-and-readiness`: period reports, tag impact and training focus read canonical activity rows only; report `observed_at` comes from canonical coverage.
- `coach-context-and-provenance`: the activities section freshness comes from canonical coverage.

## Impact

- Backend:
  - `backend/activities/duplicates.py`, `duplicate_inspection.py`, `duplicate_service.py`, `read_service.py`
  - `backend/performance/activity_read_service.py`, `training_report.py`, `report_service.py`, `tag_impact.py`, `training_focus.py`, `canonical_inputs.py`
  - `backend/sync/garmin_projection_service.py`, `garmin_assembly.py`
  - `backend/coach/context.py`, `context_assembly.py`, `proposal_creation.py` and `sync_tools.py` (token only)
  - `backend/db/canonical_store.py` (alias repair when a surviving session is deleted)
  - wiring in `backend/http_api/activity_assembly.py`, `athlete_assembly.py`, `public_state_assembly.py` and `server.py`
- Tests: duplicate, duplicate service, deletion, training report, focus, activity read and analysis, Garmin projection and Coach context modules move from snapshot-seeded rows to synthetic canonical sessions of two providers.
- Data: no schema change, no migration, no provider refetch. `backend/db/canonical_store.py` gets one repair in `_delete_activity`: deleting a surviving session re-points its live aliases (design D8).
- API/Coach/PWA: same keys. No `public/` change is expected, so no asset version bump; if one becomes necessary, `public/index.html` query versions and the `public/service-worker.js` cache name change together.
- Remote writes: unchanged. The only remote write remains the athlete-confirmed Intervals.icu delete of the Garmin copy.
- Exclusions: removal of the canonical read selector fallback and snapshot gate (#1416), performance legacy fallbacks (#1415), provider-neutral key names (#1413), and Epic B schema work (PR #1464).
