# Review-Log der server.py-Auslagerung

Dieses Log hält nur tatsächlich vom Orchestrator geprüfte integrierte Stände
fest. Worker-Zusammenfassungen und isolierte grüne Tests sind keine Freigabe.

## P0 — Inventar, Baseline und Architekturprüfung

- Basis: `362d6caa4c27951af86b82b11b3a43d48dadceee` (`origin/develop` beim Start).
- Geprüfter Diff-Umfang: AST-Inventargenerator und generiertes Inventar,
  Architekturtest, Entfernung des rückimportierenden
  `backend/providers/intervals_client.py`, vollständige Reabsorption seines noch
  nicht fachlich getrennten Ablaufs in `server.py`, zugehörige Tests und
  P0-Checkliste.
- `server.py`: 21.702 Zeilen in der unveränderten Baseline; 21.998 Zeilen im
  P0-Stand. Der Anstieg um 296 Zeilen macht die zuvor nur scheinbare Auslagerung
  sichtbar; `IntervalsClient` bleibt offen für die kohärente Aufteilung in
  P2/P3/P4/P6.
- Fachliche Definitionen im Inventar: 1.235 offen; 1.723 Einträge insgesamt,
  davon 309 globale Zuweisungen und 179 Imports; null unzugeordnete Ziele.

### Review-Gate

- Erster Architekturtest-Diff: **FAIL** — indirekter `server`-/`__main__`-Zugriff
  wurde anfangs nicht vollständig erkannt und unvollständige Wrapper waren
  fälschlich als bereits verlagert eingestuft.
- Korrigierter Architekturtest: **FAIL** gegen den Ausgangscode —
  `backend/providers/intervals_client.py` importierte `server` und nutzte
  `sys.modules["__main__"]` als Service-Locator.
- Reabsorbierter Intervals-Stand: **FAIL** im ersten Review — zwei kleine Tests
  importierten `server` ohne den isolierten Test-Bootstrap und hätten in einem
  anderen Checkout eine reale `.env` lesen können.
- Korrigierter integrierter P0-Stand: **PASS** — kein Backend-Rückimport oder
  indirekter Entry-Point-Zugriff, keine neue Service-Registry und kein
  Server-Callback-Container. Die vorhandenen Intervals-Transportprimitiven
  bleiben in `backend/providers/intervals.py`.

### Prüfungen

- Baseline: `python -m unittest discover -s tests -v` — 779 Tests, 12 Skips,
  PASS in 117,730 s.
- Integrierter Stand vor der abschließenden Test-Bootstrap-Korrektur:
  781 Tests, 12 Skips, PASS in 121,561 s.
- Abschließender integrierter Stand nach der Test-Bootstrap-Korrektur:
  `python -m unittest discover -s tests -v` — 780 Tests, 12 Skips, PASS in
  115,086 s.
- Architekturtest, Intervals-Client-Test und Config-Tests nach der
  Test-Bootstrap-Korrektur: 5 Tests, PASS.
- `python -m unittest discover -s tests -p test_workout_text.py -v` — 21 Tests,
  PASS.
- `python -m compileall -q server.py backend` — PASS.
- `python scripts/server_extraction_inventory.py --check` — PASS.
- `python -m py_compile scripts/server_extraction_inventory.py tests/test_server_architecture.py`
  — PASS.
- `git diff --check` — PASS.
- Docker-/E2E-Baseline: BLOCKED durch nicht erreichbaren lokalen Docker-Desktop-
  Daemon (`npipe`); ohne isolierten Server wurde E2E nicht gestartet.

### Verbleibende Risiken und nächster Schritt

- Docker-Build und E2E bleiben eine externe lokale Infrastrukturvoraussetzung;
  CI darf dafür nicht umgangen werden.
- Nächster Schritt ist P1 in einem neuen Worktree auf dem gemergten P0-Stand:
  zuerst `errors.py`, danach die voneinander trennbaren konkreten Ressourcen
  `runtime/events.py` und `runtime/maintenance.py`.

## P0-Follow-up — Sonar-Korrektur

- Basis: Merge-Commit `25e92f2e6c592a756103d77680c75a447ebe744d`
  von PR #663, auf `origin/develop` als Vorfahr bestätigt.
- Auslöser: Der PR-spezifische SonarCloud-Scan meldete 43 neue Befunde nur in
  `scripts/server_extraction_inventory.py`, darunter fünf überkomplexe
  Funktionen, duplizierte Zielmodul-Literale, ein redundantes Regex-
  Muster, einen ungenutzten Parameter und einen doppelten Dictionary-Key.
