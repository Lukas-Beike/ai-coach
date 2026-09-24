# Intervals Coach

Intervals Coach is a private, mobile-first Progressive Web App (PWA) designed for a single athlete. Built on Python's standard-library HTTP server and an encrypted SQLCipher SQLite database, it bridges athlete training history and daily health metrics from Intervals.icu and Garmin Connect with state-of-the-art conversational AI models from OpenAI and Google Gemini.

The application serves as an autonomous, conversational training companion. It understands athlete fatigue, manages a structured workout library, schedules future training sessions, analyzes past workouts, tracks environmental weather constraints, and interprets read-only calendar events—all while keeping sensitive biometric data, credentials, and workout plans strictly local and under the athlete's direct control.

Intervals Coach is intentionally standalone and designed for operation on a trusted local network (LAN) or private VPN (such as WireGuard or Tailscale). It must never be exposed directly to the public internet without a trusted, authenticated reverse proxy.

---

## Core Architecture & Principles

- **Single-Athlete Authority**: Built specifically for one athlete. There are no multi-tenant abstractions, user role hierarchies, or hosted cloud dependencies.
- **Local Source of Truth**: The local SQLCipher database is the authoritative source for future planned units, training goals, workout templates, and athlete feedback. Intervals.icu remains the authoritative record of completed historical activities.
- **Explicit Action Gate**: Conversational coaching operates with strict boundaries. While the Coach can analyze, draft, and propose training changes, mutating local workouts or synchronizing changes to Intervals.icu requires explicit athlete confirmation in the dialogue.
- **Untrusted External Content**: Data received from Intervals.icu, Garmin Connect, Open-Meteo, and external iCalendar feeds is strictly treated as untrusted data, never as system instructions.
- **Zero Cloud Telemetry**: Biometric data, activity recordings, API keys, database keys, and athlete conversations never leave the host server, except when sending sanitized coaching prompts to the user's selected AI provider.
- **Standard-Library Foundation**: The backend runs on Python's native `http.server` without heavyweight web frameworks. Application logic is modularized under `backend/`, keeping `server.py` strictly as a composition root.

---

## Fresh Installation Contract

Intervals Coach adheres to a clean-slate installation and maintenance model:
- **Clean Storage Mount**: Start the application with an empty `/data` directory and a fresh browser profile.
- **Direct Schema Initialization**: The application initializes the current SQLCipher schema directly upon first startup.
- **No Migration Shims**: There are no automatic schema migrations, legacy database converters, or backward-compatibility upgrade paths. Deprecated code and schemas are removed rather than shimmed.
- **Safe State Recovery**: Same-build process restarts, provider resynchronization, and current-schema backup restoration remain fully supported.
- **Isolated State**: The application will not overwrite, migrate, or delete databases from prior major installations located outside its designated storage directory.

---

## Features

### AI Coach & Conversational Intelligence
- **Natural Language Coaching**: Conversational coaching without rigid trigger words, supporting natural phrasing, corrections, follow-up questions, and pronoun resolution across turns.
- **Dual AI Provider Support**: Native integration with the OpenAI Responses API (GPT-5.6-luna, GPT-5.6-sol, GPT-5.6-terra) and Google Gemini (Gemini 3.8 Flash) with real-time SSE token streaming.
- **Durable Turn Queueing**: Every chat request is persisted in a durable SQLite background queue before processing, enabling seamless answer recovery across network drops or browser reloads.
- **Permanent Fact Memorization**: Conversational profile updates that save athlete preferences, equipment notes, and constraints to the durable profile only upon explicit confirmation.
- **Bounded Context Projection**: Dynamic context assembly projecting the 5 newest activities per sport, compact planned units, target competitions, and wellness trends within strict token budgets.
- **Targeted Clarification Protocol**: Ambiguous coaching prompts generate a single, concrete clarification question stored locally across reloads and model switches until answered.
- **Atomic Training Changesets**: Plan updates, session moves, and workout creations use transactional revision tracking and object hashes to prevent race conditions.
- **Contextual Quick Actions**: Dynamic start cards presenting context-relevant prompts such as the Morning Check-in or recent workout analysis without permanent UI clutter.
- **Intelligent Duplicate Resolution**: Automated inspection of dual-recorded workouts (e.g., Wahoo and Garmin cycling files) that designates canonical recordings while protecting against accidental cloud deletions.
- **Structured Error Recovery**: Robust recovery from provider rate limits and transient network errors with transparent diagnostic reporting and safe rollback of incomplete actions.

