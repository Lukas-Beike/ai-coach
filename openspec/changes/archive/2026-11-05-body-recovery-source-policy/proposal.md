## Why

Weight, body fat, HRV, resting HR and sleep still follow provider-first rules that contradict the athlete's decision for issue #1668 (2026-11-04): the Coach can show an old Garmin weight over a newer scale reading, Intervals.icu morning HRV silently fills Garmin night-HRV gaps in planning, and the daily planning series has no bounds.

## What Changes

- Weight and body fat resolve by recency across sources (Garmin, Intervals.icu wellness; Intervals.icu athlete record, profile and Wahoo profile weight as undated fallbacks). Within one day of the newest value a device measurement precedes a provider report, which precedes a local entry. Body fat now reads Garmin too. Metrics carry `alternatives` and a `conflict` flag (weight > 1.5 kg, body fat > 2 percentage points).
- HRV, resting HR and sleep form one method family: Garmin's night values by default; Intervals.icu joins only as a detected relay of Garmin (equal values on at least 90 % of at least 5 overlapping days), else Intervals.icu supplies values only when no Garmin value exists. Relay values are labelled "Intervals.icu Wellness (Garmin)". Current values, 7-day averages and planning days use the family.
- Daily planning rules apply the current rules' bounds.
- The PWA display preference of weight, body fat, sleep, HRV and resting HR is derived from the policy (Garmin); only FTP and W/kg charts stay display-only.
- Out of scope (slice 3 of #1668): the per-metric athlete override and per-field consent for the Garmin-to-Intervals export.

## Impact

- `backend/performance/source_policy.py`, `current_metrics.py`, `garmin_canonical.py`, `context.py`, `canonical_recovery.py`, `recovery_context.py`, `planning_recovery.py`, `display_sources.py`.
- No schema change, no provider write, no frontend code change.
