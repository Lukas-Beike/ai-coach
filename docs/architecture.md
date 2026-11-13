# Architecture

`server.py` is the composition root: it reads the configuration, builds the one application context (`backend/app/context.py`, typed, with live `config` and `database` holders that a credential save or a restore replaces) and runs the lifecycle (startup, workers, shutdown). Each domain's builder (`backend/<domain>/wiring.py`) constructs that domain's services from the context; the HTTP server class is `backend/http_api/server.py`. Business logic lives in `backend/`; the import contract is layered. `canonical` imports only the standard library and itself, `athlete` imports no other domain package, `providers` may import only `canonical`, configuration, errors, observability and the runtime clock, ports and socket deadline, and package import cycles are not allowed. `http_api` owns HTTP transport and route assembly, `coach` owns Coach workflows, `sync` owns synchronization and scheduling, `providers` owns external adapters, and `db` owns persistence; the domain packages may import `backend.app` to read the context. AST layer tests enforce a permitted-import map per layer, the empty cycle baseline and these rules.

```text
               +-------------------------------------------------------------+
               |                       Trusted Athlete                       |
               |                (Mobile PWA / Desktop Browser)               |
               +------------------------------+------------------------------+
                                              | HTTPS / SSE
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
|  | server.py (Composition Root: configuration, application context, lifecycle)         |  |
|  +-------------------------------------------+-----------------------------------------+  |
|                                              |                                            |
|                                              v                                            |
|  +-------------------------------------------------------------------------------------+  |
|  | backend/ Domain Layer                                                               |  |
|  |   - backend.app       : The application context the domain builders read            |  |
|  |   - backend.http_api  : HTTP server, routing and request/response transport         |  |
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
|  |   - backend.canonical : Standard-library vocabulary and canonical records           |  |
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
`components.js`, `connection-status.js` (provider status chips),
`status-strip.js` (the one status strip), `format.js` (number, date and
duration formats), `view-refresh.js` (the refresh control of a view),
`provider-connections.js` (credential forms), `provider-checks.js` (explicit
connection checks), `wahoo-connection.js` (the Wahoo connection card), and
`appearance.js`. The service worker owns the offline asset cache.
