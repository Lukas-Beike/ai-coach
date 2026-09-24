# Plan: server.py vollständig in fachliche Backend-Module aufteilen

Stand: 23.09.2026. P0–P6 integriert; P7–P11 in Arbeit.
Historischer Ausgangscommit: `58e352d`. Die Architekturregel in der
Root-`AGENTS.md` ist integriert. Aktuelle Commits und offene Befunde stehen
im `docs/server-extraction-review-log.md`; das Inventar wird pro Stand erzeugt.

## 1. Ziel und verbindliche Abnahmekriterien

`server.py` wird zum Einstiegspunkt und zur Composition Root: Konfiguration
laden, konkrete Abhängigkeiten zusammenstecken, Anwendung starten und beenden.
Die vollständige Fachlogik einschließlich Use-Case-Orchestrierung erhält einen
klaren Eigentümer unter `backend/`. HTTP bleibt bei `http.server`; ein
Frameworkwechsel oder eine Änderung des Datenmodells ist dafür nicht erforderlich.

Die Aufteilung ist erst abgeschlossen, wenn:

- `server.py` keine Provider-Requests, SQL-Abfragen, Fachvalidierung,
  Kontextprojektion, Coach-Tool-Schleifen, Scheduler-Entscheidungen,
  HTTP-Handler-Implementierung oder fachlichen globalen Zustand mehr enthält.
- Alle ursprünglichen Top-Level-Funktionen, Klassen und relevanten globalen
  Werte im Auslagerungsinventar ein Ziel oder eine begründete Entfernung haben.
- Kein Backend-Modul `server` importiert oder indirekt dessen Namensraum nutzt.
- Keine ausgelagerte Fachfunktion ihre eigentliche Implementierung weiterhin
  als Callback aus `server.py` erhält.
- Keine dauerhaften Re-Exports, Weiterleitungsfunktionen oder Testkompatibilitäts-
  Wrapper in `server.py` verbleiben.
- Die bestehenden API-, Daten-, Berechtigungs-, Streaming- und Provider-Verträge
  durch die jeweiligen Regressionstests abgesichert sind.
- Start, Worker-Lebenszyklus, Backup/Restore und die zentralen Benutzerabläufe
  im isolierten integrierten System erfolgreich geprüft wurden.

Orientierungswert für den verbleibenden Einstiegspunkt: etwa 100–300 gut lesbare
Zeilen. Das ist eine Schätzung, keine Aufforderung, Code zu komprimieren oder
Verdrahtung in einen neuen versteckten Monolithen zu verschieben. Bei mehr als
300 Zeilen wird jede verbliebene Verantwortung geprüft; entscheidend sind die
obigen Kriterien. Die Gesamtzahl der Backend-Zeilen muss durch reine Auslagerung
nicht sinken. Sicherheitsprüfungen und unterstützte Funktionen bleiben erhalten.

## 2. Verifizierter Ausgangszustand

- `server.py`: 21.702 physische Zeilen inklusive Leerzeilen und Kommentaren.
- 1.235 Top-Level-Funktions- und Klassendefinitionen.
- 42 vorhandene Python-Dateien unter `backend/`, einschließlich `__init__.py`.
- `RequestHandler`: Zeilen 20.885–21.562, also 678 Zeilen.
- Vorhandene Modulbereiche: `coach`, `planning`, `sync`, `providers`, `db`,
  `http_api`, `backup` sowie `config.py`.
- Zahlreiche Tests verwenden `patch.object(server, ...)`; die Testabhängigkeiten
  sind deshalb Teil der Migration und kein nachgelagerter Aufräumschritt.
- `backend/planning/changes.py` besitzt bereits eine Transaktionshülle,
  lässt aber Vorbereitung, Validierung und Anwendung über
  `PlanningChangeDependencies` liefern. Diese Schnittstelle muss bis zur
  tatsächlichen fachlichen Eigentümerschaft vervollständigt werden.
- `backend/coach/service.py` enthält bisher Receipt-/Outcome-Helfer, während
  die eigentliche Turn-Ausführung weiterhin in `server.py` liegt.
- Locks, Worker-Events, Stream-Register und Caches sind heute global im Server.
- `package.json` enthält Playwright mit `npm run test:e2e`; die vorhandenen
  Browser- und Accessibility-Prüfungen gehören deshalb zur Validierung der
  HTTP-/PWA-Grenze.

Zeilennummern sind Orientierung am Ausgangscommit. Funktionsnamen und das
Inventar sind nach dem ersten Umzug die maßgebliche Referenz.

## 3. Vollständige Bestandsabdeckung und Zielbereiche

Die folgenden Intervalle decken die gesamte Datei lückenlos ab. Sie sind
Inventarabschnitte, keine Aufforderung, zusammenhängende Zeilen blind zu
verschieben: Innerhalb eines Abschnitts liegen mehrere Verantwortlichkeiten.

| Quellbereich | Enthaltene Verantwortlichkeiten / Anker | Ziele unter `backend/` |
| --- | --- | --- |
| 1–2.999 | Imports, Konfiguration, Konstanten, Events, Gates, Logging, Fehler, DB-Initialisierung, Sync-Jobs, Freshness, Änderungshistorie, Diagnostik | `config.py`, `errors.py`, `observability.py`, `runtime/`, `db/`, `sync/`, `history/`, `settings.py` |
| 3.000–5.799 | Aktivitätsabgleich, Garmin-Metriken und Sync, Profil, Check-ins, Feedback, Wettkampfnormalisierung, Kalenderabruf und iCalendar | `activities/`, `performance/`, `sync/garmin.py`, `athlete/`, `planning/competitions.py`, `providers/calendar.py`, `calendar/` |
| 5.800–8.299 | Tageskontext, Recovery, öffentliche Kalender, Wettkampfänderungen/-Sync, Providerfehler und HTTP, Wetter | `coach/context.py`, `performance/`, `calendar/`, `planning/competitions.py`, `sync/competitions.py`, `providers/`, `weather/` |
| 8.300–10.499 | Compliance, Trainingskalender, Workout-Validierung, Library, Pläne, adaptive Planung, Pagination, Aktivitäten | `planning/`, `activities/`, `http_api/pagination.py`, `providers/workout_text.py` |
| 10.500–12.999 | Kanonische Workouts, Remote-Abgleich/-Schreiben, Library-/Planänderungen, Snapshots, Resync, Intervals-Sync, erste Performance-Aggregate | `planning/`, `sync/`, `db/`, `performance/` |
| 13.000–15.499 | Performance-/Aktivitätsanalyse, Coach-Kontext, Usage, OpenAI/Gemini, Transkription, Streaming, Konversationsverwaltung, Duplikatvorschau | `performance/`, `coach/context.py`, `coach/conversation.py`, `providers/`, `activities/` |
| 15.500–17.499 | Vorschläge und Bestätigung, Coach-Jobs/-Streams, strukturierte Planbefehle, Planvalidierung/-ersatz, Tool-Dispatch | `coach/proposals.py`, `coach/jobs.py`, `coach/streams.py`, `coach/tool_execution.py`, `planning/` |
| 17.500–19.499 | Dialog-Scope, Reparatur-/Replay-Logik, Receipts, Modellrunden, Turn-Ausführung, Coach-Worker | `coach/authorization.py`, `coach/dialogue.py`, `coach/service.py`, `coach/receipts.py`, `coach/jobs.py` |
| 19.500–21.702 | Morning Check-in, öffentliche State-Projektionen, Settings, Diagnostik, Export/Restore/Löschen, Auth, HTTP/SSE, Scheduler, main | `coach/morning.py`, `http_api/`, `settings.py`, `observability.py`, `backup/`, `privacy.py`, `sync/scheduler.py`, `runtime/`; nur Verdrahtung bleibt in `server.py` |

Neue Bereiche werden nur zusammen mit konkreter auszulagernder Implementierung
angelegt. Keine leeren Paketgerüste auf Vorrat. Bestehende passende Module werden
erweitert. Wenn beispielsweise `planning/service.py` selbst zum Sammelbehälter
wächst, wird nach konkreten Aufgaben wie `library`, `calendar`, `changes` und
`adaptive` getrennt, nicht nach beliebigen Zeilenblöcken.

## 4. Abhängigkeiten und Zustand

