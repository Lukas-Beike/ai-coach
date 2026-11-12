# HTTP API Routes

This inventory lists every route registered by `backend/http_api` in the
current build. All routes use the same origin. `Session` means an authenticated
session cookie; `Session + CSRF` means that session plus the `X-CSRF-Token`
header. The request handler checks the access level before any route code runs;
a path that is not in the table answers 404 (an unknown POST or PUT only after
the session and CSRF checks).

During a restore the maintenance operation gate answers 503. A PUT enters it
before authentication. A POST enters it after the session and CSRF checks and
checks the session again inside it, except login, chat cancellation and the
restore itself, which run outside it, and logout, which enters it only to end
the session. GET routes do not enter it, except the Wahoo callback while it
completes the authorization.

The table between the markers is generated from the route table
(`backend/http_api/route_table.py`); the purpose is each handler's docstring.
Regenerate it with `python tests/test_api_routes_doc.py --write`.

<!-- BEGIN GENERATED ROUTES -->
| Method | Path | Access | Purpose |
| --- | --- | --- | --- |
| GET | `/api/activities` | Session | Activity list page; items carry the local session `id` and `record_ids`. |
| GET | `/api/activities/{id}` | Session | The `activity_detail.v1` document of one session (local or provider id). |
| POST | `/api/activities/{id}/feedback` | Session + CSRF | Save activity feedback; returns a `change` undo reference. |
| POST | `/api/activities/{id}/session` | Session + CSRF | Confirm, split, merge or delete one session bundle. |
| GET | `/api/analysis/power-profiles` | Session | Analysis projection: power profiles or training records. |
| POST | `/api/analysis/refresh` | Session + CSRF | Run a targeted refresh of one analysis area. |
| GET | `/api/analysis/training-records` | Session | Analysis projection: power profiles or training records. |
| GET | `/api/auth/status` | Public | Current login status. |
| GET | `/api/bootstrap` | Session | Initial authenticated client state. |
| POST | `/api/change-history/undo` | Session + CSRF | Apply an undo from the change history. |
| POST | `/api/change-history/undo-turn` | Session + CSRF | Undo every tracked write of one Coach turn. |
| POST | `/api/chat/cancel` | Session + CSRF | Cancel running Coach work of this session. |
| GET | `/api/chat/history` | Session | Coach conversation history page, optionally searched. |
| GET | `/api/chat/receipt` | Session | Receipt of one Coach turn. |
| POST | `/api/chat/reset` | Session + CSRF | Reset the Coach conversation; needs `{"confirmed": true}`, else 400 `confirmation_required`. |
| GET | `/api/chat/status` | Session | Status of this session's Coach work. |
| POST | `/api/chat/stream` | Session + CSRF | Stream one Coach turn as server-sent events. |
| POST | `/api/coach/actions/cancel` | Session + CSRF | Cancel a Coach proposal. |
| POST | `/api/coach/actions/confirm` | Session + CSRF | Confirm a Coach proposal. |
| POST | `/api/coach/actions/execute` | Session + CSRF | Execute a confirmed Coach proposal. |
| GET | `/api/context-preview` | Session | Preview of the context the Coach receives. |
| GET | `/api/diagnostics` | Session | Diagnostic report. |
| POST | `/api/diagnostics/delete` | Session + CSRF | Clear the stored diagnostics. |
| POST | `/api/equipment/maintenance` | Session + CSRF | Record equipment maintenance. |
| POST | `/api/external-calendar/sync` | Session + CSRF | Queue a provider synchronization, or a targeted refresh of the external calendars or the weather. |
| GET | `/api/feedback` | Session | Activity feedback projection. |
| POST | `/api/garmin/disconnect` | Session + CSRF | Garmin login, MFA code or disconnect (see below). |
| GET | `/api/garmin/full-resync` | Session | State and outcome of the full resync started in the background. |
| POST | `/api/garmin/full-resync` | Session + CSRF | Start the confirmed full resync in the background (`202` with `operation_id`; `200` `already_running` while one runs). |
| POST | `/api/garmin/login` | Session + CSRF | Garmin login, MFA code or disconnect (see below). |
| POST | `/api/garmin/login/mfa` | Session + CSRF | Garmin login, MFA code or disconnect (see below). |
| POST | `/api/garmin/sync` | Session + CSRF | Queue a provider synchronization, or a targeted refresh of the external calendars or the weather. |
| GET | `/api/health` | Public | Liveness and maintenance state. |
| GET | `/api/library` | Session | Workout library page. |
| POST | `/api/login` | Public | Create a session. |
| POST | `/api/logout` | Session + CSRF | End the current session. |
| GET | `/api/logs` | Session | Recent redacted log entries. |
| POST | `/api/logs/delete` | Session + CSRF | Clear the server log. |
| GET | `/api/logs/download` | Session | Download the redacted server log as JSON lines. |
| POST | `/api/metric-export/automatic` | Session + CSRF | Intervals.icu write: switch the automatic metric export (consent per field); needs `confirmed: true`, a boolean `enabled`, `source: "garmin"` and `provider: "intervals"`. |
| GET | `/api/nutrition/day` | Session | Nutrition day summary with macro ranges. |
| POST | `/api/nutrition/entry` | Session + CSRF | Log a meal; returns a `change` undo reference. |
| POST | `/api/nutrition/entry/add-product` | Session + CSRF | Add a saved product to a logged meal. |
| POST | `/api/nutrition/entry/delete` | Session + CSRF | Delete a logged meal. |
| GET | `/api/nutrition/products` | Session | Product search, barcode lookup or food database entries. |
| POST | `/api/nutrition/products` | Session + CSRF | Save a product. |
| PUT | `/api/nutrition/products` | Session + CSRF | Update a confirmed saved product. |
| POST | `/api/nutrition/products/archive` | Session + CSRF | Archive a product. |
| POST | `/api/nutrition/products/database/delete` | Session + CSRF | Forget a food database entry. |
| POST | `/api/nutrition/products/database/refresh` | Session + CSRF | Re-check one food database entry or own product online now; gaps fill. |
| POST | `/api/nutrition/products/extract` | Session + CSRF | Extract a product from a label photo. |
| POST | `/api/nutrition/products/favorite` | Session + CSRF | Mark or unmark a product as favorite. |
| POST | `/api/nutrition/products/lookup` | Session + CSRF | Look a product up by barcode. |
| POST | `/api/nutrition/refresh` | Session + CSRF | Run a targeted nutrition refresh. |
| GET | `/api/nutrition/week` | Session | Nutrition week summary. |
| POST | `/api/nutrition/yazio/check` | Session + CSRF | Explicitly check Yazio authentication; the result is kept in memory. |
| GET | `/api/nutrition/yazio/status` | Session | Last local Yazio authentication check, without contacting Yazio. |
| GET | `/api/performance` | Session | Performance projection. |
| GET | `/api/plan` | Session | Planning projection. |
| POST | `/api/planned-units/{id}/focus` | Session + CSRF | Set or clear `session_focus` and `strength_intensity` of a planned unit; returns the unit. |
| POST | `/api/planned-units/{id}/garmin-exercise` | Session + CSRF | Assign the Garmin exercise of one strength exercise (`exercise_index`, `garmin_exercise`, `expected_payload_hash`). |
| GET | `/api/privacy/backup` | Session | Download the encrypted database backup. |
| POST | `/api/privacy/delete` | Session + CSRF | Delete the local athlete data after the typed confirmation (`confirm`). |
| GET | `/api/privacy/delete/preview` | Session | Preview of the local data deletion. |
| GET | `/api/privacy/export` | Session | Download the privacy export archive. |
| GET | `/api/privacy/gps` | Session | GPS-track setting and stored-track count. |
| POST | `/api/privacy/gps` | Session + CSRF | Turn GPS-track storage on or off (`enabled`). |
| POST | `/api/privacy/gps/delete` | Session + CSRF | Delete every stored GPS track and the routes derived from them after the typed confirmation (`confirm`). |
| POST | `/api/privacy/restore` | Session + CSRF | Restore a database backup; ends every session. |
| GET | `/api/profile` | Session | Profile and competitions; also `first_threshold_estimate` (percent of the run threshold HR, bpm, session count, quality, date range) or null. |
| PUT | `/api/profile` | Session + CSRF | Patch only the submitted profile fields; with `sync_body_to_garmin: true` a changed weight or body fat is also exported to Garmin and the result carries `garmin_body_export`. |
| POST | `/api/profile/first-threshold/adopt` | Session + CSRF | Store the shown first threshold estimate (`percent_lthr`) with origin `estimated`; `replace_measured: true` replaces a measured value. |
| GET | `/api/providers/connections` | Session | Last local connection check per provider, without contacting any provider. |
| POST | `/api/providers/{provider}/check` | Session + CSRF | Explicitly run one bounded read-only connection check for an OpenAI, Intervals.icu, Garmin, Wahoo or Open-Meteo provider and record an in-memory result. |
| GET | `/api/readiness` | Public | Readiness status; 503 while not ready. |
| POST | `/api/routes/rename` | Session + CSRF | Rename a recognised route (`route_id`, `name`: 1 to 60 characters without control characters); answers `route_id` and `label` only. |
| PUT | `/api/settings/calendar-display` | Session + CSRF | Update the calendar display settings. |
| PUT | `/api/settings/credentials` | Session + CSRF | Save or clear provider credentials in the encrypted database (see below). |
| PUT | `/api/settings/model` | Session + CSRF | Select the Coach model. |
| PUT | `/api/settings/service-tier` | Session + CSRF | Select the OpenAI service tier. |
| PUT | `/api/settings/thinking-level` | Session + CSRF | Select the thinking level. |
| GET | `/api/state/events` | Session | Authenticated state event stream. |
| POST | `/api/sync/jobs` | Session + CSRF | Queue a sync job. |
| GET | `/api/sync/jobs/{id}` | Session | Result of one sync job. |
| GET | `/api/sync/status` | Session | Synchronization status. |
| POST | `/api/transcribe` | Session + CSRF | Transcribe short-lived voice input. |
| GET | `/api/wahoo/callback` | Public | Wahoo OAuth redirect target; answers 302 to the app (see below). |
| POST | `/api/wahoo/connect` | Session + CSRF | Start the Wahoo OAuth connection or disconnect Wahoo. |
| POST | `/api/wahoo/disconnect` | Session + CSRF | Start the Wahoo OAuth connection or disconnect Wahoo. |
| GET | `/api/wahoo/full-resync` | Session | State and outcome of the full resync started in the background. |
| POST | `/api/wahoo/full-resync` | Session + CSRF | Start the confirmed full resync in the background (`202` with `operation_id`; `200` `already_running` while one runs). |
| POST | `/api/wahoo/sync` | Session + CSRF | Queue a provider synchronization, or a targeted refresh of the external calendars or the weather. |
| GET | `/api/weather` | Session | Weather projection. |
| POST | `/api/weather/sync` | Session + CSRF | Queue a provider synchronization, or a targeted refresh of the external calendars or the weather. |
| GET | `/api/zones` | Session | Local and provider zone configurations. |
| PUT | `/api/zones` | Session + CSRF | Save one local zone configuration; returns a receipt with an undo reference. |
| PUT | `/api/zones/remove` | Session + CSRF | Remove one local zone configuration; needs `confirmed: true`. |
<!-- END GENERATED ROUTES -->

