# Tasks

Implement in order. Each task names its tier (L1 simple, L2 standard, L3 complex) and its verification. The acceptance mapping for #1413 slice 1 is in task 6.2.

## 1. Neutral wellness day view (design D1, D2)

- [ ] 1.1 [L3] Add `backend/performance/wellness_days.py` with the frozen `WellnessDay` view and the helpers `read_wellness_days`, `current_window`, `latest` and `series`. Move `wellness_day_values` and the wellness-day filter there from `canonical_sections.py`. Include `MetricKind.FORM` among the day kinds. Read each kind once through the unit's reader. Verify with a new `tests/test_performance_wellness_days.py`:
  - athlete-record and sport-scoped observations are excluded;
  - a form-only day is a day;
  - the window holds the 90 days ending on the latest day;
  - the history holds all days;
  - empty input gives no days;
  - provenance is kept per value.
- [ ] 1.2 [L3] Change `CanonicalPerformanceInputs`: replace `wellness_rows` and `history_wellness_rows` with `wellness_days` and `history_wellness_days`, and add `run_eftp_by_day`. Build them in `read_performance_inputs` without reading any snapshot wellness section. Derive the latest wellness day, `_activity_start`, the CTL ramp series and `form_by_day` from the days, and the run series from run-scoped wellness-day eFTP. Remove `_snapshot_rows` and `_raw_wellness_rows` if they are unused. Reduce `canonical_sections.py` to `compact_activity_rows`. Verify:
  - adapt `tests/test_performance_canonical_parity.py` (`_UNIT_READS`: every kind read once) and the successors of `tests/test_performance_canonical_sections.py`;
  - snapshot rows that contradict the observations, or add extra days, change nothing;
  - `None` inputs keep their current conditions.

## 2. Consumers on the view (design D3, D4)

- [ ] 2.1 [L3] Move `context.py`, `load_context.py` and `load.actual_atl_series` to the days and the ATL series. Remove the snapshot wellness reads in `context.py` (`_activities_and_wellness` keeps only the activity part). Read the subjective ratings from the latest day's `SUBJECTIVE_*` values. Verify in `tests/test_performance_load_context.py`, `tests/test_performance_load.py`, `tests/test_characterization_load_focus.py` and `tests/test_performance_context.py`:
  - unchanged golden values with canonical inputs;
  - unknown CTL, ATL and subjective ratings without canonical inputs;
  - an ATL seed day gap decays as before.
- [ ] 2.2 [L3] Move `comparisons.py`, `wellness.py` and `trends.py` to day series. Remove `trends._sport_info_setting` and every `sportInfo` key read. `intervals_performance_average` keeps `weight_kg` and `readiness` from the days, and `run_threshold_watts` from `run_eftp_by_day` with the existing bounds. Drop the snapshot fallback in `performance_trend_average`. Verify in `tests/test_performance_comparisons.py`, `tests/test_performance_trends.py` (or the existing trend tests) and `tests/test_performance_wellness.py`:
  - CTL/ATL 7-day and weight/readiness/run-eFTP 30-day averages match the former golden values;
  - `sportInfo` `ftp`/`lthr`/`vo2max`/pace keys give no average.
