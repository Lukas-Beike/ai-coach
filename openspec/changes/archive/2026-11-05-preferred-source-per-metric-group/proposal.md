## Why

Issue #1668 (athlete decision 2026-11-04) keeps the athlete override (solution A.5) in scope: the athlete must be able to change the source precedence per metric group without code changes, for example "use my Withings weight via Intervals.icu" or "my HRV is the morning reading in Intervals.icu".

## What Changes

- Five profile settings `preferred_source_thresholds`, `preferred_source_body`, `preferred_source_hrv`, `preferred_source_resting_hr` and `preferred_source_sleep` (empty, `garmin` or `intervals`), saved through the normal profile API with receipt and undo.
- The source policy puts the preferred provider first in each group: thresholds behind a locally confirmed zone configuration; weight and body fat over a newer value of another source; HRV, resting HR and sleep as the only method family (Intervals.icu) or Garmin without any fallback.
- Every consumer reads the same preference inside its read unit: Coach context and current metrics, plan thresholds and load checks, the planning recovery days, and the PWA display preferences.
- A "Bevorzugte Quelle" fieldset in the profile form.

## Impact

- `backend/performance/source_policy.py` and its consumers, `backend/athlete/profile.py`, `backend/change_history.py`, composition wiring (`server.py`, assemblies), `public/index.html`, `public/service-worker.js`.
- No schema change: the settings are profile fields in the encrypted database and backups.
