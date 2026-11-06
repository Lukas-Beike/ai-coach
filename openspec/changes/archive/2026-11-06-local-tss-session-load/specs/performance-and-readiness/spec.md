## ADDED Requirements

### Requirement: Local TSS-scale session load is a labelled model estimate
The system SHALL compute each canonical session's load with M6 `local-tss-load` v1 from its summary and the thresholds valid on its local day: power (NP/FTP, ride and run), then run pace, then heart rate (Banister TRIMP, 60 min at threshold HR = 100). It SHALL store the load, and the power IF, as derived observations owned by the session and SHALL NOT use a provider load or intensity.

#### Scenario: Garmin-only session with power
- **WHEN** a Garmin-only ride reports NP 230 W for 70 minutes and the FTP valid that day is 250 W
- **THEN** its summary serves `training_load` 98.75, `intensity` 92 and `load_branch` `power` with the source label `derived`, and the rollup sums it.

#### Scenario: Threshold valid only after the session
- **WHEN** no threshold is valid on the session day but a later one exists
- **THEN** the earliest later threshold is used and the value is flagged `threshold_after_session`.

#### Scenario: Changed input or method
- **WHEN** a session's inputs, its dated thresholds or the method version change, or the session is gone
- **THEN** the next stage pass rewrites only the values whose fingerprint changed and retires the values of gone sessions.

Detailed contract: thresholds follow `resolve_current_thresholds` per day with the policy's age limits; resting HR comes from the session day or up to 7 days earlier, Garmin first. Strength, yoga and alpine ski get no value; an IF above 2.0 is rejected. The pass runs as the last canonical backfill follow-up, triggered by worker start, completed sync jobs and committed local zone changes, and keeps content-free counts that diagnostics report as `local_load`.

Evidence: `backend/performance/local_tss.py`, `backend/sync/local_load.py`, `backend/sync/canonical_backfill_assembly.py`, `backend/sync/executor.py:SyncJobExecutor.run`, `backend/athlete/zones.py:ZoneConfigurationService`; `tests/test_local_tss.py`, `tests/test_local_load_store.py`, `tests/test_sync_executor.py`, `tests/test_zone_configuration_canonical.py`, `docs/performance-methods/m6-local-tss-load.md`.

## MODIFIED Requirements

### Requirement: Load rollups and actual-load reconstruction
The system SHALL calculate explicit current/previous 7- and 30-day completed-activity rollups and supported actual ATL reconstruction using known completed loads. It SHALL sum multiple known loads on the same day, decay the reconstructed series across gaps using its implemented model, and keep Intervals CTL/ATL/form separate from Garmin measured acute load. Activity-derived load SHALL not be presented as Garmin's device-reported acute load.

#### Scenario: Multiple sessions and rest days
- **WHEN** a day contains several completed loads and later days have no activity
- **THEN** rollups sum known contributions and actual ATL evolves through the implemented decay rather than copying a future planned load.

#### Scenario: Sessions without a TSS-scale load
- **WHEN** a rollup window holds sessions without a stored local TSS-scale load (M6), such as a strength session or a session without power, pace or heart-rate inputs
- **THEN** the rollup and the actual ATL report how many sessions were left out of the load sum, and the rollup reports their known session-RPE load in AU beside the sum, with the labels of its RPE sources, never added to it.

#### Scenario: Provider loads are not summed
- **WHEN** a session carries an Intervals.icu training load, a Wahoo TSS or a Garmin load
- **THEN** the rollup sums only the session's local load; the provider value stays on the summary as `provider_training_load` for cross-checking.

#### Scenario: Missing or conflicting Garmin acute load
- **WHEN** no dated valid measured acute-load value exists or device values conflict
- **THEN** Garmin acute-load history leaves the date unknown instead of reconstructing it from daily/chronic activity totals.

#### Scenario: Form comes from canonical observations
- **WHEN** the current load block is composed
- **THEN** `tsb` is the form observation of the latest wellness day (reported or derived as mapped); `tsb`, `form` and `freshness` of the snapshot wellness row are not read and the consumer does not derive CTL minus ATL itself.

#### Scenario: No form observation
- **WHEN** the latest wellness day has no form observation, including a reported form value that the mapper rejected as invalid, or no canonical inputs exist
- **THEN** `tsb` is unknown instead of a snapshot value or a consumer-side derivation.

