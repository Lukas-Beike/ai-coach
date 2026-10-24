# Design

## Context

See `proposal.md` (Why, existing behavior) and the two spec deltas for the required behavior. This section lists only the constraints that shape the approach.

- `CanonicalDetailReader.read(db, any_id)` (`backend/performance/canonical_detail.py`) already:
  - resolves local/Intervals ids and duplicate chains;
  - merges stored sets;
  - recomputes analysis;
  - accepts optional `summary_row`, `failures` and `envelope` readers.
  It has no production caller. Its `_status` decides Intervals staleness against `summary_fingerprint` of the summary row, and other providers' staleness against `canonical_store.active_provider_record_hash`.
- `activity_detail_contract` (`backend/activities/detail_contract.py`):
  - fills measured metrics from `ActivityRecord`s, which the summary sync keeps current, and fills summary extras from `intervals_summary_metrics(summary)`;
  - `_source()` (~385) and `detail_summary_metrics.py:56` build `{provider, label, kind}` without the recorder.
- Every current kv document (`ActivityDetailRefreshService.refresh`, `backend/sync/activity_details.py:108-188`) holds full-resolution normalized streams (`full_resolution: True`). Older documents may hold streams downsampled by `detail_projection._downsample_series` (≤2000 points, first/last index kept). Their laps come from `_analysis_laps` (≤200 laps, strings ≤120 chars).
- Stream values are stored as float64 (`backend/db/activity_detail_store.py:encode_series`), so value equality is exact.
- The backfill worker (`backend/sync/canonical_backfill_worker.py`) runs each batch inside `maintenance_gate.operation()` and `unit_of_work()`, then runs follow-up stages strictly in order. A batch exception rolls back and calls `mark_failed` in a separate transaction.
- The privacy export (`backend/backup/export.py`):
  - exports canonical detail as JSONL (format version 6);
  - exports every non-excluded kv key in `application_state`, so it includes the kv detail documents today.

## Goals / Non-Goals

**Goals:**

- One canonical read path for all provider sessions.
- A verified, transactional, idempotent removal of redundant kv detail documents.
- No production kv detail reads after this change.

**Non-Goals:**

- Schema version bump or new tables.
- Provider refetch during retirement.
- Re-deriving canonical sets from kv after retirement.
- A new Garmin or Wahoo acquisition path.
- Changes to the activity page list contract beyond removing kv reads.
- Changing `summary_fingerprint`: canonical code imports it, so it stays in `backend/activities/detail_store.py`.

## Decisions

### D1. Reader wiring and the served response

`ActivityAnalysisReadService.detail()` keeps its signature (HTTP and Coach callers unchanged). It works in this order:

1. Normalize the id. Return 400 `invalid_activity_request` for an empty id or one longer than 200 characters, as today.
2. Open one `database_manager.reader()` snapshot and call `CanonicalDetailReader.read(db, id)`.
3. If the reader returns `None`, return 404 `activity_details_not_found` with the provider-neutral message "Diese Aktivität ist lokal nicht vorhanden." This is the message the refresh already uses.

The reader is built in `backend/http_api/activity_assembly.py:ActivityReadAssembly.activity_read()` with these dependencies:

- `session_records`: the existing active-record reader of a canonical session.
- `refreshable`: the providers whose descriptor supports the `activity_details` job type (Intervals.icu, Garmin; Wahoo does not), intersected with the providers configured at read time. Credentials can change at runtime, so this is computed per read through a callable rather than as a fixed `frozenset`. The constructor parameter becomes a provider callable, and tests keep passing a constant.
- `summary_row`: the existing full local summary lookup (`_raw_activity`: snapshot first, then full local history). This preserves the old-activity scenario.
- `failures`: `ActivityDetailStore.failures`.
- `envelope`: a new `DetailEnvelopeReader` owned by `backend/performance/`. It returns:
  - `activity_feedback` for the resolved session reference;
  - `equipment` from `read_equipment`;
  - `activity_validation` from `current_performance_context` using the current Intervals summary when present, otherwise the validation's existing explicit no-data/unsupported result.

