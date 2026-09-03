# GPT-5.6 Luna Handover: Coach-first Architektur, Workflow und UI/UX

**Status:** Arbeitsplan, alle Tasks absichtlich offen  
**Stand:** 2026-09-03  
**Ausgangsversion:** 1.4.9  
**Basis-Commit:** `c9a25e9`  
**Ziel:** Ein stabiler Coach, der Planung und Synchronisation über Werkzeuge ausführt, mit einer professionellen, konsistenten und responsiven Oberfläche.

> Dieses Dokument ist die verbindliche Arbeitsanweisung für GPT-5.6 Luna. Die Checkboxen werden erst nach Implementierung **und** nachweisbarer Verifikation abgehakt. Teilfertige Aufgaben bleiben offen.

## 1. Verbindliche Leitplanken

### Produktregeln

- Eine eindeutige Handlungsaufforderung ist die Autorisierung: „Plane …“, „Verschiebe …“, „Speichere …“, „Synchronisiere …“.
- Lokale Planungsänderungen werden unmittelbar, atomar und revisionssicher gespeichert. Danach erscheint ein Receipt mit „Plan ansehen“ und „Rückgängig“.
- Ein ausdrücklich genannter Intervals.icu-Sync wird ohne zweite Bestätigung als persistenter Hintergrundjob gestartet.
- Hypothetische Fragen bleiben beratend und mutieren keine Daten.
- Bei echter Mehrdeutigkeit stellt der Coach genau eine konkrete Rückfrage.
- „Kalender“ bezeichnet den lokalen Trainingskalender. Der gemeinsame iCal-Kalender bleibt lesend.
- Garmin, Wetter und iCal sind Lesedatenquellen; Intervals.icu ist der einzige Remote-Schreibpfad.
- Automatisch ausgelöste adaptive Neuplanung behält eine einzige Vorschau mit „Anwenden“.
- Irreversible Administration (Restore, lokales Löschen, vollständiger Resync) verwendet einen gestalteten Dialog; native `window.confirm`/`window.prompt` werden entfernt.
- Profil-, Check-in- und sonstige Datenbankänderungen bleiben durch explizite Benutzeraktion autorisiert; Chat-Text darf nicht stillschweigend dauerhafte Daten ändern.

### Sicherheits- und Datenregeln

- `APP_PASSWORD`, SQLCipher, Sessions, CSRF und Authentifizierung nicht abschwächen.
- Keine Secrets, Provider-Tokens, `.env`, `/data`, Backups oder Athleteninhalte in Logs, Tests, Diagnosen oder dieses Dokument übernehmen.
- Die App bleibt private Single-Athlete-PWA im vertrauenswürdigen LAN/VPN.
- Provider-Rohdaten und vollständige Snapshots bleiben unverändert groß. Nur die Coach-Projektion wird kompakt; im Coach-Kontext maximal die fünf neuesten Aktivitäten je Sport.
- Keine impliziten Remote-Schreibvorgänge. Eine explizite Benutzeranweisung an den Coach gilt als Remote-Autorisierung für den benannten Zielprovider.

## 2. Verifizierter Ist-Befund

### Workflow- und Laufzeitfehler

- Regex-Routing erkennt natürliche Formulierungen wie „Der Plan sieht gut aus, bitte speichere ihn dauerhaft“ und „Jetzt speichern“ nicht zuverlässig.
- Nach Folge-Turns werden dem Modell Werkzeuge teilweise entzogen; es kann dann nur noch behaupten, dass nichts gespeichert wurde.
- Der bestehende Ablauf erzwingt Vorschau → Browser-Confirm → Confirm-API → Execute-API für normale Planung und Synchronisation.
- Bootstrap liefert Chat, Wetter und Teilbereiche zunächst leer; die Oberfläche wirkt dadurch zugleich „bereit“ und „nicht eingerichtet“.
- `server.py` bündelt HTTP, DB, Provider, Coach, Planung und Synchronisation in etwa 14.000 Zeilen.
- SQLCipher-Verbindungen werden häufig neu geöffnet; ein globaler Lock serialisiert zu viele Lese- und Netzwerkpfade.
- Diagnosewerte: Intervals-Sync ca. 456 Sekunden, Kalender-Sync ca. 642 Sekunden; Garmin 109 Zeitfenster, 9.742 Daily-Stats und 9.742 Resting-HR-Einträge sowie 108 identische Body-Battery-Fehler.
- Intervals beginnt bei Vollsyncs historisch im Jahr 2000; Garmin arbeitet tageweise und weitgehend sequenziell; iCal-Recurser starten vom historischen `DTSTART`.

