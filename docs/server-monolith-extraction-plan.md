# Plan: server.py vollständig in fachliche Backend-Module aufteilen

Stand: 14.09.2026. Arbeitsbranch: `docs/backend-logic-boundary`.
Ausgangscommit: `58e352d`. Status: Plan erstellt, Umsetzung noch nicht begonnen.
Die Architekturregel in der Root-`AGENTS.md` ist bereits lokal ergänzt.

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

- [ ] `http_json`, begrenzte Reads, Providerfehler und sichere HTTP-Aufrufe
  mit `providers/http.py` zusammenführen.
  - [x] Request-Body/-Header-Aufbau, begrenzte Erfolgs-/Fehler-Reads,
    abbrechbares Header-Warten samt Response-Handle-Lifecycle und redigierte
    Providerfehler in reine Adapter verschieben.
  - [ ] Netzwerk-, Retry-/Cancellation- und Statusorchestrierung vollständig
    aus `server.py` entfernen.
- [ ] OpenAI Request/Response, Background Retrieve/Cancel, SSE-Verarbeitung,
  Usage-/Rate-Limit-Auswertung und Audio-Transkription in konkrete Provider-Module
  ziehen. Nutzungs-Persistenz bleibt außerhalb des reinen Transports.
  - [x] Response-/Fehlerparsing, SSE-Ereignisse, Response-ID-, Payload-,
    Rate-Limit-/Usage-Berechnungen und Audio-Wire-Helfer auslagern.
  - [x] Begrenztes SSE-Lesen einschließlich Fragmentgrenzen, finaler Response,
    Abbruchprüfung und Bytefortschritt in den OpenAI-Adapter verschieben.
  - [ ] Request-, Background- und Stream-Transport einschließlich Abbruch und
    Polling vollständig im OpenAI-Adapter besitzen.
- [ ] Gemini Payload-/Tool-Konvertierung und Streaming zum Gemini-Adapter ziehen;
  persistierte Dialoghistorie gehört zu `coach/conversation.py`.
  - [x] Payload-/Tool-/Medienkonvertierung und Stream-Akkumulation auslagern.
  - [x] Stream-Transport einschließlich Header-Abbruch, Response-Handle,
    Größenlimit und SSE-Akkumulation auslagern.
  - [ ] Persistierte Historie in P7 nach `coach/conversation.py` verschieben.
- [x] Kalenderabruf einschließlich SSRF-Prüfung und iCalendar-Parsing auslagern.
- [ ] Vorhandene Garmin-/Intervals-Adapter erweitern, ohne Sync-Use-Cases in
  Provider-Module zu verschieben.

Abnahme: Adaptertests decken Fehler, Timeout, Größenlimits, fragmentiertes SSE,
Abbruch und finale Responses ab. Retry-After, Quota-Unterscheidung und aktuelle
Tokenbudgets bleiben erhalten; Tests verwenden ausschließlich Provider-Fakes.

### P3 — Athlet, Aktivitäten, Performance, Kalender und Wetter

Abhängigkeit: P1; Transportnutzer zusätzlich P2.

- [ ] Profil, Check-ins und Aktivitätsfeedback samt Validierung und Persistenz
  in `athlete/` ziehen; vorhandene Repositories wiederverwenden.
- [ ] Aktivitätsidentität, Duplikaterkennung und Detailprojektion in `activities/`
  bündeln. Remote-Löschen bleibt ein ausdrücklich autorisierter Use Case.
- [ ] Garmin-Metriken, Trends, Recovery, Leistungswerte und Aktivitätsvalidierung
  nach `performance/` verschieben; Rohdaten und Quellenlabels erhalten.
- [ ] Externe/öffentliche Kalender und Wetter-Cache/-Projektion auslagern.
- [ ] Reine Kontextbausteine von Datenabruf und Synchronisierung trennen.

Abnahme: Quellenpriorität, Messdatum/Freshness, fehlende Werte, Duplikate,
Kalenderrekurrenz und Wetter-Cache-Verhalten sind mit bestehenden bzw.
gezielt ergänzten Fixtures abgesichert.

### P4 — Lokale Planung vollständig besitzen

Abhängigkeit: P1, benötigte Berechnungen aus P3.

- [ ] Workout-Normalisierung, Library/Templates, geplante Units, Wettkämpfe,
  Trainingskalender und Compliance in fachliche `planning/`-Module ziehen.
- [ ] CRUD, Bounds, Revisionen, Validierung, Planersatz und strukturierte
  Batch-Änderungen einschließlich sämtlicher privater Helfer verschieben.
- [ ] `PlanningChangeDependencies` und `AdaptiveDependencies` prüfen:
  fachinterne Callbacks durch direkte modulinterne Aufrufe ersetzen.
- [ ] Adaptive Vorschau/Apply und Krankheitspausen lokal vollständig zuordnen;
  Remote-Synchronisation über einen separaten Sync-Einstieg aufrufen.
- [ ] Hash-/Revisionsprüfungen, Historieneinträge und Atomarität innerhalb
  derselben Transaktion bewahren.

Abnahme: Vollständiger Planersatz, Teiländerung und Adaptive Apply funktionieren
ohne fachliche Callback-Implementierungen in `server.py`. Fehler in der Mitte
einer Batch-Änderung rollen alle zugehörigen lokalen Änderungen zurück.

### P5 — Änderungshistorie und Undo

Abhängigkeit: P4.

- [ ] Projektionen, Hashes, Kapazitätsprüfung und Historienpersistenz zuordnen.
- [ ] Undo-Preview und Undo-Apply nach `history/` verschieben; fachliche
  Wiederherstellung nutzt transaktionsfähige Operationen der Domänen.
