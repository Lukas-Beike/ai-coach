## Why

The Einheiten list, the Coach's `list_recent_activities` and the feedback existence check read the raw Intervals.icu rows, while the calendar and the Coach context read canonical sessions. Garmin- or Wahoo-only sessions were missing from the list and the Coach lookup, their feedback answered 404, and an Intervals.icu duplicate pair was listed twice. Stale checks parsed every stored payload to compare one fingerprint (#1684).

## What Changes

- `/api/activities` and `list_recent_activities` list one provider-neutral session summary per live canonical session, keyed by the local session id; the page cursor moves to version 3 and older cursors restart at page one. `local_activity_id`, `type` and the compact Intervals.icu row shape are gone; the PWA labels sessions from `sport` and `environment`.
- Coach and HTTP feedback saves accept any id that leads to a live canonical session; the stored key is unchanged.
- One sync-owned port, `summary_fingerprints`, returns current summary fingerprints for requested activities only; stored fingerprint values are unchanged, so nothing becomes stale or is refetched.
- Equipment usage, maintenance, assignment and Garmin gear links read session summaries; assignment keys are unchanged.
- The raw-row read is renamed `intervals_activity_payloads` and a guard keeps it inside `backend/sync/`.
- No schema or data migration.

## Impact

Backend activity reads, feedback, detail freshness, training-record and calendar-profile reads, the Coach tool description, `public/activity-analysis.js`, `public/activity-details.js`, `public/performance-view.js`, README.