Die grundsätzliche Aufrufrichtung lautet:

```text
server.py (konkrete Instanzen, Start/Stop)
  -> HTTP-Adapter und Scheduler/Worker-Einstiegspunkte
  -> fachliche Use Cases: Coach, Planung, Sync, Athlet, Kalender, Wetter
  -> Provider-Adapter, Repositories und reine Berechnungen
  -> Standardbibliothek / bestehende Abhängigkeiten
```

- HTTP übersetzt Request/Response und ruft Use Cases auf. Fachmodule erhalten
  keinen `BaseHTTPRequestHandler` und schreiben keine HTTP-Antworten.
- Coach darf Planungs- und Sync-Use-Cases aufrufen. Planung darf nicht zurück in
  Coach importieren. Coach-Autorisierung wird vor Übergabe geprüft; fachliche
  Integrität wird zusätzlich im Planungs-Use-Case geprüft.
- Provider-Adapter besitzen Transport, Parsing und Provider-Protokolle. Sync
  besitzt Zusammenführung, Persistenz und Konfliktbehandlung. Provider importieren
  keine HTTP-Handler, Coach-Services oder Sync-Orchestrierung.
- Repositories erhalten die aktive DB-Verbindung. Der schreibende Use Case
  besitzt die Transaktion; untergeordnete Helfer eröffnen keine unabhängige
  Transaktion für Teile derselben atomaren Änderung.
- Cross-Domain-Abhängigkeiten werden auf konkrete benötigte Operationen begrenzt.
  Keine universelle Service-Registry, kein DI-Framework, kein `globals()`-Proxy
  und kein riesiges Context-Objekt, das jedem Modul die gesamte Anwendung gibt.
- Abhängigkeitsobjekte bleiben auf Infrastruktur beschränkt, wo sie nötig sind:
  DB-Zugang, Provider, Uhr, Event-Publikation. Fachinterne Helfer leben mit ihren
  Aufrufern im verantwortlichen Modul und werden dort direkt verwendet.

| Zustand | Endgültiger Eigentümer und Migrationsbedingung |
| --- | --- |
| DB-Manager, Verbindungszugang, DB-Lock | `db/manager.py`; alle Nutzer teilen den vorgesehenen Manager, keine zweite DB-Instanz durch Imports |
| Maintenance-Gate und Restore-Generation | `runtime/maintenance.py`; Restore und Worker verwenden dieselbe Instanz |
| Provider-Resync-Gates, Sync-Locks, laufende Unit-Syncs | `sync/`; Lock-Reihenfolge und Ausschlussgrenzen vor Umzug erfassen und bewahren |
| State-Events und Sequenznummern | `runtime/events.py`; ein gemeinsamer Strom für Produzenten und SSE-Konsumenten |
| Coach-Conversation-Lock, Queue, Job-Events und Cancellation | `coach/jobs.py` / `coach/conversation.py`; genau ein Eigentümer je Zustand |
| Chat-Stream-Register | `coach/streams.py`; HTTP ist Konsument, Job-Ausführung Produzent |
| Garmin-, Kalender- und Wettercache/-Locks | Jeweiliger Sync-/Fachservice; keine verdoppelten Caches nach dem Import |
| Diagnose-Capture und redigiertes Logging | `observability.py`; vorhandene Redaktions- und Größenlimits erhalten |
| Sessions und Rate-Limit-Zustand | `http_api/auth.py`; bestehende Session- und CSRF-Verträge erhalten |

Imports dürfen keine Worker starten, Provider kontaktieren oder eine Live-DB
öffnen. Ressourcen werden durch explizite Startfunktionen erzeugt und durch die
Composition Root verbunden. Geänderte Shutdown-Pfade müssen Stop-Signale,
laufende Operationen und DB-Zugriff konsistent behandeln; vorhandene Semantik
wird vor einer Verbesserung zunächst dokumentiert und getestet.

## 5. Umsetzung in abhängiger Reihenfolge

Jeder Schritt ist eine fachlich zusammenhängende Änderung mit umgezogenen
Aufrufern und Tests. Große Schritte werden an den genannten Verantwortlichkeiten
in mehrere PRs geteilt. Kein Schritt gilt durch die bloße Existenz einer neuen
Datei als fertig.

### P0 — Inventar, Baseline und Architekturprüfung

- [x] Mit Python-AST sämtliche Top-Level-Definitionen und globale Bindungen
  erfassen. Pro Eintrag Quellname, Ausgangszeile, Zielmodul, Phase und Status
  in `docs/server-extraction-inventory.md` festhalten.
- [x] Referenzen in Backend, Tests, E2E-Fixtures, Skripten, Docker und Workflows
  erfassen; dynamische Zugriffe/Monkeypatches manuell ergänzen.
- [x] Direkte Aufruf-/Importabhängigkeiten und globale Reads/Writes für den
  nächsten Schritt prüfen; zyklische Gruppen als gemeinsame Umzugseinheit
  identifizieren oder an einer konkreten Verantwortungsgrenze auflösen.
- [x] Ausgangstests mit synthetischen Daten ausführen und vorhandene Fehler
  dokumentieren. Keine späteren Regressionen als Altfehler deklarieren.
- [x] Kleine Architekturprüfung mit stdlib `ast` in die bestehenden Tests
  aufnehmen: kein Backend-Import von `server`; bereits ausgelagerte Namen
  dürfen dort nicht wieder als Implementierung auftauchen.
Abnahme: Jeder Inventareintrag ist zugeordnet, Baseline und reproduzierbare
Testbefehle sind erfasst. Reale Secrets oder Athletendaten werden nicht gelesen.

### P1 — Fundament und gemeinsam genutzte Ressourcen

Abhängigkeit: P0.

- [x] `AppError`, Disconnect-Signal und Fehlerabbildung passend zwischen
  `errors.py` und HTTP aufteilen; Konstanten zum jeweiligen Eigentümer ziehen.
- [x] Konfiguration, Settings-Zugriff und Logging/Redaktion auslagern.
  - [x] Anbieter-/Modell-/Thinking-/Kalenderauswahl sowie Secret-/URL-
    Redaktion, JSON-Formatter und Logging-Setup verlagern.
  - [x] Verbleibende Konfigurationsvalidierung, Settings-Dateischreibpfade,
    Provider-Freshness und diagnostische Observability verlagern.
- [x] DB-Initialisierung vervollständigen; Job-Recovery von Schema-Initialisierung
  trennen und aus der Startverdrahtung explizit aufrufen.
- [x] Maintenance-Gate und State-Event-Puffer mit konkreten Instanzen auslagern.
- [x] Release-Verwendung von `APP_VERSION` und statischen Pfaden erfassen;
  den bestehenden Releasevertrag bei einer Verlagerung gleichzeitig anpassen.
  - `APP_VERSION` bleibt bis zu einer gemeinsamen Migration der Release-Quelle,
    des Review-Gates und des Release-Workflows als exakte Zuweisung in
    `server.py`.
  - `PUBLIC_DIR`, die versionierte Asset-Allowlist und `send_static` bleiben bis
    P10 zusammen; Änderungen am PWA-Assetset aktualisieren weiterhin
    `index.html`, Cache-Name und Asset-URLs in `service-worker.js` gemeinsam.

Abnahme: Fachmodule können Fehler, Ressourcen und Events verwenden, ohne
`server` zu importieren. Import-Smoke-Test erzeugt keine Laufzeitaktivitäten.

### P2 — Provider-Transport, Parsing und Modelladapter

Abhängigkeit: P1.

- [x] `http_json`, begrenzte Reads, Providerfehler und sichere HTTP-Aufrufe
  mit `providers/http.py` zusammenführen.
  - [x] Request-Body/-Header-Aufbau, begrenzte Erfolgs-/Fehler-Reads,
    abbrechbares Header-Warten samt Response-Handle-Lifecycle und redigierte
    Providerfehler in reine Adapter verschieben.
  - [x] Begrenzte JSON-Request-Ausführung einschließlich Öffnen, Lesen,
    UTF-8-/JSON-Dekodierung, Status-/Header-Metadaten und Cleanup auslagern.
  - [x] Netzwerk-, Retry-/Cancellation- und Statusorchestrierung vollständig
    aus `server.py` entfernen.
