# Architektur-, Pattern-, Design- und UX-Review – Intervals Coach

Datum: 2026-10-07 · Review-Gate: Orchestrator (alle Subagent-Befunde wurden am `path:line` selbst verifiziert; unbelegte Aussagen wurden verworfen oder herabgestuft)

## Review scope

- **Commit:** `361290a13562f774915eefc950922e9e0d356e7e`, Branch `t3code/deep-architecture-ux-review`, Worktree `C:\Users\Dev\.t3\worktrees\ai-coach\t3code-578b0d53`.
- **Baum-Status:** sauber bis auf diesen Bericht (unversioniert, nicht committet). `node_modules` stammt aus `npm ci` und ist ignoriert.
- **Art:** vollständiges Repository-Review mit Schwerpunkt **Codequalität, Architektur, Software-Patterns, Design und UX**. Security/Privacy, Sync und Coach-Vertrag wurden auf Architektur- und Vertragsebene geprüft. Eine Security-Tiefenprüfung (Codex Security) war nicht Teil des Auftrags.
- **Angewendete Regeln:** `AGENTS.md` (Root, `public/`, `tests/`) und `.codex/skills/ai-coach-codebase-review` (Checkliste, Coach-first-Audit, Report-Template).
- **Ausgeschlossen (nie gelesen):** `.env`, `data/`, Datenbanken, Garmin-Token, Backups, Laufzeit-Logs mit Athletendaten.
- **Zusatzanforderung des Nutzers:** Der Plan entfernt **Gemini als API-Provider vollständig** und bindet nur noch **OpenAI-kompatible APIs** an (siehe Phase 2).
- **Laufzeit:** eigener, wegwerfbarer Fixture-Container `ai-coach-review-578b` (Image `ai-coach:review-361290a`, `127.0.0.1:8094`, `--read-only`, `--cap-drop=ALL`, tmpfs `/data`). Er ist nach dem Review entfernt worden. Fremde Container wurden nicht angefasst.
- **Methodik:** Komponenten-/Vertrauensgrenzen-Map, Import-Graph-Analyse (341 Module, 1394 Kanten, SCC- und Paketzyklen), Komplexitätsmetriken (ruff `PLR0913/PLR0911/C901/PLR0915/PLR0912`), Datei-Größenverteilung, End-to-End-Flusstraces (Browser → HTTP → Use Case → Persistenz/Provider), SOLID-/Layering-/Repository-Pattern-Prüfung, WCAG-/Geometrie-Prüfung in vier Viewports, Playwright gegen frische Fixture-Runtime.

## Findings

Sortiert nach Schweregrad und Wirkung. Verwandte Symptome sind unter einer Ursache zusammengefasst.

### [P2] Mobiler Composer wird von der Bottom-Navigation vollständig verdeckt — public/styles.css:428

- **Evidenz:**
  - Unter 768 px ist `.composer` `position: sticky; bottom: 12px; z-index: 4` (`public/styles.css:425-428`).
  - Die `.bottom-nav` ist `position: fixed; bottom: max(12px, env(safe-area-inset-bottom)); z-index: 5` (`public/styles.css:966-970`).
  - Das Padding von `#chatPanel` (`public/styles.css:1041`) schützt den Composer nur am Scroll-Ende. Sonst klebt er bei 12 px – also exakt unter der Navigation.
- **Trigger:** Ein frisches Laden von `#coach` bei 375×667 (iphone-se) mit vorhandener Chat-Historie, wenn der Chat nicht ganz unten steht.
  - Gemessen: `scrollY` 1173 von max. 1286, Composer bei 595–655 px, Nav bei 594–655 px.
  - `elementFromPoint` auf der Textarea liefert das Nav-Icon. Alle fünf Punkte der Oberkante treffen die Nav.
  - Zweimal reproduziert, nach Login und nach Reload. Nach Sprung ans Ende ist der Composer erreichbar.
- **Impact:** Die primäre Coach-Eingabe ist unsichtbar und nicht antippbar. Nur der Sprung-Button ist sichtbar. Das verletzt das Coach-first-Prinzip auf dem wichtigsten Viewport.
- **Remediation:**
  - Ein Layout-Token `--bottom-nav-offset` einführen (Nav-Höhe + Abstand + `env(safe-area-inset-bottom)`).
  - `.composer` auf Mobil `bottom: var(--bottom-nav-offset)` geben; bei `html.chat-keyboard-open` zurück auf 12 px.
  - Zusätzlich den Chat beim Laden deterministisch ans Ende scrollen.
- **Regressionstest:** Playwright `mobile-small` und `mobile` laden mit langer Historie, scrollen nicht und prüfen `elementFromPoint(textarea-Mitte) === textarea` sowie die Bounding-Box-Disjunktheit von Composer und Nav.
- **Confidence:** high

### [P2] Kontrast der erledigten Laufeinheiten unter WCAG AA — public/styles.css:751

- **Evidenz:**
  - `.planned-entry.is-completed .planned-session-header` setzt weißen Text auf `var(--session-color)` (`:751`) bei `.72rem` (`:746`).
  - Laufen `#288b38` (`:742`) ergibt nur **4,34:1** (gefordert 4,5:1). Kraft `#a56821` liegt mit 4,56:1 knapp darüber, Rad mit 5,46 und Schwimmen mit 5,23 bestehen.
  - axe meldet `color-contrast` (serious) im Kalender des geseedeten Fixtures.
- **Trigger:** Eine erledigte Laufeinheit im Kalender.
- **Impact:** Die Lesbarkeit für sehbeeinträchtigte Nutzer ist reduziert, und der eigene WCAG-Anspruch ist verletzt.
  - Die CI-Fixture enthält keine erledigten Einheiten, deshalb ist die Lücke im axe-Test unsichtbar.
- **Remediation:** Sportfarben als Tokenpaar `--session-color`/`--session-on-color` mit geprüftem Kontrast ≥ 4,5:1 führen (z. B. Laufen dunkler, etwa `#1f7a2e`). Die Light-Theme-Variante gleich mitprüfen.
- **Regressionstest:** Die E2E-Fixture um erledigte Einheiten aller vier Sportarten erweitern; axe `color-contrast` im Kalender für beide Themes.
- **Confidence:** high

### [P2] Provider-Retry-Hinweis geht auf dem Weg zum Client verloren — backend/providers/http.py:710

- **Evidenz:**
  - `providers/http.py:710-712` und `providers/openai.py:1375-1377` setzen das Attribut `retry_after_seconds` auf den Fehler.
  - `AppError` kennt nur `retry_after` (`backend/errors.py:35-41`), und `public_error_payload` serialisiert nur dieses Feld (`backend/errors.py:55-56`).
  - Der Streaming-Pfad im Frontend wertet `retry_after` zusätzlich nicht aus (`public/coach.js:254`), im Gegensatz zu `public/api.js:33`.
- **Trigger:** Ein 429 oder 503 des Providers mit `Retry-After`-Header.
- **Impact:**
  - Der Client erhält keinen Wartehinweis und wiederholt zu früh oder zeigt einen generischen Fehler.
  - Das schafft zwei konkurrierende Namen für denselben Vertrag (Pattern-Drift).
- **Remediation:**
  - Ein einziges Feld `AppError.retry_after` verwenden; Provider-Adapter setzen nur noch dieses.
  - `coach.js` nutzt denselben Fehler-Parser wie `api.js` (siehe Phase 7).
- **Regressionstest:**
  - Unit: Provider-Fehler mit `Retry-After: 7` → JSON `retry_after: 7`.
  - Playwright: gemockter 429 im Stream zeigt einen Wartehinweis.
- **Confidence:** high

### [P2] Upstream-HTTP-Status leckt in den App-HTTP-Vertrag — backend/errors.py:60

- **Evidenz:**
  - `public_app_error_status` übersetzt nur `401` + `authentication_or_permission` → 502 (`backend/errors.py:60-64`).
  - Andere Upstream-Status, etwa Gemini 403/404 (`providers/http.py:708`), werden unverändert an `/api/transcribe` (`http_api/transcribe_post.py:23-34`) und `/api/chat/stream` durchgereicht.
  - Das Frontend behandelt 403 und 404 identisch (`public/coach.js:103`).
