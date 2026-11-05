## MODIFIED Requirements

### Requirement: Current and planning recovery sources
The system SHALL compose sleep duration/score, resting HR, HRV, readiness, supported averages, and planning day recovery with explicit source/date. Sleep, HRV and resting HR SHALL keep one method family: Garmin's night values whenever an in-bounds Garmin value exists, with Intervals.icu values only when they relay Garmin's (equal within rounding on at least 90 % of at least 5 days with both), labelled as such; without any Garmin value, Intervals.icu values form the family. Readiness prefers eligible Intervals values. Per-day planning values SHALL use their date-specific source priority and the current rules' bounds, preserve absent days, and include available saved/current morning Body Battery through its dedicated path. Source freshness SHALL distinguish measurement date from fetch time.

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
- **WHEN** a current sleep, HRV or resting HR value is selected
- **THEN** its 7-day average uses only the daily values of its method family in the seven days ending on the current day; readiness averages only the selected provider's days, and a metric without a selected value averages the Intervals days.

#### Scenario: Another method never fills Garmin gaps
- **WHEN** Garmin night HRV exists and Intervals.icu holds HRV values that do not relay Garmin's, such as a morning reading
- **THEN** neither the current value nor any planning day takes the Intervals.icu value, and a newer Intervals.icu relay value of a lapsed Garmin sync is current under the label "Intervals.icu Wellness (Garmin)".

#### Scenario: Garmin-only recovery without a wellness day
- **WHEN** no usable Intervals wellness day exists but Garmin recovery observations do
- **THEN** the Garmin values are still selected for the current recovery context and personal baselines.

Evidence: `backend/performance/source_policy.py:family_providers`, `backend/performance/recovery_context.py:performance_recovery_context`, `backend/performance/planning_recovery.py:planning_recovery_view`, `backend/performance/freshness.py:garmin_source_freshness`; `tests/test_source_policy.py:MethodFamilyTests`, `tests/test_planning_canonical_recovery.py:CanonicalPlanningRecoveryTests.test_a_relay_fills_garmin_gaps_with_its_own_label`, `tests/test_performance_planning_recovery.py:test_saved_and_current_morning_body_battery`, `tests/test_performance_freshness.py:test_current_stale_partial_unknown_and_notes`, `tests/test_performance_recovery_context.py`, `tests/test_characterization_recovery.py`.
