## Why

Provider copies are bundled into canonical sessions by heuristics, and the athlete cannot correct the result: a wrong merge or a missed merge stays forever and distorts load, summaries and the Coach's recent training (issue #1667).

## What Changes

- The athlete can confirm a bundle, split one provider copy off it, or merge two sessions of the same day from the activity detail view. Each correction records a change-history receipt with undo.
- Corrected sessions are athlete-confirmed, so later session linking never merges or splits them.
- Local Coach tools run the same corrections with receipts and undo.
- Feedback stays with the session it was written for; a test shows that feedback written on a Garmin-only session still resolves after the Intervals.icu copy arrives, so no key migration is needed.
- Out of scope here (follow-up PR of #1667): local activity deletion without alias revival and automatic re-validation of heuristic links.

## Impact

- `backend/activities/session_corrections.py`, `backend/db/canonical_store.py`, change history and undo wiring, `FeedbackPostRoutes`, activity detail GET, `public/activity-details.js`, Coach tools.
- No schema change: `athlete_confirmed`, `link_kind` and `merged_into` already exist. No provider writes.
