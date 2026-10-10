# Intervals Coach

Intervals Coach is a private, mobile-first Progressive Web App (PWA) designed for a single athlete. Built on Python's standard-library HTTP server and an encrypted SQLCipher SQLite database, it bridges athlete training history and daily health metrics from Intervals.icu and Garmin Connect with OpenAI Responses-compatible conversational AI APIs.

The application serves as an autonomous, conversational training companion. It understands athlete fatigue, manages a structured workout library, schedules future training sessions, analyzes past workouts, tracks environmental weather constraints, and interprets read-only calendar events—all while keeping sensitive biometric data, credentials, and workout plans strictly local and under the athlete's direct control.

Intervals Coach is intentionally standalone and designed for operation on a trusted local network (LAN) or private VPN (such as WireGuard or Tailscale). It must never be exposed directly to the public internet without a trusted, authenticated reverse proxy.

---

## Core Architecture & Principles

- **Single-Athlete Authority**: Built specifically for one athlete. There are no multi-tenant abstractions, user role hierarchies, or hosted cloud dependencies.
- **Local Source of Truth**: The local SQLCipher database is the authoritative source for future planned units, training goals, workout templates, and athlete feedback. Intervals.icu remains the authoritative record of completed historical activities.
- **Explicit Action Gate**: Local Coach actions follow the athlete's direct request. Intervals.icu writes show a separate, session-bound preview that the athlete must approve before a job is queued; the preview expires and rechecks its target before execution.
- **Plan Replacement**: A requested full plan replacement archives local Coach, library, and imported Intervals units within the selected period (or selected plan). Competitions and external calendar blockers remain protected. Remote changes require a separate approved synchronization.
- **Untrusted External Content**: Data received from Intervals.icu, Garmin Connect, Open-Meteo, and external iCalendar feeds is strictly treated as untrusted data, never as system instructions.
- **Zero Cloud Telemetry**: Biometric data, activity recordings, API keys, database keys, and athlete conversations never leave the host server, except when sending sanitized coaching prompts to the user's selected AI provider.
- **Standard-Library Foundation**: The backend runs on Python's native `http.server` without heavyweight web frameworks. Application logic is modularized under `backend/`, keeping `server.py` strictly as a composition root.

The backend import contract is layered: `athlete` is below `weather`, and
`calendar` is below `activities`, which is below `performance`, which is below
`planning`. `http_api` owns HTTP transport and route assembly, `coach` owns
Coach workflows, `sync` owns synchronization and scheduling, `providers` owns
external adapters, and `db` owns persistence. The AST layer tests enforce this
order and the package-cycle fixture is empty.

---

## Release and Database Compatibility

Releases preserve the athlete's existing encrypted database. Schema changes use
explicit, versioned and transactional migrations with upgrade regression tests;
supported previous releases can be upgraded directly, including when an
intermediate release was skipped. A fresh database is only required when the
athlete explicitly chooses to start over. Unknown or newer schemas are rejected
without deleting or partially changing the data.

Version 1.12.21 supports direct updates from 1.12.19 and 1.12.20. Keep the existing
`/data` bind mount and `APP_PASSWORD` when recreating the container. Startup
automatically adds the missing nutrition-product table and indexes before
workers start, retaining existing records and SQLCipher encryption. A failed
migration rolls back; do not replace or reset the data directory to resolve it.

---

## Features

### AI Coach & Conversational Intelligence
- **Natural Language Coaching**: Conversational coaching without rigid trigger words, supporting natural phrasing, corrections, follow-up questions, and pronoun resolution across turns.
- **Responses API Support**: Uses OpenAI Responses-compatible APIs with real-time SSE token streaming. Chat Completions and provider fallback are unsupported.
- **Durable Turn Queueing**: Every chat request is persisted in a durable SQLite background queue before processing, enabling seamless answer recovery across network drops or browser reloads.
- **Permanent Fact Memorization**: Conversational profile updates that save athlete preferences, equipment notes, and constraints to the durable profile only upon explicit confirmation.
- **Request-Specific Context Projection**: Compact daily, activity and dialogue windows for routine turns; detailed local context and additional tools are available on demand, with conservative fallback for continuations.
- **Targeted Clarification Protocol**: Ambiguous coaching prompts generate a single, concrete clarification question stored locally across reloads and model switches until answered.
- **Atomic Training Changesets**: Plan updates, session moves, and workout creations use transactional revision tracking and object hashes to prevent race conditions.
- **Contextual Quick Actions**: Dynamic start cards presenting context-relevant prompts such as the Morning Check-in or recent workout analysis without permanent UI clutter.
- **Intelligent Duplicate Resolution**: Automated inspection of dual-recorded workouts (e.g., Wahoo and Garmin cycling files) that designates canonical recordings while protecting against accidental cloud deletions.
- **Structured Error Recovery**: Robust recovery from provider rate limits and transient network errors with transparent diagnostic reporting and safe rollback of incomplete actions.

### Training Calendar & Workout Planning
- **Calendar Navigation**: The `Kalender` tab combines planned and completed training. `Analyse` contains performance metrics; there is no separate activity-history tab or activity filtering.
- **Collapsible Weekly Calendar**: Mobile-optimized weekly agenda with a date rail, visible planned and completed volume totals, and separate cards for planned and completed sessions. Illness and pain from saved check-ins appear as day notices; days without sessions remain visible. Matched sessions show execution percentages based on load or duration and the original target directly on the card; missed sessions show 0%, while additional activities have no invented target percentage.
- **Configurable Planning Horizon**: User-adjustable calendar display settings controlling past lookback and future planning horizons through the More tab.
- **Plan vs. Actual Pairing**: Intelligent pairing of planned workouts to completed activities using provider pairing IDs with a conservative same-day sport fallback.
- **Visual Volume Comparisons**: Accurate plan-versus-actual volume matching evaluated by training load (TSS) when available, falling back to moving or elapsed duration.
- **Unmatched Activity Display**: Prominent display of completed, unscheduled sessions alongside planned workouts without fabricating missing target metrics.
- **Full Workout Lifecycle Management**: Direct UI and conversational controls to schedule, move, edit, duplicate, archive, restore, and delete planned workouts.
- **Target Period Scoping**: Conversational plan adjustments strictly scoped to requested date ranges, leaving surrounding weeks and existing training blocks untouched.
- **Daily Athlete Check-ins**: Dedicated check-in tracking morning readiness, sleep quality, muscle soreness, perceived stress, and free-form athlete notes.
- **Post-Activity Feedback**: Dedicated local feedback logging for completed workouts, capturing perceived exertion (RPE), equipment details, and workout execution notes.
- **Multi-Phase Season Periodization**: Long-term seasonal planning mapping base, build, peak, taper, and recovery phases anchored to primary competition dates.

### Workout Library & Structured Formats
- **Local Workout Library**: Searchable, categorised repository of reusable endurance and strength workout templates stored entirely in the local encrypted database.
- **Template Lifecycle Management**: Comprehensive tools to create, modify, tag, schedule, archive, and delete reusable workout templates from the UI or via Coach dialogue.
- **Strict Endurance Syntax Enforcement**: Rigorous validation of endurance steps requiring explicit duration or distance alongside defined intensity targets (e.g., `- 15m 50-70%` or `- 6km Z1 HR`).
- **Relative Target Calculations**: Automatic resolution of percentage-based targets against the athlete's current FTP, threshold heart rate, or threshold pace stored in Intervals.icu.
- **Native Repeat Block Formatting**: Standardized parsing for interval repeat blocks with mandatory preceding count headers, blank-line delimitation, and step-level recovery tracking.
- **Prose Support for Non-Endurance Workouts**: Flexible free-form text formatting for strength training, yoga, mobility, and core routines without rigid step constraints.
- **Provider Upload Verification**: Two-phase upload verification ensuring Intervals.icu parses step instructions, duration, and training load before marking a workout synced.
- **Rejection of Ambiguous Formats**: Pre-upload validation rejecting prose-only endurance entries, mismatched target types, and conflicting watt conversions.

