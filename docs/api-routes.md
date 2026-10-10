# HTTP API Routes

This inventory describes the routes registered by `backend/http_api` in the
current build. All routes use the same origin. `Auth` means an authenticated
session cookie; `CSRF` means that session plus the `X-CSRF-Token` header.

## Public and authentication

| Method | Path | Purpose | Requirement |
| --- | --- | --- | --- |
| GET | `/api/health` | Liveness and health status | Public |
| GET | `/api/readiness` | Readiness status | Public |
| GET | `/api/auth/status` | Current login status | Public |
| GET | `/api/bootstrap` | Initial authenticated client state | Auth |
| POST | `/api/login` | Create a session | Public |
| POST | `/api/logout` | End the current session | CSRF |

## Reads

| Method | Path | Purpose | Requirement |
| --- | --- | --- | --- |
| GET | `/api/plan`, `/api/library`, `/api/weather` | Planning, library and weather projections | Auth |
| GET | `/api/performance`, `/api/profile`, `/api/feedback`, `/api/context-preview` | Athlete and performance projections | Auth |
| GET | `/api/activities`, `/api/activities/{id}` | Activity list and detail | Auth |
| GET | `/api/sync/status`, `/api/sync/jobs/{id}` | Synchronization status and job result | Auth |
| GET | `/api/chat/history`, `/api/chat/receipt`, `/api/chat/status` | Coach history, receipts and status | Auth |
| GET | `/api/change-history` | Local change history | Auth |
| GET | `/api/state/events` | Authenticated state event stream | Auth |
| GET | `/api/logs`, `/api/logs/download`, `/api/diagnostics` | Diagnostics and redacted logs | Auth |
| GET | `/api/privacy/export`, `/api/privacy/delete/preview`, `/api/privacy/backup` | Privacy export, deletion preview and backup | Auth |
| GET | `/api/analysis/endurance`, `/api/analysis/power-profiles`, `/api/analysis/season`, `/api/analysis/training-records`, `/api/analysis/scenarios` | Analysis projections and scenarios | Auth |
| GET | `/api/nutrition/day`, `/api/nutrition/range`, `/api/nutrition/templates`, `/api/nutrition/fueling`, `/api/nutrition/products` | Nutrition projections and product search | Auth |

## Writes and jobs

| Method | Path | Purpose | Requirement |
| --- | --- | --- | --- |
| POST | `/api/chat`, `/api/chat/stream`, `/api/chat/reset`, `/api/chat/cancel` | Submit, stream, reset or cancel Coach work | CSRF |
| POST | `/api/coach/actions/confirm`, `/api/coach/actions/cancel`, `/api/coach/actions/execute` | Confirm, cancel or execute a Coach proposal | CSRF |
| POST | `/api/planning/commands` | Apply an approved local planning command | CSRF |
| POST | `/api/feedback`, `/api/activities/{id}/feedback` | Save athlete feedback | CSRF |
| POST | `/api/sync/jobs`, `/api/sync/jobs/{id}/resolve` | Queue or resolve a sync job | CSRF |
| POST | `/api/sync`, `/api/garmin/sync`, `/api/intervals/full-resync`, `/api/garmin/full-resync` | Queue provider synchronization | CSRF |
| POST | `/api/performance/refresh`, `/api/external-calendar/sync`, `/api/weather/sync` | Queue or run a targeted refresh | CSRF |
| POST | `/api/change-history/undo/preview`, `/api/change-history/undo` | Preview or apply an undo | CSRF |
| POST | `/api/privacy/delete`, `/api/privacy/restore` | Delete or restore privacy data | CSRF |
| POST | `/api/logs/delete`, `/api/diagnostics/delete` | Clear diagnostics data | CSRF |
| POST | `/api/equipment/maintenance` | Record equipment maintenance | CSRF |
| POST | `/api/nutrition/entry`, `/api/nutrition/sync` | Write or synchronize nutrition entries | CSRF |
| POST | `/api/transcribe` | Transcribe short-lived voice input | CSRF |

## PUT routes

| Method | Path | Purpose | Requirement |
| --- | --- | --- | --- |
| PUT | `/api/settings/model`, `/api/settings/thinking-level`, `/api/settings/calendar-display` | Update settings | CSRF |
| PUT | `/api/profile`, `/api/athlete-context` | Update profile and competitions | CSRF |
| PUT | `/api/nutrition/entry` | Update a nutrition entry | CSRF |

The former `/api/logs/clear` and `/api/diagnostics/clear` aliases are not
registered. Static files and the application shell are served separately from
these API route tables.
