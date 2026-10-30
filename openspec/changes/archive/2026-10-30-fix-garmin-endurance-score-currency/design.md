# Design

## Context

See proposal.md - Why. Observed in source at `ee89726c9`:

- `backend/providers/garmin.py:_collect_historic_metrics` calls
  `get_endurance_score(start, end)` for `today-89 .. today` and records
  `"weekly"` in `provider_sync.pagination.endurance_score.aggregation`.
- `targeted_analysis_sources()["performance"]["endurance_score"]` uses the
  shared `date_range` call shape, which also falls back to the SDK default
  `weekly`.
- In `garminconnect==0.3.19`, `get_endurance_score(startdate, enddate,
  aggregation="weekly")` accepts `daily` or `weekly` against the same `/stats`
  endpoint.
- `garmin_metric_history._records` returns `groupMap` entries (keyed date →
  record) before falling back to `enduranceScoreDTO`, so the dated latest DTO is
  dropped whenever `groupMap` exists.
- `public/analysis.js` groups provider metrics into Monday-based weeks via
  `analysisWeeklyPerformancePoints`, taking the latest reading per week, and
  takes `currentPoint` from the latest raw point. `providerMetricValue` already
  reads `groupAverage`.
- The canonical `ENDURANCE_SCORE` mapping unwraps only `enduranceScoreDTO`
  wrappers and is not affected by `groupMap` granularity.

## Goals / Non-Goals

**Goals:**
- Daily endurance-score and running-tolerance readings in both Garmin request
  paths, with matching aggregation metadata.

**Non-Goals:**
- Changing the UI chart, the canonical metric mapping, weekly training
  status, or stored data.

## Decisions

- **Request `aggregation="daily"`** rather than merging `enduranceScoreDTO` into
  weekly buckets. Daily data is what the Garmin web app uses for the same
  windows, gives the chart real per-week latest values, and removes the
  Sunday-key/Monday-week mismatch at its source. Merging the DTO would fix only
  the current value while past weeks stay week-start averages.
- **Keep `_records` precedence unchanged.** With daily `groupMap` keys the
  newest day already equals the DTO date; no projection change is needed.
- **Pass aggregation explicitly in the targeted contract** with a dedicated
  lambda, mirroring the existing `running_tolerance` entry.
- **Update aggregation labels** in `chart_history._provider_metrics` and
  `history._provider_metrics` to `daily` so metadata matches the data.
- **Include running tolerance** (retro finding R1): `public/analysis.js` shows
  it through the same weekly grouping, and `get_running_tolerance` defaults to
  the same week-start-keyed `weekly` aggregation, so it had the same stale
  running-week risk. **Exclude weekly training status**: the SDK offers only a
  weekly endpoint and the analysis view does not display it.

## Risks / Trade-offs

- [Daily `groupMap` shape differs from weekly] → Tests cover a daily
  `groupMap`; existing DTO/list fallbacks stay intact; the UI value aliases
  include `groupAverage`. The live shape is unverified (no live payload may be
  inspected); confirm on the next real sync via the analysis view.
- [Larger response, ~90 records vs ~13] → Bounded by the existing 90-day window
  and snapshot size limits; one request per sync as before.
- [Stored weekly payload until next sync] → Remains renderable as today; the
  next Garmin sync overwrites it.

## Migration Plan

No schema or data migration. Deploy normally; the next scheduled or manual
Garmin sync fetches daily data. Rollback is a code revert; weekly payloads
remain readable.