- Erste Worker-Korrektur: **FAIL** — nur Literale waren bereinigt; die fünf
  Komplexitätsbefunde blieben im tatsächlichen Diff unverändert.
- Zweite Worker-Korrektur: **FAIL** — die Funktionen waren zerlegt, aber elf
  fachliche Eigentümer wurden durch geänderte Regelprioritäten umklassifiziert.
- Erster Follow-up-PR-Scan: **FAIL** — von 43 Befunden blieb ausschließlich
  `python:S1172` für einen ungenutzten Parameter in der Owner-Auflösung übrig;
  der Parameter wurde ohne Verhaltensänderung entfernt.
- Integrierter Korrekturstand: **PASS (lokal)** — Owner-Auflösung,
  Inventareinträge, Referenzscanner, Abhängigkeitsanalyse, SCC-Ermittlung und
  Dokumentaufbau sind fokussiert getrennt; das erzeugte Inventar ist bytegleich
  zum bereits geprüften P0-Inventar.

### Prüfungen

- `ruff check scripts/server_extraction_inventory.py` — PASS.
- `python scripts/server_extraction_inventory.py` und anschließender
  bytegleicher Git-Vergleich des Inventars — PASS.
- `python scripts/server_extraction_inventory.py --check` — PASS.
- `python -m py_compile scripts/server_extraction_inventory.py` — PASS.
- `python -m unittest tests.test_server_architecture -v` — 2 Tests, PASS.
- `git diff --check` — PASS.
- Lokale Vortex-Dateianalyse — nicht verfügbar (`403 Forbidden`); der neue
  PR-spezifische SonarCloud-Lauf ist deshalb das verbindliche externe Gate.

## P1.1 — Fehlervertrag

- Basis: Merge-Commit `a081e013352eb52e020e934c3d5ccf0dc8312573`
  von PR #664, auf `origin/develop` als Vorfahr bestätigt.
- Delegation: eigenständiger Luna-Worker-Diff mit Schreibbereich ausschließlich
  `backend/errors.py` und `tests/test_errors.py`; keine Änderung an `server.py`.
- Worker-Diff: `AppError`, `ClientDisconnected`, öffentliche HTTP-Statusabbildung,
  redigierte Providerfehler und die zugehörigen Fehlerkonstanten nach
  `backend/errors.py` verlagert.
- Erstes Orchestrator-Review des tatsächlichen Worker-Codes: **PASS** — keine
  Rückimporte, kein Zustand, keine Providertexte in öffentlichen Meldungen und
  identische Status-/Reason-Semantik.
- Geprüfter integrierter Commit: `2820e8514eee2d4c37353bc4a5bee8de282f1226`.
- Integriertes Orchestrator-Review: **PASS** — `server.py` importiert die
  Symbole nur noch als Composition Root; sämtliche Implementierungen und
  Konstantendefinitionen wurden entfernt. Die Architekturprüfung erfasst nun
  zusätzlich top-level Zuweisungen und verhindert damit Rückverlagerungen von
  Konstanten.
- `server.py`: 21.962 physische Zeilen; gegenüber dem geprüften P0-Stand 36
  Zeilen weniger. Erfolgskriterium ist die vollständige Eigentumsverlagerung,
  nicht die Zeilenreduktion.

### Prüfungen

- `python -m unittest tests.test_errors tests.test_server_architecture -v` —
  12 Tests, PASS.
- `python -m unittest discover -s tests -v` — 790 Tests, 12 übersprungen,
  PASS in 121,964 s.
- `ruff check backend/errors.py tests/test_errors.py` — PASS.
- `python -m compileall -q server.py backend` — PASS.
- `python scripts/server_extraction_inventory.py --check` — PASS.
- `git diff --check` — PASS.
- Repositoryweiter Ruff-Lauf: bestehende Monolith-/Architekturtest-Befunde;
  keine als P1.1 eingeführte Fachlogikverletzung. Das neue Modul und sein
  fokussierter Testbestand sind vollständig sauber.

### Verbleibende Risiken und nächster Schritt

- Docker-/E2E-Ausführung bleibt wegen des bereits dokumentierten nicht
  erreichbaren lokalen Docker-Desktop-Daemons extern blockiert; das CI-Gate
  darf nicht umgangen werden.