- **Trigger:** Ein Provider antwortet 403 oder 404, z. B. bei falschem Modell oder fehlender Berechtigung.
- **Impact:** Ein App-403 wird als lokale Autorisierungsablehnung und ein App-404 als fehlende Route fehlinterpretiert. UI und Diagnose können Upstream- und lokale Ursache nicht unterscheiden.
- **Remediation:** Eine Regel für alle Provider-Fehler: Upstream 4xx-Konfig/Auth → 502 mit `reason`; Upstream 5xx/Timeout → 503; Upstream 429 → 429 mit `retry_after`. Die Gemini-Ursache entfällt mit Phase 2, die Regel bleibt nötig.
- **Regressionstest:** Eine parametrisierte Tabelle `upstream_status → app_status/reason` für Chat-Stream und Transkription.
- **Confidence:** high

### [P2] HTTP-Transport kennt konkrete Provider und mutiert Provider-Zustand — backend/providers/http.py:722

- **Evidenz:**
  - `_provider_error_details` (`providers/http.py:722-750`) importiert `openai`/`gemini` lazy und schreibt in `provider_state`.
  - Der Import-Graph zeigt eine SCC `providers.{gemini, http, openai, state}`. Sie ist kein eager Zyklus, aber eine Design-Kopplung.
- **Trigger:** Jeder neue Provider erfordert eine Änderung am generischen Transport.
- **Impact:** Verletzt DIP/SRP und OCP; die Fehlerklassifikation ist nicht isoliert testbar.
- **Remediation:** Ein Interface `ProviderErrorClassifier`, das pro Adapter injiziert wird. Der Transport kennt nur das Interface; Statusupdates erfolgen im Adapter.
- **Regressionstest:**
  - Ein Architekturtest: `providers/http.py` importiert keinen konkreten Adapter.
  - Ein Unit-Test pro Classifier.
- **Confidence:** high

### [P2] Schichtverletzungen: Provider-Adapter importieren Domänenlogik — backend/providers/intervals_client.py:13

- **Evidenz:**
  - Provider-Adapter importieren Domänenlogik:
    - `providers/intervals_client.py:13-16` importiert `planning.context`, `planning.workouts` und `sync.gates`;
    - ebenso `providers/weather.py:10-12` und `providers/calendar.py:22-24`.
  - Umgekehrt importieren `planning/workouts.py:10-15` und `planning/planned_units.py:16-18` `providers.workout_text`, obwohl das Workout-Text-Format eine Planungsregel ist.
  - Daraus entstehen die Paketzyklen planning↔providers und providers↔sync.
- **Trigger:** Strukturell, bei jeder Änderung an Planungsregeln oder Adaptern.
- **Impact:**
  - Adapter sind nicht austauschbar oder isoliert testbar.
  - Domänenregeln hängen am Transportformat.
  - Das erschwert die geplante Provider-Abstraktion (Phase 2).
- **Remediation:**
  - `workout_text` nach `planning/` verschieben.
  - Adapter liefern nur Provider-DTOs; das Mapping erfolgt im Use Case (`sync/`).
  - Sync-Gates werden als Parameter oder Callback injiziert.
- **Regressionstest:** Eine AST-basierte Layer-Matrix (Phase 9), die `providers → {planning, sync, athlete, coach}` verbietet.
- **Confidence:** high

### [P2] Domänenpakete bilden Zyklen und lesen Sync-Snapshots direkt — backend/athlete/assembly.py:25

- **Evidenz:**
  - Paketzyklen:
    - activities↔performance (`performance/activity_validation.py:8`, `activities/read_service.py:15`, `activities/detail_store.py:10`);
    - athlete↔performance (`athlete/equipment.py:11`, `athlete/tag_impact.py:7`);
    - performance↔planning (`planning/daily_context_service.py:10`, `planning/season_preparation.py:11`);
    - activities↔sync und athlete↔sync.
  - Domänen lesen `sync.snapshots.latest_snapshot` direkt (`athlete/assembly.py:25`, `activities/read_service.py:83-86`, `weather/assembly.py:10-12`).
  - Private Konfliktregeln werden lazy importiert (`planning/changes.py:229`, `planning/replacement.py:51` → `_calendar_items_conflict`), obwohl kein echter Zyklus vorliegt.
- **Trigger:** Strukturell.
- **Impact:**
  - Keine klare Abhängigkeitsrichtung.
  - Änderungen am Snapshot-Format brechen mehrere Domänen.
  - Lazy-Imports verschleiern Kopplung, und private Symbole werden zur API.
- **Remediation:**
  - Eine Read-Port-Schnittstelle `ProviderSnapshotReader` in `sync/` einführen und per Assembly injizieren.
  - Gemeinsame Typen in ein neutrales Modul (z. B. `performance/models.py` oder `activities/models.py`) heben.
  - Die Konfliktregel als öffentliche Funktion `planning.conflicts.calendar_items_conflict` bereitstellen.
- **Regressionstest:** Ein Layer-Matrix-Test plus Zyklusfreiheit auf Paketebene (Allowlist mit sinkendem Ratchet).
- **Confidence:** high

### [P2] Uhrzeit wird an mehreren Stellen direkt gelesen statt über den Clock-Port — backend/sync/jobs.py:163

- **Evidenz:** `providers/intervals_client.py:36-39` und `sync/jobs.py:163-168` rufen `datetime.now` direkt auf, obwohl `runtime/clock.py:8` existiert.
- **Trigger:** Tests oder Zeitzonenwechsel; athletenlokale Zeit.
- **Impact:** Inkonsistente Zeitbasis; nicht deterministisch testbar (Datums-/Zeitzonenfehler sind in Sync-Logik besonders teuer).
- **Remediation:** Den Clock injizieren; eine Lint-Regel (ruff `DTZ` und banned-api) verbietet `datetime.now` außerhalb von `runtime/clock.py`.
- **Regressionstest:** Ein Sync-Job-Test mit fixem Clock über Mitternacht und DST.
- **Confidence:** high

### [P2] Planungsdatum akzeptiert beliebige Suffixe — backend/planning/changes.py:47

- **Evidenz:**
  - `str(value or "").strip()[:10]` schneidet ab, statt zu validieren (`planning/changes.py:47`, analog `:163`, `:197`, `:216`, `:487`).
  - `nutrition/models.py:22` validiert dagegen strikt.
- **Trigger:** `"2026-10-07garbage"` oder ein ISO-Datetime mit Offset wird stillschweigend zu einem Datum.
- **Impact:**
  - Fehlerhafte Eingaben (auch Coach-Tool-Argumente) werden akzeptiert statt mit 400 abgelehnt.
  - Eine Zeitzonen-Komponente wird verworfen, statt in Athletenzeit umgerechnet zu werden.
- **Remediation:** Ein gemeinsames Value Object `LocalDate.parse` (strikt `YYYY-MM-DD` oder explizite Konvertierung von Datetime in Athletenzeit), genutzt von Planung, Ernährung und Coach-Tools.
- **Regressionstest:** Eine Tabelle gültiger und ungültiger Eingaben für die Planungs-API und das Coach-Tool `plan_change`.
- **Confidence:** high

### [P2] SQL-Zugriff außerhalb der Persistenzschicht (Repository-Pattern inkonsistent) — backend/calendar/external.py:19

- **Evidenz:**
  - Direkte `.execute(`-Aufrufe in:
    - `calendar/external.py:19,35,53,56` und `calendar/public_events.py:7,15`;
    - `http_api/library_page.py:27` und `http_api/state_versions.py:30`.
  - Dateien mit `.execute(` pro Paket: coach 22, sync 17, planning 11, http_api 7, db 5, athlete 3, backup 3, diagnostics 2, history 2, calendar 2, performance 1, nutrition 1, activities 1.
- **Trigger:** Strukturell.
- **Impact:**
  - Schemaänderungen (die laut `AGENTS.md` versioniert und migrationsgetestet sein müssen) betreffen verstreute Stellen.
  - Transaktionsgrenzen sind nicht einheitlich.
  - HTTP-Handler mit SQL verletzen die Schichtregel `http_api` → Use Case.
