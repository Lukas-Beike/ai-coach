## ADDED Requirements

### Requirement: Daily wellness values are read through a provider-neutral day view
The system SHALL read every daily wellness value of the performance projection from canonical Intervals.icu wellness-day observations, identified by metric kind and keeping each observation's provenance. Performance readers SHALL NOT read snapshot wellness rows or Intervals.icu wellness field names for these values. Without canonical inputs these values SHALL be absent.

#### Scenario: Canonical days without snapshot rows
- **WHEN** canonical wellness-day observations exist and the snapshot holds no wellness rows
- **THEN** `current_load.ctl`, `current_load.atl`, `actual_load`, `comparisons.fitness_ctl`, `comparisons.fatigue_atl`, `metrics.weight_kg`, `metrics.body_fat_pct`, the subjective ratings in `recovery`, `comparisons.weight_kg_30d` and the body history weight and body-fat series equal the values computed before this change from equivalent snapshot rows.

#### Scenario: Snapshot rows contradict the observations
- **WHEN** snapshot wellness rows carry different CTL, ATL, weight, body fat, readiness, subjective or `sportInfo` values than the observations, or carry days without observations
- **THEN** only the observations decide the values and the latest wellness day; snapshot-only days and fields have no effect.

#### Scenario: No canonical inputs
- **WHEN** the performance context is composed without canonical inputs
- **THEN** CTL, ATL, weight and body fat from wellness, subjective ratings, wellness-based trend averages and wellness body history are unknown instead of read from the snapshot. Sources other than wellness keep their behaviour.

#### Scenario: Sport-scoped and athlete-record observations
- **WHEN** athlete-record observations (thresholds, athlete weight) or sport-scoped wellness observations exist
- **THEN** they do not become daily wellness values; only the run-scoped wellness-day eFTP feeds the 30-day running threshold-power average.

Detailed contract: the daily wellness values are CTL, ATL, form, weight, body fat, readiness, the subjective fatigue, soreness, stress and mood ratings, and the run eFTP of the trend averages. The snapshot rows not read are `recent_wellness` and `raw_provider_data.wellness`. The current-day window is the 90 days ending on the latest wellness day. The history view covers every stored wellness day.

Evidence: `backend/performance/wellness_days.py:read_wellness_days`, `backend/performance/canonical_inputs.py:read_performance_inputs`; `tests/test_performance_wellness_days.py:WellnessDayTests`, `tests/test_performance_canonical_sections.py:SectionHelperTests` and `SectionReadTests`, `tests/test_performance_canonical_parity.py:CanonicalLoadEdgeTests`, `tests/test_performance_context.py:PerformanceContextTests`, and `tests/test_performance_canonical_body_history.py:CanonicalBodyLedgerCaseTests`.

### Requirement: Wellness `sportInfo` threshold fallbacks are not read
The system SHALL NOT read cycling or running FTP, LTHR, maximum heart rate, VO2max, threshold pace or Zone-2 pace from Intervals.icu wellness `sportInfo` entries. These values SHALL come only from their remaining sources: Garmin, athlete sport settings, the athlete record, Wahoo and the manual profile. The 30-day `run_threshold_watts` average SHALL read the run-scoped wellness-day eFTP observations, bounded as before.

#### Scenario: `sportInfo` carries threshold keys
- **WHEN** a stored wellness row's `sportInfo` entry carries `ftp`, `lthr`, a maximum heart rate, `vo2max`, `threshold_pace` or a Zone-2 pace
- **THEN** none of them supplies a current metric or a 30-day average.

#### Scenario: Run eFTP average
- **WHEN** run eFTP wellness-day observations exist in the 30 days ending on the current day and the current `run_threshold_watts` has an Intervals.icu source
- **THEN** `comparisons.run_threshold_watts_30d` averages those observations as the snapshot `sportInfo` run eFTP average did; days without an observation are not filled.

Detailed contract: the Intervals.icu wellness `sportInfo` entry provides the sport type, CTL, ATL, eFTP, W′ and Pmax (`tests/fixtures/providers/intervals/wellness.json`); the removed keys are not part of it. No live payload was inspected (evidence gap).

Evidence: `backend/performance/current_metrics.py:current_performance_metrics`, `backend/performance/trends.py:intervals_performance_average`; `tests/test_characterization_current_metrics.py:CurrentThresholdTests.test_wellness_sport_info_ftp_does_not_supply_cycling_ftp`, `tests/test_characterization_current_metrics.py:CurrentMaxHrTests.test_out_of_range_setting_does_not_read_wellness_sport_info`, `tests/test_performance_trends.py:IntervalsPerformanceAverageTests.test_wellness_values_and_run_eftp_are_bounded_and_sport_info_thresholds_absent`, `tests/test_performance_wellness_days.py:WellnessDayTests.test_run_eftp_is_a_separate_sparse_series`.

### Requirement: Performance context output keys are provider-neutral
The current performance context returned to the Coach and through HTTP SHALL name its recovery, comparison, load and threshold values with provider-neutral keys and SHALL NOT emit the former provider-shaped keys. Values, units and source labels SHALL stay unchanged.

#### Scenario: Same data before and after
- **WHEN** the same synthetic canonical data is projected before and after this change
- **THEN** every renamed key holds the value and source label of its former key, and every other key of the context is unchanged.

#### Scenario: Coach context
- **WHEN** the Coach context includes the current performance section
- **THEN** it carries the neutral keys and none of the former keys.

Detailed contract: the neutral keys are
- `recovery.resting_hr_bpm`, `recovery.hrv_ms` and `recovery.sleep_score`, each with a matching `*_source` key and matching `recovery.source_freshness` keys;
- `comparisons.resting_hr_bpm` and `comparisons.hrv_ms`;
- `current_load.ramp_rate` and `current_load.ramp_rate_source`;
- `thresholds.ftp_w` and `thresholds.w_prime_j`.

