# Intervals Coach

Intervals Coach is a private, mobile-first PWA for a single athlete. Its
Python standard-library HTTP server synchronizes training data from
Intervals.icu and, optionally, Garmin Connect, sends a sanitized coaching
context to the OpenAI Responses API, and stores the local application state in
an encrypted SQLite database.

The application is designed for use on a trusted home network or private VPN.
It is not intended to be exposed directly to the public internet.

## Features

- Athlete profile, target competitions, performance metrics, training history,
  chat history, and workout drafts stored locally in SQLite.
- One Intervals.icu synchronization at startup, plus user-requested refreshes.
- Optional Garmin Connect synchronization with deduplication against
  Intervals.icu. Garmin-sourced VO2 max, running predictions, body weight, and
  sport-specific maximum heart rates are explicitly marked as Garmin Connect
  data in the performance view. If Garmin data is unavailable, sport-specific
  maximum heart rates can fall back to Intervals.icu data.
- Activity synchronization for strength training, running, outdoor cycling,
  and indoor/virtual cycling.
- Mobile-first profile and system sections can be collapsed; the planned
  calendar is grouped into collapsible full weeks with compact volume summaries.
  Intervals.icu planned workouts are matched to completed activities through
  their pairing (with a conservative same-day/sport fallback) and show
  workout and weekly compliance percentages. The comparison uses training
  load when available, otherwise moving/elapsed time.
- If adaptive planning shortens a local workout or reduces its intensity due
  to a read-only iCalendar appointment, the linked planned workout records
  that reason and the original versus adjusted duration after approval.
- Google Calendar has no editable iCalendar category field. Add
  `[NO_TRAINING]` to the event description for informational appointments;
  the event remains visible in the external-calendar list but is excluded
  from coaching and adaptive planning.
- Add `[NO_INTENSITY]` to the description when a calendar event should allow
  training but prevent hard sessions; other description tags have no effect.
- Optional weather integration via Open-Meteo: a city or postal code in the
  profile enables a cached 14-day forecast in the planned calendar. For
  outdoor runs and rides, the app suggests a weather-aware time window for
  the next five days, including wind speed, gusts, and direction. In NRW the
  short range uses DWD ICON-D2 and the longer range uses ECMWF IFS HRES. The
  free Open-Meteo tier is intended for non-commercial use and requires
  attribution.
- Thirty-day trends for FTP, thresholds, VO2 max, running predictions,
  readiness, and body weight. Garmin performance values are stored locally as
  compact historical points during synchronization.
- Push-to-talk voice input in the chat: short recordings are transcribed
  server-side and inserted into the editable message field; audio is not stored.
- Coach chat with selectable GPT-5.6 models, configurable thinking level,
  context preview, structured logs, and prioritized steering/FIFO message
  queueing while the coach is responding.
- The coach creates dated local workout drafts only. Each draft requires an
  explicit athlete approval before it can be transferred to the Intervals.icu
  calendar.
- Before a draft is created, the local workout library is checked for an exact
  or similar workout. Existing templates are reused; missing templates are
  added to the Intervals.icu library when the integration is configured.
- Multi-week plans are grouped and can be approved incrementally.
- Bidirectional synchronization of target competitions with Intervals.icu.
- Local athlete check-ins for subjective soreness, stress, motivation, session
  RPE, pain/illness notes, available training time, and day-specific constraints.
- Read-only shared iCalendar integration for the next 90 days. Event
  timing and duration are used as schedule/recovery signals; high-intensity or
  long local drafts on busy days can be proposed as short easy sessions.
- Adaptive plan review that proposes changes to future local drafts after a
  check-in. Changes are shown as a preview and require explicit local approval;
  remote Intervals.icu calendar events are never changed by this process.
- Annual event overview with base, build, peak, taper, and completed phases.
- Optional PWA notifications for pending draft approvals, upcoming events, and
  synchronization errors. Notifications are opt-in and are delivered by the
  browser/service worker while the PWA can run; device workout delivery remains
  delegated to Intervals.icu.
- Configurable Intervals.icu activity synchronization period, data export,
  local cleanup, and retention policy.
- Encrypted database backup download and validated restore with an automatic
  pre-restore copy of the previous database.
- OpenAI usage display for the latest request and token quotas reported by the
  API. Account dollar balances are available through the OpenAI billing
  dashboard or authorized organization access, not through this application.

## Loading and synchronization

After login, the chat and all data already stored locally are rendered first.
The browser then loads the current remote-enriched view in the background. The
authentication request itself does not force a new Intervals.icu, Garmin, or
calendar synchronization: those providers are synchronized at server
startup, once per calendar day in the background, or on demand from the System
tab. The selected activity windows (Intervals.icu and Garmin) are retained
locally and can be changed in that tab.

The browser refreshes the local/remote view every minute while the PWA is
visible and polls more frequently while a manual synchronization is running.
Open-Meteo uses the profile location, keeps a three-hour server-side forecast
cache, and refreshes that location in the background every three hours. A
visible view also refreshes it when the cache has expired.
GitHub release information is checked at most every 15 minutes. The morning
check-in is generated at most once per local calendar day when its required
integrations are configured.

New activities become available to the coach after the startup/daily
Intervals.icu sync, a manual synchronization, or a chat request that
explicitly asks for current/latest training data. The browser's regular state
poll only reads the local snapshot; it does not contact Intervals.icu.

## Target competitions and Intervals.icu

Target competitions are entered manually in the profile with the Intervals.icu
event fields: name, local start date/time, sport/type, category, description,
duration, distance, target, and external ID. They are synchronized in both
directions with Intervals.icu. Local changes are exported as `RACE_A`,
`RACE_B`, or `RACE_C` events with a stable `external_id`; matching race events
from Intervals.icu are imported into the local database.