- **Remediation:**
  - HTTP-Handler zuerst bereinigen.
  - Danach pro Domäne ein Repository-Modul (`<domain>/store.py`) als einzigen SQL-Ort.
  - Ein Architekturtest verbietet `.execute(` in `http_api/` sofort, in anderen Paketen per Ratchet.
- **Regressionstest:** Ein AST-Scan auf `execute`-Aufrufe je Paket gegen eine sinkende Allowlist.
- **Confidence:** high

### [P2] Sync-Job-Zustandsmaschine ohne bewachte Übergänge — backend/sync/jobs.py:673

- **Evidenz:**
  - `update()` (`sync/jobs.py:673-710`) überschreibt Items ohne Statusvorbedingung, und `requeue()` (`:806-827`) nutzt nur `WHERE id=?`.
  - `claim()` (`:646-670`) und `resolve()` (`:837-858`) sind dagegen bewacht.
  - Zustandsmodell und SQL sind in einem Modul vermischt.
- **Mitigation (verifiziert):** Es gibt nur einen `SyncJobWorker` (`sync/worker_assembly.py:32`), der einzige Requeue-Aufrufer ist `sync/job_outcomes.py:92`, und es existiert kein Sync-Cancel-Pfad. **Ein Race ist derzeit nicht nachgewiesen.** Deshalb ist dies ein Design-Befund, kein Datenintegritätsdefekt.
- **Trigger:** Ein künftiger zweiter Worker, ein Cancel-Pfad oder manueller Requeue während eines laufenden Jobs.
- **Impact:** Ein abgeschlossener Job könnte stillschweigend wieder `queued` werden; die Invarianten sind nur durch Konvention geschützt.
- **Remediation:**
  - Eine explizite Übergangstabelle `ALLOWED_TRANSITIONS`.
  - Alle Statusänderungen als `UPDATE … WHERE id=? AND status IN (...)` mit Rowcount-Prüfung.
  - SQL in einem `sync/job_store.py` bündeln.
- **Regressionstest:** Ein Property-Test über alle Übergänge; `requeue` auf `succeeded` muss scheitern.
- **Confidence:** high (Design), low (Laufzeitfolgen heute)

### [P2] Gemini-Logik bläht den Konversationskern auf — backend/coach/conversation.py:22

- **Evidenz:**
  - `coach/conversation.py` mischt OpenAI-Provisioning (`:134-170`) mit Gemini-Historie, -Payload und -Transport (`:300-740`), insgesamt 57 Gemini-Treffer.
  - Die KV-Schlüssel sind doppelt definiert: `db/bootstrap.py:58-59` und `coach/conversation.py:108-110, 303-304, 369, 563`.
- **Trigger:** Strukturell.
- **Impact:** Zwei Konversationsmodelle (serverseitige OpenAI-Conversation vs. lokal rekonstruierte Gemini-Historie) in einer Klasse; hohe kognitive Last und Divergenzrisiko.
- **Remediation:** Wird durch die Gemini-Entfernung (Phase 2) aufgelöst. Danach die KV-Schlüssel als eine Konstante in `db/`.
- **Regressionstest:** `rg -i gemini backend` liefert nur noch Migrationscode und Migrationstests.
- **Confidence:** high

### [P2] God-Services mit zu vielen Abhängigkeiten — backend/nutrition/service.py:106

- **Evidenz:**
  - `NutritionService` (`nutrition/service.py:106`, Datei 1242 Zeilen) bündelt Tagebuch, Mahlzeiten, Produkte, Foto-Extraktion und Sync-Status.
  - `backup/restore.py:33` nimmt 12 Abhängigkeiten, `performance/report_service.py:22` nimmt 13 Argumente.
  - `performance/garmin_metrics.py:19` mischt Parsing, Normalisierung und Ableitung.
  - Repo-weit: PLR0913 (zu viele Argumente) 242, PLR0911 15, C901 6, PLR0915 2, PLR0912 1.
  - Größte Dateien: `providers/openai.py` 1868, `coach/tools.py` 1318, `coach/proposals.py` 1214 Zeilen.
- **Trigger:** Strukturell.
- **Impact:** Änderungen haben großen Wirkradius, Tests brauchen viele Mocks, und Verantwortlichkeiten sind unklar.
- **Remediation:**
  - `NutritionService` in `DiaryService`, `MealLibraryService`, `ProductCatalogService` und `PhotoExtractionService` (Fassade für Bestandsaufrufer) zerlegen.
  - Restore über ein `RestoreDependencies`-Parameterobjekt.
  - `openai.py` in `responses_client`, `stream_events`, `errors` und `usage` zerlegen.
- **Regressionstest:** Die bestehenden Tests bleiben grün; neue Fokus-Tests pro Teilservice; der PLR0913-Ratchet sinkt.
- **Confidence:** medium (Schnitt ist Design-Urteil, Metriken sind belegt)

### [P2] `public/app.js` ist ein God-Orchestrator mit globalem Zustand — public/app.js:1

- **Evidenz:** 4612 Zeilen mit zehn Verantwortlichkeiten:

  | Zeilen | Verantwortlichkeit |
  |---|---|
  | 1–269 | Darstellung und Navigation |
  | 270–760 | Session, API und Sync |
  | 752–1017 | Sprache und Benachrichtigungen |
  | 1024–1454 | Status |
  | 1472–2098 | Chat |
  | 2118–2782 | Planung |
  | 2836–3273 | Profil und Leistung |
  | 3337–3780 | Einstellungen und Diagnose |
  | 3786–4399 | State-Loader, Sync und Datenschutz |
  | 4402–4612 | Bootstrap |

  - Globaler, frei mutierbarer `state` (`public/state.js:11-64`).
  - Navigation doppelt gebunden: `app.js:4424` und `:4446` (`hashchange`), `nutrition.js:688` (`.nav-item`-Klick) und `:691` (`hashchange`).
- **Trigger:** Jede Frontend-Änderung.
- **Impact:**
  - Doppelte `hashchange`-Handler führen zu Doppel-Render und Reihenfolgeabhängigkeit.
  - Hohe Regressionsgefahr ohne Frontend-Unit-Runner.
  - Der Service-Worker-Cache-Bump betrifft immer die Monolith-Datei.
- **Remediation:**
  - Schrittweise Extraktion zu ES-Modulen: `session.js`, `sync-status.js`, `voice.js`, `notifications.js`, `coach-renderer.js`, `planning-view.js`, `profile-view.js`, `settings-view.js`, `state-loader.js`, `bootstrap.js`.
  - Ein einziger Router als Navigationseigentümer.
  - Ein State-Store mit expliziten Update-Funktionen.
- **Regressionstest:** Playwright-Navigationstest zählt Render-Aufrufe pro Hashwechsel (genau 1); ein bestehender Responsive-Lauf über alle Projekte.
- **Confidence:** high

### [P2] Doppelte API-, Auth- und Fehlerlogik im Frontend; interne Fehlerklassen in Toasts — public/app.js:392

- **Evidenz:**
  - Drei Implementierungen für Request/Fehler:
    - `public/api.js:13-67`;
    - der eigene `downloadRequest`-Fetch in `public/app.js:392-430`;
    - der Stream-Pfad in `public/coach.js:236-254`.
  - Toasts zeigen technische `error_class`-Werte an (`public/app.js:4028`, `:4045`, `:4063`).
- **Trigger:** Ein Fehler beim Download, Stream oder Diagnose-Export.
- **Impact:**
  - Uneinheitliches 401/CSRF-Verhalten (Session-Ablauf wird je nach Pfad anders behandelt).
  - Nutzer sehen interne Klassennamen statt handlungsleitender Texte.
- **Remediation:** Ein `apiClient` mit `request`, `download` und `stream`, gemeinsamem 401-Redirect, CSRF-Header, `retry_after` und einer Abbildung `reason → deutscher Nutzertext`.
- **Regressionstest:** Playwright mit gemockten 401/403/404/429/502 für alle drei Pfade; Toast-Text ohne `error_class`.
- **Confidence:** high

### [P2] `aria-live`-Region wird vollständig neu gerendert — public/index.html:58

