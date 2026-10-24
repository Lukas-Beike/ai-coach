# Tasks

## 1. Retirement and canonical data path (slice A)

- [x] 1.1 Add `refill_lap_metrics(db, provider, provider_activity_id, values, *, now)` (returns the number of filled metric values) to `backend/db/activity_detail_store.py`. It fills only NULL lap metric columns and recomputes `content_sha256`/`updated_at` (design D6). Verify with a new test that a NULL `max_speed_mps` is filled, a non-NULL value is never overwritten, and the content hash changes only when a value was filled.
- [x] 1.2 Create `backend/sync/activity_detail_retirement.py:ActivityDetailRetirement` implementing `BackfillStage` with the state, counters, cursor and version restart from design D5, and the exact comparison steps 1–10 plus the D6 refill. Verify with new tests in `tests/test_activity_detail_retirement.py`:
  - a verified record is deleted in the batch and counted `retired`;
  - each unverifiable reason (`invalid`, `no_record`, `mapping_issues`, `unmapped_stream`, `no_canonical`, `fingerprint_mismatch`, `streams_unproven`, `laps_mismatch`, `zones_mismatch`, `analysis_mismatch`) leaves the kv row and the canonical rows unchanged and increments its counter;
  - a downsampled kv stream is proven against a FULL canonical set through the `_downsample_series` index selection;
  - failure notes and the prefetch floor are untouched;
  - no provider client is called.
- [x] 1.3 Wire the stage after `ActivityDetailBackfill` in `backend/sync/canonical_backfill_assembly.py` (`followups=(detail_backfill, detail_retirement)`) and expose its summary. Verify with a worker test that retirement runs only after the detail backfill completes, that an exception in a retirement batch rolls back every refill and deletion of that batch and marks the stage failed in its own transaction, and that a same-build restart resumes from the cursor and is idempotent (a second pass changes no rows).
- [x] 1.4 Make `ActivityDetailRefreshService` (`backend/sync/activity_details.py`) canonical-only (design D4):
  - require the canonical writer;
  - write `write_fetch` and the new `ActivityDetailStore.clear_failure_in` in one unit of work;
  - reuse `target_snapshot` from the canonical analysis payload;
  - base prefetch settledness only on `intervals_detail_fingerprints` and same-fingerprint failure notes.
  Verify by updating `tests/test_activity_detail_refresh.py`. It must show that no `activity_detail:` kv row is written, the failure note is deleted atomically, a failed canonical write commits nothing, the frozen targets are reused, a leftover kv record does not settle prefetch, and the existing ten-newest/floor/25-per-pass tests still pass.
- [x] 1.5 Remove the kv analysis fallback (`backend/db/activity_analysis_reads.py:recent_kv_analyses`, `_KV_SQL`) and make `backend/activities/detail_analysis_reads.py:_recent` canonical-only. Verify that the tests covering `calendar_profiles` (`backend/http_api/public_plan.py`) and `analysis_summaries` (`backend/performance/report_service.py`) pass with canonical rows only, and that a kv-only analysis is no longer returned (intended, decision 11).
- [x] 1.6 Add populated upgrade evidence in `tests/test_activity_detail_retirement_upgrade.py`. For each of `tests/fixtures/schema_v9.sql.txt` through `tests/fixtures/schema_v13.sql.txt`:
  - build a temporary SQLCipher database with Intervals records and seeded kv detail records (one current full-resolution record, one old downsampled record, and one pre-v13 FETCH lap set with realistic `work`/`recovery` kinds lacking `max_speed_mps`);
  - upgrade it, then run the backfill and retirement stages;
  - assert that every seeded detail is readable as `activity_detail.v1`, that verified kv rows are gone and unverifiable ones remain, and that the refilled lap speed is present.
  Also verify that an interrupted retirement rolls back and that a same-build restart is idempotent.
- [x] 1.7 Extend backup/restore and privacy-export tests (`backend/backup/export.py`). After retirement, assert that `activity_detail_sets`, `activity_stream_channels`, `activity_laps`, `activity_zone_times` and `activity_detail_analysis` JSONL files contain the detail, that the retired kv keys are absent from `application_state`, and that a restored backup serves the same v1 document. Verify with the focused backup/export test modules.

## 2. Served `activity_detail.v1` contract (slice B)

- [x] 2.1 Add `recorded_by` to `backend/activities/detail_contract.py:_source` and to the summary metric sources in `backend/activities/detail_summary_metrics.py` (design D3). Verify in `tests/test_activity_detail_contract.py` that every `source` carries `recorded_by`, that `"unknown"` is used when the recorder is unknown, and that the existing keys are unchanged.
- [x] 2.2 Extend `CanonicalDetailReader` (design D1/D2):
  - accept a `refreshable` provider callable;
  - substitute live Intervals zone sets from the summary row without affecting `_status`;
  - return `analysis: null` when any merged provider is stale.
  Verify in `tests/test_canonical_detail_reader.py` with tests for live zones overriding stored zones, stale withholding, sets without a fingerprint never being stale, failure notes being ignored for another fingerprint, and the current summary scalars being shown when stale.
- [x] 2.3 Add the production envelope reader under `backend/performance/` (feedback, equipment, activity validation; design D1) and wire `CanonicalDetailReader` in `backend/http_api/activity_assembly.py` with session records, the refreshable callable, the summary-row lookup and failures. Verify with a test that the envelope keys are populated for Intervals, Garmin and Wahoo sessions and that validation for sessions without an Intervals summary returns its explicit no-data result.
- [x] 2.4 Switch `ActivityAnalysisReadService.detail()` to the canonical reader:
  - keep the 400 response;
  - return a provider-neutral 404;
  - add `ok` and the `data_scope` template from design D3;
  - emit no legacy keys.
  Update `tests/test_characterization_activity_reads.py`. Record `test_changed_provider_summary_marks_record_stale_and_hides_analysis` as an intended behavior change (current scalars) and port the other staleness characterizations to canonical seeds. Verify with `tests/test_activity_read_service.py` and the characterization module.
