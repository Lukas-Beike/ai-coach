# Proposal

## Why

The athlete reports that the Garmin endurance score in the analysis view has not
advanced since 2026-10-18, although Garmin syncs succeed and the diagnostics of
2026-10-24 show an endurance-score measurement dated 2026-10-23. The 90-day
history is requested with the SDK default `weekly` aggregation, so Garmin
returns one `groupMap` bucket per week keyed by the week's start (Sunday
2026-10-18 for the running week). The history projection prefers `groupMap`
over the dated latest `enduranceScoreDTO`, and the UI's Monday-based calendar
weeks place a Sunday key into the previous week. The current week therefore
shows no point and the "current" value stays dated on the last Sunday.

## What Changes

- Request the Garmin endurance-score range with `daily` aggregation in both the
  scheduled historic-metrics collection and the targeted analysis read, matching
  the Garmin web app's 4- and 12-week reports.
- Record `daily` as the endurance score's aggregation in sync pagination
  metadata and in both provider-metric history projections.
- Apply the same daily request and metadata to Garmin running tolerance, which
  the analysis view also groups by calendar week and which used the same
  week-start-keyed `weekly` aggregation. Weekly training status stays weekly:
  it has no daily endpoint and is not shown in the analysis view.
- Keep the existing UI weekly display: it already selects the latest valid
  reading per calendar week, so daily readings make the running week and the
  current value reflect the newest Garmin measurement.
- Existing stored weekly payloads remain readable; the next Garmin sync
  replaces them with daily data. No schema or migration change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `performance-and-readiness`: adds a requirement that the Garmin endurance-score
  history reflects the newest dated Garmin measurement within the running
  calendar week instead of a week-start bucket.

## Impact

- Code: `backend/providers/garmin.py` (historic-metrics request and targeted
  analysis contract), `backend/performance/chart_history.py`,
  `backend/performance/history.py` (aggregation metadata).
- Tests: `tests/test_provider_garmin_metric_history.py`,
  `tests/test_performance_chart_history.py`,
  `tests/test_garmin_analysis_refresh.py`, `tests/test_provider_wire_fixtures.py`.
- Provider: one Garmin request per sync returns up to 90 daily records instead
  of ~13 weekly buckets; same endpoint and SDK method (`garminconnect==0.3.19`
  `get_endurance_score(start, end, aggregation=...)` and
  `get_running_tolerance(start, end, aggregation=...)`). No new dependency.
- No frontend asset, schema, persistence, or Coach-contract change. Canonical
  `ENDURANCE_SCORE` mapping is unchanged.