## Wahoo callback

`/api/wahoo/callback` is the only API GET that needs no session: the
SameSite=Strict session cookies are not sent on Wahoo's cross-site redirect.
Its only accepted credential is the single-use, expiring `state` stored on the
server by `POST /api/wahoo/connect`.

## Activity identifiers

Activity routes accept the local session ID (`act_...`) or the provider activity
ID of one of the session's records, as long as that ID names one session. The
Intervals.icu ingest store was removed by the #1728 purge of release 2.0.0; its
activity IDs no longer resolve.

- `GET /api/activities` items carry the local session `id` and `record_ids`
  (provider to provider activity ID). `GET /api/activities/{id}` serves the
  `activity_detail.v1` document of the session whatever form the ID has; an
  unknown or ambiguous ID returns `404` (`activity_details_not_found`).
- The list `cursor` is versioned:
  `{"v": 3, "after": [started_at, id], "day": "YYYY-MM-DD"}`, base64url-encoded.
  Any other version or an unrecognized cursor returns the first page.
- `POST /api/activities/{id}/feedback` and the Coach activity tools (feedback,
  equipment assignment, session confirmation) accept either form and store the
  data under the live session the ID leads to. A reference that leads to no
  live session is passed through unchanged and receives the route's existing
  not-found or validation response.
