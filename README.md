# Intervals Coach

Intervals Coach is a private, mobile-first PWA for a single athlete. Its
Python standard-library HTTP server synchronizes training data from
Intervals.icu and, optionally, Garmin Connect, sends a sanitized coaching
context to the OpenAI Responses API, and stores the local application state in
an encrypted SQLite database.

The application is designed for use on a trusted home network or private VPN.
It is not intended to be exposed directly to the public internet.

## Fresh installation

Use a new empty data directory and a fresh browser profile for this application.
The application creates its current SQLCipher schema directly. It does not
convert previous databases, backups, API payloads, or browser storage. Restore
accepts backups created with the current schema. The service worker supports
first installation and offline assets; there is no application update dialog
or upgrade workflow. Normal edits, provider syncs, and same-build restart
recovery remain supported. Keep the previous installation separate; these
instructions do not delete or convert its data.

## Features

- Athlete profile, target competitions, performance metrics, training history,
  chat history, and a growing local workout library stored in SQLite.
- One Intervals.icu synchronization at startup, plus user-requested refreshes.
- Optional Garmin Connect synchronization with deduplication against
  Intervals.icu. Garmin-sourced FTP (separate from eFTP), running threshold
  power, running and cycling threshold heart rate, running threshold pace,
  sleep, resting heart rate, HRV, VO2 max, running predictions, body weight,
  sport-specific maximum heart rates, and daily steps, floors, and calories are
  explicitly marked as Garmin Connect data in the performance view. Daily
  health totals are shown in the planned calendar's date-specific context; the
  performance view shows their seven-day averages. If a Garmin value is
  unavailable, the existing Intervals.icu value remains available as a
  labelled fallback.
- Activity synchronization for strength training, running, outdoor cycling,
  and indoor/virtual cycling.
- Mobile-first profile and system sections can be collapsed; the planned
  calendar is grouped into collapsible full weeks with compact volume summaries.
  The More tab controls how many past and future weeks are displayed.
  Intervals.icu planned workouts are matched to completed activities through
  their pairing (with a conservative same-day/sport fallback). The training
  calendar also shows unmatched completed activities for past days and today.
  Completed cards expose actual duration, distance, training load, RPE, and
  available sport metrics without inventing missing values. Matched cards show
  plan-versus-actual volume; the comparison uses training load when available,
  otherwise moving/elapsed time.
- If adaptive planning shortens a local workout or reduces its intensity due
  to a read-only iCalendar appointment, the linked planned workout records
  that reason and the original versus adjusted duration after approval.
- Google Calendar has no editable iCalendar category field. The external
  calendar sync imports only events whose description contains one of
  `[NO_TRAINING]`, `[NO_INTENSITY]`, or `[SHORT_ONLY]`. Add `[NO_TRAINING]`
  to informational appointments; the event remains visible as a red marker
  on its day in the planned calendar, but is excluded from coaching and
  adaptive planning.
- Add `[NO_INTENSITY]` to the description when a calendar event should allow
  training but prevent hard sessions; it is shown as a red marker on its day;
  `[SHORT_ONLY]` marks an appointment that should only allow a short session.
  Other description tags have no effect.
- Optional weather integration via Open-Meteo: a city or postal code in the
  profile enables a cached 14-day forecast in the planned calendar. For
  outdoor runs and rides, the app suggests a weather-aware time window for
  the next five days, including a small weather symbol, wind speed, gusts,
  and direction. Weekday suggestions account for work from 06:00–15:30
  (Monday–Thursday), work until 14:00 on Friday, and the usable 12:00–13:00
  lunch break. In NRW the short range uses DWD ICON-D2 and the longer range
  uses ECMWF IFS HRES. The free Open-Meteo tier is intended for non-commercial
  use and requires attribution.
- Thirty-day trends for FTP, thresholds, VO2 max, running predictions,
  readiness, and body weight. Garmin performance values are stored locally as
  compact historical points during synchronization.
- Push-to-talk voice input in the chat: short recordings are transcribed
  server-side and inserted into the editable message field; audio is not stored.
- Coach chat with selectable GPT-5.6 models, configurable thinking level,
  context preview, structured logs, and prioritized steering/FIFO message
  queueing while the coach is responding. Responses are streamed through a
  credential-free server-side SSE bridge; the chat view renders safe partial
  Markdown, and **Abbrechen** cancels the active request while **Steuern**
  remains a separate queued follow-up action. Reloading the page or losing the
  streaming connection does not cancel the server-side coach request; its
  persisted answer appears in the chat after the next load. Planning requests
  longer than seven calendar days or containing more than seven requested
  units are persisted as background jobs and use OpenAI background responses;
  their response ID and progress survive a page reload or process restart.
- The Coach start card contains only contextual quick actions, not provider
  connection badges. The morning check-in disappears after it completed for
  the athlete's local day. "Plan anpassen" appears only for an unapplied
  calendar, illness, injury, or blocking-weather change affecting a planned
  unit within the next three days. "Letzte Einheit analysieren" refreshes
  Intervals.icu before coaching. When near-identical Wahoo and Garmin cycling
  recordings are present, Wahoo is canonical; deleting the Garmin cloud copy
  always requires a separate confirmation in Coach Chat.