Evidence: `backend/performance/load.py:activity_rollup`, `tests/test_performance_load.py:test_sessions_without_a_tss_scale_load_are_counted_with_their_rpe_load`, `tests/test_local_load_store.py`, `tests/test_intervals_mapping_parity.py:test_rollup_totals_match_the_mapped_records`, `backend/performance/load.py:actual_atl_series`, `backend/performance/load_context.py:performance_load_context`, `backend/performance/garmin_load.py:acute_load_value`; `tests/test_performance_load.py:test_actual_atl_decays_across_missing_days_and_is_sorted`, `tests/test_performance_chart_history.py:test_garmin_acute_load_is_dated_and_never_derived_from_daily_or_chronic_load`, `tests/test_performance_chart_history.py:test_acute_load_rejects_invalid_and_conflicting_device_values`. The form scenarios are verified by `tests/test_performance_canonical_load_metrics.py:FormTests`, `tests/test_performance_load_context.py:test_form_and_ramp_rate_come_from_the_canonical_inputs` and `tests/test_characterization_load_focus.py:test_carrier_form_fields_are_not_read_without_canonical_inputs`.

### Requirement: Released local methods are registered and shown the same in Coach and UI
Each Epic S local method SHALL be listed in the register below with its method id and version, statuses, limits and card. The Coach SHALL receive the value, status, method and period the UI shows for the same inputs; it MAY omit display-only arrays such as per-day history or chart points, but SHALL NOT recompute, round differently or relabel a value.

#### Scenario: Same inputs on both paths
- **WHEN** one set of canonical sessions, feedback, recovery observations and sleep periods is read by the public performance state, the analysis route, the Coach context and `get_training_report`
- **THEN** a full ISO week's session-RPE load, each recovery baseline, the sleep timing summary and the best-effort curve carry the same value, status, method and period on both paths.

#### Scenario: Large sleep timing history
- **WHEN** the sleep timing variability spans many nights
- **THEN** `get_training_report` returns the Coach context's summary plus each series' last 14 nights as the UI shows them, without the 84-night chart points, and reports the section as complete.

Detailed contract:

| Metric | Method id, version | Statuses | Limits | Card, review |
| --- | --- | --- | --- | --- |
| Session-RPE load (AU) | `session-rpe-load` v1 | `descriptive`, `insufficient_data` | AU is not TSS, provider load or TRIMP; no injury, readiness or ramp statement | M1, released |
| HRV, resting HR and sleep duration comparison | `personal-quartiles-v1` | `ok`, `provisional`, `insufficient_data` | own earlier values only, not a normal or clinical range | M2, M3, released |
| Sleep goal shortfall (last 7 nights) | inside the `personal-quartiles-v1` result, no own id | `ok`, `partial`; none without a 4–12 h goal | no sleep debt | M3, released |
| Sleep timing variability | `sleep-timing-variability-v2` | `ok`, `provisional`, `insufficient_data` | not the Sleep Regularity Index; no median or deviation below 14 earlier intervals | M3, released |
| Power and running best-effort curve | `mean-max-curve` v1 | `ok`, `insufficient_data`; per running point also `unknown` | observed bests only, no FTP, CP or pace estimate | M4 card |
| Critical Power and Critical Speed | `critical-power-speed` v1 | method `experimental`; per fit `ok`, `insufficient_data`, `withheld` | model estimate from the best 3/7/12-min efforts of 28 days; never FTP, threshold or zones | M4, released |
| Short- and long-term session-RPE load (AU) | `smoothed-session-load` v1 | `estimate`, `insufficient_data` | smoothed subjective load; no fitness, form, ratio, risk or provider comparison | M5, released |
| Session load and intensity factor (TSS scale) | `local-tss-load` v1 | stored per session with `load_branch` `power`, `pace` or `heart_rate`; none without inputs | branches are not equivalent; no fatigue, readiness or injury statement; IF = 1 is not a physiological threshold | M6, released |

Passive CP/CS, other TRIMP uses, further threshold or VO2max estimates, DFA-α1, W′ balance and HRV-based recommendations stay deferred. No observation phase has run.

Evidence: `docs/performance-methods/README.md`, `backend/coach/context.py:coach_performance_projection`, `backend/coach/context.py:coach_sleep_timing_projection`, `backend/coach/activity_read_tools.py:CoachActivityReadToolService.execute`; `tests/test_performance_coach_ui_parity.py`.
