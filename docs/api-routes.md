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
| GET | `/api/wahoo/callback` | Wahoo OAuth redirect target; answers with a 302 redirect to the app | Public |

`/api/wahoo/callback` is the only API GET that needs no session: the
SameSite=Strict session cookies are not sent on Wahoo's cross-site redirect.
Its only accepted credential is the single-use, expiring `state` stored on the
server by `POST /api/wahoo/connect`.

## Activity identifiers

Activity routes accept either the local canonical activity ID (`act_...`) or the
legacy Intervals.icu provider ID. The server resolves a local ID once, at the
entry point, to the provider ID; every stored key and provider request stays
provider-keyed.

- `GET /api/activities` items and `GET /api/activities/{id}` responses carry
  `activity_id` (the provider ID) and `local_activity_id` (the local ID, or
  `null` when no canonical record exists yet).
- The list `cursor` is versioned: `{"v": 2, "after": [sort_date, provider_id]}`,
  base64url-encoded. Unversioned cursors issued before this change are still
  accepted. Unrecognized cursors return the first page.
- `POST /api/activities/{id}/feedback` and the Coach activity tools, including
  equipment assignment and duplicate deletion, accept either form. Those two
  have no HTTP route of their own; a confirmed duplicate deletion runs through
  `POST /api/coach/actions/execute`. Only Intervals.icu
  primary, non-deleted sessions resolve; each resolves to its own provider ID,
  including a duplicate. Any other `act_` reference (unknown, Garmin-primary or
  deleted) is passed through unchanged and receives the route's existing
  not-found or validation response.
- `activity_details` sync jobs are stored under the provider ID at enqueue time.

## Reads

| Method | Path | Purpose | Requirement |
| --- | --- | --- | --- |
| GET | `/api/plan`, `/api/library`, `/api/weather` | Planning, library and weather projections | Auth |
| GET | `/api/performance`, `/api/profile`, `/api/feedback`, `/api/context-preview` | Athlete and performance projections | Auth |
| GET | `/api/zones` | Local and provider zone configurations | Auth |
| GET | `/api/settings/activity-detail-floor` | Activity detail prefetch floor | Auth |
| GET | `/api/activities`, `/api/activities/{id}` | Activity list and detail | Auth |
| GET | `/api/sync/status`, `/api/sync/jobs/{id}` | Synchronization status and job result | Auth |
| GET | `/api/chat/history`, `/api/chat/receipt`, `/api/chat/status` | Coach history, receipts and status | Auth |
| GET | `/api/change-history` | Local change history | Auth |
| GET | `/api/state/events` | Authenticated state event stream | Auth |
| GET | `/api/logs`, `/api/logs/download`, `/api/diagnostics` | Diagnostics and redacted logs | Auth |
| GET | `/api/privacy/export`, `/api/privacy/delete/preview`, `/api/privacy/backup` | Privacy export, deletion preview and backup | Auth |
| GET | `/api/analysis/endurance`, `/api/analysis/power-profiles`, `/api/analysis/season`, `/api/analysis/training-records` | Analysis projections | Auth |
| GET | `/api/nutrition/day`, `/api/nutrition/range`, `/api/nutrition/templates`, `/api/nutrition/week`, `/api/nutrition/products` | Nutrition projections and product search | Auth |

## Writes and jobs

| Method | Path | Purpose | Requirement |
| --- | --- | --- | --- |
| POST | `/api/chat`, `/api/chat/stream`, `/api/chat/reset`, `/api/chat/cancel` | Submit, stream, reset or cancel Coach work | CSRF |
| POST | `/api/coach/actions/confirm`, `/api/coach/actions/cancel`, `/api/coach/actions/execute` | Confirm, cancel or execute a Coach proposal | CSRF |
| POST | `/api/planning/commands` | Apply an approved local planning command | CSRF |
| POST | `/api/feedback`, `/api/activities/{id}/feedback` | Save athlete feedback; activity feedback returns a `change` undo reference | CSRF |
| POST | `/api/sync/jobs`, `/api/sync/jobs/{id}/resolve` | Queue or resolve a sync job | CSRF |
| POST | `/api/sync`, `/api/garmin/sync`, `/api/wahoo/sync`, `/api/intervals/full-resync`, `/api/garmin/full-resync`, `/api/wahoo/full-resync` | Queue provider synchronization | CSRF |
| POST | `/api/performance/refresh`, `/api/external-calendar/sync`, `/api/weather/sync`, `/api/analysis/refresh`, `/api/nutrition/refresh` | Queue or run a targeted refresh | CSRF |
| POST | `/api/analysis/scenarios` | Project a training scenario without saving it | CSRF |
| POST | `/api/change-history/undo/preview`, `/api/change-history/undo`, `/api/change-history/undo-turn` | Preview or apply an undo, or undo one Coach turn | CSRF |
| POST | `/api/privacy/delete`, `/api/privacy/restore` | Delete or restore privacy data | CSRF |
| POST | `/api/logs/delete`, `/api/diagnostics/delete` | Clear diagnostics data | CSRF |
| POST | `/api/equipment/maintenance` | Record equipment maintenance | CSRF |
| POST | `/api/nutrition/entry`, `/api/nutrition/entry/delete`, `/api/nutrition/sync` | Write, delete or synchronize nutrition entries | CSRF |
| POST | `/api/nutrition/products`, `/api/nutrition/products/lookup`, `/api/nutrition/products/extract`, `/api/nutrition/products/archive`, `/api/nutrition/products/database/delete` | Save, look up, extract or archive products, or forget a food database entry | CSRF |
| POST | `/api/wahoo/connect`, `/api/wahoo/disconnect` | Start the Wahoo OAuth connection or disconnect Wahoo | CSRF |
| POST | `/api/metric-export/preview` | Preview metric values for export without writing | CSRF |
| POST | `/api/metric-export/execute` | Intervals.icu write: send the confirmed metric selection | CSRF |
| POST | `/api/metric-export/automatic` | Intervals.icu write: switch the automatic Garmin metric export; needs `confirmed: true` and the `intervals` target | CSRF |
| POST | `/api/transcribe` | Transcribe short-lived voice input | CSRF |