- The Coach is the local source of truth for future planned units, target
  competitions, and reusable workout templates. An unambiguous plan request
  stores local planned units immediately. Explicit requests to move, archive,
  restore, or delete units and templates are executed by Coach tools without a
  second UI confirmation; questions and hypotheticals remain read-only. Every
  planning entity has a stable local UUID and sync metadata.
- Dated workouts are stored in the dedicated local `planned_units` table and
  never in the reusable template library. Intervals.icu calendar workouts and
  templates are imported once during initial setup. After that import, the
  local app is authoritative for future planning; completed Intervals.icu
  activities remain authoritative for what was actually performed.
   Beim ersten expliziten Bibliothekssync wird dafür bei Intervals.icu bei
   Bedarf ein privater Ordner „Intervals Coach“ angelegt.
- The regular Intervals.icu activity pull is read-only and never uploads
  pending local library entries or re-imports future remote planning. Only an
  explicitly named Coach synchronization can create, update, or delete planned
  units remotely. The current chat request is the authorization for that sync.
- When the first regular Intervals.icu sync finds an empty local library, it
  imports the existing remote templates into the local library. This initial
  import is read-only; later local edits still require the separate explicit
  library synchronization action for remote writes.
- The explicit planning synchronization transfers dirty local planned units to
  the Intervals.icu calendar with stable upsert identities. It does not replace
  the local plan with later remote edits or deletions.
- If a provider response no longer contains an imported template, it is kept
  locally and marked as missing remotely. A later library synchronization
  reconciles it before creating it again; local templates are never removed by
  a full Intervals.icu resync.
- Multi-week plans and library templates are managed through the Coach. The
  Geplant view has read-only Übersicht and Bibliothek segments: the overview
  shows the combined planned and completed training calendar by week, while the
  library groups active workout templates by sport.
- Existing training plans can be renamed, have their goal, status, or date range
  changed, and can be deleted directly through the Coach. Plan deletion removes
  plan metadata only; scheduled local workout units remain untouched.
- The coach can explicitly apply saved library entries as local planned units.
  Existing calendar dates are checked first. Intervals.icu calendar writes stay
  disabled unless the athlete explicitly requests that synchronization.
- Bidirectional synchronization of target competitions with Intervals.icu.
- The coach can explicitly list, create, update, and locally delete target
  competitions. Linked remote changes remain pending until an explicit
  competition synchronization is requested.
- Local athlete check-ins for day form (such as heavy legs and fatigue),
  subjective soreness, stress, motivation, session RPE, illness, pain, available
  training time, and day-specific constraints. Reported illness is a high-priority
  planning constraint and is shown separately in the dated daily context. The
  coach can propose a conservative sport-pause forecast; after explicit approval
  in Coach Chat, future local sessions are replaced with illness-pause entries and
  the corresponding future check-in days filled.
  Check-ins can be entered or edited through Coach Chat. Check-in dates and daily training
  boundaries use the saved IANA profile timezone, and future check-ins are
  rejected. The Heute tab provides a compact, read-only coach-oriented daily
  synthesis of the local morning check-in, readiness/recovery signals, today's
  planned workout, relevant weather, open activity feedback, and pending plan
  adjustments. It uses already loaded state and does not trigger an additional
  coach or provider request when opened; navigation and action buttons are not
  shown in this view. Missing, loading, offline, sync, and error states are
  shown clearly.
- After a completed activity, the coach can ask for a short subjective follow-up
  and store the athlete's answer as activity feedback.
- The coach can explicitly read completed activities, the local workout library,
  planned units, competitions, training plans, and local change-history
  references. It can schedule selected saved library templates locally after
  conflict checks, and remove activity feedback on request. Explicit provider
  refreshes for Intervals.icu, current performance, Garmin, weather, and the
  external calendar run as trackable background jobs; local plans and
  competitions are pushed to Intervals.icu only through an explicitly named,
  trackable synchronization. The local workout library remains authoritative
  after its initial import and is never overwritten by a Coach refresh.
  Adaptive planning can be previewed and, after explicit approval, applied to
  future local workouts; an illness-pause event is sent to Intervals.icu only
  when that synchronization is explicitly named in the same request.
- Read-only shared iCalendar integration for the next 8 weeks. Event
  timing and duration are used as schedule/recovery signals; high-intensity or
  long local library entries on busy days can be proposed as short easy sessions.
  Invalid feeds are rejected without replacing the last good local calendar;
  common Google/RFC 5545 recurring events (`DAILY`, `WEEKLY`, `MONTHLY`, and
  `YEARLY`, including `BYDAY`, `BYMONTHDAY`, `BYMONTH`, `BYSETPOS`, and `WKST`) are
  expanded only inside the eight-week window. Google recurrence exceptions and
  date-only `RDATE` additions are applied; unsupported rule parts are reported
  clearly. Expansion is capped at 1,000 occurrences.
- The planned calendar never displays a provider horizon wider than the
  Intervals.icu window actually loaded by the latest snapshot. The configured
  display preference may therefore be reduced temporarily after a short sync.
- Adaptive plan review that checks after a weather or shared-calendar refresh
  whether future local library entries need adjustment. In the next two days,
  persistent rain or snow can trigger a shorter easy replacement for a long
  outdoor ride. A red update notice appears in the planned calendar and as a
  compact hint on the Coach tab. Changes are shown as a preview and require
  explicit local approval; remote Intervals.icu calendar events are never
  changed by this process.