### Training Calendar & Workout Planning
- **Collapsible Weekly Calendar**: Mobile-optimized calendar displaying complete training weeks with collapsible volume summaries, planned workouts, and completed sessions.
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
- **Daily Wellness Summaries**: Calendar-integrated daily summaries tracking total steps, floors climbed, active calories, resting heart rate, and overnight HRV.
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
- **Actionable Calendar Description Tags**: Selective tag parsing recognizing `[NO_TRAINING]`, `[NO_INTENSITY]`, and `[SHORT_ONLY]` within event descriptions to steer adaptive planning.
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
- **Accessible Keyboard Shortcuts**: Desktop navigation supporting Enter-to-send, Shift+Enter for line breaks, Esc for modal dismissal, and ARIA live announcements.

### Privacy, Security & Data Management
- **SQLCipher AES-256 Encryption**: Complete encryption of all athlete data, metrics, tokens, chat history, and attachments at rest using `APP_PASSWORD`.
- **Strict Session Security**: High-security session cookies hardened with `HttpOnly`, `SameSite=Strict`, and optional `Secure` flags.
- **Zero Third-Party Trackers**: Self-hosted architecture containing zero tracking scripts, third-party analytics, external CDNs, or telemetry reporting.
- **Comprehensive Privacy Export**: Single-click export producing a complete, unencrypted JSON archive of all profile records, workouts, metrics, and chat history.
- **Confirmed Local Data Purge**: Irreversible deletion of all local athlete data guarded by an explicit typed confirmation phrase (`LOKALE DATEN LÖSCHEN`).
- **Zero-Downtime Maintenance Mode**: Process-level maintenance gate that prevents concurrent writes and ensures transaction safety during database restoration.
- **Pre-Restore Rollback Copies**: Automated creation of a safety copy of the existing database before executing any database restore or replacement.
- **Redacted Operational Logging**: Structured server logs that correlate technical operation IDs while stripping authentication headers, tokens, and athlete text.
- **Temporary Diagnostic Capture**: Time-limited (1-hour) technical diagnostic logger recording API response shapes and error traces without capturing athlete content.

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
|  |   - backend.http_api  : Request routing, JSON/multipart parsing, session cookies     |  |
|  |   - backend.coach     : AI turn queue, context builder, 37 tool dispatchers, SSE    |  |
|  |   - backend.sync      : Background scheduler, Intervals.icu, Garmin, Weather, ICS   |  |
|  |   - backend.activities: Activity matching, duplicate detection, feedback tracking   |  |
|  |   - backend.planning  : Workout units, templates, atomic changesets, revision locks |  |
|  |   - backend.weather   : Open-Meteo client, ICON-D2/ECMWF forecast models, windows   |  |
|  |   - backend.backup    : Export, validation, pre-restore snapshots, maintenance gate |  |
|  |   - backend.db        : Repositories, transaction locks, SQLCipher connection pool   |  |
|  +-------------------------------------------+-----------------------------------------+  |
|                                              |                                            |
|                                              v                                            |
|  +-------------------------------------------------------------------------------------+  |
|  | Persistent Storage Mount (/data)                                                    |  |
|  |   - coach.db (SQLCipher AES-256 Encrypted Database)                                 |  |
|  |   - garmin_tokens (Encrypted Garmin OAuth Session Store)                            |  |
|  |   - backups/ (Local Database Snapshots and Pre-Restore Copies)                      |  |
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

---

## Configuration & Environment Variables

All configuration is loaded from container environment variables or a local `.env` file mounted in `/data/.env` or the application root.

### Environment Variable Reference