### Intervals.icu Synchronization & Mapping
- **Automated Activity Ingestion**: Scheduled and on-demand synchronization pulling completed activities, training loads, and performance metrics from Intervals.icu.
- **Duplicate-Safe Pagination**: Resilient pagination fetching large activity histories in bounded chunks while verifying page boundaries to prevent duplicate entries.
- **Initial Template Import**: One-time read-only import of existing remote workout templates into a dedicated, private 'Intervals Coach' folder upon initial setup.
- **Explicit Plan Synchronization**: Unidirectional push transferring locally approved planned units to the Intervals.icu calendar with stable upsert identifiers.
- **Automatic Performance Refresh**: Immediate background refresh of current fitness (CTL), fatigue (ATL), and form (TSB) following every successful activity synchronization.
- **Unidirectional Write Boundary**: Strict boundary preventing standard read syncs from altering, overwriting, or deleting locally maintained planned workouts.
- **Illness Pause Synchronization**: Explicit synchronization of confirmed illness pauses to Intervals.icu as calendar note entries only upon dedicated athlete request.
- **Bidirectional Competition Sync**: Coordinated synchronization aligning competition dates, priorities (A/B/C), target sports, and goal times between local and remote calendars.

### Garmin Connect Integration & Health Metrics
- **Direct Read-Only Health Sync**: Independent synchronization of Garmin Connect wellness metrics, activity recordings, and physiological measurements.
- **Dedicated Sleep Gating**: Intelligent morning check-in gate that delays morning coaching until the current day's sleep analysis is processed and finalized by Garmin.
- **Overnight Body Battery Tracking**: Targeted extraction of resting stress metrics capturing the final level before sleep and the initial waking level within one hour of rising.
- **Bounded Sleep Retry Engine**: Three-tier exponential retry schedule (15-minute intervals, max 3 attempts) handling delayed Garmin cloud sleep processing.
- **Garmin-Specific Metric Labeling**: Clear source labeling distinguishing Garmin-calculated FTP, running threshold power, threshold HR, threshold pace, and VO2 max from Intervals.icu metrics.
- **Daily Wellness Summaries**: Calendar-integrated daily summaries tracking total steps, floors climbed, active calories, resting heart rate, and overnight HRV. Garmin's dated daily energy expenditure is also shown alongside the nutrition diary, with current-day values marked provisional.
- **Rolling Health Averages**: Automated calculation of 7-day rolling health baselines displayed alongside acute readings on the performance dashboard.
- **Transparent Metric Fallback**: Resilient metric aggregation preserving Intervals.icu values as labeled fallbacks when Garmin biometric readings are absent.

### Weather Intelligence & Outdoor Scheduling
- **Open-Meteo Integration**: Server-side cached 14-day local weather forecasts powered by the non-commercial Open-Meteo meteorological API.
- **Dual-Model Forecast Engine**: Intelligent forecast resolution using high-precision DWD ICON-D2 for short-range predictions and ECMWF IFS HRES for long-range outlooks.
- **Weather Window Recommendations**: Automated calculation of optimal outdoor training windows over the next 5 days based on temperature, precipitation, and wind speeds.
- **Workday Schedule Awareness**: Outdoor suggestions tailored around athlete working hours (06:00-15:30 Monday-Thursday, until 14:00 Friday, with a 12:00-13:00 lunch window).
- **Adaptive Weather Alerts**: Proactive notifications and planned calendar warnings when impending heavy rain, extreme heat, or high winds impact scheduled outdoor sessions.
- **Efficient Server Caching**: 3-hour server-side forecast caching with automatic on-demand cache overrides accessible from the More tab.

### External Calendars & Schedule Constraints
- **Read-Only iCalendar (ICS) Sync**: Secure polling of private external iCalendar feeds (Google Calendar, Apple iCloud, Microsoft Outlook) without write permissions.
- **Rolling 8-Week Event Horizon**: Bounded calendar expansion mapping external life events across an 8-week (56-day) forward-looking window.
- **RFC 5545 Recurrence Engine**: Comprehensive expansion of standard recurring rules (daily, weekly, monthly, yearly) and Google Calendar recurrence exceptions capped at 1,000 instances.
- **Bounded Calendar Processing**: Feeds are limited to 5 MB and 10,000 parsed event components; folded lines, RDATE deduplication and recurrence-exception lookup are processed linearly. Instance records are generated incrementally and feeds exceeding 1,000 unique events in the sync window are rejected. Connected calendar HTTP transfers have a 30-second total deadline.
- **Calendar Training Constraints**: `[NO_TRAINING]`, `[NO_INTENSITY]`, and `[SHORT_ONLY]` are recognized in event titles and descriptions. `[NO_TRAINING]` and `[NO_INTENSITY]` are enforced against planned-workout changes on the affected local calendar day: training is blocked for the former, the latter requires an explicitly easy workout, and `[SHORT_ONLY]` blocks workouts longer than 60 minutes.
- **Visual Schedule Conflict Markers**: Distinctive visual indicators on the planned calendar alerting the athlete to busy days and potential scheduling conflicts.
- **Adaptive Session Replanning**: Heuristic session adjustments that suggest shorter durations or lower-intensity replacements for scheduled workouts on congested days.

### Performance Analytics, Metrics & Trends
- **30-Day Historical Trends**: Long-term tracking and trend lines for FTP, running threshold pace, VO2 max, resting heart rate, heart rate variability (HRV), and body weight.
- **Impulse-Response Fitness Modeling**: Real-time tracking of Chronic Training Load (Fitness), Acute Training Load (Fatigue), and Training Stress Balance (Form).
- **Race Prediction Engine**: Dynamic race time estimations across standard distances (5K, 10K, Half Marathon, Marathon) based on current aerobic threshold and VO2 max trends.
- **Sport-Specific Intensity Distributions**: Heart rate and power zone distribution analysis across running, outdoor cycling, and indoor/virtual cycling activities.
- **Nutritional Intake Logging**: Integrated tracking of daily caloric intake and macronutrient splits (protein, carbohydrates, fats) stored alongside training load.
- **Explicit Metric Freshness**: Clear differentiation between observation timestamps and synchronization retrieval times to prevent outdated metrics appearing fresh.

### Multimodal Inputs & File Attachments
- **Push-to-Talk Voice Input**: Low-latency voice recording in chat with real-time server-side transcription and zero persistence of raw audio recordings.
- **Multi-File Attachment Support**: Seamless file upload supporting up to 4 concurrent GPX tracks, FIT files, or image files (PNG, JPEG, WebP) up to 5 MB each.
- **Server-Side GPX Processing**: In-memory parsing of GPX tracks calculating total distance, un-smoothed elevation gain, and sampled geographic coordinates for the Coach.
- **Binary FIT Activity Summaries**: Local extraction of binary FIT files summarizing elapsed time, distance, normalized power, average heart rate, and cadence.
- **Visual Technique Analysis**: Image forwarding to multimodal AI models enabling visual evaluation of training charts, race routes, or workout screenshots.
- **Encrypted Attachment Storage**: Durable storage of uploaded attachments within the encrypted SQLite database, included in full backups and privacy exports.