- [x] OpenAI Request/Response, Background Retrieve/Cancel, SSE-Verarbeitung,
  Usage-/Rate-Limit-Auswertung und Audio-Transkription in konkrete Provider-Module
  ziehen. Nutzungs-Persistenz bleibt außerhalb des reinen Transports.
  - [x] Response-/Fehlerparsing, SSE-Ereignisse, Response-ID-, Payload-,
    Rate-Limit-/Usage-Berechnungen und Audio-Wire-Helfer auslagern.
  - [x] Begrenztes SSE-Lesen einschließlich Fragmentgrenzen, finaler Response,
    Abbruchprüfung und Bytefortschritt in den OpenAI-Adapter verschieben.
  - [x] Stream-Transport einschließlich Öffnen, Header-Abbruch, Response-Handle,
    Status-/Header-Metadaten, Größenlimit und Cleanup im OpenAI-Adapter besitzen.
  - [x] Persistierten OpenAI-/Gemini-Status, tägliche Usage und OpenAI-
    Rate-Limits in einem transaktionalen Provider-State-Service besitzen;
    DB-Lock, Manager-Lebenszyklus und redigiertes Logging bleiben eindeutig.
  - [x] Request- und Background-Transport einschließlich Abbruch und Polling
    vollständig im OpenAI-Adapter besitzen.
  - [x] Stream-Request, Conversation-Lock-Retry, Fehler-/Diagnosepfade,
    Cancellation, finale Usage und Rate-Limit-Status vollständig im konkreten
    OpenAI-Stream-Client besitzen; `server.py` routet nur noch.
  - [x] Audio-Validierung, providerabhängige Transkriptionsorchestrierung,
    transiente Base64-/Multipart-Payloads und Response-Prüfung im konkreten
    Audio-Client besitzen; `server.py` komponiert nur noch.
- [x] Gemini Payload-/Tool-Konvertierung und Streaming zum Gemini-Adapter ziehen;
  persistierte Dialoghistorie gehört zu `coach/conversation.py`.
  - [x] Payload-/Tool-/Medienkonvertierung und Stream-Akkumulation auslagern.
  - [x] Stream-Transport einschließlich Header-Abbruch, Response-Handle,
    Größenlimit und SSE-Akkumulation auslagern.
  - [x] Stream-Request, Fehlerklassifizierung, Status-/Usage-Persistenz und
    Cancellation vollständig im konkreten Gemini-Stream-Client besitzen.
  - [x] Persistierte Historie in P7 nach `coach/conversation.py` verschieben.
- [x] Kalenderabruf einschließlich SSRF-Prüfung und iCalendar-Parsing auslagern.
- [x] Vorhandene Garmin-/Intervals-Adapter erweitern, ohne Sync-Use-Cases in
  Provider-Module zu verschieben.

Abnahme: Adaptertests decken Fehler, Timeout, Größenlimits, fragmentiertes SSE,
Abbruch und finale Responses ab. Retry-After, Quota-Unterscheidung und aktuelle
Tokenbudgets bleiben erhalten; Tests verwenden ausschließlich Provider-Fakes.

### P3 — Athlet, Aktivitäten, Performance, Kalender und Wetter

Abhängigkeit: P1; Transportnutzer zusätzlich P2.

- [x] Profil, Check-ins und Aktivitätsfeedback samt Validierung und Persistenz
  in `athlete/` ziehen; vorhandene Repositories wiederverwenden.
  - [x] Profil-/Check-in-/Feedback-Normalisierung sowie Check-in- und
    Feedback-Persistenz besitzen fachliche Module.
  - [x] Profilpersistenz einschließlich History-Writer und
    Wetter-Cache-Invalidierung vollständig aus `server.py` lösen.
- [x] Aktivitätsidentität, Duplikaterkennung und Detailprojektion in `activities/`
  bündeln. Remote-Löschen bleibt ein ausdrücklich autorisierter Use Case.
  - [x] Identität, Duplikaterkennung und Gruppierung paralleler
    Radausfahrten sind ohne Server-Callbacks ausgelagert.
  - [x] Detailprojektion und verbleibende Kalender-/Matching-Helfer zuordnen.
- [x] Garmin-Metriken, Trends, Recovery, Leistungswerte und Aktivitätsvalidierung
  nach `performance/` verschieben; Rohdaten und Quellenlabels erhalten.
  - [x] Beobachtungsfreshness, Aktivitätsvalidierung, Load/ATL,
    Wellness-Vergleiche und 30-Tage-eFTP sind reine Eigentümermodule.
  - [x] Garmin-Metriken, Recovery-, Trend- und Kontextorchestrierung auslagern.
    - [x] Max-HR-Zusammenführung, Freshness, kompakte Garmin-Projektion,
      Gewichtsnormalisierung, Recovery-Datensuche sowie Garmin-/Intervals-
      Trendmittelwerte sind zustandsfreie Eigentümermodule.
    - [x] Garmin-Metriknormalisierung und Daily-Health-Projektion besitzen
      konkrete, zustandsfreie Performance-Module mit explizitem Datum.
    - [x] Verbleibende Performance-/Recovery-Kontextorchestrierung vollständig
      aus `server.py` lösen.
- [x] Externe/öffentliche Kalender und Wetter-Cache/-Projektion auslagern.
- [x] Reine Kontextbausteine von Datenabruf und Synchronisierung trennen.

Abnahme: Quellenpriorität, Messdatum/Freshness, fehlende Werte, Duplikate,
Kalenderrekurrenz und Wetter-Cache-Verhalten sind mit bestehenden bzw.
gezielt ergänzten Fixtures abgesichert.

### P4 — Lokale Planung vollständig besitzen

Abhängigkeit: P1, benötigte Berechnungen aus P3.

- [x] Workout-Normalisierung, Library/Templates, geplante Units, Wettkämpfe,
  Trainingskalender und Compliance in fachliche `planning/`-Module ziehen.
  - [x] Workout-Normalisierung, Text-/Dauerprüfung, Event-Payload und Remote-
    Readback besitzen `planning/workouts.py` ohne Server-Callback.
  - [x] Saisonphasen und kombinierter Planning-State werden rein in
    `planning/season.py` projiziert.
  - [x] Snapshot-, Sport- und lokale Kalenderprojektionen besitzen
    `planning/context.py` mit expliziter Zeit-/Vollsync-Injektion.
  - [x] Wettkampf-Sport-, Payload-, Remote- und Konfliktprojektionen besitzen
    `planning/competitions.py`; der Konfliktzeitpunkt wird explizit injiziert.
  - [x] Kalender-Zeitfenster und Konfliktprojektionen besitzen
    `planning/calendar.py`; DB-, Library- und externe Kalenderquellen bleiben
    explizite Composition-Abhängigkeiten.
  - [x] Library-Identität, Normalisierung, Dauer und konservatives Matching
    besitzen `planning/library.py`; die Kandidatenliste wird explizit
    übergeben.
  - [x] Planned-Unit-Normalisierung, Update- und Remote-Projektionen besitzen
    `planning/planned_units.py`; das aktuelle Datum wird explizit übergeben.
  - [x] Reine Adaptive-/Illness-Projektionen besitzen `planning/adaptive.py`;
    Datum, Grenzwerte und Kalenderkennungen werden explizit injiziert.
  - [x] Library-Bulk-Auswahl und Payload-Hashing besitzen
    `planning/library.py`; Eingabegrenzen, UUID-/Datums-/Hash-Verträge und
    Reihenfolge entsprechen dem bisherigen Verhalten.
  - [x] Reine Wettkampf-Sync-Planung besitzt `planning/competitions.py`;
    Remote-Match-Priorität, Konflikte, Tombstones, Fingerprint und Summary
    werden ohne Provider- oder Datenbankzugriff erzeugt.
  - [x] Lokales Wettkampf-CRUD und Konfliktauflösung besitzen einen
    transaktionalen `CompetitionService`; Audit, Tombstones und lokale
    Änderungen committen oder rollen gemeinsam zurück.
  - [x] Planungsrevisionen besitzen `PlanningRevisionService`; Initialisierung,
    Recovery nach Privacy-Reset und konkurrierende Bumps bleiben unter der
    `DatabaseManager`-Transaktions- und Lockgrenze.
  - [x] Trainingsplan-Metadaten, Status, Bounds und Constraints besitzen einen
    transaktionalen `TrainingPlanService` einschließlich Audit und Events.
  - [x] Strukturierte Artifact-/Change-/Replacement-Vorbereitung sowie
    Planreferenzauflösung besitzen `planning/`-Module ohne Server-Rückimport.
  - [x] Library- und Planned-Unit-Mutationsnormalisierung besitzen ihre
    fachlichen Module; Persistenz-Use-Cases bleiben bis zum Service-Umzug offen.
  - [x] Der tagesbezogene Planning-Read besitzt einen
    `DailyPlanningContextService`; Garmin-/Battery-History, Check-ins,
    relevante externe Termine und Feedback werden über ihre konkreten
    Eigentümer geladen und anschließend rein projiziert.
  - [x] Die kombinierte Kalender-, Compliance-, Wetter- und Parallel-Cycling-
    Projektion besitzt `planning/calendar_read_model.py`; Provider-I/O bleibt
    als explizite Composition-Abhängigkeit außerhalb des Read-Modells.
  - [x] Strukturierte Trainingsplan-Artefakte besitzen einen
    `TrainingPlanArtifactService`; Stage/Commit, Conversation-Bindung,
    Revisions-/Kalenderprüfung, Limits und lokaler Plan-Commit laufen unter
    einer gemeinsamen transaktionalen Eigentümergrenze.
  - [x] Lokale Library-/Template-, Planned-Unit- und Wettkampf-Use-Cases sowie
    Trainingskalender und Compliance vollständig auslagern; Reconciliation,
    Provider-Reads und Remote-Schreiben bleiben explizit P6.
