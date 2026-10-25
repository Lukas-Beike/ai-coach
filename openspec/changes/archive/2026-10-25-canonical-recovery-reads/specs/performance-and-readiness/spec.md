## MODIFIED Requirements

### Requirement: Current and planning recovery sources
The system SHALL compose sleep duration/score, resting HR, HRV, readiness, supported averages, and planning day recovery with explicit source/date. Sleep/HRV/resting HR prefer supported Garmin values and readiness prefers eligible Intervals values. Per-day planning values SHALL use their date-specific source priority, preserve absent days, and include available saved/current morning Body Battery through its dedicated path. Source freshness SHALL distinguish measurement date from fetch time.

#### Scenario: Providers disagree on readiness
- **WHEN** eligible Intervals readiness and Garmin readiness coexist for the supported current/day context
- **THEN** the Intervals readiness path takes priority while Garmin remains available for its other supported recovery values.

#### Scenario: Recently fetched old measurement
- **WHEN** a source was fetched recently but its latest measurement is old or missing
- **THEN** source metadata reports measurement age/unknown status rather than treating the fetch time as proof of a current reading.

#### Scenario: Current recovery values come from canonical observations only
- **WHEN** the current performance context is composed
- **THEN** sleep duration/hours, sleep score, resting HR, HRV and readiness, their 7-day averages, source labels and Garmin measurement dates are derived only from canonical observations; values present only in the raw Garmin view or only in snapshot wellness carrier fields are not shown, and without canonical inputs these values are absent rather than read from provider data.

#### Scenario: Averages never mix providers
- **WHEN** a current recovery value is selected from one provider
- **THEN** its 7-day average uses only that provider's daily observations in the seven days ending on the current day, and a metric without a selected value averages the Intervals days.

#### Scenario: Garmin-only recovery without a wellness day
- **WHEN** no usable Intervals wellness day exists but Garmin recovery observations do
- **THEN** the Garmin values are still selected for the current recovery context and personal baselines.

Evidence: `backend/performance/recovery_context.py:performance_recovery_context`, `backend/performance/planning_recovery.py:planning_recovery_view`, `backend/performance/freshness.py:garmin_source_freshness`; `tests/test_performance_planning_recovery.py:test_intervals_values_keep_sources_and_garmin_priority`, `tests/test_performance_planning_recovery.py:test_saved_and_current_morning_body_battery`, `tests/test_performance_freshness.py:test_current_stale_partial_unknown_and_notes`, `tests/test_performance_recovery_context.py`, `tests/test_characterization_recovery.py`.

### Requirement: Personal recovery baselines and sleep deficit
The system SHALL form personal recovery distributions separately by provider and measurement method, exclude the current reading from its comparison baseline, require at least 14 prior matching nights for provisional classification and 28 for full classification, and leave stale/future evidence unclassified. RMSSD and SDNN SHALL not be pooled. Sleep deficit SHALL require an explicit valid sleep target, sum only known-night shortfalls, and never offset them with excess sleep on another night.

#### Scenario: Baseline coverage thresholds
- **WHEN** a current reading has 13, 14, or 28 prior matching nights
- **THEN** its classification is insufficient, provisional, or fully supported respectively, and the current reading does not shift the baseline median.

#### Scenario: Missing nights or sleep target
- **WHEN** fewer than seven recent nights are known or no explicit valid sleep target exists
- **THEN** deficit coverage is partial or no target-based deficit is produced; missing nights are not imputed.

#### Scenario: Baselines read daily canonical observations
- **WHEN** personal baselines and sleep deficits are computed, with or without an Intervals snapshot
- **THEN** each provider's daily sleep duration, resting HR, RMSSD and SDNN observations form the series, with the existing bounds and measurement labels; raw provider views are not read, and without canonical inputs no baseline is produced.

#### Scenario: Provider switch or gap
- **WHEN** the athlete's recovery data moves from one provider to another, a day is missing, or the newest value is older than yesterday
- **THEN** each provider keeps its own series, missing days are not filled from the other provider, and stale or insufficient series report the same insufficient/stale status as before.

Evidence: `backend/performance/personal_recovery.py:personal_recovery`; `tests/test_personal_recovery.py:test_coverage_and_excluding_current_value_from_baseline`, `tests/test_personal_recovery.py:test_future_stale_and_separate_hrv_methods_are_not_classified`, `tests/test_personal_recovery.py:test_deficit_uses_known_nights_and_never_offsets_with_long_sleep`.

### Requirement: Sleep timing and tagged-day associations
The system SHALL derive sleep regularity from validated dated onset/wake intervals with timezone/DST-aware duration and separate source/method series. It SHALL keep insufficient coverage explicit. Tagged-day analysis SHALL use only explicit boolean answers paired with the following provider-dated night, require ten measured days per comparison group, and label results as observed associations rather than causal effects or inferred answers.

#### Scenario: Sleep across midnight or DST
- **WHEN** valid sleep intervals cross midnight or a clock change
- **THEN** local timing comparisons use circular timing logic and actual interval duration while source/method series remain separate.

#### Scenario: Unanswered tag
- **WHEN** a day has no explicit tag answer or no measured following night
- **THEN** it is excluded from both groups rather than treated as a negative answer; insufficient groups expose no confident association statistic.

#### Scenario: Sleep timing input before canonical sleep periods
- **WHEN** sleep regularity is computed before canonical sleep periods exist (#1419)
- **THEN** onset and wake times are still read from the stored provider sleep and wellness records, as the only recovery input not yet read from canonical observations.

Evidence: `backend/performance/personal_recovery.py:sleep_regularity`, `backend/performance/tag_impact.py:tag_impact`; `tests/test_personal_recovery.py:test_sleep_regularity_circular_midnight_median_and_source_separation`, `tests/test_personal_recovery.py:test_sleep_intervals_reject_future_missing_and_reversed_and_keep_dst_duration`, `tests/test_training_record_features.py:test_tag_impact_requires_ten_measured_days_in_each_explicit_group`.

## ADDED Requirements

### Requirement: Weekly HRV is a labelled fallback
The system SHALL show a Garmin weekly HRV average as the current HRV only when no last-night RMSSD is selected, with a source label that names the weekly average and without a 7-day average. It SHALL never pool weekly and last-night values in one series.

#### Scenario: Only a weekly HRV average exists
- **WHEN** Garmin provides a weekly HRV average and no provider has a selectable last-night RMSSD
- **THEN** the HRV value is the weekly average, its source label states that it is a weekly average, and the HRV average is absent.

#### Scenario: Last-night RMSSD exists
- **WHEN** a last-night RMSSD is selectable from any provider
- **THEN** it is shown and the weekly average is not used.

### Requirement: Morning sleep readiness reads canonical sleep days
The manual morning check-in SHALL decide whether today's Garmin sleep is available from the latest canonical Garmin sleep observation day, combined with the Garmin source freshness, and SHALL not read sleep days from the raw Garmin view.

#### Scenario: Sleep observation for today exists
- **WHEN** a Garmin sleep duration or score observation exists for the check-in day and the sleep source is current or partial
- **THEN** the check-in proceeds.

#### Scenario: Only raw data has today's sleep
- **WHEN** the raw Garmin view has today's sleep but no canonical sleep observation exists for today
- **THEN** the check-in waits for sleep data.