- Annual event overview with base, build, peak, taper, and completed phases.
- Optional PWA notifications for upcoming events and synchronization errors.
  Notifications are opt-in and are delivered by the browser/service worker
  while the PWA can run; there is no guaranteed background push service, and
  device workout delivery remains delegated to Intervals.icu.
- Configurable Intervals.icu activity synchronization period, data export,
  local cleanup, and retention policy.
- Encrypted database backup download and validated restore with an automatic
  pre-restore copy of the previous database.
- OpenAI usage display for the latest request, remaining request/token quotas,
  and the classified status of the last API call. Account dollar balances are
  available through the OpenAI billing dashboard or authorized organization
  access, not through this application.
- Chat requests use a bounded queue, retry only structured conversation-lock
  failures, and persist tool-call results so retried follow-ups do not repeat
  local mutations. The application does not impose a local daily request or
  token budget; requests continue until OpenAI rejects them because the
  account or project quota is exhausted. An explicitly cancelled stream never
  executes a partial tool call; a lost browser connection leaves the request
  running so its completed answer can be recovered after reload. One-week
  plans and requests for at most seven units remain synchronous; larger plans
  return control to the browser immediately and are polled from durable state.

## Loading and synchronization

After login, the chat and all data already stored locally are rendered first.
The browser then loads the current remote-enriched view in the background. The
authentication request itself does not force a new Intervals.icu, Garmin, or
calendar synchronization: those providers are synchronized at server
startup, once per calendar day in the background, or on demand from the More
tab. The selected activity windows (Intervals.icu and Garmin) are retained
locally and can be changed in that tab.

The browser refreshes the local/remote view every minute while the PWA is
visible and polls more frequently while a manual synchronization is running.
Large Intervals.icu responses are fetched in bounded pages and the latest
sync reports the fetched page/window counts; incomplete required Garmin ranges
remain visible as partial provider status instead of being presented as complete.
Garmin Body Battery is deliberately separate from the regular and historical
Garmin synchronization. It is fetched once during the morning check-in, only
for the completed sleep window (at most the previous and current calendar
day). The app stores the last level before sleep and the newest available level
after waking. A missing optional morning value neither retries in the background
nor marks the complete Garmin connection as incomplete; the last valid dated
pair remains available.
Open-Meteo uses the profile location, keeps a three-hour server-side forecast
cache, and refreshes that location in the background every three hours. A
visible view also refreshes it when the cache has expired. The current forecast
can be forced manually from the Open-Meteo card in the More tab.
The morning check-in is generated at most once per local calendar day when its required
integrations are configured.

The five main views use stable hash links: `#coach`, `#today`, `#plan`,
`#analysis`, and `#more`. Navigation is implemented with real
links, so direct links, reload, browser back/forward, keyboard access, and
screen-reader announcements remain available. An unknown hash falls back to
`#coach`; a deep link is retained through the login flow. The `#today` view
combines the local check-in, current recovery/readiness signals, today's
planned workout, relevant weather, open activity feedback, and pending plan
adjustments. It uses already loaded state only; opening the view does not
trigger an additional coach or provider request. Missing data, offline state,
sync progress, and the last sync error are shown explicitly.

The PWA provides an installable offline shell only. It does not provide a full
offline data view or a local mutation queue: authenticated API responses are
never cached by the service worker, and offline mode clearly limits the user
to already loaded data until connectivity returns. This is the deliberate
product decision for the current private single-athlete app; adding an offline
data cache, queue, or Web Push would require a separate privacy and threat-
model decision.

Versioned JavaScript, CSS, and image assets with a `?v=...` query are served
with a one-year immutable cache policy and an ETag. HTML, the manifest, and the
service worker remain revalidatable with `no-cache`. The service worker uses
cache-first for versioned assets and network-first for other non-API requests,
removes older versioned caches on activation, and never caches API responses.
Enable gzip or Brotli only at the documented trusted HTTPS reverse proxy; the
application remains LAN/VPN-only.

## Coach context projection

The encrypted provider snapshots and the general local state remain complete.
Only the projection assembled for an OpenAI coaching request is bounded: it
includes the five newest activities per normalized sport, compact planned
workout fields, and at most 50 local planned units. Long descriptions and
provider-only payloads are omitted from that projection. Local planned units
are serialized once, and the context preview reports section sizes and the
overall character-budget status. Current performance metrics retain their
source labels; Garmin performance fields are included only when they add
information not already represented by the Intervals.icu performance context.

New activities become available to the coach after the startup/daily
Intervals.icu sync, a manual synchronization, or a chat request that
explicitly asks for current/latest training data. The browser's regular state
poll only reads the local snapshot; it does not contact Intervals.icu.

The browser bootstrap is intentionally independent of chat and activity
history. Domain data is loaded through bounded endpoints: activities and chat
history use stable cursors (chat history also supports bounded server-side
search), while plans, performance, profile, feedback, and the workout library
are loaded separately. The activity view can request the next page without
reloading the complete application state.

The `#plan/overview` and `#plan/library` routes form the read-only Geplant view.
The overview shows dated local units in a weekly calendar and the library shows
active workout templates grouped by sport. Neither segment contains planning,
deletion, editing, or synchronization controls. Planning, template management,
competitions, multi-week plans, and explicit remote synchronization are handled
through the Coach.