### UI/UX-Review

Geprüft wurden die Haupt- und Unterrouten in 320×568, 390×844, 768×1024, 844×390 und 1440×1000 sowie leere, geöffnete und lange Zustände.

Stärken:

- Dunkle Farbpalette, grüne Akzentfarbe, Kartenflächen, Safe-Area und Reduced-Motion sind brauchbare Grundlagen.
- In den geprüften Viewports wurde kein grundlegendes horizontales Overflow festgestellt.
- Interaktive Basiselemente sind überwiegend mindestens 44 Pixel hoch.

Probleme:

- Sechs gleich gewichtete Haupttabs sind auf Mobilgeräten zu eng; Unicode-Zeichen und Emoji bilden kein konsistentes Icon-System.
- Dieselbe Bottom-Navigation bleibt auf Desktop bestehen; der Inhalt bleibt auf 820 Pixel begrenzt und verschenkt Arbeitsfläche.
- „Mehr“ enthält fünf weitere, umbrechende Tabs und darunter Akkordeons: Navigation in Navigation in Navigation.
- `Verlauf` und `Leistung` sollten als gemeinsamer Bereich `Analyse` organisiert werden.
- Leerer Plan ca. 1.741 Pixel, Profil ca. 2.102 Pixel, geöffnete Anbindungen ca. 2.254 Pixel hoch; leere Tage und technische Hinweise erzeugen unnötige Länge.
- Coach zeigt eine große leere Fläche und „Dein Coach ist bereit“, während gleichzeitig eine globale Einrichtungwarnung erscheint.
- Viele Metadaten liegen bei `.62rem` bis `.68rem`; auf Mobilgeräten werden Markenheader, Seitentitel und Aktionen zusätzlich umgebrochen.
- Nach Routennavigation wird das komplette Panel fokussiert; ohne eigene Panel-Fokusgestaltung erscheint ein weißer Rahmen um die gesamte Seite.
- Es gibt 45 statische Buttons, 74 buttonbezogene CSS-Treffer, viele lokale Varianten und `!important`. Primär-, Sekundär-, Text-, Sync- und Danger-Aktionen sind nicht als ein Designsystem erkennbar.
- Login passt im kontrollierten 390-Pixel-Test korrekt; der frühere abgeschnittene Login-Screenshot wird nicht als bestätigter Defekt behandelt.

## 3. Zielbild und Informationsarchitektur

### Hauptnavigation

Die verbindliche Navigation lautet:

| Ziel | Inhalt |
|---|---|
| Coach | Gespräch, strukturierte Planartefakte, Receipts, Undo und Syncfortschritt |
| Heute | Heutige Einheit, Readiness, Check-in, Wetter, offene Rückmeldung |
| Plan | Kalender, Vorlagen, Ziele |
| Analyse | Verlauf, Leistung |
| Mehr | Profil, Anbindungen, Coach & Modell, Datenschutz, Betrieb |

Kanonische Hashes:

- `#coach`, `#today`
- `#plan/calendar`, `#plan/templates`, `#plan/goals`
- `#analysis/history`, `#analysis/performance`
- `#more`, `#more/profile`, `#more/connections`, `#more/coach`, `#more/privacy`, `#more/operations`

Bestehende Hashes (`activities`, `performance`, `planned/*`, `profile`, `settings`) bleiben als Redirect-Aliase erhalten.

### Responsive Shell

- Unter 768 Pixel: fünfteilige Bottom-Navigation.
- 768–1099 Pixel: 72 Pixel breite linke Icon-Leiste, keine Bottom-Navigation.
- Ab 1100 Pixel: 216 Pixel breite linke Navigation mit Icons, Labels, Status und Version.
- Maximale Arbeitsbreite 1280 Pixel, Gutter 16/24/32 Pixel.
- Ab 1100 Pixel: Coach-Hauptspalte bis 760 Pixel plus 320-Pixel-Kontextspalte.
- Chat-Composer und Nachrichten werden in einem eigenen Layout-/Scroll-Container geführt. Keine globalen festen Clearance-Hacks für übereinanderliegende Fixed-Elemente.

