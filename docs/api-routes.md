# HTTP API Routes

This is the HTTP contract of every route registered by `backend/http_api` in
the current build. All routes use the same origin. `Session` means an
authenticated session cookie; `Session + CSRF` means that session plus the
`X-CSRF-Token` header. The request handler checks the access level before any
route code runs; a path that is not in the table answers 404 (an unknown POST
or PUT only after the session and CSRF checks).

The maintenance gate column says where the request handler enters the
maintenance operation gate, which answers 503 `maintenance` during a restore:
`before access` (every PUT, before authentication), `after access` (a POST,
after the session and CSRF checks; the session is checked again inside the
gate) or `no`. Login, logout, chat cancellation and the restore itself are
POST routes outside it; logout enters it only to end the session. GET routes
do not enter it, except the Wahoo callback inside its handler while it
completes the authorization.

The route contracts list only route-specific errors. Every route can also
answer the common errors: 401 without a valid session, 403 without a valid
CSRF token, 429 when rate limited, 503 during maintenance or while the
database is busy, 400, 413 or 415 for a malformed, oversized or non-JSON
request body, and 500 for an unexpected failure. Errors are JSON with a German
`error` message and no secret or raw provider text.

Everything between the markers is generated from the route table
(`backend/http_api/route_table.py`): the purpose and the contract are each
handler's docstring. Regenerate it with
`python tests/test_api_routes_doc.py --write`.

<!-- BEGIN GENERATED ROUTES -->
| Method | Path | Access | Maintenance gate | Purpose |
| --- | --- | --- | --- | --- |
| GET | `/api/activities` | Session | no | Activity list page; items carry the local session `id` and `record_ids`. |
| GET | `/api/activities/{id}` | Session | no | The `activity_detail.v1` document of one session (local or provider id). |
| POST | `/api/activities/{id}/feedback` | Session + CSRF | after access | Save, edit or clear the athlete's feedback of one activity. |
| POST | `/api/activities/{id}/session` | Session + CSRF | after access | Confirm, split, merge or delete one session bundle, with a change receipt. |
| GET | `/api/analysis/power-profiles` | Session | no | Analysis projection: power profiles or training records. |
| POST | `/api/analysis/refresh` | Session + CSRF | after access | Run a targeted refresh of one analysis area. |
| GET | `/api/analysis/training-records` | Session | no | Analysis projection: power profiles or training records. |
| GET | `/api/auth/status` | Public | no | Current login status. |
| GET | `/api/bootstrap` | Session | no | Initial authenticated client state. |
| POST | `/api/change-history/undo` | Session + CSRF | after access | Apply an undo from the change history. |
| POST | `/api/change-history/undo-turn` | Session + CSRF | after access | Undo every tracked write of one Coach turn. |
| POST | `/api/chat/cancel` | Session + CSRF | no | Cancel running Coach work of this session. |
| GET | `/api/chat/history` | Session | no | Coach conversation history page, optionally searched. |
| GET | `/api/chat/receipt` | Session | no | Receipt of one Coach turn. |
| POST | `/api/chat/reset` | Session + CSRF | after access | Reset the Coach conversation. |
| GET | `/api/chat/status` | Session | no | Status of this session's Coach work. |
| POST | `/api/chat/stream` | Session + CSRF | after access | Stream one Coach turn as server-sent events. |
| POST | `/api/coach/actions/cancel` | Session + CSRF | after access | Cancel a Coach proposal. |
| POST | `/api/coach/actions/confirm` | Session + CSRF | after access | Confirm a Coach proposal. |
| POST | `/api/coach/actions/execute` | Session + CSRF | after access | Execute a confirmed Coach proposal. |
| GET | `/api/context-preview` | Session | no | Preview of the context the Coach receives. |
| GET | `/api/diagnostics` | Session | no | Diagnostic report. |
| POST | `/api/diagnostics/delete` | Session + CSRF | after access | Clear the stored diagnostics. |
| POST | `/api/equipment/maintenance` | Session + CSRF | after access | Record one maintenance entry for a piece of equipment, stored locally. |
| POST | `/api/external-calendar/sync` | Session + CSRF | after access | Queue a provider synchronization, or a targeted refresh of the external calendars or the weather. |
| GET | `/api/feedback` | Session | no | Activity feedback projection. |
| POST | `/api/garmin/disconnect` | Session + CSRF | after access | Connect Garmin with credentials or an MFA code, or disconnect it. |
| GET | `/api/garmin/full-resync` | Session | no | State and outcome of the full resync started in the background. |
| POST | `/api/garmin/full-resync` | Session + CSRF | after access | Start the confirmed full resync in the background (`202` with `operation_id`; `200` `already_running` while one runs). |
| POST | `/api/garmin/login` | Session + CSRF | after access | Connect Garmin with credentials or an MFA code, or disconnect it. |
| POST | `/api/garmin/login/mfa` | Session + CSRF | after access | Connect Garmin with credentials or an MFA code, or disconnect it. |
| POST | `/api/garmin/sync` | Session + CSRF | after access | Queue a provider synchronization, or a targeted refresh of the external calendars or the weather. |
| GET | `/api/health` | Public | no | Liveness and maintenance state. |
| GET | `/api/library` | Session | no | Workout library page. |
| POST | `/api/login` | Public | no | Create a session. |
| POST | `/api/logout` | Session + CSRF | no | End the current session. |
| GET | `/api/logs` | Session | no | Recent redacted log entries. |
| POST | `/api/logs/delete` | Session + CSRF | after access | Clear the server log. |
| GET | `/api/logs/download` | Session | no | Download the redacted server log as JSON lines. |
| POST | `/api/metric-export/automatic` | Session + CSRF | after access | Intervals.icu write: switch the automatic metric export (consent per field). |
| GET | `/api/nutrition/day` | Session | no | Nutrition day summary with macro ranges. |
| POST | `/api/nutrition/entry` | Session + CSRF | after access | Log a meal; returns a `change` undo reference. |
| POST | `/api/nutrition/entry/add-product` | Session + CSRF | after access | Add a saved product to a logged meal as one more component. |
| POST | `/api/nutrition/entry/delete` | Session + CSRF | after access | Delete a logged meal. |
| GET | `/api/nutrition/products` | Session | no | Product search, barcode lookup or food database entries. |
| POST | `/api/nutrition/products` | Session + CSRF | after access | Save a confirmed product. |
| PUT | `/api/nutrition/products` | Session + CSRF | before access | Update a confirmed saved product. |
| POST | `/api/nutrition/products/archive` | Session + CSRF | after access | Archive a product. |
| POST | `/api/nutrition/products/database/delete` | Session + CSRF | after access | Forget a food database entry. |
| POST | `/api/nutrition/products/database/refresh` | Session + CSRF | after access | Re-check one food database entry or own product online now; gaps fill. |
| POST | `/api/nutrition/products/extract` | Session + CSRF | after access | Extract a product from a label photo; the image is not stored. |
| POST | `/api/nutrition/products/favorite` | Session + CSRF | after access | Mark or unmark a product as favorite. |
| POST | `/api/nutrition/products/lookup` | Session + CSRF | after access | Look a product up by barcode or name, local products first. |
| POST | `/api/nutrition/refresh` | Session + CSRF | after access | Run a targeted nutrition refresh. |
| GET | `/api/nutrition/week` | Session | no | Nutrition week summary of the closed days before today. |
| POST | `/api/nutrition/yazio/check` | Session + CSRF | after access | Explicitly check Yazio authentication; the result is kept in memory. |
| GET | `/api/nutrition/yazio/status` | Session | no | Last local Yazio authentication check, without contacting Yazio. |
| GET | `/api/performance` | Session | no | Performance projection. |
| GET | `/api/plan` | Session | no | Planning projection. |
| POST | `/api/planned-units/{id}/focus` | Session + CSRF | after access | Set or clear the focus of a planned unit without a remote write. |
| POST | `/api/planned-units/{id}/garmin-exercise` | Session + CSRF | after access | Assign the Garmin catalogue exercise of one strength exercise of a unit. |
| GET | `/api/privacy/backup` | Session | no | Download the encrypted database backup. |
| POST | `/api/privacy/delete` | Session + CSRF | after access | Delete the local athlete data after the typed confirmation (`confirm`). |
| GET | `/api/privacy/delete/preview` | Session | no | Preview of the local data deletion. |
| GET | `/api/privacy/export` | Session | no | Download the privacy export archive. |
| GET | `/api/privacy/gps` | Session | no | GPS-track setting and stored-track count. |
| POST | `/api/privacy/gps` | Session + CSRF | after access | Turn GPS-track storage on or off (`enabled`). |
| POST | `/api/privacy/gps/delete` | Session + CSRF | after access | Delete every stored GPS track and the routes derived from them after the typed confirmation (`confirm`). |
| POST | `/api/privacy/restore` | Session + CSRF | no | Restore a database backup; ends every session. |
| GET | `/api/profile` | Session | no | Profile, competitions and the first threshold estimate. |
| PUT | `/api/profile` | Session + CSRF | before access | Patch only the submitted profile fields. |
| POST | `/api/profile/first-threshold/adopt` | Session + CSRF | after access | Adopt the shown first threshold estimate into the profile. |
| GET | `/api/providers/connections` | Session | no | Last local connection check per provider, without contacting any provider. |
| POST | `/api/providers/{provider}/check` | Session + CSRF | after access | Explicitly run one bounded read-only connection check for an OpenAI, Claude, Intervals.icu, Garmin, Wahoo or Open-Meteo provider and record an in-memory result. |
| GET | `/api/readiness` | Public | no | Readiness status; 503 while not ready. |
| POST | `/api/routes/rename` | Session + CSRF | after access | Rename one recognised activity route; nothing is written remotely. |
| PUT | `/api/settings/calendar-display` | Session + CSRF | before access | Update the calendar display settings. |
| PUT | `/api/settings/credentials` | Session + CSRF | before access | Save or clear provider credentials in the encrypted database. |
| PUT | `/api/settings/model` | Session + CSRF | before access | Select the Coach model. |
| PUT | `/api/settings/service-tier` | Session + CSRF | before access | Select the OpenAI service tier. |
| PUT | `/api/settings/thinking-level` | Session + CSRF | before access | Select the thinking level. |
| GET | `/api/state/events` | Session | no | Authenticated state event stream. |
| POST | `/api/sync/jobs` | Session + CSRF | after access | Queue a sync job. |
| GET | `/api/sync/jobs/{id}` | Session | no | Result of one sync job. |
| GET | `/api/sync/status` | Session | no | Synchronization status. |
| POST | `/api/transcribe` | Session + CSRF | after access | Transcribe short-lived voice input. |
| GET | `/api/wahoo/callback` | Public | no | Wahoo OAuth redirect target; answers 302 to the app. |
| POST | `/api/wahoo/connect` | Session + CSRF | after access | Start the Wahoo OAuth connection or disconnect Wahoo. |
| POST | `/api/wahoo/disconnect` | Session + CSRF | after access | Start the Wahoo OAuth connection or disconnect Wahoo. |
| GET | `/api/wahoo/full-resync` | Session | no | State and outcome of the full resync started in the background. |
| POST | `/api/wahoo/full-resync` | Session + CSRF | after access | Start the confirmed full resync in the background (`202` with `operation_id`; `200` `already_running` while one runs). |
| POST | `/api/wahoo/sync` | Session + CSRF | after access | Queue a provider synchronization, or a targeted refresh of the external calendars or the weather. |
| GET | `/api/weather` | Session | no | Weather projection. |
| POST | `/api/weather/sync` | Session + CSRF | after access | Queue a provider synchronization, or a targeted refresh of the external calendars or the weather. |
| GET | `/api/zones` | Session | no | Local and provider zone configurations. |
| PUT | `/api/zones` | Session + CSRF | before access | Save one local zone configuration. |
| PUT | `/api/zones/remove` | Session + CSRF | before access | Remove one local zone configuration. |