- [x] CRUD, Bounds, Revisionen, Validierung, Planersatz und strukturierte
  Batch-Änderungen einschließlich sämtlicher privater Helfer verschieben.
  - [x] Kalenderkonflikte besitzen einen konkreten `CalendarConflictService`;
    lokale, Library- und externe Quellen bleiben explizite Abhängigkeiten.
  - [x] Der vollständige strukturierte Planning-State-Read einschließlich
    Pagination besitzt einen `StructuredTrainingStateService`.
  - [x] Batch-Datums-, Revisions- und Payload-Hash-Prüfungen besitzen einen
    `StructuredTrainingChangeValidator` innerhalb der Aufrufertransaktion.
  - [x] Lokale Planned-Unit-Erzeugung, generisches transaktionsgebundenes
    Insert und Listing besitzen einen `PlannedUnitService`; Audit,
    Planungsrevision und Sync-Fehler-Redaktion bleiben erhalten.
  - [x] Lokale Library-Erzeugung, Template-Validierung und Listing besitzen
    einen `WorkoutLibraryService`; Transaktions- und historisches
    Korruptionsverhalten bleiben unverändert.
  - [x] Planned-Unit-Update/Archive/Restore/Delete einschließlich
    Kalenderkonflikt, Audit und optionaler Revision sowie Library-
    Update/Archive/Restore/Delete einschließlich Sync-Grenzen liegen in den
    jeweiligen Services; Events werden erst nach erfolgreichem Commit
    publiziert.
  - [x] Lokale Planned-Unit-Konfliktauflösung besitzt der
    `PlannedUnitService`; Keep-local, Remote-Übernahme und persistenter
    Remote-Deletion-Tombstone bleiben transaktional und revisionsgesichert.
  - [x] Das lokale Einplanen von Library-Vorlagen besitzt einen
    `WorkoutLibraryPlanService`; Lookup, vollständige Konfliktprüfung und alle
    Creates bilden einen atomaren Batch mit Event erst nach Commit.
  - [x] Lokale Coach-Planerzeugung besitzt einen
    `LocalTrainingPlanCreationService`; Normalisierung, Kalenderprüfung,
    Template-Wiederverwendung, optionale Planmetadaten, History, Unit-Erzeugung
    und genau ein Revisionsbump liegen in derselben Unit-of-Work.
  - [x] Planned-Unit-/Library-Persistenz, Batch-Apply und Planersatz als
    vollständige Services auslagern und alle zugehörigen Server-Callbacks
    entfernen; Sync-State-/Remote-Persistenz folgt der P6-Grenze.
    `StructuredTrainingChangeService` besitzt Vorbereitung, Validierung,
    Planauflösung, Row-Mutationen, Bounds, Revision und Post-Commit-Event;
    `StructuredTrainingPlanReplacementService` besitzt Auswahl, History-
    Kapazität, Archivierung, Constraints, Neuanlage und Revision in einer
    Unit-of-Work.
- [x] `AdaptiveDependencies` und `PlanningChangeDependencies` entfernen;
  Adaptive Preview und Apply besitzen konkrete Services mit direkten
  Modul-/Repository-Abhängigkeiten statt fachlicher Server-Callbacks.
- [x] Adaptive Vorschau/Apply und Krankheitspausen lokal vollständig zuordnen;
  Remote-Synchronisation bleibt als separater, nachgelagerter Sync-Einstieg
  außerhalb der lokalen Transaktion erhalten.
- [x] Hash-/Revisionsprüfungen, Historieneinträge und Atomarität innerhalb
  derselben Transaktion bewahren.

Abnahme: Vollständiger Planersatz, Teiländerung und Adaptive Apply funktionieren
ohne fachliche Callback-Implementierungen in `server.py`. Fehler in der Mitte
einer Batch-Änderung rollen alle zugehörigen lokalen Änderungen zurück.

### P5 — Änderungshistorie und Undo

Abhängigkeit: P4.

- [x] Projektionen, Hashes, Kapazitätsprüfung und Historienpersistenz zuordnen.
- [x] Undo-Preview und Undo-Apply nach `history/` verschieben; fachliche
  Wiederherstellung nutzt transaktionsfähige Operationen der Domänen.
- [x] Zyklen vermeiden: Domänen dürfen einen kleinen History-Writer verwenden;
  nur der Undo-Orchestrator ruft Domänenoperationen auf, nicht der Writer.
  - [x] `ChangeHistoryService` besitzt Cleanup, Listenprojektion, aktuellen
    lokalen Audit-Zustand und die Rekonstruktion des Undo-Ziels.
  - [x] `HistoryUndoService` besitzt Preview-Hashbindung, atomaren Apply,
    genau einen Undo-Audit-Eintrag und den revisionsgesicherten Dispatch an
    Profil, Wettkampf, Library, Planned Unit und Trainingsplan.
  - [x] Die fünf Domänendienste stellen schmale
    `restore_in_transaction`-Operationen bereit; sie öffnen keine eigene
    Transaktion und schreiben weder Undo-History noch Providerzustand.

Abnahme: Profil-, Wettkampf-, Library- und Plan-Undo behalten Eigentümerprüfung,
Konflikterkennung und Rollback. Keine Rückabhängigkeit auf HTTP oder Coach.

### P6 — Synchronisierung, Reconciliation und Sync-Worker

Abhängigkeit: P2–P5.