### Seitenregeln

- Kompakter Seitentitel statt wiederholtem großem Markenheader auf jeder Route.
- Coach: lokaler Verlauf oder Skeleton sofort, drei kohärente Schnellaktionen im leeren Zustand, kompakter Providerstatus und Inline-Receipts.
- Heute: heutige Einheit zuerst, danach Readiness, Check-in, Wetter und Rückmeldung; höchstens eine Primäraktion pro Karte.
- Plan: Mobil Agenda mit Wochenleiste; leere Tage als kompakte Zeilen. Desktop Wochenansicht mit ausgewähltem Tag und Detailinspektor. Tab „Bibliothek“ wird „Vorlagen“.
- Analyse: Segmente `Verlauf` und `Leistung`; Filterleiste auf Mobilgeräten als Filter-Sheet.
- Mehr: Mobil zuerst eine Liste mit Status und Chevron, danach Detailseite mit Zurücknavigation. Tablet/Desktop: Einstellungsnavigation links, Detailinhalt rechts. Danger Zone separat.

### Designsystem

- Farbsemantik: Grün Primär/Erfolg, Orange Warnung, Rot Gefahr, Blau Information/Links.
- Höchstens drei Surface-Ebenen und eine Schattenstufe.
- Abstände 4/8/12/16/24/32 Pixel; Radien 10/14/18 Pixel.
- Mindestschriftgröße 12 Pixel für Metadaten; Hauptskala 14/16/20/28/36 Pixel.
- Lokales Inline-SVG-Sprite statt Unicode- und Emoji-Icons.
- Einheitliche Komponenten: `.btn` (`primary`, `secondary`, `ghost`, `danger`), `.icon-btn`, `.card`, `.status-chip`, `.segmented-control`, `.empty-state`, `.skeleton`, `.action-receipt`, `.sync-progress`, `.dialog`.
- Kein `!important` für Komponentenvarianten; maximal eine sichtbare Primäraktion je Karte/Arbeitsfläche.
- Fokus auf Überschrift oder Landmark-Anker setzen, niemals den Standardfokusrahmen des gesamten Panels zeigen.

## 4. Zielarchitektur, Daten und APIs

### Modularer Monolith

`server.py` bleibt Composition Root und HTTP-Routing-Schicht. Fachlogik wird in Coach-, Planning-, Sync- und DB-Dienste verschoben. Frontend-Module behalten Plain-JS/PWA ohne Framework; `app.js` wird auf Initialisierung und Eventverdrahtung reduziert.

### Schema 6

Additive, transaktionale Migration von Schema 5:

- `planning_state`: globale Planungsrevision.
- `coach_plan_artifacts`: Entwürfe mit Conversation/Turn, Basisrevision und `draft|committed|superseded`.
- `coach_commands`: eindeutige `client_turn_id`, Intent, Ziel, Status, Receipt und Fehlerklasse.
- `sync_jobs`: persistente, wiederaufnehmbare Jobs.
- `sync_job_items`: einzelne Operationen, Payload-Hash, Remote-ID, Versuche und Fehlerklasse.
- `provider_sync_cursors`: Cursor/High-Water-Mark je Provider und Datenstrom.
- `planned_units`: Planreferenz, Revision, Tombstone und erzeugendes Kommando.

### Öffentliche Schnittstellen

- `POST /api/chat`: verpflichtendes `client_turn_id`; Antwort enthält `command_receipts` und `sync_job_ids`.
- `POST /api/planning/commands`: Artefakt, erwartete Revision und validierte Operationen; idempotent über `client_turn_id`.
- `POST /api/sync/jobs`: Provider `intervals|garmin|calendar|weather`, Typ `refresh|plan_push|historical_backfill`; antwortet mit HTTP 202.
- `GET /api/sync/jobs/{id}` und `POST /api/sync/jobs/{id}/resolve`.
- `GET /api/state/events?since={event_id}` als authentifizierter SSE-Strom für Provider-, Job-, Planungs- und Coach-Ereignisse.
- Bootstrap-Schema 3 liefert lokalen Zustand, Chatverlauf/Skeleton, Planrevision, Providerzustände und laufende Jobs ohne Provider-Netzwerkaufruf.
- Preview/Confirm/Execute bleiben höchstens eine Übergangsrelease als Adapter; neue UI und neuer Coach verwenden sie nicht für normale Planung/Sync.