The response is the v1 document plus two transport keys: the route's existing `ok` flag and `data_scope`. The keys `activity`, `session_analysis`, `activity_id`, `local_activity_id` and `snapshot_synced_at` are not emitted. `session.activity_id` is the local id.

Routes:

- HTTP (`backend/http_api/sync_get.py`) keeps popping `activity_validation`. It no longer applies `neutral_activity_metrics`, because v1 metric keys are already neutral.
- The Coach tool returns the full envelope.

Alternative considered: a new read service next to `ActivityAnalysisReadService`. Rejected because both callers and the 400/404 error contract already live there.

### D2. Freshness, live scalars, live zones, withheld analysis

- **Scalars.** Measured scalars come from the current `ActivityRecord`s, and Intervals extras come from the current summary row. A cached kv `activity` is never overlaid. This is an intended change to `tests/test_characterization_activity_reads.py:test_changed_provider_summary_marks_record_stale_and_hides_analysis`, which today pins the cached `moving_time` 3600.
- **Zones.** When the summary row carries `HEART_RATE_ZONE_TIMES` or `ZONE_TIMES`, the reader maps those fields with the existing Intervals zone mapping (the zone branch of `intervals_activity_detail_mapping._map_detail`) into `ZoneDistribution` sets for that Intervals record. Before merging, these replace that record's stored zone sets of the same metric. They never enter `_status`, so a zone-only difference does not mark the entry stale. This matches today's fingerprint exclusion.
- **Analysis.** `analysis` is `null` when any provider entry among the merged candidates is stale. Alternative considered: withhold only when a stale provider supplies a selected channel. Rejected as more complex, and the old path hid all analysis once stale.
- **Missing fingerprint.** A set without `summary_sha256` is never stale. This is unchanged from `_status`.

### D3. Recording device and `data_scope`

- `_source(provenance, kind)` and `intervals_summary_metrics` add `"recorded_by": provenance.recorded_by.value`, a `RecordingOrigin` value such as `"garmin"`, `"wahoo"` or `"unknown"`. Summary metrics take it from the Intervals record's provenance, which the reader passes in. The field is additive, and the existing keys are unchanged.
- `data_scope` uses this exact template: `"bounded sanitized activity_detail.v1 document of exactly one local session; providers: <labels>; recorded by: <recorded_by>"`.
  - `<labels>` are the `detail_data.providers[].label` values in document order, joined by `", "`.
  - `<recorded_by>` is the `recorded_by` of `measured_order(records)[0]`.

### D4. Refresh and prefetch without kv documents

- `ActivityDetailRefreshService` requires a canonical writer (the `canonical is None` branch is removed; production always wires `CanonicalDetailWriter`).
- In one `unit_of_work`, refresh runs `write_fetch(...)` and then deletes the failure note through a new `ActivityDetailStore.clear_failure_in(db, activity_id)`. `save_in` is removed.
- `target_snapshot` reuse:
  - Read the canonical analysis payload: `analysis_row_for_record(db, "intervals", activity_id)`, else the session row from `analysis_rows_for`.
  - Reuse `payload["target_snapshot"]` when it is a dict; otherwise call `freeze_targets(...)` as today.
- The `MAX_DETAIL_BYTES` bound stays on the in-memory record passed to `write_fetch`.
- `_pending_prefetch` and `_prefetch_settled` drop `store.fingerprints`. An activity is settled when `intervals_detail_fingerprints` contains its current summary fingerprint. `DETAIL_PROJECTION_VERSION` no longer participates, because canonical mapper and analysis versions are handled by `ActivityDetailBackfill` restarts. Failure-note handling is unchanged.

### D5. Retirement stage

**Module and state.**

