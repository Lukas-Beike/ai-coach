# Architecture

`server.py` is the composition root. Business logic lives in `backend/`; the import contract is layered: `athlete` is below `weather`, and `calendar` is below `activities`, which is below `performance`, which is below `planning`. `http_api` owns HTTP transport and route assembly, `coach` owns Coach workflows, `sync` owns synchronization and scheduling, `providers` owns external adapters, and `db` owns persistence. AST layer tests enforce this order.

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
| Pacecraft Container (/app)                                                          |
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
       | HTTPS REST (writes only)       | HTTPS (Garmin, Wahoo)       | HTTPS REST
       v                                v                             v
+------------------+      +-----------------------+      +--------------------+
|  Intervals.icu   |      |  Garmin / Wahoo       |      |  Open-Meteo & ICS  |
|  (output only)   |      |  - Activities, FIT    |      |  - 14-Day Forecast |
|  - Workouts      |      |  - Sleep, HRV, Health |      |  - Air & Pollen    |
|  - Competitions  |      |  - Thresholds         |      |  - Life Calendars  |
|  - Nutrition     |      |  - Strength workouts  |      |                    |
+------------------+      +-----------------------+      +--------------------+
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
`forms.js`, `components.js`, `connection-status.js` (provider status chips),
`status-strip.js` (the one status strip), and
`appearance.js`. The service worker owns the offline asset cache.