### Coach-Intent und Werkzeuge

- Vor jedem Turn isolierter Structured-Output-Intent mit niedriger Reasoning-Stufe. Eingabe: aktuelle Nachricht, lokale Artefaktreferenzen und erlaubte Ziele; keine ungefilterten Providertexte.
- Intentwerte: `advice|local_action|remote_sync|needs_clarification`, Operationen, Zielsystem, Artefaktbezug, Ambiguitäten und Autorisierungsumfang.
- Bei Intent-Ausfall einmal wiederholen, danach Mutation sperren; keine Regex-Autorisierung.
- Tool-Liste bleibt in allen Folgerunden erhalten; maximal sechs Tool-Runden.
- Tools: `read_training_state`, `stage_training_plan`, `commit_training_plan`, `apply_training_changes`, `manage_training_templates`, `start_provider_refresh`, `start_intervals_plan_sync`, `get_sync_job`, `resolve_training_sync_conflict`, `undo_training_change`.
- `stage_training_plan` erzeugt einen referenzierbaren Entwurf; eindeutige Aktionswünsche dürfen im selben Turn direkt committen.
- „Jetzt speichern“ referenziert das jüngste offene Artefakt desselben Gesprächs. Bereits gespeicherte Artefakte liefern `already_applied`.
- Maximal 28 geänderte Einheiten pro Kommando, maximal 366 Einheiten/730 Tage pro Artefakt.

### Provider- und DB-Verhalten

- Nach DB-Initialisierung zuerst HTTP bereitstellen, danach Intervals/Garmin als Jobs einreihen.
- Intervals: interaktives 90-Tage-Fenster und Zukunft priorisieren; Historie anschließend per Cursor in niedriger Priorität ergänzen.
- Garmin: neueste 30 Tage priorisieren, maximal zwei tägliche Aufrufe parallel, historische Blöcke resumable; gleicher Capability-Fehler nach drei Versuchen für 24 Stunden pausieren.
- iCal: Wiederholungen in das angeforderte Fenster vorspulen und Occurrence-Limits anwenden.
- Wetter ohne Standort ist `not_configured`, nicht `{}`.
- SQLCipher: ein Writer, vier Reader, Schlüsselung einmal je Verbindung, Netzwerk nie unter DB-Lock, kontrollierter Pool-Drain beim Restore.

## 5. Abhakbare Implementierungsaufgaben

### 0. Vorbereitung und Baseline

- [ ] `AGENTS.md`, `public/AGENTS.md` und `tests/AGENTS.md` vollständig lesen.
- [ ] Worktree/Branch und Arbeitsregeln prüfen; Primärcheckout, `.env`, `/data` und `Task.md` nicht verändern.
- [x] Baseline mit `python -m unittest discover -s tests -v`, `python -m py_compile server.py tests/test_server.py` und Docker-Build dokumentieren.

**Subsysteme:** Git, Tests, Docker.  
**Definition of Done:** Branch basiert auf aktuellem `origin/develop`; Baseline und bekannte Skips dokumentiert.  
**Tests:** Baseline-Befehle, `git status`, kein Secret-Scan-Treffer.  
**Seiteneffekte:** Nur temporäre Test-/Buildartefakte; keine Live-Daten.  
**Evidence:**

- Ergebnis: 344 Tests grün, 3 erwartete SQLCipher-Skips; beide Syntaxchecks grün (Bytecode temporär ausgelagert); `docker build -t ai-coach:local .` grün; Branch basiert auf `origin/develop` `c9a25e9`. Zeitabhängige Test-Fixtures stabilisiert in Commit `0dd1ca0`.

### 1. Schema-6-Migration und DB-Manager

- [x] Migrationen und Repositories für alle neuen Tabellen sowie additive `planned_units`-Felder implementieren.
- [x] SQLCipher-Connection-Manager mit Writer/Reader-Pool, Unit of Work, Sessioncache und Restore-Drain einführen.
- [x] Bestehende Daten, Tombstones, Backups und Recovery-Pfade erhalten.