- **Evidenz:** Die Nachrichtenliste ist eine Live-Region (`public/index.html:58`), wird aber in `public/app.js:1907-1937` komplett ersetzt.
- **Trigger:** Jeder Streaming-Delta oder Re-Render.
- **Impact:** Screenreader lesen ganze Verläufe erneut oder gar nichts (Browser-abhängig); das macht den Coach für AT-Nutzer praktisch unbrauchbar.
- **Remediation:**
  - Inkrementelles Anhängen.
  - Eine separate, knappe Live-Region („Coach antwortet …“, „Antwort fertig“) mit `aria-busy` während des Streamings.
- **Regressionstest:** Ein Playwright-Test zählt DOM-Mutationen der Live-Region pro Nachricht; axe bleibt grün.
- **Confidence:** medium (Wirkung AT-abhängig, Code belegt)

### [P2] Qualitäts-Gates messen nur Teilmengen — .github/workflows/publish-container.yml:158

- **Evidenz:**
  - Coverage läuft nur auf Shard 1 von 4 mit `--fail-under=0` (`:158-161`).
  - ruff und mypy prüfen nur eine Baseline-Liste plus geänderte `backend/`-Dateien, mypy mit `--follow-imports=skip` (`:164-207`).
  - Es gibt kein `pyproject.toml` und keine ruff/mypy-Konfiguration; `ruff format --check` würde 211 von 724 Dateien umformatieren.
  - Keine Paket-Layer-Matrix im Architekturtest (`tests/test_server_architecture.py:2546`, `:2558` prüfen nur `server`-Importe).
- **Trigger:** Strukturell.
- **Impact:** Architekturregeln aus `AGENTS.md` sind nur teilweise maschinell durchgesetzt; Coverage-Regressionen bleiben unsichtbar.
- **Remediation:** Phase 0 (Ratchet) und Phase 9 (Layer-Matrix).
- **Regressionstest:** CI schlägt fehl, wenn die Coverage unter die Baseline fällt oder ein neuer verbotener Import entsteht.
- **Confidence:** high

### [P3] 500-Fehlerumschlag ohne `reason` — backend/http_api/handler.py:150

- **Evidenz:** `handler.py:150` und `:162` liefern bei unerwarteten Fehlern nur `error`; alle anderen Pfade liefern `reason`.
- **Trigger:** Eine unbehandelte Ausnahme.
- **Impact:** Das Frontend kann den Fall nicht klassifizieren und fällt auf `http_error` zurück.
- **Remediation:** `reason: "internal_error"` und eine Korrelations-ID ohne Athleteninhalt.
- **Regressionstest:** Ein Handler-Test mit erzwungener Ausnahme prüft das Schema.
- **Confidence:** high

### [P3] Toter Composer-Hide-Code — public/app.js:1504

- **Evidenz:** `chat-composer-hidden` wird nur entfernt (`app.js:1507`, `:1516`), nie gesetzt. `styles.css:442` macht die Klasse ohnehin sichtbar.
- **Impact:** Irreführender Code im kritischen Chat-Pfad.
- **Remediation:** Funktion, Aufrufe und CSS-Regel entfernen.
- **Regressionstest:** Der bestehende `coach.spec` bleibt grün; `rg chat-composer-hidden` ist leer.
- **Confidence:** high

### [P3] Schnellstart-Chips ohne Scroll-Affordance auf 375 px — public/styles.css:464

- **Evidenz:**
  - `.quick-message-templates` hat `scrollWidth` 375 bei `clientWidth` 314 (`overflow-x: auto`).
  - „Letzte Einheit an…“ ist ohne sichtbaren Hinweis abgeschnitten.
  - Tablet und Desktop sind ohne Überlauf.
- **Impact:** Ein Prompt wird übersehen; das ist ein Coach-Einstieg.
- **Remediation:** Ein Fade-Mask- oder Wrap-Layout unter 480 px.
- **Regressionstest:** Ein Playwright-Geometrie-Test bei `mobile-small`.
- **Confidence:** high

### [P3] CSS-Token-Umgehung und uneinheitliche Breakpoints — public/styles.css:93

- **Evidenz:**
  - Hartkodierte Farben trotz Token-System (`styles.css:93-135`, `:510-511`, `:526`).
  - Breakpoints 479/480 und 767/768 sind gemischt (`:773`, `:829`, `:1044`, `:1272`, `:1297`).
- **Impact:** Theme-Inkonsistenzen (Light-Theme) und Off-by-one-Layouts an Grenzbreiten.
- **Remediation:** Eine dokumentierte Breakpoint-Skala (Custom-Media-Kommentarblock) und Farb-Tokens für Danger, Stop und Disabled.
- **Regressionstest:** Ein stylelint-ähnlicher `rg`-Check im Architekturtest auf Hex-Farben außerhalb von `:root`.
- **Confidence:** medium

### [P3] Test-Architektur: Mega-Testmodul und feste Wartezeit — tests/test_server_architecture.py:1

- **Evidenz:** `test_server_architecture.py` hat 3596 Zeilen; `e2e/coach.spec.js:668` nutzt `waitForTimeout(100)`.
- **Impact:** Schwer wartbar; flaky bei langsamen Runnern.
- **Remediation:** Nach Regelgruppen aufteilen und auf ein ereignisbasiertes `expect.poll`/Locator-Warten umstellen.
- **Regressionstest:** Gleiche Testanzahl vor und nach dem Split; `rg waitForTimeout e2e` ist leer.
- **Confidence:** high

### [P3] Veraltete Planungsdoku und ungenutzte Routen — docs/feature-implementation-plan.md:3

- **Evidenz:**
  - Der Status markiert Szenario-Features als offen, obwohl UI, API und Tools existieren (`public/analysis.js:1122`, `http_api/analysis.py:52`, `coach/activity_read_tools.py:51`, `coach/athlete_record_tools.py:65`).
  - Analyse-Routen ohne PWA-Aufrufer (`http_api/analysis.py:16`, `:55`).
  - Doppelte Alias-Routen `/api/logs/clear` und `/api/diagnostics/clear`.
- **Impact:** Falsche Planungsgrundlage; die Angriffs- und Wartungsfläche ohne Nutzen wächst.
- **Remediation:** Den Doku-Status aktualisieren; ungenutzte Routen entfernen oder als Coach-only dokumentieren; einen Alias mit Deprecation behalten.
- **Regressionstest:** Ein Routen-Inventar-Test: Jede Route hat einen Frontend-Aufrufer, einen Coach-Tool-Bezug oder eine explizite Allowlist.
- **Confidence:** medium
## Cross-cutting observations

Diese Punkte sind keine bestätigten Defekte, sondern systemische Design-Risiken oder Refactoring-Kandidaten.

- **Composition Root ist sauber, aber eager:** `server.py` (1935 Zeilen) ist eine reine Verdrahtung (407–1864) plus Lifecycle (1865–1935); kein Backend-Modul importiert `server`. Die gesamte Assembly ist eager an einem Ort, was Startzeit und Testaufbau verteuert. Gruppierte Assembly-Funktionen pro Domäne würden helfen; das ist kein Defekt.
- **Assembly-Indirektion:**
  - Es gibt 38 `*_assembly.py`-Module; in `coach/` sind es 11 mit 96–207 Zeilen (Median 116) und je genau einem Produktionsimporteur.
  - Das ist kein Over-Engineering, erzeugt aber Navigationskosten.
  - Konsolidierung pro Domäne prüfen, sobald die Layer-Matrix (Phase 9) die Richtung absichert.
