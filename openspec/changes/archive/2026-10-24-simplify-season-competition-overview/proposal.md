# Proposal

## Why

The Season screen obscures the athlete's competitions with weekly training evidence, preparation metrics and load simulations. The athlete needs a compact chronological competition overview with individually expandable event details.

## What Changes

- Rename the visible Season segment to `Wettkämpfe` and show one compact entry per upcoming competition, initially collapsed.
- Show name, date, sport, distance, personal A/B/C priority and relative event date in the collapsed entry.
- Expand an event to show its saved start time, target, expected duration, course profile, description and notes where present.
- Group past competitions in an initially collapsed archive, without changing stored records.
- Remove phase labels, weekly volume/history, preparation evidence, long-session lists and load-scenario controls from this screen.
- Read the overview from canonical local competition records, without requiring activity history or preparation analysis.
- Preserve existing Coach mutation, receipts/undo, provenance and explicitly requested synchronization workflows.

This is a proposed behavior change, not a documentation backfill. New participation statuses, results, location/elevation fields and direct CRUD forms are deferred; this change uses existing saved fields and Coach workflows.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `competitions-and-seasons`: Add the competition-focused overview and its display, archive, state and nonmutation requirements.

## Impact

Primary owners are `public/analysis.js`, `public/plan-views.js`, `public/index.html`, navigation and view-refresh consumers, shared formatting and styles. The service-worker asset versions and README must follow the UI change. Reuse the existing public competition read model; add no persistence schema, dependency or provider operation. Existing preparation/scenario APIs and CS6–CS8 backend contracts remain available to their existing consumers; this proposal removes their presentation from the overview only.

Inspected baseline: clean branch `t3/season-competition-overview`, revision `ee89726c9`. Evidence: `seasonEventCard`, `appendSeasonEvidence`, `appendSeasonScenario` in `public/analysis.js`; competition rendering in `public/plan-views.js`; `CompetitionService` in `backend/planning/competition_service.py`; existing `competitions-and-seasons` spec and `tests/season-factor.test.cjs`. Current browser layout and end-to-end behavior have not been verified in this planning session.
