## RENAMED Requirements

- FROM: `### Requirement: Personal recovery baselines and sleep deficit`
- TO: `### Requirement: Personal recovery comparison and sleep goal shortfall`

## MODIFIED Requirements

### Requirement: Personal recovery comparison and sleep goal shortfall
The system SHALL form personal recovery distributions separately by provider and measurement method, exclude the current reading from its comparison distribution, require at least 14 prior matching nights for provisional classification and 28 for full classification, and leave stale/future evidence unclassified. RMSSD and SDNN SHALL not be pooled. The quartile range is a comparison with the athlete's own earlier values (method `personal-quartiles-v1`); it SHALL not be described as a normal, healthy, abnormal or clinical range, and a position below or above it SHALL not be described as an alarm or deficiency. The 14/28-night thresholds, the 42-day window and the status `ok` are product rules and SHALL not be presented as validity, confirmation or a health standard. The sleep goal shortfall SHALL require an explicit valid sleep target, sum only known-night shortfalls against that target, and never offset them with excess sleep on another night; it SHALL not be called sleep debt or presented as a recovery need.

#### Scenario: Baseline coverage thresholds
- **WHEN** a current reading has 13, 14, or 28 prior matching nights
- **THEN** its classification is insufficient, provisional, or fully supported respectively, and the current reading does not shift the comparison median.

#### Scenario: Missing nights or sleep target
- **WHEN** fewer than seven recent nights are known or no explicit valid sleep target exists
- **THEN** shortfall coverage is partial or no target-based shortfall is produced; missing nights are not imputed.

#### Scenario: Baselines read daily canonical observations
- **WHEN** personal comparisons and the sleep goal shortfall are computed, with or without an Intervals snapshot
- **THEN** each provider's daily sleep duration, resting HR, RMSSD and SDNN observations form the series, with the existing bounds and measurement labels; raw provider views are not read, and without canonical inputs no comparison is produced.

#### Scenario: Provider switch or gap
- **WHEN** the athlete's recovery data moves from one provider to another, a day is missing, or the newest value is older than yesterday
- **THEN** each provider keeps its own series, missing days are not filled from the other provider, and stale or insufficient series report the same insufficient/stale status as before.

#### Scenario: Quartile position is a comparison, not a norm
- **WHEN** a recovery value lies below or above the quartile range of the athlete's earlier values
- **THEN** every API, UI and Coach text describes it as a position relative to the athlete's own earlier values, states that the middle two quartiles hold about half of the values, and derives no diagnosis, training clearance or training change from it.

#### Scenario: Product rules are not validity claims
- **WHEN** a comparison is provisional, `ok`, insufficient or stale
- **THEN** the displayed state names the coverage or reason (for example fewer than 14 earlier nights or an outdated measurement) and the recovery UI shows no "confirmed" or equivalent validity wording for it.

#### Scenario: Shortfall is not sleep debt
- **WHEN** the sleep goal shortfall is reported or summarized
- **THEN** it is worded as the sum of known shortfalls against the athlete's own sleep goal over known nights, with missing nights and unrecorded naps noted as limits, and no output uses the term sleep debt or states a needed number of hours of recovery sleep.

Evidence: `backend/performance/personal_recovery.py:personal_recovery`, `public/analysis.js:recoveryReferenceLabel`; `tests/test_personal_recovery.py:test_coverage_and_excluding_current_value_from_baseline`, `tests/test_personal_recovery.py:test_future_stale_and_separate_hrv_methods_are_not_classified`, `tests/test_personal_recovery.py:test_deficit_uses_known_nights_and_never_offsets_with_long_sleep`; wording and Coach cases in `tests/test_performance_claim_wording.py` and `tests/test_personal_recovery_coach_cases.py`; `e2e/analysis-info.spec.js` recovery scenarios. Claim lists: `docs/performance-methods/m2-hrv-resting-hr.md`, `m3-sleep-duration-timing.md`.

### Requirement: Sleep timing and tagged-day associations
The system SHALL derive sleep timing variability (method `sleep-timing-variability-v1`) from validated dated onset/wake intervals with timezone/DST-aware duration and separate source/method series. The method compares each night's clock times circularly with the athlete's own earlier nights; it is not the Sleep Regularity Index and SHALL NOT be named, labelled or described as such, and no output SHALL share that name. It SHALL keep insufficient coverage explicit. Tagged-day analysis SHALL use only explicit boolean answers paired with the following provider-dated night, require ten measured days per comparison group, and label results as observed associations rather than causal effects or inferred answers.

#### Scenario: Sleep across midnight or DST
- **WHEN** valid sleep intervals cross midnight or a clock change
- **THEN** local timing comparisons use circular timing logic and actual interval duration while source/method series remain separate.

#### Scenario: Unanswered tag
- **WHEN** a day has no explicit tag answer or no measured following night
- **THEN** it is excluded from both groups rather than treated as a negative answer; insufficient groups expose no confident association statistic.

#### Scenario: Sleep timing input before canonical sleep periods
- **WHEN** sleep timing variability is computed before canonical sleep periods exist (#1419)
- **THEN** onset and wake times are still read from the stored provider sleep and wellness records, as the only recovery input not yet read from canonical observations.

#### Scenario: Timing variability is not the Sleep Regularity Index
- **WHEN** the timing variability result, its Coach report section or any description of it is produced
- **THEN** the method id and section name are `sleep-timing-variability-v1` and `sleep_timing_variability`, the Sleep Regularity Index or SRI appears only in a sentence that denies the equivalence, and the unchanged fields `regularity` and `*_deviation_minutes` carry the same values as before the rename.

Evidence: `backend/performance/personal_recovery.py:sleep_timing_variability`, `backend/performance/tag_impact.py:tag_impact`; `tests/test_personal_recovery.py:test_sleep_timing_variability_circular_midnight_median_and_source_separation`, `tests/test_personal_recovery.py:test_sleep_intervals_reject_future_missing_and_reversed_and_keep_dst_duration`, `tests/test_training_record_features.py:test_tag_impact_requires_ten_measured_days_in_each_explicit_group`, `tests/test_performance_claim_wording.py`.

### Requirement: Claim lists bound physiological statements
API, UI and Coach output SHALL NOT make statements that the method's card forbids. A physiological interpretation SHALL stay blocked until the independent review recorded on its card releases it; descriptive statements that the card allows MAY be shown before that review.

#### Scenario: Interpretation not yet reviewed
- **WHEN** a card records the interpretation as `blocked`
- **THEN** the method is limited to the card's descriptive statements, and no training clearance, diagnosis or model-based recommendation is derived from it.

#### Scenario: Reviewed interpretation
- **WHEN** the card records `released` with date and reviewer for an interpretation
- **THEN** implementations may present exactly the allowed statements for it, with the card's limits and status.

#### Scenario: Recovery wording is enforced at runtime
- **WHEN** the runtime sources and outputs of the personal recovery comparison, sleep goal shortfall and sleep timing variability are scanned
- **THEN** none contains a term the M2 or M3 card forbids (sleep debt, normal range, abnormal or clinical quartile positions, the Sleep Regularity Index as a name), and the scan fails with the file, line and term otherwise.

Evidence: claim lists in `docs/performance-methods/m1-session-rpe-load.md`, `m2-hrv-resting-hr.md`, `m3-sleep-duration-timing.md`, `m4-critical-power-speed.md`. Runtime enforcement for M2 and M3 wording: `tests/test_performance_claim_wording.py`; the remaining methods are enforced by their work packages (#1427–#1431).