- **Repository-Pattern nur teilweise etabliert:** Siehe den SQL-Befund. `db/` ist eher Infrastruktur (Bootstrap, Migration) als Persistenzschicht der Domänen.
- **Provider-Abstraktion fehlt als Port:** `coach/response_transport.py:20,35` kapselt den Transport bereits ordentlich (kein Befund). Ein einheitlicher Provider-Port für Antworten, Transkription und Vision fehlt aber und wird mit Phase 2 eingeführt.
- **Frontend ohne Unit-Runner:** Die gesamte Frontend-Logik ist nur über Playwright abgesichert. Die Modularisierung (Phase 7) sollte reine Funktionen (Formatter, Fehler-Mapping, Router) so schneiden, dass sie mit `node --test` ohne neue Abhängigkeit testbar werden.
- **Formatierungsdrift:** 211 von 724 Dateien sind nicht `ruff format`-konform. Das ist kosmetisch, verursacht aber Diff-Rauschen; einmalig formatieren, sobald Phase 0 die Konfiguration festlegt.
- **Sync-Snapshot als implizite Shared-Datenbank:** Mehrere Domänen lesen Rohsnapshots. Ein typisierter Read-Port reduziert Kopplung und klärt die Provenienz (Quelle/Frische) zentral.

## Coach-first and natural-language verdict

**Kein bestandenes Gesamturteil möglich**, weil der Live-OpenAI-Pfad (Tool-Auswahl durch das Modell, echtes Streaming) bewusst nicht aufgerufen wurde. Auf der Architektur- und Fixture-Ebene gilt:

- **Capability-Parität:**
  - Die Coach-Tools (`coach/tools.py`, `activity_read_tools.py`, `athlete_record_tools.py`, `proposals.py`) decken Planung, Feedback, Ernährung, Profil und Sync ab.
  - Approval- und Proposal-Mechanik ist zentralisiert (`CoachProposalExecutionService`).
  - Eine vollständige Tool↔Route-Paritätstabelle wurde in diesem Architektur-Review nicht neu aufgebaut. Status: **blocked** für den Live-Abgleich, Struktur geprüft.
- **Natürliche Sprache:** Es wurden keine neuen Regex- oder Keyword-Gates gefunden, die Tool-Zugriff gewähren. Paraphrasen, Folgefragen und Korrekturen sind ohne Live-Modell nicht prüfbar (**blocked**).
- **Direkte Ausführung vs. geschützte Fälle:** Adaptive Replanung (Preview/Apply), Datenschutzlöschung und Remote-Workout-Sync bleiben explizit geschützt. Die Fixture-E2E (`coach.spec`) bestätigt den Approval-Pfad.
- **Nachrichten-Lebenszyklus:** Der Fixture-Stream ist stabil (16/16 desktop, 20/20 mobile-small). **Der neue P2-Befund zur Composer-Verdeckung** beeinträchtigt jedoch die Erreichbarkeit der Eingabe auf Mobilgeräten direkt.
- **Wahrhaftige Fehlermeldungen:** Sie sind durch den verlorenen Retry-Hinweis, das Upstream-Status-Leck und `error_class`-Toasts beeinträchtigt (je P2).
- **Current-Data/Named-Sync:** Die Architektur ist geprüft (`sync/`-Worker, Job-Store), Live-Provider sind **blocked** (keine echten Konten).

## Validation

| Prüfung | Ergebnis | Anmerkung |
|---|---|---|
| `python -m unittest discover -s tests -v` | **passed** | 3322 OK, 16 skipped, 681 s; temporäre Daten, gemockte Provider |
| `python -m compileall -q server.py backend tests` | **passed** | |
| `docker build -t ai-coach:review-361290a .` | **passed** | |
| `ruff format --check .` | **failed** (informativ) | 211/724 Dateien würden umformatiert; kein CI-Gate |
| ruff-Komplexität (`PLR0913`, `PLR0911`, `C901`, `PLR0915`, `PLR0912`) | gemessen | 242 / 15 / 6 / 2 / 1 |
| Import-Graph (eigenes Skript, Temp-Verzeichnis) | ausgeführt | 341 Module, 1394 Kanten, 1 Modul-SCC, 7 Paketzyklen, 0 `server`-Importe |
| Playwright `desktop` `contracts`+`coach`, Lauf 1 | 37 passed / 4 failed | Container mit `FIXTURE_AUTO_SEED=1` (anders als CI); 3 Fehler sind Zustandskontamination (Plan-Datumskonflikt, 2 Timeouts); der Kontrastfehler ist ein echter Befund |
| Playwright `desktop` `coach.spec`, Lauf 2 | **16/16 passed** | frischer Container ohne Auto-Seed (CI-gleich) |
| Playwright `mobile-small` `coach`+`nutrition` `@responsive`, Lauf 3 | **20/20 passed** | frischer Container |
| Playwright `mobile`, `tablet`, `tablet-landscape` | **not run** | Zeitbudget; ersetzt durch manuelle Geometrieprüfung |
| Manuelle Geometrie (T3-Preview, Chromium) | ausgeführt | 375×667, 768×1024, 1024×768, 1440×900; Ansichten Coach, Kalender-Übersicht, Bibliothek, Analyse-Belastung/-Leistung, Ernährung, Mehr/Coach, Mehr/Betrieb; Ergebnis: Composer-Verdeckung und Chip-Überlauf nur bei 375 px, sonst kein horizontaler Überlauf |
| Kontrastberechnung Sportfarben | ausgeführt | Laufen 4,34, Kraft 4,56, Schwimmen 5,23, Rad 5,46 |
| Mikrofon, Benachrichtigungen, echte PWA-Installation, Offline | **not run** | kein physisches Gerät und keine Berechtigungsdialoge in der Preview |
| OpenAI/Gemini/Intervals/Garmin live | **not run** | bewusst; Fixtures und Mocks only |

Laufzeit-Identität: Container `ai-coach-review-578b`, Image `ai-coach:review-361290a`, `python /app/e2e/fixture_runtime.py`, synthetische Fixture-Daten, Chromium (Playwright und T3-Preview). Der Container wurde nach dem Review mit `docker rm -f` entfernt (ohne `-v`).

## Coverage ledger

| # | Domain | Hauptevidenz | Validierung | Ergebnis | Verbleibende Lücke |
|---|---|---|---|---|---|
| 1 | Produktinvarianten & Architektur | `server.py`, `backend/*` Paketgrenzen, Import-Graph, `AGENTS.md` | statisch, Graph | **finding** (Layering, Zyklen, God-Services) | – |
| 2 | Auth, Sessions, CSRF, HTTP | `http_api/handler.py`, `errors.py`, `api.js` | Unit, statisch | **finding** (Fehlervertrag, 500 ohne `reason`) | Security-Tiefenprüfung: **blocked** (nicht beauftragt; Codex Security empfohlen) |
| 3 | Secrets, Privacy, untrusted content | `observability.py`, `diagnostics/report.py`, Markdown-Rendering `views.js:24-41` | statisch | **clean** (Markdown-XSS-Hypothese verworfen) | Security-Tiefenprüfung: **blocked** wie oben |
| 4 | SQLCipher-Persistenz | `db/`, `.execute`-Verteilung | statisch, Unit | **finding** (SQL außerhalb `db/`) | Migrationspfade nicht neu ausgeführt (Unit-Suite deckt sie ab) |
| 5 | Backup/Restore | `backup/restore.py` | statisch, Unit | **finding** (12 Abhängigkeiten) | kein Restore-Laufzeittest in diesem Review |
| 6 | Provider-Clients & Netzwerk | `providers/{http,openai,gemini,intervals_client,weather,calendar}.py` | statisch, Graph | **finding** (Transport-DIP, Retry-Feld, Domänenimporte) | Live-Provider **blocked** |
| 7 | Sync & Nebenläufigkeit | `sync/jobs.py`, `worker_assembly.py`, `job_outcomes.py` | statisch, Unit | **finding** (unbewachte Übergänge, Design) | kein Interleaving-Laufzeittest |
| 8 | Coach-Kontext & Provenienz | `coach/context.py`, `performance/`, Snapshot-Leser | statisch | **finding** (Snapshot-Kopplung) | Inhaltliche Trainingskorrektheit nicht bewertet |
| 9 | OpenAI-Lifecycle & Coach-Tools | `providers/openai.py`, `coach/conversation.py`, `response_transport.py`, `tools.py` | statisch, Fixture-E2E | **finding** (Gemini-Verflechtung, Dateigröße) | Live-Modell **blocked** |
| 10 | Planung, Workouts, Kalender | `planning/changes.py`, `replacement.py`, `calendar/` | statisch, E2E | **finding** (Datumsparsing, private Konfliktregel, SQL) | – |
| 11 | Datum, Zeitzone, Einheiten | `runtime/clock.py`, `datetime.now`-Aufrufe | statisch | **finding** (Clock-Umgehung, `[:10]`) | DST-Laufzeittest fehlt |
| 12 | Frontend-State & API-Verträge | `app.js`, `state.js`, `api.js`, `coach.js`, `nutrition.js` | statisch, E2E, Preview | **finding** (Monolith, Doppelnavigation, 3 Fetch-Pfade) | – |
| 13 | PWA, Service Worker, Offline | `service-worker.js`, Asset-Versionen `index.html` | statisch | **clean** | Installation/Offline: **blocked** (kein Gerät) |
| 14 | Zuverlässigkeit, Performance, Observability | `observability.py`, Fehlerumschlag | statisch | **finding** (500-Umschlag) | keine Lastmessung |
| 15 | Tests & Verifikation | `tests/`, `e2e/`, CI-Coverage | Unit, E2E, CI-Analyse | **finding** (Coverage, Teil-Lint, Mega-Testmodul, `waitForTimeout`, Fixture ohne erledigte Einheiten) | Playwright-Vollmatrix **not run** |
| 16 | Dependencies, Container, Runtime | `Dockerfile`, `requirements*.txt` | Docker-Build | **clean** | kein Dependency-CVE-Scan in diesem Review |
| 17 | CI/CD & Releases | `.github/workflows/*` | statisch | **finding** (Quality-Gates partiell) | Release-Workflow nicht ausgeführt |
| 18 | Doku & Wartbarkeit | `README.md`, `docs/`, Dateigrößen, Komplexität | statisch | **finding** (veraltete Doku, ungenutzte Routen, CSS-Tokens) | – |