| Variable | Default Value | Required? | Description |
| :--- | :--- | :--- | :--- |
| `APP_PASSWORD` | *None* | **Yes** | Master password (minimum 12 characters). Secures web UI authentication and acts as the encryption key for the SQLCipher database. |
| `OPENAI_API_KEY` | *None* | **Conditional** | API key for OpenAI. Required if using OpenAI as the AI provider. |
| `GEMINI_API_KEY` | *None* | **Conditional** | API key for Google Gemini. Required if using Gemini as the AI provider. |
| `AI_PROVIDER` | `openai` | No | Active AI provider (`openai` or `gemini`). Determines which model powers Coach Chat. |
| `OPENAI_MODEL` | `gpt-5.6-luna` | No | OpenAI model deployment name. Supported options: `gpt-5.6-luna`, `gpt-5.6-sol`, `gpt-5.6-terra`. |
| `GEMINI_MODEL` | `gemini-3.8-flash` | No | Google Gemini model name. Default: `gemini-3.8-flash`. |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | No | Custom base URL for OpenAI-compatible APIs (e.g., Azure OpenAI / Microsoft Foundry endpoints ending in `/openai/v1`). |
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
- **Startup Sync**: On container launch, the backend initializes the database, spins up background worker threads, and triggers an initial synchronization across all configured providers.
- **Hourly Provider Cycle**: Checks for updated calendar events, refreshed weather forecasts, and new Intervals.icu completed activities.
- **Daily Synchronization Loop**: Runs daily at 03:00 UTC (or configured local time) to pull comprehensive activity files, update rolling fitness metrics, and schedule the day's training agenda.
- **On-Demand Refreshes**: Triggered immediately whenever the athlete clicks **Synchronisieren** in the More tab or when requested by the Coach.

### Priority Queue & Durable Job Processing
Every conversational request, activity sync, and background task is enqueued in the SQLite `background_jobs` table.
- **Streaming Handshake**: When an HTTP turn starts, Server-Sent Events (SSE) immediately return the durable job UUID.
- **Decoupled Execution**: If the athlete locks their phone or loses cellular connection, the server continues execution uninterrupted.
- **Recovery on Reconnect**: Upon reconnection or app reload, the PWA polls the durable job result using its UUID, rendering the completed answer without re-executing actions.

### Provider Data Handling
- **Intervals.icu Activity Pull**: Ingests new completed workouts with full telemetry (duration, distance, TSS, HR zones, power curves). Large imports are safely fetched in paginated windows.
- **Garmin Sleep Gate & Body Battery**: Morning synchronization deliberately halts until Garmin's sleep window completes. Body Battery tracking captures the final pre-sleep value and the wake-up value within 60 minutes of rising, retrying up to 3 times with 15-minute intervals.
- **Open-Meteo Weather**: Forecasts are fetched for the athlete's coordinates and cached for 3 hours. Short-range predictions use Germany's DWD ICON-D2 model, transitioning to ECMWF IFS HRES for 14-day projections.
- **iCalendar (ICS) Life Constraints**: The external feed is parsed up to 8 weeks out. Events containing `[NO_TRAINING]`, `[NO_INTENSITY]`, or `[SHORT_ONLY]` in their description are tagged as training constraints.

---

## Coach Intelligence & Execution Boundaries

### Prompt Projection & Token Budgeting
To optimize API token consumption and response latency, Intervals Coach uses a strictly bounded context projection rather than dumping entire databases into prompts:
- **Activity Projection**: Bounded to the 5 most recent completed activities per normalized sport type.
- **Planning Projection**: Bounded to at most 50 future planned units.
- **Metric Sanitization**: Raw JSON payloads from providers are stripped down to core athletic parameters (FTP, TSS, RPE, Heart Rate, Power Zones, Duration, Distance).
- **Dialogue Pruning**: Multi-turn dialogue history is maintained locally; remote conversation chains are pruned between distinct command sessions.

### Tool Execution & Reversible Changesets
The Coach interacts with the athlete's data via 37 structured tools covering plan inspection, template management, profile editing, and provider synchronization:
- **Transaction Locks**: All database updates share SQLite transaction locks to guarantee that conversational actions and background syncs never collide.
- **Revision Control**: Plan modifications require passing the current planning revision and object hash, preventing overwrite collisions if edits occur concurrently.
- **Receipt Verification**: Tool invocations produce structured receipts in the chat UI, explicitly delineating saved local modifications, queued sync jobs, and rejected parameters.