- Module: `backend/sync/activity_detail_retirement.py`, class `ActivityDetailRetirement`, implementing `BackfillStage`.
- `STATE_KEY = "activity_detail_retirement_state"`, `STAGE = "activity_detail_retirement"`, batch size 20 (bounded 1..100), `RETIREMENT_VERSION = 1`.
- State: status, retirement_version, mapper_version, cursor, batches, counters, completed_at. The state restarts from an empty cursor when `RETIREMENT_VERSION` or `MAPPER_VERSION` changes.

**Wiring.** `backend/sync/canonical_backfill_assembly.py` sets `followups=(detail_backfill, detail_retirement)` and exposes the stage's `summary` next to the existing one.

**Batch.** Each batch calls `ActivityDetailStore.records_after(db, cursor, batch_size)` and handles each `(key, record)` in key order. The counter outcomes are listed in the comparison steps below. Deleting by exact key is safe for the cursor because the cursor is the last key seen.

Ownership: backend modules must not import `server.py`, so the assembly passes all dependencies explicitly.

**Comparison steps.** An empty set of compared kinds is verified only when the analysis comparison below passes.

Both stream cases in step 6 require equal channel sets. A record with no compared kinds and no analysis keys still needs an existing canonical analysis payload; otherwise it counts `analysis_mismatch`. The analysis payload is read with `analysis_row_for_record` only; the session-row fallback reads the same row and is omitted.

1. Validate the record shape. If the value is not a dict, or `activity_id` is not a non-empty string, count `invalid`.
2. Resolve `link = activity_record_link(db, "intervals", activity_id)`. If it is absent or not ACTIVE, count `no_record`.
3. Map with `map_legacy_activity_detail(record, recorded_by=link.recorded_by)`. If the result has any issues, count `mapping_issues`.
4. Check that every key in `record.activity.streams` maps to a canonical channel. Otherwise count `unmapped_stream`.
5. For each mapped set `m`, load the canonical set `c` for `("intervals", activity_id, m.kind)`. If it is missing, count `no_canonical`. Then require `c.summary_sha256 == record.summary_sha256`, treating `None` as equal to missing; otherwise count `fingerprint_mismatch`.
6. Compare streams:
   - Same resolution: the channel sets are equal, and each channel has equal point count and exactly equal values, including `None` positions.
   - Legacy DOWNSAMPLED with canonical FULL: apply the `_downsample_series` index selection to each canonical channel. The result must equal the legacy channel exactly.
   - Any other combination or inequality counts `streams_unproven`.
7. Compare laps:
   - Compare legacy laps `L[0..n)` against canonical laps `C[0..n)`. Canonical may have more laps, because kv is capped at 200.
   - Per index, require `index`, `start_offset_s` and `end_offset_s` to be equal. Kind is compatible when equal, or when the legacy-mapped kind is `LAP`: kv laps never store the Intervals.icu interval type, so the legacy mapper always yields `LAP` while the FETCH set carries `work`/`recovery`.
   - `name` must be equal, or the kv name must be exactly 120 characters and a prefix of the canonical name.
   - Every `LAP_METRIC_FIELDS` value that is non-null in `L[i]` must equal `C[i]` after the refill in D6.
   - Any failure counts `laps_mismatch`.
8. Compare zones: for each mapped zone metric, every bucket's `index`, `seconds`, `lower`, `upper` and `label` must be equal. Otherwise count `zones_mismatch`.
9. Compare analysis:
   - Load the payload with `analysis_row_for_record(db, "intervals", activity_id)`.
   - If the record has any of `target_snapshot`, `session_analysis` or `calendar_profile`, the payload must exist.
   - The payload's `summary_sha256` must equal the record's.
   - Each of those three keys must be JSON-equal to the record's value; a missing key equals `null`.
   - Any failure counts `analysis_mismatch`.
10. If every step passes, run `DELETE FROM kv WHERE key = ?` for that exact key and count `retired`.

Unverifiable records are never modified, except for the D6 refill, which only adds missing canonical values. The failure note and the prefetch floor are different keys and are never touched.