- [x] 2.5 Update the HTTP route `backend/http_api/sync_get.py`: keep popping `activity_validation`, drop `neutral_activity_metrics` for the detail body, and keep authentication first. Verify with HTTP route tests for authentication before reads, the v1 body shape, a Garmin-only `act_` id returning 200, and an unknown id returning 404.
- [x] 2.6 Update the Coach tool `get_activity_details` (`backend/coach/activity_read_tools.py`) and its provider-neutral descriptions in `backend/coach/tool_schemas.py:258` and, if wording requires it, `backend/coach/dialogue.py:118-124`. Verify with Coach tool tests for the v1 result including `activity_validation`, a bounded result size, and description text that no longer limits the tool to Intervals.icu.
- [x] 2.7 Add parity tests over synthetic Intervals.icu, Garmin and Wahoo/FIT sessions in `tests/test_activity_detail_parity.py`. For the same seeded data, the old projection values (duration, distance, laps, zones, stream presence, analysis/stale handling) appear in the corresponding v1 fields, and `data_scope` names provider(s) and recorder. Verify by running the module.
- [x] 2.8 Switch `public/activity-details.js` and `public/activity-analysis.js` to the v1 document following the design D8 mapping:
  - per-provider notes;
  - a refresh offer from `detail_data.providers[]` with `refreshable: true`;
  - zone and analysis labels from their sources;
  - the feedback POST from `session`.
  Then bump the `public/index.html` query versions and the `public/service-worker.js` cache name and `ASSETS` together. Verify with `node --test tests/*.cjs` (asset-version test) and by updating `e2e/activity-details.spec.js` and `e2e/activity-detail-floor.spec.js`.
- [ ] 2.9 Run `npm run test:e2e -- e2e/activity-details.spec.js e2e/activity-detail-floor.spec.js` on mobile-small, mobile, tablet, tablet-landscape and desktop. Verify that all pass, including a Garmin-only session opening and a stale/load-error note per provider.

## 3. Cleanup and guard (slice C)

- [ ] 3.1 Reduce `backend/activities/detail_store.py:ActivityDetailStore` to failure notes, the prefetch floor and `records_after`. Remove `get`, `save`, `save_in`, `fingerprints`, `calendar_profiles` and `analysis_summaries`, and keep `summary_fingerprint`. Verify with `python -m compileall -q server.py backend tests` and repository-wide mypy showing no remaining callers.
- [ ] 3.2 Add `tests/test_activity_detail_kv_guard.py`, implementing the design D7 scan and allowlist. Verify that it passes on the final tree and fails when a probe production module referencing `activity_detail:` is introduced in a temporary copy inside the test.
- [ ] 3.3 Migrate test and e2e seeds from kv detail documents to canonical sets: `e2e/fixture_runtime.py` (the `ActivityDetailStore(...).save` uses near lines 583, 733, 1591 and 2084–2119), `tests/test_fixture_standard_data.py:446`, and `tests/test_activity_reference.py` (lines 304, 458, 465). Verify with those modules and with the Playwright specs from 2.9.
- [ ] 3.4 Check `README.md` for kv-detail, detail-response or Intervals-only detail wording and update it to the canonical behavior and the retirement stage. Verify with a grep for `activity_detail:` and the changed sections.

## 4. Validation (slice D)

- [ ] 4.1 Run `python -m unittest discover -s tests -v` and `python -m compileall -q server.py backend tests` on the final tree. Both must pass.
- [ ] 4.2 Run repository-wide mypy and ruff exactly as CI does. Single-file mypy is insufficient. Both must pass.
- [ ] 4.3 Run `node --test tests/*.cjs` and the affected Playwright projects from 2.9 on the final tree. All must pass.
- [ ] 4.4 Manually check, if a browser is available: login, fresh PWA install/offline assets after the cache bump, detail open for Intervals and Garmin-only sessions, stale/load-error notes, and the refresh offer.
- [ ] 4.5 Review scoped evidence. Map each #1410 acceptance criterion to the tasks and spec scenarios below, inspect the complete diff, and confirm that no production module reads `activity_detail:` kv keys.
  - Canonical reads for all providers: 2.3–2.5 and 2.7 ("Garmin-only or Wahoo-only session").
  - Envelope: 2.3 ("One served contract").
  - Recording device and `data_scope`: 2.1, 2.4 and 2.7 ("Recording device provenance").
  - Stale/parity: 2.2, 2.4 and 2.7 ("Summary corrected after analysis", "Live zone times").
  - Consumers switched: 2.5, 2.6, 2.8 and 2.9.
  - Kv writes stopped: 1.4 ("Successful refresh writes only canonical state").
  - Verified retirement with lap refill: 1.1–1.3 ("Verified record retired", "Missing lap metric refilled", "Unverifiable record kept", "Interrupted batch", "Same-build restart").
  - Upgrade/backup/export: 1.6–1.7 ("Upgrade from supported released schemas", "Backup, restore and privacy export").
  - Fallback/store reduction and guard: 1.5, 3.1 and 3.2 ("Guarded kv detail access").
- [ ] 4.6 Run `npm run -s openspec -- validate canonical-activity-detail-reads --strict`. It must pass.

## Workflow follow-up

- Apply this change through `.agents/skills/orchestrated-plan-implementation/SKILL.md` as one PR for #1410.
- Archive the change after review requirements are satisfied, then run `.agents/skills/ai-coach-retro/SKILL.md`.