### Detail-Ledger 1 – Coach-Capability- und Tool-Parität

| Capability | UI/API | Coach-Tool | Prüfung | Status |
|---|---|---|---|---|
| Planänderung (anlegen/ändern/verschieben) | `/api/plan*`, `planning-view` | `coach/tools.py`, Proposals | Fixture-E2E `coach.spec` | geprüft (Fixture) |
| Ernährung (Mahlzeit, Produkt, Foto) | `nutrition.js`, `/api/nutrition*` | Ernährungs-Tools | Fixture-E2E `nutrition` | geprüft (Fixture); Foto-Pfad nutzt Gemini → Phase 2 |
| Aktivitätsfeedback/-lesen | Analyse, Kalender | `activity_read_tools.py` | statisch | geprüft (statisch) |
| Profil, Wettkämpfe, Check-ins | Mehr/Profil | `athlete_record_tools.py` | statisch | geprüft (statisch) |
| Named Sync (Intervals, Garmin, Wetter, Kalender) | Sync-Buttons | Sync-Tools | statisch | Live **blocked** |
| Adaptive Replanung | Preview/Apply | Proposal-Pfad | Fixture-E2E | geprüft (Fixture) |
| Datenschutz/Löschen | Mehr/Datenschutz | geschützt | statisch | geprüft (statisch) |
| Modell-Toolauswahl bei Paraphrasen | – | – | Live-Modell nötig | **blocked** |

### Detail-Ledger 2 – Nachrichten-Lebenszyklus und Races

| Szenario | Status | Begründung |
|---|---|---|
| Senden, Streamen, Abschluss | geprüft (Fixture-E2E) | – |
| Enter vs. Shift+Enter | geprüft (Fixture-E2E `coach.spec`) | – |
| Composer-Erreichbarkeit nach Laden (mobil) | **failing** | Befund P2 Composer-Verdeckung |
| Abbruch (Stop) und Wiederaufnahme | geprüft (Fixture-E2E) | – |
| Reload während Stream, Hintergrund-Recovery | **blocked** | keine kontrollierte Verzögerungsinjektion in diesem Lauf |
| Mehrere Tabs, überlappende Refreshes | **blocked** | nicht ausgeführt |
| Out-of-order und doppelte Nachrichten | **blocked** | nicht ausgeführt; Live-Region-Rerender als Risiko notiert |
| Offline-Übergang während Senden | **blocked** | nicht ausgeführt |

### Detail-Ledger 3 – API-Verträge und Fehlerklassen

| Fehlerklasse | Backend | Frontend `api.js` | Frontend `coach.js` (Stream) | `downloadRequest` | Status |
|---|---|---|---|---|---|
| 400 Validierung | `reason` vorhanden | korrekt | korrekt | eigener Pfad | uneinheitlich (P2) |
| 401 lokale Session | 401 | Re-Login | Re-Login | eigener Pfad | uneinheitlich (P2) |
| 401 Upstream | → 502 | – | – | – | korrekt |
| 403/404 Upstream | **durchgereicht** | – | wie lokal behandelt | – | **finding** P2 |
| 429 mit Retry | Feld verloren | würde `retry_after` lesen | ignoriert | – | **finding** P2 |
| 500 unerwartet | ohne `reason` | Fallback `http_error` | Fallback | – | **finding** P3 |

Die Injektion wurde statisch nachvollzogen; eine Laufzeit-Injektion pro Klasse ist **blocked** (kein gemockter Provider-Fehler im Fixture-Lauf).

### Detail-Ledger 4 – Provider-Zustände, Named Syncs und Recovery

| Provider | Normal | Fehler/Auth | Teilfehler | Recovery | Status |
|---|---|---|---|---|---|
| OpenAI | statisch und Unit | Unit | Unit | Unit | Live **blocked** |
| Gemini | statisch und Unit | Status-Leck (P2) | Unit | Unit | wird entfernt (Phase 2) |
| Intervals.icu | statisch und Unit | Unit | Unit | Unit | Live **blocked**; Schichtverletzung (P2) |
| Garmin | Fixture | Unit | Unit | Unit | Live **blocked** |
| Wetter/Kalender | statisch | Unit | – | – | Live **blocked**; Schichtverletzung (P2) |

### Detail-Ledger 5 – User Journeys nach Viewport

| Journey | mobile-small (375) | mobile (390) | tablet (768) | tablet-landscape (1024) | desktop (1440) |
|---|---|---|---|---|---|
| Login → Coach-Chat | E2E pass; **Composer verdeckt** | Playwright not run | Geometrie ok | Geometrie ok | E2E pass, Composer erreichbar |
| Kalender/Planung | Geometrie ok | not run | Geometrie ok | Geometrie ok | E2E (Lauf 1) mit Kontrastbefund |
| Analyse | Geometrie ok | not run | Geometrie ok | Geometrie ok | Geometrie ok |
| Ernährung | E2E pass | not run | Geometrie ok | Geometrie ok | Geometrie ok |
| Mehr/Einstellungen | Geometrie ok | not run | Geometrie ok | Geometrie ok | Geometrie ok |
| Sprache/Mikrofon, Benachrichtigungen, PWA-Install | blocked | blocked | blocked | blocked | blocked |

## Areas checked without actionable findings

- **Composition Root:** Kein Backend-Modul importiert `server.py`; Geschäftslogik ist nicht in den Composition Root zurückgewandert.
- **Markdown-Rendering:** `public/views.js:24-41` escaped zuerst den gesamten Text und erlaubt nur `http`/`https`-Links. Die gemeldete XSS-Hypothese ist **verworfen**. Optionale Robustheit: Links per DOM-API statt String bauen.
- **Response-Transport:** `coach/response_transport.py:20,35` kapselt den Modell-Transport sauber; ein fehlender Port ist kein Befund.
- **Sync-Worker-Topologie:** Es gibt genau einen Worker, und `claim`/`resolve` sind bewacht. Damit besteht heute kein Race (siehe P2-Design-Befund).
- **PWA-Cache-Vertrag:** Asset-Query-Versionen in `index.html` und der Service-Worker-Cache sind konsistent gepflegt.
- **Container-Härtung:** non-root, `--read-only`-tauglich, `/data` beschreibbar, Fixture-Runtime ohne Secrets.
- **Responsive Layout:** Ab 768 px gibt es in keiner geprüften Ansicht horizontalen Überlauf.

## Limitations and follow-up