### PWA, Mobile Experience & Offline Capabilities
- **Installable Progressive Web App**: Responsive PWA optimized for mobile, tablet, and desktop viewports, installable on iOS, Android, macOS, and Windows.
- **Reliable Hash-Based Navigation**: Accessible URL routing (`#coach`, `#plan`, `#analysis`, `#more`) preserving browser history, deep links, and screen-reader announcements.
- **Immutable Static Asset Caching**: Versioned static asset serving with one-year immutable cache headers, accompanied by instant service worker cache eviction on updates.
- **Resilient Offline App Shell**: Pre-cached application shell allowing view navigation and inspection of previously loaded training data during network drops.
- **Auto-Reconnecting SSE Streaming**: Server-Sent Events stream with exponential backoff (capping at 30 seconds) ensuring smooth recovery after connection drops.
- **Touch-Friendly Collapsible Views**: Ergonomic mobile interface featuring collapsible profile headers, compact calendar cards, and thumb-friendly bottom navigation.
- **Light and Dark Appearance**: Choose the system setting, light mode, or dark mode under More → Appearance; the choice is stored on this device.
- **Chat Controls**: Keep the composer available while reading older messages, jump to the latest reply, stop a response, copy messages, and edit a prior user prompt as a new draft.
- **Accessible Keyboard Shortcuts**: Desktop navigation supporting Enter-to-send, Shift+Enter for line breaks, Esc for modal dismissal, and ARIA live announcements.

### Privacy, Security & Data Management
- **SQLCipher AES-256 Encryption**: Complete encryption of all athlete data, metrics, tokens, chat history, and attachments at rest using `APP_PASSWORD`.
- **Strict Session Security**: High-security session cookies hardened with `HttpOnly`, `SameSite=Strict`, and optional `Secure` flags.
- **Bounded HTTP Input**: At most 32 active handlers, with separate 20-second absolute limits for request headers and bodies. Login admission is checked before reading its body; these input limits do not shorten Coach responses or SSE streams.
- **Zero Third-Party Trackers**: Self-hosted architecture containing zero tracking scripts, third-party analytics, external CDNs, or telemetry reporting.
- **Comprehensive Privacy Export**: Single-click export producing a complete, unencrypted JSON archive of all profile records, workouts, metrics, and chat history.
- **Confirmed Local Data Purge**: Irreversible deletion of all local athlete data guarded by an explicit typed confirmation phrase (`LOKALE DATEN LÖSCHEN`).
- **Zero-Downtime Maintenance Mode**: Process-level maintenance gate that prevents concurrent writes and ensures transaction safety during database restoration.
- **Pre-Restore Rollback Copies**: Automated creation of a safety copy of the existing database before executing any database restore or replacement.
- **Redacted Operational Logging**: Structured server logs that correlate technical operation IDs while stripping authentication headers, tokens, and athlete text.
- **Always-on Technical Diagnostics**: Bounded diagnostic logger (up to 10,000 entries, 16 MiB total, 1 MiB per entry) recording sanitized Coach requests and responses, provider error details, tool activity, and error traces. Credentials, keys, tokens, and session data are removed before storage.

---

## System Architecture & Data Flow

```text
               +-------------------------------------------------------------+
               |                       Trusted Athlete                       |
               |                (Mobile PWA / Desktop Browser)               |
               +------------------------------+------------------------------+
                                              | HTTPS / WSS / SSE
                                              v
               +-------------------------------------------------------------+
               |                  Reverse Proxy (Caddy / Nginx)              |
               |               Terminates TLS, Sets Secure Headers           |
               +------------------------------+------------------------------+
                                              | HTTP (Port 8090)
                                              v
+-------------------------------------------------------------------------------------------+
| Intervals Coach Container (/app)                                                          |
|                                                                                           |
|  +-------------------------------------------------------------------------------------+  |
|  | server.py (Composition Root & HTTP Server)                                          |  |
|  +-------------------------------------------+-----------------------------------------+  |
|                                              |                                            |
|                                              v                                            |
|  +-------------------------------------------------------------------------------------+  |
|  | backend/ Domain Layer                                                               |  |
|  |   - backend.http_api  : HTTP routing and request/response transport                 |  |
|  |   - backend.coach     : Coach conversations, context, tools, jobs and SSE           |  |
|  |   - backend.sync      : Provider synchronization, scheduling and durable jobs       |  |
|  |   - backend.providers : External provider adapters and response handling            |  |
|  |   - backend.athlete   : Profile, check-ins and athlete-local time                  |  |
|  |   - backend.activities: Activity reads, matching, feedback and workout projections  |  |
|  |   - backend.performance: Derived/readiness context and chart history                |  |
|  |   - backend.planning  : Plans, library, workouts, conflicts and season preparation  |  |
|  |   - backend.weather   : Weather projections and caching                              |  |
|  |   - backend.calendar  : Public/external calendar data                                |  |
|  |   - backend.nutrition : Nutrition entries, templates and product workflows          |  |
|  |   - backend.backup    : Export, validation and restore workflows                    |  |
|  |   - backend.diagnostics: Safe diagnostics and logging views                         |  |
|  |   - backend.history   : Change history and undo                                      |  |
|  |   - backend.runtime   : Lifecycle and maintenance state                              |  |
|  |   - backend.db        : Repositories, schema and SQLCipher persistence              |  |
|  +-------------------------------------------+-----------------------------------------+  |
|                                              |                                            |
|                                              v                                            |
|  +-------------------------------------------------------------------------------------+  |
|  | Persistent Storage Mount (/data)                                                    |  |
|  |   - intervals-coach.db (SQLCipher encrypted database)                               |  |
|  |   - garmin_tokens (Garmin OAuth token store)                                        |  |
|  |   - intervals-coach.db.pre-restore-<timestamp>-<id> (restore safety copies)          |  |
|  +-------------------------------------------------------------------------------------+  |
+-------------------------------------------------------------------------------------------+
       |                                |                             |
       | HTTPS REST                     | HTTPS (curl_cffi)           | HTTPS REST
       v                                v                             v
+------------------+         +--------------------+         +--------------------+
|  Intervals.icu   |         |   Garmin Connect   |         |  Open-Meteo & ICS  |
|  - Activities    |         |   - Sleep & Stress |         |  - 14-Day Forecast |
|  - Fitness/Form  |         |   - Body Battery   |         |  - Rain & Wind     |
|  - Plan Uploads  |         |   - Health Totals  |         |  - Life Calendars  |
+------------------+         +--------------------+         +--------------------+
```

The browser client is a plain JavaScript PWA. `app.js` bootstraps the client;
`auth.js` owns login, session, confirmation, and app-shell loading; `shared.js`
owns generic helpers and cross-view UI state; `sync-status.js` owns sync,
connectivity, provider freshness, and progress state; and `sync-actions.js`
owns refresh actions. `notifications.js` owns notification permission,
notifications, and service-worker registration. `performance-view.js` owns
performance, Garmin, and editable metrics; `diagnostics.js` owns change
history, logs, and diagnostic capture; and `settings.js` owns profile,
check-ins, model and calendar settings, backups, and privacy actions. The
remaining modules own their named domains: `api.js`, `navigation.js`,
`state.js`, `state-loader.js`, `views.js`, `plan-views.js`, `coach.js`,
`analysis.js`, `activity-details.js`, `nutrition.js`, `forms.js`,
`components.js`, and `appearance.js`. The service worker owns the offline
asset cache.

---

## Configuration & Environment Variables