## Route contracts

### `GET /api/activities`

Request: query `cursor` (opaque `next_cursor` of the previous page,
base64url JSON `{"v": 3, "after": [started_at, id], "day": "YYYY-MM-DD"}`;
any other version or an unrecognized cursor returns the first page),
`limit` (1 to 250, default 100; unparsable gives 100) and `days` (-1 for
all, else clamped to 1 to 3650; default and unparsable value -1).

Response: 200 with `snapshot_synced_at`, `activities` (newest session
first; per item the local session `id`, `record_ids` mapping each provider
to its activity id, and the attached feedback), `next_cursor` (null on the
last page), `limit` and `days`.

Errors: none beyond the common ones.

### `GET /api/activities/{id}`

Request: path `id`, URL-decoded: the local session id (`act_...`) or the
provider activity id of one of the session's records, as long as it
names one session; no body.

Response: 200 with `ok`, the document (`contract`, `session`, `metrics`,
`streams`, `laps`, `zones`, `strength_sets`, `analysis`, `detail_data`
and more, plus `weather` and `route` when stored, and `data_scope`),
and `session_bundle` (the session's provider copies and merge
candidates; null when the session is not live).

Errors: 400 `invalid_activity_request` "Die Aktivität konnte nicht
eindeutig zugeordnet werden." when the id is empty or longer than 200
characters; 404 `activity_details_not_found` "Diese Aktivität ist lokal
nicht vorhanden." when the id is unknown, ambiguous or has no records.

### `POST /api/activities/{id}/feedback`

Request: path `{id}`, a local session id or the provider activity id of one
of the session's records; the feedback is stored under the live session.
JSON body, every field optional, an omitted field keeps its stored value:
`notes` (string, trimmed, cut to 4000 characters), `session_rpe` (number 0
to 10 or `null`), `deviation_reason` (string, cut to 500 characters),
`purpose` (`training`, `race`, `commute`, `warmup`, `cooldown`, or `null`
or `""` to clear), `activity_name` (cut to 200) and `activity_date` (cut
to 40). Clearing every content field removes the feedback.

Response: 200 `{"status": "ok", "activity_feedback", "change",
"session_rpe_load"}`. `activity_feedback` is the effective feedback
(`activity_id`, `activity_name`, `activity_date`, `notes`, `session_rpe`,
`deviation_reason`, `created_at`, `updated_at`, `session_rpe_rated_at`,
`purpose`), `null` after clearing; `change` is the undo reference;
`session_rpe_load` is left out when its read fails.

Errors: 400 "Der Aktivitäts-RPE muss zwischen 0 und 10 liegen."; 400 "Die
Art der Einheit ist unbekannt." for another `purpose`; 400 "Die Aktivität
konnte nicht eindeutig zugeordnet werden." for an id longer than 200
characters; 409 "Die Aktivität lässt sich keiner Einheit eindeutig
zuordnen; die Art der Einheit kann nicht markiert werden." for a `purpose`
on an id that leads to no single session; 409 "Zu viele Rückmeldungen für
diese Einheit, um sie mit Undo zu ändern." A body with non-empty
`notes`, a non-null `session_rpe`, a non-empty `deviation_reason` or a
`purpose` is a save only for a live session: 404 "Die Aktivität ist im
aktuellen lokalen Trainingssnapshot nicht vorhanden." otherwise.

### `POST /api/activities/{id}/session`

Request: path `{id}`, a local session id (`act_...`; a merged alias leads to
its survivor); JSON body `{"action": string}` with `action` one of
`confirm`, `split` (`member_id`: session id of the provider copy to detach),
`merge` (`other_id`: session id of the other session) or `delete`
(`confirmed: true` required). Records and provider data are not changed;
nothing is deleted at a provider.

Response: 200 `{"status", "activity_id", "change", "session_bundle"}`.
`status` is `confirmed`, `split`, `merged` or `deleted`; `change` is the
undo reference; `session_bundle` is the current bundle of `activity_id`
(`activity_id`, `link_kind`, `athlete_confirmed`, `members`,
`merge_candidates`), `null` when that session is no longer live.

Errors: 400 "Unbekannte Korrektur." for a missing or unknown `action`; 409
"Das Löschen muss bestätigt werden." for `delete` without `confirmed:
true`; 404 "Diese Aktivität ist nicht (mehr) vorhanden." when `id` (or
`other_id`) names no live session. Split: 409 "Diese Aufzeichnung gehört
nicht zu der Aktivität." for a `member_id` outside the bundle, 409 "Die
Aktivität besteht nur aus einer Aufzeichnung." for a single copy. Merge:
409 "Beide Angaben bezeichnen dieselbe Aktivität." for one session, 409
"Nur Aktivitäten desselben Tages können zusammengeführt werden.", 409
"Beide Aktivitäten enthalten eine Aufzeichnung derselben Quelle und können
nicht zusammengeführt werden." Any action: 409 "Diese Aktivität ist zu
groß für eine rücknehmbare Korrektur." beyond 16 touched sessions.

### `GET /api/analysis/power-profiles`, `GET /api/analysis/training-records`

Request: `power-profiles` takes no query and no body. `training-records`
takes the optional query `record_type` (only `equipment`) and `record_id`
(a UUID, required with `record_type`); no body.

Response: 200. `power-profiles`: `status` (`ok` or `insufficient_data`),
`best`, `critical_power`, `power_meter_changes`, `activities`, `windows`
(keys `28` and `90`), `running`, `method`, `method_version`,
`input_fingerprint` and `scope`. `training-records`: `{"equipment": object}`
without query, `{"record_type": "equipment", "record": object}` for one
record.

Errors: `training-records` only: 400 "Unbekannte Datensatzart."; 400
"Ungültige Datensatz-ID."; 503 "Einzelne Trainingsdatensätze sind nicht
verfügbar.". `power-profiles`: none beyond the common ones.

### `POST /api/analysis/refresh`

Request: JSON body `{"area": string, "days": integer}`. `area` is required:
`load`, `performance`, `recovery` or `sessions`. `days` is optional, `14` or
`84`, and only for `load` and `recovery` (default 84 for `load`, 14 for
`recovery`); the other areas use fixed windows.

Response: 200 with `area`, `status` (`ok`, `partial`, `already_running` or
`failed`), `refreshed_sources`, `incomplete_sources`, `pending_sources`,
`not_refreshed_sources` (source names) and `source_status` (per source name
its status string). Garmin is read for every area, Wahoo also for
`sessions` and `performance`; a source that is not configured is left out.

Errors: 400 "Ungültiger Analysebereich."; 400 "Ungültiger Analysezeitraum.";
503 `analysis_refresh_unavailable` "Die gezielte Aktualisierung ist nicht
verfügbar.".

### `GET /api/auth/status`

Request: no body; the session cookie is read if present.

Response: 200 with `authenticated` (boolean) and `maintenance` (`active`,
`running_operations`).

Errors: none beyond the common ones.

### `GET /api/bootstrap`

Request: no body.

Response: 200 with the bounded, local-only projection of
`PublicBootstrapService.read`, read from one database snapshot. Top-level
keys include `state_versions`, `app`, `messages`, `planned`, `calendar`,
`profile`, `competitions`, `planning`, `external_calendar`, `garmin`,
`intervals`, `wahoo`, `sync`, `sync_settings`, `model`, `service_tier`,
`thinking_level`, `configured`, `credentials`, `usage` and
`provider_status`. Lists that have their own route (`library`,
`activities`, `checkins`) are empty.

Errors: none beyond the common ones.

### `POST /api/change-history/undo`

Request: JSON body `{"change_id": string, "expected_current_hash": string,
"activity_id": string}`. `change_id` is the change-history entry (36
characters, `0-9`, `a-f`, `-`); `expected_current_hash` is the hash from the
undo preview and is required, a missing or different one answers 409;
`activity_id` is optional and only used for `activity_feedback` entries.

Response: 200 `{"status": "undone", "change_id": string, "entity_type":
string, "entity_id": string, "remote_untouched": true}`; for
`activity_feedback` with a string `activity_id` also `session_rpe_load`
(omitted if it cannot be read).

Errors: 400 "Ungültige Änderungshistorie-ID."; 404 "Änderung nicht
gefunden."; 409 "Eine Undo-Aktion kann nicht erneut zurückgenommen
werden."; 400 "Ein Export an einen Anbieter lässt sich nicht zurücknehmen.";
400 "Diese Änderung lässt sich nicht mehr zurücknehmen."; 409 "Die lokale
Änderung wurde inzwischen weiter geändert; Undo wurde abgebrochen."; 400
"Unbekannte lokale Änderung.".

### `POST /api/change-history/undo-turn`

Request: JSON body `{"client_turn_id": string}`, 1 to 120 characters.

Response: 200 `{"status": "undone", "client_turn_id": string,
"coach_changes": object, "remote_untouched": true}`; `coach_changes` is the
turn's change summary with `undone_at` set. All changes are restored in one
transaction or none.

