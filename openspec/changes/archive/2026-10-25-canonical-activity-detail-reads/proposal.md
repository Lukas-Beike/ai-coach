## Why

Session detail is still served from the legacy kv `activity_detail:<sha>` document overlaid on the live Intervals.icu summary row. Garmin-only and Wahoo-only sessions therefore return 404, and every response is labelled as Intervals.icu data. Meanwhile the canonical detail tables and the `activity_detail.v1` reader already exist but have no production caller. Issue #1410 (Epic A #1407) asks to serve canonical detail and retire the kv copy without losing athlete data.

## What Changes

Existing behavior (verified in source on origin/develop 0afdb7514):

- `ActivityAnalysisReadService.detail()` (`backend/performance/activity_read_service.py`) serves both `GET /api/activities/<id>` (`backend/http_api/sync_get.py`) and the Coach tool `get_activity_details` (`backend/coach/activity_read_tools.py`).
  - It reads `ActivityDetailStore.get()` and overlays the cached `activity` on the live summary row, with live zone times on top.
  - A stale record hides `session_analysis` but keeps its cached scalars.
  - `data_scope` is fixed to "exactly one Intervals.icu activity".
  - Sessions with no Intervals summary row return 404.
- `CanonicalDetailReader` (`backend/performance/canonical_detail.py`) builds `activity_detail.v1` (`backend/activities/detail_contract.py`) only in tests. It has no envelope reader, `refreshable` set, or summary-row wiring, and its `source` objects omit the recording device.
- `ActivityDetailRefreshService.refresh` (`backend/sync/activity_details.py`) writes the kv document and the canonical sets in one unit of work. It reuses `target_snapshot` from kv. Prefetch settledness prefers the kv fingerprint.
- `CanonicalDetailWriter.write_legacy` skips activities that already have FETCH-origin sets. As a result, lap `max_speed_mps` (schema v13) stays NULL for FETCH sets written before v13, even when the kv laps carry it.
- `calendar_profiles` and `analysis_summaries` (`backend/activities/detail_analysis_reads.py`) merge canonical analysis rows with a temporary kv fallback (`recent_kv_analyses`). `ActivityDetailStore.calendar_profiles` and `ActivityDetailStore.analysis_summaries` have no production caller.

Proposed behavior:

- **BREAKING** `GET /api/activities/<id>` and the Coach tool `get_activity_details` serve the `activity_detail.v1` document plus its feedback/equipment/validation envelope. HTTP keeps omitting the validation part.
  - The legacy keys `activity`, `session_analysis`, `local_activity_id`, `activity_id` and the flat `detail_data` shape are removed.
  - No dual or compatibility keys remain.
  - The PWA (`public/activity-details.js`, `public/activity-analysis.js`) switches in the same change. Asset query versions and the service-worker cache bump together.
- Local `act_` ids of Garmin-only and Wahoo-only sessions become readable through the same path.
- Activity scalars come from the current summary row, and Intervals zone times come from the live row.
  - The stale notice stays, decided per provider by comparing the stored canonical fingerprint with the current summary fingerprint.
  - Recomputed analysis is withheld while a contributing provider is stale.
- Every `source` object gains an additive `recorded_by` recording-device field. `data_scope` names the provider(s) and the recording device.
- The Coach tool and dialogue descriptions become provider-neutral.
- A verified kv-detail retirement stage runs after `ActivityDetailBackfill` in the canonical backfill runner. For each kv record it:
  - maps the record with the legacy mapper;
  - refills missing canonical lap metrics, including `max_speed_mps`;
  - compares defined fields;
  - deletes the kv record in the same transaction only when the comparison passes.
  Unverifiable records stay and are counted. There is no provider refetch and no schema version bump.
- `refresh()` stops writing the kv document but still clears the failure note atomically. `target_snapshot` reuse reads the canonical analysis payload. Prefetch settledness uses canonical fingerprints only.
- The kv analysis fallback and the dead kv scans are removed. `ActivityDetailStore` keeps only failure notes and the prefetch floor. A guard test forbids production reads of `activity_detail:` kv keys outside the backfill and retirement modules.
- Test and e2e seeds move from kv detail documents to canonical sets. README is kept consistent.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `activity-analysis-and-feedback`: the served detail contract becomes `activity_detail.v1` for HTTP/Coach/PWA. Freshness, analysis withholding and zone authority move to the canonical reader. The detail read is reachable for every provider session.
- `activity-ingestion-and-storage`: Intervals detail refresh and prefetch stop using the kv document. Local activity reads stop depending on kv detail. A verified kv detail retirement stage is added.

## Impact

- Backend:
  - `backend/performance/activity_read_service.py`, `backend/performance/canonical_detail.py`
  - `backend/activities/detail_contract.py`, `backend/activities/detail_store.py`, `backend/activities/detail_analysis_reads.py`
  - `backend/db/activity_analysis_reads.py`
  - `backend/sync/activity_details.py`, `backend/sync/activity_detail_canonical.py`, `backend/sync/canonical_backfill_assembly.py`
  - a new retirement stage module under `backend/sync/`
  - `backend/http_api/activity_assembly.py`, `backend/http_api/sync_get.py`
  - `backend/coach/activity_read_tools.py`, `backend/coach/tool_schemas.py`, `backend/coach/dialogue.py` (wording check)
- Frontend: `public/activity-details.js`, `public/activity-analysis.js`, `public/index.html`, `public/service-worker.js`.
- Tests and fixtures:
  - `tests/test_characterization_activity_reads.py`: an intended behavior change in the stale-scalar pin.
  - `tests/test_canonical_detail_reader.py`, `tests/test_activity_detail_contract.py`, `tests/test_activity_detail_refresh.py`, `tests/test_activity_read_service.py`, `tests/test_activity_reference.py`, `tests/test_fixture_standard_data.py`
  - `e2e/fixture_runtime.py`, `e2e/activity-details.spec.js`, `e2e/activity-detail-floor.spec.js`
  - new retirement, upgrade and guard tests using `tests/fixtures/schema_v9..v13.sql.txt`
- Data:
  - No schema change.
  - kv `activity_detail:<sha>` rows are deleted only after verification.
  - The privacy export loses those rows from `application_state` (`backend/backup/export.py:application_state` exports every kv key) and keeps the canonical detail JSONL files.
- API: a breaking response shape for one authenticated local route and one Coach tool. There is no external API or provider write change.