**Not compared.** The kv document's scalar `activity` fields, `projection_version`, `content_sha256`, `coverage` and `available_streams` are not compared:

- the scalars are provider summary copies superseded by the current summary row and the `ActivityRecord`s (D2);
- the rest are derived bookkeeping.

This is a deliberate decision; see Conflicts C9.

### D6. Lap refill

This step runs before step 7, inside the same batch transaction. Its target is the canonical Intervals lap set of that activity, whatever its origin.

- Refill only after steps 1–6 pass and when, for each compared index, `index`, `start_offset_s` and `end_offset_s` are equal and the kind is compatible as defined in step 7. If any differs, there is no refill and step 7 fails.
- For every lap metric that is NULL canonically and non-null in the legacy-mapped lap, write the legacy value.
- Use a new `backend/db/activity_detail_store.py:refill_lap_metrics(db, provider, provider_activity_id, values)`. It runs `UPDATE ... SET col = COALESCE(col, ?)` and then recomputes `content_sha256` and `updated_at`.
- `origin`, `mapper_version`, `fetched_at` and `summary_sha256` are unchanged.
- Count `laps_refilled` per set.

Alternative considered: re-run `write_legacy` for FETCH sets. Rejected because it would replace full-resolution FETCH streams with kv data.

### D7. Store reduction and guard

**Store reduction.**

- `ActivityDetailStore` keeps `failures`, `save_failure`, `clear_failure`, `clear_failure_in`, `prefetch_floor`, `save_prefetch_floor` and `records_after`. `records_after` is used only by the backfill and retirement stages.
- Removed: `get`, `save`, `save_in`, `fingerprints`, `calendar_profiles`, `analysis_summaries`.
- `recent_kv_analyses` and `_KV_SQL` are removed. `detail_analysis_reads._recent` reads canonical rows only.

**Guard test.** `tests/test_activity_detail_kv_guard.py` scans `backend/**/*.py` and `server.py` and fails on any of the following outside the allowlist:

- the literal `activity_detail:` record prefix;
- `records_after`;
- `map_legacy_activity_detail`;
- `write_legacy`.

The allowlist is:

- `backend/activities/detail_store.py`
- `backend/sync/activity_detail_backfill.py`
- `backend/sync/activity_detail_retirement.py`
- `backend/sync/activity_detail_canonical.py`
- `backend/providers/intervals_activity_detail_mapping.py`

Failure-note keys use `activity_detail_failure`. The guard must match the colon-terminated prefix only.

### D8. PWA mapping

The PWA renders only from the document:

| PWA element | Source |
| --- | --- |
| Session header | `session.{sport, started_at, name}` |
| Summary values | `metrics.<key>.value` (`moving_duration_s`, `distance_m`, `load`, `avg_hr`, `avg_power`, …) |
| Charts | `streams.time_s` and `streams.channels.{heart_rate_bpm, power_w, speed_mps, cadence_rpm, altitude_m, temperature_c}` (exact channel names from `StreamChannel`) |
| Laps | `laps.laps[]` using neutral lap fields |
| Zones | `zones.<metric>.buckets[]`, labelled with `zones.<metric>.source.label` instead of the fixed "Zonen laut Intervals.icu" |
| Analysis | `analysis.*` |
| Notes | per-provider `detail_data.providers[]` `stale` / `load_error` / `coverage` / `fetched_at` |
| Sampling note | `detail_data.display_sampled` |

- `aerobic.provider_decoupling` and the other analysis texts use their own `source_label`.
- Refresh: one action per provider entry with `refreshable: true`. It posts the existing CSRF-protected activity-detail job with that `provider` and the session's local id. Garmin accepts `act_` aliases; for Intervals the server resolves the local reference as it does today.
- `isIntervalsActivity` is replaced by this entry check.
- The feedback POST uses `session.name` and `session.started_at`.
- `public/index.html` `?v=` for `activity-details.js` and `activity-analysis.js` and the `public/service-worker.js` cache name and `ASSETS` change together.

## Risks / Trade-offs