- Es gab keine Live-Aufrufe an OpenAI, Gemini, Intervals.icu oder Garmin. Modell-Toolauswahl, Paraphrasen und echte Provider-Fehler sind nur statisch oder über Unit-Tests belegt.
- Die Playwright-Projekte `mobile`, `tablet` und `tablet-landscape` sind nicht gelaufen. Die Geometrie wurde manuell geprüft. Mikrofon, Benachrichtigungen, echte PWA-Installation und Offline wurden nicht geprüft.
- Playwright-Lauf 1 nutzte versehentlich `FIXTURE_AUTO_SEED=1`. Drei Fehlschläge sind als Kontamination klassifiziert und nicht als Defekte gewertet; nur der Kontrastfehler wurde übernommen.
- Die Security-Tiefenprüfung ist nicht Teil dieses Auftrags; empfohlen wird ein separater lokaler Codex-Security-Scan über `.agents/skills/ai-coach-codex-security`.
- Die Schnittvorschläge für God-Services sind Design-Urteile (Confidence medium).
- Ein Lead mit niedriger Confidence: Der Chat scrollt beim Laden nicht deterministisch ans Ende (`scrollY` 1173/1286). Das ist eine Mitursache der Composer-Verdeckung und wird im selben Fix adressiert.

## Behebungsplan

### Leitplanken für alle Phasen

- **Ablauf pro PR-Slice:** eigener Worktree und Task-Branch ab aktuellem `main`, Conventional-Commit-Titel, englische PR-Beschreibung, Rebase vor dem PR, `--auto --squash`.
- **Schemaänderungen:** versionierte, transaktionale SQLCipher-Migration mit eingefrorenem Fixture des Vorrelease-Schemas. Nachzuweisen sind Upgrade mit Bestandsdaten, Rollback bei Fehler, Neustart desselben Builds und ein Direkt-Upgrade über übersprungene Releases. Unbekannte oder neuere Schemas werden ohne Datenänderung abgelehnt.
- **Frontend-Änderungen:** Asset-Query-Versionen in `public/index.html` und Cache-Name/Assets in `public/service-worker.js` anheben. Betroffene Playwright-Projekte laufen gegen die isolierte Fixture-Runtime (`--read-only`, tmpfs `/data`, ohne `FIXTURE_AUTO_SEED`).
- **Pflichtprüfungen je Slice:** `python -m unittest discover -s tests -v`, `python -m compileall -q server.py backend tests`, `node --check` für geänderte JS-Dateien. Bei Docker-, Abhängigkeits- oder Startup-Änderungen zusätzlich `docker build -t ai-coach:local .`.
- **Verhalten:** Verhalten, Security- und Datenintegritätsverträge bleiben erhalten. Extraktionen verschieben Verantwortung nach `backend/`, nicht nur Hilfsfunktionen.

### Phase 0 – Quality-Gate-Ratchet (Voraussetzung)

| Slice | Titel | Inhalt | Akzeptanz |
|---|---|---|---|
| 0.1 | `build: centralize tool configuration in pyproject.toml` | ruff-, mypy- und coverage-Konfiguration zentralisieren; bestehende Ausnahmen als explizite Baseline | CI nutzt nur diese Konfiguration |
| 0.2 | `style: apply repository-wide ruff format` | einmalige, rein mechanische Formatierung als eigener PR | Diff ist nur Formatierung; Tests grün |
| 0.3 | `ci: enforce repository-wide ruff, mypy and merged coverage` | repo-weites ruff/mypy statt inkrementell; zusammengeführte Coverage mit Schwellwert auf Ist-Stand, danach Ratchet | Gate schlägt bei Verschlechterung fehl |

### Phase 1 – Schnelle UX- und A11y-Fixes

| Slice | Titel | Inhalt | Akzeptanz/Tests |
|---|---|---|---|
| 1.1 | `fix(ui): keep composer above bottom navigation` | Token `--bottom-nav-offset` inkl. `env(safe-area-inset-bottom)` für Composer und Scroll-Padding; deterministisches Scroll-to-End nach History-Load | Playwright-Geometrie: Composer-Rect schneidet Bottom-Nav in keinem Projekt; letzter Chat-Eintrag sichtbar |
| 1.2 | `fix(ui): meet WCAG contrast for session colours` | Session-Farb-Tokens mit Kontrast >= 4.5:1; Fixture mit abgeschlossenen Einheiten | Kontrast-Assertion im Kalender mit erledigten Sessions |
| 1.3 | `refactor(ui): remove dead composer-hide code` | toten Code entfernen | keine Verhaltensänderung |
| 1.4 | `fix(ui): show overflow affordance for chips` | sichtbare Scroll-Affordanz für überlaufende Chips | Geometrie-Test in mobile-small |

### Phase 2 – Gemini restlos entfernen, ausschließlich Responses-kompatible APIs

**Zielbild (vom Nutzer bestätigt):** Es gibt genau einen KI-Provider-Port für die OpenAI Responses API, konfiguriert über `OPENAI_API_KEY`, `OPENAI_MODEL` und optional `OPENAI_BASE_URL` für Responses-kompatible Endpunkte. Chat Completions und ein Fallback darauf sind ausgeschlossen. Provider-Auswahl, Gemini-Modelloptionen, Gemini-Zugangsdaten und Gemini-Konversationszustand entfallen vollständig. Bestehende Gemini-Konversationshistorie und Call-Namen werden ausdrücklich gelöscht, nicht archiviert. Betroffen sind 98 Dateien mit Gemini-Bezug.

| Slice | Titel | Inhalt | Abhängigkeit |
|---|---|---|---|
| 2.1 | `refactor(providers): route transcription and photo analysis through OpenAI-compatible APIs` | `providers/audio.py` auf `/audio/transcriptions` umstellen; `nutrition/photo.py` (`gemini_json_client`) auf Responses-Vision mit strukturiertem Output umstellen; beides vorher ohne Gemini-Fallback testen | Phase 0 |
| 2.2 | `feat(db)!: migrate AI provider state to OpenAI only` | versionierte, transaktionale Migration: KV `selected_ai_provider='gemini'` wird zu `openai`; `selected_model_gemini`, `gemini_conversation_history` und `gemini_call_names` vollständig löschen, ohne Archivkopie; weitere eindeutig Gemini zugeordnete Konversationsdatensätze inventarisieren und löschen; offene Coach-Jobs mit `ai_provider=gemini` deterministisch abbrechen, ohne Gesprächsinhalte an einen anderen Provider zu übertragen; Frozen-Fixture-, Rollback-, Restore- und Restart-Tests | 2.1 |
| 2.3 | `refactor(coach)!: remove Gemini provider and selection` | entfernen: `providers/gemini.py`, Gemini-Zweige in `http.py`/`model_assembly.py`/`state.py`/`usage.py`, `coach/conversation.py`, `job_submission.py`, `job_store.py`; dazu `config.py` (`GEMINI_API_KEY`, `GEMINI_MODEL`, `AI_PROVIDER`), `settings.py` (`GEMINI_MODEL_OPTIONS`, Provider-Auswahl), `db/bootstrap.py`, `errors.py`, `observability.py`, `diagnostics/report.py`, `http_api`-Bootstrap/Public-State, `server.py` | 2.2 |
| 2.4 | `feat(ui)!: remove AI provider selector` | Provider-Auswahl aus `public/app.js`, `coach.js` und `index.html` entfernen; Modellauswahl behält `gpt-6-luna` und das konfigurierte `OPENAI_MODEL`; PWA-Cache-Bump | 2.3 |
| 2.5 | `feat(providers): support OPENAI_BASE_URL for Responses-compatible endpoints` | optionale Basis-URL validieren; nur Responses-kompatible Endpunkte zulassen; erforderliche Fähigkeiten (Responses, Background-Mode, Conversations) prüfen und fehlende Fähigkeiten klar melden; keine Chat-Completions-Anbindung oder automatische Protokollumschaltung | 2.3 |
| 2.6 | `docs: remove Gemini from configuration and agent instructions` | `README.md`, `.env.example`, Gemini-Abschnitt in `AGENTS.md`, `docs/coach-dialogue-evaluation.md`, Diagnose-Doku | 2.3 |