- Die übrigen vier P1-Arbeitspakete bleiben offen. Als Nächstes folgen die
  voneinander trennbaren Ressourcen `runtime/events.py` und
  `runtime/maintenance.py` in neuen, abgegrenzten Delegationen.

## P1.2 — Runtime-Events und Maintenance-Gate

- Basis: bestätigter Merge-Commit
  `f658d4159b156ca1695b35c39722ecfbc1012299` von PR #665; `mergedAt`
  `2026-09-15T19:35:47Z` und Erreichbarkeit auf `origin/develop` bestätigt.
- Events-Worker: lokaler Commit
  `fad5ab86ebfc6e9b585c1c01e1a381040b9d9945`, im Integrations-Worktree als
  `ef88f81` sequenziell übernommen.
- Erstes Events-Review: **FAIL** — `OverflowError` wurde entgegen dem
  Ausgangsvertrag neu in `AppError` übersetzt, und der gemeldete Ruff-Lauf
  hatte die Testdatei mit einem `BaseException`-Befund ausgelassen.
- Events-Korrekturreview: **PASS** — ursprüngliche Cursor-Ausnahmen
  wiederhergestellt; Modul, Paketdatei und Tests gemeinsam Ruff-clean; der
  konkrete `StateEventBuffer` besitzt Condition, Ringpuffer und Cursor.
- Maintenance-Worker: lokaler Commit
  `91b738d8d1ecdd0d9861bdcb31a70fc14ec84f37`, im Integrations-Worktree als
  `26842d6` sequenziell übernommen.
- Maintenance-Review: **PASS** — Modul-Singleton ist alleiniger
  Zustandseigentümer; Nested-Operation, Restore-Drain, Generation,
  Invalidierung und selektives Schlucken erwarteter Claim-Abbrüche entsprechen
  dem bisherigen Vertrag. Keine Rückabhängigkeit auf `server.py`.
- Geprüfter integrierter Commit:
  `23802ecf1a85a0d1965b5b5173998b7f8e9143e5`.
- Integrationsreview: **PASS** — sämtliche Produktionsaufrufer und
  Test-Patchziele verwenden die Runtime-Eigentümer direkt; `server.py` enthält
  weder Callback-Wrapper noch Event-/Maintenance-Implementierungen. Die
  Architekturprüfung schützt Klassen, Funktionen, Singleton-Namen und globale
  Zuweisungen vor Rückverlagerung.
- `server.py`: 21.835 physische Zeilen, 1.226 verbleibende Funktionen/Klassen;
  gegenüber P1.1 127 Zeilen weniger. Maßgeblich ist die vollständige
  Verlagerung von Zustand und Orchestrierung.

### Prüfungen

- `python -m unittest tests.test_runtime_events tests.test_runtime_maintenance tests.test_server_architecture -v`
  — 19 Tests, PASS.
- Gezielte Discovery-Regressionen: State-Event-Retention/HTTP-Batch 3 Tests,
  Maintenance-Gate 2 Tests, Privacy-Delete-Races 3 Tests und Audit-Maintenance
  1 Test — alle PASS.
- `python -m unittest discover -s tests -v` — 807 Tests, 12 übersprungen,
  PASS in 122,617 s.
- `ruff check backend/runtime/events.py backend/runtime/maintenance.py tests/test_runtime_events.py tests/test_runtime_maintenance.py`
  — PASS.
- `python -m compileall -q server.py backend` — PASS.
- `python scripts/server_extraction_inventory.py --check` — PASS.
- `git diff --check` — PASS.

### Verbleibende Risiken und nächster Schritt

- Docker-/E2E-Ausführung bleibt lokal durch den nicht erreichbaren
  Docker-Desktop-Daemon blockiert; der externe PR-Browserlauf bleibt
  verbindlich.
- Offen in P1: Konfiguration/Settings/Logging, DB-Initialisierung versus
  Job-Recovery und der Releasevertrag für `APP_VERSION`/statische Pfade.

### Veröffentlichungsstand

- PR #666 wurde am `2026-09-15T19:51:52Z` als Squash gemergt; Merge-Commit
  `99afb2a40edb36505831d07c6be8bf9342599a97` ist auf `origin/develop`
  erreichbar.
- Browser-/Accessibility-, SonarCloud-, CodeQL-, Container- und Testchecks
  sind PASS. Der zeitgebundene Koordinator-Job lief vor Abschluss des
  eigentlichen Codex-Review-Checks aus; der Codex-Review-Check selbst ist PASS.