**Subsysteme:** `server.py`, `backend/db`, Migrationen, Backup.  
**Definition of Done:** Schema 5 migriert deterministisch nach 6; Wiederholung ist sicher; alte Daten bleiben lesbar.  
**Tests:** Migration von temporärer DB, Rollback, Parallel-Reads, Writer-Serialisierung, Sessioninvalidierung, Restore.  
**Seiteneffekte:** Keine Migration gegen `/data`; keine Datenlöschung außerhalb eines getesteten Restore-Flows.  
**Evidence:**

- Ergebnis: `python -m unittest discover -s tests -v` mit 347 Tests grün und 3 erwarteten SQLCipher-Skips; fokussierte DB-Manager-, Migrations-, Export- und Delete-Tests grün; beide Syntaxchecks grün; `docker build -t ai-coach:local .` grün. Commit: `4a25ad4`.

### 2. Persistente Providerjobs

- [x] `sync_jobs`, `sync_job_items`, Cursor, Statusautomat, Retry und Fortschrittsaggregation implementieren.
- [x] Jobs überleben Prozessneustart und Client-Trennung.
- [x] Fehlerklassen und Diagnosefelder strikt redigieren.

**Subsysteme:** `backend/sync`, Provideradapter, HTTP-Handler, Diagnostics.  
**Definition of Done:** Jeder Job liefert `queued|running|completed|partial|failed`; Status ist abrufbar und resumable.  
**Tests:** Queue, Retry, Restart-Fortsetzung, Teilfehler, Idempotenz, Status-API, Redaction.  
**Seiteneffekte:** Kein synchrones Warten auf Providerantworten im Request-Thread.  
**Evidence:**

- Ergebnis: `python -m unittest discover -s tests -v` mit 352 Tests grün und 3 erwarteten SQLCipher-Skips; Job-Vertrag, Claim/Resume, Retry, Completion und Schema-/API-Regressionen grün; Syntaxcheck und `docker build -t ai-coach:local .` grün. Commit: `a3a780d`.

### 3. Inkrementelle Provider-Synchronisation

- [x] Intervals-Sync in priorisiertes 90-Tage-Fenster plus historische Backfilljobs teilen.
- [x] Garmin-Tagesabfragen begrenzen, deduplizieren und Capability-Circuit-Breaker einführen.
- [x] iCal-Fensterberechnung und Occurrence-Limit korrigieren; Wetterzustände typisieren.
- [x] Vollständige Rohdaten/Snapshots erhalten; nur Coach-Projektion begrenzen.

**Subsysteme:** Intervals, Garmin, Kalender, Wetter, Context-Projektion.  
**Definition of Done:** Initiale UI-Bedienbarkeit ist unabhängig von Backfill; regulärer Sync lädt Cursorfenster.  
**Tests:** Mockprovider mit 2000er-Historie, Cursorüberlappung, Garmin-Fehlerwiederholung, iCal-Recurser, Rohdaten-/Projection-Assertions.  
**Seiteneffekte:** Keine echten Providerkonten oder Tokens; keine Snapshot-Trunkierung.  
**Evidence:**

- Ergebnis: `python -m unittest discover -s tests -v` mit 353 Tests grün und 3 erwarteten SQLCipher-Skips; Intervals-Rohdaten-/Fenster-, Garmin-Deduplizierungs-/Parallelitäts-/Circuit-Breaker-, iCal- und Wetterstatus-Tests grün; Syntaxcheck und `docker build -t ai-coach:local .` grün. Commits: `293ada5`, `5676ebe`.

### 4. Structured Intent und Coach-Orchestrator

- [x] Intent-Schema, isolierten Intent-Schritt, Autorisierungsumfang und Fail-closed-Verhalten implementieren.
- [x] Tool-Loop mit maximal sechs Runden und unveränderter Tool-Liste in Folgerunden implementieren.
- [x] Conversation-/Artifact-Referenzen und `client_turn_id` durchgängig propagieren.