All configuration is loaded from container environment variables or a local `.env` file mounted in `/data/.env` or the application root.

### Environment Variable Reference

| Variable | Default Value | Required? | Description |
| :--- | :--- | :--- | :--- |
| `APP_PASSWORD` | *None* | **Yes** | Master password (minimum 12 characters). Secures web UI authentication and acts as the encryption key for the SQLCipher database. |
| `OPENAI_API_KEY` | *None* | **Yes** | Server-side API key for the OpenAI Responses API or compatible endpoint. |
| `OPENAI_MODEL` | `gpt-6-luna` | No | OpenAI model deployment name (GPT-6 Luna). |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | No | Optional Responses-compatible API base URL. HTTPS is required; HTTP is allowed only for loopback addresses. |
| `INTERVALS_API_KEY` | *None* | **Yes** | Personal API key obtained from Intervals.icu account settings. |
| `INTERVALS_ATHLETE_ID` | `0` | No | Athlete ID for Intervals.icu (`0` targets the athlete account associated with the API key). |
| `GARMIN_EMAIL` | *None* | No | Garmin Connect account email. Used only during initial interactive login. |
| `GARMIN_PASSWORD` | *None* | No | Garmin Connect account password. Used only during initial interactive login. |
| `GARMINTOKENS` | `/data/garmin_tokens` | No | File path to the persisted Garmin OAuth token store. |
| `GARMIN_FIXTURE_PATH` | *None* | No | Local mock JSON fixture path for development and testing without live Garmin credentials. |
| `CALENDAR_ICAL_URL` | *None* | No | Private read-only iCalendar (ICS) feed URL from Google Calendar, iCloud, or Outlook. |
| `COOKIE_SECURE` | `false` | No | Set to `true` when running behind an HTTPS reverse proxy to add the `Secure` flag to cookies. |
| `DATA_RETENTION_DAYS` | `-1` | No | Retention period in days for historical sync logs and data. `-1` retains data indefinitely. |
| `PORT` | `8090` | No | Internal HTTP port the application listens on. |
| `DATA_DIR` | `/data` | No | Path to the directory where the encrypted database and tokens are stored. |
| `TZ` | `UTC` | No | Container timezone (e.g., `Europe/Berlin`). Crucial for accurate daily scheduling and sleep windows. |

---

## Installation & Deployment

### Docker Run

Run the published container image with a persistent data volume and read-only container root:

```sh
docker pull ghcr.io/lukas-beike/ai-coach:latest

docker run -d \
  --name ai-coach \
  --restart unless-stopped \
  --read-only \
  --security-opt no-new-privileges:true \
  --cap-drop=ALL \
  -p 8090:8090 \
  -v /mnt/user/appdata/ai-coach/data:/data \
  --env-file /mnt/user/appdata/ai-coach/.env \
  -e TZ=Europe/Berlin \
  ghcr.io/lukas-beike/ai-coach:latest
```

*Note: Never run `docker rm -v`, as the `/data` volume contains your encrypted database and token stores.*

### Docker Compose

Create a `docker-compose.yml` file:

```yaml
services:
  ai-coach:
    image: ghcr.io/lukas-beike/ai-coach:latest
    container_name: ai-coach
    restart: unless-stopped
    read_only: true
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    ports:
      - "8090:8090"
    volumes:
      - ./data:/data
    env_file:
      - .env
    environment:
      - TZ=Europe/Berlin
```

Start the service:

```sh
docker compose up -d
```

### Unraid Deployment Guide

1. **Prepare Appdata Directory**:
   Create the storage folder on your cache pool and ensure it is writable by the container user (UID 100 / GID 101 or standard app permissions):
   ```sh
   mkdir -p /mnt/user/appdata/ai-coach/data
   chmod -R 770 /mnt/user/appdata/ai-coach/data
   ```
2. **Container Template Setup**:
   - **Repository**: `ghcr.io/lukas-beike/ai-coach:latest`
   - **Network Type**: `Bridge`
   - **Container Port**: `8090` -> **Host Port**: `8090`
   - **Container Path `/data`**: `/mnt/user/appdata/ai-coach/data` (Read/Write)
   - **Environment Variables**: Add `APP_PASSWORD`, `OPENAI_API_KEY`, `INTERVALS_API_KEY`, `TZ`, etc.
   - **Icon URL**: `https://raw.githubusercontent.com/Lukas-Beike/ai-coach/main/public/logo.png`
3. **Save and Start**: Start the container and check `docker logs -f ai-coach`.

### HTTPS Reverse Proxy Setup

Modern mobile browsers require a **Secure Context (HTTPS)** to register Service Workers, install Progressive Web Apps (PWAs), and enable microphone audio recording for push-to-talk voice. Always terminate TLS using a trusted reverse proxy.

#### Caddy Example
```caddy
coach.internal.domain {
    reverse_proxy ai-coach:8090 {
        header_up X-Forwarded-Proto https
    }
}
```

#### Nginx Example
```nginx
server {
    listen 443 ssl http2;
    server_name coach.internal.domain;

    ssl_certificate /etc/letsencrypt/live/coach.internal.domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/coach.internal.domain/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8090;
        proxy_http_version 1.1;

        # WebSocket and SSE Streaming support
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        # Disable buffering for live SSE token streaming
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}
```
*When deploying behind HTTPS, remember to set `COOKIE_SECURE=true` in your `.env`.*

### Garmin Authentication & MFA Setup

Garmin Connect enforces Multi-Factor Authentication (MFA). Complete the initial authentication interactively using the bundled `garmin-login.py` script:

1. Ensure `GARMIN_EMAIL` and `GARMIN_PASSWORD` are defined in your `.env` file.
2. Run the interactive login helper inside a temporary container attached to your persistent data directory:
   ```sh
   docker run --rm -it \
     --env-file /mnt/user/appdata/ai-coach/.env \
     -v /mnt/user/appdata/ai-coach/data:/data \
     ghcr.io/lukas-beike/ai-coach:latest \
     python /app/garmin-login.py
   ```
3. Enter the MFA code sent to your email or mobile device when prompted.
4. The helper generates an encrypted OAuth token store saved to `/data/garmin_tokens`.
5. Once complete, you may safely remove `GARMIN_PASSWORD` from your `.env`. Restart the `ai-coach` container, and it will authenticate automatically using the persisted tokens.

---

## Loading, Synchronization & Job Architecture

### Background Scheduling Engine
- **Startup**: On launch, `server.py` composes configuration, persistence, providers, HTTP routes and workers; startup initializes the database and enqueues configured refreshes.
- **Hourly Provider Cycle**: The scheduler loop wakes every 300 seconds. Calendar, Garmin and Intervals refreshes become eligible once their latest attempt or success is at least 3,600 seconds old; weather refreshes are queued on a pass when a location is configured and no weather job is active.
- **Garmin Recent History**: Manual activity synchronization defaults to 84 days for both providers. Automatic Garmin synchronization first loads 84 days of activities, sleep, HRV, daily statistics and resting heart rate where supported. Subsequent hourly refreshes normally read today and yesterday. Successfully read continuous date windows are retained per collection; failed collections do not advance their coverage. After an outage, refreshes catch up from the oldest collection endpoint with overlap, bounded to 90 days per request. Historical activity backfills do not advance recovery coverage.
- **Analysis Coverage**: Charts expose the number of available dated values; recovery charts show measured days and prior nights in the 42-day personal baseline. Training focus shows locally known Garmin sessions and their observation dates. Missing measurements and recordings remain unknown, never confirmed zeros or rest days.
- **Periodic Synchronization Loop**: Each loop pass enqueues eligible calendar, Garmin and Intervals refresh jobs and runs the morning Body Battery refresh. The loop uses the athlete's local clock for provider freshness markers; there is no fixed 03:00 daily run.
- **On-Demand Refreshes**: The UI and Coach can enqueue provider, calendar, weather and performance refresh work through the documented API routes.