- [x] Garmin-, Intervals-, Library-, Planned-Unit- und Wettkampf-Sync mit
  ihren vollständigen Abläufen nach `sync/` ziehen.
  - [x] Wettkampf-Reconciliation, Provider-Orchestrierung, Cleanup und
    gemeinsamer Single-flight-Lock liegen vollständig in `sync/competitions.py`.
  - [x] Remote-Planned-Unit-Import einschließlich Konflikten, Missing-State,
    CAS und gemeinsamer Revision liegt in `sync/planned_units.py`.
  - [x] Einzelne Workout-Library-Remote-Mutation, initialer Read-Refresh,
    lokaler Remote-Read-Reconcile und ihr gemeinsamer Lock liegen vollständig
    in `sync/library.py`; der Selected-Batch liegt mit Hash-/Konfliktprüfung,
    Repair-Verifikation und denselben Resync-/Single-flight-Grenzen in
    `sync/selected.py`.
  - [x] Der normale Planned-Unit-Kalender-Push liegt einschließlich
    Remote-Readback, Löschung und per-ID-Lock in `sync/planned_calendar.py`.
  - [x] Den Planned-Unit-Repair-Batch vollständig auslagern; er muss denselben
    per-ID-Lock wie der normale Push verwenden.
  - [x] Garmin-Fixture-Laden, Sleep-Datumsnormalisierung, Source-Merge und
    Collection-Completion sowie Intervals-Snapshot-/Initialimport- und
    Fensterpersistenz besitzen konkrete `sync/garmin.py`- beziehungsweise
    `sync/intervals.py`-Eigentümer ohne Server-Callbacks.
  - [x] Garmin- und Intervals-Gesamtabläufe einschließlich äußerer Gates,
    Cancellation, Status und Eventprojektion vollständig auslagern.
    - [x] Der Intervals-Gesamtablauf besitzt mit `IntervalsSyncService` den
      äußeren Observer, das Provider-Resync-Gate, den gemeinsamen Lock,
      Cancellation, Wait-for-existing, Status-/Eventpersistenz, Snapshot-
      Speicherung, Daily-Marker, Library-Initialisierung, Performance-
      Follow-up, Fehlerredaktion und deterministisches Cleanup. Alle früheren
      Server-Helper und der `sync_intervals`-Einstieg sind entfernt.
    - [x] `GarminSyncService` besitzt Observer, Provider-Resync-Gate, den mit
      Morning-Body-Battery geteilten Lock, Fixture-/Remote-Orchestrierung,
      MFA und Cancellation, Wait-for-existing, Status-/Eventpersistenz,
      Payload-Aufbereitung, Fehlerzustand und deterministisches Cleanup. Der
      SDK-Client und alle früheren Garmin-Ablauf-Helper sind aus `server.py`
      entfernt.
  - [x] Garmin-/Sync-Public-State und Garmin-Coach-Projektion auslagern; die
    Services konsumieren konkrete Snapshot-/Freshness-Eigentümer und erhalten
    weder `server.py`-Callbacks noch Zugriff auf dessen Namensraum.
  - [x] Adaptive Krankheitspausen-Remote-Sync sowie strukturierte Refresh-,
    Plan-Sync-, Retry- und Konfliktbefehle in konkrete Sync-Use-Cases
    verschieben. Coach-Autorisierung bleibt vorgelagert und Remote-Schreiben
    bleibt an die bestehende explizite Freigabe gebunden.
- [x] Snapshots, Freshness, Cursors, historische Fenster, Performance-Refresh
  und vollständigen Provider-Resync konsolidieren.
  - [x] Snapshot-Merge, Sync-Snapshot/-Cursor/-Zeitraum-Persistenz und
    begrenzte Datumsfenster besitzen konkrete `sync/`-Module.
  - [x] Provider-Freshness einschließlich Cleanup-Transaktion und sämtlicher
    KV-Fallbacks besitzt einen konkreten Service mit genau einer DB-UOW.
  - [x] Intervals- und Garmin-Resync-Gates sowie ihre Operation-Decorators
    besitzen `sync/gates.py`.
  - [x] Maintenance, Korrelationskontext, Refresh-Historie, Statusprojektion
    und sichere Lifecycle-Logs einer Provideroperation besitzen den gemeinsamen
    Eigentümer `sync/observation.py`; die Übergangsdekoration verbleibender
    Server-Sync-Einstiege wird mit deren vollständigem Service-Umzug entfernt.
  - [x] Der innere Performance-Refresh besitzt Provider-Read, atomaren
    Snapshot-Merge, Marker, Fehlerredaktion, Event und seinen Single-flight-
    Lock in `sync/performance.py`; die gemeinsame äußere Beobachtung ist
    ausgelagert, der Intervals-Gate-gebundene Service-Einstieg bleibt bis zum
    vollständigen Sync-Service-Umzug offen.
  - [x] Performance-Refresh und vollständigen Provider-Resync auslagern.
    - [x] Performance-Refresh einschließlich konkretem Snapshot-Reader sowie
      Queue-/Polling-Follow-up besitzt vollständig Backend-Eigentümer ohne
      fachliche Server-Callbacks.
    - [x] `FullProviderResyncService` besitzt Validierung, Gates, Provider-
      Orchestrierung, Status-/Fehlerpersistenz, Observation und Cleanup ohne
      Rückimport oder Fachcallback aus `server.py`.
- [x] `ReconcileDependencies` von fachlichen Server-Callbacks befreien.
- [x] Durable Job-Queue, Claim, Retry, Ergebnis-Persistenz, Restart-Recovery
  und Worker-Lebenszyklus auslagern.
  - [x] Request-Normalisierung, Store, atomarer Claim, Retry-/Result-State und
    Restart-Recovery liegen in `sync/jobs.py`.
  - [x] Queue-Steuerung sowie Ergebnis-/Fehler-, Retry- und Requeue-
    Orchestrierung besitzen `SyncJobQueueService` und
    `SyncJobOutcomeService`; die früheren Server-Helper sind entfernt.
  - [x] Worker-Thread, Wakeup/Stop und Executor-Dispatch auslagern.
    - [x] `SyncJobWorker` besitzt Thread, Start-Lock, Wakeup/Stop, Claim,
      Restore-Generation und den dauerhaften Polling-Lebenszyklus ohne
      `server.py`-Import.
    - [x] `SyncJobExecutor` besitzt konkreten Providerdispatch, historische
      Fenster, Competition-Observation/-Gate, Garmin-Fixture-/Morning-Regeln,
      Ergebnis-/Retry-Persistenz und Backfill-Folgejobs. `server.py` komponiert
      Executor und Worker ausschließlich aus konkreten Backend-Services.
- [x] Konfliktbehandlung, Remote-Readback, Tombstones und lokale Dirty-Zustände
  zusammen mit den Mutationspfaden prüfen. Planned Units verwenden CAS und
  begrenzte Missing-Fenster, Library-Reads überschreiben keine Dirty-Zeilen,
  Competition-Tombstones werden nur im expliziten Push gelöscht und Planned-
  Calendar-Mutationen prüfen Hash, Identität und Readback vor dem lokalen
  Abschluss.

Abnahme: Keine doppelte Jobausführung bei konkurrierenden Claims/Neustart;
Resync und Restore respektieren dieselben Gates. Explizite Remote-Autorisierung
und bestehende automatische Lese-Syncs behalten ihren jeweiligen Vertrag.

### P7 — Coach-Kontext, Konversation, Vorschläge und Tool-Ausführung

Abhängigkeit: P2–P6.

- [x] Kontextaufbau, Projektionen, Prompttexte und Kontextvorschau in `coach/`
  bündeln. Der Kontext konsumiert Domänenlesefunktionen.
- [ ] Konversationshistorie, Reset, Attachments und Usage-Zuordnung auslagern.
  - [x] Providerabhängige Konversations-ID-Bereitstellung einschließlich
    persistierter Wiederverwendung und OpenAI-/Gemini-Erzeugung einem
    konkreten Coach-Service zuordnen; übrige History-/Reset-Pfade bleiben offen.
  - [x] Coach-Chat-Reset einschließlich best-effort Remote-Löschung,
    lokaler Transaktion, Job-Cancellation und Provider-KV-Clearing einem
    konkreten `CoachConversationResetService` zuordnen; History und
    Usage-Zuordnung bleiben offen.
- [ ] Vorschläge, Scope-/Owner-Prüfungen, explizite Bestätigung, TTL sowie
  Replay-/Repair-Schlüssel ihren Coach-Modulen zuordnen.
  - [x] Sitzungsgebundene Command-Receipt-Lesefunktion mit 400/403/404-
    Grenzen, aktuellen Vorschlägen, TTL-Projektion und Entfernung des
    Session-Schlüssels einem konkreten `CoachCommandReceiptService` zuordnen.
