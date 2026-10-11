# Standard synthetic fixture coverage

Reviewed the standard demo seed against the current provider normalizers,
analysis renderers, route projections and existing fixture regression tests.
This is a dataset coverage review, not a full application audit.

## Gaps closed in seed version 7

| Area | Previous gap | Added or corrected |
| --- | --- | --- |
| Running predictions | Entire optional section absent | Current 5 km, 10 km, half-marathon and marathon estimates plus dated weekly history across 90 days |
| Current performance | FTP used an unrecognized `power` field; running thresholds and max HR missing | Provider-shaped FTP, running pace/power, running/cycling threshold HR and sport-specific max HR |
| Provenance | Existing Garmin readings lacked observation dates and freshness | Source freshness and observation dates for seeded measurements |
| Consistency | Current VO2max/FTP and the final history reading differed; historical FTP reversed the trend | Current readings agree with their last history point; dated historical FTP increases towards today |
| Recovery | Readiness, sleep score and morning Body Battery absent | Dated readiness, sleep scores and before/after-sleep Body Battery derived through the actual projection |
| Sleep | Reported duration differed from the interval | Sleep end timestamps match each reported duration |
| Daily health | No floors metric | Synthetic daily floors alongside steps and energy expenditure |
| Nutrition products | Local product catalog empty | Active gram/ml products and an archived product with manual provenance |
| Workout library | Planned units existed, but the reusable template library was empty | Local cycling, indoor cycling and running templates without calendar dates or remote IDs |

The existing versioned demo upgrade applies these additions to previously seeded
disposable demos. Repeated seeding does not add duplicate products or records.
These are fixture changes only; the application database schema is unchanged.

## Existing representative data

- Profile, upcoming cycling/running competitions and local planned workouts.
- Calendar marker constraints, multi-day and recurring external events, rest and
  illness days, swim sessions and planned-load ambiguity scenarios.
- Cycling, indoor cycling and running history; cycling/running stream details,
  feedback, zone distributions, endurance analysis and best performance windows.
- Garmin and Intervals body/recovery histories, both FTP sources, intentionally
  sparse body measurements and missing HRV samples, endurance score and running
  tolerance history.
- Local/Garmin equipment, active/archived components, assignments, maintenance
  and usage-limit examples.
- Nutrition diary, saved porridge and a planned ride for fueling interactions;
  synthetic conversation history.

## Remaining demo limits

- No weather forecast is seeded. Weather success cards need a separate synthetic
  weather fixture; the standard demo displays the unconfigured state.
- Fueling has an eligible workout but no pre-saved fueling plan. The creation
  flow must be exercised to inspect a saved plan.
- No multi-week training-plan record is seeded. Individual planned units cover
  the calendar; the plan creation flow is a separate scenario.
- Zone-2 running pace is not configured; its missing-value state remains visible.
- Provider credentials stay absent and provider calls stay blocked. Connection,
  live sync, permission and failure states require dedicated scenarios.
- Pending Coach approvals, attachments, notifications and backup/restore are
  interaction-specific scenarios, not persistent standard-demo contents.
- The default canned Coach transport does not represent real model behavior.

Do not infer UI parity with a connected installation from the standard demo
alone. Optional sections must have a positive dataset scenario as well as tests
for unavailable/sparse data. The added browser test uses the actual standard
seed and verifies all four running predictions in the compact table without mocked API results.
Race prediction history remains seeded for backend coverage, although redundant
race charts and endurance-efficiency cards were removed from the Performance UI.