## PUT routes

| Method | Path | Purpose | Requirement |
| --- | --- | --- | --- |
| PUT | `/api/settings/model`, `/api/settings/service-tier`, `/api/settings/thinking-level`, `/api/settings/calendar-display`, `/api/settings/activity-detail-floor` | Update settings | CSRF |
| PUT | `/api/profile` | Patch only the submitted profile fields onto the current stored profile | CSRF |
| PUT | `/api/zones` | Save one local zone configuration; returns a receipt with an undo reference | CSRF |
| PUT | `/api/zones/remove` | Remove one local zone configuration; needs `confirmed: true` | CSRF |
| PUT | `/api/athlete-context` | Replace profile and competitions | CSRF |
| PUT | `/api/nutrition/entry` | Update a nutrition entry | CSRF |
| PUT | `/api/nutrition/products` | Update a confirmed saved product | CSRF |
| PUT | `/api/settings/credentials` | Save or clear provider credentials stored in the encrypted database (see below) | CSRF |

### Provider credentials and Garmin login

These routes are reached from **Mehr > Anbindungen > Zugangsdaten**. They never
return a secret: the response is the credential status only.

- `PUT /api/settings/credentials` takes a JSON object whose keys are credential
  fields (`openai_api_key`, `openai_base_url`, `intervals_api_key`,
  `intervals_athlete_id`, `wahoo_client_id`, `wahoo_client_secret`,
  `garmin_email`). `garmin_email` has no UI field; it pairs with the
  environment `GARMIN_PASSWORD` fallback and is reported as configured only,
  never echoed back. A string
  stores the value; `null` or a blank string clears the value stored in the app,
  so the environment value applies again. Each field is validated server-side.
  Changing the effective `intervals_athlete_id` returns `409` while Intervals.icu
  records or sync cursors are stored, because they are not scoped by athlete; a
  privacy delete clears them first.
  The response is the credential status: per field `source` (`db`, `env` or
  `none`), `configured`, and `value` only for non-secret fields, plus
  `garmin_connected`, `openai_configured`, `intervals_configured`,
  `wahoo_configured` and `garmin_connection` (`connected`, `source`,
  `mfa_pending`).
- `POST /api/garmin/login` takes `{"email": "...", "password": "..."}`. The
  password is used once and never stored. The response is `{"status":
  "connected"}` or `{"status": "mfa_required"}`, plus the current
  `connected`, `source` and `mfa_pending` fields. An MFA challenge keeps its pending login on the
  server for 10 minutes, until a code is submitted or a new login starts;
  cancelling in the UI does not discard it. Wrong Garmin credentials return
  `422`, an unreachable Garmin returns `502`.
- `POST /api/garmin/login/mfa` takes `{"code": "..."}` and completes the pending
  login. The response is `{"status": "connected"}` with the same fields. A wrong
  code returns `422` and keeps the pending login for another attempt. The fifth
  wrong code discards it and returns `409`, as does a missing, expired or
  superseded pending login. A privacy delete also discards it.
- `POST /api/garmin/disconnect` takes an empty JSON object, deletes the stored
  Garmin tokens and returns `{"status": "disconnected"}` with the same fields. Garmin data already stored
  locally is kept.

Each POST and PUT above requires the session cookie and `X-CSRF-Token`.
Errors are JSON with a German `error` message and no secret or raw provider text.

The former `/api/logs/clear` and `/api/diagnostics/clear` aliases are not
registered. Static files and the application shell are served separately from
these API route tables.