**Subsysteme:** Coach, OpenAI-Client, Conversation-State, HTTP-Chat.  
**Definition of Done:** Natürliche deutsche Aktionssätze werden ohne Regex erkannt; Beratungsfragen mutieren nicht.  
**Tests:** „Plan sieht gut aus …“, „Jetzt speichern“, Hypothese, Mehrdeutigkeit, Intent-Timeout, Mehrfach-Toolrunde, Wiederholung.  
**Seiteneffekte:** Keine externen Providertexte im Intentprompt; keine unautorisierte Mutation.  
**Evidence:** `- Test: python -m unittest discover -s tests -v` — 360 Tests grün, 3 erwartete SQLCipher-Skips; zusätzlich Syntaxcheck und fokussierte Intent-/Job-Tests grün. `POST /api/chat` und `/api/chat/stream` verlangen `client_turn_id`; Wiederholungen sind über `coach_commands` idempotent, Providerrefreshes werden als persistente Jobs eingereiht. Commit: `312ad2a`.

### 5. Vollständige Planungs- und Sync-Tools

- [x] Lesen, Entwurf, Commit, Änderung, Vorlagen, Providerrefresh, Intervals-Push, Konfliktlösung und Undo als typisierte Tools anbinden.
- [x] Atomare Revisionen, Limits, Payload-Hashes und `already_applied` implementieren.
- [x] Routine-Preview-/Confirm-/Execute-Aufrufe aus Coach und UI entfernen; adaptive Replan-Ausnahme erhalten.

