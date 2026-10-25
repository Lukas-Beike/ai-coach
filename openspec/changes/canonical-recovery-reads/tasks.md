# Tasks

## 1. Weekly HRV kind (design D5)

- [ ] 1.1 Add the weekly HRV kind:
  - `MetricKind.HRV_WEEKLY_AVERAGE` with its unit in `backend/canonical/vocabulary.py`;
  - its bounds in `backend/canonical/validation.py`;
  - `GARMIN_HRV_WEEKLY_ALIASES` in `backend/providers/garmin_fields.py`, reused by `garmin_performance_fields.py`;
  - a Garmin-only current rule with bounds 1–300 in `source_policy.CURRENT_RULES`;
  - the kind in `backend/diagnostics/canonical_counts.py`.

  Verify with `tests/test_canonical_vocabulary.py`, `tests/test_source_policy.py` and the canonical count tests.
- [ ] 1.2 Map the weekly average in the Garmin `hrv` group (`PROVIDER_REPORTED`) and bump `garmin_health_mapping.MAPPER_VERSION` to 11. Extend `tests/test_garmin_health_mapping.py:test_hrv_prefers_last_night_and_ignores_weekly_average`: a weekly-only payload yields no RMSSD and one `hrv_weekly_average` observation, and a last-night payload yields both kinds. Run the canonical plan and backfill tests, so stored Garmin health records reproject on the version change.

## 2. Canonical recovery input (design D1)

- [ ] 2.1 Replace the recovery input types with the single `CanonicalRecoveryInputs` (observations by kind plus the latest wellness day) and `read_recovery_inputs(reader, db, *, as_of, latest_wellness_day)`. Remove `canonical_recovery_averages.py` and `canonical_personal_recovery.py` and fold the reads into it. Update `CanonicalPerformanceInputs` and `read_performance_inputs` so recovery inputs are read with and without a latest wellness day. Verify by updating `tests/test_performance_canonical_recovery.py` and `tests/test_performance_canonical_parity.py`:
  - each kind is read once per unit (the `_UNIT_READS` count is adjusted for the new kinds);
  - the window starts 83 days before `as_of`;
  - Garmin observations are present without a wellness day.

## 3. Current recovery values (design D2)

- [ ] 3.1 Rewrite `backend/performance/recovery_context.py:performance_recovery_context(recovery, today)` to use canonical observations only, as specified in D2, including the weekly HRV fallback label and the single-provider averages. Update its caller `backend/performance/context.py`. Verify:
  - `tests/test_performance_recovery_context.py` and the `RecoveryContextPrecedenceTests` in `tests/test_characterization_recovery.py`, migrated to the D7 mapper helper, keep their expectations except for commented intended differences;
  - new tests cover weekly HRV only, RMSSD plus weekly, None inputs (all values None) and Garmin-only data without a wellness row.
- [ ] 3.2 Pass canonical inputs to `_unavailable_context` in `backend/performance/context.py`. Verify in `tests/test_performance_context.py` that a missing Intervals snapshot with Garmin observations yields Garmin baselines, and that no raw Garmin view is read for them.

## 4. Personal baselines (design D3)

- [ ] 4.1 Build the `personal_recovery` groups from the canonical daily observations with the D3 label table. Remove `_add_garmin_records` and `_prefer_canonical_resting_hr`. Mark `sleep_regularity` as the remaining raw-input path until #1419. Verify by migrating `tests/test_personal_recovery.py` and `PersonalRecoveryGarminTests` to the D7 helper, with expectations unchanged. Add tests for:
  - a provider switch (separate series, no filling);
  - a missing day;
  - a stale newest value;
  - RMSSD and SDNN separation;
  - `canonical=None` producing no baselines.

## 5. Morning check-in (design D4)

- [ ] 5.1 Make `GarminSleepObservations` required in `backend/coach/morning.py` and always pass it from `backend/coach/local_assembly.py`. Remove the snapshot-day default from `garmin_observations.garmin_sleep_ready_for_checkin` if no other caller remains. Verify in `tests/test_coach_manual_morning.py`, `tests/test_coach_local_assembly.py` and `tests/test_garmin_observations.py` that today's raw sleep without an observation waits, and that an observation for today with current or partial freshness proceeds.

## 6. Cleanup and documentation (design D6)

- [ ] 6.1 Remove the unused helpers listed in D6 and update the module docstrings (`canonical_inputs.py`, `source_policy.py`, `garmin_health_mapping.py`). Verify with `python -m compileall -q server.py backend tests`, repository-wide mypy and a grep showing no remaining callers.
- [ ] 6.2 Check `README.md` and `docs/performance-methods/` for wording about recovery sources or weekly HRV, and update any user-visible behavior description. Verify with a grep for `hrvWeeklyAvg`, `Wochenmittel` and the recovery source wording.

## 7. Validation

- [ ] 7.1 Run the focused modules, then `python -m unittest discover -s tests -v`, `python -m compileall -q server.py backend tests`, repository-wide mypy and the quality ratchet. Run the e2e projects that read performance or recovery (`e2e/analysis-info.spec.js`) if any fixture expectation changes.
- [ ] 7.2 Run `npm run openspec -- validate canonical-recovery-reads --strict` and reconcile every acceptance criterion of #1411 with evidence.
