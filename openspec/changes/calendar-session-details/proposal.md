## Why

The athlete reviews a session where it happened, in the calendar (#2258). "Analyse › Einheiten" duplicated the calendar with a separate paged list, and the calendar card could only open a dialog. The athlete decided (2026-11-11, with mockups) to move the single-session analysis into the calendar card and remove the list.

## What Changes

- A completed session's calendar card gets a "Details" toggle that opens, in the card, everything "Analyse › Einheiten" showed: channel charts with tap readout, time in zones, laps, all values, form drift, provider notes and detail-loading actions.
- Runs chart the running dynamics per second (ground contact time and balance, vertical oscillation and ratio, step length); the activity detail document serves them in their own section, and the Coach does not receive them.
- "Feedback" next to "Mit dem Coach analysieren" opens the existing rating and session dialog (option B).
- **BREAKING (UI):** the Analyse segment "Einheiten" and its paged list are removed; an old `#analysis/sessions` link opens the calendar.
- The calendar pages back without limit; weeks before the configured "Wochen zurück" load their completed sessions on demand (option A).

## Capabilities

### New Capabilities

### Modified Capabilities

- `web-pwa-and-accessibility`: the calendar card carries the single-session analysis; the compact calendar week pages back without limit.

## Impact

- Client: `public/plan-views.js`, `public/activity-analysis.js`, `public/activity-details.js`, `public/analysis.js`, `public/navigation.js`, `public/index.html`, `public/styles.css`.
- Server: `backend/activities/detail_contract.py` (running dynamics section, coverage), `backend/coach/activity_read_tools.py` (drops it for the Coach).
- No schema change, no stored data change, no remote effect.
- Note: the athlete asked for this as an OpenSpec change after the implementation had started; the proposal records the decisions taken with mockups during #2258.
