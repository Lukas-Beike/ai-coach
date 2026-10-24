# Design

## Context

See proposal.md for motivation and scope. At `ee89726c9`, `public/analysis.js` fetches `/api/analysis/season`, opens the nearest event automatically and renders preparation evidence and scenarios. `public/plan-views.js` already formats saved competition facts. Bootstrap and profile reads expose canonical local competitions; `CompetitionService` owns audited local mutations. The current route is `#plan/season`.

The baseline spec CS6–CS8 describes backend phase/evidence/scenario behavior, not an obligation to render those analyses on this screen. Add UI requirements without deleting these backend contracts. Source inspection, rather than a live athlete session, is the evidence boundary.

## Goals / Non-Goals

**Goals:** One competition-focused rendering owner, canonical local input, predictable expansion and archive behavior, and continuity with existing refresh/cache and Coach actions.

**Non-Goals:** New persisted fields, direct editing forms, schema migrations, remote sync changes, moving the removed analyses into another new screen, or deleting backend analysis functionality.

## Decisions

1. **Use the existing canonical competition list in application state.** Render through the plan-view owner and existing state refresh pipeline rather than depending on `/api/analysis/season`. Bootstrap and `/api/profile` supply saved optional fields, avoiding coupling event visibility to activity evidence. Keeping the analysis response would retain unnecessary work and its restricted projection. Preserve cancellation/session/cache guards when replacing the loader; an old season-analysis cache must never substitute for competition state. Apply-time source verification located these fields in `backend/http_api/bootstrap_state.py` and `backend/http_api/athlete_get.py`; the plan endpoint consumes competitions for calendar projection rather than supplying the overview's raw list.

2. **Retain the internal `season` route and segment key.** Rename the visible link, heading and accessible label to `Wettkämpfe`, keeping bookmarks and neighboring navigation stable. A route migration adds no value to the requested simplification.

3. **Use native details/summary controls.** Place date/name first, then sport, distance, A/B/C priority and a short relative date in a wrapping summary. Expanded content is a simple definition-style group of populated saved fields. All events and the historical archive start closed on first entry; retain open event IDs during routine in-place refreshes. Render provider text using safe text nodes and shared German date/sport/distance formatting. Preserve meaningful zero values and free-text distance, rather than guessing units.

4. **Partition by athlete-local date.** Today's events belong to upcoming; past events appear newest first inside `Vergangene Wettkämpfe`. Events lacking a valid date stay accessible in a separate `Ohne gültiges Datum` group. Tie-break by priority and name, then stable identity. Do not delete or rewrite invalid records while rendering.

5. **Remove the old analysis presentation and its overview requests.** Disconnect this segment's preparation/scenario loader and remove only obsolete UI helpers/styles/tests with verified consumers. Keep shared analysis charts, backend endpoints, Coach evidence and calculations. Reuse existing compact provenance/local-change badges and Coach entry points; no new CRUD or automatic sync is introduced.

Compact hierarchy: `Wettkämpfe` heading → upcoming event summaries → expanded saved facts when requested → closed historical archive. No metric dashboard or explanatory introduction precedes the list.

## Risks / Trade-offs

- [Refresh collapses the active event or shows stale edits] → Key expansion by stable ID, preserve existing state lifecycle and test a Coach edit followed by refresh.
- [Removing helpers breaks other analysis consumers] → Trace references before deletion, keep shared functions and run affected Node/backend/browser checks.
- [Dense summaries overflow on small phones] → Wrap facts, use existing tokens, verify long names and 200% text in light/dark themes with keyboard-accessible 44px targets.
- [Cached PWA serves mixed old/new assets] → Update index query versions and service-worker cache/assets together.
- [No direct priority editor] → Existing Coach editing remains the supported path; direct forms and registration/result fields are explicit follow-up scope.

## Migration Plan

No database or athlete-data migration. Deliver frontend wiring, README terminology and cache versions together. Rollback restores the previous frontend asset set with a fresh cache version; no record restoration is needed. Validate synthetic fixtures before release, with no access to live databases, credentials or provider writes.