## P1.3 — Settings-Auswahl und Redaction/Logging

- Basis: bestätigter Merge-Commit
  `99afb2a40edb36505831d07c6be8bf9342599a97` von PR #666.
- Settings-Worker: geprüfter lokaler Commit
  `8e1c5ac7661fa8a967669e989036b1eedcf5b572`; Schreibbereich ausschließlich
  `backend/settings.py` und `tests/test_settings.py`.
- Settings-Review: **PASS** — `SettingsService` besitzt Anbieter-, Modell-,
  Thinking- und Kalenderauswahl vollständig, liest die Konfiguration pro
  Aufruf dynamisch, verwendet die unveränderten KV-Schlüssel und besitzt keine
  Importaktivität oder Rückabhängigkeit auf `server.py`.
- Observability-Worker: korrigierter lokaler Commit
  `1e5e5344bf723e8d3142cb4ff0c82bffa12f034c`; Schreibbereich ausschließlich
  `backend/observability.py` und `tests/test_observability.py`.
- Erstes Observability-Review: **FAIL** — das neue Logging-Setup hätte bei
  bereits vorhandenen fremden Handlern zusätzliche Handler und Verzeichnisse
  erzeugt, statt den bisherigen Early-return-Vertrag zu bewahren.
- Korrekturreview: **PASS** — beliebige vorhandene Handler bleiben unverändert,
  und der negative Dateisystemvertrag ist durch einen Regressionstest belegt.
- Erstes Integrationsreview: **FAIL** — vier HTTP-Diagnostikaufrufer benötigten
  weiterhin den aus `server.py` entfernten sicheren Netloc-Helfer.
- Geprüfter integrierter Commit:
  `5698db5d5f51341825081c6e679e184ff021bd14`.
- Integrations-Re-Review: **PASS** — `safe_url_netloc` ist eine kleine
  öffentliche Observability-Schnittstelle, sämtliche vier Aufrufer verwenden
  sie direkt. Settings- und Redaction-Aufrufer sowie Test-Patchziele wurden auf
  die konkreten Eigentümer migriert; es gibt keine Kompatibilitätswrapper oder
  `server.py`-Rückimporte.
- `server.py`: 21.525 physische Zeilen, 1.204 verbleibende
  Funktionen/Klassen; das Inventar enthält 1.685 Einträge und wieder exakt
  null unzugeordnete P0-Einträge. Maßgeblich ist die Eigentumsverlagerung, nicht
  die Reduktion um 310 Zeilen gegenüber P1.2.

### Prüfungen

- `python -m unittest discover -s tests -v` — 825 Tests, 12 übersprungen,
  PASS in 121,405 s.
- Gezielte Settings-/Redaction-/HTTP-/Provider-/Coach-Regressionen — PASS;
  insbesondere dynamische Config, persistente Auswahl, Secret-/URL-/Traceback-
  Redaktion, fremde Logging-Handler und sichere HTTP-Host-/Pfadprojektion.
- `ruff check scripts/server_extraction_inventory.py backend/settings.py backend/observability.py tests/test_settings.py tests/test_observability.py`
  — PASS.
- `python -m compileall -q server.py backend tests` — PASS.
- `python scripts/server_extraction_inventory.py --check` — PASS.
- `git diff --check` — PASS.
- Der repositoryweite Ruff-Aufruf meldet ausschließlich bereits vorhandene
  Import-/Simplify-Befunde in `server.py` und älteren Tests; neue Module,
  neue Tests und der Inventargenerator sind sauber.

### Verbleibende Risiken und nächster Schritt

- Der P1-Punkt bleibt bewusst offen: Konfigurationsvalidierung,
  Settings-Dateischreibpfade, Provider-Freshness und die übrige diagnostische
  Observability sind noch fachlich in `server.py`.
- Als nächste abhängige P1-Arbeit folgen die Trennung von Schema-Initialisierung
  und Job-Recovery sowie danach die verbleibenden Config-/Observability-
  Teilpakete. Docker-/E2E bleibt lokal extern blockiert; das PR-CI-Gate ist
  verbindlich.

## P1.4 — Datenbank-Bootstrap und explizite Recovery

- Basis: bestätigter Merge-Commit
  `9d6101c0d1fe2a7a4c5259550758c663a6ff2b5b` von PR #667; der Commit ist auf
  `origin/develop` erreichbar und sein Tree stimmt mit dem geprüften PR-Head
  `c4549bcec1c4b8a3e71db95a7f858f45ff964c9a` überein.
