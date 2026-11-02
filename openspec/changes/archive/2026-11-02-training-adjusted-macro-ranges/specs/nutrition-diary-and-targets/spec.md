## ADDED Requirements

### Requirement: Daily macro comparison
The diary SHALL subtly color complete macro totals outside athlete-specific daily reference ranges using the latest available weight and training data.

#### Scenario: Protein target
- **WHEN** a current body weight is available
- **THEN** the protein reference is 2 g/kg with a 15 percent tolerance in either direction.

#### Scenario: Training-adjusted carbohydrate range
- **WHEN** the day's training is known
- **THEN** the base range is 3–5 g/kg below 90 minutes, 5–7 g/kg from 90 minutes, and 6–10 g/kg from 120 minutes; at least ten minutes in zone 4 or above within one session raises it one range, capped at 6–10 g/kg.

#### Scenario: Planned and completed sessions
- **WHEN** a completed activity is matched to a planned session
- **THEN** its actual duration replaces the planned duration on the activity's actual date without double counting.

#### Scenario: Missed session
- **WHEN** a planned session is marked missed
- **THEN** it does not contribute training to the day's carbohydrate range.

#### Scenario: Fat reference
- **WHEN** complete fat and positive calorie totals are available
- **THEN** the reference is 20–30 percent of recorded energy as fat energy.

#### Scenario: Missing input
- **WHEN** intensity or training information is unavailable but current weight is known
- **THEN** carbohydrate comparison uses the 3–5 g/kg light-activity reference without claiming the training intensity is known.

#### Scenario: Missing weight or intake
- **WHEN** a required weight, calorie value or macro total is unknown
- **THEN** the affected comparison is not colored and no missing value is assumed.

Evidence: `backend/nutrition/macro_ranges.py`, `backend/http_api/nutrition.py`, `public/nutrition.js`; `tests/test_nutrition_macro_ranges.py`, `tests/test_nutrition_api_and_sync.py`, `tests/nutrition-macro-ranges.test.cjs`, `e2e/nutrition-macro-ranges.spec.js`.
