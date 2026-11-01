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
- **Untrusted External Content**: Data received from Intervals.icu, Garmin Connect, Open-Meteo, the DWD, and external iCalendar feeds is strictly treated as untrusted data, never as system instructions.
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

Releases preserve the athlete's existing encrypted database. The oldest
supported schema is version 16, written by release 1.13.32; startup and restore
accept it in place, retaining existing records and SQLCipher encryption. Older,
unknown or newer schemas are rejected without deleting or partially changing
the data: upgrade an older database or backup with release 1.13.32 first. Keep
the existing `/data` bind mount and `APP_PASSWORD` when recreating the
container, and do not replace or reset the data directory to resolve a
rejected schema. A fresh database is only required when the athlete explicitly
chooses to start over. Future schema changes add explicit, versioned and
transactional migrations from version 16 with upgrade regression tests.
The current schema is version 19. Version 10 adds canonical activity detail
(streams, laps and zone times), version 11 the food-database mirror, version 12
stores the Garmin collection as one keyed row per element instead of one large
`garmin_snapshot` value, version 13 adds the maximum speed of each lap, and
version 14 lets Yazio foods into the food-database mirror and saved products,
and version 15 adds canonical sleep periods, zone configurations, provider
statuses, gear with its activity links, the session each activity note was
written for, and the survivor a deleted merged session keeps, version 16
names the start and planned duration of local planning records (planned units,
workout-library entries, competitions, staged Coach plans and adaptive previews)
`starts_at_local` and `planned_duration_s` instead of the Intervals.icu fields
`start_date_local` and `moving_time`, and version 17 stores the Intervals.icu
cycling power curve (best power per duration with its day and activity, plus the
status and window of the latest fetch) as canonical rows. A version 16 to 18 database or backup is
upgraded to it in place within one transaction, and a failed upgrade leaves it
unchanged. The version 16 schema uses the neutral start and duration fields;
the change history is not rewritten, so earlier changes stay undoable, and recorded Intervals.icu sync
baselines still match. A sync confirmation that was prepared before the
upgrade, or a confirmed sync job still queued during it, no longer matches the
renamed records: it reports them as changed since the preview and writes
nothing, so prepare and confirm that sync again. The version 17 step keeps the
power curve of the newest stored snapshot as a raw record; the analysis power
profile shows it again once the canonical backfill has projected it.
Version 18 records the session-RPE rating time. Version 19 names local planned
load and intensity `planned_load` and `planned_intensity` and the frozen target
FTP basis `ftp`; the Intervals.icu adapter retains its provider wire names.

Schema version 9 stores sports in the canonical vocabulary (`sport` such as `ride`, `run` or `strength`, plus `environment` and, for text without a canonical sport, a lossless `sport_detail`) for equipment, competitions, the workout library and planned units. The HTTP API and coach tools keep accepting the previous Intervals.icu-style tokens (for example `VirtualRide` becomes `ride` + `virtual`), and Intervals.icu payloads are unchanged because only the Intervals.icu adapter maps canonical values back to its activity types. Likewise only that adapter maps `starts_at_local` and `planned_duration_s` to the Intervals.icu event and workout fields, and Coach tools take `starts_at_local` and `planned_duration_s` as well.

---

## Features