The More view is organized into the deep-linked segments `#more/profile`,
`#more/connections`, `#more/coach`, `#more/privacy`, and `#more/operations`.
Profile fields show when they may be included in requests to OpenAI. Sports and
time zone use controlled selections, while competition duration and distance are
entered as `hh:mm` and kilometers and normalized before local storage. Privacy,
backup/restore, and diagnostics remain available within two navigation levels.

Manual Intervals.icu synchronization starts in the background and exposes only
the bounded `/api/sync/status` response while it runs. The browser uses one
status poll at a time, coordinates visible tabs through a short-lived local
lease, pauses polling while hidden or offline, and reloads only domains whose
state version changed after completion.

The connections view shows a bounded, sanitized freshness timeline for
Intervals.icu, Garmin, Open-Meteo, and the read-only shared calendar. It
separates never-loaded, fresh, partial, stale-but-usable, and failed states,
records only technical timestamps/phases/error classes, and calculates a
bounded retry time after transient failures. Retry buttons are limited to the
corresponding read-only provider path; competition and workout-library writes
remain separate explicit actions. The same safe freshness metadata is included
in the diagnostics report. The timeline retains at most 200 attempts for 30
days and never stores provider responses or calendar URLs during normal use.

While a provider synchronization is running, the connections view shows its
current phase and, where the provider reports one, a progress indicator. A
site-wide notice headed **“Anbindung benötigt Aufmerksamkeit”** is displayed
only for errors that require manual intervention (for example, renewed login
or invalid configuration). An unavailable optional morning Body Battery value
is rendered neutrally and does not raise that notice or schedule a retry.

The library has no multi-selection, local marking, manual planning, conflict
resolution, or synchronization controls. The Coach receives bounded local IDs
and payload hashes, performs explicitly requested single or bulk changes, and
queues an explicitly named Intervals.icu synchronization in batches. Provider
failures are reported in Coach Chat and can be retried there.

## Target competitions and Intervals.icu

Target competitions are managed through the Coach with the Intervals.icu event
fields: name, local start date/time, sport/type, category, description, duration,
distance, target, and external ID. They are synchronized in both directions
with Intervals.icu. Local changes are exported as `RACE_A`,
`RACE_B`, or `RACE_C` events with a stable `external_id`; matching race events
from Intervals.icu are imported into the local database.

Startup, daily, and ordinary pull synchronization only reads competition events
and never exports local changes or deletion tombstones. An explicit named Coach
request performs the dedicated competition synchronization.

Competition synchronization accepts strength training, running, outdoor
cycling (`Ride`), and indoor/virtual cycling (`VirtualRide`). Other sports are
skipped. Remote events that were previously linked but no longer exist are
kept locally; a later explicit Coach synchronization reconciles them. Local
deletions are propagated to Intervals.icu during that synchronization.
The Intervals.icu event ID is stored locally after import or a successful push.
Before creating a new event, synchronization also checks for an existing race
with the same name, date, and sport to avoid creating duplicates. A dirty local
row that matches a remote race by identity only is never silently adopted. The
Coach reports provider failures and can retry the requested operation; planned
workouts always use the preserved local version.

## Configuration

Copy `.env.example` to `.env`, or set the variables directly as Docker or
Unraid environment variables. Values supplied through the container
environment take precedence over values in `.env`.

Required:

```text
OPENAI_API_KEY=replace-me
INTERVALS_API_KEY=replace-me
INTERVALS_ATHLETE_ID=0
APP_PASSWORD=replace-with-at-least-12-random-characters
```

`APP_PASSWORD` protects the web interface and all API endpoints except the
liveness/readiness probes, login, and authentication-status endpoints. The same password
is used as the SQLCipher database key. It is never stored by the application
and cannot be recovered if lost. The password must be at least 12 characters
long.

The database is created with the current SQLCipher schema on first startup.
Startup never changes an existing database schema: if its application tables,
columns, or named indexes differ from the current schema, startup stops. This
release therefore expects a newly created database instead of an older
database being reused. Restore accepts only a database with that exact current
schema and checks its integrity before replacing the active file. The
public-calendar candidate relation explicitly cascades when its source is
deleted.

`/api/health` is a liveness probe: it only confirms that the HTTP process can
answer. `/api/readiness` is a separate infrastructure probe and returns HTTP
503 until a harmless database read, the current schema, a temporary write in
`/data`, and the maintenance gate are all usable. Its response contains only
safe booleans and status values, never paths, secrets, or athlete data.

Local state reads and Coach usage accounting share the database transaction
lock. Completing a Coach response while the UI reloads its state therefore
cannot deadlock through a separate usage-statistics lock. Usage counters remain
atomic when multiple responses finish concurrently.

Backend modularization starts with dependency-light database primitives in the
`backend.db` package. Its repositories provide explicit
`KeyValueRepository`, `ProfileRepository`, `CompetitionRepository`,
`TrainingPlanRepository`, `PlanAdjustmentRepository`,
`ChatRepository`,
`CheckinRepository`,
`ActivityFeedbackRepository`, and `SnapshotRepository` interfaces in
`backend/db/repositories.py`. The Intervals.icu provider's bounded,
duplicate-page-safe collection
pagination is isolated in `backend/providers/intervals.py`; it receives the
transport and error factory explicitly and has no dependency on application
state. Further provider operations, synchronization, coaching,
backup, and HTTP routing are moved in separate cohesive steps. The HTTP
boundary also isolates bounded request-body, JSON, and audio parsing in
`backend/http_api/requests.py`; socket I/O, authentication, and application
error types remain in the handler. These modules are copied into the container
as application code and do not change the
SQLCipher, authentication, or persistence contracts.