- [ ] Zyklen vermeiden: Domänen dürfen einen kleinen History-Writer verwenden;
  nur der Undo-Orchestrator ruft Domänenoperationen auf, nicht der Writer.

Abnahme: Profil-, Wettkampf-, Library- und Plan-Undo behalten Eigentümerprüfung,
Konflikterkennung und Rollback. Keine Rückabhängigkeit auf HTTP oder Coach.

### P6 — Synchronisierung, Reconciliation und Sync-Worker

Abhängigkeit: P2–P5.

- [ ] Garmin-, Intervals-, Library-, Planned-Unit- und Wettkampf-Sync mit
  ihren vollständigen Abläufen nach `sync/` ziehen.
- [ ] Snapshots, Freshness, Cursors, historische Fenster, Performance-Refresh
  und vollständigen Provider-Resync konsolidieren.
- [ ] `ReconcileDependencies` von fachlichen Server-Callbacks befreien.
- [ ] Durable Job-Queue, Claim, Retry, Ergebnis-Persistenz, Restart-Recovery
  und Worker-Lebenszyklus auslagern.
- [ ] Konfliktbehandlung, Remote-Readback, Tombstones und lokale Dirty-Zustände
  zusammen mit den Mutationspfaden prüfen.

Abnahme: Keine doppelte Jobausführung bei konkurrierenden Claims/Neustart;
Resync und Restore respektieren dieselben Gates. Explizite Remote-Autorisierung
und bestehende automatische Lese-Syncs behalten ihren jeweiligen Vertrag.

### P7 — Coach-Kontext, Konversation, Vorschläge und Tool-Ausführung

Abhängigkeit: P2–P6.

- [ ] Kontextaufbau, Projektionen, Prompttexte und Kontextvorschau in `coach/`
  bündeln. Der Kontext konsumiert Domänenlesefunktionen.
- [ ] Konversationshistorie, Reset, Attachments und Usage-Zuordnung auslagern.
- [ ] Vorschläge, Scope-/Owner-Prüfungen, explizite Bestätigung, TTL sowie
  Replay-/Repair-Schlüssel ihren Coach-Modulen zuordnen.
- [ ] Tool-Dispatch samt Ergebnis-/Fehlerprojektion verschieben; Planmutationen
  rufen die in P4 abgeschlossenen Planungs-Use-Cases auf.

Abnahme: Natürliche Dialogfortsetzungen, Klärungen, Korrekturen und Tool-Scopes
bleiben erhalten. Keine neuen Triggerwörter oder reduzierten Kontext-/Planlimits.
Abgelaufene oder fremde Vorschläge dürfen keine Mutation auslösen.

### P8 — Coach-Turn, Background-Jobs, Streaming und Morning Check-in

Abhängigkeit: P7 und Sync-Worker aus P6.

- [ ] Die gesamte strukturierte Response-/Tool-Rundenschleife einschließlich
  Retry, Fehler-Recovery, Receipts und finaler Persistenz nach `coach/` ziehen.
- [ ] `chat_with_coach`, Background-Claim/Resume/Cancel und Stream-Register
  auslagern; synchrone und Hintergrundausführung teilen denselben Turn-Use-Case.
- [ ] Morning Check-in und seine Reservierung/Retry-Steuerung auslagern.
- [ ] Tages-/Startup-Scheduler nach `sync/scheduler.py` ziehen; die Composition
  Root registriert den konkreten Morning-Check-in-Aufruf ohne Importzyklus.

Abnahme: SSE liefert inkrementelle Texte und finale Receipts; Disconnect,
Cancel, Retry nach bereits ausgeführtem Tool und Neustart verursachen keine
doppelten Seiteneffekte. Morning Check-in wartet auf Schlafdaten des aktuellen
Tages, bevor davon abhängiger Sync oder Coach-Analyse startet.

### P9 — Backup, Restore, Datenschutz und Diagnostik

Abhängigkeit: P1 sowie Ressourcen-/Worker-Verträge aus P6 und P8.

- [ ] Archivaufbau, Exportgrenzen, Backupvalidierung, Restore und
  Wiederaufnahme nach `backup/` verschieben.
- [ ] Lokalen Privacy-Export/-Delete und autorisierte Remote-Konversations-
  löschung nach `privacy.py` bzw. zum zuständigen Provider aufteilen.
- [ ] Diagnosehistorie/-report und Logprojektion vollständig auslagern.
- [ ] HTTP-Streaming von Exportdateien bleibt im HTTP-Adapter.

Abnahme: Ungültige Backups verändern keine Daten; Restore blockiert
konkurrierende Operationen korrekt und verwendet anschließend konsistente
Ressourcen. Tests laufen ausschließlich mit temporären Datenbanken/Archiven.

### P10 — HTTP-API und öffentliche Projektionen

Abhängigkeit: P3–P9; Route-Migration kann vorher für abgeschlossene Use Cases beginnen.

- [ ] Auth, Session-Cookies, CSRF, Rate-Limits und Readiness in `http_api/` ziehen.
- [ ] Öffentliche Bootstrap-/State-Projektionen und Pagination zuordnen;
  Projektionen erhalten Daten über Domänenlesefunktionen.
- [ ] `RequestHandler`, Route-Dispatch, Body-Limits, statische Dateien und SSE
  transportseitig auslagern; vorhandene `requests.py`/`responses.py` nutzen.
- [ ] Handler mit den konkret benötigten Services verbinden; keine Weitergabe
  des `server`-Moduls als Pseudo-Servicecontainer.
- [ ] `CoachHTTPServer` dem HTTP-Bereich zuordnen.

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
