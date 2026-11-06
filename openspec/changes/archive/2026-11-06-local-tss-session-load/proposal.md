## Why

Load sums count only TSS-scale provider loads (Intervals.icu `icu_training_load`, Wahoo TSS). Without Intervals.icu ingest (epic #1732) almost every session would drop out, because Garmin's load is EPOC-based (#1725, #1717 inventory). The athlete decided on 2026-11-06 that TSS and IF are always computed locally, with one method and the thresholds valid on the session day, and stored per session.

## What Changes

- New method M6 `local-tss-load` v1 (card `docs/performance-methods/m6-local-tss-load.md`, released 2026-11-06): power (NP/FTP), then run pace (grade-adjusted speed vs threshold pace), then heart rate (Banister TRIMP normalised to one threshold hour); none for strength, yoga, alpine ski and walking.
- Thresholds are resolved per session day under the current-threshold source policy; a session before any threshold takes the earliest later one, flagged `threshold_after_session`.
- Each value is a derived `session_load` observation (and `intensity_factor` for power) owned by the canonical session, with method, version and input fingerprint. A backfill follow-up stage recomputes changed sessions after completed Intervals.icu, Garmin and Wahoo jobs, local zone changes, session corrections, a changed preferred threshold source and worker start, and retires values of sessions that are gone.
- Summaries serve `training_load` and `intensity` only from the local method; provider values move to `provider_training_load`, `provider_load_model` and `provider_intensity`. The Coach reads `load_branch` instead of `load_model`.
- Garmin activity mapper v15 maps `avgGradeAdjustedSpeed`. Diagnostics report content-free `local_load` counts.
- Out of scope: local CTL/ATL/form (#1726), eFTP and power curve (#1727).

## Impact

- `backend/performance/local_tss.py`, `backend/sync/local_load.py`, `backend/sync/canonical_backfill_assembly.py`, `backend/sync/canonical_read_selector.py`, `backend/sync/executor.py`, `backend/athlete/zones.py`, `backend/activities/activity_summary.py`, `backend/db/canonical_store.py`, `backend/providers/garmin_activity_mapping.py`, `backend/diagnostics/report.py`, `server.py`.
- No schema change (observations hold the values; schema stays v21), no provider write, no frontend change.