### Priority Queue & Durable Job Processing
Conversational turns are persisted in `coach_commands`; provider synchronization and background work use durable jobs in `sync_jobs`.
- **Streaming Handshake**: When an HTTP turn starts, Server-Sent Events (SSE) immediately return the durable job UUID.
- **Decoupled Execution**: If the athlete locks their phone or loses cellular connection, the server continues execution uninterrupted.
- **Recovery on Reconnect**: Upon reconnection or app reload, the PWA polls the durable job result using its UUID, rendering the completed answer without re-executing actions.
- **Visible Provider Failures**: OpenAI API credit, quota, spending-limit, access, rate-limit, unavailable-model, conversation-state, timeout, and service-unavailability failures produce a clear recovery instruction in the chat history, including classified failures reported inside an HTTP-200 response stream. The message remains visible after reload; private provider error text is not shown. Unknown failures use a safe technical-error message with retry and diagnostic-export guidance.

### Provider Data Handling
- **Intervals.icu Activity Pull**: Ingests new completed workouts with full telemetry (duration, distance, TSS, HR zones, power curves). Large imports are safely fetched in paginated windows.
- **Garmin Sleep Gate & Body Battery**: Morning synchronization deliberately halts until Garmin's sleep window completes. Body Battery tracking captures the final pre-sleep value and the wake-up value within 60 minutes of rising, retrying up to 3 times with 15-minute intervals.
- **Open-Meteo Weather**: Forecasts are fetched for the athlete's coordinates and cached for 3 hours. Short-range predictions use Germany's DWD ICON-D2 model, transitioning to ECMWF IFS HRES for 14-day projections.
- **iCalendar (ICS) Life Constraints**: The external feed is parsed up to 8 weeks out. Events containing `[NO_TRAINING]`, `[NO_INTENSITY]`, or `[SHORT_ONLY]` in their description are tagged as training constraints.

---

## Coach Intelligence & Execution Boundaries

### Prompt Projection & Context Budgeting
To optimize API token consumption and response latency, Intervals Coach uses a strictly bounded context projection rather than dumping entire databases into prompts:
- **Request Profiles**: General coaching, today's training, activity analysis, weekly planning, plan edits, competition preparation, profile/check-in, provider sync and attachments select different projections. Selection is not an authorization decision.
- **Activity Projection**: Routine turns include the newest completed activity per sport; planning and analysis retain up to five. Exact activity details remain available through the existing read tools.
- **Planning Projection**: Routine turns include a three-day outlook and two recent days; weekly planning includes a 14-day outlook. Daily planning combines recovery, illness/check-ins, weather and calendar constraints instead of repeating separate provider histories. Confirmed profile constraints, competitions and labeled current performance remain available.
- **On-Demand Details**: `read_coach_context` loads selected omitted local sections without a provider refresh. Its output is bounded to 40,000 characters and marks incomplete results. Successful reads also expose remaining tools already permitted for the turn, without granting mutation or remote-write authorization.
- **Conservative Fallback**: Pending requests, short continuations, explicit provider refresh/sync requests and long-range or explicitly dated planning retain full bounded context and tools. A clear topical request does not select full training context merely because it contains a pronoun such as "das" or "diese". The 120,000-character training-context cap, model selection, attachment handling and output-token limits remain unchanged.
- **Refresh Follow-Ups**: After refresh results, the Coach rebuilds current data using the original request topic and attachment context. Existing tool receipts retain dialogue continuity without automatically expanding all training sections or tools.
- **Library Selection**: Template descriptions are included for planning, not ordinary questions; library read tools remain available when details are needed.
- **Metric Sanitization**: Raw JSON payloads from providers are stripped down to core athletic parameters (FTP, TSS, RPE, Heart Rate, Power Zones, Duration, Distance).
- **Dialogue Pruning**: Routine requests send up to eight recent messages and three completed-action receipts. Pending work, pronoun references and resumed tool work retain the full bounded dialogue and source IDs; authorization still uses the original local dialogue. The current user message is sent once, separately with its source ID, and request JSON omits unnecessary separator whitespace. Remote conversation chains are pruned between distinct command sessions.
- **Size Diagnostics**: Context profiles, section character counts and request/tool-schema sizes are recorded without athlete content. Character counts are not provider token measurements; synthetic reduction tests do not establish live quality or latency.
- **Context Preview**: The preview remains a full local context overview; actual request selection depends on the message subsequently sent.

### Tool Execution & Reversible Changesets
The Coach interacts with the athlete's data via structured tools covering plan inspection, template management, profile editing, nutrition correction, and provider synchronization:
- **Transaction Locks**: All database updates share SQLite transaction locks to guarantee that conversational actions and background syncs never collide.
- **Revision Control**: Plan modifications require passing the current planning revision and object hash, preventing overwrite collisions if edits occur concurrently.
- **Remote Approval**: Intervals.icu changes remain proposals until the athlete approves their visible scope. A changed or stale workout manifest fails closed, and approval is bound to the current session and originating Coach turn.
- **Receipt Verification**: Tool invocations produce structured receipts in the chat UI, distinguishing saved local modifications, pending approval, queued sync jobs, and rejected parameters.

### Multimodal Capabilities
- **Voice Transcription**: Push-to-talk voice recording captures audio directly in the PWA. Audio is streamed to `/audio/transcriptions` in memory and inserted into the message box. Raw audio is never persisted.
- **File Attachments**: Athletes can attach up to 4 GPX, FIT, or image files (max 5 MB each) per turn. GPX tracks are summarized locally (distance, elevation, GPS bounds); FIT files are parsed for power and cardiac data; images are sent for vision-based AI coaching.

---

## Workout Export & Syntax Specification

Endurance workouts synchronized to Intervals.icu must comply with the native workout builder syntax. The application validates workout text locally before attempting remote synchronization:

See the [workout export examples and verification contract](docs/workout-export-format.md) for detailed provider readback rules.

### Format Specification & Examples

#### Cycling Intervals (Power & Cadence Targets)
```text
Warmup
- 15m ramp 50-70%
- 3m 80%
- 3m 50-60%

Main Set
3x
- 8m 88-92% 85-95rpm
- 4m 50-60%

Cooldown
- 10m 50-60%
```

#### Running Workout (Pace & Heart Rate Targets)
```text
Warmup
- 15m Z1 HR

Main Set
- 6km Z2 Pace
- 1km 90-95% HR

Cooldown
- 10m Z1 HR
```

### Strict Validation Rules
1. **Executable Steps Required**: Endurance workouts (Ride, Run, Swim, Row) require explicit step durations (`m`, `s`) or distances (`km`, `m`) paired with an intensity target.
2. **Relative Targets Preferred**: Use percentage FTP (`88-92%`) or zones (`Z2 HR`). Do not hardcode absolute wattages into steps, as they conflict with dynamic FTP adjustments.
3. **Repeat Block Formatting**: Multi-interval blocks must begin with a repeat line (e.g., `3x`) and must be surrounded by blank lines. All steps within the block repeat equally.
4. **Non-Endurance Activities**: Strength training, yoga, and mobility workouts use free-text prose instructions and bypass step validation.

---

## Data Integrity, Privacy, Backups & Maintenance