Errors: 400 "Ungültiger Coach-Auftrag."; 404 "Coach-Antwort nicht
gefunden." for an unknown or unfinished turn; 409 "Diese Coach-Antwort hat
nichts geändert."; 409 "Diese Coach-Änderungen wurden bereits
zurückgenommen."; 409 "Diese Coach-Änderungen können nicht gesammelt
zurückgenommen werden."; 409 "Die lokale Änderung wurde inzwischen weiter
geändert; Undo wurde abgebrochen." when a record changed since the turn.

### `POST /api/chat/cancel`

Request: JSON body `{"operation_id": string}`; `operation_id` is optional
and names the attached stream or background turn to cancel.

Response: 200 `{"status": "cancelling", "operation_id": string}` when
running work of this session was signalled, `{"status": "not_running"}`
when there is none.

Errors: 409 "Die angegebene Coach-Anfrage ist nicht mehr aktiv." when
`operation_id` differs from the attached stream's.

The route is not held back by maintenance mode.

### `GET /api/chat/history`

Request: query `cursor` (optional, the `next_cursor` of the previous page),
`limit` (optional, default 100, clamped to 1..100) and `q` (optional search
text, trimmed to 200 characters, substring match on the message content).
No body.

Response: 200 with `generation` (chat generation, changes on a reset),
`messages` (one page, oldest first, going back from the cursor; each has
`id`, `role`, `content`, `created_at` and, when present, `client_turn_id`,
`attachment_names`, `coach_changes`, `coach_failed`, `coach_request_kind`),
`proposed_actions` (this session's open Coach proposals, at most 30),
`next_cursor` (null on the last page), `limit` and `search`.

Errors: 400 `invalid_page_cursor` "Ungültiger Cursor." when `cursor` is not
a cursor this route returned.

### `GET /api/chat/receipt`

Request: query `client_turn_id` (required, 1 to 120 characters). No body.

Response: 200 with the stored receipt of that turn of this session, without
its `session_key`: fields such as `status`, `mode`, `phase`, `operation_id`,
`plan_scope`, `model`, `command_receipts` and `change_summary`, plus
`client_turn_id` and `proposed_actions` (the turn's proposals as stored now,
`status` `expired` once past `expires_at`).

Errors: 400 `invalid_client_turn` "Ungültige Coach-Auftragskennung." when
`client_turn_id` is missing or longer than 120 characters; 404
`command_not_found` "Coach-Auftrag nicht gefunden."; 403
`command_scope_denied` "Dieser Coach-Auftrag gehört zu einer anderen
Sitzung." when another session started the turn.

### `POST /api/chat/reset`

Request: JSON body `{"confirmed": true}` (required); body limit 28 000 000
bytes. Running Coach turns are cancelled first.

Response: 200 `{"status": "ok", "generation": string,
"remote_conversation_deleted": null | false, "message": string}`; `null`
means the remote conversation is deleted in the background.

Errors: 400 `confirmation_required` "Das Zurücksetzen muss bestätigt werden."
unless `confirmed` is `true`; 409 `chat_reset_timeout` "Die laufende
Coach-Anfrage wird noch beendet. Bitte den Chat gleich erneut
zurücksetzen." when the running turn does not stop in time.

### `GET /api/chat/status`

Request: no query, no body.

Response: 200 `{"status": "idle", "operation_id": null}` without Coach
work; `{"status": "running", "operation_id": string}` while a stream is
attached; for a durable background turn also `mode` `background`, `phase`
and `plan_scope`.

Errors: none beyond the common ones.

### `POST /api/chat/stream`

Request: JSON body `{"message": string, "client_turn_id": string,
"request_kind": string, "attachments": array}`; body limit 28 000 000 bytes.
`client_turn_id` is required, at most 120 characters; sending the id of a
turn this session already queued returns that turn instead of a new one.
`message` is trimmed, 1 to 12 000 characters; it may be empty only with
`attachments`, then it becomes "Bitte analysiere die angehängten Dateien.".
`request_kind` is optional: `morning_checkin`, `session_analysis`,
`progress_review`, `block_review`, `plan_week`, `plan_block` or
`adjust_week`. `attachments` is optional, up to 4 objects
`{"name": string, "data": base64 string}` (name 1 to 160 characters without
`/` or a backslash, at most 5 MB each) of GPX, FIT, PNG, JPEG or WebP files.

Response: 200 `text/event-stream`; the response ends after the final event.
Events: `started` `{operation_id}`; `delta` `{text}` (a chunk of reply text);
`heartbeat` `{operation_id}` every 15 s while the turn is queued or running;
`completed` the turn receipt (as `GET /api/chat/receipt`); `background`
`{operation_id, ...}` when the turn goes on without this stream (already
queued, or maintenance is pending); `error` `{reason, message}`. A closed
connection does not cancel the turn.

Errors: before the stream opens, as JSON: 400 `invalid_client_turn`
"client_turn_id ist für Coach-Nachrichten erforderlich." and 409
`chat_already_running` "Für diese Sitzung läuft bereits eine
Coach-Anfrage." when a stream of this session is attached. Once open, a
failure is an `error` event: `invalid_request_kind` "Unbekannte
Coach-Schnellaktion."; `invalid_attachment` "Ungültiger Anhang. Erlaubt: bis
zu 4 GPX-, FIT-, PNG-, JPEG- oder WebP-Dateien mit je höchstens 5 MB.";
`attachment_request_too_large` "Die Anhänge sind zusammen zu groß für eine
Coach-Anfrage. Bitte sende weniger oder kleinere Dateien.";
`invalid_chat_message` "Die Coach-Nachricht ist leer oder zu lang.";
`invalid_client_turn`
"client_turn_id muss eine begrenzte, nicht leere Kennung sein.";
`chat_already_running` "Für diese Sitzung läuft bereits eine Coach-Anfrage."
when another turn of the session is queued or running;
`client_turn_in_progress` "Diese Coach-Nachricht wird bereits verarbeitet.";
`command_scope_denied` "Dieser Coach-Auftrag gehört zu einer anderen
Sitzung."; `attachment_storage_quota` "Der lokale Speicher für Chat-Anhänge
ist ausgeschöpft. Entferne alte Chat-Daten, bevor du weitere Bilder
sendest."; `internal_error` "Interner Serverfehler.".

### `POST /api/coach/actions/cancel`

Request: JSON body `{"proposal_id": string}`, as for confirming.

Response: 200 `{"status": "cancelled", "proposal_id": string}`; its token,
if any, stops working.

Errors: 400 "Ungültige Aktionsvorschau." for a malformed id; 409 "Die
Aktionsvorschau ist nicht mehr offen." when the proposal is not of this
session or is no longer `preview` or `ready`.

### `POST /api/coach/actions/confirm`

Request: JSON body `{"proposal_id": string}`, the `id` of an open proposal
of this session (36 characters, `0-9`, `a-f`, `-`).

Response: 200 `{"status": "ready", "action_token": string,
"proposed_action": object}`. The token is shown once and is what
`POST /api/coach/actions/execute` takes; `proposed_action` has `id`,
`action_type`, `target_system`, `object_ids`, `diff`, `payload_hash`,
`expires_at` and `status`. Confirming a `ready` proposal again issues a new
token.

Errors: 400 "Ungültige Aktionsvorschau." for a malformed id; 404
`proposal_unavailable` "Aktionsvorschau nicht gefunden."; 409
`proposal_used` "Die Aktionsvorschau wurde bereits verwendet." or "Die
Aktionsvorschau wurde bereits bestätigt."; 409 `proposal_expired` "Die
Aktionsvorschau ist abgelaufen.".

### `POST /api/coach/actions/execute`

Request: JSON body `{"action_token": string, "payload_hash": string}`.
`action_token` is required, the token from the confirmation (at least 32
characters, single use). `payload_hash` is optional and, when sent, must
equal the proposal's `payload_hash`.

Response: 200 with the action's result: for `undo_change` the undo result
(`status` `undone`, ...); for a local Coach write the tool result with `ok`
`true` and `status` `applied`; for a remote Coach write the tool result,
with `sync_job_ids` when sync jobs were queued.

Errors: 400 "Ungültiges Coach-Aktionstoken." for a token shorter than 32
characters; 409 `proposal_invalid` "Das Coach-Aktionstoken ist ungültig,
abgelaufen oder bereits verwendet."; 409 `proposal_expired` "Das
Coach-Aktionstoken ist abgelaufen."; 409 `proposal_payload_changed` "Der
bestätigte Aktions-Payload wurde verändert."; 409 `proposal_used` "Das
Coach-Aktionstoken wurde bereits verwendet."; 400 `unknown_coach_action`
"Unbekannte Coach-Aktion."; 409 when the proposal's origin no longer checks
out, "Der freigegebene Coach-Auftrag ist ungültig.", "Der freigegebene
Coach-Auftrag ist nicht mehr gültig.", "Der freigegebene Coach-Auftrag
gehört nicht mehr zu dieser Sitzung." or "Der ursprüngliche Nutzerauftrag
ist nicht mehr verfügbar."; 503 "Die Coach-Aktionsausführung ist nicht
verfügbar.". Validation errors of the underlying write are passed through.

### `GET /api/context-preview`

Request: no query, no body.

Response: 200 with `generated_at`, `snapshot_truncated`,
`snapshot_compacted`, `assembly`, `conversation`, `chat_prompt`,
`structured_athlete_context`, `latest_activities`, `projection`,
`context_text` and `local_training_library` (built by
`CoachContextPreviewService.preview`). It changes no state.

Errors: none beyond the common ones.

### `GET /api/diagnostics`

Request: no body.

Response: 200 with the redacted report of `DiagnosticReportService.report`,
read from one database snapshot. Top-level keys include `generated_at`,
`app`, `runtime`, `configuration`, `openai`, `coach_commands`, `sync`,
`garmin`, `wahoo`, `provider_freshness`, `external_calendar`, `database`,
`plan_sync`, the `canonical_*` sections, `logs` (recent warnings, errors
and INFO entries), `debug_capture` (status and captured request and
response shapes) and `note`. A section that cannot be built is
`{"status": "unavailable"}`.

Errors: none beyond the common ones.

### `POST /api/diagnostics/delete`

Request: no body.

Response: 200 with `ok` (`true`) and `entries` (`0`): the captured
technical diagnostic entries are emptied.

Errors: 500 "Diagnose konnte nicht gelöscht werden." when clearing fails.

### `POST /api/equipment/maintenance`

Request: JSON body `{"equipment_id": string, "date": "YYYY-MM-DD", "notes":
string}` and no other key; `notes` is optional and cut to 1000 characters.
The date must not be before the item's `start_date` or in the future.

Response: 200 `{"ok": true, "stored_locally": true, "maintenance": {"id",
"equipment_id", "date", "notes", "distance_km", "observed_at"}, "change"}`;
`change` is the undo reference. `distance_km` is the item's usage so far,
`null` for a past date of a Garmin-linked item.

Errors: 400 "Ungültige Wartung." for an unknown body key; 400
"Wartungsdatum ungültig." for a `date` that is not an ISO date; 400
"Wartungsgegenstand oder Datum ungültig." for an empty or unmatched
`equipment_id` or a date outside the item's range; 404 "Ausrüstung nicht
gefunden." for a non-empty unknown `equipment_id`.

### `POST /api/external-calendar/sync`, `POST /api/garmin/sync`, `POST /api/wahoo/sync`, `POST /api/weather/sync`

Request: registered for `/api/garmin/sync`, `/api/wahoo/sync`,
`/api/weather/sync` and `/api/external-calendar/sync`. Only
`/api/garmin/sync` reads a JSON object body (required, `{}` suffices):
optional `days` (integer, `-1` for all history or 1 to 90; default the
stored Garmin sync period), which is also stored as the new period. The
other three take no body.

Response: 202 with the queued job (as `GET /api/sync/jobs/{id}`: `id`,
`provider`, `type`, `status`, `progress`, `items`, ...), a `refresh` job
requested by `user`. Its payload holds `reason` (`manual` for Garmin and
Wahoo, `manuell` for the calendar and the weather), for Garmin the
applied `days`, and for the weather `force: true`.

Errors: 400 "Der Synchronisationszeitraum muss eine ganze Zahl sein." when
`days` is not an integer, or "Der Zeitraum für garmin muss -1 oder
zwischen 1 und 90 Tagen liegen." when it is out of range; 409
`not_configured` for Garmin ("Garmin ist nicht konfiguriert. Unter Mehr →
Anbindungen bei Garmin anmelden oder einen Schlüssel der Garmin Personal
API hinterlegen.") and Wahoo ("Wahoo ist nicht verbunden. Bitte Wahoo in
den Einstellungen verbinden.") when the provider is not set up.

### `GET /api/feedback`

Request: no query, no body.

Response: 200 with `checkins` (the latest 30 check-ins), `local_feedback`
(the check-in context) and `activity_feedback` (the activity feedback
context).

Errors: none beyond the common ones.

### `POST /api/garmin/disconnect`, `POST /api/garmin/login`, `POST /api/garmin/login/mfa`

Request: `POST /api/garmin/login` takes `{"email": string, "password":
string}`, each non-blank and at most 512 characters; the password is used
once, never stored. `POST /api/garmin/login/mfa` takes `{"code": string}`
of 4 to 10 digits. `POST /api/garmin/disconnect` reads no field (an empty
object).

Response: 200 `{"status", "connected", "source", "mfa_pending"}`. `status`
is `connected` or `mfa_required` (login, the challenge stays pending for 10
minutes until a code is submitted or a new login starts), `connected` (MFA)
or `disconnected`. Disconnect deletes the stored Garmin tokens and discards
a pending login; stored Garmin data is kept.

Errors: 400 "Ungültige Garmin-Eingabe." for a missing, non-string, blank
or too long `email`, `password` or `code`; 400 "Der MFA-Code ist ungültig.
Bitte erneut eingeben." for a `code` that is not 4 to 10 digits. Login: 422
"Garmin-Anmeldung fehlgeschlagen. Bitte E-Mail und Passwort prüfen." for
rejected credentials, 502 "Garmin ist derzeit nicht erreichbar. Bitte
später erneut versuchen." for any other Garmin failure, 502
"Garmin-Tokens konnten nicht übernommen werden." when the tokens cannot be
taken from the Garmin session. Login and MFA: 409 "Die Garmin-Anmeldung wurde
inzwischen getrennt oder neu gestartet." when a disconnect or newer login
superseded this one. MFA: 409 "Keine Garmin-Anmeldung mit MFA aktiv. Bitte erneut
anmelden." without a pending login, 409 "Die MFA-Anmeldung ist abgelaufen.
Bitte erneut anmelden." after expiry, 422 "Der MFA-Code ist ungültig.
Bitte erneut eingeben." for a wrong code (the login stays pending), 409
"Zu viele falsche MFA-Codes. Bitte die Garmin-Anmeldung neu starten." on
the fifth wrong code, which discards it.

### `GET /api/garmin/full-resync`, `GET /api/wahoo/full-resync`

Request: no body; registered for `/api/garmin/full-resync` and
`/api/wahoo/full-resync`, the path names the provider.

Response: 200 with `running`, `status` (progress text while
running, else null), `last_resync_at`, `last_error` and `outcome`
(null until a run of this process ends, then `operation_id`,
`status` and, after a failure, `reason`).

Errors: none beyond the common ones.

### `POST /api/garmin/full-resync`, `POST /api/wahoo/full-resync`

Request: JSON body `{"confirm": "FULL_RESYNC"}`, required. Registered for
`/api/garmin/full-resync` and `/api/wahoo/full-resync`; the path names the
provider.

Response: 202 with `status` (`"started"`), `source` (the provider id) and
`operation_id`; or 200 with `status` `"already_running"`, `source` and the
`operation_id` of the run in progress. Progress is read with the GET
route of the same path.

Errors: 400 "Zum vollständigen Resync muss FULL_RESYNC bestätigt werden."
when `confirm` is not `FULL_RESYNC`; 503 `not_configured` when the
provider is not set up: "Garmin ist nicht konfiguriert. Unter Mehr →
Anbindungen bei Garmin anmelden oder einen Schlüssel der Garmin Personal
API hinterlegen." or "Wahoo ist nicht verbunden. Bitte Wahoo in den
Einstellungen verbinden."

### `GET /api/health`

Request: no body.

Response: 200 with `status` (`"ok"`) and `maintenance` (`active` boolean,
true during a restore; `running_operations` count).

Errors: none beyond the common ones.

### `GET /api/library`

Request: query `cursor` (opaque `next_cursor` of the previous page; an
invalid cursor is ignored and starts at the first page) and `limit`
(1 to 100, default 100; an unparsable value gives 100).

Response: 200 with `workouts` (active, undated library templates ordered
by sport, name and id, each with the derived `type` and, when Wahoo state
exists, `wahoo_state`), `next_cursor` (null on the last page) and
`limit` (the applied page size).

Errors: none beyond the common ones.

### `POST /api/login`

Request: JSON body `{"password": string}`; no session or CSRF token. A
missing `password` counts as empty. Runs outside the maintenance gate.

Response: 200 with `status` (`"ok"`), `authenticated` (`true`) and `csrf`
(the CSRF token for the `X-CSRF-Token` header). `Set-Cookie` sets the
`ic_session` (HttpOnly) and `ic_csrf` cookies, both `SameSite=Strict` and
valid for 30 days.

Errors: 401 "Ungültiges Passwort." for a wrong password; 429 `rate_limited`
"Zu viele Anmeldeversuche. Erneut versuchen in etwa N Sekunden." after 5
failed attempts within 15 minutes from one client address (only failed
attempts count); 503 "Die sichere App-Konfiguration ist unvollständig."
when the secure configuration is incomplete.

### `POST /api/logout`

Request: no body.

Response: 200 with `status` (`"ok"`); `Set-Cookie` clears the `ic_session`
and `ic_csrf` cookies. The stored session is deleted.

Errors: none beyond the common ones.

### `GET /api/logs`

Request: query `limit` (1 to 500, default 200; a non-integer value gives
200).

Response: 200 with `entries`, the last `limit` redacted entries of the
active log file in log order (objects such as `timestamp`, `level`,
`event`, `message`).

Errors: none beyond the common ones.

### `POST /api/logs/delete`

Request: no body.

Response: 200 with `ok` (`true`) and `cleared` (whether a log file
existed): the rotated log files are removed and the active one is
emptied.

Errors: 500 "Logs konnten nicht gelöscht werden." when a log file cannot
be removed or emptied.

### `GET /api/logs/download`

Request: no body.

Response: 200 `application/x-ndjson` attachment
`pacecraft-server-logs.jsonl`: every entry of the rotated and the active
log file, oldest first, one redacted JSON object per line.

Errors: none beyond the common ones.

### `POST /api/metric-export/automatic`

Request: JSON body `{"confirmed": true, "enabled": boolean, "source":
"garmin", "provider": "intervals"}`, all four required. Optional `fields`:
non-empty list of export field keys (`weight`, `body_fat`, `resting_hr`,
`threshold_pace`, `threshold_hr`, `max_hr`, `ftp`, `run_ftp`), or `field`
with a boolean `field_enabled` to change one field against the stored
consent (not together with `fields`). Without either, enabling keeps the
stored fields or starts with `threshold_pace`, `threshold_hr` and `max_hr`;
`enabled: false` revokes every field.

Response: 200 `{"enabled", "fields", "changes"}`; `fields` lists every
export field as `{"key", "label", "enabled"}`, `changes` the entries whose
consent changed.

Errors: 400 `confirmation_required` "Der automatische Abgleich mit
Intervals.icu muss ausdrücklich bestätigt werden." when `confirmed`,
`provider`, `source` or `enabled` is missing or wrong; 400
`invalid_metric_export` "Die Auswahl der Werte ist ungültig." for an invalid
`fields`, `field` or `field_enabled`.

### `GET /api/nutrition/day`

Request: query `date` (`YYYY-MM-DD`, default today).

Response: 200 `{"ok": true, ...}` with the day of `get_day_summary`: `date`,
`total_kcal`, `total_carbs_g`, `total_protein_g`, `total_fat_g`,
`total_sugar_g`, `total_salt_g`, `known_macro_totals`, `known_intake_totals`,
`entries_without_macros`, `entry_count`, `entries` and `energy_expenditure`; a
macro total is `null` unless every entry reports it. `macro_ranges` maps
`protein_g`, `carbs_g` and `fat_g` to `[low, high]` where weight and training
calendar allow it.

Errors: 400 "Ungültiges Datumsformat '<value>'. Erwartet wird YYYY-MM-DD." for
an invalid `date`.

### `POST /api/nutrition/entry`

Request: JSON body, either `components` alone or one meal. Meal fields:
`description` (cut to 500 characters; required unless `product_id` supplies it),
`kcal` (0 to 10000, or `calories`; required unless `product_id`,
`food_ingredients` or `components` supply it), optional `carbs_g`, `protein_g`,
`fat_g` (0 to 1000, or `carbs`, `carbohydrates`, `protein`, `fat`), `meal_date`
(or `date`, default today), `meal_time` (or `logged_at`; a time or an ISO
timestamp), `logged_time_known` (boolean; `false` needs `meal_type`),
`meal_type` (`breakfast`, `lunch`, `dinner`, `snack`; default derived from the
time), `source` (`manual`, `voice`, `photo`, `coach`; anything else is
`manual`), `packaging_label` (`true` marks label values), `food_ingredients`
(list of `{food_id, amount, unit}`) or `product_id` with `amount` and `unit`
(nutrients calculated from the saved product). `components` is a list of 1 to 20
items `{kind, amount, unit}` plus `product_id` (`local_product`), `food_id`
(`database`) or `name`, `kcal`, `carbs_g`, `protein_g`, `fat_g` (`manual`,
`estimate`, `packaging_label`); `unit` is `g`, `ml` or `portion`. It excludes
`product_id`, `food_ingredients`, `nutrition_basis` and every nutrient field.

Response: 200 `{"ok": true, "entry", "change"}`; `entry` is the stored entry
(`id`, `meal_date`, `logged_at`, `meal_type`, `description`, `kcal`, the macros,
`source`, `nutrition_basis`, `sync_state`, `logged_time_known`), `change` the
undo reference.

Errors: 400 "Beschreibung der Mahlzeit ist erforderlich."; 400 "Kalorienangabe
(kcal) ist erforderlich."; 400 "Kalorien müssen zwischen 0 und 10000 liegen.";
400 "Ungültiges Datumsformat '<value>'. Erwartet wird YYYY-MM-DD."; 400
"Ungültige Uhrzeit '<value>'."; 400 "Bei unbekannter Uhrzeit ist der Mahlzeittyp
erforderlich."; 400 "Ungültiger Mahlzeittyp '<value>'. Erlaubt sind: breakfast,
lunch, dinner, snack."; 400 "Komponenten dürfen nicht mit Einzelzutaten,
Summenwerten oder clientseitiger Herkunft kombiniert werden."; 400 "1 bis 20
Mahlzeitenkomponenten sind erforderlich."; 400 "Ungültige Mahlzeitenkomponente."
and 400 "Einheit muss g, ml oder portion sein." for a malformed component; 404
`nutrition_product_not_found` "Produkt nicht gefunden." and 409
`nutrition_product_archived` "Archivierte Produkte können nicht erfasst werden."
for an unknown or archived product; 400 `food_unit_mismatch` when `unit` differs
from the basis unit of the product; 400 `food_energy_missing` for a component
without calorie value.

### `POST /api/nutrition/entry/add-product`

Request: JSON body `{"id": string, "product_id": string, "amount": number,
"unit": string}`; `id` is the entry id, `amount` is above 0 up to 10000, `unit`
must be the basis unit of the product (`g`, `ml` or `portion`). The entry
becomes a composite of at most 20 components and its description gains " +
<product name>".

Response: 200 `{"ok": true, "entry", "change"}` with the updated entry and the
undo reference.

Errors: 400 "Ungültige Eintrags-ID." for a missing `id`; 404 "Ernährungseintrag
nicht gefunden."; 404 `nutrition_product_not_found` "Produkt nicht gefunden.";
409 `nutrition_product_archived` "Archivierte Produkte können nicht erfasst
werden."; 400 "Komponentenreferenz muss eine Zeichenkette sein." for a missing
`product_id`; 400 "Ungültige Komponentenmenge." or 400 "Komponentenmenge muss
größer als 0 sein."; 400 "Einheit muss g, ml oder portion sein."; 400
`food_unit_mismatch` "Komponenteneinheit stimmt nicht mit dem Produkt überein.";
400 `food_energy_missing` "Für dieses Produkt fehlt der Kalorienwert."; 400
"Eine Mahlzeit kann höchstens 20 Komponenten enthalten."

### `POST /api/nutrition/entry/delete`

Request: JSON body `{"id": string}` (or `entry_id`), the entry id.

Response: 200 `{"ok": true, "status": "ok", "deleted_id", "change"}`; `change`
is the undo reference.

Errors: 400 "id ist erforderlich zum Löschen." for a missing id; 404
"Ernährungseintrag nicht gefunden."

### `GET /api/nutrition/products`

Request: query `q` (search text, optional), `barcode`, `source` and `scope`,
checked in this order. `source=database` lists the stored food database entries
(at most 50, newest first without `q`). `scope=all` lists own products and
stored database foods matching `q`. A `barcode` looks the product up, local
first, then the food databases. Otherwise the active own products matching `q`,
favorites first, at most 50.

Response: 200. `source=database`: `{"ok": true, "foods"}`, each food with
`missing_fields`. `scope=all` and the plain list: `{"ok": true, "products"}`.
Barcode: `{"ok": true, "foods", "product", "local", "source"}` with `source`
`local`, `yazio` or `open_food_facts`, plus a `notice` for a database hit.

Errors: none beyond the common ones.

### `POST /api/nutrition/products`

Request: JSON body `{"confirmed": true, "product": {...}}`, or the product
fields next to `confirmed`. Product fields: `name` (required, at most 200
characters), `brand` (cut to 120), `barcode` (8, 12, 13 or 14 digits, else
dropped), `basis_amount` (above 0 up to 10000) and `basis_unit` (`g`, `ml`,
`portion`), both required, `kcal`, `carbs_g`, `protein_g`, `fat_g`, `sugar_g`,
`fiber_g`, `salt_g` (0 to 10000, empty is unknown), `confidence` (clamped to 0
to 1), `source` (`packaging_label` default, `manual`, `open_food_facts`,
`yazio`, `bls`, `fddb_export`), `source_url` (cut to 500), `external_id` (cut to
200), `id` (saves over that product) and `status` (`active` or `archived`).
Saving a new product with a barcode fills its empty fields from the stored
database foods of that barcode.

Response: 200 `{"ok": true, "product", "change"}` with the stored product and
the undo reference.

Errors: 400 `confirmation_required` "Das Produkt muss ausdrücklich bestätigt
werden."; 400 `invalid_food_extraction` "Ein Produktname ist erforderlich.",
"Ungültiger Wert für <field>.", "Ungültige Bezugsmenge.", "Bezugsmenge muss
zwischen 0 und 10000 liegen." or "Bezugsmenge und Einheit sind erforderlich.";
400 "Ungültige Produktquelle."; 409 `nutrition_product_barcode_conflict` "Diese
EAN ist bereits einem lokalen Produkt zugeordnet."

### `PUT /api/nutrition/products`

Request: JSON body `{"id": string, "confirmed": true, ...}` with the fields to
change, as for the product save; they are merged into the stored product. For a
stored database food only the nutrient values (`kcal`, `carbs_g`, `protein_g`,
`fat_g`, `sugar_g`, `fiber_g`, `salt_g`) can change.

Response: 200 `{"ok": true, "product", "change"}` with the updated product and
the undo reference.

Errors: 400 `confirmation_required` "Das Produkt muss ausdrücklich bestätigt
werden."; 400 "id ist erforderlich zum Aktualisieren."; 404
`nutrition_product_not_found` "Produkt nicht gefunden."; 404 `food_not_found`
"Datenbankeintrag nicht gefunden."; 400 `food_database_field_fixed` "Bei einem
Datenbankeintrag sind nur die Nährwerte änderbar."; the validation errors of the
product save.

### `POST /api/nutrition/products/archive`

Request: JSON body `{"id": string, "confirmed": true}`.

Response: 200 `{"ok": true, "product", "change"}` with the archived product and
the undo reference.

Errors: 400 `confirmation_required` "Das Archivieren muss ausdrücklich bestätigt
werden."; 404 `nutrition_product_not_found` "Produkt nicht gefunden."

### `POST /api/nutrition/products/database/delete`

Request: JSON body `{"id": string, "confirmed": true}`.

Response: 200 `{"ok": true, "id", "status": "removed"}`.

Errors: 400 `confirmation_required` "Das Entfernen muss ausdrücklich bestätigt
werden."; 404 `food_not_found` "Datenbankeintrag nicht gefunden."

### `POST /api/nutrition/products/database/refresh`

Request: JSON body `{"id": string}`, an own product id or a stored database food
id (`off:...` or `yazio:...`). Only empty fields are filled; known values stay.

Response: 200 for an own product: `{"ok": true, "product", "notice", "change"}`
(`change` only when fields were filled); for a database food: `{"ok": true,
"food"}` with `missing_fields` and a `notice` when a source was skipped.

Errors: 409 `nutrition_product_archived` "Archivierte Produkte werden nicht
aktualisiert."; 400 `nutrition_product_barcode_missing` "Zum Aktualisieren
braucht das Produkt eine EAN. Trage sie beim Bearbeiten ein."; 404
`food_not_found` "Datenbankeintrag nicht gefunden."; 409 `not_configured` "Yazio
ist nicht konfiguriert." for a Yazio food without credentials; 502
`food_database_unavailable` "Der Datenbankeintrag konnte nicht aktualisiert
werden."

### `POST /api/nutrition/products/extract`

Request: JSON body `{"image_data_url": string}`, a `data:image/jpeg`,
`image/png` or `image/webp` base64 URL of at most 5 MiB decoded. Without
`image_data_url` the body is validated as an extraction (`name`, `brand`,
`barcode`, `basis_amount`, `basis_unit`, `kcal`, `carbs_g`, `protein_g`,
`fat_g`, `sugar_g`, `fiber_g`, `salt_g`, `confidence`; `name` required). The
body limit is 7 056 044 bytes.

Response: 200 `{"ok": true, "candidate", "extraction", "provenance":
"packaging_label", "requires_confirmation": true}`; `extraction` repeats
`candidate`. Nothing is saved.

Errors: 413 `food_image_too_large` "Das Verpackungsfoto ist zu groß."; 415
`food_image_type` "Nur JPEG-, PNG- oder WebP-Fotos werden unterstützt." or
"Dateityp und Bildinhalt stimmen nicht überein."; 400 `invalid_food_image` "Das
Verpackungsfoto ist ungültig."; 503 `provider_unavailable` "Fotoerkennung ist
nicht verfügbar." or "Der OpenAI-Dienst ist nicht verfügbar."; 502
`invalid_provider_response` "Die Nährwerttabelle konnte nicht gelesen werden.";
400 `invalid_food_extraction` for an invalid candidate (as for the product
save).

### `POST /api/nutrition/products/favorite`

Request: JSON body `{"id": string, "favorite": boolean}`.

Response: 200 `{"ok": true, "product"}` with the updated product.

Errors: 400 "favorite muss true oder false sein."; 404
`nutrition_product_not_found` "Produkt nicht gefunden."

### `POST /api/nutrition/products/lookup`

Request: JSON body `{"barcode": string}` or `{"query": string}` (alias `q`, at
least 2 characters), with the optional `source` `open_food_facts`, `yazio` or
`bls` for a name search. Without a local hit the food databases are asked.

Response: 200 `{"ok": true, "foods", "product", "local", "source", "notice"}`;
`product` is the first hit or `null`; a local hit has `local: true` and `source:
"local"`; `notice` comes with a database hit.

Errors: 400 "Suchbegriff muss mindestens 2 Zeichen enthalten." without a barcode
and a query of fewer than 2 characters; 400 "Suchbegriff muss 2 bis 120 Zeichen
enthalten." for a longer query; 400 "Ungültige Lebensmitteldatenbank." for
another `source`.

### `POST /api/nutrition/refresh`

Request: JSON body `{"area": string, "date": "YYYY-MM-DD", "days": integer}` and
no other key. `area` is `diary`, `week`, `body` or `products`. `date` is
optional: today for `diary` and `body`, yesterday for `week`; for `week` and
`body` it must not lie in the future. `days` is `14` or `84` (default `14` for
`week`, `84` for `body`) and ends at `date`. `diary` refreshes the Garmin energy
expenditure of that day, `week` the Garmin daily totals, `body` the Garmin
weight; `products` only reads the local products and ignores `date` and `days`.

Response: 200 `{"ok": true, "area", ...}`. `diary`: `status`, `meal_status`
(`local`), `summary` (the day as in `GET /api/nutrition/day`) and
`expenditure_refresh`. `products`: `status` `local` and `products` (active own
products). `week` and `body`: the Garmin result, `status` (`ok` or `partial`),
`source`, `data_source`, `start`, `end`, `records`, `synced_at`, or `status`
`partial` with `reason` (`not_configured`, `not_supported`,
`library_unavailable`, `provider_unavailable`) when Garmin cannot be read.

Errors: 400 "Ungültiger Ernährungsbereich." for another `area`; 400 "Ungültiger
Anfrageinhalt." for another key; 400 "Ungültiges Datumsformat '<value>'.
Erwartet wird YYYY-MM-DD." for an invalid `date`; 400 "Der Zeitraum muss 14 oder
84 Tage umfassen."; 400 "Das Datum darf nicht in der Zukunft liegen."; 503
`provider_busy` "Garmin wird bereits aktualisiert."

### `GET /api/nutrition/week`

Request: query `days` (integer, default `7`; `7`, `14` or `84`).

Response: 200 `{"ok": true, "start_date", "end_date", "days", "averages",
"balance_kcal", "balance_days"}`. Each item of `days` has `date`, `intake_kcal`,
`expenditure_kcal`, `balance_kcal`, `energy_expenditure`, the macro totals and
the intake fields; unknown values are `null`. `averages` gives `{"value",
"days"}` per field.

Errors: 400 "Ungültiger Zeitraum." for a non-integer `days`; 400 "Zeitraum muss
7, 14 oder 84 Tage umfassen." for another number.

### `POST /api/nutrition/yazio/check`

Request: JSON object; its content is ignored.

Response: 200 `{"status", "checked_at"}`: `not_configured` (`checked_at` `null`)
without Yazio credentials, else `success`, `auth_failed`, `rate_limited` or
`unavailable` with the check time.

Errors: none beyond the common ones.

### `GET /api/nutrition/yazio/status`

Request: no body.

Response: 200 `{"status", "checked_at"}`. `status` is `not_configured`
(`checked_at` `null`), `unchecked` before the first check, else the result of
the last check (`success`, `auth_failed`, `rate_limited`, `unavailable`) with
its `checked_at`.

Errors: none beyond the common ones.

### `GET /api/performance`

Request: no query, no body.

Response: 200 with `performance` (the current performance context, with
`history` and `training_focus_periods` added; built by
`PublicPerformanceStateService.performance_state`) and `garmin` (the public
Garmin projection).

Errors: none beyond the common ones.

### `GET /api/plan`

Request: query `local` (`1` skips the weather refresh and answers from
stored data; any other value or none refreshes the weather first).

Response: 200 with `plans`, `planned`, `training_calendar`, `calendar`,
`planning_view`, `planning_compliance`, `parallel_cycling`, `weather`,
`external_calendar`, `daily_planning_context`, `planning` and
`coach_quick_actions`, composed by `PublicPlanStateService.read_public`
from one database snapshot.

Errors: none beyond the common ones.

### `POST /api/planned-units/{id}/focus`

Request: path `{id}`, the local unit UUID; JSON body `{"session_focus":
string|null, "strength_intensity": string|null}`. Both fields are always
applied: an omitted or `null` field is cleared. `session_focus` must be a
focus of the unit's sport; `strength_intensity` is `light`, `moderate` or
`heavy` and only for strength units.

Response: 200 `{"status": "local", "local_id", "library_entry"}` with the
updated unit. A focus-only change keeps the Intervals.icu sync state.

Errors: 400 "Ungültige lokale Planungs-ID." for an id that is no UUID; 404
"Lokale Planung nicht gefunden."; 403 "Nur lokale geplante Einheiten können
bearbeitet werden." for a record without a date; 400 `invalid_session_focus`
"Ungültige Art der Einheit für diese Sportart." or "Ungültige
Krafteinheit-Intensität."; 409 `plan_date_conflict` when an external
calendar marker rules out the unit's day.

### `POST /api/planned-units/{id}/garmin-exercise`

Request: path `{id}`, the local unit id; JSON body `{"exercise_index":
integer, "garmin_exercise": string, "expected_payload_hash": string}`. The
index counts into the unit's strength structure from 0; the hash is the
unit's content hash from the read the pick was made on. A name is trimmed,
cut to 80 characters and checked against the Garmin catalogue; the pair is
derived from it. An empty name removes the pick.

Response: 200 `{"status": "local", "local_id", "library_entry"}` with the
updated unit. The unit's Intervals.icu sync state is kept and nothing is
written remotely.

Errors: 404 "Einheit nicht gefunden." for an unknown or deleted unit; 409
`planning_revision_conflict` "Die Einheit wurde inzwischen geändert." for a
missing or outdated `expected_payload_hash`; 400 `invalid_exercise_index`
"Unbekannte Übung." when the unit has no strength structure or the index is
not an integer within it; 400 `invalid_strength_structure` "Unbekannte
Garmin-Übung: ..." with suggestions for a name the catalogue does not know.

### `GET /api/privacy/backup`

Request: no body.

Response: 200 `application/octet-stream` attachment
`pacecraft-database.backup`, a consistent snapshot of the database file
that `POST /api/privacy/restore` accepts.

Errors: 503 "Der Backup-Speicher ist nicht verfügbar." or "Die Datenbank
konnte nicht konsistent als Backup vorbereitet werden."; 413 "Das
Datenbank-Backup überschreitet das Größenlimit."; 507 "Für den
Backup-Download ist nicht ausreichend freier Speicher verfügbar."

### `POST /api/privacy/delete`

Request: JSON body `{"confirm": "LOKALE DATEN LÖSCHEN"}`, required and
compared exactly.

Response: 200 with `status` (`"ok"`), `local_data_deleted` (`true`),
`deleted_categories` (record count per category, as in the preview),
`recovery_copies_failed` and `log_files_failed` (what could not be
erased), `remote_delete_attempted` and `remote_conversation_deleted`
(the OpenAI conversation), `wahoo_revoke_attempted`, `wahoo_revoked` and
`remote_untouched`. The deletion runs under the maintenance gate and also
ends every session.

Errors: 400 "Zum Löschen muss LOKALE DATEN LÖSCHEN bestätigt werden."; 409
"Eine Datenbankwiederherstellung läuft bereits." while another restore or
deletion runs; 409 `maintenance_drain_timeout` "Laufende Aufgaben, etwa
eine Coach-Antwort, werden noch beendet. Es wurde nichts geändert. Bitte
gleich erneut versuchen."

### `GET /api/privacy/delete/preview`

Request: no body.

Response: 200 with `status` (`"preview"`), `confirmation_text` (the text
`POST /api/privacy/delete` requires), `categories` (list of `id`, `label`
and `records`, including the recovery copies and the server log files),
`remote_untouched` (list of statements about data at providers that stays
unchanged) and `openai_conversation` (statement about the OpenAI
conversation).

Errors: none beyond the common ones.

### `GET /api/privacy/export`

Request: no body.

Response: 200 `application/zip` attachment `pacecraft-export.zip`, built
from one database snapshot: `profile.json`, `application_state.json`,
`provider_settings.json`, `planning.json`, `garmin_snapshot.json`,
`weather_cache.json`, one `.jsonl` file per exported table and
`manifest.json`.

Errors: 503 "Der Export-Speicher ist nicht verfügbar."; 507 "Für den
Export ist nicht ausreichend freier Speicher verfügbar."; 408 "Der Export
überschreitet das Zeitlimit."; 413 "Der Export überschreitet das
Größenlimit."

### `GET /api/privacy/gps`

Request: no body.

Response: 200 with `enabled` (whether new GPS tracks are stored),
`stored_tracks` (number of activities holding a track) and
`confirmation_text` (`GPS-SPUREN LÖSCHEN`, required by
`POST /api/privacy/gps/delete`).

Errors: none beyond the common ones.

### `POST /api/privacy/gps`

Request: JSON body `{"enabled": boolean}`, required. Tracks already stored
stay.

Response: 200 with `status` (`"ok"`), `enabled`, `stored_tracks` and
`confirmation_text`, as in `GET /api/privacy/gps`.

Errors: 400 "enabled muss true oder false sein." when `enabled` is not a
boolean.

### `POST /api/privacy/gps/delete`

Request: JSON body `{"confirm": "GPS-SPUREN LÖSCHEN"}`, required and
compared exactly.

Response: 200 with `status` (`"ok"`), `deleted_tracks` (number deleted),
`enabled`, `stored_tracks` and `confirmation_text`. The deletion runs
under the maintenance gate.

Errors: 400 "Zum Löschen muss GPS-SPUREN LÖSCHEN bestätigt werden."; 409
"Eine Datenbankwiederherstellung läuft bereits." while another restore or
deletion runs; 409 `maintenance_drain_timeout` as for
`POST /api/privacy/delete`.

### `POST /api/privacy/restore`

Request: the raw bytes of a backup from `GET /api/privacy/backup` as the
body (no JSON), streamed to a staging file; 1 000 000 000 bytes at most.
Runs outside the maintenance gate and takes it for validation and swap.

Response: 200 with `status` (`"ok"`), `restored` (`true`) and
`previous_database_backup` (file name of the pre-restore copy of the live
database, or null); `Set-Cookie` clears the `ic_session` and `ic_csrf`
cookies, since the restored sessions are deleted.

Errors: 413 "Das Datenbank-Backup ist leer oder zu groß."; 400 "Das
Datenbank-Backup konnte nicht validiert werden: ..." (redacted detail of
at most 300 characters), "Das Backup entspricht keinem unterstützten
Datenbankschema.", "Das Backup entspricht nicht exakt dem aktuellen
Datenbankschema.", "Das Backup enthält ungültige Fremdschlüssel." or
"Die Integritätsprüfung des Backups ist fehlgeschlagen."; 400 for a
schema older than 26 ("Das Backup stammt aus einem Release vor 2.0.5
..."); 503 "SQLCipher ist für die Wiederherstellung nicht verfügbar.";
507 `restore_storage_full`; 500 `restore_storage_failed`; 500
`restored_resume_failed` when the restore succeeded but the background
work could not resume; 409 "Eine Datenbankwiederherstellung läuft
bereits."; 409 `maintenance_drain_timeout`, nothing changed.

### `GET /api/profile`

Request: no query, no body.

Response: 200 with `profile` (every profile field as a string),
`competitions` (up to 100; a past competition carries `result` when a
session is linked to it) and `first_threshold_estimate`: `percent_lthr`,
`bpm`, `sessions`, `quality`, `from`, `to`, `spread_pct`, `source`, or null
without an estimate or when computing it fails.

Errors: none beyond the common ones.

### `PUT /api/profile`

Request: JSON object of profile fields; fields not sent keep their value,
unknown keys are ignored, `null` clears a field, values are trimmed to 4000
characters. Fields: `name`, `goals`, `sports`, `training_background`,
`typical_weekly_volume`, `availability`, `constraints`, `equipment`,
`training_preferences` and its `_running`, `_cycling`, `_swimming`,
`_strength`, `_mobility` variants, `training_model` (`pyramidal`,
`polarized`, `threshold`, `sweet_spot`), `performance_notes`, `weight_kg`
(20 to 300), `body_fat_pct` (1 to 70), `height_cm` (50 to 250), `sex`
(`male`, `female` or empty), `coaching_style`, `timezone` (IANA name),
`weather_location`, `sleep_target_hours` (4 to 12), `fueling_tolerance`,
`first_threshold_pct` (40 to 100, percent of the run threshold HR),
`first_threshold_origin` (`measured`, `estimated` or empty) and
`preferred_source_thresholds`, `_body`, `_hrv`, `_resting_hr`, `_sleep`
(`garmin` or empty). Instead of the percent, `first_threshold_hr` (bpm, 60
to 220) with optional `first_threshold_on` (`YYYY-MM-DD`) is converted with
the run threshold HR of that day and stored as `measured`. With
`sync_body_to_garmin: true` a changed `weight_kg` or `body_fat_pct` is also
exported to Garmin; with `retry_body_to_garmin: true` as well, the export
runs even when unchanged. Neither flag is stored.

Response: 200 with the saved profile (every field as a string); with
`sync_body_to_garmin: true` also `garmin_body_export`: `unchanged`,
`success`, `uncertain`, `rejected`, `unavailable`, `superseded` or
`invalid`. The profile is saved before the export, whatever its outcome.

Errors: 400 "Die Zeitzone muss eine gültige IANA-Zeitzone sein."; 400
"Unbekanntes Trainingsmodell; erlaubt: pyramidal, polarized, threshold,
sweet_spot"; 400 "Unbekannte bevorzugte Quelle; erlaubt: garmin oder leer.";
400 "Unbekanntes Geschlecht; erlaubt: male, female oder leer."; 400 "Das
Gewicht muss zwischen 20 und 300 kg liegen.", "Die Größe muss zwischen 50
und 250 cm liegen.", "Der Körperfettanteil muss zwischen 1 und 70 %
liegen.", "Das Schlafziel muss zwischen 4 und 12 Stunden liegen."; 400
"Die Herkunft der ersten Schwelle muss gemessen oder geschätzt sein."; 400
"Die gemessene erste Schwelle muss zwischen 40 und 100 % LSHF liegen."; 400
"Die gemessene erste Schwelle muss zwischen 60 und 220 bpm liegen."; 400
"Das Messdatum muss das Format JJJJ-MM-TT haben."; 400 "Zu diesem Datum ist
keine Laktatschwelle (LSHF) bekannt, mit der die erste Schwelle in Prozent
gespeichert werden kann.".

### `POST /api/profile/first-threshold/adopt`

Request: JSON body `{"percent_lthr": number, "replace_measured": boolean}`.
`percent_lthr` is required and must equal the current estimate from
`GET /api/profile`; `replace_measured: true` is needed to replace a value
stored with origin `measured`.

Response: 200 `{"profile": object, "first_threshold_estimate": object,
"adopted": boolean}`. The estimate is stored as percent of the run
threshold HR with origin `estimated`; `adopted` is `false` without a profile
write when that value is already stored.

Errors: 409 "Es liegt keine Schätzung der ersten Schwelle vor."; 409 "Die
Schätzung hat sich geändert. Bitte die Anzeige aktualisieren." when
`percent_lthr` differs from the current estimate; 409 "Ein gemessener Wert
ist gespeichert. Zum Ersetzen bitte bestätigen." without
`replace_measured`.

### `GET /api/providers/connections`

Request: no body.

Response: 200 with `providers`, an object keyed by provider id (`openai`,
`anthropic`, `intervals`, `garmin`, `wahoo`, `weather`) whose values hold
`status`, `checked_at` and `guidance`. `status` is `not_configured`,
`unchecked`, `checking`, `unknown` or the result of the last check in
this process (`success`, `auth_failed`, `rate_limited`, `unavailable`,
`scope_missing`, `unsupported`, `misconfigured`, `busy`); `guidance` is
a German recovery hint only for `auth_failed`, else an empty string.

Errors: none beyond the common ones.

### `POST /api/providers/{provider}/check`

Request: path `provider` (`openai`, `anthropic`, `intervals`, `garmin`,
`wahoo` or `weather`); JSON object body, which is ignored (send `{}`).

Response: 200 with `status`, `checked_at` and `guidance` as in
`GET /api/providers/connections`. The check waits at most 45 seconds and
then answers `checking` while it finishes in the background; repeating a
settled check for the same credentials within 10 seconds returns the
stored result without a new provider request.

Errors: 404 `unknown_provider` "Unbekannter Anbieter." for any other
provider id.

### `GET /api/readiness`

Request: no body.

Response: 200 when ready, else 503, with the same body: `status`
(`"ready"` or `"not_ready"`), `ready`, `checks` (booleans `database`,
`schema`, `data_directory`, `maintenance`) and `maintenance` (`active`).

Errors: 503 with the body above while any check fails, including during
a restore.

### `POST /api/routes/rename`

Request: JSON body `{"route_id": string, "name": string}`; `name` is trimmed
and must be 1 to 60 printable characters without control characters.

Response: 200 `{"status": "ok", "route_id", "label"}` with the trimmed name
as `label`.

Errors: 400 "Der Name muss aus 1 bis 60 Zeichen ohne Steuerzeichen
bestehen." for an invalid `name`; 404 "Nicht gefunden." when `route_id`
names no stored route.

### `PUT /api/settings/calendar-display`

Request: JSON body `{"past_weeks": integer, "future_weeks": integer}`, each
0 to 52, at least one required; a field not sent keeps its value.

Response: 200 `{"status": "ok", "past_weeks": integer, "future_weeks":
integer}` with the stored values (defaults 1 and 4).

Errors: 400 "Wochen zurück muss eine ganze Zahl sein." and "Wochen voraus
muss eine ganze Zahl sein."; 400 "Wochen zurück muss zwischen 0 und 52
liegen." and "Wochen voraus muss zwischen 0 und 52 liegen."; 400 "Keine
Kalenderansicht-Einstellungen eingegeben." when neither field is sent.

### `PUT /api/settings/credentials`

Request: JSON object whose keys are credential fields and whose values are
strings (stored after trimming, at most 4096 characters, no control
characters) or `null` / a blank string (clears the value stored in the app,
so the environment value applies again). Fields: `openai_api_key`,
`anthropic_api_key`, `intervals_api_key`, `garmin_personal_api_key`,
`wahoo_client_secret`, `yazio_password`, `openai_base_url`,
`anthropic_base_url` (HTTPS, or HTTP on loopback), `intervals_athlete_id`,
`wahoo_client_id`, `garmin_personal_api_key_expires` (`YYYY-MM-DD`; changing
the key without it clears the stored date), `garmin_email`, `yazio_email`.
Fields not sent keep their value; the whole submission is validated before
anything is written. Setting (not clearing) `openai_base_url`,
`anthropic_base_url`, `wahoo_client_id` or `wahoo_client_secret` also needs
`app_password`, the APP_PASSWORD entered again; it is checked in constant
time before anything is written, rate limited to 10 attempts per 15 minutes
and client address, and never stored. Saving or clearing
`garmin_personal_api_key` or `garmin_email` also resets a paused Garmin
capability.

Response: 200 with the credential status, never a secret value: `fields`
(per field `source` `db`, `env` or `none`, `configured`, and `value` for
`openai_base_url`, `anthropic_base_url`, `intervals_athlete_id`,
`wahoo_client_id` and `garmin_personal_api_key_expires` only),
`garmin_connected`, `garmin_connection_source`, `openai_configured`,
`anthropic_configured`, `intervals_configured`, `wahoo_configured`,
`yazio_configured` and `garmin_connection` (`connected`, `source`,
`mfa_pending`). `garmin_email` and `yazio_email` are reported as configured
only.

Errors: 403 "Das App-Passwort fehlt oder ist falsch. Es wurde nichts
geändert." when `app_password` is missing or wrong for a field above; 400
"Unbekanntes Zugangsdatenfeld."; 400 "Ungültiger Wert für {field}." for a
non-string value, an over-long one or one with control characters; 400
"Ungültiges Ablaufdatum."; 400 "OPENAI_BASE_URL muss HTTPS oder HTTP auf
Loopback verwenden." (`ANTHROPIC_BASE_URL` for the other field).

### `PUT /api/settings/model`

Request: JSON body `{"model": string}`. `model` is `claude-opus`,
`claude-sonnet`, `claude-haiku`, the model configured in the environment,
or, with the default OpenAI base URL, `gpt-6-luna`, `gpt-6-sol`,
`gpt-6.1-sol` or `gpt-6-astra`.

Response: 200 `{"model": string}`.

Errors: 400 "Nicht unterstützte Modellauswahl."; 400 "Für dieses Modell
fehlt der API-Schlüssel unter Mehr › Anbindungen." when the model's provider
has no key.

### `PUT /api/settings/service-tier`

Request: JSON body `{"service_tier": string}`, case-insensitive: `default`,
`fast` or `ultrafast`, as far as the selected model supports it. `fast` needs
`gpt-6-luna`, `gpt-6-sol`, `gpt-6.1-sol` or `gpt-6-astra`, `ultrafast`
`gpt-6.1-sol` or `gpt-6-astra`; with a custom OpenAI base URL or any other
model only `default`.

Response: 200 `{"service_tier": string}`.

Errors: 400 "Nicht unterstützter Geschwindigkeitsmodus für dieses Modell.".

### `PUT /api/settings/thinking-level`

Request: JSON body `{"thinking_level": string}`, case-insensitive: `low`,
`medium` or `high`.

Response: 200 `{"thinking_level": string}`.

Errors: 400 "Nicht unterstütztes Thinking Level.".

### `GET /api/state/events`

Request: query `since` (last seen event id: ASCII digits, at most 19;
default 0).

Response: 200 `text/event-stream`, kept open until the client or its
session ends. It sends the retained events after `since` as SSE events
named `provider`, `job`, `planning`, `coach` or `sync` (each with `id:`
and a JSON object), then `ready` with `latest_event_id`. A `since` the
buffer no longer covers, or ahead of it (earlier process), sends `reset`
with `reason` `gap` and `latest_event_id` instead. Every 15 seconds
without an event it sends `heartbeat` with `latest_event_id`.

Errors: 400 `invalid_event_cursor` "Die Event-ID ist ungültig." for a
malformed `since`, before the stream starts.

### `POST /api/sync/jobs`

Request: `POST /api/sync/jobs` with JSON body `{"provider": string,
"type": string, "payload": object}`. `provider` is a registered provider
id (case-insensitive); `type` is optional (default `refresh`) and one of
`refresh`, `activity_details`, `plan_push`, `competition_push`,
`nutrition_sync`, `historical_backfill`, `wellness_backfill` or
`stream_backfill`, as far as the provider supports it. Without `payload`,
the top-level `days`, `force` and `reason` fields are used as the payload.
The payload fields are validated per provider and job type; a refresh
takes `days` (`-1` or 1 up to the provider's window, at most 365 for
Intervals.icu and 90 for the others), `force` (boolean), `reason` and
`end_date`.

Response: 202 with the queued job (as `GET /api/sync/jobs/{id}`),
requested by `user`.

Errors: 400 `invalid_job_request` with the validation text, for example
"Unsupported provider.", "Unsupported job type.", "Job payload must be an
object." or "Der Job enthält nicht unterstützte Felder."; 400
`invalid_job_request` "Der Ernährungs-Export braucht eine bestätigte
Vorschau." for `nutrition_sync`; 409 `not_configured` with the provider's
setup message for `garmin`, `wahoo` and `intervals`.

### `GET /api/sync/jobs/{id}`

Request: path `id`, the job id (lowercase hexadecimal and `-`); no body.

Response: 200 with `id`, `provider`, `type`, `status`, `payload`,
`requested_by`, `attempts`, `progress` (`completed`, `total`),
`available_at`, `started_at`, `finished_at`, `error_class`,
`error_detail`, `items` (per item `id`, `item_key`, `operation`,
`remote_id`, `status`, `attempts`, `error_class`, `error_detail`,
`created_at`, `updated_at`), `created_at` and `updated_at`.

Errors: 404 `sync_job_not_found` "Synchronisationsjob nicht gefunden."
when no such job exists (an id with other characters matches no route).

### `GET /api/sync/status`

Request: no body.

Response: 200 with `status`, `phase`, `progress` (0 to 100),
`operation_id`, `running`, `message`, `started_at`, `finished_at`,
`last_error`, `state_versions`, `provider_freshness`, `maintenance`
(`active`, `running_operations`) and `jobs` (the recent sync jobs).

Errors: none beyond the common ones.

### `POST /api/transcribe`

Request: the raw audio bytes as body, not JSON. `Content-Type` is one of
`audio/webm`, `audio/mp4`, `audio/ogg`, `audio/mpeg`, `audio/wav`,
`audio/x-wav`, `audio/mpga`, `audio/m4a` (parameters after `;` are ignored);
`Content-Length` 1 to 8 000 000 bytes. The audio is never stored.

Response: 200 `{"transcript": string}`.

Errors: 415 "Nicht unterstütztes Audioformat. Erlaubt sind WebM, MP4, OGG,
MP3 und WAV."; 400 "Ungültige Content-Length."; 400 "Ungültige Größe der
Audioaufnahme." for an empty body, 413 with the same message above 8 000 000
bytes; 400 "Die Audioaufnahme wurde unvollständig übertragen."; 503
`not_configured` "OpenAI ist nicht eingerichtet. Zugangsdaten unter Mehr →
Anbindungen hinterlegen."; 502 "OpenAI hat kein Transkript
zurückgegeben." when the provider returns no text.

### `GET /api/wahoo/callback`

Request: no session; query `code` (authorization code), `state` and
`error`, each at most 2048 characters. The only accepted credential is
the single-use `state` stored on the server by `POST /api/wahoo/connect`
(valid 10 minutes, consumed by the first callback that matches or finds
it expired): the SameSite=Strict session cookies are not sent on Wahoo's
cross-site redirect. The call enters the maintenance operation gate.

Response: 302 with an empty `text/plain` body and `Location`
`/?wahoo=connected` after the code was exchanged and the tokens stored,
else `/?wahoo=error`.

Errors: none; an unknown, expired or reused `state`, a missing `code`, an
`error` parameter, a failed code exchange, an unconfigured Wahoo or a
disconnect during the exchange all redirect to `/?wahoo=error`.

### `POST /api/wahoo/connect`, `POST /api/wahoo/disconnect`

Request: JSON object body, which is ignored (send `{}`). Registered for
`/api/wahoo/connect` and `/api/wahoo/disconnect`.

Response: for `/api/wahoo/connect` 200 with `authorize_url`, the Wahoo
authorization URL carrying a new one-time `state` that replaces any
pending one. For `/api/wahoo/disconnect` 200 with `status` (`"ok"`),
`connected` (`false`), `remote_revoke_attempted` and `remote_revoked`
(the revocation at Wahoo is best effort; the local tokens are always
deleted).

Errors: for `/api/wahoo/connect`: 503 `not_configured` "Wahoo ist nicht
konfiguriert. Bitte WAHOO_CLIENT_ID, WAHOO_CLIENT_SECRET und
WAHOO_REDIRECT_URI in der Serverkonfiguration hinterlegen."; 400
`invalid_redirect_uri` "WAHOO_REDIRECT_URI muss eine vollständige
HTTPS-URL ohne Zugangsdaten sein." when the configured redirect is not an
HTTPS URL with host, without credentials or fragment. Disconnect has no
route-specific errors.

### `GET /api/weather`

Request: query `local` (`1` answers from the stored forecast without
contacting the weather provider; any other value or none refreshes it
when it is stale).

Response: 200 with `configured`, `state` (`not_configured`, `loading`,
`ready`, `stale` or `error`), `provider`, `days` and `recommendations`;
a ready or stale forecast adds `attribution`, `model`, `location`,
`fetched_at`, and a stale one `stale` and `error`. Without a configured
location it carries `message` instead; `error` and `loading` states
carry `error` or `loading` and `message`.

Errors: none beyond the common ones.

### `GET /api/zones`

Request: no query, no body.

Response: 200 with `sports` (`ride`, `run`, `swim`), `today` (athlete-local
date), `configurations` (each with `key`, `source` `local` or the provider,
`label`, `sport`, `metric`, `environment`, `valid_from`, `valid_until`,
`threshold`, `maximum`, `limits`, `percent_limits`, `percent_basis`),
`effective` (per sport, metric and environment the configuration in effect
today: `sport`, `metric`, `environment`, `key`) and, only when there is one,
`threshold_warnings`.

Errors: none beyond the common ones.

### `PUT /api/zones`

Request: JSON body `{"sport": string, "metric": string, "environment":
string | null, "limits": number[], "percent_limits": number[],
"threshold": number, "maximum": number, "valid_from": string,
"from_beginning": boolean}`. `sport` is `ride`, `run` or `swim`; `metric`
is `heart_rate`, `power` or `pace`; `environment` is `null` or `indoor`.
Exactly one of `limits` (absolute upper zone limits in bpm, W or m/s) and
`percent_limits` (percent of the threshold) is required, each 3 to 7
numbers. `threshold` is required for `heart_rate` and `power`; `maximum` is
read for `heart_rate` only. `valid_from` (`YYYY-MM-DD`, not in the future)
defaults to today; `from_beginning: true` stores an undated base value
instead.

Response: 200 `{"configuration": object, "change": object | null}`;
`change` is the undo reference (`id`, `entity_type`, `action`,
`after_hash`).

Errors: 400 "Die Zonen sind ungültig: {reason}." with the invalid field or
rule (`sport`, `metric`, `environment`, `limits oder percent_limits`,
`limits braucht 3 bis 7 Werte`, `Schwellenpuls (LSHF) fehlt`, `FTP fehlt`,
`valid_from`); 400 "Die maximale Herzfrequenz darf nicht unter dem
Schwellenpuls liegen."; 400 "Die Zonenobergrenzen dürfen nicht über der
maximalen Herzfrequenz liegen."; 400 "Das Datum „Gilt ab“ darf nicht in der
Zukunft liegen.".

The route exists only where zone editing is configured.

### `PUT /api/zones/remove`

Request: JSON body `{"key": string, "confirmed": true}`; `key` is the `key`
of a local configuration from `GET /api/zones`.

Response: 200 `{"configuration": null, "change": object | null}`; `change`
is the undo reference (`id`, `entity_type`, `action`, `after_hash`).

Errors: 400 "Das Entfernen lokaler Zonen muss bestätigt werden." unless
`confirmed` is `true`; 404 "Lokale Zonen nicht gefunden.".

The route exists only where zone editing is configured.
<!-- END GENERATED ROUTES -->

The former `/api/logs/clear` and `/api/diagnostics/clear` aliases are not
registered. Static files and the application shell are served separately from
these API route tables.
