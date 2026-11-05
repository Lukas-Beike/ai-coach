## Why

Coach, plan, charts and current-value tiles decide "which provider's value is current" in several places with contradicting rules, so the Coach can explain a plan in watts that differ from the plan's own targets (issue #1668). The athlete decided the threshold order on 2026-11-04.

## What Changes

- One resolver in `backend/performance/source_policy.py` resolves the current ride FTP (local zone configuration, Intervals.icu setting, Garmin, Wahoo) and the heart-rate, pace and run-power thresholds (local, Garmin, Intervals.icu), with per-source bounds and age limits (Intervals.icu sync 30 days, Garmin 180 days, Wahoo 90 days).
- Coach context, current metrics and plan thresholds read the same resolved values; the hand-coded Garmin-first chain in `current_metrics.py` is gone. Provider zone configurations only fill thresholds the resolver leaves empty.
- Metrics carry `alternatives` and a `conflict` flag; the Coach thresholds carry `ftp_source`, `ftp_alternatives` and `ftp_conflict`, and the plan playbook names a flagged conflict.
- The PWA display preference table is derived from the policy, so sleep, HRV and resting HR now prefer Garmin and body fat Intervals.icu.
- Out of scope here (later PRs of #1668): weight/body-fat recency, the HRV/resting-HR/sleep method family with relay detection, the per-metric athlete override, and per-field consent for the Garmin-to-Intervals export.

## Impact

- `backend/performance/source_policy.py`, `current_thresholds.py`, `canonical_current.py`, `current_metrics.py`, `garmin_canonical.py`, `display_sources.py`, `backend/activities/zone_settings.py`, `backend/planning/load_checks.py`, `planned_unit_load.py`, `backend/coach/playbooks.py`.
- No schema change, no provider write, no frontend change.
