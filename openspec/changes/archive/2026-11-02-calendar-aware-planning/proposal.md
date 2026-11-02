# Proposal

## Why

Planning omits ordinary calendar events and truncates the feed, so the Coach can plan without knowing about a busy day.

## What Changes

- Include bounded, compact calendar context for planning and report omissions.
- Summarize busy time and report non-blocking calendar conflicts in plan receipts.
- Ask the athlete about training and reduced intensity when an event creates material uncertainty.

## Capabilities

### New Capabilities

### Modified Capabilities

- `coach-context-and-provenance`: planning calendar context and busy time.
- `coach-conversation`: clarification when events make training uncertain.
- `coach-tool-authority`: non-blocking calendar findings.

## Impact

Coach context and planning checks; no database migration or remote writes. Inspected revision c60b3ae1: `backend/coach/context.py`, `backend/calendar/external.py`, `backend/planning/plan_guard_service.py`, `backend/planning/plan_checks.py`. Existing context uses a filtered 50-event list. Evidence for new behavior requires focused tests.