They replace `restingHR`, `hrv`, `sleepScore`, `rampRate`, `rampRate_source`, `icu_ftp` and `icu_w_prime`.

Evidence: `backend/performance/context.py:current_performance_context`, `backend/performance/comparisons.py:performance_comparisons`, `backend/performance/load_context.py:performance_load_context`; `tests/test_performance_context.py:PerformanceContextTests.test_composed_context_has_only_neutral_performance_keys`, `tests/test_characterization_coach_context.py`, `tests/test_server_performance.py`.

### Requirement: Personal recovery measurement labels name the method
Personal recovery baselines, sleep goal shortfalls and tag-impact reports SHALL label their measurement with a provider-neutral method name: `duration` for sleep duration, `resting` for resting heart rate, and `RMSSD` or `SDNN` for HRV. They SHALL NOT use a provider field name such as `lastNightAvg`, `sleepSecs`, `sleepTimeSeconds`, `restingHR` or `restingHeartRate`. Series SHALL remain separated by provider and method, and RMSSD and SDNN SHALL not be pooled.

#### Scenario: Garmin and Intervals.icu HRV
- **WHEN** Garmin nightly HRV and Intervals.icu RMSSD observations both exist
- **THEN** both baselines are labelled `RMSSD`, stay two series distinguished by their source label, and the HRV chart heading shows `RMSSD` after the source.

Evidence: `backend/performance/personal_recovery.py:personal_recovery`, `backend/performance/tag_impact.py:tag_impact`; `tests/test_personal_recovery.py:PersonalRecoveryTests`, `tests/test_characterization_recovery.py`, `tests/test_training_record_features.py`, `e2e/analysis-info.spec.js`.

## MODIFIED Requirements

### Requirement: Ramp rate is a labelled local derivation
The system SHALL derive the ramp rate of the current load block as the latest wellness day's CTL minus the CTL of exactly seven days earlier, rounded to two decimals, from canonical Intervals.icu wellness-day CTL observations, and SHALL label it as derived through `current_load.ramp_rate_source`. Intervals.icu's own `rampRate` is not read and can differ from the derived number.

#### Scenario: Both days present
- **WHEN** CTL observations exist for the latest wellness day (58.4) and for seven days earlier (54.1)
- **THEN** `current_load.ramp_rate` is 4.3 and `current_load.ramp_rate_source` is `Intervals.icu CTL (berechnet)`.

#### Scenario: A day is missing
- **WHEN** either CTL day is absent, even though a neighbouring day exists
- **THEN** `ramp_rate` and `ramp_rate_source` are unknown; exact days only, no neighbouring day is substituted and nothing is interpolated.

#### Scenario: Snapshot ramp rate present
- **WHEN** the snapshot wellness row carries its own `rampRate` while the derivation inputs are present or absent
- **THEN** the snapshot value is ignored and only the derived value, or unknown, is shown.

#### Scenario: No wellness day or no canonical inputs
- **WHEN** there is no wellness day or no canonical performance inputs exist
- **THEN** `ramp_rate` and `ramp_rate_source` are unknown and the other load keys keep their behaviour.

Evidence: none for existing behavior (the legacy path passes the snapshot `rampRate` through: `backend/performance/load_context.py:performance_load_context`). Verified by `tests/test_performance_canonical_load_metrics.py:RampRateTests`, `tests/test_performance_load_context.py` and `tests/test_performance_canonical_parity.py`.

### Requirement: Cycling eFTP and form are read from canonical observations only
The system SHALL read cycling eFTP and form only from canonical Intervals.icu observations: the ride-scoped eFTP of the athlete record and of wellness days, and wellness-day form. Activity rows supply only the activity eFTP step. Without canonical inputs these values SHALL be absent rather than read from snapshot wellness rows or sport settings. Values and source labels stay unchanged. Output keys follow the provider-neutral output key requirement.

#### Scenario: No snapshot rows
- **WHEN** the snapshot has no wellness rows and no athlete sport settings but canonical observations exist
- **THEN** `metrics.cycling_eftp_watts`, `comparisons.cycling_eftp_30d`, `current_load.tsb` and `comparisons.form_tsb` equal the values computed from equivalent snapshot rows, apart from the known limits below.

#### Scenario: Carrier fields are ignored
- **WHEN** snapshot wellness rows still carry `tsb`, `rampRate` and `sportInfo`
- **THEN** none of them influences these values.

#### Scenario: Stale and multi-sport data
- **WHEN** the newest wellness day has no eFTP observation, or Run settings coexist with Ride settings
- **THEN** the current eFTP falls to the next step of its chain and the history keeps the older dated values; Run values never feed cycling eFTP.

Detailed contract: these are known limits, not requirements. They are tracked by a follow-up issue, and the wellness mapper version 7 of Epic B did not change them.
- The mapper stores the last of two ride sport settings; the legacy reader took the first.
- A setting or `sportInfo` entry is classified by `types[0]` or `type` only. Entries identified solely by `sport` or `sport_type`, or by a later `types` entry, yield no eFTP.
- A reported form value that is not a number yields no form for that day.

Evidence: `backend/providers/intervals_wellness_mapping.py:map_intervals_wellness`, `backend/providers/intervals_wellness_mapping.py:map_intervals_athlete_thresholds`; `tests/test_intervals_wellness_mapping.py` (EFTP and FORM mapping), `tests/test_performance_canonical_parity.py`. The strict-read scenarios are verified by `tests/test_performance_canonical_load_metrics.py` (carrier rows are stripped or contradicting), `tests/test_performance_canonical_parity.py:_assert_load_metric_split` and `tests/test_server_performance.py`.