**Akzeptanz Phase 2:**
- `rg -i gemini` trifft nur noch die Migration samt Tests und den Changelog.
- Rund 60 Gemini-Tests sind entfernt oder auf den OpenAI-Pfad umgeschrieben.
- Die Diagnose prüft ausschließlich den OpenAI-Pfad.
- Ein Upgrade einer Datenbank mit `selected_ai_provider='gemini'` entfernt die ausdrücklich zur Löschung freigegebene Gemini-Historie und ihren Provider-State. Profil, Pläne, Trainingsbibliothek, andere Athletendaten und nicht Gemini zugeordnete Chatdaten bleiben erhalten.
- Wiederholte Migration und Same-Build-Restart sind idempotent; bei einem Fehler bleibt die vorherige Datenbank vollständig erhalten. Ein unterstützter Restore durchläuft dieselbe Migration und aktiviert keinen Gemini-Zustand erneut. Vorhandene Recovery-Backups bleiben unverändert geschützt.
- Keine Gemini-Zugangsdaten, aktiven Konfigurationspfade, Adapter, Modelloptionen oder Archivkopien verbleiben in Anwendung und aktueller Konfiguration; keine Gemini-Nachrichten werden an Responses übertragen.
- Tests belegen den Responses-Vertrag und die Ablehnung von Chat-Completions-only-Endpunkten. Fotoanalyse und kurzlebige Transkription funktionieren ohne Gemini-Fallback; separat benötigte OpenAI-Feature-Endpunkte werden ausdrücklich auf Unterstützung geprüft.

### Phase 3 – Fehlervertrag

| Slice | Titel | Inhalt | Akzeptanz/Tests |
|---|---|---|---|
| 3.1 | `fix(api): use a single retry_after field` | `retry_after_seconds` vereinheitlichen; Header `Retry-After` setzen; Frontend liest nur ein Feld | Vertragstests 429/503 |
| 3.2 | `fix(api): map upstream failures to 502/503/429 without leaking status` | `errors.py:60` übernimmt keinen Upstream-Status 1:1; Mapping-Tabelle; `reason` als stabiler Code | Tests je Upstream-Status |
| 3.3 | `fix(api): include reason in 500 envelope` | einheitliches Envelope `{error, reason, request_id}` | Envelope-Vertragstest |

### Phase 4 – Schichtung und Abhängigkeitsrichtung

| Slice | Titel | Inhalt |
|---|---|---|
| 4.1 | `refactor(http_api): introduce ProviderErrorClassifier` | Der Transport kennt keine Provider mehr (`http.py:722`); Provider liefern klassifizierte Fehler. |
| 4.2 | `refactor(planning): move workout_text into planning` | Provider importieren keine Domänenlogik. |
| 4.3 | `refactor(performance): add ProviderSnapshotReader port` | Snapshot-Kopplung über einen Port auflösen; Paketzyklen brechen. |
| 4.4 | `refactor(core): inject clock and enforce ruff DTZ` | Zentrale Clock-Abhängigkeit, keine direkten `datetime.now()`/`date.today()` in der Domäne. |
| 4.5 | `refactor(planning): expose calendar_items_conflict publicly` | Öffentliche API `planning.conflicts.calendar_items_conflict` statt privater Zugriffe. |

**Akzeptanz Phase 4:**
- Der Importgraph ist zyklenfrei.
- Ruff `DTZ` ist aktiv.
- Tests mit fixer Uhr decken Mitternachts- und Zeitzonengrenzen ab.

### Phase 5 – Persistenz

| Slice | Titel | Inhalt | Akzeptanz/Tests |
|---|---|---|---|
| 5.1 | `refactor(db): add per-domain repositories` | SQL aus Domänen und `http_api` in Repositories unter `db/` verschieben, Transaktionsgrenze beim Use Case | Guard-Test: kein SQL in `http_api` |
| 5.2 | `refactor(sync): guard sync-job state transitions` | `sync/job_store.py` mit expliziter Zustandsmaschine und atomarem `UPDATE ... WHERE state=?` | tabellengetriebene Übergangstests; ohne Schemaänderung, sonst Migration nach Leitplanken |

### Phase 6 – God-Services schneiden und Werteobjekte

| Slice | Titel | Inhalt |
|---|---|---|
| 6.1 | `refactor(core): add LocalDate value object` | `LocalDate.parse` ersetzt das `[:10]`-Parsing (`planning/changes.py:47` u. a.); ungültige Daten werden abgelehnt statt abgeschnitten. |
| 6.2+ | `refactor(<domain>): split <Service> by use case` | Je God-Service ein PR mit Schnitt nach Use Case. Fokussierte Tests mit temporärem Speicher und gemockten Providern. |

### Phase 7 – Frontend-Architektur

| Slice | Titel | Inhalt | Akzeptanz/Tests |
|---|---|---|---|
| 7.1 | `refactor(ui): introduce single apiClient` | ein Client für request, download und stream; 401 führt zum Login, 403 lädt CSRF neu, 404 zeigt einen Hinweis | e2e für Session-Ablauf |
| 7.2 | `refactor(ui): map error reasons to German messages` | `reason`→Text-Mapping statt `error_class`-Toasts | Playwright prüft die Meldungen |
| 7.3 | `refactor(ui): extract router and state store from app.js` | ein Router, ein State-Store, Views als Module | `app.js` nur noch Bootstrap |
| 7.4 | `fix(a11y): update aria-live regions incrementally` | kein Full-Re-Render der Live-Region | Playwright zählt Mutationen der Live-Region |

### Phase 8 – CSS-Tokens und Breakpoints

- **Slice 8.1** – `refactor(ui): consolidate design tokens and breakpoint scale`.
  - Farb-, Abstands- und Radius-Tokens zusammenführen.
  - Feste Breakpoint-Skala einführen und Ad-hoc-Media-Queries ersetzen.
  - **Akzeptanz:** Screenshot-Vergleiche in allen Playwright-Projekten zeigen keine Regression.

### Phase 9 – Architektur-Guards und Testarchitektur

| Slice | Titel | Inhalt |
|---|---|---|
| 9.1 | `test: add AST layer-matrix guard` | Erlaubte Importe je Paket als Matrix; Verstöße lassen CI fehlschlagen. |
| 9.2 | `test: split test_server_architecture by concern` | Architekturtests nach Domänen aufteilen. |
| 9.3 | `test(e2e): replace waitForTimeout with state assertions` | Flakiness-Quellen entfernen. |

### Phase 10 – Dokumentation und Routen

- **Slice 10.1** – `docs: refresh architecture and API documentation`.
- **Slice 10.2** – `refactor(api): remove unused routes`.
  - Ungenutzte Routen erst nach einem Nutzungsnachweis in Frontend, Tests und Doku entfernen.

### Reihenfolge

- **Phase 0** ist die Voraussetzung für alles Weitere.
- **Phase 1** kann sofort parallel starten.
- **Phase 2** kommt vor den Phasen 3 und 4, weil sie die Provider-Fläche verkleinert.
- **Slice 4.1** kann vor Phase 3 gezogen werden.
- **Phasen 4 → 5 → 6** laufen sequenziell, weil sich die Schreibmengen überlappen.
- **Phase 7** setzt Phase 3 voraus.
- **Phase 8** folgt auf Phase 1.
- **Phase 9** härtet die Ergebnisse der Phasen 4 bis 6 ab.
- **Phase 10** schließt ab.

### Verbindliche Entscheidungen

1. **API-Vertrag:** Ausschließlich Responses-kompatible APIs; keine Chat-Completions-Anbindung. Eine eigene Basis-URL ist nur für diesen Vertrag zulässig.
2. **Gemini-Bestandsdaten:** Konversationshistorie und Call-Namen ausdrücklich löschen, nicht archivieren; andere Athletendaten bleiben erhalten.
3. **Review-Gate:** Neue, isolierte `gpt-6-luna`-Subagents liefern abgegrenzte Arbeitsergebnisse; der Orchestrator prüft und übernimmt allein die Patches. Diese Rollenverteilung gilt auch für die Umsetzung des Behebungsplans.
## Completion statement

Complete for the recorded source snapshot; all checklist domains were reviewed or explicitly blocked.
