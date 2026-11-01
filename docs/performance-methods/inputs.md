# Method inputs, provenance and consumers (gate G1)

Checked 2026-10-24 against `develop` at `3553c1597` for #1425. This page records
where each input of M1–M4 is stored today, how provenance is kept apart, which
code reads it, and what is missing. Synthetic fixtures for every statement
below are in `tests/test_performance_method_inputs.py`; a pinned gap there names
its issue and fails when the gap closes.

Provenance has three separate parts. Fixtures check them separately:

- **Transport provider:** `Provenance.provider` / the record's `provider`
  (Intervals.icu, Garmin, Wahoo).
- **Recording origin:** `recorded_by` (`RecordingOrigin`, a brand) and, for
  activities, `device_type` (`DeviceType`, a class). A typed measurement
  context (device model, firmware, algorithm, sensor, window, protocol) is
  stored since schema v15; unreported fields stay explicitly unknown (#1420).
- **Local method:** the method ID on the card (for example
  `personal-quartiles-v1`). Provider-fixed `observations.method` and
  `aggregation` are written since schema v15, for example Garmin last-night HRV
  as `rmssd` mean over the overnight window (#1418).

## M1 — Session-RPE load

| Input | Canonical storage today | Evidence |
| --- | --- | --- |
| Elapsed duration | `elapsed_duration_s` in the record details JSON for every provider (Intervals elapsed time, Garmin `duration`, Wahoo `duration_total_accum`, since #1445); `duration_s` stays the provider summary duration and `moving_duration_s` separate. | `backend/providers/intervals_activity_mapping.py:427-446`, `backend/providers/garmin_activity_mapping.py:175-177`, `backend/providers/wahoo_activity_mapping.py:265-273`, `backend/db/canonical_store.py:34` |
| Local session RPE | `activity_feedback.session_rpe` (0–10) with `session_id` (#1423) and, since schema v18, `session_rpe_rated_at` | `backend/db/schema.py`, `backend/activities/feedback.py` |
| Intervals `icu_rpe` | `ActivityRecord.rpe`, stored in the activity record details with provider provenance (#1510, closes #1446); the summary marks disagreeing records with `rpe_conflict` | `backend/providers/intervals_activity_mapping.py`, `backend/db/canonical_store.py`, `backend/activities/activity_summary.py` |
| One session per ride | `bundle_sessions` groups records; `link_activity_sessions` marks the younger session `duplicate` with `merged_into` | `backend/activities/canonical_sessions.py:97`, `backend/activities/session_linking.py:47` |

Consumer trace (method `session-rpe-load-v1`, `backend/performance/session_rpe_load.py`, #1427):

- Rating input: `public/activity-details.js` (CR-10 selection) → `POST /api/activities/{id}/feedback`
  (`backend/http_api/feedback_post.py:24`) → `ActivityFeedbackService`
  (`backend/activities/feedback.py`).
- Report: `training_report` carries `session_rpe_load` per session, day, week
  and sport from one summary per canonical session and the session's effective
  feedback (`backend/performance/report_service.py`); the public performance
  history carries the load tab's 84 days (`backend/http_api/public_performance.py`),
  the activity detail the session value (`backend/performance/detail_envelope.py`).
- Coach: feedback tools (`backend/coach/athlete_record_tools.py`,
  `backend/coach/tool_schemas.py`); `session_rpe_load` in `get_training_report`
  and `get_activity_details`. The planning context projects feedback with notes
  or a session RPE (`FEEDBACK_FIELDS`, `backend/planning/context.py`).
- `athlete_checkins.session_rpe` (`backend/db/schema.py:1037`) is a daily
  check-in value and is not an M1 input.

## M2 — HRV and resting HR

| Input | Canonical storage today | Evidence |
| --- | --- | --- |
| HRV RMSSD | `MetricKind.HRV_RMSSD` from Intervals `hrv` and Garmin last-night HRV | `backend/canonical/vocabulary.py:86` |
| HRV SDNN | `MetricKind.HRV_SDNN` from Intervals `hrvSDNN` only | `backend/canonical/vocabulary.py:87` |
| Resting HR | `MetricKind.RESTING_HR` | `backend/canonical/vocabulary.py:85` |
| Nightly or morning, window | Garmin HRV: `overnight` window in the measurement context; Intervals HRV: not reported | #1418, #1420 |

Consumer trace:

- Canonical read: `read_recovery_inputs` reads sleep duration and score, resting
  HR, RMSSD, SDNN, the Garmin weekly HRV average and readiness of all providers
  (`backend/performance/canonical_recovery.py`) since #1411, and for M3 timing
  the canonical sleep periods (#1419, #1429).
- Method: `personal_recovery` (`backend/performance/personal_recovery.py`)
  builds one series per provider and measurement from the daily canonical
  observations and restarts the comparison at a change of method, aggregation
  or measurement context (#1428); no raw provider row or payload is read.
- Report/context: `current_performance_context` (`backend/performance/context.py:167`).
- HTTP: `GET /api/performance` (`backend/http_api/athlete_get.py:51`) and the
  report services (`backend/http_api/assembly.py:430`).
- UI: `renderPersonalRecovery` (`public/analysis.js:1192`, called from
  `public/performance-view.js:311`).
- Coach: `personal_recovery` projection (`backend/coach/context.py:423-455`).

## M3 — Sleep duration, goal shortfall and timing

| Input | Canonical storage today | Evidence |
| --- | --- | --- |
| Sleep duration | `MetricKind.SLEEP_DURATION` (s) from Intervals and Garmin | `backend/canonical/vocabulary.py:88` |
| Sleep start and end, night kind | canonical `sleep_periods` (schema v15): UTC bounds, ingest zone, wake date, NIGHT or UNKNOWN; naps out of scope | `backend/canonical/domain_records.py`, `backend/providers/sleep_period_mapping.py` |
| Sleep goal | athlete profile `sleep_target_hours` | `backend/performance/personal_recovery.py:63` |

Consumer trace:

- Method: `personal_recovery` → `_sleep_deficits` on canonical sleep duration
  observations, and `sleep_timing_variability` (`sleep-timing-variability-v2`)
  on canonical sleep periods only (#1429).
- Report/context, HTTP, UI and Coach as for M2; in addition the Coach tool
  `get_training_report(sections=["sleep_timing_variability"])`
  (`backend/coach/activity_read_tools.py:83`) via
  `TrainingDerivedReadService.sleep_timing_variability`
  (`backend/performance/report_service.py:399`).

## M4 — Critical Power and Critical Speed

| Input | Canonical storage today | Evidence |
| --- | --- | --- |
| Power, speed, distance, time streams | `activity_detail_sets` (with `resolution`) and `activity_stream_channels` | `backend/db/activity_detail_store.py` |
| Resolution | Intervals fetch `full`, legacy cache `full` only when marked, Garmin `downsampled`, FIT (Wahoo) `full` | `backend/providers/intervals_activity_detail_mapping.py:195,227-230`, `backend/providers/garmin_activity_detail_mapping.py:207`, `backend/providers/fit_activity_detail_mapping.py:257` |
| Effort windows | 5–3600 s for cycling; no 180, 420 or 720 s window | `backend/performance/power_profile.py:10-13` |

Consumer trace (no M4 method exists yet):

- Per activity: `CanonicalDetailReader.read`
  (`backend/performance/canonical_detail.py:113`) follows a merged session
  (`:68`), `merge_details` (`backend/activities/detail_merge.py:126`) prefers a
  full-resolution stream set, then `power_profile` runs on the result.
- Reports: stored analyses (`backend/db/activity_analysis_reads.py:78`, kv
  fallback `:92`) → `power_profiles`
  (`backend/performance/report_service.py:123`) → `GET /api/analysis/power-profiles`
  (`backend/http_api/analysis.py:40`) → `public/analysis.js`; Coach tool
  `get_training_report(sections=["power_profiles"])`
  (`backend/coach/activity_read_tools.py:72`).
- `power_profile` does not check resolution; a downsampled stream still gives
  best efforts.

## Data gaps and persistence needs

| Gap | Method | Kind | Owner |
| --- | --- | --- | --- |
| Elapsed duration in three provider-specific places; Wahoo keeps none | M1 | mapping | resolved by #1445 |
| `icu_rpe` has no canonical field | M1 | mapping | resolved by #1510 (#1446) |
| Two duplicate rules (session state and `deduplicated_rows`) | M1 | read path | resolved: M1 reads one summary per canonical session (#1427) |
| Planning context omits feedback `session_rpe` | M1 | read path | resolved by #1427 |
| HRV and sleep duration read from raw rows | M2, M3 | read path | resolved by #1411 |
| Canonical resting HR only replaces an equal legacy value | M2 | read path | resolved by #1411 |
| Method, aggregation and window stored; only Garmin HRV populates them | M2, M3 | mapping | #1418 (#1408) |
| Device model and firmware unknown for Garmin HRV (no measurement-associated evidence) | M2, M3, M4 | mapping | #1420 (#1408) |
| Timing deviations computed below 14 earlier intervals | M3 | method | resolved by #1429 (`sleep-timing-variability-v2`) |
| Labels "sleep deficit" and regularity | M3 | wording | resolved by #1426 |
| No full-resolution filter and no 180/420/720 s windows | M4 | method | #1430 |
| Reports read stored analyses with kv fallback | M4 | read path | #1410 |
| No CP/CS fit | M4 | method | #1431 |
| No RR/NN stream | M2 | out of scope | #1428 |

The canonical home for `icu_rpe` (#1446) was delivered by #1510, the
provider-independent elapsed duration by #1445.

## Fixture index

Classes in `tests/test_performance_method_inputs.py`; each has `test_complete`,
`test_incomplete` and `test_contradictory`.

| Method | Class | Extra tests | Pinned gaps |
| --- | --- | --- | --- |
| M1 | `M1SessionRpeInputs` | — | — |
| M2 | `M2HrvRestingHrInputs` | `test_canonical_resting_hr_is_the_primary_input`, `test_canonical_hrv_is_read_per_provider` | — |
| M3 | `M3SleepInputs` | `test_sleep_duration_and_timing_are_canonical_inputs` | — |
| M4 | `M4BestEffortInputs` | — | #1430 |