The first frontend boundary is `public/api.js`. It owns same-origin JSON and
audio requests, CSRF headers, and common HTTP error handling; `app.js` supplies
the login callback. The API
client has no dependency on application state or views. Future frontend
boundaries (`state`, `navigation`, `views`, `forms`, and `components`) depend
on this client through explicit interfaces, with no new framework and no
duplicate DTO definitions. The route constants and pure hash parsers are
isolated in `public/navigation.js`, the shared mutable UI state is isolated in
`public/state.js`, state-free display/formatting helpers are isolated in
`public/views.js`, and dialog focus components are isolated in
`public/components.js`.
DOM- and data-loading coordination remains in `app.js` and the script order is
explicit.

Optional Garmin Connect configuration:

```text
GARMIN_EMAIL=your-email@example.com
GARMIN_PASSWORD=replace-me
GARMINTOKENS=/data/garmin_tokens
GARMIN_FIXTURE_PATH=garmin-fixture.example.json
```

`GARMIN_FIXTURE_PATH` is intended for local development and tests. A persistent
Garmin token store is preferred after the first login and MFA setup.

Optional shared calendar configuration:

```text
CALENDAR_ICAL_URL=https://calendar.example/household.ics
```

Use the private iCalendar/ICS feed supplied by the calendar provider. Treat a
private feed URL like a password. The application only fetches this feed,
stores bounded event metadata locally, and never writes to the calendar. The
URL stays in the server environment and is excluded from browser state,
exports, and logs.

The feed is read at startup, once per day, or on demand with **Synchronisieren**
in the More tab. Daily synchronization uses the athlete's validated
IANA timezone and stores a separate local execution date for each provider.
Successful manual synchronization counts for the provider's current local day. Events
are supplied to the Coach as read-only scheduling context.
A successful sync keeps events from today through the next
8 weeks (56 days). A failed refresh leaves the last successful event set in place and
shows the error. Calendar text is untrusted data; it cannot change application
settings or bypass explicit library synchronization or planning approvals.

Other supported operational variables are:

```text
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5.6-sol
DATA_RETENTION_DAYS=-1
PORT=8090
DATA_DIR=/data
TZ=Europe/Berlin
```

`OPENAI_BASE_URL` is optional and defaults to `https://api.openai.com/v1`. It
must be an HTTP(S) base URL without credentials or query parameters. This lets
you use an OpenAI-compatible Responses API, for example a Microsoft Foundry
endpoint such as `https://<resource>.openai.azure.com/openai/v1`. Keep
`OPENAI_API_KEY` for the provider credential and set `OPENAI_MODEL` to the
provider's deployment/model name. The configured service must support the
Responses API, SSE streaming, and Conversations API used by the app; voice
input additionally requires `/audio/transcriptions`.

`DATA_RETENTION_DAYS=-1` is the default and disables automatic deletion. The
application does not impose its own OpenAI request or token limits; it displays
remaining quotas when the API reports them. When the configured provider returns
a billing or quota error such as `credit_balance_exhausted`, the app shows a
clear message and points to billing.

## Garmin authentication

For the first Garmin login, run the one-time interactive helper with the
persistent data directory mounted. The helper prompts for the Garmin MFA code
when required and stores refresh tokens under `GARMINTOKENS`.

```sh
docker run --rm -it \
  --env-file /mnt/user/appdata/ai-coach/.env \
  -v /mnt/user/appdata/ai-coach/data:/data \
  ghcr.io/lukas-beike/ai-coach:latest \
  python /app/garmin-login.py
```

After the token store has been created, restart the application container with
the same `/data` mount. The application can then use the stored Garmin tokens
without asking for the login code on every startup.

## Local planning data and target competitions

The **Activities** tab allows you to add local notes after a completed activity,
for example about pain, unusual fatigue, conditions, or anything that went
particularly well. These activity-specific notes are stored separately from
imported Garmin and Intervals.icu values and included in the AI context as
local athlete data.

The adaptive planning action is surfaced as a compact hint on the Coach tab when
a weather or shared calendar refresh finds future local planned units that need
adjustment. It produces a change preview; asking the Coach to apply the preview
is the explicit approval and updates eligible local library entries.
It does not overwrite, delete, or reschedule remote Intervals.icu calendar
events.

External calendar events are only planning signals. The heuristic uses the event
date, start/end time, duration, and all-day status to identify library entries
that are hard or long. It does not infer or diagnose an infection from a family event;
illness must still be entered in the athlete check-in. Every suggested change
remains a local preview and requires an explicit Coach request to apply it.

Confirmed illness pauses can optionally be synchronized as explicit `SICK`
calendar entries to Intervals.icu. This remote calendar write happens only when
the athlete explicitly names that synchronization in Coach Chat.


## Docker and Unraid

The container runs as a non-root user and expects a persistent writable mount
at `/data`. The Unraid Appdata directory must grant the container write access.

The Unraid application logo is available at
[`public/logo.png`](public/logo.png).

Pull and run the published image:

```sh
docker pull ghcr.io/lukas-beike/ai-coach:latest
docker stop ai-coach || true
docker rm ai-coach || true
docker run -d \
  --name ai-coach \
  --restart unless-stopped \
  --read-only \
  --security-opt no-new-privileges:true \
  -p 8090:8090 \
  -v /mnt/user/appdata/ai-coach/data:/data \
  --env-file /mnt/user/appdata/ai-coach/.env \
  -e TZ=Europe/Berlin \
  ghcr.io/lukas-beike/ai-coach:latest
```

Alternatively, build locally from the project root:

```sh
docker build -t ai-coach:local .
```

Do not use `docker rm -v`, because the `/data` volume must be preserved. In
Unraid, set credentials and the athlete ID under the container's **Environment
variables**. Recreate the container after changing environment variables. API
keys and passwords are not entered in the application UI.

For access outside the home network, use a private VPN. The project does not
provide HTTPS proxying; do not expose its HTTP port directly to the public
internet.

The chat voice-input feature requires the PWA to be opened through a trusted
HTTPS reverse proxy so the browser can request microphone permission. The
recording is limited to short voice notes, transcribed server-side, and is not
persisted locally. The resulting transcript is placed in the message field
for review before it is sent to the coach.

## Data, privacy, and logs

The encrypted database and rotating JSONL logs are written to `/data`. OpenAI
receives only the structured coaching context required for a request. API keys
are never sent to the browser or included in the coach context. Text received
from external services is treated as untrusted data and never as instructions.

Logs record external service, operation, path, duration, result sizes, and safe
failure classifications, but
not request/response bodies or credentials. Garmin identity values and private
calendar URLs are redacted case-insensitively, including URL-encoded forms;
URL userinfo, known token query parameters, and long credential-like path
segments are removed while a non-sensitive provider host remains visible for
diagnostics. Provider failures use short classified error messages rather than
forwarding SDK exception text. Client disconnects such as a closed browser
connection are handled as normal aborted requests rather than internal server
failures.

The **System** tab allows the athlete to export local data as JSON or delete
local chats, snapshots, active and archived library entries,
competitions, plans, check-ins, feedback, provider snapshots, calendar imports,
and profile state. It also shows a bounded local change history for profile,
library, competition, and plan changes. History entries expose only changed
field names; the values needed for an explicitly confirmed local Undo remain in
the encrypted database record and are never sent to a provider. Undo uses a
preview and one-time confirmation token, checks the current object hash, and
marks a previously synchronized object as locally changed so any remote sync
remains a separate action. Session cookies and server credentials are never part of the
export. The database file itself remains in place. Chat reset and local cleanup
also attempt to delete the stored OpenAI conversation; if that remote deletion
cannot be confirmed, the UI shows an explicit warning. Data held by external
providers remains subject to their own policies.

For Intervals.icu and Garmin, the System tab also offers a full local
resynchronization. It removes only the locally cached data for that provider
and then fetches it again; cloud data, credentials, and Garmin tokens are not
deleted. While this operation runs, syncs for the affected provider and
Intervals.icu write operations are blocked.
The Intervals.icu connection card also reports whether the provider is
connected, synchronizing, or in error, including the time of the last
successful update and a safe provider validation message when available.

The **More** tab also provides an encrypted database backup download and a
validated restore action. Restoring requires the same `APP_PASSWORD` used by
the backup database. Before replacement, the current database is retained as a
`*.pre-restore-*` copy in `/data`. Keep both files protected.

Database backups are checkpointed and downloaded in bounded file chunks. The
privacy export is an incrementally written ZIP archive: large collections are
JSONL entries and `manifest.json` records the export format, format version,
categories, and complete status. Temporary export files are removed after the
download, including after a client disconnect. Export generation enforces a
100 MB size limit, a 120-second time limit, and a free-space check before it
starts. The archive is an intentional, athlete-readable export format; it is
not a database copy.

The login session has a fixed 30-day lifetime; its cookie `Max-Age` and the
server-side expiry use the same duration. The cookie is protected with `HttpOnly`
and `SameSite=Strict` attributes. Activity metadata is written at most once per
five minutes, while expired sessions and stale in-memory rate-limit buckets are
cleaned up periodically in bounded batches. Synchronization logs correlate a
technical operation ID across trigger, provider, phase, duration, counts, and
safe error codes; they do not log provider payloads or athlete content.
In **Betrieb & Diagnose**, the athlete can explicitly enable a one-hour
technical capture. It records response shapes and technical metadata only for
that period so an export can diagnose provider schema failures. It never records
response content or athlete data. It does not
capture request bodies, API keys, passwords, tokens, cookies,
authorization/session/CSRF fields, athlete content, or private calendar URLs;
the normal logs and diagnostics remain content-free. The capture is never
enabled by the Coach.
For HTTPS reverse-proxy deployments, set
`COOKIE_SECURE=true`; this adds the `Secure` attribute to the session and CSRF
cookies. Keep it `false` for the documented local HTTP development flow.

During database restore, the process enters a maintenance mode. Running
provider and coach operations are allowed to finish before the database is
validated and exchanged; new mutations receive a temporary maintenance error.
Read-only status endpoints remain available, and the browser displays the
maintenance state. Restore accepts only a backup with the current schema
version and valid foreign-key/integrity checks. A failed restore leaves the
current database in place.

Open-Meteo failures are shown without exposing provider details and are retried
with an increasing local backoff. A forced manual weather refresh bypasses that
backoff.