- [ ] Tool-Dispatch samt Ergebnis-/Fehlerprojektion verschieben; Planmutationen
  rufen die in P4 abgeschlossenen Planungs-Use-Cases auf.
  - [x] Gesamtwerkzeug-Routing einschließlich unbekanntem Werkzeug,
    Plan-/Sync-/Athleten-/Lesezweigen und Session-/Cancel-Weitergabe in
    `CoachToolDispatchService` verlagern; Turn-spezifische
    Ergebnis-/Fehlerprojektion und Spezialwerkzeuge bleiben offen.
  - [x] Read-only Coach-Toolauswahl, begrenzte Limits und Antwortprojektion
    einem zustandslosen `CoachReadToolService` zuordnen; konkrete Profil-,
    Planning-, Activity- und History-Dienste bleiben ihre Zustandseigentümer.
  - [x] Strukturierte Coach-Sync-Werkzeuge einschließlich Scope-/Remote-
    Prüfung und Job-ID-Buchführung dem konkreten Sync-Tool-Service zuordnen.
  - [x] Adaptive Apply-Freigabe mit späterem Nutzerturn und atomare
    Coach-Profiländerungen in eigene konkrete Services verlagern.
  - [x] Die fünf lokalen Athletenakten-Werkzeuge (Check-in,
    Aktivitätsfeedback, Wettkampf) samt Operation-/Objekt-Scope-Prüfung
    einem konkreten `CoachAthleteRecordToolService` zuordnen.
  - [x] Lokale Trainingsvorlagen-Batches mit 1–28-Eintragsgrenze,
    Objekt-Scope und gemeinsamem Rollback einem konkreten
    `TrainingTemplateToolService` zuordnen.
  - [x] Lokales Bibliotheksplan-Werkzeug mit Operation-/Objekt-Scope und
    Eingabeprüfung `CoachLibraryPlanToolService` zuordnen; atomare
    Planung und Remote-Schreibgrenze verbleiben bei `WorkoutLibraryPlanService`.
  - [x] Stage-/Commit-Autorisierung, Artifact-ID-Prüfung und Scope des
    strukturierten Planartefakt-Werkzeugs `CoachPlanArtifactToolService`
    zuordnen; `TrainingPlanArtifactService` bleibt Eigentümer von Zustand,
    lokaler Speicherung und atomarem Commit.
  - [x] Autorisierung, Plan-ID-Scope und Argumentprojektion für
    `replace_training_plan` und `apply_training_changes` dem konkreten
    `CoachPlanningChangeToolService` zuordnen; die atomaren Replacement- und
    Change-Planungsservices bleiben Zustandseigentümer.
  - [x] Autorisierung, Scope und Argumentprojektion der vier übrigen
    strukturierten Adaptive-, Planupdate- und Undo-Werkzeuge einem konkreten
    `CoachPlanningActionToolService` zuordnen; die zuständigen Preview-, Apply-, Plan-,
    History- und Proposal-Services bleiben Zustandseigentümer.
  - [x] Dialogbezogene Datums-, Planned-Unit-, Library- und Draft-Scopes in
    `CoachDialoguePlanScopeService` verlagern; lokale SQL-Lesegrenzen und der
    gemeinsame DatabaseManager/DB-Lock bleiben unverändert.
  - [x] Dialog-Request-Bindung, Anbieter-/Remote-Schreibgrenzen, lebende
    Objekt-Scopes und Reparaturzeitraum in `CoachDialogueActionService`
    verlagern; `server.py` komponiert nur die bestehenden Zustandseigentümer.
  - [x] Provenienz-/Textprüfung und KV-Persistenz einer konkreten Coach-
    Rückfrage `CoachClarificationService` zuordnen; ungültige oder fremde
    Quellen verändern den ausstehenden Auftrag nicht.
  - [x] Atomaren Coach-Trainings-Patch mit Revisions- und Kalenderprüfung,
    gemeinsamer Planänderung/-erstellung, Constraints und Rollback in
    `CoachTrainingPatchService` verlagern; Planung bleibt Zustandseigentümer.
  - [x] Explizite lokale Planungskommandos einschließlich Vorbereitung,
    Scope, Session-/Conversation-Claim, Replay, atomarer Tool-Ausführung
    und finalem Receipt `CoachPlanningCommandService` zuordnen; der
    HTTP-Handler delegiert direkt.
  - [x] Strukturierte Tool-Call-Metadaten einschließlich Allowlist,
    Schrittlimit, Argumentprüfung und stabiler Replay-/Reparatur-Schlüssel
    als reine Backend-Projektion `structured_tool_call_metadata` verlagern;
    die restliche Turn-Orchestrierung bleibt bis zur folgenden Auslagerung offen.
  - [x] Call-ID-/Effekt-Replay einschließlich Read-only-Ausnahme und
    Draft-Artifact-Revisionsprüfung `CoachStructuredToolReplayService`
    zuordnen; `DatabaseManager` und DB-Lock bleiben Zustandseigentümer.
  - [x] Strukturierte Turn-Ergebnisprojektion einschließlich reparierter
    Fehler, bestätigter Effekte, Antwort-/Status-Fallback und atomarer
    Pending-Request-Persistenz `CoachStructuredOutcomeService` zuordnen;
    Provider- und Tool-Rundenschleife bleiben bis P8 offen.

Abnahme: Natürliche Dialogfortsetzungen, Klärungen, Korrekturen und Tool-Scopes
bleiben erhalten. Keine neuen Triggerwörter oder reduzierten Kontext-/Planlimits.
Abgelaufene oder fremde Vorschläge dürfen keine Mutation auslösen.

### P8 — Coach-Turn, Background-Jobs, Streaming und Morning Check-in

Abhängigkeit: P7 und Sync-Worker aus P6.

- [ ] Die gesamte strukturierte Response-/Tool-Rundenschleife einschließlich
  Retry, Fehler-Recovery, Receipts und finaler Persistenz nach `coach/` ziehen.
  - [x] Provider-Request-Aufbau einschließlich Dialogkontext,
    Attachment-Sicherheitsanweisung, OpenAI-Kontinuität, Gemini-Medien
    und Modell-/Thinking-Auswahl `CoachRequestPayloadService` zuordnen;
    die Response-/Tool-Rundenschleife bleibt offen.
  - [x] Terminale Turn-Fehlerprojektion einschließlich bestätigter Effekte,
    Pending-Request, atomarem Receipt, Checkpoint-Bereinigung und Event nach
    Commit einem `CoachTurnFailureService` zuordnen; der übrige Turn bleibt offen.
- [ ] `chat_with_coach`, Background-Claim/Resume/Cancel und Stream-Register
  auslagern; synchrone und Hintergrundausführung teilen denselben Turn-Use-Case.
  - [x] Process-lokales Chat-Stream-Register, SSE-Queues und Background-
    Cancel-Events einem einzigen `ChatStreamRegistry` zuordnen; durable
    Job-Entscheidungen bleiben bis zur Coach-Job-Auslagerung offen.
  - [x] Durable Background-Claims, Contention-Requeue und gespeicherte
    Nutzernachrichten einem konkreten `CoachJobStore` zuordnen; Enqueue,
    Resume und Cancel sind in den folgenden Teilaufgaben abgeschlossen,
    Worker-Turn-Orchestrierung bleibt offen.
  - [x] Restart-Recovery für unterbrochene synchrone, OpenAI- und Gemini-
    Background-Turns einschließlich persistierter Intents, Queue-Phase und
    Worker-Wake dem `CoachJobStore` zuordnen; Worker-Turn-Orchestrierung
    bleibt offen.
  - [x] Background-Enqueue samt Validierung, Session-Bindung, Replay,
    Anhangsquote und atomarer Command-/Message-Persistenz einem
    `CoachJobSubmissionService` zuordnen; Worker-/Turn-Ausführung bleibt
    offen. Resume und Cancel sind in den folgenden Teilaufgaben abgeschlossen.
  - [x] Sessiongebundene Attached-/Background-Cancellation samt
    persistierter Cancel-Markierung, Provider-Response-Close und
    Restart-Verhalten einem `CoachCancellationService` zuordnen;
    Receipt-Merge gehört dem `CoachJobStore`. Turn-Ausführung und
    Worker-Ausführung bleiben offen.
- [ ] Manuellen Morning Check-in mit Frische-Gate auslagern; die auf `develop`
  entfernte automatische Reservierungs-/Retry-Steuerung nicht wieder einführen.
  - [x] Manuellen Garmin-Schlaf-/Body-Battery-Vorbereitungspfad und
    read-only Statusprojektion ihren konkreten Coach-Services zuordnen.
  - [ ] Verbleibende Background-Receipt-/Fehlerzustände mit dem Coach-Job-
    Eigentümer zusammenführen und Restart-/Cancellation-Verträge prüfen.
