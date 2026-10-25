## MODIFIED Requirements

### Requirement: Health and body unit normalization
The system SHALL normalize Garmin sleep duration/score, last-night RMSSD, weekly HRV average, resting HR, readiness, body measurements, daily counts/energy, VO2max, thresholds, predictions, and endurance score using supported aliases and plausible bounds. Weekly HRV SHALL not stand in for a last-night reading. Declared grams/pounds/kilograms SHALL convert to kg, body-fat fractions to percent, with bounded fallback magnitude interpretation only for undeclared units.

#### Scenario: Declared weight unit
- **WHEN** a valid Garmin weigh-in explicitly declares pounds or grams
- **THEN** canonical weight is converted once to kilograms and its dated provenance is retained.

#### Scenario: Different HRV windows
- **WHEN** a payload has only a weekly HRV average and no last-night value
- **THEN** the canonical last-night observation stays absent rather than borrowing the weekly statistic, and the weekly average is stored as its own weekly HRV observation.

#### Scenario: Stored Garmin health records after the weekly HRV mapping
- **WHEN** the Garmin health mapper version changes to add the weekly HRV kind
- **THEN** stored Garmin health records are reprojected through the existing canonical backfill without a provider refetch, schema change or remote write.

Detailed contract: Zero SHALL remain valid for sleep score, steps, floors, and active energy where implemented, while absent or invalid measurements remain unknown.

Evidence: `backend/providers/garmin_health_mapping.py:map_garmin_health`, `backend/providers/intervals_wellness_mapping.py:map_intervals_wellness`; `tests/test_garmin_health_mapping.py:test_weight_converts_declared_units_to_kilograms`, `tests/test_garmin_health_mapping.py:test_hrv_prefers_last_night_and_ignores_weekly_average`, `tests/test_garmin_health_mapping.py:test_zero_sleep_score_is_kept`, `tests/test_garmin_health_mapping.py:test_daily_stats_map_counts_and_energy_with_units`.
