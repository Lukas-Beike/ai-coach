## Why

The Coach prompt says the athlete's request is the authorization, yet every Intervals.icu write and Garmin strength push ended as an approval card (#2342). Athlete decision 2026-11-12: sync without a card when the request is clear, otherwise the Coach asks.

## What Changes

- A remote write the athlete named in their own message (wording gate CA5, hardened by #2341) is bound to stored state exactly as a card would bind it and queued in the same turn, without a card. This covers Intervals.icu plan, competition and nutrition syncs, failed-push retries, the illness-pause sync and the Garmin strength push.
- Remote deletions that run with a clear sync (orphaned Intervals.icu events, deleted competitions, orphaned Garmin workouts) also need no card; the turn receipt names each one.
- An explicit Garmin removal entry keeps its approval card.
- An unclear request is denied by the wording gate and the Coach offers the sync; a yes to that offer is a named sync.
- The Garmin wording check gets the whole-message refusal block of the Intervals.icu gate.
- **BREAKING** for the visible flow: the remote approval card no longer appears for named syncs.

## Capabilities

### New Capabilities

### Modified Capabilities
- `coach-tool-authority`: CA5 (card-free named remote writes, unclear request, Garmin removal card) and CA6 (card binding reused by the card-free run).
- `garmin-strength-workout-push`: Coach request queues without a card.
- `nutrition-provider-sync`: the named Coach sync queues the export without a card.
- `competitions-and-seasons`: CS5 named push without card approval.
- `training-library`: TL10 named plan sync selection.

## Impact

`backend/coach/tool_execution_service.py`, `backend/coach/proposal_creation.py`, `backend/coach/change_receipts.py`, `backend/coach/write_gate.py`, `backend/coach/tool_schemas.py`; docs `docs/coach.md`, `docs/features.md`, `docs/coach-dialogue-evaluation.md`, `docs/nutrition.md`; `AGENTS.md` (orchestrator-granted turn). No schema, API route or frontend change; card execution routes stay for Garmin removals and cards created before the upgrade. Exclusion: the adaptive preview approval (TP9) is unchanged; the illness-pause sync still needs the classifier-confirmed approval of the athlete's next message.
