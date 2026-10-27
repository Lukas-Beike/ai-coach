## Context

Epic A (#1407) moves every application read onto the canonical model; #1410 (activity detail) and #1411 (recovery) are merged. This change covers #1414. Motivation and the verified current behavior are in `proposal.md`.

Inspected revision: origin/develop `6eab8617d`. Constraints taken from source:

- The table reader's `activity_rows` returns the stored, sanitized raw Intervals.icu payloads of live activities (`backend/sync/canonical_table_reader.py:CanonicalTableReader.activity_rows`). Reports, focus and impact compute from those payload fields (`moving_time`, `icu_training_load`, zones). "Canonical rows" for them means this row port; mapping the reports to `ActivityRecord` is not part of this change.
- `ActivityRecord` values (`CanonicalTableReader.activities`) carry provider, `activity_id` (the provider activity id), `recorded_by`, sport, start instant, `duration_s`, `distance_m`, name and `provenance.retrieved_at` (the row's `fetched_at`). Unchanged records have their `fetched_at` refreshed by each fetch (`canonical_store._refresh_fetch_time`).
- `backend/activities/canonical_sessions.py` already holds the canonical Wahoo-recorded vs Garmin-recorded Intervals ride rule (30 minute start window, duration and distance present, positive and within `max(floor, 10 %)`).
- Persisted `merged_into` does not say which side is Wahoo: `session_linking._age` keeps the older session by `created_at`.
- Provider coverage is persisted at ingest (`canonical_coverage:<provider>`) and served by `CanonicalReadSelector.coverage(db)` (`ProviderCoverageReader`). `ProviderCoverage.activities_retrieved_at` is derived from the same snapshot field the read service uses today, except that a duplicate delete can no longer move it.
- `public/activity-analysis.js:422` builds its list cache key as `${payload.snapshot_synced_at}|<activity ids>`. It uses the value only to detect a changed sync.
- `AGENTS.md`: remote writes need the athlete to name the sync; the remote delete path must stay as it is.

## Goals / Non-Goals

**Goals:**
- Duplicate detection, inspection and the local effect of the confirmed delete use canonical records and tables only; the Intervals snapshot is neither read for activities nor rewritten.
- Lookup, the four report-family callers and the Garmin projection have one source: the canonical row port, required at construction.
- Freshness labels of activity reads come from canonical provider coverage, with unchanged keys.
- Dead snapshot code (`remove_activity_from_snapshot`, `latest_wahoo_garmin_duplicate(snapshot)`, `canonical_rows`, `_snapshot_activities`, `_intervals_rows_legacy`) is removed.

**Non-Goals:**
- A merge or undo flow, an `athlete_confirmed` writer, new remote writes, new Coach tools, or any change to the approval gate and receipts.
- Removing the selector's legacy projection, the snapshot gate or the compact-row special case (#1416); performance fallbacks (#1415); renamed output keys (#1413).
- A schema change or a mapper version change. The only `canonical_store` edit is the alias repair of D8.
- Replacing `filter_garmin_activities`' raw Garmin payload input.

## Decisions

### D1 Scope is the existing remote-delete flow

Detection, the Coach proposal, the athlete confirmation, one Intervals.icu `delete_activity` call and the local tombstone stay the only duplicate behavior. Gate (`write_gate.REMOTE_INTERVALS`), proposal types, outcomes text (`Garmin-Duplikat entfernt`), the delete result (`status`, `deleted_activity_id`, `kept_activity_id`, `kept_source`) and the `duplicate_deleted` event are unchanged. `ActivitySessionState.DUPLICATE`, `merged_into`, `ActivityLinkKind` and `athlete_confirmed` are not used for new behavior.

Alternative considered: implement athlete-confirmed merge with undo receipts as the issue text suggests. Rejected by decision: no such flow exists today, it needs a new writer, history entity and UI, and it would be a separate issue.

### D2 Canonical detection and inspection

`DuplicateInspector` reads canonical Intervals activity records from the canonical tables directly (`CanonicalTableReader`, the table-backed `ActivityReader` that knows tombstones) instead of raw rows, and takes the athlete's time zone provider. It never reads through the read selector: before the first completed backfill the selector serves the snapshot projection, which is not rewritten by a delete and would keep offering the tombstoned copy, and a second confirmation would send another remote delete for an already-deleted id. Reading the tables is not enough while the selector is legacy: a delete tombstones the tables but leaves the snapshot unchanged, and the next incremental Intervals sync ingests the snapshot payload again and revives the deleted copy (`upsert_activity_record` makes it active), so the pair would be offered again with a fresh token and deleted twice. The inspector therefore also takes the existing `CanonicalTableServing` port (`selector.serves_tables(db)`, wired through `AthleteRepositories.table_serving`) and returns no pair while the tables do not serve reads, i.e. before the first completed backfill. A Coach proposal then cannot be created and `inspect_activity_duplicates` reports none. Validation in the delete path uses the same inspection, so a confirmation submitted in that state, or after the copy is tombstoned, gives the existing 409 before any provider call. Once the tables serve, behaviour is as described above.

- Candidates: `provider == intervals`, `sport == ride`, active, `recorded_by` Wahoo (kept) or Garmin (duplicate).
- Rule: `canonical_sessions` exposes its Wahoo/Garmin copy predicate publicly and the inspector uses it, so the all-pairs semantics of the legacy search are kept (the bundling assigns each copy to its first Wahoo match, which is not the same selection).
- "Newest" gate: as before, only a pair that contains the newest Intervals activity is reported. Garmin- and Wahoo-provider records are not part of this gate, as the legacy rows were Intervals rows only. Of several pairs the newest start wins.
- View: `canonical_id` and `duplicate_id` are the Intervals provider activity ids; names are truncated as today; `start_date_local` is the start on the athlete's wall clock in the existing `YYYY-MM-DDTHH:MM:SS` form; `moving_time` is the Wahoo record's `duration_s` (the Intervals.icu moving time, else elapsed time); `distance` is `distance_m`.
- Persisted `merged_into` links are not consulted: they are survivor-by-age, not by recorder.

Known parity differences, pinned by characterization tests: virtual rides and other cycling kinds follow the canonical sport mapping instead of `activity_kind`; the duration compared is the canonical `duration_s` (Intervals moving time, else elapsed) instead of `moving_time or elapsed_time` of the raw row.

Alternative considered: run `bundle_sessions` over the Intervals records and read the sessions. Rejected: first-match-wins can pick another pair than the legacy all-pairs search.

### D3 Stale-safe confirmation token

The manifest key `snapshot_synced_at` is kept so that proposals, Coach tool output, receipts and tests keep one contract. Its value is the newest `provenance.retrieved_at` (ISO text) of the two records. Because every fetch refreshes `fetched_at`, the token changes with any later fetch of either record and stays independent of the snapshot.

`validate_duplicate_delete` is unchanged in logic: any mismatch of `canonical_id`, `duplicate_id` or the token gives the existing 409 (`_DUPLICATE_DELETE_STALE_ERROR`) before any remote call, event or write. Pending proposals created with the old value fail the same way; the proposal TTL is short and the athlete re-analyses.

Alternative considered: a pair fingerprint (hash of ids and measurements). Rejected: a new value type for no extra safety, and it would not follow later fetches.

### D4 Delete without snapshot surgery

`DuplicateActivityService.delete` order stays: inspect, resolve ids, validate, remote `delete_activity`, then one local unit of work with `canonical_store.mark_activity_deleted` (record, provider record, session), then the event. The snapshot reader and repository dependencies, `remove_activity_from_snapshot`, `_save_snapshot` and the stripped-snapshot activity count are removed. The snapshot, its `synced_at` and the snapshot row count are not touched. The only `canonical_store` change is the alias repair of D8.

Lists and reports served by the selector may still show the deleted copy until the first backfill completes, because the snapshot is deliberately not rewritten; this transient legacy-window visibility is accepted (#1416 removes the window). Deleting duplicates is not offered in that window at all (D2), so the legacy snapshot never has to be rewritten. A remote failure leaves local data untouched. A local failure after a successful remote delete keeps the documented non-promise of distributed rollback.

### D5 Required canonical dependency for lookup, reports and Garmin status

- `ActivityAnalysisReadService` requires `canonical` and the row reader; `_snapshot_activities` and the `rows is None` branch go away. A missing id still reads the full history in the same read snapshot ("Valid old activity").
- `TrainingRecordsService`, `TrainingReportReadService` and `TrainingDerivedReadService` require `canonical`; `activity_rows_for` no longer returns None (it requires a reader). `training_report`, `tag_impact` and `training_focus` take the rows as a required argument; `canonical_rows` is removed and `deduplicated_rows` is kept (equipment and reports use it).
- `GarminProjectionService` requires `GarminCanonicalSources`; `_intervals_rows_legacy` and the `None` branch of `_canonical_read` go away. `filter_garmin_activities(snapshot["activities"], canonical Intervals rows)` is unchanged.

Without activity rows the outputs are the existing empty-data outputs (no sessions, `insufficient_data`), not an error.

### D6 Freshness from canonical coverage

The activity read service and the Coach activities reader receive a `ProviderCoverageReader` and read, in the same read snapshot as the rows, the Intervals `activities_retrieved_at` (ISO text). That value becomes:

- `snapshot_synced_at` of `GET /api/activities` pages and the recent list;
- `activities.synced_at` and `activities.source.synced_at` of the Coach context;
- `observed_at` of the training report (passed in by `TrainingReportReadService`; `training_report` no longer takes a snapshot).

The stored coverage already keeps the snapshot's `activities_synced_at` semantics, so values equal today's, except that a duplicate delete no longer moves them. Unrelated performance refreshes still do not move it.

Empty coverage (before the first completed backfill, or no Intervals ingest yet): the value is None and there is no snapshot fallback. Evidence that this is safe for the PWA: `public/activity-analysis.js` only concatenates the value into a list cache key together with the activity ids, so `null|<ids>` still renders and still re-renders when the ids change; the empty list renders the "Noch keine abgeschlossenen Einheiten" text. Before the first backfill the selector serves legacy rows (#1416 scope), so a summary-only correction without new ids would not invalidate the cached list until the backfill completes; that window is transient and accepted. No `public/` change is needed.

Alternative considered: provider refresh freshness (`last_success_at`). Rejected: it moves on empty refreshes and is a sync-job concept, not the data's fetch time.

### D7 Tests move to synthetic canonical sessions

Fixtures for the duplicate, deletion and service tests seed `activity_records` / `provider_records` / sessions for a Wahoo-recorded and a Garmin-recorded Intervals ride (and a Garmin-provider record) with `canonical_store.upsert_activity_record`, `upsert_provider_record` and, where needed, `merge_activity_session`, on a real temporary SQLite database, with an absent snapshot. The pattern of `MergedDuplicateDeleteTests` in `tests/test_activity_duplicate_service.py` is reused; `SnapshotActivityRows` stays only for tests that exercise the legacy selector. Report and lookup tests pass canonical rows through `FixedActivityRows`-style readers and assert that the snapshot is never read.

### D8 Re-point the aliases of a deleted surviving session

The canonical merge keeps the older session as survivor, which can be the Garmin copy that the confirmed delete tombstones. `canonical_store._delete_activity` (reached through `mark_activity_deleted` of the duplicate flow and `mark_missing_deleted` of provider disappearance, the only code that sets a session to `deleted`) therefore repairs the aliases in the same transaction:

- the oldest live alias (by creation, then id) becomes the active survivor and its `merged_into` is cleared;
- every other live alias merges into it;
- the deleted session, and every deleted alias that retained it, now retain the new survivor in `merged_into_retained`. Epic B's semantics stay: feedback written for any of them keeps grouping on one live session (`effective_session_ids`), and `read_reference`, detail lookup, lists and `resolve_reference` never reach a deleted session.

No live session is left merged into a deleted one. A deleted session without aliases is unchanged. No schema change is needed (`merged_into_retained` exists since v15, the existing CHECK constraints hold), so no migration or frozen-schema fixture applies. The remote delete is untouched: one `delete_activity` call, same gate, proposal and receipts.

Alternative considered: re-pointing at read time in `read_reference`. Rejected: every reader of `merged_into` would need it, and the stored state would stay inconsistent across restart and backup/restore.

## Risks / Trade-offs

- [Survivor-deleted alias] Resolved by D8: deleting a surviving session now re-points its live aliases. Pinned by `tests/test_activity_duplicate_service.py` (`SurvivorDeletedAliasTests`, `SeveralAliasesTests`), `tests/test_activity_duplicate_feedback.py` and `tests/test_duplicate_persistence.py`.
- [Pair-rule parity] Sport and duration fields differ from the raw-row rule (D2). → Characterization tests with the existing `WahooGarminDuplicateTests` and `IntervalsCyclingMatchTests` cases ported to records; each differing expectation is commented.
- [In-flight proposals] A proposal created before the upgrade has an old token and returns 409. → Documented in the proposal; no data is lost.
- [Pre-backfill coverage is empty] `snapshot_synced_at` is None until the backfill completes. → Accepted (D6); the legacy selector window is removed by #1416.
- [Pre-backfill duplicate visibility] While the selector serves the snapshot, lists and reports can still show a Garmin copy deleted earlier, and duplicate deletes are not offered at all. → Accepted (D2/D4/D6): inspection and the delete validation read the tables and require `serves_tables`, so there is never a wrong or repeated remote delete, including after a sync revives a tombstoned record from the unchanged snapshot; pinned by `tests/test_sync_snapshot_storage.py:LegacyStateDuplicateTests`.
- [Required dependencies break optional wiring] Tests and compositions that omitted `canonical` fail at construction. → Intended; production already wires everything; the full suite and `server.py` import prove the wiring.
- [Conflict with Epic B PR #1464] Shared files: `backend/performance/activity_read_service.py`, `backend/coach/context.py`, `context_assembly.py`, `backend/http_api/athlete_assembly.py` and `public_state_assembly.py`, `server.py`, `tests/test_activity_reference.py`, `tests/canonical_read_support.py`. → Keep edits narrow, rebase onto whichever merges first.

## Migration Plan

- No schema change, no migration, no mapper bump, no provider refetch.
- On deploy nothing is rewritten. Existing tombstones, sessions and merged states are untouched; restart and backup/restore keep them (verified by task 5.1).
- Rollback: an older build reads the same tables; it would again restamp the snapshot on a duplicate delete, which is the defect being fixed.

## Open Questions

None.
