# Spec Delta

## ADDED Requirements

### Requirement: Profile body fat is shown in the Body overview
The Body overview SHALL show a valid saved body-fat profile value labelled as profile data, without projecting it into dated measurement history.

#### Scenario: Profile value exists
- **WHEN** the saved profile contains valid body fat
- **THEN** the overview shows that value and labels it as profile data.

#### Scenario: No profile value exists
- **WHEN** the profile has no valid body-fat value
- **THEN** the overview shows the latest eligible Garmin body-fat reading when available.

Evidence: `public/analysis.js`; focused synthetic presentation test is required.