## Development and testing

The backend is a Python standard-library HTTP server. The frontend is served
from `public/` as a browser PWA. Runtime state belongs in `data/` and is not
included in Docker builds.

### Local Docker development on Windows

Use the local Docker image as the development runtime. The pinned
`sqlcipher3-binary` package does not provide the required Windows wheel, and
the application requires SQLCipher for secure startup. Do not remove the
dependency or bypass the secure-startup check to run the application natively
on Windows.

From PowerShell in the repository root, create the ignored local configuration
and persistent data directory:

```powershell
Copy-Item .env.example .env
New-Item -ItemType Directory -Force .\data
```

Set the required API values and a stable `APP_PASSWORD` of at least 12
characters in `.env`. For Docker, use `DATA_DIR=/data` and
`GARMINTOKENS=/data/garmin_tokens`. Keep `.env`, `data/`, Garmin credentials,
tokens, encrypted databases, and recovery backups private; never commit or
print them.

Build the image after application, frontend, dependency, Dockerfile, or
startup changes:

```powershell
docker build -t ai-coach:local .
```

For real Garmin data, complete the one-time login interactively. Enter the
Garmin email, password, and MFA code in the local terminal; they do not need to
be stored in `.env` after the token store exists:

```powershell
docker run --rm -it `
  --env-file .env `
  -v "${PWD}\data:/data" `
  ai-coach:local `
  python /app/garmin-login.py
```

Start the local application with the persistent data mount:

```powershell
docker run -d --name ai-coach `
  --restart unless-stopped `
  --read-only `
  --security-opt no-new-privileges:true `
  -p 8090:8090 `
  -v "${PWD}\data:/data" `
  --env-file .env `
  ai-coach:local
```

After code changes, rebuild the image, then recreate only the container while
retaining the same `data` mount:

```powershell
docker stop ai-coach
docker rm ai-coach
```

Never use `docker rm -v`, and never delete or replace the `data` directory.
Open [http://localhost:8090](http://localhost:8090) for browser verification.
Use `docker logs -f ai-coach` and
`Invoke-WebRequest http://localhost:8090/api/health` for local diagnostics.
Do not expose port 8090 directly to the public internet.

For UI work that does not need a live Garmin account, use the checked-in
fixture instead. Mount it into the container and set
`GARMIN_FIXTURE_PATH=/app/garmin-fixture.example.json`; no Garmin email,
password, or token store is then required. The fixture is test data and must
not contain credentials.

Run the test suite and syntax checks from the project root:

```powershell
python -m unittest discover -s tests -v
python -m py_compile server.py tests/test_server.py
```

The GitHub Actions test workflow runs the unit tests in four parallel shards
with `python tests/run_tests.py --shard <number> --total 4`. General tests use
an isolated fast SQLite fixture; the dedicated encryption checks retain their
SQLCipher setup.

The canonical Windows SQLCipher/container run builds an isolated image and
mounts only the test inputs (`tests/` and `public/`) read-only. It never mounts
the repository root, so `.env`, `data/`, token stores, databases, and backups
cannot enter the test container:

```powershell
./tests/run_sqlcipher_tests.ps1
```

Native Python syntax checks, container unit tests, and image security are
separate CI jobs aggregated by the required `test` check. The container job
uses the same bounded test runner as the four fast native shards.
The quality job records coverage and runs pinned Ruff formatter/linter and
MyPy checks. Every test module is discovered before deterministic sharding;
import failures are fatal and the runner reports executed and skipped counts.
All checks and container builds use the workflow event's immutable `github.sha`.
The release tag must identify that same commit and its APP_VERSION; dispatch
inputs cannot replace the source that is executed.

Pull requests run the unit tests, syntax checks, and image security report. The conventional-commit
workflow validates pull-request titles and commit subjects. Dependabot manages
Python, Docker, and GitHub Actions dependencies and can automatically squash
merge successful update pull requests.

### Codex pull-request review

The required `Codex code review` check is a merge gate for the native,
subscription-backed Codex GitHub review. Enable automatic Code Review for this
repository in Codex Cloud, or request one with `@codex review` in the pull
request. The gate follows the Codex summary comment that is posted as soon as a
review starts and edited as its status changes. It passes only after that
comment reports completion for the current pull-request commit and Codex has
published the matching submitted review. Inline findings are associated with
that review by review ID, because their individual commit IDs can refer to
different revisions of the changed lines. Any finding fails the gate. A new
push invalidates the old review and starts the gate again. Retargeting the PR
also starts a fresh gate for the new base branch. A manual `@codex review`
request requires a summary and submitted review created or updated after that
request, so an older result cannot be reused. When the target branch advances,
the gate requests a fresh review for each affected open PR and replaces the
older polling run. For normal pull-request events it also posts `@codex review`
to start the subscription review explicitly. If the PR is closed or merged
while the gate is waiting, the gate cancels its check instead of polling until
the timeout.

The workflow runs from the trusted target branch and never checks out or
executes pull-request code. It uses only the GitHub token to read reviews and
update the required check; no `OPENAI_API_KEY` repository secret is needed.
Keep the exact required status-check name `Codex code review` in the GitHub
rulesets for `develop` and `main`.

### Image supply chain and runtime boundary