- [x] Tages-/Startup-Scheduler nach `sync/scheduler.py` ziehen; die Composition
  Root registriert die konkreten Sync-Dienste ohne Importzyklus. Automatische
  Morning-Check-ins sind seit dem `develop`-Abgleich kein Scheduler-Auftrag.
  - [x] Die vier täglichen Providerentscheidungen einschließlich Due-Marker,
    Queue-/Resync-/Maintenance-Gates und Payload-Reihenfolge gehören einem
    konkreten `DailySyncScheduler`; `server.py` komponiert nur noch.
  - [x] Startup-Provider- und Historical-Backfill-Entscheidungen einem
    konkreten `StartupSyncScheduler` zuordnen; Reihenfolge und aktive Jobs
    bleiben erhalten.
  - [x] Verbleibende Tages-Loop-Lifecycle-Steuerung einschließlich
    300-Sekunden-Takt, Fehlerbehandlung und Morning-Battery-Refresh
    dem konkreten `DailySyncLoop` zuordnen.

Abnahme: SSE liefert inkrementelle Texte und finale Receipts; Disconnect,
Cancel, Retry nach bereits ausgeführtem Tool und Neustart verursachen keine
doppelten Seiteneffekte. Morning Check-in wartet auf Schlafdaten des aktuellen
Tages, bevor davon abhängiger Sync oder Coach-Analyse startet.

### P9 — Backup, Restore, Datenschutz und Diagnostik

Abhängigkeit: P1 sowie Ressourcen-/Worker-Verträge aus P6 und P8.

- [x] Archivaufbau, Exportgrenzen, Backupvalidierung, Restore und
  Wiederaufnahme nach `backup/` verschieben.
  - [x] Begrenzten lokalen Privacy-ZIP-Aufbau einschließlich SQL-/KV-
    Auswahl, Manifest, Zeit-/Platz-/Größenlimits und Temp-Datei-Cleanup
    einem konkreten `PrivacyArchiveExportService` zuordnen.
  - [x] Datenbank-WAL-Checkpoint, Byte-Backup und den über die gesamte
    HTTP-Dateiausgabe gehaltenen Lock mit Platz-/Größen-/Zeitgrenzen
    einem konkreten `DatabaseBackupService` zuordnen; die Wiederaufnahme
    nach Restore gehört dem `DatabaseRestoreService`.
  - [x] Restore-Payload-Staging, Schema-/Integritäts-/Fremdschlüsselprüfung
    und Session-Bereinigung einem konkreten `DatabaseRestoreValidationService`
    zuordnen; Austausch und Worker-Wiederaufnahme gehören dem folgenden
    Restore-Eigentümer.
  - [x] Wartungsgate, WAL-Checkpoint, DB-Drain, vorherige Sicherung,
    atomaren Dateiaustausch, temporäres Cleanup und anschließende Sync-/
    Coach-Job-Wiederaufnahme `DatabaseRestoreService` zuordnen.
- [x] Lokalen Privacy-Export/-Delete und autorisierte Remote-Konversations-
  löschung nach `privacy.py` bzw. zum zuständigen Provider aufteilen.
  - [x] Lokale JSON-Datenprojektion einschließlich sensibler KV-Ausnahmen,
    fehlerhaftem JSON und getrennter DB-Lesegrenzen einem konkreten
    `PrivacyDataExportService` zuordnen.
  - [x] Preview, Wartungsgate, lokale Löschtransaktion und best-effort-
    Remote-Ergebnis gehören `PrivacyDeleteService`; der einzige
    autorisierte OpenAI-DELETE gehört `OpenAIResponsesClient`.
- [x] Diagnosehistorie/-report und Logprojektion vollständig auslagern.
  - [x] Begrenzte, datensparsame Coach-Command-Historie samt SQL-Read und
    Fehlerprojektion zu `diagnostics/history.py` verschieben.
  - [x] Begrenzte, redigierte Logprojektion und alle Aufrufer zu
    `diagnostics/logs.py` verschieben; Diagnosebericht und Capture bleiben
    bis zu ihrem eigenen Service-Umzug offen.
  - [x] Diagnosebericht, Capture-Projektion und Aufrufer auslagern;
    Capture-Status und Enable bleiben bereits dem konkreten
    `DiagnosticCapture` zugeordnet, die HTTP-Aufrufer sind nur Transport.
    - [x] Vollständigen Diagnosebericht einschließlich redigierter Logs,
      Capture-Status/Entries, DB-Zähler und Provider-Frische einem
      konkreten `DiagnosticReportService` zuordnen; der eigenständige
      Capture-Endpunkt delegiert unverändert an `DiagnosticCapture`.
- [x] HTTP-Streaming von Exportdateien bleibt im HTTP-Adapter.
  `ExportStreamTransport` besitzt die Download-Orchestrierung; jede Route
  konstruiert nur ihren eigenen Backup-/Privacy-Service und behält
  Authentisierung, Deadline, Lock-Lebensdauer und Cleanup bei.

Abnahme: Ungültige Backups verändern keine Daten; Restore blockiert
konkurrierende Operationen korrekt und verwendet anschließend konsistente
Ressourcen. Tests laufen ausschließlich mit temporären Datenbanken/Archiven.

### P10 — HTTP-API und öffentliche Projektionen

Abhängigkeit: P3–P9; Route-Migration kann vorher für abgeschlossene Use Cases beginnen.

- [ ] Auth, Session-Cookies, CSRF, Rate-Limits und Readiness in `http_api/` ziehen.
  - [x] Den Login-/API-Rate-Limiter einschließlich Lock, Buckets,
    begrenztem Cleanup und Retry-After einem konkreten
    `http_api/`-Zustandseigentümer zuordnen.
  - [x] Öffentliche Readiness-Prüfung mit bestehender DB-UOW,
    kurzlebiger Verzeichnisprobe und Wartungsstatus einem konkreten
    `ReadinessService` zuordnen; Handler sendet nur Status und JSON.
  - [x] Session-Lebenszyklus, Cookie-/CSRF-Prüfung, Login-/Logout-
    Autorisierung und persistierten Coach-Session-Binding-Read einem
    konkreten `SessionAuthService` zuordnen. Der Handler löst den
    aktuellen Eigentümer auch auf Keep-Alive-Verbindungen dynamisch
    auf; Rate-Limit-Zustand bleibt bei `RateLimiter`.
- [ ] Öffentliche Bootstrap-/State-Projektionen und Pagination zuordnen;
  Projektionen erhalten Daten über Domänenlesefunktionen.
  - [x] Begrenzte Performance-/Garmin- und lokale Feedback-/Check-in-
    Projektionen konkreten `http_api/`-Services zuordnen.
  - [x] Die vollständige bisherige `public_state`-Projektion in einen
    konkreten Service verschieben und Performance-/Feedback-Felder
    über dieselben Projektionseigentümer erzeugen; die frühere Funktion
    hatte nur Testaufrufer, aber keinen produktiven HTTP-Route-Caller.
    Bootstrap und weitere P10-Transportaufgaben bleiben offen.
  - [x] Lokalen Bootstrap-Lesevorlauf und Wetter-Follow-up mit
    bestehender UOW-/Lock-Grenze in konkrete `http_api/`-Eigentümer
    verschieben; übrige `public_state`-Projektionen bleiben offen.
  - [x] Kalender-, Wettkampf- und Tageskontext-Projektion als konkreten
    Service innerhalb der bestehenden Bootstrap-UOW zuordnen; die
    verbleibenden öffentlichen Felder bleiben offen.
  - [x] Begrenzte Chat-History-Pagination einschließlich Suche, Cursor,
    Generation und sitzungsgebundener Vorschläge einem konkreten
    `http_api/`-Service mit unveränderter DB-UOW zuordnen.
  - [x] Öffentliche Plan-/Kalender-/Wetterprojektion mit bestehenden
    Datenlimits und geschütztem History-Read in `PublicPlanStateService`
    verlagern; andere öffentliche Projektionen bleiben offen.
  - [x] Den vollständigen bounded Local-Only-Bootstrap einschließlich
    Providerstatus und aller Felder in `PublicBootstrapService` verlagern;
    der Handler authentifiziert und sendet nur die Antwort.
  - [x] Den separaten `/api/weather`-Read mit unveränderter
    Refresh-/Local-Only-Regel in `PublicWeatherStateService` verlagern.