Competition synchronization accepts strength training, running, outdoor
cycling (`Ride`), and indoor/virtual cycling (`VirtualRide`). Other sports are
skipped. Remote events that were previously linked but no longer exist are
removed locally, and local deletions are propagated to Intervals.icu during the
next synchronization.
The Intervals.icu event ID is stored locally after import or a successful push.
Before creating a new event, synchronization also checks for an existing race
with the same name, date, and sport to avoid creating duplicates.

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
health check, login, and authentication-status endpoints. The same password
is used as the SQLCipher database key. It is never stored by the application
and cannot be recovered if lost. The password must be at least 12 characters
long.

When an existing unencrypted database is first started with `APP_PASSWORD`,
the application migrates it to SQLCipher and keeps a file named
`*.plaintext-backup-*` in the data directory. Protect this backup like any
other unencrypted copy of the database.

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
in the System tab. A successful sync keeps events from today through the next
90 days. A failed refresh leaves the last successful event set in place and
shows the error. Calendar text is untrusted data; it cannot change application
settings or bypass workout approval.

Other supported operational variables are:

```text
OPENAI_MODEL=gpt-5.6-sol
DATA_RETENTION_DAYS=-1
PORT=8090
DATA_DIR=/data
TZ=Europe/Berlin
GITHUB_REPOSITORY=Lukas-Beike/ai-coach
GITHUB_TOKEN=
GITHUB_RELEASE_CHECK_SECONDS=900
```

`DATA_RETENTION_DAYS=-1` is the default and disables automatic deletion. The
application does not impose its own OpenAI request or token limits; it displays
remaining quotas when the API reports them.

The application checks the latest non-draft, non-prerelease GitHub release on
the server and caches the result for 15 minutes by default. A newer release is
shown next to the application version and its release notes are available in
the **System** tab. Set `GITHUB_TOKEN` only when the configured repository is
private; the token remains server-side and is never returned to the browser.

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

The **Profile** tab stores athlete-entered feedback separately from imported
Garmin and Intervals.icu values. This includes subjective stress, soreness,
motivation, session RPE, pain or illness, available time, and other daily
constraints. These values are included in the AI context as local athlete data.

The adaptive planning action reviews future local workout drafts and produces a
change preview. Only after explicit approval are eligible local drafts updated.
It does not overwrite, delete, or reschedule remote Intervals.icu calendar
events.

External calendar events are only planning signals. The heuristic uses the event
date, start/end time, duration, and all-day status to identify drafts that are
hard or long. It does not infer or diagnose an infection from a family event;
illness must still be entered in the athlete check-in. Every suggested change
remains a local preview and requires **Anpassung freigeben**.


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

Logs record external service, operation, path, duration, and result sizes, but
not request payloads or credentials. Client disconnects such as a closed
browser connection are handled as normal aborted requests rather than internal
server failures.

The **System** tab allows the athlete to export local data as JSON or delete
local chats, snapshots, drafts, library entries, competitions, and profile
data. The database file itself remains in place. Chat reset and local cleanup
also attempt to delete the stored OpenAI conversation; data held by external
providers remains subject to their own policies.

For Intervals.icu and Garmin, the System tab also offers a full local
resynchronization. It removes only the locally cached data for that provider
and then fetches it again; cloud data, credentials, and Garmin tokens are not
deleted. While this operation runs, syncs for the affected provider and
Intervals.icu write operations are blocked.

The **System** tab also provides an encrypted database backup download and a
validated restore action. Restoring requires the same `APP_PASSWORD` used by
the backup database. Before replacement, the current database is retained as a
`*.pre-restore-*` copy in `/data`. Keep both files protected.

The login session cookie is valid for 30 days and is protected with `HttpOnly`
and `SameSite=Strict` attributes.

## Development and testing

The backend is a Python standard-library HTTP server. The frontend is served
from `public/` as a browser PWA. Runtime state belongs in `data/` and is not
included in Docker builds.

Run the test suite and syntax checks from the project root:

```powershell
python -m unittest discover -s tests -v
python -m py_compile server.py tests/test_server.py
```

Pull requests run the unit tests and syntax checks. The conventional-commit
workflow validates pull-request titles and commit subjects. Dependabot manages
Python, Docker, and GitHub Actions dependencies and can automatically squash
merge successful update pull requests.

## Releases and container publishing

The container image is published to
`ghcr.io/lukas-beike/ai-coach` only for a published release or an explicitly
started manual publish workflow. Ordinary pushes and pull requests run tests
but do not publish an image.

The `Weekly release` workflow creates the next patch release every Monday at
03:00 UTC from the current `main` branch. If the server-reported
`APP_VERSION` does not match the next release tag, it opens a version-bump PR
instead of pushing to `main`. After that PR is merged, the workflow creates the
release automatically. Its release notes contain all commits since the previous
release. It can also be started manually through **Actions -> Weekly release ->
Run workflow**. The resulting release starts the test and container-publish
workflow, which rejects any release where the tag and `APP_VERSION` differ.

Use Conventional Commits for manual commits and pull-request titles, for
example:

```text
fix: handle Garmin configuration errors
feat(sync): make the Intervals.icu period configurable
docs: rewrite the README in English
```

## Security and limitations

Intervals Coach is a private planning assistant, not a medical device. Keep it
on a trusted LAN or behind a private VPN. Review every workout draft before
transferring it to Intervals.icu, and seek professional advice for injuries,
illness, or warning symptoms.

## License

Intervals Coach is licensed under the GNU Affero General Public License v3.0.
See [`LICENSE`](LICENSE) for the full license text.