**Subsysteme:** Planning-Service, Tool-Registry, lokale Bibliothek, Intervals-Push.  
**Definition of Done:** Ein eindeutiger Benutzerauftrag beendet den gesamten lokalen Workflow in demselben Turn; Remotejobs werden eindeutig eingereiht.  
**Tests:** 28er-Batch, Revision, Konflikt, Undo, Remote-Job, keine Duplikate, adaptive Vorschau.  
**Seiteneffekte:** Kein stiller Remote-Write; keine Teilcommits.  
**Evidence:** `- Test: python -m unittest discover -s tests -v` — 363 Tests grün, 3 erwartete SQLCipher-Skips; `python -m py_compile server.py tests/test_server.py`, verbotene-Dialog-/Protected-Path-Scan und `docker build -t ai-coach:local .` (Image-SHA `93ba494c3994c18ebdb4d4a4f459185452e7cf2634f1cde5038e3809dac65d15`) grün. Routine-UI nutzt zugänglichen Bestätigungsdialog, direkte lokale Mutationsendpunkte und persistente `plan_push`-Jobs; adaptive Replan bleibt als dokumentierte Preview-/Confirm-/Execute-Ausnahme. Commit: `f775e03` (zuvor `eec187a`, `649ccfb`).`

### 6. Bootstrap v3 und SSE

- [x] Lokalen Bootstrap ohne Providerwartezeit implementieren.
- [x] Chatverlauf/Skeleton, lokale Planung, Providerzustände und laufende Jobs initial liefern.
- [x] SSE-Ereignisse, Reconnect und Gap-Recovery implementieren.

**Subsysteme:** HTTP API, State Store, SSE, Bootstrap.  
**Definition of Done:** Shell ist sofort bedienbar; Providerstatus ist `not_configured|loading|ready|stale|degraded|error` statt leerer Objekte.  
**Tests:** Bootstrap ohne Netzwerk, SSE-Reconnect, verpasste Ereignisse, Auth/CSRF, Jobfortschritt.  
**Seiteneffekte:** Keine Netzwerkanfrage im Bootstrap-Request.  
**Evidence:** Ergebnis: python -m unittest discover -s tests -v — 366 Tests grün, 3 erwartete SQLCipher-Skips; python -m py_compile server.py tests/test_server.py grün; Bootstrap-Spezialtests inklusive Offline-/Ein-Verbindungsprüfung, Schema 3, Providerstatus und lokalem State grün; SSE-Cursor-, Jobfortschritt-, Retention-Gap- und Frontend-Reconnect-Tests grün. Netzwerkprüfung bestätigte github_release_status(refresh=False) im Bootstrap; native-Dialog- und Protected-Path-Scan grün. Commit: 305d534.

### 7. Responsive App-Shell und Designsystem

- [ ] Route-Modell und alte Hash-Aliase auf die fünf Hauptziele umstellen.
- [ ] Mobile Bottom-Navigation, Tablet-Iconrail und Desktop-Sidebar implementieren.
- [ ] SVG-Sprite, Button-, Card-, Status-, Empty-, Skeleton-, Receipt- und Dialogkomponenten einführen.
- [ ] Panel-Fokusrahmen, Fixed-Clearance-Hacks, `!important`-Buttonvarianten und native Confirm/Prompt entfernen.

**Subsysteme:** `public/index.html`, `navigation.js`, `components.js`, `styles.css`, `app.js`.  
**Definition of Done:** Keine doppelte Navigation; pro Ansicht klare Hierarchie; alle fünf Viewports ohne Overlay/Overflow.  
**Tests:** DOM-/Keyboardprüfung, Zoom 200 %, Reduced Motion, Safe Area, langes deutsches Label, Dialogfokus.  
**Seiteneffekte:** Kein Framework- oder Buildsystemwechsel.  
**Evidence:** `- Viewport/Commit: …`

### 8. Coach-, Heute-, Plan-, Analyse- und Mehr-Redesign

- [ ] Coach mit sofortigem Verlauf/Skeleton, Schnellaktionen, Providerstatus und Inline-Receipts umsetzen.
- [ ] Heute nach Priorität ordnen; Plan als Agenda/Week-Grid mit kompakten Leerzuständen umsetzen.
- [ ] Verlauf/Leistung unter Analyse zusammenführen; Filter als gemeinsame Komponente umsetzen.
- [ ] Mehr als mobile Liste und Desktop-Einstellungsrail implementieren; technische Details und Danger Zone trennen.

**Subsysteme:** `views.js`, `forms.js`, `components.js`, `state.js`, Styles.  
**Definition of Done:** Keine Seite zeigt widersprüchlich „bereit“ und „Einrichtung nötig“; jede Aktion hat einen sichtbaren Status.  
**Tests:** Leeren, befüllten, Loading-, Offline-, Fehler-, Sync- und Konfliktzustand je Route prüfen.  
**Seiteneffekte:** Fachansichten bleiben Transparenz/Reparatur; Coach bleibt primäre Aktionsfläche.  
**Evidence:** `- Screenshot/Viewport/Commit: …`

### 9. Backend-, Integrations- und Dialogregressionstests

- [ ] Alle gemeldeten deutschen Dialoge als End-to-End-ähnliche Mocktests abdecken.
- [ ] Tool- und API-Idempotenz, Revision, Jobfortsetzung und Redaction testen.
- [ ] Keine Routineaktion darf einen nativen Confirm-/Prompt-Aufruf auslösen.

**Subsysteme:** `tests/`, Coach, Planning, Sync, UI-Vertragsprüfungen.  
**Definition of Done:** Jeder Fehlerfall liefert ein korrektes Receipt statt einer erfundenen „nichts gespeichert“-Meldung.  
**Tests:** Vollständige Unit-/Integrationstest-Suite, `rg`-Prüfung auf verbotene Aufrufe, temporäre DB/Mockprovider.  
**Seiteneffekte:** Keine Tests gegen echte Konten, `.env` oder `/data`.  
**Evidence:** `- Test/Commit: …`

### 10. Vollständige visuelle Viewport-Abnahme

- [ ] Jede Route in 320×568, 390×844, 768×1024, 844×390 und 1440×1000 prüfen.
- [ ] Leere, befüllte, Loading-, Fehler-, Offline-, Konflikt- und laufende-Sync-Zustände prüfen.
- [ ] Tastatur, 200-%-Zoom, Kontrast, Fokus, Dialoge, Safe Area, Enter/Shift+Enter, Mikrofon und PWA-Refresh prüfen.

**Subsysteme:** Browser, Docker-Runtime, alle Frontend-Routen.  
**Definition of Done:** Kein abgeschnittener Text/Dialog, kein verdeckter Inhalt, maximal fünf Haupttabs, Icons und Buttons konsistent.  
**Tests:** Manuelle Browsermatrix mit sanitized fixture/mock state; Screenshots nicht in Git aufnehmen.  
**Seiteneffekte:** Nur isolierte temporäre Runtime/Profile.  
**Evidence:** `- Viewportmatrix/Screenshotpfad/Commit: …`

### 11. Docker-, Sicherheits- und Abschlussprüfung

- [ ] `python -m unittest discover -s tests -v` und beide Syntaxchecks erneut ausführen.
- [ ] `docker build -t ai-coach:local .` ausführen.
- [ ] Security-/Secret-/Redaction-Prüfung und Healthcheck ausführen.
- [ ] Assetquerys und Service-Worker-Cache gemeinsam aktualisieren; `APP_VERSION` nur über den Releaseprozess ändern.
- [ ] Diff, Branch, Migration, Datenpfade und Dokumentation abschließend prüfen.

**Subsysteme:** CI, Docker, Release, Security, README.  
**Definition of Done:** Alle Tests grün, keine Secrets, keine Datenbankmutation außerhalb getesteter Pfade, Arbeitsbaum sauber.  
**Tests:** Unit, Syntax, Docker, Health, Secret-Scan, Browser-Smoke.  
**Seiteneffekte:** Keine Veröffentlichung, kein PR und kein Push von Runtime-/Testdaten.  
**Evidence:** `- Finale Befehle/Ergebnisse/Commit: …`

## 6. Arbeitsweise und Commitfolge

1. `refactor(db): add schema v6 and sqlcipher connection manager`
2. `feat(sync): add persistent resumable provider jobs`
3. `feat(sync): optimize incremental provider synchronization`
4. `feat(coach): execute natural planning and sync commands`
5. `refactor(api): add bootstrap v3 and state event stream`
6. `refactor(ui): introduce responsive shell and design system`
7. `feat(ui): redesign coach planning analysis and settings`
8. `test: cover coach commands sync jobs and responsive flows`

Jeder Commit bleibt klein, verwendet Conventional Commits und wird vor dem nächsten Paket getestet. Luna aktualisiert die Checkboxen erst nach dem zugehörigen Commit und trägt Commit-SHA sowie Testergebnis im Evidence-Feld ein.

## 7. Direkt nutzbarer Startprompt für GPT-5.6 Luna

> Du arbeitest im Repository `ai-coach` auf dem Branch `feat/coach-first-architecture`. Lies zuerst alle `AGENTS.md`-Dateien und dieses Handover-Dokument vollständig. Arbeite ausschließlich im vorgesehenen Worktree. Verändere niemals `.env`, `/data`, SQLCipher-Datenbank, Garmin-Tokens, Backups oder `Task.md` im Primärcheckout. Arbeite die Tasks strikt in Reihenfolge ab. Halte dich an die Coach-first-Autorisierungsregeln, die Schema-/API-Verträge, die Provider-Rohdaten-Grenze und die responsive UI-Spezifikation. Für jeden Task: implementieren, relevante Tests ausführen, Evidence mit Ergebnis und Commit-SHA eintragen, erst dann `[ ]` zu `[x]` ändern. Bei einem Fehler bleibt der Task offen; keine stillen Workarounds, keine Regex-Autorisierung, keine nativen Confirm-/Prompt-Dialoge und keine impliziten Remote-Schreibvorgänge. Vor Abschluss müssen Unit-/Syntaxtests, Docker-Build, Security-/Redaction-Prüfung und die komplette visuelle Viewportmatrix erfolgreich sein.

## 8. Abschlusskriterien für das Handover

- [ ] Alle Implementierungstasks sind mit Evidence belegt.
- [ ] Der gemeldete Plan-/Kalenderdialog speichert im richtigen Turn und liefert keinen falschen „nichts gespeichert“-Text.
- [ ] Coach kann lokale Planung, Vorlagenänderungen, Undo, Providerrefresh, Intervals-Sync, Jobs und Konfliktlösung über Werkzeuge ausführen.
- [ ] Initiale Shell, Chatverlauf/Skeleton, Wetterzustand und Syncfortschritt sind nachvollziehbar.
- [ ] Navigation, Tabs, Buttons, Layouts und Breakpoints erfüllen die visuelle Abnahme.
- [ ] Daten-, Sicherheits-, SQLCipher- und Remote-Sync-Grenzen sind unverändert eingehalten.
- [ ] Alle Tests und der Docker-Build sind grün; der Arbeitsbaum enthält keine Runtime- oder Geheimnisdateien.
