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
  activities, `device_type` (`DeviceType`, a class). No device model, firmware
  or measurement window exists (#1420).
- **Local method:** the method ID on the card (for example
  `personal-quartiles-v1`). The `observations.method` and `aggregation` columns
  exist but are never written (#1418).

## M1 — Session-RPE load

| Input | Canonical storage today | Evidence |
| --- | --- | --- |
| Elapsed duration | Intervals: `elapsed_duration_s` in the record details JSON; `duration_s` is moving time when present. Garmin: `duration_s` is elapsed (`duration`), `moving_duration_s` separate. Wahoo: `duration_s` is moving time when present, no elapsed field. | `backend/providers/intervals_activity_mapping.py:427-446`, `backend/providers/garmin_activity_mapping.py:87-88`, `backend/providers/wahoo_activity_mapping.py:74-75`, `backend/db/canonical_store.py:34` |
| Local session RPE | `activity_feedback.session_rpe` (0–10), keyed by the provider activity id plus `provider`; no link to `activity_sessions` | `backend/db/schema.py:662-673`, `backend/activities/feedback.py:43` |
| Intervals `icu_rpe` | No canonical field. Kept in the stored provider activity row; the browser contract renames it to `rpe` | `backend/providers/intervals_activity_fields.py:47`, `backend/canonical/public_metrics.py:17` |
| One session per ride | `bundle_sessions` groups records; `link_activity_sessions` marks the younger session `duplicate` with `merged_into` | `backend/activities/canonical_sessions.py:97`, `backend/activities/session_linking.py:47` |

Consumer trace (no M1 method exists yet):

- Rating input: `public/activity-details.js:80` → `POST /api/activities/{id}/feedback`
  (`backend/http_api/feedback_post.py:24`) → `ActivityFeedbackService`
  (`backend/activities/feedback.py`).
- Report: `training_report` lists `activity_feedback` with `session_rpe`
  (`backend/performance/training_report.py:284`); rows are deduplicated by
  `deduplicated_rows` (`:35`), a second rule beside the session state.
- Coach: feedback tools (`backend/coach/athlete_record_tools.py:102`,
  `backend/coach/tool_schemas.py:651`) and the planning context field list
  (`backend/planning/context.py:26`).
- `athlete_checkins.session_rpe` (`backend/db/schema.py:1037`) is a daily
  check-in value and is not an M1 input.

## M2 — HRV and resting HR

| Input | Canonical storage today | Evidence |
| --- | --- | --- |
| HRV RMSSD | `MetricKind.HRV_RMSSD` from Intervals `hrv` and Garmin last-night HRV | `backend/canonical/vocabulary.py:86` |
| HRV SDNN | `MetricKind.HRV_SDNN` from Intervals `hrvSDNN` only | `backend/canonical/vocabulary.py:87` |
| Resting HR | `MetricKind.RESTING_HR` | `backend/canonical/vocabulary.py:85` |
| Nightly or morning, window | not stored; `observed_at` is empty for daily values | #1418, #1420 |

Consumer trace:

- Canonical read: `read_personal_recovery_inputs` reads **resting HR only**
  (`backend/performance/canonical_personal_recovery.py:42-60`).
- Method: `personal_recovery` (`backend/performance/personal_recovery.py:32`)
  reads HRV from raw Intervals wellness rows and the raw Garmin payload
  (`:202`); a canonical resting HR replaces the legacy value only when provider,
  day and number match (`:105`, `backend/performance/canonical_recovery.py:72`).
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
| Sleep start and end, night or nap | no canonical kind or table; read from raw payload fields | `backend/performance/personal_recovery.py:297` |
| Sleep goal | athlete profile | `backend/performance/personal_recovery.py:170` |

Consumer trace:

- Method: `personal_recovery` → `_sleep_deficits` (`personal_recovery.py:170`)
  and `sleep_regularity` (`:241`), both on raw rows. No canonical sleep read
  exists.
- Report/context, HTTP, UI and Coach as for M2; in addition the Coach tool
  `get_training_report(sections=["sleep_regularity"])`
  (`backend/coach/activity_read_tools.py:83`) via
  `TrainingDerivedReadService.sleep_regularity`
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
| Feedback keyed by provider id, not canonical session | M1 | persistence | #1423 (#1408) |
| Elapsed duration in three provider-specific places; Wahoo keeps none | M1 | mapping, maybe persistence | #1427; no #1408 sub-issue yet |
| `icu_rpe` has no canonical field | M1 | mapping, maybe persistence | D3 on #1406; no #1408 sub-issue yet |
| Two duplicate rules (session state and `deduplicated_rows`) | M1 | read path | #1427 |
| HRV and sleep duration read from raw rows | M2, M3 | read path | #1411 |
| Canonical resting HR only replaces an equal legacy value | M2 | read path | #1415 |
| No method, aggregation or measurement window on observations | M2, M3 | persistence | #1418 (#1408) |
| No device model or firmware | M2, M3, M4 | persistence | #1420 (#1408) |
| No sleep periods (start, end, night or nap) | M3 | persistence | #1419 (#1408) |
| Timing deviations computed below 14 earlier intervals | M3 | method | #1429 |
| Labels "sleep deficit" and regularity | M3 | wording | #1426 |
| No full-resolution filter and no 180/420/720 s windows | M4 | method | #1430 |
| Reports read stored analyses with kv fallback | M4 | read path | #1410 |
| No CP/CS fit | M4 | method | #1431 |
| No RR/NN stream | M2 | out of scope | #1428 |

Two needs have no #1408 sub-issue: a provider-independent elapsed duration and
a canonical home for `icu_rpe`. They are listed here; filing them is outside
this change.

## Fixture index

Classes in `tests/test_performance_method_inputs.py`; each has `test_complete`,
`test_incomplete` and `test_contradictory`.

| Method | Class | Extra tests | Pinned gaps |
| --- | --- | --- | --- |
| M1 | `M1SessionRpeInputs` | — | #1427, #1423, D3 on #1406 |
| M2 | `M2HrvRestingHrInputs` | `test_canonical_resting_hr_override_needs_an_exact_match`, `test_canonical_hrv_is_not_consulted` | #1415, #1411 |
| M3 | `M3SleepInputs` | `test_canonical_sleep_inputs_are_not_available` | #1429, #1411, #1419 |
| M4 | `M4BestEffortInputs` | — | #1430 |