- [Breaking response for the PWA and the Coach] → One PR switches all consumers. The service-worker cache bump forces fresh assets, and Playwright on all five projects covers both specs.
- [Coach tool result size grows with merged multi-provider streams] → The contract already bounds presentation sampling (`display_sampled`). Add a test that the Coach result stays within the existing tool-output bound.
- [Retirement deletes data] → It deletes only after field-exact comparison in the same transaction, never touches unverifiable records, and keeps counters per reason. The rollback, restart and v9–v13 upgrade tests are acceptance evidence.
- [After retirement, a future `MAPPER_VERSION` bump cannot re-derive canonical sets from kv] → Accepted. Retired records are exactly the ones whose canonical copy was proven equal. Later re-mapping must use explicit provider reloads.
- [Analyses kept only in unverifiable kv records are no longer displayed after fallback removal] → Accepted (decision 11). They stay stored and are counted in stage state.
- [Scalar-only kv fields are deleted with verified records] → They duplicate provider summary data that the summary row and `ActivityRecord`s still hold.
- [Garmin refresh becomes reachable from the PWA] → It uses the existing Garmin activity-detail job and its rate-limit handling, and is offered only when Garmin is configured. See Conflicts C3.

## Migration Plan

1. There is no schema version bump. The retirement stage starts with the canonical backfill worker after startup and after `ActivityDetailBackfill` completes. Upgrades from v9..v13 run the existing schema migrations first, then the backfill, then retirement.
2. Interrupted runs roll back the batch and resume from the stored cursor. Completed runs are no-ops until `RETIREMENT_VERSION` or `MAPPER_VERSION` changes.
3. Restoring a pre-retirement backup on this build restores the kv records and stage state, and the stages then run again.
4. Rollback: reverting this build before retirement is safe. Restoring a post-retirement backup on an older build is an unsupported downgrade (note only). The older build would read no kv detail and would show canonical-only data through its own paths.

## Conflicts between the brief and source/specs

Parent decision (2026-10-24): every default below is accepted as designed. C3 is accepted because Garmin-only sessions become readable and need the existing explicit Garmin detail job to load detail.

- **C1.** The old path hides stale `session_analysis`, while the canonical reader always recomputes. This design withholds `analysis` when any merged provider is stale (D2).
- **C2.** Stored zone sets versus live-row zones. Decision 4 is implemented by replacing the Intervals zone candidates from the summary row (D2). Garmin and Wahoo zones remain stored-only.
- **C3.** `refreshable` already includes Garmin (its descriptor supports `activity_details` and accepts `act_` ids). Offering a Garmin refresh in the PWA is new UI. This design offers it (D8). The alternative is to keep an Intervals-only refresh offer.
- **C4.** `refresh()` clears failure notes through `ActivityDetailStore.save_in`. Without the kv write, a new in-transaction `clear_failure_in` is needed (D4).
- **C5.** `refresh()` has a kv-only branch when `canonical is None`. Production always wires the writer, and this design removes the branch.
- **C6.** HTTP pops `activity_validation` today. This is kept with the v1 envelope.
- **C7.** After retirement, `ActivityDetailBackfill` restarts on a mapper bump cannot re-derive retired records (trade-off above).
- **C8.** The brief says `backend/coach/dialogue.py:120` names Intervals.icu. The inspected text does not, and only `backend/coach/tool_schemas.py:258` does. dialogue.py only needs a wording check.
- **C9.** kv scalar fields, `projection_version`, `content_sha256`, `coverage` and `available_streams` are excluded from the retirement comparison (D5).
- **C10.** The 404 message names "lokalen Intervals.icu-Snapshot". It becomes provider-neutral (D1).
- **C11.** `refreshable` is a constant `frozenset` in the reader constructor. Configuration can change at runtime, so this design changes it to a callable (D1).
- **C12.** For sessions without an Intervals summary row, `activity_validation` has no input. This design returns the validation's explicit no-data/unsupported result (D1).