### SQLCipher Encryption
All persistent application state is stored in `/data/intervals-coach.db` encrypted with AES-256 via SQLCipher. The database key is derived from `APP_PASSWORD`. The application will refuse to start without SQLCipher libraries present.

### Maintenance Mode & Database Restoration
When a database restore is initiated:
1. The application enters an exclusive maintenance mode, rejecting new incoming API mutations with an HTTP 503 maintenance notice.
2. Active background sync jobs and Coach turns are allowed to finish gracefully.
3. If an active database exists, a timestamped pre-restore copy is saved beside it in `/data` using the name `intervals-coach.db.pre-restore-<timestamp>-<id>`.
4. Supported older schemas are migrated on the staged backup copy. The replacement database must then match the current schema and pass SQLite integrity and foreign-key checks. Restored sessions are cleared before it is installed; failed validation rolls back the staged changes.
5. If valid, the new database is swapped into place and the maintenance gate is lifted; if invalid, the original database is preserved without data loss.

### Privacy Export & Data Purge
- **Full Privacy Export**: Download a single comprehensive JSON archive containing all stored profile fields, workouts, check-ins, activity notes, and chat history.
- **Local Data Purge**: Completely wipes all local athlete records from the database. To prevent accidental loss, the action requires entering the exact confirmation phrase `LOKALE DATEN LÖSCHEN`. External accounts (Intervals.icu and Garmin) remain untouched.

### Operational Logging & Diagnostics
- **Sanitized Logs**: Standard container logs contain only operational timestamps, correlation IDs, status codes, and anonymized error classifications. API tokens, passwords, and athlete metrics are never logged.
- **Always-on Technical Diagnostics**: The application keeps up to 10,000 recent diagnostic entries (16 MiB total, 1 MiB per entry, with truncation marked), including sanitized Coach requests, provider responses, tool activity, and provider error messages. Credentials, keys, tokens, and session data are removed before storage.
- **Server Log Management**: In **Betrieb & Diagnose**, authenticated users can download the sanitized current server log and its available rotations as JSON Lines, or delete the log files.
- **Diagnostics Management**: In **Betrieb & Diagnose**, authenticated users can download the sanitized technical diagnostic report as JSON, or clear the stored technical diagnostic entries.

---

## Development, Testing & Contribution

### Local Development on Windows

Because native Windows environments often lack compatible pre-compiled wheels for `sqlcipher3-binary`, the canonical development and testing environment is the local Docker container.

1. **Clone and Prepare**:
   ```powershell
   git clone https://github.com/Lukas-Beike/ai-coach.git
   cd ai-coach
   Copy-Item .env.example .env
   New-Item -ItemType Directory -Force .\data
   ```
2. **Build Local Image**:
   ```powershell
   docker build -t ai-coach:local .
   ```
3. **Run Local Container**:
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
4. Access `http://localhost:8090` in your browser. Inspect logs using `docker logs -f ai-coach`.

### Testing & Quality Assurance

The [Coach dialogue evaluation rubric](docs/coach-dialogue-evaluation.md) and [executable tool coverage matrix](docs/coach-tool-coverage.md) describe the current conversation and tool checks.

The current HTTP route inventory is in [docs/api-routes.md](docs/api-routes.md).

#### Native Python Unit Tests
Run standard unit tests with temporary in-memory fixtures (mocking external providers):
```powershell
python -m unittest discover -s tests -v
python -m compileall -q server.py backend tests
```

#### Parallel Sharded CI Runner
Run test shards matching the GitHub Actions CI pipeline:
```powershell
python tests/run_tests.py --shard 1 --total 4
```

#### Isolated SQLCipher Integration Tests
Execute full SQLCipher container tests without exposing local host `.env` or data files:
```powershell
./tests/run_sqlcipher_tests.ps1
```

#### Playwright Browser E2E Tests
End-to-end browser testing validates PWA responsiveness, keyboard navigation, and UI flows across 5 device viewports:
```sh
npm ci
npm run test:e2e
```
Functional contracts run once on desktop. Tests tagged `@responsive` also run on
all four smaller viewports. CI runs the five projects in independent jobs, with
a fresh disposable SQLCipher fixture per spec and one worker per invocation.
Chromium downloads are cached by the locked dependency version; system
dependencies are installed on every runner. Follow
`.agents/skills/ai-coach-pwa-e2e/references/browser-validation.md` for safe local
fixture setup; never target a connected installation.

Configured viewports in `playwright.config.cjs`:
- `mobile-small`: 320x568 (Compact mobile)
- `mobile`: 390x844 (Standard mobile)
- `tablet`: 768x1024 (Tablet portrait)
- `tablet-landscape`: 844x390 (Mobile/tablet landscape)
- `desktop`: 1440x1000 (Desktop workstation)

#### Standard synthetic preview data

The disposable fixture runtime exposes `GET /api/fixture/demo` for a reusable,
mobile-safe preview. It seeds profile, check-ins, nutrition, competitions,
library workouts, activity details, recovery, body history, Garmin daily
calories, dated Garmin FTP and Intervals.icu eFTP, calendar marker examples,
and active, archived, component, zero-target, no-target, and over-target gear.
All values are synthetic and providers remain blocked; no credentials or live
athlete data are read. The seed is idempotent and carries a version marker so
an older demo seed is upgraded in place when the disposable database is reused.
Use a fresh fixture browser profile and check the mobile-small and mobile
projects when reviewing this preview.

`scripts/demo-container.ps1` builds the image and starts a disposable demo
container that seeds this data itself on every start (`FIXTURE_AUTO_SEED=1`;
idempotent). Run it with
`powershell -ExecutionPolicy Bypass -File scripts/demo-container.ps1`; add
`-Persist` to keep the data in a named volume and `-Port`/`-Name` to adjust the
container. The login password is the fixture password
`e2e-fixture-password-1234`. Never point it at a real `/data` directory.

### Dependency lock maintenance

`requirements.in` and `requirements-dev.in` contain direct pins. The matching
`requirements.txt` and `requirements-dev.txt` files are pip-tools outputs with
hashes; Docker and CI install those locked files with `--require-hashes`.
Dependabot recognizes this `.in`/`.txt` pairing and updates both files. When
regenerating locally, use Python 3.14 on Linux (the SQLCipher wheel is not
available on native Windows):

```text
pip-compile --allow-unsafe --generate-hashes --output-file=requirements.txt requirements.in
pip-compile --allow-unsafe --generate-hashes --output-file=requirements-dev.txt requirements-dev.in
```

### Continuous Integration & Native Codex Reviews
- **Conventional Commits**: All commit messages and pull request titles must follow the Conventional Commits specification (e.g., `feat(coach): add structured response support` or `fix(sync): resolve Garmin sleep retry backoff`).