### AI Coach & Conversational Intelligence
- **Natural Language Coaching**: Conversational coaching without rigid trigger words, supporting natural phrasing, corrections, follow-up questions, and pronoun resolution across turns.
- **Responses API Support**: Uses OpenAI Responses-compatible APIs with real-time SSE token streaming. Chat Completions and provider fallback are unsupported.
- **Durable Turn Queueing**: Every chat request is persisted in a durable SQLite background queue before processing, enabling seamless answer recovery across network drops or browser reloads.
- **Permanent Fact Memorization**: Conversational profile updates save athlete preferences, equipment notes, and constraints to the durable profile when the athlete explicitly asks in Coach Chat; no separate UI confirmation is needed.
- **Sport-Specific Training Preferences**: The profile keeps general training preferences plus separate preferences for running, cycling, swimming, strength training, and mobility; the Coach saves sport-specific wishes in the matching field.
- **Training Model**: The profile selects the intensity distribution the Coach plans with: pyramidal (default), polarized, threshold-focused or sweet spot. The Coach changes it only on the athlete's explicit request.
- **Server-Side Write Gate**: Every Coach write tool call is checked by impact, not by wording. In a turn started by the athlete's own message, reversible local edits run directly and appear under the answer as "Geändert: …" with undo where fully tracked. Deleting or archiving records, replacing or committing a whole plan, and changing more than 7 records in one turn additionally need a small model classifier to confirm that the athlete explicitly asked for exactly that in the same data area (a requested deletion of a meal never confirms deleting a race); otherwise, or when the classifier fails, the Coach asks one clarification question and nothing is changed. Undoing a creation deletes the record, so the Coach offers it as a confirmation card instead of running it directly. Intervals.icu writes need the athlete's message (or a short "ja" to the Coach's sync offer) to name the sync; the classifier can never authorize them. Adaptive replans keep their preview approval: only the athlete's very next message after the published preview can apply it, and the classifier must confirm that this message accepts the previewed change as proposed (a bare "danke", an unrelated message, or a rejection that asks for a different change instead does not); an illness-pause sync to Intervals.icu additionally needs the named sync and is built from the stored preview. A turn makes at most 25 changes.
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
- **Daily Athlete Check-ins**: Stored check-ins track morning readiness, sleep quality, muscle soreness, perceived stress, and free-form athlete notes. They are recorded through the Coach chat and feed readiness, planning, and calendar day notices. Saved check-ins stay in the local data and in exports.
- **Post-Activity Feedback**: Dedicated local feedback logging for completed workouts, capturing perceived exertion (RPE), equipment details, and workout execution notes. Feedback belongs to the canonical session: the Intervals.icu and Garmin copies of one confirmed session show and edit the same feedback, and its session RPE counts once. Older feedback saved on different copies stays stored; the newest is shown and the others are listed as `conflicting_feedback`. Clearing removes the session's feedback entirely. An id that matches activities of several providers stays on its own, and deleting a provider copy keeps the feedback. Local session RPE is never mixed with the provider's RPE. The RPE is chosen from 0 to 10 in half steps, with the CR-10 anchors (Ruhe, Leicht, Moderat, Schwer, Maximal and others) on their steps; the time of each new or changed rating is stored, earlier ratings keep an unknown rating time. **Session-RPE load** (method `session-rpe-load` v1, evidence card `docs/performance-methods/m1-session-rpe-load.md`) is elapsed minutes × session RPE in arbitrary units (AU): the activity details show it per session (for example "403 AU · RPE 6,5 (Athletenfeedback) × 62 min"), Belastung shows it per day or week with the count of rated sessions, and the Coach reads it in the training report. Without a local rating the Intervals.icu RPE of the same session is used and labelled; disagreeing provider ratings, a missing rating or a session with only a moving time give no value. AU are never added to Intervals.icu or Garmin load. Saving or removing feedback in the activity details shows a receipt with "Rückgängig"; undo restores every stored row of the session as it was, full-length notes and hidden older entries included. Feedback keeps the provider copy it was written for, so a later split of wrongly merged sessions stays lossless; the app has no split action yet.
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
- **Compact Snapshot Storage**: Each sync ingests its full payload into the canonical tables first. Once the tables serve reads (after the first completed backfill), the stored Intervals.icu snapshot omits `recent_activities` and `raw_provider_data.activities` and carries `"canonical_sections": "tables"`; wellness, athlete, calendar and sync-status sections stay. The next incremental or historical sync rebuilds its merge base from the stored activity rows. Existing snapshot rows are never rewritten, and until the first backfill completes snapshots are stored in full.
- **Initial Template Import**: One-time read-only import of existing remote workout templates into a dedicated, private 'Intervals Coach' folder upon initial setup.
- **Explicit Plan Synchronization**: Unidirectional push transferring locally approved planned units to the Intervals.icu calendar with stable upsert identifiers.
- **Automatic Performance Refresh**: Immediate background refresh of current fitness (CTL), fatigue (ATL), and form (TSB) following every successful manual activity synchronization and the first automatic one of each day; later hourly short-window refreshes already update the athlete, power curve and recent wellness.
- **Unidirectional Write Boundary**: Strict boundary preventing standard read syncs from altering, overwriting, or deleting locally maintained planned workouts.
- **Automatic Garmin to Intervals.icu metrics**: Automatic export is off by default. The athlete enables Garmin-to-Intervals.icu synchronization once in the Anbindungen section (More → Anbindungen), below the Garmin login and only while Garmin is connected, confirming the named source and target; this consent is persisted in the encrypted database and can be revoked in the same place. After a successful current Garmin sync, new provider-reported Garmin measurements from the last 90 days are sent only while consent is enabled and Intervals.icu is configured. This covers supported body values (weight, body fat, resting heart rate, dated wellness records) and sport settings (cycling FTP, running threshold pace, and sport-specific threshold/max heart rate). Existing differing target values without an accepted baseline are never overwritten automatically. Matching values establish a baseline without a remote write; missing values may be populated. Later transfers compare live Intervals.icu values with the provider-normalized last accepted value stored per remote record and field, including each dated wellness record: an intervening change pauses that field, while other fields continue. Matching values and already sent values are not written again. Heart-rate zones always remain unchanged (`recalcHrZones=false`); AI estimates, derived values, local profile entries and other providers are excluded. Fixture, failed, partial and historical Garmin runs do not trigger exports. The sync status reports sent values, conflicts and failures; export failures preserve the successful local Garmin import and retry on the next successful current sync. A conflict remains paused until the target matches its last accepted value or an explicitly confirmed manual API export resolves it. Baselines survive restarts and backup/restore in the existing encrypted database; no schema change is needed. The existing session/CSRF-protected metric-export preview/execute API remains available for explicit manual exports, including resolving conflicts; its confirmation and live-value checks are unchanged. The Coach has no metric export tool.
- **Illness Pause Synchronization**: Explicit synchronization of confirmed illness pauses to Intervals.icu as calendar note entries only upon dedicated athlete request.
- **Bidirectional Competition Sync**: Coordinated synchronization aligning competition dates, priorities (A/B/C), target sports, and goal times between local and remote calendars.

### Garmin Connect Integration & Health Metrics
- **Direct Read-Only Health Sync**: Independent synchronization of Garmin Connect wellness metrics, activity recordings, and physiological measurements.
- **Dedicated Sleep Gating**: Intelligent morning check-in gate that delays morning coaching until the current day's sleep analysis is processed and finalized by Garmin.
- **Overnight Body Battery Tracking**: Targeted extraction of resting stress metrics capturing the final level before sleep and the initial waking level within one hour of rising.
- **Bounded Sleep Retry Engine**: Three-tier exponential retry schedule (15-minute intervals, max 3 attempts) handling delayed Garmin cloud sleep processing.
- **Garmin-Specific Metric Labeling**: Clear source labeling distinguishing Garmin-calculated FTP, running threshold power, threshold HR, threshold pace, and VO2 max from Intervals.icu metrics.
- **Daily Wellness Summaries**: Calendar-integrated daily summaries tracking total steps, floors climbed, active calories, resting heart rate, and overnight HRV. Garmin's dated daily energy expenditure is also shown alongside the nutrition diary, with current-day values marked provisional. For the running day, a separately labelled derived projection of the full-day total (resting calories of the last complete day plus active calories so far) is added.
- **Rolling Health Averages**: Automated calculation of 7-day rolling health baselines displayed alongside acute readings on the performance dashboard.
- **Transparent Metric Fallback**: Resilient metric aggregation preserving Intervals.icu values as labeled fallbacks when Garmin biometric readings are absent.
- **Garmin performance selection**: Current FTP and running thresholds come from Garmin Connect's latest biometric readings, which can differ from manually configured watch sport profiles. Scaled threshold speed is normalized to m/s before canonical storage and displayed as min/km. FTP calendar dates accept Garmin's ISO date or datetime format and retain its calendar day. An undated latest cycling FTP uses the sync day as its observation day; undated FTP history is not invented. Mapper updates re-project stored provider records through the existing background backfill. The general maximum-heart-rate value prefers Garmin over Intervals.icu, then shows the higher of the available running and cycling values from that provider; threshold heart rate is a separate metric.

### Weather Intelligence & Outdoor Scheduling
- **Open-Meteo Integration**: Server-side cached 14-day local weather forecasts powered by the non-commercial Open-Meteo meteorological API.
- **Dual-Model Forecast Engine**: Intelligent forecast resolution using high-precision DWD ICON-D2 for short-range predictions and ECMWF IFS HRES for long-range outlooks.
- **Air Quality & Pollen**: Open-Meteo/CAMS European AQI, particulate matter, ozone, nitrogen dioxide, and UV index for about 5 days. For German locations the official DWD pollen-flight hazard index (0–3, today plus two days) is used for the automatically resolved pollen region; elsewhere Open-Meteo/CAMS pollen concentrations are the fallback.
- **Compact Calendar Weather**: Each calendar day shows only a weather symbol with its temperature range beside the date, so the sessions and their load/interval charts stay in the foreground; small flags are added only when notable (rain from 50 %, UV from 6, European AQI from 60, any DWD pollen level), and all weather and air figures appear in the symbol's tooltip.
- **Weather Window Recommendations**: Automated calculation of optimal outdoor training windows over the next 5 days based on temperature, precipitation, wind speeds, and air quality.
- **Workday Schedule Awareness**: Outdoor suggestions tailored around athlete working hours (06:00-15:30 Monday-Thursday, until 14:00 Friday, with a 12:00-13:00 lunch window).
- **Adaptive Weather Alerts**: Proactive notifications and planned calendar warnings when impending heavy rain, extreme heat, or high winds impact scheduled outdoor sessions.
- **Efficient Server Caching**: 3-hour server-side forecast caching with automatic on-demand cache overrides accessible from the More tab.

### External Calendars & Schedule Constraints
- **Read-Only iCalendar (ICS) Sync**: Secure polling of private external iCalendar feeds (Google Calendar, Apple iCloud, Microsoft Outlook) without write permissions.
- **Rolling 8-Week Event Horizon**: Bounded calendar expansion mapping external life events across an 8-week (56-day) forward-looking window.
- **RFC 5545 Recurrence Engine**: Comprehensive expansion of standard recurring rules (daily, weekly, monthly, yearly) and Google Calendar recurrence exceptions capped at 1,000 instances. A date-only `UNTIL` includes recurrences on that day in the event's own time zone, and feeds whose recurrence expansion is too expensive are rejected.
- **Bounded Calendar Processing**: Feeds are limited to 5 MB and 10,000 parsed event components; folded lines, RDATE deduplication and recurrence-exception lookup are processed linearly. Instance records are generated incrementally and feeds exceeding 1,000 unique events in the sync window are rejected. Connected calendar HTTP transfers have a 30-second total deadline.
- **Calendar Training Constraints**: `[NO_TRAINING]`, `[NO_INTENSITY]`, and `[SHORT_ONLY]` are recognized in event titles and descriptions. `[NO_TRAINING]` and `[NO_INTENSITY]` are enforced against planned-workout changes on the affected local calendar day: training is blocked for the former, the latter requires an explicitly easy workout, and `[SHORT_ONLY]` blocks workouts longer than 60 minutes.
- **Visual Schedule Conflict Markers**: Distinctive visual indicators on the planned calendar alerting the athlete to busy days and potential scheduling conflicts.
- **Adaptive Session Replanning**: Heuristic session adjustments that suggest shorter durations or lower-intensity replacements for scheduled workouts on congested days.

### Performance Analytics, Metrics & Trends
- **30-Day Historical Trends**: Long-term tracking and trend lines for FTP, running threshold pace, VO2 max, resting heart rate, heart rate variability (HRV), and body weight.
- **Impulse-Response Fitness Modeling**: Real-time tracking of Chronic Training Load (Fitness), Acute Training Load (Fatigue), and Training Stress Balance (Form) from Intervals.icu wellness observations. The Coach context shows a ramp rate that Intervals Coach derives from the CTL change over exactly seven days, labelled as calculated; it can differ from the Intervals.icu value and is unknown when a day is missing.
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
- **Immutable Static Asset Caching**: Versioned static asset serving with one-year immutable cache headers. A new service worker takes over at once and removes the old caches; the open app then reloads once without a prompt, but only while no message is typed, no attachment is staged, no Coach answer is running or queued, no unsaved profile change is open, no setting or credential is being entered or saved and no load or restore is running. Otherwise the reload waits until that has ended or the app is hidden.
- **Resilient Offline App Shell**: Pre-cached application shell allowing view navigation and inspection of previously loaded training data during network drops. Changes are not queued while offline: saving shows a connection message and nothing is sent later.
- **Instant Start from Device Data**: The last loaded training state is stored on this device and shown immediately at every start, before the session check and fresh data complete; each area is shown and stored on the device as soon as its own data arrives, without waiting for slower areas; an area that fails to load keeps its previously stored data, also after an app update as long as that data still has the current shape. Nutrition views likewise show their last loaded data while they refresh. The Wettkämpfe segment uses the saved local competition state: date, sport, distance and personal A/B/C priority are visible in collapsed event summaries; saved event details expand individually and past events sit in a closed archive. Weekly preparation evidence and load simulations are not shown in this overview. Competition editing remains available through the Coach, with receipts/undo and explicitly requested synchronization. The latest 20 Coach messages are stored on the device as soon as they are shown, so a start shows the current conversation even when the rest of the stored state is older; earlier messages load when scrolling up. While the Coach shows these stored messages the chat stays at the newest one, unless the athlete has already scrolled the chat, and a "Nachrichten werden synchronisiert…" note replaces the jump-to-latest button until the fresh messages have loaded or the load has failed. If the network is slow, the cached app page starts after 2.5 seconds, and an offline start keeps the stored data and checks the session again every 15 seconds or as soon as the network returns. After an app update the start shows an "Update wird verarbeitet…" loading screen until the fresh start data arrives; if the server cannot be reached, the previous data is shown instead. Logout, an expired session and a privacy deletion remove this device data.
- **Auto-Reconnecting SSE Streaming**: Server-Sent Events stream with exponential backoff (capping at 30 seconds) ensuring smooth recovery after connection drops.
- **Touch-Friendly Collapsible Views**: Ergonomic mobile interface featuring collapsible profile headers, compact calendar cards, and thumb-friendly bottom navigation.
- **Light and Dark Appearance**: Choose the system setting, light mode, or dark mode under More → Appearance; the choice is stored on this device.
- **Chat Controls**: Keep the composer available while reading older messages, jump to the latest reply, stop a response, copy messages, and edit a prior user prompt as a new draft.
- **Accessible Keyboard Shortcuts**: Desktop navigation supporting Enter-to-send, Shift+Enter for line breaks, Esc for modal dismissal, and ARIA live announcements. On touch devices, Enter inserts a line break; the send button or Ctrl/Cmd+Enter sends.

### Privacy, Security & Data Management
- **SQLCipher AES-256 Encryption**: Complete encryption of all athlete data, metrics, database-stored provider credentials (API keys and secrets entered in the UI), provider tokens (Wahoo and Garmin), chat history, and attachments at rest using `APP_PASSWORD`. Only a legacy Garmin token file, if one still exists, is plaintext and not covered; see Garmin setup.
- **Database Key Placement**: Keep `APP_PASSWORD` in the container environment or the project-root `.env`. If it is found in `DATA_DIR/.env`, beside the encrypted database, startup logs a warning (never the value), because a copy of the data directory would then include its key.
- **Strict Session Security**: High-security session cookies hardened with `HttpOnly`, `SameSite=Strict`, and optional `Secure` flags.
- **Bounded HTTP Input**: At most 32 active handlers, with separate 20-second absolute limits for request headers and bodies. Login admission is checked before reading its body; these input limits do not shorten Coach responses or SSE streams.
- **Zero Third-Party Trackers**: Self-hosted architecture containing zero tracking scripts, third-party analytics, external CDNs, or telemetry reporting.
- **Comprehensive Privacy Export**: Single-click export producing a complete, unencrypted JSON archive of all profile records, workouts, metrics, and chat history.
- **Confirmed Local Data Purge**: Irreversible deletion of all local athlete data, including stored provider credentials and Garmin tokens, guarded by an explicit typed confirmation phrase (`LOKALE DATEN LÖSCHEN`). The Garmin account and Intervals.icu/Wahoo accounts themselves are not changed.
- **Zero-Downtime Maintenance Mode**: Process-level maintenance gate that prevents concurrent writes and ensures transaction safety during database restoration.
- **Pre-Restore Rollback Copies**: Automated creation of a safety copy of the existing database before executing any database restore or replacement.
- **Redacted Operational Logging**: Structured server logs that correlate technical operation IDs while stripping authentication headers, tokens, and athlete text.
- **Always-on Technical Diagnostics**: Bounded diagnostic logger (up to 10,000 entries, 16 MiB total, 1 MiB per entry) recording sanitized Coach requests and responses, provider error details, tool activity, and error traces. Credentials, keys, tokens, and session data are removed before storage. New entries are written to the database in one batch at most 30 seconds after they are captured, as background work, and on shutdown, including `docker stop`; a crash or forced kill can lose the entries of the last 30 seconds.

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
|  |   - garmin_tokens (legacy plaintext token file, imported once, left in place)       |  |
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
`analysis.js`, `activity-details.js`, `activity-analysis.js`, `nutrition.js`,
`forms.js`, `components.js`, and `appearance.js`. The service worker owns the
offline asset cache.

---

## Configuration & Environment Variables

All configuration is loaded from container environment variables or a local `.env` file mounted in `/data/.env` or the application root.

### Environment Variable Reference

Coach settings offer GPT-6 Luna (default), GPT-6 Sol, GPT-6.1 Sol and GPT-6 Astra, plus the configured deployment on the official OpenAI endpoint. Compatible endpoints offer only their configured deployment and omit the service-tier parameter. Thinking defaults to Medium. Speed defaults to Fast for these models; Standard is always available, and Ultrafast is available for GPT-6.1 Sol and GPT-6 Astra. Fast/Ultrafast have higher API prices. Unknown configured deployments omit the service-tier parameter. Choices are saved locally; unsupported speed choices fall back to Fast (or Standard for unknown deployments). Account availability depends on the API provider. See [Fast mode](https://developers.openai.com/api/docs/guides/fast-mode) and [Ultrafast mode](https://developers.openai.com/api/docs/guides/ultrafast-mode).

| Variable | Default Value | Required? | Description |
| :--- | :--- | :--- | :--- |
| `APP_PASSWORD` | *None* | **Yes** | Master password (minimum 12 characters). Secures web UI authentication and acts as the encryption key for the SQLCipher database. |
| `OPENAI_API_KEY` | *None* | **Yes** | Server-side API key for the OpenAI Responses API or compatible endpoint. Can also be set in **Mehr > Anbindungen > Zugangsdaten**. |
| `OPENAI_MODEL` | `gpt-6-luna` | No | Default OpenAI model deployment; selectable in Coach settings. |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | No | Optional Responses-compatible API base URL. HTTPS is required; HTTP is allowed only for loopback addresses. |
| `INTERVALS_API_KEY` | *None* | **Yes** | Personal API key obtained from Intervals.icu account settings. |
| `INTERVALS_ATHLETE_ID` | `0` | No | Athlete ID for Intervals.icu (`0` targets the athlete account associated with the API key). |
| `GARMIN_EMAIL` | *None* | No | Garmin Connect account email. Read-only fallback used when no Garmin login is stored in the app. The UI login does not need it. |
| `GARMIN_PASSWORD` | *None* | No | Garmin Connect account password. Read-only fallback for login; the UI never stores the password. Remove it once tokens are stored. |
| `GARMINTOKENS` | `/data/garmin_tokens` | No | Path of the legacy Garmin token file. It is imported once when the database has no Garmin tokens and is left in place. |
| `GARMIN_FIXTURE_PATH` | *None* | No | Local mock JSON fixture path for development and testing without live Garmin credentials. |
| `WAHOO_CLIENT_ID` | *None* | No | Wahoo Cloud API application client ID. Wahoo counts as configured only when all three `WAHOO_*` values are set. |
| `WAHOO_CLIENT_SECRET` | *None* | No | Wahoo Cloud API application client secret. Stored server-side only and redacted from logs. |
| `WAHOO_REDIRECT_URI` | *None* | No | Full HTTPS callback URL, `https://<app-host>/api/wahoo/callback`. Never derived from the request Host header. |
| `YAZIO_EMAIL`, `YAZIO_PASSWORD` | *None* | No | Yazio account used for the optional read-only product lookup. Stored server-side only and redacted from logs; also editable under **Mehr > Anbindungen > Zugangsdaten**, where a stored value wins. |
| `YAZIO_COUNTRY` | `DE` | No | Two-letter country code sent as the Yazio search region (`DE` also selects German-language ranking). |
| `YAZIO_USER_AGENT` | built-in iOS client string | No | User-Agent sent to Yazio, which blocks unrecognized client versions (`version_blocked`). Set a current value when lookups fail with that error. |
| `CALENDAR_ICAL_URL` | *None* | No | Private read-only iCalendar (ICS) feed URL from Google Calendar, iCloud, or Outlook. |
| `COOKIE_SECURE` | `false` | No | Set to `true` when running behind an HTTPS reverse proxy to add the `Secure` flag to cookies. |
| `TRUSTED_PROXY_IPS` | *None* | No | Comma- or space-separated reverse-proxy addresses or CIDR networks (e.g. `192.168.1.6`). Only requests whose direct peer is in this list have `X-Forwarded-For` honored; the rightmost untrusted hop then becomes the client IP for login and API rate limits. The proxy must append the address it sees (nginx: `$proxy_add_x_forwarded_for`). List only the proxies themselves: a network that also contains clients, such as the whole LAN, lets those clients choose their rate-limit address through the header. Invalid entries, including a host address with a mask such as `192.168.1.6/24`, are ignored with a startup warning. |
| `DATA_RETENTION_DAYS` | `-1` | No | `-1` (or any value ≤ 0) retains data indefinitely; positive values are clamped to 30–3650 days and remove older chat messages and snapshots at startup. |
| `SYNC_HISTORY_EARLIEST_DATE` | `2000-01-01` | No | ISO date (`YYYY-MM-DD`) that bounds the historical Intervals.icu/Garmin backfill. The backfill walks back in 90-day chunks, never beyond this date, and stops after 180 consecutive days without records. An invalid value is ignored with a logged warning. |
| `PORT` | `8090` | No | Internal HTTP port the application listens on. |
| `DATA_DIR` | `/data` | No | Path to the directory where the encrypted database and any legacy Garmin token file are stored. |
| `TZ` | `Europe/Berlin` | No | IANA timezone (e.g., `Europe/Berlin`) used as the default athlete timezone when none is saved and as the container's local timezone. Crucial for accurate daily scheduling and sleep windows. |

---

## Installation & Deployment

### Docker Run

Run the published container image with a persistent data volume and read-only container root. The app runs as UID 100 / GID 101, so on a Linux host the data directory must belong to that user before the first start:

```sh
mkdir -p /mnt/user/appdata/ai-coach/data
chown -R 100:101 /mnt/user/appdata/ai-coach/data

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

*Note: Never run `docker rm -v`, as the `/data` volume contains your encrypted database and any legacy plaintext Garmin token file.*

The image runs as the non-root `app` user. Application code under `/app` is owned by root and is not writable by that user; only `/data` is writable.

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

Start the service. The app runs as UID 100 / GID 101, so on a Linux host give it the data directory first:

```sh
mkdir -p data
chown -R 100:101 data
docker compose up -d
```

### Unraid Deployment Guide

1. **Prepare Appdata Directory**:
   Create the storage folder on your cache pool and give it to the container user, which runs as UID 100 / GID 101:
   ```sh
   mkdir -p /mnt/user/appdata/ai-coach/data
   chown -R 100:101 /mnt/user/appdata/ai-coach/data
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
*When deploying behind HTTPS, remember to set `COOKIE_SECURE=true` in your `.env`. Set `TRUSTED_PROXY_IPS` to the address the app sees as the proxy's connection peer so rate limits apply per real client instead of to the proxy; without it, every request is attributed to the proxy. That is the proxy host's LAN address for a separate proxy (for example `TRUSTED_PROXY_IPS=192.168.1.6`), the proxy container's address for a proxy on the same Docker network, or `127.0.0.1` or the Docker bridge gateway for a same-host proxy like the nginx example above.*

### Provider credentials in the app

Intervals.icu, OpenAI and Wahoo credentials can be entered under **Mehr > Anbindungen > Zugangsdaten** instead of in `.env`:

- **Where values live:** a value saved in the app is stored in the encrypted database and takes precedence. The matching environment variable is a read-only fallback that applies again after the stored value is removed.
- **Badges:** each field shows "In der App gespeichert", "Aus Umgebung" or "Nicht gesetzt". "Entfernen" deletes only the value stored in the app and asks for confirmation.
- **Secrets:** API keys and client secrets are never shown again after saving, and the form is cleared on submit. Non-secret values (OpenAI base URL, Intervals.icu athlete ID, Wahoo client ID) are shown as the current value.
- **Timing:** changes apply without a container restart.
- **Privacy delete:** the local data purge removes stored credentials and Garmin tokens. A legacy token file at `/data/garmin_tokens` stays on disk, as every token store is preserved, but it is no longer used; delete it on the host if it should go too. It does not change the external Garmin, Intervals.icu or Wahoo accounts.

### Connection checks

Each provider card under **Mehr > Anbindungen** shows its configuration or sync state, and a separate "Verbindung" line with the last explicit check. "Verbindung prüfen" performs one bounded read-only request and never writes remotely or starts a sync. The OpenAI check does not change the OpenAI status shown elsewhere in the app. The result shows the check time and one of: successful, rejected credentials, rate limited, service unreachable, check not supported, invalid configuration, missing Wahoo permission (reconnect), check still running, or local state unreadable. A check that outlives 45 seconds is shown as still running and picked up when it finishes; the card reads again when it becomes visible. A repeat check within 10 seconds returns the stored result, except after a transient failure (unreachable or local read error), which is retried. It lives in memory only: it resets on restart and when the matching credentials change, and loading or polling the screen never contacts a provider.

| Card | Check | Limit |
| --- | --- | --- |
| OpenAI | `GET {OPENAI_BASE_URL}/models` | Compatible endpoints without a model listing (404, 405, 501) report "not supported"; 401 and 403 count as rejected. |
| Intervals.icu | `GET /athlete/{id}` | Confirms key and athlete ID, not data freshness. |
| Garmin | Login with the stored tokens only | Needs a connection made in the app; `GARMIN_EMAIL` without tokens or a preserved token file shows "nicht konfiguriert". Never falls back to e-mail and password, and waits for no running sync (reports "busy"). The SDK does not distinguish causes, so any failure (including an outage) asks to retry or sign in again, and a success may only show that the tokens are accepted locally. A reconnect or any other change of the stored login drops the earlier result. Fixture mode (`GARMIN_FIXTURE_PATH`) reports not supported. The check is skipped while a Garmin sync runs.  |
| Wahoo | `GET /v1/user` with the stored token | Needs a completed Wahoo connection with the `user_read` scope; without it the card asks to reconnect Wahoo. Uses the same client as the sync, so it may refresh the token, and a rejected refresh disconnects Wahoo as it does for a sync. |
| Open-Meteo | Forecast for fixed public coordinates | Needs no key; never sends the profile location. |
| Yazio | Authentication only | See below. |

The shared calendar and Open Food Facts have no check: a calendar check would be the full feed fetch, which "Synchronisieren" already performs, and Open Food Facts needs no credentials.

### Garmin Authentication & MFA Setup

Garmin Connect enforces Multi-Factor Authentication (MFA). The primary way to connect is the UI:

1. Open **Mehr > Anbindungen > Zugangsdaten** and enter your Garmin E-Mail and password, then choose "Bei Garmin anmelden". The password is sent once to the server and is never stored; the form is cleared as soon as it is submitted.
2. If Garmin requests a verification code, the card switches to a code step. Enter the code sent to your email or mobile device. "Abbrechen" returns to the login form; the pending login expires on the server after 10 minutes.
3. On success the card shows "Verbunden" with the source "In der App gespeichert". The Garmin OAuth tokens are stored in the encrypted database, not in a file.
4. **Disconnect:** "Garmin trennen" (after a confirmation) deletes the stored Garmin tokens. Already loaded data stays in the local database. A preserved token file is not used again. `GARMIN_EMAIL` and `GARMIN_PASSWORD` from the environment are not used either; Garmin syncs stay off until the next login in the app.

An existing token file at `/data/garmin_tokens` is imported once when the database has no Garmin tokens yet. The file is left in place and is not deleted by the import. Because it is plaintext JSON protected only by owner-only file permissions, keep `/data` and every backup of it on encrypted host storage, and treat the file like a password.

The bundled `garmin-login.py` helper is still available as an alternative for headless setups. It runs inside a temporary container attached to your data directory, which on a Linux host must already belong to UID 100 / GID 101 (`chown -R 100:101`, see [Docker Run](#docker-run)):

```sh
docker run --rm -it \
  --env-file /mnt/user/appdata/ai-coach/.env \
  -v /mnt/user/appdata/ai-coach/data:/data \
  ghcr.io/lukas-beike/ai-coach:latest \
  python /app/garmin-login.py
```

`GARMIN_EMAIL` and `GARMIN_PASSWORD` from `.env` remain a read-only fallback for the app's own Garmin login and for this helper. If you connect through the UI, you can remove `GARMIN_PASSWORD` from `.env`; the stored tokens are then used.

### Wahoo connection

The app can connect to Wahoo through OAuth and reads its workouts. Library workouts are written to Wahoo only when you explicitly start a Wahoo library sync (see step 6).

1. Register an application in the Wahoo developer portal and set its redirect URI to `https://<app-host>/api/wahoo/callback`. This must be the HTTPS URL at which you reach the app, and it must match `WAHOO_REDIRECT_URI` exactly.
2. Set the client ID and secret under **Mehr > Anbindungen > Zugangsdaten**, or as `WAHOO_CLIENT_ID` and `WAHOO_CLIENT_SECRET` in the environment, and set `WAHOO_REDIRECT_URI` in the environment and restart the container. The redirect URI is not editable in the UI. Without all three values, the Wahoo card under **Mehr > Anbindungen** shows "Nicht konfiguriert" and explains which server variables are missing; no secret is ever shown in the browser.
3. **Connect:** in **Mehr > Anbindungen**, choose "Wahoo verbinden". The app calls `POST /api/wahoo/connect` (session and CSRF protected), which returns the Wahoo authorize URL, and the browser follows it. The callback `GET /api/wahoo/callback` needs no session (session cookies are SameSite=Strict); it is accepted only with the server-stored, single-use state that expires after 10 minutes, and always redirects to `/?wahoo=connected` or `/?wahoo=error`. The PWA reads only that outcome word, shows a confirmation or error message and removes it from the address bar.
4. **Status:** the card shows "Nicht verbunden", "Verbunden" or, after Wahoo rejected the stored refresh token, "Erneute Verbindung erforderlich" with a "Wahoo erneut verbinden" action. Wahoo also appears with its registry label in the connection summary, the data-freshness list, running-sync progress and the manual-attention banner.
5. **Disconnect:** "Wahoo trennen" (after a confirmation) calls `POST /api/wahoo/disconnect`, which revokes access at Wahoo (best effort) and deletes the local tokens, also after the server variables were removed. Workouts that were already imported stay in the local database.
6. Tokens are stored in the encrypted database, refreshed with rotation before expiry, and excluded from exports, diagnostics and coach context. The state JSON reports only `configured`, `connected`, `scope` and `connected_at`.
7. **What is synced:** Wahoo is polled only; no webhooks are used. Once connected, the startup and daily schedulers enqueue a Wahoo refresh (default window 84 days). Workouts are stored as canonical activities with the provider `wahoo` and local dates, including duration, moving time, distance, ascent, average heart rate, cadence and power, normalized power, work (kJ) and the Training Stress Score as a separate TSS load model that is never summed with Intervals.icu or Garmin load. Calories and speed stay only in the raw record, and the workout file download URL is not stored. The sync status shows them as "Wahoo". While connected, the Wahoo card offers "Jetzt synchronisieren" (`POST /api/wahoo/sync`, queues a refresh over the default window) and "Vollständig neu synchronisieren" (`POST /api/wahoo/full-resync`, re-reads the maximum window of 90 days). The full resync deletes no local data and never writes to Wahoo; if Wahoo holds more workouts than one run can read, the newest are stored and the resync is reported as failed instead of complete. While it runs, scheduled and manual Wahoo syncs and plan exports are rejected with a busy message. A disconnected account is skipped with the not-connected message; stored activities are kept. Two threshold reads follow the same run: `power_zones_read` supplies the newest cycling FTP and `user_read` the profile weight. They are the lowest-priority sources for current FTP and weight, after Garmin and Intervals.icu. A Wahoo FTP or weight observed more than 90 days before the athlete's local today is not used as the current value; it stays stored for history. A read whose scope was not granted is skipped, and a 403 or 404 on either read is non-fatal while the workouts are still stored; any other failure stops the run.
8. **Explicit plan export.** A library workout is uploaded to Wahoo as a plan only by the explicit library synchronization action with the target `wahoo` (`POST /api/sync/jobs` with `{"provider": "wahoo", "type": "plan_push", "payload": {"entries": [...]}}`, using the same session and CSRF protections and the same preview hash as Intervals.icu). Intervals.icu stays the default target; the Coach and adaptive replanning never export to Wahoo. The Wahoo plan id is kept in the local remote links, so a second sync updates the same plan instead of creating a duplicate, and a plan deleted at Wahoo is created again. Without a connected Wahoo account the request is rejected with a reconnect hint and nothing is written. Wahoo plans support cycling and running workouts with time-based steps and absolute targets (`W` or `BPM`, or a pace for runs). Ramps, zone targets, other sports, and percentage targets (which need an FTP or heart-rate reference that is not synchronized to Wahoo) are rejected for that workout with a clear message; the other selected workouts still sync. Format reference: <https://cloud-api.wahooligan.com/docs/plan-json-format.pdf>.
9. **Workout files.** After a sync, the FIT files of at most 10 workouts per run are downloaded read-only and kept as full-resolution streams and laps, a failed download is retried at most three times per workout version and an empty file is not retried; the signed download link is never stored or logged.

---

## Loading, Synchronization & Job Architecture

### Background Scheduling Engine
- **Startup**: On launch, `server.py` composes configuration, persistence, providers, HTTP routes and workers; startup initializes the database and enqueues configured refreshes.
- **Hourly Provider Cycle**: The scheduler loop wakes every 300 seconds. Calendar, Garmin and Intervals refreshes become eligible once their latest attempt or success is at least 3,600 seconds old; weather refreshes are queued on a pass when a location is configured, no weather job is active, the 3-hour forecast cache has expired and no retry backoff after a failure is pending. Startup and manual weather refreshes still force a fresh read.
- **Garmin Recent History**: Manual activity synchronization defaults to 84 days for both providers. Automatic Garmin synchronization first loads 84 days of activities, sleep, HRV, daily statistics and resting heart rate where supported. Subsequent hourly refreshes normally read today and yesterday; the first refresh of each local day re-reads the last 7 days so late watch uploads replace partial values. Slowly changing metrics (heart-rate zones, gear, race predictions, VO2 max, FTP and lactate threshold, endurance score, running tolerance and their histories) are read on that first daily refresh and after a new activity; other refreshes keep their stored values and freshness. Successfully read continuous date windows are retained per collection; failed collections do not advance their coverage. After an outage, refreshes catch up from the oldest collection endpoint with overlap, bounded to 90 days per request. Historical activity backfills do not advance recovery coverage.
- **Intervals.icu Recent History**: The first automatic Intervals.icu refresh of each local day reads the whole configured sync period, so remote edits and deletions inside it arrive daily; a manual refresh of the whole period counts as that read. Later automatic refreshes that day read today and yesterday and merge into the stored snapshot, keeping the sync period's wellness rows in date order. A failed full read keeps the next automatic refresh full.
- **Analysis Coverage**: Charts expose the number of available dated values; recovery charts show measured days and the earlier nights of the 42-day comparison. Training focus shows locally known Garmin sessions and their observation dates. Missing measurements and recordings remain unknown, never confirmed zeros or rest days.
- **Periodic Synchronization Loop**: Each loop pass enqueues eligible calendar, Garmin and Intervals refresh jobs and runs the morning Body Battery refresh. The loop uses the athlete's local clock for provider freshness markers; there is no fixed 03:00 daily run.
- **On-Demand Refreshes**: The UI and Coach can enqueue provider, calendar, weather and performance refresh work through the documented API routes. When the athlete explicitly asks the Coach for current data, the Coach waits for the Intervals.icu and Garmin refresh to finish before answering instead of queueing a job; a Garmin refresh also updates the morning Body Battery, and the answer notes when it finished only partially. Calendar and weather refreshes stay queued.

### Priority Queue & Durable Job Processing
Conversational turns are persisted in `coach_commands`; provider synchronization and background work use durable jobs in `sync_jobs`.
- **Streaming Handshake**: When an HTTP turn starts, Server-Sent Events (SSE) immediately return the durable job UUID.
- **Decoupled Execution**: If the athlete locks their phone or loses cellular connection, the server continues execution uninterrupted.
- **Recovery on Reconnect**: Upon reconnection or app reload, the PWA polls the durable job result using its UUID, rendering the completed answer without re-executing actions.
- **Visible Provider Failures**: OpenAI API credit, quota, spending-limit, access, rate-limit, unavailable-model, conversation-state, timeout, and service-unavailability failures produce a clear recovery instruction in the chat history, including classified failures reported inside an HTTP-200 response stream. The message remains visible after reload; private provider error text is not shown. Unknown failures use a safe technical-error message with retry and diagnostic-export guidance.
- **Busy Local Database**: When no database connection becomes free in time, a sync or a recorded Coach turn failure shows a short German retry message instead of a technical one, also when the database was busy after a provider answer arrived. Any other HTTP request, including login and starting a turn, answers with a retryable HTTP 503 (`reason: database_busy`, a `Retry-After` header and `retry_after_seconds`) instead of a server error. Login and logout wait at most 10 seconds for the writer and never queue behind startup syncs or the canonical backfill, which yield the writer to waiting requests between their transactions. A Coach turn failure that cannot itself be stored keeps the generic server error. A sync that fails this way is queued again like a network error and never raises the manual-attention banner. Older stored English errors stay until the next successful sync.

### Provider Data Handling
- **Intervals.icu Activity Pull**: Ingests new completed workouts with full telemetry (duration, distance, TSS, HR zones, power curves). Large imports are safely fetched in paginated windows.
- **Garmin Sleep Gate & Body Battery**: Morning synchronization deliberately halts until Garmin's sleep window completes. Body Battery tracking captures the final pre-sleep value and the wake-up value within 60 minutes of rising, retrying up to 3 times with 15-minute intervals.
- **Garmin Element Storage**: A Garmin sync stores each element of a collection (a sleep night, a daily summary, a gear item) as its own raw row keyed by the provider's id or calendar day, and writes only the elements that changed; an unchanged element is not rewritten. Activities keep their own rows and tables. The small remainder (fetch times, source freshness, cursors) stays in one small `garmin_state` value. Readers load only the sections and days they need; only the privacy export, which rebuilds `garmin_snapshot.json` from the rows, reads everything. Garmin never deletes activities, a full resync merges its state keys, and a payload without a readable fetch time updates the state only. Gear is identified by its `gearUUID`.
- **Garmin Activity Details**: After each successful automatic or manual Garmin sync, the details of up to ten recent Garmin activities from the last 90 days load automatically, newest first and read-only; the backfill pauses after a Garmin rate limit, and manual activities are skipped.
- **Open-Meteo Weather**: Forecasts are fetched for the athlete's coordinates and cached for 3 hours. For locations in Germany, the first two days use the DWD ICON-D2 model; other locations and the remaining days up to 14 use ECMWF IFS HRES. Air quality comes from the Open-Meteo Air Quality API; the DWD pollen region is resolved from the coordinates through the DWD GeoServer and its levels are read from the DWD open-data feed. Both sources are optional: a failure is logged and the weather forecast is still cached. Attribution: Open-Meteo.com, Copernicus Atmosphere Monitoring Service, and Deutscher Wetterdienst (CC BY 4.0).
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

Each pooled database connection uses a 16 MiB page-cache budget to reduce repeated encrypted reads of large histories. The default pool has four readers and one writer (up to 80 MiB of page caches, allocated as needed).

### Maintenance Mode & Database Restoration
When a database restore is initiated:
1. The uploaded backup is first written in 1 MiB chunks to a new staging file in `/data`, so it is never held in memory as a whole; the size limit is enforced while writing. Staging does not touch the live database, and the staging file is removed when the restore ends. If the process is killed first, leftover staging files, unencrypted privacy-export archives and database-backup snapshots stay in `/data` until the next start removes them before any worker runs.
2. The application enters an exclusive maintenance mode, rejecting new incoming API mutations with an HTTP 503 maintenance notice.
3. Active background sync jobs and Coach turns are allowed to finish gracefully.
4. If an active database exists, a timestamped pre-restore copy is saved beside it in `/data` using the name `intervals-coach.db.pre-restore-<timestamp>-<id>`. The restore is refused with HTTP 507 when `/data` lacks the free space for this copy, and a partial copy is deleted.
5. The replacement database must have the current schema (version 19) or a supported released schema from version 16 onward; a version 16 backup is upgraded on the staged copy during validation, and older, newer or unknown schemas are rejected unchanged. It must also pass SQLite integrity and foreign-key checks. Restored sessions are cleared before it is installed; failed validation rolls back the staged changes.
6. If valid, the new database is swapped into place and the maintenance gate is lifted; if invalid, the original database is preserved without data loss. A storage failure during the copy or swap returns HTTP 507 (disk full) or 500 instead of a validation error and leaves the original database and its WAL files in place.

### Privacy Export & Data Purge
- **Full Privacy Export**: Download a single comprehensive JSON archive containing all stored profile fields, workouts, check-ins, activity notes, and chat history. Export format version 10 also includes the canonical provider tables (provider records, activity sessions with the survivor each deleted merged session keeps, activity records, observations), the canonical activity detail (detail sets, stream channels as decoded point lists with `null` gaps, laps, zone times and session analyses) and the canonical sleep periods, zone configurations with decoded limit lists, provider statuses, gear and gear-to-activity links, retired rows included, as JSON Lines, the owning provider and session of each activity note, when known, and the remote links that map local workouts, planned units and competitions to their provider counterparts (including the provider of each competition sync tombstone). Stored sports are exported in the canonical vocabulary (`sport`, `environment` and a lossless `sport_detail`), and planning records name their start and planned duration `starts_at_local` and `planned_duration_s` (since version 8); version 9 adds the canonical power curve and version 10 the session RPE rating time of each activity note; credential-like keys are removed from provider payloads before export, and signed download URLs are replaced with a `[redacted]` marker.
- **Local Data Purge**: Completely wipes all local athlete records from the database, including canonical provider data. To prevent accidental loss, the action requires entering the exact confirmation phrase `LOKALE DATEN LÖSCHEN`. External accounts (Intervals.icu and Garmin) remain untouched.

### Operational Logging & Diagnostics
- **Sanitized Logs**: Standard container logs contain only operational timestamps, correlation IDs, status codes, and anonymized error classifications. API tokens, passwords, and athlete metrics are never logged.
- **Always-on Technical Diagnostics**: The application keeps up to 10,000 recent diagnostic entries (16 MiB total, 1 MiB per entry, with truncation marked), including sanitized Coach requests, provider responses, tool activity, and classified provider error details such as status, error code and request ID. Raw OpenAI error text is not stored. Credentials, keys, tokens, and session data are removed before storage.
- **Server Log Management**: In **Betrieb & Diagnose**, authenticated users can download the sanitized current server log and its available rotations as JSON Lines, or delete the log files.
- **Diagnostics Management**: In **Betrieb & Diagnose**, authenticated users can download the sanitized technical diagnostic report as JSON, or clear the stored technical diagnostic entries.
- **Canonical Coverage Summary**: The diagnostic report includes a `canonical_coverage` section with per-provider counts only: activities, observations, issue counts per reason, and whether a sync time is stored. It contains no dates or record content. If the summary cannot be computed, the section reports `unavailable` without details.
- **Canonical Backfill Status**: The diagnostic report includes a `canonical_backfill` section next to `canonical_coverage`. It copies stored legacy snapshots into the canonical tables in newest-first batches. Each run is insert-only: existing rows, live or deleted, are never updated or revived, and the backfill never deletes data. The newest Intervals snapshot is the only one that inserts activities, because it already shows every activity that still exists upstream. Each activity in an older snapshot is skipped and counted as `superseded`, so older data cannot revive activities that were deleted or fall outside the synced range. Older snapshots still insert their wellness and athlete records and observations when absent, and their `snapshots` rows are never modified or deleted. Active provider records whose mapper version is behind the current version are re-projected from their stored raw data. Re-projection never revives a deleted activity, and leaves an activity whose session is deleted untouched. When the new projection no longer emits an activity that an active raw record owns, that activity becomes `invalid` (its session keeps its state) and is counted as `retired`; a later mapper version that emits it again makes it `active` with the same id, counted as `reprojected`. Observations are not retired: an observation that an upgraded mapper no longer emits keeps its old `mapper_version`. While a re-projection is pending, the table reader serves each observation at the newest version stored for it, so nothing disappears; once the backfill completes it serves only observations at the current version. A mapper-version change during a partial re-projection restarts the re-projection scan, including records already passed by the interrupted run. Temporary writer contention waits and retries the same batch. The section reports `status` (`pending`, `running`, `complete`, or `failed`), the number of `batches`, `unresolved_feedback` (feedback entries that match no activity), and per-provider counters: `inserted`, `already_present`, `superseded`, `skipped_invalid`, `sessions_created`, `duplicates`, `reprojected`, and `retired`. It contains counts only, never activity ids, names, or dates. A `failed` run resumes from its saved cursor at the next startup. If the status cannot be read, the section reports `unavailable`. Activity details are served only from the canonical tables as `activity_detail.v1` for every provider. Once the detail backfill has finished, a follow-up stage retires the older per-activity `activity_detail:` records in the key-value store: a record is deleted only when its streams, laps, zone times and analysis are proven equal to the canonical rows in the same transaction, missing lap maximum speeds are filled in from it first, and a record that cannot be proven stays stored and is counted by reason in the stage state without being read. The stage resumes from its cursor after an interruption, and loading details again never writes those records.
- **Garmin Snapshot Size**: The diagnostic report includes `database.garmin_snapshot_bytes`, the UTF-8 byte size of the stored `garmin_snapshot` value (`0` when absent). SQL measures this without loading or parsing the payload in Python; the report adds only the byte count. This is a stored-payload measurement, not the process's RAM usage.
- **Runtime Memory Diagnostics**: The diagnostic export adds `runtime.process_memory`: available Linux RSS, peak RSS, locked/anonymous/file memory and virtual bytes, thread count, mapping count and kernel mapping limit. Only numeric counters are exported; process memory, mapping addresses and file paths are never captured. Unavailable OS counters are omitted. Sync start, completion and failure log events include the same counters for before/after comparisons; the snapshot byte count is measured only for the diagnostic report.
- **Stalled Server Stack Dump**: `docker kill -s USR1 AI-Coach` writes the stack of every Python thread to the container log (`docker logs`) without stopping the process. The dump contains file names, line numbers and function names only, no variable values. Capture it before restarting a container whose health check times out.
- **Database Memory Budget**: Each pooled SQLCipher connection targets a 16 MiB decrypted-page cache. SQLite's cache target is not a hard process RAM limit: Python objects, query results and other native allocations use additional memory. The database file stays encrypted; `cipher_memory_security` is OFF because locking every SQLCipher allocation in memory fragmented the process into tens of thousands of mappings until allocations failed near the kernel's `vm.max_map_count`. A larger host `vm.max_map_count` can provide temporary mapping headroom but does not correct memory growth.
- **Garmin Metadata Reads**: Automatic sync-window selection, current Morning Body Battery, daily planning and the nutrition day and week energy summaries extract only their required snapshot fields in SQL. Unrelated Garmin collections are not decoded into Python objects for these reads; full sync/merge reads and the stored history remain intact. **Analyse**, `/api/performance` and the Coach performance and recovery sections read Garmin values only from the canonical tables and take only the small stored sync status (freshness, fetch times, read windows) from `garmin_state`.
- **Canonical Read Source**: The diagnostic report includes a `canonical_read` section that names the source serving reads (`tables`, or `pending` while nothing is served yet), the `reason`, and whether the stored check matches the current digest. Reads come from the canonical tables once the backfill has completed at least once; a content-free marker in the backfill state records that, and an existing `complete` state counts as completed. Until then, for example right after an upgrade, reads return no values and **Analyse → Leistung** and the Coach report "Daten werden vorbereitet" instead of partial values. After the first completion a mapper-version or time-zone change re-projects the stored records in the background while reads stay on the tables, and a sync inside the running process is written to the tables as it happens. Coverage is served from the summaries persisted at ingest; before the first completion only current summaries are reported. An Intervals.icu snapshot stored by a release before raw provider data lists its activities only in compact form; those activities cannot be backfilled, so **Analyse → Leistung** shows "Aktivitäten: Intervals.icu neu abrufen" until **Lokale Daten neu laden** on the Intervals.icu card (`POST /api/intervals/full-resync`) loads them again as raw rows. A normal sync keeps the older compact rows and the mark. The section reports `serving`, `reason` and `digest_current` (false while a re-projection is pending), and reports `unavailable` if its state cannot be read.

---

## Development, Testing & Contribution

### AI coding instructions

Keep shared policy in [AGENTS.md](AGENTS.md) and its scoped files, PR review
criteria in [REVIEW.md](REVIEW.md), and task workflows in the
[repository skill index](.agents/skills/README.md). Load relevant workflows on
demand; keep deployment commands here. All project skills have one canonical
root, `.agents/skills/`; full review and `pr` were moved from the legacy `.codex/`
root without duplicate copies. No duplicate `CLAUDE.md` is needed.

Rules without exceptions are enforced, not just written down:
[`.claude/settings.json`](.claude/settings.json) denies agent file access to any
`.env`/`.env.local` and to the `data/` directory of this checkout and the
primary `ai-coach` checkout. Before every shell command it runs
`scripts/hooks/guard_private_paths.py`, a tested text-matching safety net (not
a sandbox) that blocks clear `.env`, `data`, and Garmin token path forms with no
exceptions, so you run the Docker runbook commands that pass `.env` or mount
`data` yourself. It also blocks commands that merely mention such a path, such
as a commit message; pass that text through a file.
`.claude/agents/` defines the `explorer` (Haiku, low effort, read-only),
`implementer` (Sonnet, medium), and `reviewer` (Sonnet, medium, read-only)
subagents.

Sessions default to `medium` effort (`effortLevel` in `.claude/settings.json`);
raise it with `/effort high` for tricky work. Agents may not go above `high`
without your approval. `/pr`, `/deliver-issue`, and `/ai-coach-release-unraid`
are user-only Claude Code commands (`disable-model-invocation: true`) that load
the canonical workflows in `.agents/skills/`.

To keep usage down, start a fresh session (`/clear`) for each unrelated task;
every turn re-sends the whole conversation. Check `/usage` occasionally to see
which skills and subagents earn their cost, and delete skills nobody loads.

The local [code-review skill](.agents/skills/code-review/SKILL.md) adapts
Claude's review workflow for PRs and pre-push branch diffs. Agents read it
directly; the `pr` workflow requires no host-specific slash command.

The [orchestration skill](.agents/skills/orchestrated-plan-implementation/SKILL.md)
decides per task whether delegating to subagents pays off; by default the main
model does the work. Delegated tasks use fixed tiers without a model question:
Claude Haiku alternating with Gemini Flash for easy tasks, Claude Sonnet for
standard work, and Claude Opus only for genuinely hard or risky tasks, each at
its newest available version. Writers use isolated worktrees; the main model
reviews and integrates their branches.

The [retro skill](.agents/skills/ai-coach-retro/SKILL.md) runs on request and
briefly after a `deliver-issue` run. It prefers removing or shortening
instructions; a new rule needs an observed failure that a hook or test cannot
prevent.

Coding tasks default to the repository's [Ponytail workflow](.agents/skills/ai-coach-ponytail/SKILL.md)
in `full` mode: the smallest complete change, reusing existing code before adding
dependencies or abstractions. Any agent can read its Markdown directly;
the external Ponytail plugin is optional. Say `ponytail lite`, `ponytail full`,
`ponytail ultra`, or `stop ponytail` to change the session mode. Repository safety
rules and required checks still apply. This is instruction routing, not a CI gate.

For any coding agent, start in the task worktree and load root plus applicable
scoped AGENTS guidance. Identify the requested behavior, affected owner, and
acceptance check; select the relevant skill, implement the complete flow, inspect
the final diff, and run affected validation. Include final-state evidence and
unverified checks in the handoff. Source code and current workflow behavior take
precedence over remembered paths or stale operating assumptions.

#### Optional local OpenSpec

[OpenSpec](https://github.com/Fission-AI/OpenSpec) 1.14.3 is pinned as a local
development dependency. It manages behavior specifications and change plans;
the application does not load it. Node.js >=20.19.0 is required. Install and
check it from the task worktree. The preparation entry point also sets up
Graphify and generates its first graph; configure worktree creation to invoke it
after the script reaches develop:

```powershell
python scripts/prepare_worktree.py
npm.cmd run openspec -- --version
npm.cmd run openspec -- list --specs
npm.cmd run openspec -- validate --all --strict --no-interactive
```

If only Node dependencies need preparing, `npm.cmd ci --ignore-scripts` remains
the manual fallback. Use `npm` instead of `npm.cmd` outside Windows and in Git
Bash, where `npm.cmd` breaks arguments that contain spaces. The repository script disables
OpenSpec telemetry on every invocation; no global CLI, skills, profile changes,
store, hosted service, or model credentials are required. Its config/data homes
are isolated under ignored `.openspec-local/` in the working directory, including
profile migrations triggered by `init` or `update`. The universal
`agents` adapter installs six skills directly into `.agents/skills/`, shared
by agents that support that directory. Other agents read the linked
skills in the index. Restart a session if its skill catalog was already loaded.
Host-specific slash commands are not installed; plain-language requests such
as "use openspec-propose to plan a backfill of Coach write authorization" work
through the repository skill index.

To regenerate those skills from the installed, pinned CLI:

```powershell
npm.cmd run openspec -- init --tools agents --profile core --no-animation
```

Review the generated diff and retain the project context/rules in
`openspec/config.yaml`. Do not pass `--language` when regenerating an existing
project; the language instruction is already in its context. Deliberate upgrades
update the exact dependency pin, lockfile, generated skills, and their provenance
together. Do not run the bare `openspec config profile`: that changes user-global
configuration. Existing
AGENTS boundaries and authorization take precedence over generated workflows;
OpenSpec does not replace repository review, orchestration, or validation.

**Application specifications.** The [OpenSpec baseline](openspec/README.md)
documents the application's behavior by capability. Its
[coverage ledger](openspec/COVERAGE.md), [surface inventory](openspec/coverage.json)
and [Coach tool map](openspec/COACH_TOOLS.md) are frozen snapshots of the
baseline revision and are not maintained further. A valid document is not proof
of runtime conformance.

OpenSpec is optional. Most changes put their acceptance criteria in the PR body,
but a behavior change still updates the affected main specs in `openspec/specs/`
directly; the `pr` workflow finds them by the changed files they cite.
Use an OpenSpec change for a larger feature (a new capability or a behavior change
across several flows) or when asked, created with the CLI:

```powershell
npm.cmd run openspec -- new change add-example-capability
npm.cmd run openspec -- instructions proposal --change add-example-capability --json
npm.cmd run openspec -- archive add-example-capability --yes
```

Keep it to a proposal, the spec delta, and tasks finished before merge. Archive
it in the same branch as the implementation; `archive` also updates the main
specs, and the `pr` workflow blocks a push while a touched change is still active.

#### Local code graph

Worktree preparation uses `python scripts/prepare_worktree.py` to install Node
development dependencies, the hash-locked `ruff` and `mypy` pins from
`requirements-dev.txt` into that interpreter (`tools/quality_baseline.py` runs
them as `python -m`), set up Graphify and generate the first graph.
Graphify's version comes from the hash-locked `requirements-graphify.txt`.
Run the tooling scripts with Python 3.14 or newer. Setup requires Python 3.14
for its environment and selects it explicitly (`py -3.14` on Windows,
`python3.14` on POSIX) when called with a newer interpreter.
One shared virtual environment per version and lock hash lives under
`%LOCALAPPDATA%/ai-coach/graphify` on Windows, or
`$XDG_DATA_HOME/ai-coach/graphify` (default `~/.local/share/ai-coach/graphify`)
on POSIX. Graphs, update locks, isolated home and exports stay per worktree
under `.graphify-local/`. Session hooks never install missing tools.
Preparation uses `update --preparation` with a 600-second budget; hooks and
plain `update` keep 180 seconds. Graphify does not require Sonar; source allowlists
and credential/runtime exclusions remain enforced.
Codex and Claude Code are configured to run the same local `update
--session-start` command synchronously at session start and resume. This keeps
the graph fresh before use; after edits during a session, run
`python scripts/graphify_local.py update` before querying it. Check `status`
first if an update could not complete.

As a manual fallback, run `python scripts/graphify_local.py setup`, then
`python scripts/graphify_local.py update`. Setup serializes creation, verifies
every package hash and reuses a ready environment without installing again.
`python scripts/graphify_local.py prune` explicitly removes other unlocked shared
environments that no running Graphify command uses; nothing prunes automatically. Old `.graphify-local/venv` directories
are unused and may be removed manually. Only setup and worktree preparation may
download packages; subsequent graph operations stay offline. Use
`status`, `query <terms>`, `path <source> <target>`, and `explain <symbol>` to
inspect availability and navigate; queries select the active graph
automatically. Run `python scripts/graphify_local.py export html --output .graphify-local/exports/graph.html` or
`python scripts/graphify_local.py export wiki --output .graphify-local/exports/wiki`
for local views; exports are restricted to `.graphify-local/exports/`. `mcp`
starts the optional local stdio MCP server. Its read-only snapshot exposes
`graph_query`, `graph_node`, `graph_path`, and `graph_stats`, with no upstream
PR tools; restart the server after graph edits to refresh the snapshot. The hook
does not read session payloads or transcripts. Native host activation has not
been verified; the hook tests do not prove Codex or Claude dispatch. Codex may
require repository trust approval in `/hooks` before activation.

The graph represents structural relationships only. Semantic documentation
enrichment is disabled; it requires a separately installed, explicitly local
model and is outside this integration. Always check current source, callers,
tests, and applicable instructions before acting on graph findings. Broad or
stale matches can be incomplete; use ordinary source search when needed.

The Codex hook is configured in `.codex/hooks.json` and refreshes Graphify without
scanning incoming prompts. Codex requires accepting the repository hook in its
`/hooks` trust UI. Claude Code uses `.claude/settings.json` and requires its
normal repository trust. Do not bypass either trust prompt. The checked-in
Claude hook uses the documented PowerShell shell on Windows. For POSIX Claude
installations, use the included `scripts/graphify-session-start.sh` and this
SessionStart command configuration:

```json
{
  "type": "command",
  "command": "sh \"$(git rev-parse --show-toplevel)/scripts/graphify-session-start.sh\"",
  "shell": "bash",
  "timeout": 240
}
```

Both launchers resolve the repository root, including when the session starts
in a nested directory. If the worker or Python is unavailable, they print a
short status message, do not install anything, and let the session continue.

On 2026-10-24, T3 Code delivered the Claude SessionStart hook in a task worktree.
This observation does not establish delivery by every host/provider; run the
update manually if the hook is skipped. After merge, the T3 worktree-creation
script can invoke `python scripts/prepare_worktree.py`; host configuration is
separate from this repository.

AI documentation is checked by the existing
`Validate repository AI documentation` workflow. Locally, after secrets scans,
run `python -m unittest discover -s tests -p test_ai_docs_contract.py -v`.
These structural checks catch broken guidance/discovery; they do not measure
coding quality. Behavioral comparisons use the repository skill-evaluation workflow
with synthetic tasks and isolated sessions, without live accounts or deployments.

For Claude Code, verify instruction loading in the actual session:

1. Run `claude --version`; native AGENTS support requires 2.1.277+, with broader
   session support from 2.1.281. Restart after upgrading.
2. In `/config`, check **Project instructions**. The default
   `claude-md-or-agents-md` works when no project/ancestor `CLAUDE.md`,
   `.claude/CLAUDE.md`, or `CLAUDE.local.md` shadows AGENTS. If one is needed,
   choose `claude-md-and-agents-md`; ensure the built-in AGENTS plugin is enabled.
3. Use `/memory` to confirm root instructions loaded; after reading backend,
   frontend, or test files, verify their scoped instructions too.

Claude instruction loading does not auto-discover skills under `.agents/`.
Follow the skill index explicitly; do not copy skills globally. Project
workflows remain repository-owned; app-supplied skills and their tools have
[separate replacement constraints](.agents/skills/references/app-skill-ownership.md).
AGENTS and review text guide behavior; CI, permissions, and hooks provide
deterministic enforcement.
These files do not activate hosted reviews or prove session configuration.

References: [Claude best practices](https://code.claude.com/docs/en/best-practices)
and [AGENTS loading](https://code.claude.com/docs/en/memory#agents-md).

### Secret checks before Git pushes

Source reads, incoming prompts/provider data, and Graphify do not require a secret
scan. Outgoing Git objects are checked by `.githooks/pre-push`, which invokes
`python scripts/check_push_secrets.py`. It scans the lines the outgoing
commits add (so flagged lines already on the branch's base never block a push)
and commit/tag messages, including intermediate commits, in temporary storage and suppresses scanner payload output.
A finding, missing Sonar CLI, or scanner error blocks the push. Deleted refs need
no scan. Do not use `--no-verify`.

Enable the hook in each clone (the relative path also works in its worktrees):

```powershell
git config core.hooksPath .githooks
```

For a one-off push without changing clone configuration, use
`git -c core.hooksPath=.githooks push <remote> <branch>`.

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
CI splits the native suite into `PYTHON_TEST_SHARDS` shards (currently 4). Each
shard keeps every `TestCase` class whole, so class-level fixtures such as
`ServerTestCase.setUpClass` run once per class. Classes are assigned heaviest-first
to the least-loaded shard, so the assignment is deterministic and does not depend
on discovery order. A class weighs its recorded wall time from
`tests/test_durations.json`; a class without a recording weighs its test count
times the median recorded seconds per test. The quality job fails unless every
shard uploads exactly one coverage file. Run one shard locally, or list its test
IDs without running them:
```powershell
python tests/run_tests.py --shard 1 --total 4
python tests/run_tests.py --shard 1 --total 4 --list
```
Refresh the recording when shard times drift apart, with a full unsharded run in
the image. The Windows runner uses the same read-only mounts and writes the file
into the given directory, which then replaces `tests/test_durations.json`:
```powershell
New-Item -ItemType Directory -Force $env:TEMP\durations | Out-Null
.\tests\run_sqlcipher_tests.ps1 -RecordDurationsDirectory $env:TEMP\durations
Copy-Item $env:TEMP\durations\test_durations.json tests\test_durations.json
```

#### Container-Sensitive Suite
`--suite container` runs only the modules that depend on the container runtime:
SQLCipher, the read-only non-root runtime, configuration, startup, security limits,
privacy, and authentication sessions. The CI `container_tests` job runs this subset
inside the built image. The default `--suite all` runs everything:
```powershell
python tests/run_tests.py --suite container --list
```

#### Isolated SQLCipher Integration Tests

The PowerShell helper delegates to the standard-library supervisor. It builds
current application source once, then derives a disposable test image with Git
for synthetic repository tests; production `Dockerfile` stays unchanged. Tool
preparation may use the network, but tests run as the app user in read-only,
networkless containers with temporary data, one CPU and 512 MiB per worker.
Explicit read-only test inputs exclude the checkout root, `.git`, `.env` and live
data. Application server/backend/public files come from the current image.

```powershell
./tests/run_sqlcipher_tests.ps1
./tests/run_sqlcipher_tests.ps1 -Workers 2 -CacheState warm
./tests/run_sqlcipher_tests.ps1 -Workers 1 -ResultsDirectory $env:TEMP\coach-test-results
```

The serial default is preserved; `-Workers` accepts 1-4, with two as the first
benchmark candidate. Each run owns a unique directory below
`$env:TEMP/ai-coach-tests` (or the supplied parent), with `summary.json`, per-shard
selection/results and logs. Failed, missing, inconsistent or interrupted shards
cannot report complete success. Every class remains in one shard; all selected
IDs must form the complete discovery set exactly once. Compare complete one- and
two-worker runs on the same host, including the additional CPU/memory and summed
runner time, before increasing concurrency.

Coverage is optional. Prepare an offline wheel matching the locked dev pin and
the image's Python/Linux architecture separately; for the default amd64 image:

```powershell
$coverageVersion = (Select-String -Path requirements-dev.txt -Pattern '^coverage==([^ \\]+)').Matches.Groups[1].Value
python -m pip download --only-binary=:all: --no-deps --platform manylinux_2_17_x86_64 --python-version 314 --implementation cp --abi cp314 --dest $env:TEMP\coverage-wheels "coverage==$coverageVersion"
# Pass the downloaded .whl path explicitly:
./tests/run_sqlcipher_tests.ps1 -Workers 2 -CoverageWheel $env:TEMP\coverage-wheels\coverage-<version>-<wheel-tags>.whl
```

The supervisor verifies the wheel hash against `requirements-dev.txt`, installs
it offline into temporary test storage, and combines exactly one independent
coverage file per successful shard. It retains the originals and the combined
`coverage/.coverage`; missing coverage blocks success. No dynamic per-test
coverage contexts are enabled. Duration recording remains a complete, unsharded
operation; `-RecordDurationsDirectory` cannot be combined with multiple workers,
and failed/partial/list runs never overwrite the authoritative recording.

#### Playwright Browser E2E Tests

The shared runner lists the locked Playwright selection and gives every spec its
own disposable SQLCipher fixture. Prepare the locked native browser and build
current application source before running locally:

```powershell
npm ci --ignore-scripts
node node_modules/@playwright/test/cli.js install chromium
docker build -t ai-coach:e2e .
python scripts/run_browser_tests.py --project all --list
python scripts/run_browser_tests.py --project mobile-small --spec e2e/css-cascade.spec.js
python scripts/run_browser_tests.py --project all --jobs 1 --cache-state warm
```

`--list` starts no containers. A project/spec selection reports its focused scope;
unknown projects, missing specs, invalid shards and empty selections fail. Desktop
runs every functional contract, and the four smaller projects repeat only
`@responsive` scenarios. Use `--shard 1 --total 2` and `--shard 2 --total 2` for
complementary whole-file selections. Assignment uses the frozen
`e2e/browser_durations.json` weights, longest first to the least-loaded shard,
with a project's median (one second when unmeasured) for new files. Weights never
exclude tests. Replace weights only from comparable complete per-project records,
including environment/source identity; do not update them during a run.
The current weights are one warm native Windows observation per project, with
source/tool/image provenance in the file; they are not a Linux CI benchmark.

One process is the local default; `--jobs 2` is the bounded concurrency trial.
There is still one Playwright worker per spec. The two prewarm slots per process
have distinct containers, stable networks and loopback ports. Runs use separate
private authentication files and a unique result directory under
`test-results/browser-runs/` (override its parent with `--results-dir`).
`manifest.json` records selection, source, environment, phase times, child exits
and final status. Pending or interrupted records are unverified. Keep private
storage state and traces out of reports; the runner disables traces.
The runner warns when the application image's copy of `requirements.txt`,
`server.py`, `garmin-login.py`, `backend/` or `public/` differs from the working
tree; rebuild it before trusting results. A new `public/` file also needs an
entry in `STATIC_TARGETS` (`backend/http_api/static_assets.py`), which a unit
test enforces. A failed child prints a failing test's location and first error
line; its manifest entry lists all of them under `failures`.

CI builds and shares the current application image once, then starts browser
jobs beside the native suite. Its prepared browser image is pinned by exact
version and digest in `scripts/browser_environment.json`; ordinary matrix jobs
pull that image and install no browser OS packages. The runner checks the locked
package and installed browser revisions before tests. The required `Browser
checks` aggregate rejects failed/missing shards and incomplete or duplicate
selection evidence. Summaries are scoped to the GitHub run attempt; rerun all
jobs to supply a complete matrix rather than rerunning only failed jobs.
Summaries are uploaded separately from failure reports; authentication remains
in private temporary storage.

Prepared browser execution uses Linux host networking. Windows keeps the native
browser path above. On a Linux host, pull the pinned image, then pass it explicitly:

```sh
browser_image="$(python -c "import json; print(json.load(open('scripts/browser_environment.json'))['image'])")"
docker pull "$browser_image"
python scripts/run_browser_tests.py --project desktop --browser-image "$browser_image"
```

When Playwright changes, resolve the matching upstream tag, inspect its digest
with `docker buildx imagetools inspect`, update the pin with the lockfile, and
verify observed browser revisions plus a disposable login/PWA run. A mismatch
fails explicitly. Measure complete cold and warm preparation costs; a warm cache
is not a cold-pull result. To roll back prepared execution locally, omit
`--browser-image` after preparing the locked native browser. CI rollback requires
restoring native browser/system preparation together with that invocation.
Keep the smaller matrix/serial path until measured concurrency gains justify
additional runner-minutes. The full isolated selection can take substantial time
on Docker Desktop; retain its manifest and wait for the terminal result.

Follow the [disposable browser validation notes](.agents/skills/ai-coach-pwa-e2e/references/browser-validation.md)
for manual login, PWA/offline and UI checks. Never target a connected installation.
Direct `npm run test:e2e` remains available for an explicitly prepared fixture;
stateful specs require the shared runner's fresh per-file fixtures.

Configured viewports in `playwright.config.cjs`:
- `mobile-small`: 320x568 (Compact mobile)
- `mobile`: 390x844 (Standard mobile)
- `tablet`: 768x1024 (Tablet portrait)
- `tablet-landscape`: 844x390 (Mobile/tablet landscape)
- `desktop`: 1440x1000 (Desktop workstation)

#### Measuring validation performance

Record performance against a frozen source revision and the same complete test
selection on the same host. Keep focused results separate. Save the revision,
working-tree changes, Python/Node/Docker versions, image identities, CPU/memory
limits, process count, and whether caches were cold, warm, or unknown alongside
start/end timestamps and the process exit code. Store these records outside
athlete storage; never include authentication state, credentials, or traces in
published evidence. An unfinished record is unverified, never a pass.

For Python, measure image build and test execution separately using the full
SQLCipher helper above. For browsers, retain the complete five-project selection
and fresh fixture per spec; measure image transfer/preparation, fixture readiness,
authentication, and execution separately. Do not compare a focused run against a
complete baseline or enable per-test dynamic coverage contexts for routine timing.

For GitHub, measure elapsed time from workflow creation until the required test,
browser, and quality gates finish, excluding review and publication. Report queue
time where available and sum job durations as runner-minutes separately from
wall time. Compare at least five naturally occurring successful runs with
comparable selections and environments before claiming an improved median;
report failed and cold-cache runs separately. Do not dispatch extra workflows
just to populate a benchmark.

The provisional goals for `accelerate-test-execution` are a GitHub validation
median below six minutes and at least 30% less local wall time for each complete
Python and browser selection against its own newly captured baseline. Report
each goal as met, missed, or unverified. Timing goals do not change correctness
results, required checks, assertions, retries, or timeouts.

A same-host complete SQLCipher comparison on 26 October 2026 ran all 7,289
tests exactly once with one and two workers (14 platform skips in each). Warm
whole-run time was 728.71 seconds versus 525.62 seconds, a 27.87% reduction in
one sample. This compares worker counts on the new runner, not a successful
pre-change baseline; browser and hosted improvement goals remain unverified.

#### Standard synthetic preview data

Specialized staging/collision tests use `seed_fixture_planning_calendar(today)`
in a fresh temporary database. It shares the complete seed's planning/calendar
generation and omits unrelated history. `seed_preview_demo()` remains the
complete demo seed used by creation, upgrade, repeated-seed, and restart tests;
startup invokes it only when `FIXTURE_AUTO_SEED=1`.

The disposable fixture runtime exposes `GET /api/fixture/demo` for a reusable,
mobile-safe preview. It seeds profile, check-ins, nutrition, competitions,
library workouts, activity details, recovery, body history, Garmin daily
calories, dated Garmin FTP and Intervals.icu eFTP, calendar marker examples,
and active, archived, component, zero-target, no-target, and over-target gear.
All values are synthetic and providers remain blocked; no credentials or live
athlete data are read. The seed is idempotent and carries a version marker so
an older demo seed is upgraded in place when the disposable database is reused.
Version 6 adds review scenarios on top of the v5 data: a rest day and a sick
day with illness text in the check-ins, a planned 30-minute Swim unit with
planned load next to a 20-minute swim at 11:00 and a fitting 30-minute swim at
18:00 on the same day (activity matching ambiguity), a
`[NO_INTENSITY]` camp day with a hard planned unit, a weekly `[SHORT_ONLY]`
series with a 90-minute ride. Upgrades from v5 add these records once; repeated
seeds and restarts keep the counts stable. The default seed does not add a long
chat history; longer conversations are added on demand for specific scenarios.

`FIXTURE_OPENAI_MODE` controls the simulated OpenAI path. The default
`canned` keeps the canned Coach replies. `offline` makes each Coach
request fail as an unreachable OpenAI endpoint (`network_error`) without any
network call; the simulated failure does not reproduce the original transport
error details. Unknown values stop the fixture at startup. OpenAI stays
deliberately configured with a fake key (`OPENAI_API_KEY="e2e-fixture-openai-key"`)
in every mode, so Coach requests still take the normal Responses API path and no
real credential is needed.

Use a fresh fixture browser profile and check the mobile-small and mobile
projects when reviewing this preview.

`scripts/demo-container.ps1` builds the image and starts a disposable demo
container that seeds this data itself on every start (`FIXTURE_AUTO_SEED=1`).
Restarts keep the seeded data unchanged, including with `-Persist`; the
explicit `GET /api/fixture/features` and `GET /api/fixture/activity` test seeds
add their synthetic activities to the existing snapshot instead of replacing
it. Run it with
`powershell -ExecutionPolicy Bypass -File scripts/demo-container.ps1`; add
`-Persist` to keep the data in a named volume and `-Port`/`-Name` to adjust the
container. `-Name` must start with `demo` or `fixture` (optionally after an
`ai-coach-` prefix); the production container `ai-coach` and every other name are
refused before anything is built, stopped or removed. The fixture refuses to
start unless `AI_COACH_DISPOSABLE_FIXTURE=1` is set; only the demo script and the
CI fixture container set it. The login password is the fixture password
`e2e-fixture-password-1234`. Never point it at a real `/data` directory.

#### Optional local CLIProxyAPI probes

Agents may use the existing [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI)
connection for small manual checks when real model replies, Responses streaming,
or tool-call behavior would help a task. Keep mocked tests and the canned fixture
as the default for repeatable regression and browser checks. These probes are
separate from the fixture; `FIXTURE_OPENAI_MODE` has no live-proxy mode.

The local connection verified on 2026-10-13 was
`http://127.0.0.1:8317/v1`, with `gpt-6-luna` available. The user confirmed
Codex/ChatGPT OAuth routing with paid API-key upstreams and fallbacks disabled.
That setup uses subscription quota rather than OpenAI API credits; it is not
unlimited or offline inference. This authorization permits useful bounded
synthetic probes without asking again while this confirmed setup is unchanged.
Query `/v1/models` for current availability; that endpoint alone does not prove
OAuth-only billing. If there is evidence of changed routing or paid fallbacks,
or routing is unknown for a different connection, stop live probes. If the proxy
is unavailable, or authentication is required without already supplied local
client access, report the limit and continue with mocks. Never read proxy
credential/config files, OAuth tokens, or the application's `.env` to obtain
access. Do not enable paid fallbacks, change provider settings, install another
proxy, or purchase quota as part of a probe.

From the Windows host, this minimal probe uses the verified connection's existing
client access (it accepted requests without a client key). Run only after the
routing check above; choose a model actually listed by `/v1/models`:

```powershell
$proxyBase = 'http://127.0.0.1:8317/v1'
try {
    $proxyModels = Invoke-RestMethod -Uri "$proxyBase/models" -TimeoutSec 10
    if ('gpt-6-luna' -notin $proxyModels.data.id) { throw 'Proxy test model unavailable' }
    $proxyPayload = @{
        model = 'gpt-6-luna'
        instructions = 'Reply exactly PROXY_OK. Synthetic connectivity check.'
        input = 'Connectivity test.'
        reasoning = @{ effort = 'low' }
        max_output_tokens = 256
        store = $false
    } | ConvertTo-Json -Depth 5 -Compress
    $proxyResult = Invoke-RestMethod -Method Post -Uri "$proxyBase/responses" `
        -ContentType 'application/json' -Body $proxyPayload -TimeoutSec 60
    $proxyText = ($proxyResult.output | Where-Object type -eq 'message').content |
        Where-Object type -eq 'output_text' | ForEach-Object text
    [pscustomobject]@{
        Completed = $proxyResult.status -eq 'completed'
        ExpectedReply = (($proxyText -join '').Trim() -eq 'PROXY_OK')
    }
} catch {
    $proxyHttpStatus = if ($_.Exception.Response) {
        [int]$_.Exception.Response.StatusCode
    } else { $null }
    [pscustomobject]@{ Completed = $false; HttpStatus = $proxyHttpStatus }
    throw 'Local proxy probe failed; continue with mocked tests.'
}
```

Send only invented prompts and tool results, never athlete records, attachments,
database contents, credentials, or real provider snapshots. Synthetic tools must
not dispatch app actions or remote writes. Keep any custom probe scripts and
outputs outside tracked source; report only bounded status/shape metadata, model,
and pass/fail. Do not expose raw proxy errors or logs. Stop after the necessary
check rather than running bulk evaluations against subscription quota.

The verified app provider clients accepted JSON Responses, streaming function
calls, and a synthetic tool-result round trip. Full Coach compatibility failed:
`POST /v1/conversations` returned 404, and background Responses creation returned
400. Coach entry still provisions a conversation before inference, including
when its ordinary request later omits the remote conversation field. Recheck
affected capabilities after proxy/app changes; these results do not establish
official API parity. Do not bypass conversation, persistence, approval, or
background-job contracts to make a smoke test pass.

Use host-side provider probes for now. Inside Docker, `127.0.0.1` refers to the
container, and the app rejects plain HTTP to `host.docker.internal`; preserve
the HTTPS/loopback URL guard. This runbook does not reconfigure a connected app
or replace fixture/browser verification.

### Dependency lock maintenance

`requirements.in`, `requirements-dev.in` and `requirements-graphify.in` contain
direct requirements. Their matching `.txt` files are pip-tools outputs with
hashes. Docker and CI install only the app/development locks with `--require-hashes`;
the Graphify lock is used only by its separate shared development environment.
Dependabot recognizes this `.in`/`.txt` pairing and updates both files. When
regenerating locally, use Python 3.14 on Linux (the SQLCipher wheel is not
available on native Windows):

```text
pip-compile --allow-unsafe --generate-hashes --output-file=requirements.txt requirements.in
pip-compile --allow-unsafe --generate-hashes --output-file=requirements-dev.txt requirements-dev.in
pip-compile --allow-unsafe --generate-hashes --strip-extras --output-file=requirements-graphify.txt requirements-graphify.in
```

Compile the Graphify pair on Windows/Python 3.14 instead: a Linux resolution
drops the Windows-only `pywin32` pin that `mcp` needs, and a hash-only Windows
setup then fails. Dependabot regenerates on Linux, so its Graphify PRs fail the
lock contract test until someone runs the Graphify command above on Windows and
pushes the regenerated lock to the PR.

The incremental quality check also records the `ruff` and `mypy` versions in
`tests/fixtures/quality_baseline.json`. After changing either pin, record the new
versions without running the tools, then commit the baseline with the lock files:

```text
python tools/quality_baseline.py --align-versions
```

This changes only the version record. New diagnostics from the newer tool still
fail the check until the code is fixed or the baseline is regenerated on purpose.

### Continuous Integration & Gitar Reviews
- **Conventional Commits**: All commit messages and pull request titles must follow the Conventional Commits specification (e.g., `feat(coach): add structured response support` or `fix(sync): resolve Garmin sleep retry backoff`).

- **Gitar Reviews**: The installed Gitar GitHub App provides the required `Gitar` check for the current PR head. An isolated ruleset requires this context from `gitar-bot` (integration ID `827041`) on `develop` and `main`; Dependabot and the release app are exempt from that ruleset. Default and Main release protection separately require their CI checks and all review conversations to be resolved, including outdated threads. The release app is not exempt from either of those rulesets. Each ruleset also has an existing user-level pull-request bypass. Fix or reconcile findings before resolving threads. Ordinary PR comments have no resolved state: complete their requested action or record an evidence-based disposition before merging. Hosted automatic review settings are managed in Gitar; disable the former automatic Codex review in [Codex Settings](https://chatgpt.com/codex/settings/code-review) if it is still enabled. Local review remains optional additional evidence.
- **Dependency Updates**: Dependabot updates pip, npm, Docker and GitHub Actions on `develop`. Squash auto-merge is enabled for patch, minor and major updates; protected-branch checks and review-thread resolution still apply. The privileged auto-merge workflow never checks out or executes PR code. Dependabot runs receive no secrets, so after each push to `develop` and hourly the auto-rebase workflow uses the trusted `develop` copy of `tools/quality_baseline.py --align-versions` to read open Dependabot PR files as data and commits only the aligned tool-version record through the GitHub App, rejecting the commit if the PR head moved after the reads.
- **Bot direct merge**: The protected bot merge workflow is disabled unless the repository Actions variable `BOT_MERGE_ENABLED` is `true`. Before enabling it, verify release app integration `4772643` cannot bypass any applicable non-Gitar ruleset. Keep its exemption limited to the isolated Gitar ruleset, and verify all normal checks and review-thread requirements remain enforced. Disable the variable before changing rulesets and repeat that verification before re-enabling. The workflow checks out trusted `develop` code, accepts only Dependabot PRs to `develop` or release-app PRs on the expected release branches with auto-merge enabled, and supplies the current head SHA to the squash-merge API. Release PRs also need a successful `test` check from GitHub Actions on the current head or GitHub's current test-merge commit. Relevant events and a twice-hourly schedule retry blocked PRs. A direct app merge was verified on Dependabot PR #1502; negative protection cases have not been tested directly with that app.
- **Automated Daily Releases**: At 03:00 UTC, an automated workflow inspects `develop`. If new commits exist, it creates a version-bump PR and a promotion PR to protected `main`. Both branches require their configured test, quality and browser checks; the release app cannot bypass those requirements. After successful main tests, the workflow creates an immutable GitHub release and publishes the container. The container digest is signed and verified before promoting `latest`; the version tag and `latest` must resolve to that same digest. A read-only release preflight also verifies `APP_VERSION` before its tag exists. Actions use read-only default permissions, with explicit job-level write permissions where needed.

---

## Security Boundaries & Medical Disclaimer

Intervals Coach is a personal athletic planning assistant, not a certified medical device. Training recommendations, adaptive replanning suggestions, and performance analytics are generated by artificial intelligence models and heuristic algorithms. 

Always listen to your body. Do not follow workout intensity or duration recommendations that cause sharp pain, dizziness, or symptoms of overtraining. Consult a certified medical professional or sports physician before undertaking high-intensity endurance training or if recovering from illness or injury.

---

## License

Intervals Coach is open-source software licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**. See [`LICENSE`](LICENSE) for the complete license terms.

### Ernährung und gespeicherte Mahlzeiten

Die Tagesübersicht zeigt neben Kalorien, Kohlenhydraten, Protein und Fett auch aufgenommenen Zucker und Salz in Gramm. Beide Werte werden aus den gespeicherten Produkt- und Lebensmitteldaten mit der verzehrten Menge berechnet; spätere Produktänderungen ändern den Verzehr nicht. Fehlende Angaben bleiben unbekannt, bekannte Teilsummen heißen „unvollständig“. Der Verlauf zeigt Durchschnittswerte für Zucker und Salz mit der Anzahl vollständig erfasster Tage. Das Tagebuch zeigt jedes zusammengesetzte Essen als einen Eintrag; Zutaten lassen sich in der Karte aufklappen. Gespeicherte Produkt- und Datenbank-Snapshots bewahren die verwendete Herkunft auch nach späteren Produktänderungen. Unbekannte Nährwerte bleiben unbekannt und werden in Karten und Tagessummen nicht als Null ausgegeben. Der Eintrag bleibt lokal; eine Synchronisierung nach Intervals.icu erfolgt nur nach ausdrücklicher Freigabe.

Beim Energieverbrauch steht der letzte Garmin-Sync kompakt als **Sync: Datum, Uhrzeit**; ohne Sync-Zeit wird ein vorhandener Abrufzeitpunkt als **Abgerufen** angezeigt. Zutatenquellen zusammengesetzter Mahlzeiten stehen in der aufklappbaren Zutatenliste.

Der Tab **Ernährung** zeigt **Tagebuch**, **Verlauf**, **Body** und **Produkte**. **Verlauf** zeigt wahlweise 14 abgeschlossene Tage oder 12 Wochen bis gestern: den erfassten Kalorienüberschuss oder das Defizit, die durchschnittliche tägliche Kalorienbilanz, durchschnittliche Aufnahme und Garmin-Gesamtverbrauch sowie durchschnittliche Kohlenhydrate, Protein und Fett. Unter den Werten zeigt das Diagramm Aufnahme und Verbrauch als getrennte Balken mit Tageswerten oder Wochendurchschnitten; genaue Tageswerte lassen sich aufklappen. Jeder Durchschnitt nennt die Zahl berücksichtigter Tage. Die Wochenbalken nennen für Aufnahme und Verbrauch jeweils ihre eigene Datenabdeckung; ihre Differenz ist bei unterschiedlicher Abdeckung keine Bilanz. Verbrauch bleibt auch ohne Ernährungstracking sichtbar. Die Bilanz verwendet nur Tage mit Aufnahme und Gesamtverbrauch; bei Lücken ist sie eine Teilbilanz. Makro-Durchschnitte verwenden nur vollständige Angaben je Makro. Fehlende Tage zählen nicht als null; die Aussagekraft hängt von vollständig erfassten Mahlzeiten ab. Erfassung, Korrekturen und Löschen laufen über den Coach per Text, Sprache oder Foto. Aktionen im Tab bereiten eine bearbeitbare Nachricht vor; sie speichern und senden nichts automatisch. Ein vorhandener Chatentwurf bleibt erhalten. Nennst du keine Uhrzeit, speichert der Coach den Eintrag mit „Uhrzeit unbekannt“ und dem Mahlzeitentyp; die Karte zeigt dann nur den Typ statt einer erfundenen Uhrzeit.

Mit "Definiere mein Standardfrühstück" lassen sich wiederverwendbare Mahlzeiten mit Zutaten, Mengen und Nährwerten für eine Portion anlegen. Der Coach zeigt die Vorlage zur Bestätigung, bevor er sie speichert. Eine Vorlage zählt noch nicht als gegessen. "Ich habe eine halbe Portion meines Standardfrühstücks gegessen" erfasst den Verzehr mit entsprechend skalierten Nährwerten. Einmalige Abweichungen verändern nur den Tagebucheintrag; dauerhafte Änderungen verändern die Vorlage und niemals frühere Einträge.

Der Coach bevorzugt **BLS 4.0** für Grundnahrungsmittel und **Open Food Facts** für Markenprodukte und Barcodes; ist **Yazio** eingerichtet, sucht er ohne ausdrückliche Quelle zuerst dort (siehe „Yazio-Produktsuche“). Der Backend-Code berechnet Kalorien und Makros aus den ausgewählten Lebensmittel-IDs und Mengen; Datenbankquelle, Bezugsmenge und Zutatenmengen bleiben im Eintrag und in Mahlzeitvorlagen erhalten und werden im Ernährungstab angezeigt. Die aktuelle OFF-Produkt-API wird über ihre strukturierte Nährwertdarstellung gelesen; automatisch ergänzte OFF-Schätzwerte und Angaben wie „kleiner als“ werden nicht als exakte Etikettwerte übernommen. Rohes und gegartes Gewicht sind nicht austauschbar; Gramm und Milliliter werden nicht ohne Dichte umgerechnet. Mehrdeutige Produkte oder unbekannte Mengen müssen geklärt werden. Ohne passenden Treffer bleiben Verpackungswerte oder ausdrücklich gekennzeichnete KI-Schätzungen möglich. Fehlende Makros und nicht erfasste Tage werden nicht als vollständige Nullwerte dargestellt. Fehlen einzelnen Einträgen Makros, zeigt das Tagebuch die Summe der bekannten Werte als „unvollständig“ und nennt die Zahl der betroffenen Einträge; Freigabevorschau und Coach-Kontext verwenden weiterhin nur vollständige Tagessummen. Die Synchronisierung sendet Kalorien und die bekannten Makros, markiert den Tag als synchronisiert und löscht unbekannte Makros auf Intervals.icu (Wert -1), damit dort kein früherer Wert stehen bleibt; ergänzt eine spätere Änderung die fehlenden Makros, wird der Tag erneut synchronisiert.

**Zugang und Limits:** BLS ist als lokaler Datensatz eingebunden und funktioniert ohne API-Key, Konto oder laufende API-Abfragen. Open Food Facts benötigt für Lesezugriffe keinen API-Key; die Anwendung identifiziert sich mit einem User-Agent. Die aktuell dokumentierten IP-Limits sind 15 Produktabfragen und 10 Suchabfragen pro Minute. Die Anwendung begrenzt sich auf 14 bzw. 9 Abfragen pro Minute, speichert Antworten maximal 24 Stunden im begrenzten Arbeitsspeicher-Cache und pausiert bei 429/503. Andere Anwendungen hinter derselben öffentlichen IP teilen sich die Anbieterlimits. Keine Suche bei jedem Tastendruck. An Open Food Facts gehen nur Suchbegriffe/Barcodes für Lebensmittel, keine Mahlzeitmengen, Fotos, Profile oder Chatverläufe; der Anbieter sieht die Server-IP. Bei Ausfall oder Limit wird kein erfundener Datenbankwert verwendet.

**Datenquellen:** Max Rubner-Institut (2025): *Bundeslebensmittelschlüssel (BLS), Version 4.0 — Deutsche Nährstoffdatenbank*, Karlsruhe, [DOI 10.25826/Data20251217-134202-0](https://doi.org/10.25826/Data20251217-134202-0), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.de). Die eingebundene Ableitung enthält Lebensmittelbezeichnung, Energie, Kohlenhydrate, Protein, Fett und Datenherkunft pro 100 g essbarem Anteil; fehlende Werte, Spuren und Angaben unter der Nachweisgrenze bleiben unbekannt. Reproduzierbare Extraktion: `python tools/extract_bls.py <BLS_4_0_2025_DE.zip>` mit dem [offiziellen Download](https://www.blsdb.de/download). Open Food Facts: [Datenbank unter ODbL 1.0, Inhalte unter Database Contents License](https://openfoodfacts.github.io/openfoodfacts-server/api/); gemeinschaftlich gepflegte Produktwerte sind auf Produkt, Einheit und Vollständigkeit zu prüfen. BLS-Daten und OFF-Cache bleiben getrennt. Es werden keine Produktdaten oder Bilder zu Open Food Facts hochgeladen.

Ernährungseinträge bleiben lokal; eine Übertragung der Tagessummen zu Intervals.icu erfolgt nur nach explizitem Auftrag und Freigabe. Vorlagen und Quellenangaben gehören zu Datenschutzexport, verschlüsseltem Backup und der Löschkategorie Ernährung.

Garmins Tagesverbrauch (für heute vorläufig) mit Aktivkalorien und Grundumsatz wird für das ausgewählte Tagebuchdatum getrennt von der erfassten Nahrungsaufnahme angezeigt. Datum, Quelle und Aktualität bleiben sichtbar; Werte für heute sind vorläufig, solange Garmins Tagesdatensatz noch ergänzt wird. Fehlende Komponenten bleiben unbekannt und werden nicht zu einem erfundenen Gesamtwert addiert. Garmins eigener Tagesverbrauchs-Prognosewert ist über die API nicht abrufbar; für heute zeigt die App deshalb zusätzlich eine klar als „Prognose Tagesverbrauch (abgeleitet)“ gekennzeichnete eigene Schätzung: Grundumsatz des letzten abgeschlossenen Tages (höchstens sieben Tage zurück) plus die bisherigen Aktivkalorien, mit sichtbarer Rechnung. Sie weicht typischerweise um wenige kcal von Garmin Connect ab und entfällt, wenn Aktivkalorien oder ein plausibler Referenztag fehlen.

### Analysis history

The **Analyse** tab has four sections: Belastung, Leistung, Erholung and Einheiten. Belastung shows one Garmin Connect acute-load chart, with the latest 14 daily readings or twelve calendar weeks (last valid reading per week, including the current week), and a separate session-RPE load chart (AU, daily or weekly sums of rated sessions) with the share of rated sessions. Garmin training status is imported for the configured sync window; missing or ambiguous device readings stay unknown. Coach context also keeps Garmin's current daily acute and chronic load and the reported acute-to-chronic ratio separate from its four-week aerobic-low, aerobic-high and anaerobic balance values and target ranges. These values retain Garmin provenance and freshness; ambiguous device values and missing fields stay unknown, and they are not combined with Intervals.icu load. Training focus follows the period selection (14 days or 12 weeks) placed above it, then permanently visible HF and power zone diagrams. Focus groups recorded Garmin activity loads by primary Training Effect, read from the stored Garmin activity records (the upgrade re-projects older records once), rather than deriving categories from zones. Zones sum recorded sport-specific durations across all sports over the selected training-focus period; missing measurements are not zero. The Woche section and its cumulative Intervals.icu load charts are removed. Leistung starts with one maximum-heart-rate row above compact current performance tables for running and cycling, showing metric names and values without source or measurement-date labels. Cycling includes the latest Garmin FTP power-to-weight value, or the latest Intervals.icu eFTP value when no Garmin value exists. The endurance score follows the current values as a Garmin weekly history, including groupMap/groupAverage range responses. Below it are separate running and cycling charts for threshold pace, FTP/eFTP and VO2max over twelve calendar weeks. FTP keeps every dated Garmin daily measurement, including multiple measurements in a week. Threshold pace uses the last valid weekly measurement; eFTP and VO2max use weekly medians. Every measured week has a point, including unchanged values; missing weeks remain gaps. A chart without any valid value is not drawn; each section names such charts in one line "Keine Daten: …", sport groups without history are omitted, and current-value rows without a value are hidden (a single measured value keeps its note that no trend exists yet). Race predictions appear only in a compact distance/time table within the running section. A compact cycling power profile shows the best measured average watts over 5 seconds, 1 minute, 5 minutes, 20 minutes and 1 hour from the last 90 days, combining outdoor and indoor rides in one value per duration. Normal Intervals.icu activity and performance syncs import measured activity power curves, so the table does not depend on manually opening activity details; locally stored full-resolution streams of any provider (Intervals.icu, Wahoo FIT) also contribute, while downsampled Garmin streams never do. Provider failures preserve dated cached values and are reported as failed. These are observations, not forecasts; missing durations stay unknown. Cycling power-to-weight appears only in the current cycling table; running tolerance belongs to running development. Current values, both sport-development groups and other performance sections can be collapsed independently; race predictions collapse with running and the power profile with cycling. Endurance-efficiency cards, best activity windows and race-prediction history charts are removed. Weekly axes display DD.MM dates. Acute load and training time use bars with connected points at their tops. Every measured point has a value label, including repeated values; labels move vertically to avoid collisions. Erholung shows daily sleep, HRV and resting heart rate over the last fourteen days, with an optional twelve-week weekly-average view. Einheiten lists completed sessions newest first (20 per page, with a load-more button) without a calendar date grid. Expanding a session shows its key figures, Garmin Connect-style area charts for heart rate, pace or speed, power, cadence, elevation and temperature with a dashed average line and tap/drag readout (elevation instead shows its full minimum–maximum range without an average line), recorded HF and power zone times labelled with their provider, and laps. Walking and hiking use pace like running. Pace sports invert the pace axis; other ranges ignore the outer one percent of samples so single spikes do not flatten a curve, only non-negative channels start at zero, and stops or missing samples stay gaps. Simplified charts and per-channel data coverage are disclosed below the charts. Running, walking and hiking show step frequency (both legs, spm), twice the per-leg cadence Intervals.icu stores; other sports keep per-leg cadence in rpm. Charts need locally stored activity details. After each Intervals.icu refresh the details of the ten newest activities are loaded read-only when missing or outdated; an activity with invalid or missing data is skipped but stays listed, marked "Details nicht geladen" with a fixed reason that its expanded panel repeats with the attempt time; it is not retried automatically until its summary changes, and loading it explicitly clears the marker. A rate limit, outage or authentication failure stops that run until the next refresh. Older details stay stored and are never evicted. For other sessions the summary is shown, and each configured provider of the session that can load details (Intervals.icu, Garmin Connect) offers its own explicit detail-loading action. Load time, a changed summary, a failed load and data coverage are noted per provider; while any provider's details are outdated, the session analysis is withheld.

When the athlete changes weight or body fat in **More ? Profile**, saving also attempts to send both saved values as one dated Garmin body-composition entry. Both values must be valid and Garmin must be connected. The profile is saved locally even when Garmin is unavailable or rejects the entry; an uncertain outcome is reported without automatic retry and the athlete should check Garmin before trying again. For a known unavailable or rejected upload, the profile offers an explicit retry. A concurrent profile change may supersede a pending upload. If Garmin remains busy or authentication takes too long, the upload does not start later. Coach updates and undo do not send entries to Garmin.

The **Body** section under **Nutrition** starts with a two-row table labelled "Körperwerte". Weight and, when no profile value is set, body fat show the latest Garmin Connect measurement and date. A body fat value entered in the profile takes precedence and is labelled "Profil"; it has no measurement date and does not add a point to the history chart. The history charts use Garmin Connect observations only. Cycling power-to-weight appears as one value in the current cycling table in **Performance**, using Garmin FTP or Intervals.icu eFTP divided by a measured weight from the preceding seven days. Body offers the latest 14 days or twelve rolling weeks. Independently of that selection, the power-to-weight value in Performance shows the latest Garmin FTP quotient from twelve rolling weeks, even when a newer Intervals.icu eFTP quotient exists, and uses the latest eFTP quotient only when no Garmin quotient is available. There is no power-to-weight chart. Weekly points use the median of dated readings. Observation dates remain available, and W/kg values keep FTP/eFTP and weight provenance separate. Unmeasured dates and weeks remain gaps; profile values do not fill missing observations.

Erholung shows the latest fourteen days including today without a period selector, using three aligned charts with independent scales for sleep duration, nightly HRV and resting heart rate. Daily sleep is shown as bars starting at zero, with an average line; hours are formatted as hours and minutes. HRV and resting heart rate show the quartile range of the athlete's own earlier values (42 days, per source) only when at least 14 comparable earlier measurements exist; provisional ranges and insufficient or stale comparisons remain explicit. A change of measuring device, firmware, algorithm, sensor, window, protocol or method restarts the comparison with the values since that change; the info names the change date, or "Messkontext unbekannt" when the provider reports no device model. Every day retains its original observation; missing days remain gaps, and no missing measurement counts as zero. Each metric uses one source and measurement method: the freshest series wins, with Intervals.icu preferred on equal dates and Garmin used when fresher or unavailable from Intervals.icu. Current recovery values and the comparison ranges are read from stored canonical observations only; a value that exists only in a raw provider payload is not shown. Garmin's weekly HRV average is shown as the current HRV only when no last-night HRV exists, labelled "Garmin Connect (Wochenmittel)" and without a 7-day average. Sources, measurement dates and coverage remain available in tooltips; tap or keyboard-activate a day for details, or open the original-value table. Chart legends show only metric names. Values, dates, sources, coverage, changes and explanatory notes are available in legend and point tooltips; expandable tables retain the original values. The comparison range is a neutral background band. Recovery bands update with new observations; load and performance charts do not show comparison bands. Mixed-unit secondary axes have been removed. A position outside the range, a deviation from earlier values and a positive TSB are neither a medical statement nor a training clearance.

Charts preserve provider provenance and observation dates. Garmin performance metrics have no Intervals.icu fallback; eFTP uses Intervals.icu estimates and never manually configured FTP. Numeric labels are reduced when they would overlap, without removing data points. Tap a day or open Werte ansehen for complete values. Sleep shows minimum and maximum below the plot and its average beside the dashed line. HRV and resting-heart-rate comparison bands use earlier 42-day matching measurements, with at least fourteen observations (provisional below 28). These thresholds are product rules. The band holds the middle half of the athlete's own earlier values, so a value outside it is neither rare nor abnormal; it is not a normal range or a medical or sport-wide target. Where Garmin provides them, the Erholung tab also shows dated training readiness as its first chart; weekly training load is the acute-load chart in the Belastung tab. Missing values remain gaps. Historical availability depends on the sync window. Charts are read-only and never trigger provider requests.

### Aktivitätsdetails

Unter **Geplant → Übersicht** öffnet „Aktivität analysieren“ eine absolvierte
Einheit mit ihren lokal gespeicherten Messreihen und Intervallen. Jede
Intervals.icu-Aktualisierung lädt die Details aller neuen Aktivitäten
automatisch und nur lesend nach und speichert sie dauerhaft im kanonischen
Datenmodell. Als neu gilt jede Einheit ab der ältesten der zehn neuesten
Aktivitäten beim ersten automatischen Laden; ältere Einheiten werden nicht
automatisch nachgeladen. Das Startdatum lässt sich unter Mehr › Anbindungen bei
Intervals.icu-Aktivitätsdetails („Laden ab“) auf einen Tag setzen; bereits
gespeicherte Details bleiben unverändert. Pro Aktualisierung lädt die App höchstens 25 Einheiten,
die neuesten zuerst; übrige folgen bei der nächsten Aktualisierung. Bleiben die
Daten einer Einheit dabei aus, steht sie
trotzdem in der Liste und nennt den Grund, ohne bis zur nächsten Änderung
ihrer Zusammenfassung erneut automatisch geladen zu werden; für ältere Einheiten startet „Detaildaten
laden“ ausdrücklich einen Hintergrundjob mit ausschließlich lesenden Abfragen
beim jeweiligen Anbieter. Die Aktion erscheint je Anbieter der Einheit, der
Details laden kann (Intervals.icu, Garmin Connect) und eingerichtet ist; ohne
eingerichtete Intervals.icu-Anbindung verweist stattdessen ein Hinweis auf
Mehr › Anbindungen. Ladezeit, geänderte Zusammenfassung, Ladefehler und
Datenabdeckung werden je Anbieter genannt; solange Details eines Anbieters
veraltet sind, entfällt die Sitzungsanalyse.
Solange Zugangsdaten fehlen, zeigt ein Einrichtungshinweis auf allen Tabs
einen Link zu Mehr › Anbindungen; er lässt sich für die Browsersitzung
ausblenden. Der vorherige Detailstand bleibt bei Fehlern erhalten;
normale Synchronisierungen ersetzen ihn nicht. Fehlende Sensorwerte bleiben
als Datenlücken sichtbar. Diagramme und Coach-Kontext zeigen höchstens 2.000
Punkte je Messreihe; gespeichert werden die vollständigen Reihen bis zur
unterstützten Grenze von 172.800 Punkten und 24 MiB je Aktivität.
„Mit dem Coach besprechen“ bereitet einen sichtbaren, bearbeitbaren Entwurf vor.

Equipment and maintenance has its own More section, separate from Profile. Coach-managed local equipment records are authoritative for lifecycle actions, including assignment, maintenance, archive and restore; archived items are kept in collapsed archive groups. Garmin inventory and per-item statistics supply linked usage readings and status context without taking over the local lifecycle. The Garmin sync also reads, per gear item and read-only, the activities Garmin lists for it (up to 1000, stored as `activity_ids` with the gear item in the Garmin gear rows; an item with more Garmin activities links only the 1000 Garmin returns. A failed or unsupported read keeps the item's last known list, marked stale; without one, the item links nothing, which means unknown rather than empty). While an item's list is truncated or stale, maintenance intervals counted from its sessions, which are hours and a component's distance, show partial coverage and no not-due result; a Garmin item's distance interval still uses Garmin's own total. The equipment read lists at most 2000 assignments, explicit ones first, but usage counts all of them. Those Garmin activities are matched to Intervals.icu activities through the stored activity matches and through an Intervals.icu `external_id` equal to the Garmin activity id, and count as sessions and hours of the Garmin-linked main item without a manual assignment, once per session after duplicate removal and without a sport check. An activity Garmin lists for several main items, for example a bike and a power meter, links to each of them, as in Garmin's own totals. An explicit assignment, including an explicit unassignment, always overrides every Garmin link of that activity. Garmin mileage still comes from the Garmin inventory total. A still-open imported item the athlete has not saved and that has no components takes the sport that at least three quarters of all its linked activities, unknown types included, and at least three of them name; an athlete-chosen or earlier sport is never replaced, and an item with components or an ambiguous mix stays open. Garmin's `maximumMeters` is a lifetime target used for target/progress display, not additional distance: it is never added to Garmin's usage counter or assigned activity distances. A progress bar appears only when a valid target is known. Failed Garmin reads retain the last successful inventory, while a successful empty inventory clears the mirrored Garmin list.

Calendar cards include a compact interval profile when explicit timed workout steps or current locally cached original samples are available. Width represents time, height represents intensity, and known zones supply colors. Recorded sample gaps remain empty; stale detail profiles are excluded. Zone limits follow the canonical zone configurations of the unit's sport (3 to 7 zones; indoor and virtual units use an indoor configuration when one exists) and fall back to the standard limits. Per metric, local zones valid on the unit's day win over the Intervals.icu sport settings; a sport without any canonical configuration still reads the synced sport settings. Absolute watt or bpm targets are colored as an estimate from the sport's FTP or LTHR and the card says so; without that threshold they use neutral colors. No provider requests are triggered by rendering the calendar.

Die Ernährungsnavigation enthält Tagebuch, Verlauf, Body und Produkte. Der Verlauf zeigt 14 abgeschlossene Tage oder 12 Wochen bis gestern, mit Tageswerten beziehungsweise Wochendurchschnitten im Diagramm und einer aufklappbaren Tageswerttabelle. Fehlende Werte bleiben unbekannt; Summen und Durchschnitte nennen ihre Datenabdeckung. Body ist aus Analyse in den Ernährungsbereich verschoben. Das Erfassen eines lokalen Produkts erstellt einen bearbeitbaren Coach-Entwurf; es wird nichts automatisch gesendet oder gespeichert. Coach-Anfragen bleiben über die Hauptnavigation verfügbar.

Unter Profil → „Zonen & Schwellen“ lassen sich lokale Zonen für Radfahren, Laufen und Schwimmen je Messgröße (Leistung in % der FTP, Herzfrequenz in bpm mit LTHR und Maximum, Pace in % der Schwellenpace) und optional nur für Indoor-Einheiten speichern (`GET /api/zones`, `PUT /api/zones`). Die Werte des Anbieters bleiben daneben sichtbar; lokale Zonen gelten vorrangig, bleiben bei jeder Synchronisation, nach Neustart und Backup-Wiederherstellung erhalten und werden nie zu Intervals.icu übertragen. Der Coach sieht die jeweils geltenden Zonen mit ihrer Quelle. Ungültige Eingaben (zu wenige oder nicht aufsteigende Grenzen, unbekannte Einheiten) ändern nichts. Speichern und das bestätigte Entfernen (`PUT /api/zones/remove`) zeigen eine Quittung mit „Rückgängig“.

Trainingsverpflegung hat keine eigene Anzeige, API oder Coach-Aktion mehr. Die lokale Änderungshistorie erscheint ebenfalls nicht als eigene Ansicht; Aufzeichnung und Coach-Undo bleiben erhalten. Unter einer Coach-Antwort, die lokale Daten geändert hat, steht „Geändert: …“. Wenn die Antwort nur Profil, Wettkämpfe, Trainingsvorlagen oder Aktivitätsfeedback geändert hat, deren Änderungen vollständig im Verlauf erfasst sind, nimmt „Rückgängig“ nach Bestätigung alle zusammen in einer Transaktion zurück; wurde ein Datensatz danach weiter geändert, bleibt alles unverändert. Intervals.icu und Garmin werden dabei nicht verändert. Der Diagnoseexport enthält weiterhin technische Ereignisse und Coach-Befehlsstatus sowie die Anzahl gespeicherter Änderungen, ohne deren Athleteninhalte offenzulegen.

#### Lokale Produktdatenbank (Spiegel)

Jedes Open-Food-Facts-Produkt, das die App online abruft, wird automatisch und
dauerhaft in der lokalen Datenbank gespeichert (Tabelle `food_database_entries`,
Schema v11, seit v14 auch Yazio, getrennt von den eigenen Produkten). Abfragen lesen erst die
eigenen Produkte, dann diesen Spiegel und fragen Open Food Facts nur ab, wenn
ein Treffer fehlt oder älter als 90 Tage ist. Ist der Online-Abruf nicht
möglich, wird der gespeicherte Stand mit Datum („Stand vom …“) verwendet.
Treffer tragen für den Coach die Herkunft `data_origin` (`live`,
`local_database`, `local_database_stale`). Im Tab „Produkte“ listet der Abschnitt
„Datenbank“ die gespeicherten Einträge; „Lokal speichern“ übernimmt einen
Eintrag nach Prüfung als eigenes Produkt, „Aus Datenbank entfernen“ löscht nur
den Spiegeleintrag. Der Spiegel gehört zu Backup, Export und Datenlöschung. Das
Bereits ab Schema v16 ist diese Tabelle vorhanden und bleibt beim Upgrade erhalten.

#### Yazio-Produktsuche (optional)

Unter **Mehr > Anbindungen** prüft „Verbindung prüfen“ die Anmeldung ausdrücklich. Der Status zeigt das letzte Prüfergebnis und seine Zeit; nach Neustart oder Änderung der Zugangsdaten ist eine neue Prüfung nötig. Abgelehnte Anmeldungen können Konto- oder App-Zugangsdaten betreffen; die genaue Ursache ist nicht immer bekannt. Bei Begrenzung oder Ausfall später erneut versuchen. Das Laden des Status stellt keine Anfrage an Yazio.

Mit eingerichteten Yazio-Zugangsdaten (`YAZIO_*` oder **Mehr > Anbindungen >
Zugangsdaten**) gilt für Produktsuchen ohne ausdrückliche Quelle diese
Reihenfolge: eigene gespeicherte Produkte, lokale Datenbank (Spiegel), Yazio,
Open Food Facts, BLS. Die nächste Quelle wird gefragt, wenn die vorherige
keinen passenden Treffer hat (jedes Suchwort im Namen, bekannter Kalorienwert),
nicht erreichbar ist oder ihr Limit erreicht hat; ein Treffer in einer früheren
Quelle verhindert alle externen Anfragen. Barcodes laufen über Spiegel, Yazio
und Open Food Facts. Ohne Yazio-Zugangsdaten bleibt es bei eigenen Produkten und
BLS, Open Food Facts nur auf ausdrückliche Anfrage; mit Yazio werden Suchbegriffe ohne Quellenangabe also auch an Yazio und Open Food Facts gesendet. Der Coach kann `yazio` auch
als ausdrückliche Quelle nennen.

Yazio-Treffer tragen die Quelle „Yazio“, Werte pro 100 g oder 100 ml und, wo
Yazio sie liefert, Portionsangaben. Sie werden wie Open-Food-Facts-Treffer im
lokalen Spiegel gespeichert (Schema v14) und können nach Prüfung als eigenes
Produkt gespeichert werden. Es gibt keine Tagebuch-Synchronisierung und keine
Schreibzugriffe auf Yazio. An Yazio gehen nur das Konto (Anmeldung), Suchbegriffe
und Barcodes; Zugangsdaten und Tokens erscheinen nicht in Logs, Diagnose, Export
oder Coach-Kontext, Tokens bleiben im Arbeitsspeicher. Anfragen sind begrenzt
(10 s Zeitlimit, 20 Anfragen pro Minute, 24 h Zwischenspeicher, Pause bei 429;
nach abgelehnter Anmeldung 15 Minuten keine weiteren Anmeldeversuche).

**Bekannte Einschränkungen:** Die Schnittstelle ist inoffiziell und nicht
dokumentiert ([Spezifikation der Community](https://yazio-community.github.io/yazio-api-specification/),
[öffentliche Beschreibung](https://saganos.github.io/yazio_public_api/)); sie kann
sich ohne Ankündigung ändern oder die Nutzung blockieren. Sie benötigt die
Client-ID und das Client-Secret der Yazio-App sowie eine bekannte App-Version im
User-Agent, die du selbst bereitstellst. Die Nährwerte werden als Werte pro
Gramm beziehungsweise Milliliter (Suchparameter: Region aus `YAZIO_COUNTRY`, fest `sex=male`, ohne Einfluss auf die Nährwerte) gelesen und mit 100 multipliziert; unplausible
Werte bleiben unbekannt. Diese Annahme ist nur mit synthetischen Fixtures
getestet, nicht mit einem echten Konto. Prüfe Treffer vor dem Speichern.

#### Lokale Produkte und Verpackungsfotos

Die Ernährungsbibliothek speichert bestätigte Einzelprodukte getrennt von
Mahlzeitvorlagen und Tagebucheinträgen. Ein Barcode sucht zuerst in dieser
lokalen Produktbibliothek und verwendet Open Food Facts nur als Fallback.
Beschreibt der Athlet eine Mahlzeit mit Zutaten und Mengen, gleicht der Coach
jede Zutat zuerst mit den gespeicherten Produkten ab und nutzt passende
Produkte mit ihrer ID; die Textsuche findet ein Produkt, wenn jedes Suchwort in
Name oder Marke vorkommt (`%` und `_` zählen wörtlich; Wörter mit weniger als
drei Zeichen müssen ein Wort beginnen, damit „Ei“ nicht „Reisnudeln“ findet; Satzzeichen wie Kommas oder Klammern um ein Wort werden ignoriert). Findet
diese Suche nichts, prüft sie die 100 zuletzt geänderten Produkte erneut ohne
Groß-/Kleinschreibung und Umlaute, mit Pluralformen und einem Tippfehler
(„Champignons“ findet „Champignon“, „zuccini“ findet „Zucchini“); auch dann muss
jedes Suchwort passen. Erst für Zutaten ohne passendes Produkt fragt er BLS
oder Open Food Facts ab. Die BLS-Suche toleriert ebenfalls Pluralformen,
Tippfehler und „Soße“/„Sauce“; ganze Wörter und Wortenden ranken vor
Wortanfängen, damit „Reis“ Reis statt „Erdbeereis“ liefert. Enthält kein Eintrag
alle Suchwörter, liefert sie Teiltreffer aus den bekannten Wortteilen
(„Risottoreis“ findet Reis und Risotto) und kennzeichnet sie als solche; auch dann liefert die Suche passende
gespeicherte Produkte mit, auch wenn die externe Datenbank nicht erreichbar ist
oder die Anfrage ablehnt. Alle Zutaten einer Mahlzeit werden in einer Suche
abgefragt (höchstens 20 Begriffe); ein fehlgeschlagener Begriff lässt die
Treffer der übrigen nutzbar. Der Coach speichert die Mahlzeit danach direkt mit
allen Komponenten, ohne vorherige Nährwertvorschau; das Speichern berechnet und
nennt die Summen. Erreicht eine Antwort das Schrittlimit, sagt der Coach, was
erledigt ist und was nicht; „weiter“ setzt den Auftrag mit den bereits
gefundenen Lebensmittel-IDs fort. Ein
Treffer aus einer Onlinequelle wird erst nach Prüfung und ausdrücklicher
Bestätigung lokal gespeichert; BLS, Open Food Facts, Verpackungsangabe und
Das Modell kennt die Quellenkennzeichnung `fddb_export`, aber es gibt keinen
FDDB-Importworkflow. Eine Live-FDDB-Anbindung und der Wrapper
[itobey/fddb-exporter](https://github.com/itobey/fddb-exporter) sind derzeit
nicht integriert: Der Wrapper exportiert ein bestehendes FDDB-Tagebuch in
MongoDB/InfluxDB und ist keine produktbezogene Lookup-API. Die Nährwerte werden immer mit
Bezugsmenge und Einheit gespeichert. Gramm und Milliliter werden ohne bekannte
Dichte nicht ineinander umgerechnet.

Beim Barcode-Treffer erscheint das Produktformular direkt darunter. Verfügbare Angaben zu Zucker, Ballaststoffen und Salz werden übernommen; fehlende Werte bleiben leer. Erst das Speichern legt das Produkt lokal an.

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

Analyse und Ernährung lassen sich über das Aktualisierungssymbol im jeweiligen Kopfbereich einzeln auffrischen. Analyse lädt für den gewählten Bereich begrenzte Intervals.icu- und Garmin-Daten; Belastung und Erholung verwenden den ausgewählten Zeitraum. Ernährung lädt für Tagebuch oder Verlauf den ausgewählten Tag beziehungsweise Zeitraum, für Body gezielt Garmin-Körperdaten und für Produkte nur lokale Einträge. Dabei wird nichts zu Intervals.icu geschrieben. Laufende Aktualisierungen behalten die angezeigten Werte bei; fehlende Quellen oder unvollständige Aktivitätsfenster werden als Teil-Ergebnis gekennzeichnet.
