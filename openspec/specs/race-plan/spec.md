# race-plan Specification

## Purpose
Turn a stored target competition into a read-only race plan for the day itself:
pacing per section, carbohydrates before and during the race, each value with
its source, computed from local data only.

## Requirements

### Requirement: RP1 Read-only race plan of one competition
The system SHALL compute the race plan of one stored competition on request from the competition record, the body weight the nutrition ranges use (resolved metric, else the profile value) and the fuelling rules, without storing anything, calling a provider or changing sync state. An unknown competition id SHALL answer 404 `competition_not_found`.

#### Scenario: Plan of a stored competition
- **WHEN** the athlete requests the race plan of a stored competition
- **THEN** the answer holds the duration with its source, the pacing and the carbohydrates, and no record, sync marker or provider changes.

#### Scenario: Unknown competition
- **WHEN** the race plan of an id that is not stored is requested
- **THEN** the answer is 404 `competition_not_found` without a fabricated plan.

Evidence:
- `backend/http_api/athlete_get.py:AthleteGetRoutes._race_plan_read`
- `backend/nutrition/macro_context.py:body_weight`
- `backend/planning/race_plan.py:read_race_plan`
- `tests/test_http_athlete_get_routes.py` (race plan route and 404)
- `tests/test_nutrition_macro_ranges.py` (weight source and profile fallback)
- `tests/test_planning_race_plan.py` (competition and weight read)

### Requirement: RP2 Sections and race duration from saved fields
Sections SHALL come from course-profile lines `km <from>–<to>` with an optional grade in % or a climb in Hm; they MUST start at 0, be contiguous and end within 2 % of a known distance, otherwise the whole distance is one section and the rejection is reported. The duration SHALL be the first `h:mm:ss` or `h:mm h` time in the target, else the expected duration.

#### Scenario: Recognized course profile
- **WHEN** the course profile lists contiguous sections from km 0 to the distance
- **THEN** each line, or each comma-separated `km` part, becomes a section with the first grade or climb after its range (a dash counts as minus, `1.200 Hm` as 1200 m), a climb in Hm is converted to an average grade, and a section without one counts as level.

#### Scenario: Unrecognized course profile
- **WHEN** profile lines leave a gap, do not start at 0 or miss the distance
- **THEN** the whole distance is one level section and the plan reports that the profile was not recognized.

#### Scenario: Duration source
- **WHEN** the target holds no time but an expected duration is saved
- **THEN** the plan uses the expected duration and labels it as such; with neither, duration-based parts are unavailable.

Evidence:
- `backend/planning/race_plan.py:course_sections`
- `backend/planning/race_plan.py:target_seconds`
- `tests/test_planning_race_plan.py` (profile lines, rejection, target time forms)

### Requirement: RP3 Pacing per section
Running SHALL split the duration across sections by equal effort using the Minetti et al. (2002) grade cost, so section times add up to the duration. Cycling SHALL set power 5 % above the target on climbs, 5 % below on descents and at the target on level sections, in watts when the target names a power, else as a percentage. Other sports, or a missing distance or running duration, SHALL leave pacing unavailable with the reason.

#### Scenario: Hilly running race
- **WHEN** a running race has a target time and graded sections
- **THEN** climbs get a slower and descents a faster pace than level sections, and the whole-second section times sum exactly to the target time.

#### Scenario: Cycling race with target power
- **WHEN** a cycling target names 230 W and the profile has a climb and a descent
- **THEN** the climb shows 242 W, the descent 218 W and level sections 230 W.

#### Scenario: Unsupported input
- **WHEN** the sport is neither running nor cycling, or the distance or running duration is unknown
- **THEN** pacing is unavailable with the reason `sport`, `distance` or `duration`.

Evidence:
- `backend/planning/race_plan.py:_run_sections`
- `backend/planning/race_plan.py:_ride_sections`
- `tests/test_planning_race_plan.py` (equal effort, power variation, unavailable reasons)

### Requirement: RP4 Carbohydrates before and during the race
Carbohydrates SHALL follow Thomas, Erdman and Burke (2016) by duration: under 45 min none, up to 75 min small amounts or a mouth rinse, up to 2.5 h 30–60 g/h, above that 60–120 g/h of glucose and fructose, flagged above 90 g/h as not yet established. Before the race: over 90 min 10–12 g/kg per day on the two days before, else 7–12 g/kg the day before; over 60 min a meal of 1–4 g/kg 1–4 h before the start.

#### Scenario: Long race with known weight
- **WHEN** a 4 h race is planned and the resolved weight is 70 kg from Garmin
- **THEN** the plan shows 700–840 g per day on the two days before, a 70–280 g meal 4–1 h before the start, 60–120 g/h during the race with the 90 g/h flag, and labels the rule and the weight source.

#### Scenario: Unknown weight or duration
- **WHEN** no weight is resolved, or the duration is unknown
- **THEN** amounts before the race stay in g/kg without grams, or the carbohydrate parts are unavailable, never estimated.

Evidence:
- `backend/nutrition/fuelling.py:carbohydrate_per_hour`
- `backend/nutrition/fuelling.py:pre_race_carbohydrates`
- `tests/test_nutrition_fuelling.py` (duration steps, days before, meal)
- `tests/test_planning_race_plan.py` (weight and source)
