## MODIFIED Requirements

### Requirement: Provider-aware time and sport normalization
The system SHALL preserve explicit instants, date each activity on the day it was lived using the UTC offset the provider reports for it and otherwise the active athlete timezone, normalize supported sports and indoor/outdoor/virtual environments, and apply the implemented wall-time DST rules to local timestamps. Intervals SHALL prefer an aware `start_date` over local wall time, while a naive absolute start alone is insufficient.

#### Scenario: DST overlap or gap
- **WHEN** provider local wall time lies in a DST overlap or spring gap
- **THEN** canonical localization uses the first overlap occurrence or the implemented forward-gap interpretation and retains a valid aware instant.

#### Scenario: Unknown workout type
- **WHEN** a Wahoo workout has an unrecognized type identifier
- **THEN** it maps to other sport and unknown environment rather than claiming a known activity type.

#### Scenario: Trail runs since Garmin mapper version 10
- **WHEN** a Garmin activity has type `trail_running` or `obstacle_run`, or an Intervals.icu activity has type `TrailRun`
- **THEN** it maps to an outdoor run, the only outdoor run of those two providers, so the session analyses (decoupling, pace at heart rate) leave it out as a trail run; Wahoo outdoor runs stay ordinary runs, and treadmill and virtual runs count as flat for pace at heart rate (method `pace-at-heart-rate-v2`), never grade-adjusted by a course altitude.

#### Scenario: Activity recorded abroad
- **WHEN** an athlete with profile zone Europe/Berlin records a run at 06:30 in Tokyo, reported by Garmin (`startTimeLocal` nine hours after `startTimeGMT`), by Intervals.icu (`timezone` Asia/Tokyo with an exact `start_date`) or by Wahoo (`time_zone` Asia/Tokyo)
- **THEN** the activity, its session, `started_at_local` and every week or plan read are dated on the Tokyo day at 06:30, not on the previous Berlin day.

#### Scenario: Profile zone change
- **WHEN** the athlete changes the profile zone and stored records are reprojected
- **THEN** activities with their own offset keep their date and wall time, and only activities without one follow the new zone.

#### Scenario: No provider offset
- **WHEN** a provider reports no usable offset (no exact start, a non-IANA zone name, or an offset beyond +-14 hours or off the quarter hour)
- **THEN** the activity is dated in the athlete zone as before.

Detailed contract: Wahoo's naive `starts` SHALL be interpreted as UTC. The offset is stored as `local_offset_minutes` in the activity record's details; a session uses its primary record's offset, else that of the first record reporting one. A summary carrying an offset keeps its own `started_at_local` date even when a reader converts to the athlete zone.

Evidence: `backend/canonical/local_time.py:localize_wall_time`, `backend/canonical/local_time.py:wall_time`, `backend/canonical/local_time.py:wall_clock_offset_minutes`, `backend/canonical/local_time.py:zone_offset_minutes`, `backend/providers/intervals_activity_mapping.py:map_intervals_activities`, `backend/providers/garmin_activity_mapping.py:map_garmin_activities`, `backend/providers/wahoo_activity_mapping.py:WAHOO_WORKOUT_TYPES`, `backend/providers/garmin_activity_mapping.py:GARMIN_ACTIVITY_TYPES`, `backend/activities/detail_contract.py:session_local_start`, `backend/canonical/activity_summary.py:summary_local_date`, `backend/performance/analysis_input.py:analysis_sport`, `backend/performance/pace_at_hr.py:pace_at_heart_rate`; `tests/test_activity_local_offset.py`, `tests/test_garmin_activity_mapping.py:test_only_off_road_runs_are_outdoor_runs`, `tests/test_pace_at_hr.py:test_indoor_and_virtual_runs_ignore_course_altitude`, `tests/test_analysis_input.py:test_garmin_outdoor_runs_are_trail_runs`, `tests/test_pace_at_hr.py:test_outdoor_run_without_terrain_is_unknown_but_indoor_is_flat`, `tests/test_intervals_activity_mapping.py:test_aware_start_date_wins_over_local_wall_time`, `tests/test_intervals_activity_mapping.py:test_naive_start_date_alone_drops_the_record`, `tests/test_wahoo_activity_mapping.py:test_start_without_an_offset_is_read_as_utc`, `tests/test_wahoo_activity_mapping.py:test_local_date_follows_the_athlete_zone`, `tests/test_wahoo_activity_mapping.py:test_the_workouts_own_time_zone_dates_it_where_it_was_recorded`.

### Requirement: Canonical sleep periods
Canonical sleep periods SHALL retain aware UTC start/end, local wake date, night/unknown kind, reported duration and provenance, and the ingest timezone only when it gives that wake date. The wake date SHALL be the provider's own day (Garmin `calendarDate`, the Intervals.icu wellness day) when it lies within a day of the end's UTC date, else the end's date in the ingest zone. Invalid or reversed periods SHALL be rejected. Periods from different providers SHALL remain separate.

#### Scenario: Midnight and DST
- **WHEN** a valid period crosses midnight or a DST transition
- **THEN** its instants preserve actual duration and its assigned date is the wake date in the recorded timezone.

#### Scenario: Missing nights and overlapping providers
- **WHEN** nights are missing or two providers overlap
- **THEN** no missing night is fabricated and provider periods are not silently merged.

#### Scenario: Garmin main sleep during daytime
- **WHEN** Garmin identifies a period as its main daily sleep episode, including daytime sleep for a shift worker
- **THEN** its canonical kind is NIGHT, meaning main sleep rather than a clock-night classification; arbitrary periods are not classified by hour or duration.

#### Scenario: Travel night
- **WHEN** the athlete wakes at 06:00 in Tokyo with profile zone Europe/Berlin and Garmin files the night under that Tokyo day
- **THEN** the period's wake date is the Tokyo day, the same day as the morning run recorded there, and it keeps no timezone because Berlin names another day.

Evidence: `backend/providers/sleep_period_mapping.py:map_sleep_periods`, `backend/canonical/domain_records.py:SleepPeriod`; `tests/test_sleep_period_mapping.py`, `tests/test_activity_local_offset.py:TravelDaySleepTests`.