- [ ] 2.3 [L3] Move `current_metrics.py` to `latest_wellness: WellnessDay | None` for weight and body fat. Remove `_sport_info_setting`, the `wellness_ride` and `wellness_run` parameters and their fallback reads. Leave the athlete `sport_settings` reads (#1415). Verify in `tests/test_performance_current_metrics.py`, `tests/test_characterization_current_metrics.py` and `tests/test_performance_canonical_current_metrics.py`:
  - unchanged values for every source except the removed `sportInfo` fallbacks;
  - a test pins that `sportInfo` FTP, LTHR and VO2max no longer supply values.
- [ ] 2.4 [L2] Move `body._intervals_measurements` and `chart_history.py` to the history days (`WEIGHT`, `BODY_FAT`; the date and timestamp tuple from the observation, see design D4). Remove the snapshot wellness read `_wellness_records`. Verify in `tests/test_performance_body.py`, `tests/test_characterization_body_history.py`, `tests/test_performance_canonical_body_history.py` and `tests/test_performance_chart_history.py`:
  - the same weight and body-fat series and labels with canonical inputs;
  - empty series without them;
  - the timestamp matches the sync instant.

## 3. Neutral output keys and labels (design D5, D6, D7)

- [ ] 3.1 [L2] Rename the output keys in `context.py` (`recovery`, `source_freshness`, `thresholds`), `comparisons.py` and `load_context.py` as listed in the spec. Drop the `intervals_performance_fields` import from `context.py`. Verify in `tests/test_performance_context.py`, `tests/test_characterization_coach_context.py`, `tests/test_server_performance.py` and `tests/test_http_public_performance.py`:
  - a recursive key scan of the composed context finds none of `restingHR`, `sleepScore`, `rampRate`, `icu_ftp`, `icu_w_prime`, or a `hrv` key in `recovery` or `comparisons`;
  - each new key holds the former value and label.
- [ ] 3.2 [L2] Change the `personal_recovery._SERIES` measurement labels to `duration`, `resting`, `RMSSD` and `SDNN`, and drop the Garmin field-constant import there. Pass the stored `recent_wellness` rows from `context.py` for the sleep timing fallback (design D7). Verify in `tests/test_personal_recovery.py`, `tests/test_personal_recovery_coach_cases.py`, `tests/test_training_record_features.py` (tag impact) and `tests/test_performance_claim_wording.py`:
  - Garmin and Intervals.icu RMSSD stay two series;
  - SDNN is never pooled;
  - sleep timing values are unchanged with and without canonical sleep periods.
- [ ] 3.3 [L1] Update `e2e/analysis-info.spec.js` and `e2e/fixture_runtime.py` fixture labels (`lastNightAvg` and `restingHR` measurements become `RMSSD` and `resting`) and any assertion on the HRV heading. Verify with `npm run test:e2e -- e2e/analysis-info.spec.js` on the mobile and desktop projects.

## 4. Spec evidence and docs

- [ ] 4.1 [L1] Update the module docstrings of `canonical_inputs.py`, `canonical_sections.py`, `context.py` and `wellness_days.py` to describe the final reads. Replace the "to be recorded at implementation" evidence lines in the delta spec with the final test names. Verify by re-reading the docstrings against the code and running `npm run openspec -- validate neutral-wellness-read-shape --strict`.
- [ ] 4.2 [L1] Grep `README.md`, `docs/` and `openspec/specs/` for the renamed keys and the measurement labels, and update user-visible or contract statements outside this change's delta only where they name the old keys. Verify with a grep for `rampRate`, `restingHR`, `sleepScore`, `icu_ftp` and `lastNightAvg` that returns only provider, mapper, sync, fixture and archived-change hits.

## 5. Validation

- [ ] 5.1 [L1] Run the focused modules above, then:
  - `python -m unittest discover -s tests -v`
  - `python -m compileall -q server.py backend tests`
  - `ruff check`
  - repository-wide mypy, or the quality ratchet `python scripts/quality_baseline.py` if that is the repository's entry point

  Verify that all pass on the final tree, and that `git diff` shows no change under `backend/providers/`, `backend/sync/`, `public/` or the database schema.
- [ ] 5.2 [L1] Run `node --test tests/*.cjs` and the affected Playwright projects for `e2e/analysis-info.spec.js` (mobile-small, mobile, tablet, tablet-landscape, desktop). Verify with the command output.

## 6. OpenSpec and acceptance

- [ ] 6.1 [L1] Run the review gate per `deliver-issue` step 3 (repository `code-review`, depth=max, all findings) on the task commits and resolve the findings. Verify with the recorded review result.
- [ ] 6.2 [L1] Reconcile the #1413 slice-1 acceptance with evidence in the PR description:
  - Coach, API and UI show the same values and labels for synthetic data: parity tests from 1.2, 2.x and 3.1;
  - no performance reader reads wellness provider keys: tasks 1.2, 2.2, 2.3 and 2.4, plus a grep over `backend/performance` for `recent_wellness`, `sportInfo`, `restingHR`, `sleepSecs`, `ctLoad` and `bodyFat` (only `context.py`'s sleep-timing hand-off of `recent_wellness` remains, design D7);
  - the slice-2 items (guard, activity shape, PWA views) are named as pending in #1413.

## Workflow follow-up

- Sync the delta into `openspec/specs/performance-and-readiness/spec.md` and archive the change before the PR (deliver-issue step 4).
- After merge, start slice 2 (activity summary shape, `public_metrics`, PWA activity and plan views, field-name guard) as its own change.
- File the follow-up issue for the local planning record keys (`start_date_local`, `moving_time` of planned workouts, library and competitions) per the user decision of 2026-10-30.