### Multimodal Capabilities
- **Voice Transcription**: Push-to-talk voice recording captures audio directly in the PWA. Audio is streamed to `/audio/transcriptions` (OpenAI Whisper or Gemini) in memory and inserted into the message box. Raw audio is never persisted.
- **File Attachments**: Athletes can attach up to 4 GPX, FIT, or image files (max 5 MB each) per turn. GPX tracks are summarized locally (distance, elevation, GPS bounds); FIT files are parsed for power and cardiac data; images are sent for vision-based AI coaching.

---

## Workout Export & Syntax Specification

Endurance workouts synchronized to Intervals.icu must comply with the native workout builder syntax. The application validates workout text locally before attempting remote synchronization:

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
All persistent application state is stored in `/data/coach.db` encrypted with AES-256 via SQLCipher. The database key is derived from `APP_PASSWORD`. The application will refuse to start without SQLCipher libraries present.

### Maintenance Mode & Database Restoration
When a database restore is initiated:
1. The application enters an exclusive maintenance mode, rejecting new incoming API mutations with an HTTP 503 maintenance notice.
2. Active background sync jobs and Coach turns are allowed to finish gracefully.
3. An automated pre-restore safety copy of the active database is saved in `/data/backups/pre_restore_backup.db`.
4. The replacement database is validated for schema version integrity, table structures, and foreign-key constraints.
5. If valid, the new database is swapped into place and the maintenance gate is lifted; if invalid, the original database is preserved without data loss.

### Privacy Export & Data Purge
- **Full Privacy Export**: Download a single comprehensive JSON archive containing all stored profile fields, workouts, check-ins, activity notes, and chat history.
- **Local Data Purge**: Completely wipes all local athlete records from the database. To prevent accidental loss, the action requires entering the exact confirmation phrase `LOKALE DATEN LÖSCHEN`. External accounts (Intervals.icu and Garmin) remain untouched.

### Operational Logging & Diagnostics
- **Sanitized Logs**: Standard container logs contain only operational timestamps, correlation IDs, status codes, and anonymized error classifications. API tokens, passwords, and athlete metrics are never logged.
- **1-Hour Diagnostic Capture**: When troubleshooting complex provider schema changes, athletes can activate a temporary 1-hour diagnostic capture in **Betrieb & Diagnose**. This records payload schemas and structural metadata without logging athlete content.

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

#### Native Python Unit Tests
Run standard unit tests with temporary in-memory fixtures (mocking external providers):
```powershell
python -m unittest discover -s tests -v
python -m py_compile server.py tests/test_server.py
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
npm install
npm run test:e2e
```
Configured viewports in `playwright.config.cjs`:
- `mobile-small`: 320x568 (Compact mobile)
- `mobile`: 390x844 (Standard mobile)
- `tablet`: 768x1024 (Tablet portrait)
- `tablet-landscape`: 844x390 (Mobile/tablet landscape)
- `desktop`: 1440x1000 (Desktop workstation)

### Continuous Integration & Codex Review Gate
- **Conventional Commits**: All commit messages and pull request titles must follow the Conventional Commits specification (e.g., `feat(coach): add Gemini 3.8 Flash support` or `fix(sync): resolve Garmin sleep retry backoff`).
- **Codex PR Review Gate**: Pull requests targeting `develop` or `main` require a subscription-backed Codex review gate. Request review by commenting `@codex review` on the pull request. All review findings must be resolved before merging.
- **Automated Daily Releases**: At 03:00 UTC, an automated workflow inspects `develop`. If new commits exist, it creates a version-bump PR, integrates it, synchronizes with `main`, and publishes a cryptographically signed GitHub release and container image.

---

## Security Boundaries & Medical Disclaimer

Intervals Coach is a personal athletic planning assistant, not a certified medical device. Training recommendations, adaptive replanning suggestions, and performance analytics are generated by artificial intelligence models and heuristic algorithms. 

Always listen to your body. Do not follow workout intensity or duration recommendations that cause sharp pain, dizziness, or symptoms of overtraining. Consult a certified medical professional or sports physician before undertaking high-intensity endurance training or if recovering from illness or injury.

---

## License

Intervals Coach is open-source software licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**. See [`LICENSE`](LICENSE) for the complete license terms.