The test-and-publish workflow emits an SPDX image SBOM. An SBOM is a package
inventory, not a vulnerability scan; assess the current OS and language-package
inventory with a vulnerability scanner before deployment. Local fixture tests
do not establish the status of remote CI or a published image.

Published image digests receive a keyless Sigstore/Cosign signature through
GitHub OIDC. The local runtime remains private: use a trusted LAN or private
VPN and a trusted HTTPS reverse proxy, never expose `http.server` directly to
the public internet. Keep the documented read-only root filesystem, and add
`--cap-drop=ALL`, `--pids-limit`, `--memory`, and `--cpus` only when the
explicit `/data` mount has been compatibility-tested. A rootless container
host is recommended.

### Browser smoke and accessibility checks

The Playwright harness runs against a disposable Docker fixture. It receives
only a fake `APP_PASSWORD`, uses an empty temporary container `/data` filesystem, and
does not read `.env`, the host `data/` directory, or provider accounts. Install
the JavaScript dependencies and run the desktop/mobile smoke and WCAG-AA
checks with:

```powershell
$env:E2E_APP_PASSWORD = "e2e-fixture-password-1234"
npm ci
npx playwright install --with-deps chromium
docker build -t ai-coach:e2e .
docker run -d --name ai-coach-e2e -p 127.0.0.1:8090:8090 --read-only `
  --tmpfs /data:uid=100,gid=101,mode=0700 --tmpfs /tmp `
  --security-opt no-new-privileges:true `
  -v "${PWD}/e2e:/app/e2e:ro" `
  -e APP_PASSWORD=$env:E2E_APP_PASSWORD -e COOKIE_SECURE=false `
  ai-coach:e2e python /app/e2e/fixture_runtime.py
npm run test:e2e
docker rm -f ai-coach-e2e
```

The CI job uploads Playwright traces, screenshots, videos, and the HTML report
only when the browser checks fail. These artifacts are generated from the
empty fixture and are retained for seven days.

The accessibility baseline covers the core landmarks, headings, labels, modal
descriptions, live status/error announcements, visible focus, keyboard-only
navigation, 200% text zoom, reduced motion, and 44 CSS-pixel touch targets.
Dialogs return focus to the control that opened them; the browser check also
reviews the login, check-in, navigation, and core coach flows with axe-core.

## Releases and container publishing

The container image is published to
`ghcr.io/lukas-beike/ai-coach` only for a published release or an explicitly
started manual publish workflow. Ordinary pushes and pull requests run tests
but do not publish an image.

The repository uses `develop` as its integration branch and keeps `main`
protected as the release branch. Feature pull requests should target `develop`;
`main` should only be updated through the release promotion pull request.

The `Daily release` workflow checks every day at 03:00 UTC for commits since
the latest release tag. If there is at least one commit, it opens a
version-bump PR that increments `APP_VERSION` in `server.py`. After that PR is
merged into `develop`, the workflow automatically enables squash auto-merge,
creates a synchronized promotion branch, and opens a promotion PR to protected
`main`. The promotion PR also uses squash auto-merge. When it is merged, the
workflow creates a release tag matching `APP_VERSION` on the resulting `main`
commit. The workflow explicitly starts the test check for its generated PRs
and publishes the release after the promotion merge. Its release notes
contain all commits since the previous release. It can also be started
manually through **Actions -> Daily release -> Run workflow**. Manual runs may
optionally provide a target `MAJOR.MINOR.PATCH` version such as `1.2.0` or
`2.0.0`; when omitted, the next patch version is selected automatically. An
explicit manual version is allowed even when there are no new commits.

The resulting release starts the test and container-publish workflow, which
rejects any release where the tag and `APP_VERSION` differ. Configure branch
protection so that `develop` requires the normal CI checks and `main` disallows
force pushes and direct human pushes while allowing the required pull request
checks.

Manual container publishing must run from `main`. The selected event commit
must match the release tag, and the commit must belong to `main` history.
Non-publishing release PR checks can run before the tag exists. The workflow
does not share dependency, Buildx binary, or image-layer caches between runs.

The release workflow uses a repository-installed GitHub App so that automated
branch, pull-request, release, and workflow-dispatch events can start the next
workflow stage. Configure the App with Actions read/write, Contents read/write,
Pull requests read/write, and Checks read permission, and install it only on
this repository. Store its Client ID as the `RELEASE_APP_CLIENT_ID` Actions
secret and its private key as the `RELEASE_APP_PRIVATE_KEY` Actions secret.

Use Conventional Commits for manual commits and pull-request titles, for
example:

```text
fix: handle Garmin configuration errors
feat(sync): make the Intervals.icu period configurable
docs: rewrite the README in English
```

## Security and limitations

Intervals Coach is a private planning assistant, not a medical device. Keep it
on a trusted LAN or behind a private VPN. Review local library entries before
synchronizing them to Intervals.icu, and seek professional advice for injuries,
illness, or warning symptoms.

Before deleting local data, the Privacy section shows the complete local data
scope and record counts. The action requires entering `LOKALE DATEN LÖSCHEN`.
It deletes only local application data; Intervals.icu, Garmin, and external
calendar data remain unchanged. A best-effort OpenAI conversation deletion is
reported separately when a conversation exists. Create an encrypted backup or
privacy export first if the data may be needed later.

## License

Intervals Coach is licensed under the GNU Affero General Public License v3.0.
See [`LICENSE`](LICENSE) for the full license text.