- [ ] `RequestHandler`, Route-Dispatch, Body-Limits, statische Dateien und SSE
  transportseitig auslagern; vorhandene `requests.py`/`responses.py` nutzen.
  - [x] Cursor-Validierung, Initialereignisse, Gap-Reset, Heartbeat und
    Verbindungsschleife des authentifizierten `/api/state/events`-Streams
    `StateEventTransport` zuordnen; Event-Puffer bleibt `runtime_events`,
    Socket-/Schreibzustand bleibt beim Handler.
  - [x] Sync-POST-Fachentscheidungen in `SyncCommandEndpoint` verlagern;
    Handler behält ausschließlich Transport, Body-Lesen und Antwort.
  - [x] Statische Asset-Allowlist, Pfadsperre, Cache-/ETag-Projektion und
    Sicherheitsheader `StaticAssetService` zuordnen; Handler sendet nur
    Status, Header und Bytes.
- [ ] Handler mit den konkret benötigten Services verbinden; keine Weitergabe
  des `server`-Moduls als Pseudo-Servicecontainer.
- [x] `CoachHTTPServer` dem HTTP-Bereich zuordnen; Threading-, Daemon-
  und Queue-Vertrag bleiben unverändert.

Abnahme: Endpunkte, Statuscodes, JSON-Formate, Cookies, SSE-Events und statische
Assets bestehen die Vertrags-/Browserprüfungen. HTTP enthält keine eigene
Implementierung von Planänderungen, Provider-Sync oder Coach-Tool-Ausführung.

### P11 — Composition Root, Restcode-Audit und Abschluss

Abhängigkeit: alle vorigen Phasen.

- [ ] `main()` auf konkrete Konstruktion, Startreihenfolge und Shutdown reduzieren.
- [ ] Alle Übergangs-Wrapper, alten Imports und verwaisten Konstanten entfernen.
- [ ] Alle verbleibenden `server.*`-Testpatches migrieren; nur Tests des
  Einstiegspunkts dürfen noch `server` als Testgegenstand benötigen.
- [ ] Inventar vollständig schließen; jede ursprüngliche Definition anhand
  des finalen Codes und ihrer Aufrufer prüfen.
- [ ] Importgraph auf Zyklen und unerlaubte Richtungen prüfen; indirekte Zugriffe
  mittels `sys.modules`, dynamischen Imports, `getattr` und Namespace-Proxies
  zusätzlich im Review ausschließen.
- [ ] Architekturprüfung auf den final erlaubten Inhalt von `server.py`
  verschärfen und in bestehende CI integrieren.
- [ ] Vollständige Regression, Docker-Build und isolierte integrierte Abläufe
  ausführen; Dokumentation auf den tatsächlichen Endzustand aktualisieren.

Abnahme: Alle Kriterien aus Abschnitt 1 erfüllt. Keine Restphase mit dem
Status „Helfer ausgelagert, eigentlicher Ablauf später“.

## 6. Tests und sichere Migration der Aufrufer

Für jeden Umzug zuerst Call Sites und Patch Targets suchen. Ein Test, der
`server.responses_request` patcht, muss künftig den Lookup-Ort des konsumierenden
Coach-Moduls oder dessen injizierten Provider-Fake ersetzen. Ein Alias im Server
ist kein Ersatz: Die ausgelagerte Funktion würde diesen Patch nicht mehr sehen.

Bestehende Testfälle werden mit ihrer Verantwortung verschoben. Testanzahl
allein ist kein Qualitätsmaß; entscheidend ist, dass dieselben Verhaltens- und
Fehlerfälle nach dem Umzug die neue Implementierung tatsächlich ausführen.
Zusätzliche Tests konzentrieren sich auf neue Modulgrenzen und Risiken wie
Transaktionen, gemeinsam genutzte Locks, Imports und Cancellation.

| Änderung | Erforderliche Prüfung |
| --- | --- |
| Reine Berechnung/Projektion | Betroffene bestehende Unit-Tests; Quellen-/Grenzfälle |
| Provider/Streaming | Synthetische HTTP-/SSE-Fixtures, Fehler, Retry, Cancel, Limits |
| Persistenz/Planänderung | Temporäre DB, Rollback, Revision/Hash, konkurrierende Änderung |
| Jobs/Restore | Claim/Resume, gemeinsame Gates, Generationen, Stop/Restart |
| HTTP oder State-Vertrag | API-Vertragstests plus betroffene Playwright-Szenarien |
| Start/DB/Deployment | Docker-Build und isolierter SQLCipher-Startup-Smoke-Test |

Vor Abschluss jedes fachlichen Schritts die volle Python-Suite und die
Architekturprüfung ausführen. Browser-/Docker-Prüfungen entsprechend den
geänderten Grenzen und den Repository-Vorgaben ausführen. Bei reinem
Dokumentationsfortschritt genügt Diff-/Konsistenzprüfung.

```powershell
python -m unittest discover -s tests -v
python -m compileall -q server.py backend
git diff --check
docker build -t ai-coach:local .
npm run test:e2e
```

Die Playwright-Konfiguration und Fixtures vor Ausführung auf isolierten Start
prüfen; niemals eine produktive URL als Testziel verwenden. SQLCipher-Prüfungen
im unterstützten Container durchführen, falls die native Windows-Abhängigkeit
nicht verfügbar ist. Keine Auth-/Verschlüsselungsprüfung abschalten.

Die finale Integrationsabnahme umfasst Login/CSRF, lokale Planerstellung und
-bearbeitung, expliziten Remote-Sync, Adaptive Preview/Apply, Coach mit beiden
Providern und SSE, Activity-Analyse, Morning Check-in, Job-Neustart sowie
Backup/Restore. Externe Dienste werden dabei durch kontrollierte Fakes ersetzt.

## 7. Fortschritt, PR-Schnitt und Rücknahme

Pro PR eine zusammenhängende Verantwortung samt Aufrufern, Tests und Entfernung
aus `server.py` migrieren. Phasen mit vielen Verantwortlichkeiten ausdrücklich
in mehrere solche PRs aufteilen. Refactoring und neue Produktfunktionen getrennt
halten; Konflikte mit parallel laufenden Features vor dem nächsten Umzug durch
Rebase und erneute Prüfung der betroffenen Symbole auflösen.

Jeder PR-Bericht enthält:

- Verschobene Verantwortlichkeiten und ihre konkreten Zielmodule.
- `server.py`-Zeilen vorher/nachher und Zahl verbleibender Inventareinträge.
- Gesamtumfang des Python-Backends, damit zusätzlicher Wrapper-/Gerüstcode
  sichtbar bleibt; keine künstliche Einsparung durch verdichtete Formatierung.
- Verbleibende fachliche Rück-Callbacks und `server`-Patch-Abhängigkeiten.
- Tatsächlich ausgeführte Prüfungen und offene, reproduzierbare Probleme.

Die Zahl verbleibender fachlicher Definitionen ist der primäre Fortschritt;
Zeilenzahl ist ein unterstützender Indikator. Nach einer Übergangsänderung muss
der zugehörige fachliche Abschluss folgen, bevor die nächste unabhängige
Auslagerung begonnen wird. Unbegründetes Wachstum von `server.py` wird abgewiesen.

Übergangsadapter sind nur innerhalb eines laufenden Umzugs zulässig und werden
vor Abschluss dieser Verantwortung entfernt. Keine permanente Kompatibilität
für interne Testimports. Jeder abgeschlossene PR bleibt start- und testfähig.
Bei einer Regression wird der betreffende Code-PR gezielt zurückgenommen;
es gibt keine Datenmigration und keine Rücknahme durch Löschen von Nutzerdaten.

## 8. Nächster ausführbarer Schritt

Mit P0 beginnen: vollständiges symbolbasiertes Inventar, Test-/Importabhängigkeiten
und Baseline anlegen. Danach P1 mit Fehlerklassen und gemeinsam genutzten
Ressourcen umsetzen. Die konkrete Aufteilung aller weiteren Phasen wird anhand
dieses Inventars abgearbeitet, bis kein fachlicher Rest in `server.py` bleibt.

Dieser Plan beschreibt die Umsetzung. Er selbst führt weder Refactoring noch
Tests, Commits, PR-Erstellung oder Veröffentlichung aus.