- **Native Codex Reviews**: In [Codex Settings](https://chatgpt.com/codex/settings/code-review), enable automatic code review for this repository and select the trigger for new PRs and subsequent pushes. The watchdog waits at most three minutes for a native Codex comment. If none appears, it posts one `@codex review` fallback for that PR commit, then waits up to three minutes for the regular review or explicit exhausted-usage response. The latter grants an availability exception; continued silence fails the check. A later Codex comment or submitted review automatically reruns the check and recovers a late response. Inspect the reviewed commit and resolve all findings before merging. Local `codex review --base origin/develop` is an optional preflight. After adopting the watchdog on each protected branch, require its `Codex review availability` context in the ruleset. Account-level activation must be verified in Codex Settings. Copilot automatic review is disabled in repository rulesets.
- **Dependency Updates**: Dependabot updates pip, npm, Docker and GitHub Actions on `develop`. Squash auto-merge is enabled for patch, minor and major updates; protected-branch checks and review-thread resolution still apply. The privileged auto-merge workflow never checks out or executes PR code.
- **Automated Daily Releases**: At 03:00 UTC, an automated workflow inspects `develop`. If new commits exist, it creates a version-bump PR and a promotion PR to protected `main`. Both branches require native, SQLCipher container, quality and browser checks without bypass actors. After successful main tests, the workflow creates an immutable GitHub release and publishes the container. The container digest is signed and verified before promoting `latest`; the version tag and `latest` must resolve to that same digest. A read-only release preflight also verifies `APP_VERSION` before its tag exists. Actions use read-only default permissions, with explicit job-level write permissions where needed.

---

## Security Boundaries & Medical Disclaimer

Intervals Coach is a personal athletic planning assistant, not a certified medical device. Training recommendations, adaptive replanning suggestions, and performance analytics are generated by artificial intelligence models and heuristic algorithms. 

Always listen to your body. Do not follow workout intensity or duration recommendations that cause sharp pain, dizziness, or symptoms of overtraining. Consult a certified medical professional or sports physician before undertaking high-intensity endurance training or if recovering from illness or injury.

---

## License

Intervals Coach is open-source software licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**. See [`LICENSE`](LICENSE) for the complete license terms.

### Ernährung und gespeicherte Mahlzeiten

Das Tagebuch zeigt jedes zusammengesetzte Essen als einen Eintrag; Zutaten lassen sich in der Karte aufklappen. Gespeicherte Produkt- und Datenbank-Snapshots bewahren die verwendete Herkunft auch nach späteren Produktänderungen. Unbekannte Nährwerte bleiben unbekannt und werden in Karten und Tagessummen nicht als Null ausgegeben. Der Eintrag bleibt lokal; eine Synchronisierung nach Intervals.icu erfolgt nur nach ausdrücklicher Freigabe.

Der Tab **Ernährung** zeigt das Tagebuch mit Kalorien und Makros sowie **Meine Mahlzeiten**. Erfassung, Korrekturen und Löschen laufen über den Coach per Text, Sprache oder Foto. Aktionen im Tab bereiten eine bearbeitbare Nachricht vor; sie speichern und senden nichts automatisch. Ein vorhandener Chatentwurf bleibt erhalten.

Mit "Definiere mein Standardfrühstück" lassen sich wiederverwendbare Mahlzeiten mit Zutaten, Mengen und Nährwerten für eine Portion anlegen. Der Coach zeigt die Vorlage zur Bestätigung, bevor er sie speichert. Eine Vorlage zählt noch nicht als gegessen. "Ich habe eine halbe Portion meines Standardfrühstücks gegessen" erfasst den Verzehr mit entsprechend skalierten Nährwerten. Einmalige Abweichungen verändern nur den Tagebucheintrag; dauerhafte Änderungen verändern die Vorlage und niemals frühere Einträge.

Der Coach bevorzugt **BLS 4.0** für Grundnahrungsmittel und **Open Food Facts** für Markenprodukte und Barcodes. Der Backend-Code berechnet Kalorien und Makros aus den ausgewählten Lebensmittel-IDs und Mengen; Datenbankquelle, Bezugsmenge und Zutatenmengen bleiben im Eintrag und in Mahlzeitvorlagen erhalten und werden im Ernährungstab angezeigt. Die aktuelle OFF-Produkt-API wird über ihre strukturierte Nährwertdarstellung gelesen; automatisch ergänzte OFF-Schätzwerte und Angaben wie „kleiner als“ werden nicht als exakte Etikettwerte übernommen. Rohes und gegartes Gewicht sind nicht austauschbar; Gramm und Milliliter werden nicht ohne Dichte umgerechnet. Mehrdeutige Produkte oder unbekannte Mengen müssen geklärt werden. Ohne passenden Treffer bleiben Verpackungswerte oder ausdrücklich gekennzeichnete KI-Schätzungen möglich. Fehlende Makros und nicht erfasste Tage werden nicht als vollständige Nullwerte dargestellt.

**Zugang und Limits:** BLS ist als lokaler Datensatz eingebunden und funktioniert ohne API-Key, Konto oder laufende API-Abfragen. Open Food Facts benötigt für Lesezugriffe keinen API-Key; die Anwendung identifiziert sich mit einem User-Agent. Die aktuell dokumentierten IP-Limits sind 15 Produktabfragen und 10 Suchabfragen pro Minute. Die Anwendung begrenzt sich auf 14 bzw. 9 Abfragen pro Minute, speichert Antworten maximal 24 Stunden im begrenzten Arbeitsspeicher-Cache und pausiert bei 429/503. Andere Anwendungen hinter derselben öffentlichen IP teilen sich die Anbieterlimits. Keine Suche bei jedem Tastendruck. An Open Food Facts gehen nur Suchbegriffe/Barcodes für Lebensmittel, keine Mahlzeitmengen, Fotos, Profile oder Chatverläufe; der Anbieter sieht die Server-IP. Bei Ausfall oder Limit wird kein erfundener Datenbankwert verwendet.

**Datenquellen:** Max Rubner-Institut (2025): *Bundeslebensmittelschlüssel (BLS), Version 4.0 — Deutsche Nährstoffdatenbank*, Karlsruhe, [DOI 10.25826/Data20251217-134202-0](https://doi.org/10.25826/Data20251217-134202-0), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.de). Die eingebundene Ableitung enthält Lebensmittelbezeichnung, Energie, Kohlenhydrate, Protein, Fett und Datenherkunft pro 100 g essbarem Anteil; fehlende Werte, Spuren und Angaben unter der Nachweisgrenze bleiben unbekannt. Reproduzierbare Extraktion: `python tools/extract_bls.py <BLS_4_0_2025_DE.zip>` mit dem [offiziellen Download](https://www.blsdb.de/download). Open Food Facts: [Datenbank unter ODbL 1.0, Inhalte unter Database Contents License](https://openfoodfacts.github.io/openfoodfacts-server/api/); gemeinschaftlich gepflegte Produktwerte sind auf Produkt, Einheit und Vollständigkeit zu prüfen. BLS-Daten und OFF-Cache bleiben getrennt. Es werden keine Produktdaten oder Bilder zu Open Food Facts hochgeladen.

Ernährungseinträge bleiben lokal; eine Übertragung der Tagessummen zu Intervals.icu erfolgt nur nach explizitem Auftrag und Freigabe. Vorlagen und Quellenangaben gehören zu Datenschutzexport, verschlüsseltem Backup und der Löschkategorie Ernährung. Release 1.12.21 migriert das vorhandene SQLCipher-Schema von 1.12.19 und 1.12.20 automatisch beim Start; ein leeres Datenverzeichnis ist für dieses Update nicht erforderlich.

Garmins gemessener Gesamt-, Aktivitäts- und Ruheenergieverbrauch wird für das ausgewählte Tagebuchdatum getrennt von der erfassten Nahrungsaufnahme angezeigt. Datum, Quelle und Aktualität bleiben sichtbar; Werte für heute sind vorläufig, solange Garmins Tagesdatensatz noch ergänzt wird. Fehlende Komponenten bleiben unbekannt und werden nicht zu einem erfundenen Gesamtwert addiert.

### Analysis history

The **Analyse** tab has four sections: Belastung, Leistung, Body and Erholung. Belastung shows one Garmin Connect acute-load chart, with the latest 14 daily readings or twelve calendar weeks (last valid reading per week, including the current week). Garmin training status is imported for the configured sync window; missing or ambiguous device readings stay unknown. Coach context also keeps Garmin's current daily acute and chronic load and the reported acute-to-chronic ratio separate from its four-week aerobic-low, aerobic-high and anaerobic balance values and target ranges. These values retain Garmin provenance and freshness; ambiguous device values and missing fields stay unknown, and they are not combined with Intervals.icu load. Training focus follows over 28 days, then permanently visible HF and power zone diagrams. Focus groups recorded Garmin activity loads by primary Training Effect, rather than deriving categories from zones. Zones sum recorded sport-specific durations across all sports over the same 28 days; missing measurements are not zero. The Woche section and its cumulative Intervals.icu load charts are removed. Leistung separates running and cycling charts for threshold pace, FTP/eFTP and VO2max over twelve calendar weeks. FTP and threshold pace use the last valid weekly measurement; eFTP and VO2max use weekly medians. Every measured week has a point, including unchanged values; missing weeks remain gaps. Only available race predictions and weight appear as supplementary cards, without duplicate health, threshold or load cards. Erholung shows daily sleep, HRV and resting heart rate over the last fourteen days, with an optional twelve-week weekly-average view.

The **Body** section charts measured weight and body-fat history from Intervals.icu Wellness and Garmin Connect, plus cycling power-to-weight from Garmin FTP or Intervals.icu eFTP divided by a measured weight from the preceding seven days. It offers the latest 14 days or twelve rolling weeks; weekly points use the median of dated readings. Source, observation date and sync time remain available with each series, and W/kg values keep FTP/eFTP and weight provenance separate. Unmeasured dates and weeks remain gaps; profile values do not fill missing observations.

Erholung shows the latest fourteen days including today without a period selector, using three aligned charts with independent scales for sleep duration, nightly HRV and resting heart rate. Daily sleep is shown as bars starting at zero, with an average line; hours are formatted as hours and minutes. HRV and resting heart rate show the existing source-specific 42-day personal quartiles only when at least 14 comparable earlier measurements support them; provisional ranges and insufficient or stale baselines remain explicit. Every day retains its original observation; missing days remain gaps, and no missing measurement counts as zero. Each metric uses one source and measurement method: the freshest series wins, with Intervals.icu preferred on equal dates and Garmin used when fresher or unavailable from Intervals.icu. Sources, measurement dates and coverage remain available in tooltips; tap or keyboard-activate a day for details, or open the original-value table. Chart legends show only metric names. Values, dates, sources, coverage, changes and explanatory notes are available in legend and point tooltips; expandable tables retain the original values. Personal reference ranges use a green background band. Recovery bands update with new observations; load and performance charts do not show personal reference bands. Mixed-unit secondary axes have been removed. Personal deviations and positive TSB do not constitute a medical or training clearance.

Charts preserve provider provenance and observation dates. Garmin performance metrics have no Intervals.icu fallback; eFTP uses Intervals.icu estimates and never manually configured FTP. Numeric labels are reduced when they would overlap, without removing data points. Tap a day or open Werte ansehen for complete values. Sleep shows minimum and maximum below the plot and its average beside the dashed line. HRV and resting-heart-rate personal reference bands use earlier 42-day matching measurements, with at least fourteen observations (provisional below 28). These are personal quartiles, not medical or sport-wide targets. Historical availability depends on the sync window. Charts are read-only and never trigger provider requests.

### Aktivitätsdetails

Unter **Geplant → Übersicht** öffnet „Aktivität analysieren“ eine absolvierte
Einheit mit ihren lokal gespeicherten Messreihen und Intervallen. „Detaildaten
laden“ startet ausdrücklich einen Hintergrundjob mit ausschließlich lesenden
Intervals.icu-Abfragen. Der vorherige Detailstand bleibt bei Fehlern erhalten;
normale Synchronisierungen ersetzen ihn nicht. Fehlende Sensorwerte bleiben
als Datenlücken sichtbar. Diagramme und Coach-Kontext zeigen höchstens 2.000
Punkte je Messreihe; gespeichert werden die vollständigen Reihen bis zur
unterstützten Grenze von 172.800 Punkten und 24 MiB je Aktivität.
„Mit dem Coach besprechen“ bereitet einen sichtbaren, bearbeitbaren Entwurf vor.

Equipment and maintenance has its own More section, separate from Profile. Coach-managed local equipment records are authoritative for lifecycle actions, including assignment, maintenance, archive and restore; archived items are kept in collapsed archive groups. Garmin inventory and per-item statistics supply linked usage readings and status context without taking over the local lifecycle. Garmin's `maximumMeters` is a lifetime target used for target/progress display, not additional distance: it is never added to Garmin's usage counter or assigned activity distances. A progress bar appears only when a valid target is known. Failed Garmin reads retain the last successful inventory, while a successful empty inventory clears the mirrored Garmin list.

Calendar cards include a compact interval profile when explicit timed workout steps or current locally cached original samples are available. Width represents time, height represents intensity, and known zones supply colors. Recorded sample gaps remain empty; stale detail profiles are excluded. Absolute targets without known historical zones use neutral colors. No provider requests are triggered by rendering the calendar.

Die Ernährungsnavigation enthält das Tagebuch, gespeicherte Mahlzeiten und die Produktbibliothek. Das Erfassen eines lokalen Produkts erstellt einen bearbeitbaren Coach-Entwurf; es wird nichts automatisch gesendet oder gespeichert. Coach-Anfragen bleiben über die Hauptnavigation verfügbar. Bestätigte Fueling-Datensätze und Coach-Funktionen bleiben lokal; es gibt keinen Fueling-Tab und keine Kalenderverknüpfung.

#### Lokale Produkte und Verpackungsfotos

Die Ernährungsbibliothek speichert bestätigte Einzelprodukte getrennt von
Mahlzeitvorlagen und Tagebucheinträgen. Ein Barcode sucht zuerst in dieser
lokalen Produktbibliothek und verwendet Open Food Facts nur als Fallback. Ein
Treffer aus einer Onlinequelle wird erst nach Prüfung und ausdrücklicher
Bestätigung lokal gespeichert; BLS, Open Food Facts, Verpackungsangabe und
Das Modell kennt die Quellenkennzeichnung `fddb_export`, aber es gibt keinen
FDDB-Importworkflow. Eine Live-FDDB-Anbindung und der Wrapper
[itobey/fddb-exporter](https://github.com/itobey/fddb-exporter) sind derzeit
nicht integriert: Der Wrapper exportiert ein bestehendes FDDB-Tagebuch in
MongoDB/InfluxDB und ist keine produktbezogene Lookup-API. Die Nährwerte werden immer mit
Bezugsmenge und Einheit gespeichert. Gramm und Milliliter werden ohne bekannte
Dichte nicht ineinander umgerechnet.

Ein Foto der Nährwerttabelle wird begrenzt und nur vorübergehend an die
konfigurierte OpenAI Responses-kompatible API übertragen. Die API liefert einen
strukturierten, editierbaren Vorschlag; Bilddaten, Providerantworten und
unbestätigte Werte werden nicht in der Produktbibliothek abgelegt. Name,
Bezugsmenge und erkannte Nährwerte müssen vor dem Speichern geprüft werden.
Die Übergabe eines Kamerafotos durch Android/Chromium ist auf einem realen
Android-Gerät noch nicht verifiziert.
Beim Erfassen eines Verzehrs berechnet der Server die Werte aus dem lokalen
Produkt und speichert einen unveränderlichen Nährwert-Snapshot im Tagebuch;
spätere Produktänderungen ändern keine früheren Einträge.