- Bootstrap-Worker: korrigierter lokaler Commit
  `7669b8af4f25df5d40b91586bee6e32d36ddcfc6`; Schreibbereich ausschließlich
  `backend/db/bootstrap.py` und `tests/test_db_bootstrap.py`.
- Erstes Worker-Review: **FAIL** — der Retention-Test prüfte zunächst keinen
  echten Clamp, und der Import-Smoke-Test verwendete den bereits gefüllten
  Modulcache.
- Korrekturreview: **PASS** — Unter- und Obergrenze werden mit 1 und 9.999 Tagen
  tatsächlich geprüft; ein frischer Subprozess importiert das Modul aus einem
  leeren temporären Arbeitsverzeichnis ohne Seiteneffekt.
- Geprüfter integrierter Commit nach Rebase:
  `01f5fd00abb88700e52c9c9eab20fe81eb1f4ebb`.
- Erstes Integrations-Gate: **FAIL** — der gezielte Testaufruf verwendete nicht
  den bestehenden `tests/support.py`-Importpfad, und das nach der Verlagerung
  veraltete Inventar enthielt einen unklaren P0-Eintrag.
- Integrations-Re-Review: **PASS** — `initialize_application_database` besitzt
  Schemaanlage und -validierung, Defaultprofil, transiente Startmarker sowie
  begrenzte Retention vollständig. `server.initialise_database` verdrahtet nur
  den bestehenden DB-Lock, die Unit-of-Work und konkrete Abhängigkeiten.
  Recovery wird in `main()` vor beiden Workern explizit ausgeführt; Restore
  behält seinen notwendigen eigenen Recovery-Pfad. Es gibt keine Rückimporte,
  Kompatibilitätswrapper oder Provider-/Worker-Aktivität beim Modulimport.
- `server.py`: 21.494 physische Zeilen, 1.204 verbleibende
  Funktionen/Klassen. Das Inventar enthält wieder null unzugeordnete
  P0-Einträge; `bootstrap_provider_states` ist als P10-Projektion nach
  `http_api/bootstrap.py` zugeordnet.

### Prüfungen

- `python -m unittest discover -s tests -v` — 834 Tests, 12 übersprungen,
  PASS in 168,902 s.
- Gezielte Bootstrap-/Schema-/Retention-/Recovery-/Architekturtests — PASS;
  insbesondere mutationsfreie Ablehnung eines Fremdschemas, Transaktions- und
  Lock-Erhalt sowie Recovery vor Workerstart ohne Doppelaufruf.
- `ruff check backend/db/bootstrap.py tests/test_db_bootstrap.py scripts/server_extraction_inventory.py`
  — PASS.
- `python -m compileall -q server.py backend tests` — PASS.
- `python scripts/server_extraction_inventory.py --check` — PASS.
- `git diff --check` — PASS.

## P1 — Release- und statischer Assetvertrag

- Review: **PASS** — `APP_VERSION` bleibt bewusst als exakt formatierte
  Zuweisung in `server.py`. `.github/scripts/release_source.py`, das
  Codex-Review-Gate und `.github/workflows/weekly-release.yml` lesen oder
  ändern genau diesen Pfad und dieses Format; eine spätere Verlagerung muss
  diese drei Verbraucher samt ihren Vertragstests atomar migrieren.
- `PUBLIC_DIR`, Asset-Mapping, `VERSIONED_STATIC_ASSETS` und `send_static`
  bilden bis P10 eine gemeinsame Transportgrenze. Traversal-/Absolutpfad-,
  ETag-/Cache-Control- und Service-Worker-Tests sichern sie ab.
- Der PWA-Cachevertrag bleibt unverändert: Bei Assetänderungen werden die
  Query-Versionen in `public/index.html` sowie Cache-Name und URLs in
  `public/service-worker.js` gemeinsam aktualisiert.

### Verbleibende Risiken und nächster Schritt

- Lokal bleibt Docker/E2E wegen des nicht verfügbaren Docker-Daemons extern
  blockiert; das PR-CI-Gate ist verbindlich.
- Offen in P1 sind Konfigurationsvalidierung, Settings-Dateischreibpfade,
  Provider-Freshness und die übrige diagnostische Observability. Diese werden
  vor P2 in kleinen, getrennten Schreibbereichen abgeschlossen.
