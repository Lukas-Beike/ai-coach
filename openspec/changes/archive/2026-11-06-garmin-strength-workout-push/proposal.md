# Proposal

## Why

Intervals.icu cannot carry strength steps to Garmin: its Garmin export drops rep-based steps and structured fields, so planned strength units reach the watch as text only (issue #1741). The official Garmin Personal API is read-only; the pinned unofficial SDK `garminconnect` 0.3.20 can upload, update, schedule and delete workouts and ships the Garmin exercise catalogue.

## What Changes

- Strength exercises may name a Garmin catalogue exercise (`garmin_exercise`); the server validates it and stores the resolved category/exercise pair.
- A new explicit `plan_push` job for the provider `garmin` sends selected strength planned units as structured Garmin strength workouts scheduled on their planned date, updates the same workout on a repeated push and removes it only on an explicit `remove` entry.
- Exercises without a catalogue match block their unit; a saved workout whose exercises Garmin dropped is deleted and reported.
- No new dependency (the workout JSON is built without the SDK's optional pydantic models) and no schema change (ids live in `remote_links`).

Coach tool and UI action follow in separate PRs of #1741 and update this capability's main spec directly.

## Capabilities

### New Capabilities

- `garmin-strength-workout-push`: explicit strength workout push to Garmin Connect.

### Modified Capabilities

None.

## Impact

`backend/providers/garmin_strength_workout.py`, `backend/sync/garmin_strength_push.py`, `backend/planning/strength_structure.py`, `backend/sync/jobs.py`, `backend/sync/executor.py`, Garmin assembly wiring, `backend/providers/descriptors.py`, `backend/coach/tool_schemas.py`, README and `tests/test_garmin_strength_push.py`. Inspected baseline: `6573dfb22`. Live behavior on a real Garmin account (schedule response key, watch rendering) is verified once with the athlete before the issue closes.