- `POST /api/activities/{id}/session` confirms, splits, merges or deletes one
  session bundle (`action`: `confirm`, `split` with `member_id`, `merge` with
  `other_id`, `delete` with `confirmed: true`) and returns the new
  `session_bundle`.

## Provider credentials and Garmin login

These routes are reached from the provider cards under **Mehr > Anbindungen**. They never
return a secret: the response is the credential status only.

- `PUT /api/settings/credentials` takes a JSON object whose keys are credential
  fields (`openai_api_key`, `openai_base_url`, `intervals_api_key`,
  `intervals_athlete_id`, `garmin_personal_api_key`,
  `garmin_personal_api_key_expires` (ISO date; changing the key without it
  clears the stored date), `wahoo_client_id`,
  `wahoo_client_secret`, `garmin_email`, `yazio_email`, `yazio_password`).
  `garmin_email` and `yazio_email` are reported as configured only, never
  echoed back; `garmin_email` has no UI field and pairs with the
  environment `GARMIN_PASSWORD` fallback. A string
  stores the value; `null` or a blank string clears the value stored in the app,
  so the environment value applies again. Each field is validated server-side.
  Setting `openai_base_url`, `wahoo_client_id` or `wahoo_client_secret` (not
  clearing them) also needs the `APP_PASSWORD` in the body field `app_password`;
  a missing or wrong password answers 403 and changes nothing. The password is
  compared in constant time, rate limited and never stored.
  The response is the credential status: `fields` with per field `source`
  (`db`, `env` or `none`), `configured`, and `value` only for non-secret
  fields, plus `garmin_connected`, `garmin_connection_source`,
  `openai_configured`, `intervals_configured`, `wahoo_configured`,
  `yazio_configured` and `garmin_connection` (`connected`, `source`,
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
