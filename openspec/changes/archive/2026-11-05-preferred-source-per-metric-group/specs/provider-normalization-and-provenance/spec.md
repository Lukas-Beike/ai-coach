## ADDED Requirements

### Requirement: Athlete-preferred source per metric group
The system SHALL let the athlete choose a preferred source (Garmin or Intervals.icu, or the default) per metric group (thresholds, weight and body fat, HRV, resting HR, sleep) as a local profile setting with receipt and undo (also through the Coach's profile update), and every consumer SHALL apply it in the same read: the preferred provider leads the group's order, behind a locally confirmed zone configuration.

#### Scenario: Preferred threshold source
- **WHEN** the athlete prefers Garmin for thresholds and Garmin and Intervals.icu report different current FTPs
- **THEN** the Coach context, current metrics and plan thresholds all use Garmin's FTP, and the Intervals.icu value stays an alternative with its conflict flag.

#### Scenario: Preferred recovery method
- **WHEN** the athlete prefers Intervals.icu for HRV
- **THEN** the current HRV, its averages and the planning days use only Intervals.icu values, while resting HR and sleep keep their own preferences; preferring Garmin never falls back to Intervals.icu except as a detected relay.

#### Scenario: Preferred body source
- **WHEN** the athlete prefers Intervals.icu for weight and body fat and Garmin has a newer measurement
- **THEN** the Intervals.icu value is current and Garmin's stays an alternative.

Evidence: `backend/performance/source_policy.py:preferences_from_profile`, `backend/performance/source_policy.py:source_order`, `backend/performance/source_policy.py:family_providers`, `backend/athlete/profile.py:normalize_profile`, `backend/performance/canonical_inputs.py:CanonicalPerformanceSource`; `tests/test_source_policy.py:PreferredSourceTests`, `tests/test_current_thresholds.py:PreferredSourceTests`, `tests/test_performance_display_sources.py:PreferredDisplayTests`, `tests/test_athlete_profile.py:test_preferred_sources_accept_known_providers_only`, `tests/test_change_history.py:test_preferred_sources_are_audited_and_older_rows_stay_matchable`, `tests/test_performance_recovery_context.py:test_an_intervals_preference_uses_only_its_values`.
