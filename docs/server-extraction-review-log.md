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
- PR-CI-Erstlauf: **FAIL** — im Container liegt das importierte `backend`
  unter `/app`, während die Tests separat unter `/review/tests` gemountet sind;
  der Import-Smoke-Test leitete `PYTHONPATH` fälschlich vom Testdateipfad ab.
- CI-Korrektur: Der Smoke-Test leitet den Paket-Root nun vom tatsächlich
  importierten `backend.__file__` ab und bleibt damit im Worktree wie im
  Container unabhängig vom Test-Mount.
- Geprüfter Korrekturcommit: `27dd500c38860884c43e3efe1233dc63f5a85766`.

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

## P1.5 — Persistente Konfiguration, Diagnostic-Capture und Provider-Freshness

- Basis: bestätigter Merge-Commit
  `abf467b2377c6aac30a626e848f7b966f796d2d7` von PR #668; `mergedAt`
  `2026-09-15T20:40:44Z` und Erreichbarkeit auf `origin/develop` bestätigt.
- Konfigurations-Worker: korrigierter lokaler Commit
  `0b4ef9862c71137e9a2b9a897c1be55f5f35dc09`; Schreibbereich ausschließlich
  `backend/config.py` und `tests/test_config.py`.
- Erstes Konfigurationsreview: **FAIL** — der Worker hatte die Prozessumgebung
  erst nach dem Dateischreiben aktualisiert und einen nicht portablen
  Import-Smoke-Test verwendet. Korrekturreview: **PASS** — Allowlist,
  CR/LF-Bereinigung, Fehlerabbildung, Update-Reihenfolge und der Import aus
  leerem temporärem Arbeitsverzeichnis entsprechen dem Ausgangsvertrag.
- Diagnostic-Capture-Worker: korrigierter lokaler Commit
  `f3ffeae943ad564a2828c443f90ea65136f79cca`; Schreibbereich ausschließlich
  `backend/observability.py` und `tests/test_observability.py`.
- Erstes Capture-Review: **FAIL** — naive persistierte Ablaufzeiten wurden neu
  als UTC akzeptiert, und der Importtest war nicht containerportabel.
  Korrekturreview: **PASS** — nur timezone-aware Ablaufzeiten aktivieren die
  Aufzeichnung; abgelaufener/fehlerhafter Zustand wird bereinigt, der konkrete
  `DiagnosticCapture` besitzt allein seinen `RLock`, und die 1.500-Eintrags-
  sowie Ein-Stunden-Grenzen bleiben erhalten.
- Freshness-Worker: lokaler Commit
  `23dc506aa2f313e24d5c2f692008c0bc149d0359`; Schreibbereich ausschließlich
  `backend/sync/freshness.py` und `tests/test_sync_freshness.py`.
- Freshness-Review: **PASS** — sechs Bereiche, Reihenfolge, Labels,
  Fresh/Stale/Error/Partial/Syncing-Zustände, zukünftige Retry-Projektion und
  begrenztes Cleanup entsprechen dem Ausgangscode. Das Modul besitzt weder
  Lock noch Commit/Rollback, Provider-I/O oder Dateisystemzugriff; Verbindung
  und Transaktion bleiben beim Aufrufer.
- Geprüfter integrierter Code-Stand nach Rebase auf `origin/develop`:
  `a44a7d35d25afe5e58eca699a0a68a866c250b76`.
- Integrationsreview: **PASS** — Konfigurations- und Capture-Aufrufer sowie
  Test-Patchziele verwenden die fachlichen Eigentümer direkt. Die
  Freshness-Fachlogik ist vollständig verlagert; `_current_provider_freshness`
  verdrahtet ausschließlich die konkrete Konfiguration, KV-/Profilzugriffe,
  den vorhandenen DB-Kontext und die Uhr. Es bestehen keine Rückimporte auf
  `server.py`, keine Server-Callbacks mit ausgelagerter Fachlogik und keine
  Kompatibilitätswrapper.
- `server.py`: 21.127 physische Zeilen, 1.181 verbleibende
  Funktionen/Klassen. Das Inventar enthält 1.650 Einträge und null offene
  P0-Zuordnungen. Die Reduktion um 367 Zeilen gegenüber P1.4 ist lediglich ein
  Begleitwert; maßgeblich sind die klaren Zustands- und Fachlogikeigentümer.

### Prüfungen

- `python -m unittest discover -s tests` nach Rebase auf den aktuellen
  Zielbranch — 852 Tests, 12 übersprungen, PASS in 186,011 s.
- Gezielte Config-/Capture-/Freshness-/Architektur- und Serverregressionen —
  PASS; insbesondere persistente Umgebungspriorität, Capture-Parallelität,
  Redaktionsgrenzen, Freshness-Retry, caller-owned Rollback und
  Startup-Sicherheitsprüfung.
- `ruff check backend/config.py backend/observability.py backend/sync/freshness.py tests/test_config.py tests/test_observability.py tests/test_sync_freshness.py scripts/server_extraction_inventory.py`
  — PASS.
- `python -m compileall -q server.py backend tests` — PASS.
- `python scripts/server_extraction_inventory.py --check` — PASS.
- `git diff --check` — PASS.
- PR-#679-Sonar-Erstlauf: **FAIL** — drei neue `python:S1192`-Befunde im
  Inventargenerator für mehrfach verwendete Eigentümerpfade.
- Korrekturreview des konkreten Diffs: **PASS** — die Pfade für
  `coach/context.py`, `performance/activity_validation.py` und
  `sync/refresh.py` besitzen nun jeweils genau eine Konstante; die erzeugten
  Eigentümerwerte und damit das Inventar bleiben unverändert.
- Korrekturprüfungen: `python scripts/server_extraction_inventory.py --check`,
  `python -m unittest tests.test_server_architecture`,
  `ruff check scripts/server_extraction_inventory.py` und `git diff --check`
  — PASS.

### Verbleibende Risiken und nächster Schritt

- Docker-/E2E-Ausführung bleibt lokal durch den nicht erreichbaren
  Docker-Desktop-Daemon blockiert; Container-, Browser-, Accessibility- und
  Security-Gates werden deshalb im PR verbindlich geprüft.
- Diagnosehistorie und -report bleiben planmäßig P9; OpenAI-spezifische
  Diagnoseklassifikation sowie sichere HTTP-Header gehören mit dem Transport
  zu P2. P1 ist damit vollständig abgeschlossen, nächster Schritt ist P2 in
  kleinen Provider-Adapter-Paketen.

## P2.1 — Providerfehler und iCalendar-Parsing

- Basis: bestätigter Merge-Commit
  `68f2e140f54d1282ffd399177de0e7cbee83aa05` von PR #679; `mergedAt`
  `2026-09-19T15:44:12Z` und Erreichbarkeit auf `origin/develop` bestätigt.
- OpenAI-Worker: geprüfter Commit
  `d740ec1327041379ce0dd232fcb8f727992b7cd6`, integriert als `c438ac8`.
  Review: **PASS** — Retry-After, Quota-/Billing-, Conversation-Lock- und
  Invalid-State-Klassifikation, sichere Diagnosefelder und allowlist-basierte
  Rate-Limit-Projektion sind rein und geben keinen Providertext weiter.
- Kalender-Worker: Commits `1116a13972c8a5142b61cd300ecdac2bd63273b7`
  und `f663e31d506e9ee9cb087b98a3bb8825c691a770`, integriert als `d730214`
  und `4b1dbf5`. Erstes Review: **FAIL** — drei Rekurrenzschleifen verglichen
  ihre Laufvariable mit einer mitwachsenden rechten Seite und `unfold_ical`
  bot einen verbotenen Fehler-Callback. Korrekturreview: **PASS** — feste
  Iterationsgrenzen und direkter `AppError`-Vertrag.
- Der erste Kalender-PASS wurde nach dem Integrationsabgleich widerrufen:
  **FAIL** — die delegierten Grenzwerte 2 MB/120 Tage/8.000 Perioden wichen
  vom tatsächlichen Serververtrag ab. Korrekturcommit
  `03f2d9e17ef4289a2a61e81e83807d0f2d3f4745`, integriert als `e7c0dbd`;
  erneutes Review: **PASS** mit 5 MB, 56 Tagen, 1.000 Instanzen und 10.000
  Rekurrenzperioden.
- Gemini-Worker: geprüfter Commit
  `0c7ea0f27806625d2794cdcad9ba83daf52bd4d9`, integriert als `81ae0cf`.
  Review: **PASS** — die bestehende Auth-/Quota-/Rate-Limit-/HTTP-
  Klassifikation ist unverändert und die Rückgabe enthält keinen Rohtext.
- Geprüfter integrierter Commit: `ff1be93`. Integrationsreview: **PASS** —
  Kalenderparser und Fehlerklassifikation sind vollständig aus `server.py`
  entfernt; Aufrufer verwenden die Provider-Module direkt. Es gibt keine
  Rückimporte, Server-Callbacks oder Kompatibilitätswrapper. Kalender-Sync
  parst vor dem Löschen der letzten guten Events; URL-/DNS-Grenzen,
  Transaktion, Replan und Fehlerstatus bleiben erhalten. Architekturtests
  verhindern die Rückverlagerung der entfernten Symbole.
- Das nach der Löschung zeilenverschobene Inventar meldete vorübergehend 52
  falsche P0-Zuordnungen. Review: **FAIL** für die Inventarqualität. Die
  Eigentümer wurden symbolbasiert stabilisiert; erneutes Review: **PASS** mit
  null offenen P0-Zuordnungen.
- `server.py`: 20.357 physische Zeilen und 1.118 verbleibende
  Funktionen/Klassen. Das Inventar enthält 1.570 Einträge; davon bleiben 113
  Definitionen und 13 globale Bindungen in P2 offen. Die Zeilenreduktion ist
  nur Begleitwert; maßgeblich sind direkte Eigentümer und entfernte Wrapper.

### Prüfungen

- Provider-/Architekturtests: 23 Tests, PASS.
- Kalender-/Gemini-Aufruferregressionen: 9 Tests, PASS.
- Erster vollständiger Lauf: **FAIL** — 869 von 870 Tests bestanden; ein Test
  patchte noch den entfernten `_gemini_tools`-Wrapper.
- Migriertes Testziel auf `backend.providers.gemini.function_tools`: PASS.
- Abschließender integrierter Lauf:
  `python -m unittest discover -s tests -v` — 870 Tests, 12 übersprungen,
  PASS in 185,358 s.
- `ruff check backend/providers/calendar.py backend/providers/gemini.py tests/test_provider_calendar.py tests/test_provider_gemini.py`
  — PASS. Repositoryweiter Ruff bleibt wegen bereits vorhandener Monolith-
  und Architekturtestbefunde nicht grün.
- `ruff check scripts/server_extraction_inventory.py` — PASS.
- `python -m compileall -q server.py backend` — PASS.
- `python scripts/server_extraction_inventory.py --check` — PASS.
- `git diff --check` — PASS.

### Verbleibende Risiken und nächster Schritt

- P2 ist noch nicht abgeschlossen: HTTP-Transport, vollständige OpenAI-
  Requests/SSE/Background/Audio, vollständige Gemini-Payload-/Streaming-
  Orchestrierung, Kalender-SSRF/Abruf sowie Garmin-/Intervals-Adapter bleiben
  offen.
- Docker-/E2E-Ausführung bleibt lokal durch den nicht erreichbaren
  Docker-Desktop-Daemon blockiert; die externen PR-Gates bleiben verbindlich.

## P6.1 — Sync-Reconciliation, durable Queue und providerneutraler Sync-State

### Geprüfte und integrierte Stände

- Planned-Unit-State-Worker `220a377df0ac89aed30e8e18e90ed12045ea0c82`,
  integriert als `03e9a8f`, Server-Komposition `a04aee6`: **PASS**. Der
  `PlannedUnitSyncStateWriter` besitzt Revision, kanonischen Payload-Hash,
  Remote-Identität, Fehlerredaktion und Transaktionsgrenze; der frühere
  `ReconcileDependencies`-Callback-Bag ist entfernt.
- Competition-Reconcile-Worker
  `dcac88f1a2088af7c8957665a0fead915c608775`, integriert als `2bad72e`,
  Server-Komposition `e101b93`: **PASS**. Lokale Records, exakte
  Tombstone-Löschung, optimistischer Abgleich, Konflikte und Remote-Import
  liegen im `CompetitionSyncReconciler`; Provider-/Lock-Orchestrierung ist
  als noch offener P6-Rest ausgewiesen.
- Queue-Worker `69bf9a7f4628acd951f1df5011d11036fcee8da2`, integriert als
  `4955fc5`: **FAIL** im ersten Integrationsgate, weil `claim()` eine DTO-Payload
  statt des vom Executor erwarteten JSON-Strings zurückgab. Korrektur desselben
  Workers `5a444a941f0f3a16f39302c03c0d5cac4cf58ab3`, integriert als `c76cca9`,
  Server-Komposition `e92494b`: **PASS** für Claim-/Payload-, Retry-,
  Single-flight-, Resultat- und Restart-Verträge.
- Der vollständige Lauf nach Queue-/Library-Komposition war erneut **FAIL**:
  `public_bootstrap` verwendete vier statt einer, `public_state(local_only)`
  fünf statt zwei Verbindungen. Nach isolierter Library-Korrektur blieb je
  eine Zusatzverbindung. Queue-Korrektur
  `1962c25547c0cec4268adcdd3618b85deb67cfd0`, integriert als `bf3ee4d`,
  danach **PASS**: alle vier read-only Store-Pfade verwenden den verschachtelten
  Request-UOW; Claim- und Mutationstransaktionen blieben unverändert.
- Library-State-Worker `644ca7463038dd95a6d73fc0bfcdc88e15920ea0`,
  integriert als `7420d35`, erste Server-Komposition `49ec797`: im gezielten
  Gate **PASS**, im vollständigen Connection-Gate **FAIL**. Korrektur
  `b7ca163540c7527517ac9ee9752837340df86020`, integriert als `a7133b6`,
  Server-Komposition `81757e5`: **PASS**. Preview/Summary teilen den Request-UOW;
  Load, früh persistierte Remote-ID und atomarer Finish samt beiden KV-Markern
  besitzen jetzt einen eindeutigen lokalen Zustandseigentümer. Ein ungültiges
  Providerresultat lässt die neue Remote-ID absichtlich für duplikatfreie
  Retries bestehen.
- Sync-State-Worker `766a8492b3fc97c026b8a1fffdcf9a9395ae4b8b`:
  **FAIL** im ersten Root-Review wegen zusätzlicher Reader-Verbindungen und
  verschärfter unbekannter Setter-Quelle. Korrektur
  `f63e37e82137ecf3803a70f8a5e64e466900c467`: **PASS**, integriert als
  `84c9109` und `041aba4`; Server-/Testmigration `b1e9442`. Snapshots, Cursor
  und Sync-Zeiträume besitzen gemeinsame UOW-/Rollback-Grenzen. Alte
  Serverdefinitionen und Patch-Ziele sind entfernt.
- Server-Date-Window-Adapter `84698d9`: **PASS**. Alle drei Aufrufer verwenden
  `backend.sync.windows.split_date_windows` direkt; der Kompatibilitätswrapper
  ist entfernt. Das letzte übersehene Cursor-Patch-Ziel wurde in `4640ed6`
  auf `SyncStateRepository.cursor` migriert.
- Snapshot-Merge-Worker `5a16a3a1e914073d51379c1f88eeacd759c7166b`,
  integriert als `722d2a9`, Server-/Testmigration `55c3935`: **PASS**. Historische
  Snapshot-Zusammenführung und Garmin-Snapshot-Merge liegen ohne Serverzugriff
  in `sync/snapshots.py`; die bisherigen Serverdefinitionen und direkten
  Testzugriffe sind entfernt.
- Job-Contract-Worker `9122816`: **FAIL** im Root-Code-Review wegen eines
  verschärften UUID-Vertrags, abgewiesener zusätzlicher Plan-Entry-Felder und
  eines zusätzlichen `OverflowError`-Catch. Korrektur desselben Workers
  `4c702b894be808181f3f9ff201c501d5bfaabc37`, integriert als `080738b` und
  `8ea754f`, Servermigration in `1d75e8f`: **PASS**. Request-Normalisierung und
  Retry-Delay werden direkt aus `sync/jobs.py` verwendet; die acht alten
  Servernormalisierer sind entfernt.
- Competition-Service-Worker `3417da1`: **FAIL** im Root-Code-Review, weil
  Cleanup- und Fehlerpfade neu unterdrückt wurden. Korrektur
  `5dbf8f1665d21ba4c1cd536942e6ef1e2d64b600`, integriert als `7ca252f` und
  `e67611f`, Servermigration in `1d75e8f`: **PASS**. Providerablauf, Cleanup,
  Reconciliation und gemeinsamer Lock gehören `sync/competitions.py`; der
  Serveradapter enthält nur noch Gate und Serviceaufruf.
- Library-Entry-Worker `b970f51`: **FAIL** im ersten Integrationsreview, weil
  der ausgelagerte Lock nicht mit Refresh und öffentlichen Running-Projektionen
  geteilt wurde. Korrektur `6d48819684606fba920f2527b0b1778cb2a25af6`,
  integriert als `d7a0cdb` und `6e252cf`, Servermigration `80f4936`: **PASS**.
  Einzel-Update/Recovery/Create, früh persistierte Remote-ID, finaler Zustand
  und Kalenderidentität teilen jetzt denselben Module-Lock.
- Planned-Remote-Reconcile-Worker `7a932e2`: **FAIL** im Root-Code-Review wegen
  neu unterdrückter Normalisierungsfehler und nichtobjektartiger lokaler
  Payloads. Korrektur `58b0d22b4dbccb87907a1941a0eebf713e0df9e5`,
  integriert als `d3bbb05` und `3b5a777`, Servermigration
  `a5d6b3153d47711f0ec87a0d85af29a0ebfdb90b`: **PASS**. Der Reconciler besitzt
  eine UOW, eine Revisionsanhebung pro mutiertem Lauf und CAS über den ganzen
  gelesenen Datensatz; Rollback- und alte Fehlersemantik sind belegt. Sechs
  Server-Fachfunktionen sowie sämtliche alten Patch-Ziele sind entfernt.
- Provider-Resync-Gates, Root-Commit `cbdf88c629a34c01034175150d452516e0d9dcec`:
  **PASS**. Beide Gate-Instanzen, aktiver Operationszähler, Reset-Owner und
  Decorators gehören `sync/gates.py`; `server.py` importiert ausschließlich die
  konkreten Eigentümer. Owner-Reentranz, Wait und fremde 409-Sperre sind durch
  drei isolierte Concurrency-Tests sowie neun Resync-/Decorator-Regressionen
  belegt.
- Remote-Library-Reconcile-Worker
  `00d365adc405ca237a7b63c905b827520add4db4`, integriert als `15a8469`,
  Server-/Testmigration `39c084650d79d4c5763ad75e433ef1f3c9ea92d4`:
  **PASS**. `WorkoutLibraryRemoteReconciler` besitzt eine atomare UOW,
  Dirty-Preservation, lokalen Metadata-Merge, Storage-/Local-ID-Erhalt und
  Missing-Markierung ohne Provider-I/O. Fünf Server-Fachfunktionen und alle
  alten direkten Testaufrufe sind entfernt.
- Planned-Calendar-Single-Push-Worker
  `3b2a83ff86b7465ad9fef200734ffd73236041df`, integriert als `8380413`,
  Server-/Testmigration `bd33e83017e2692ed67cd5c098bf97429d393697`:
  **PASS**. `PlannedCalendarSyncService` besitzt Load, Remote-Upsert/-Delete,
  Identity- und Payload-Recheck, Readback-Validierung sowie State-Persistenz;
  der exportierte per-ID-Guard wird zugleich vom verbliebenen Repair-Pfad
  verwendet. Zwölf Server-Fachfunktionen und der doppelte Lock-Zustand sind
  entfernt.
- Snapshot-View-Persistenz, Root-Commit
  `8fbfda529078b043367b94d00a58627d1fb7f81f`: **PASS**. Lokale
  Ansichtsänderungen besitzen mit `SyncStateRepository.save_view` dieselbe
  Manager-/UOW-Grenze wie die übrigen Snapshots, verändern aber weiterhin
  keine Sync-Zeitmarker. Der Server-DB-Wrapper und seine Testaufrufe sind
  entfernt.
- Library-Refresh-Worker
  `a57cb797b0b7f9be400d484acb600e02472782d6`, integriert als `c495d55`,
  Server-/Testmigration `295f1c36a2ce8a769cfb382049aaff19fe3cc6ef`:
  **PASS**. Initialer Remote-Read, Local-authoritative-Skip, Cancellation,
  Reconcile, Erfolgsmarker und Event-Publikation gehören
  `WorkoutLibraryRefreshService`; Maintenance-/Intervals-Gate und der
  bestehende modulweite Library-Lock liegen am Service. Der interne
  Serverwrapper und alle alten Patch-Ziele sind entfernt.
- Freshness-Worker `481f3175ec574fbad939c29fd5cc8f006b5ce5fd`,
  integriert als `8f9776f`, Server-/Testmigration
  `f57f892b663dc6e33892364c55091414fed306f6`: **PASS**.
  `ProviderFreshnessService` besitzt genau eine UOW für Cleanup, History,
  Retry-Projektion und sämtliche KV-Fallbacks; Erfolg committed, ein
  Projektionsfehler rollt Cleanup zurück. `_current_provider_freshness` und
  alle servergebundenen Aufrufe sind entfernt.
- Planned-Calendar-Repair-Worker
  `28bdf1654a566d16707e7cd12fba5ce1dc8542ae`: zunächst **FAIL**. Der erste
  Diff übernahm eine vom Provider abweichend zurückgegebene externe ID,
  schrieb beim finalen Hashkonflikt einen neuen Zustand und veränderte die
  strikte Batch-Read-/Verify-Semantik. Korrekturen desselben Workers
  `d6fed86cdde3ce85a851f614af8452be5446ea1c` und
  `a67d94626280c714cc179311118698aea6ab3cea`, integriert als `0ca6a15`,
  `37b2bcb` und `2413a2c`, Server-/Testmigration
  `1c455727428e3af987e5992dc3ec3a2601c08065`: **PASS**. Kanonische externe
  Identität, Hash-Neubindung, zwei Collection-Reads pro normalem Batch,
  deferred Completion, Duplicate-/Foreign-Grenzen und derselbe per-ID-Guard
  wie beim normalen Push sind belegt. Der vollständige Repair-Cluster und der
  generische Server-State-Wrapper sind entfernt; Fehlerpersistenz verwendet
  den konkreten Repair-Service.
- Gemeinsamer Intervals-Lock, Root-Commit
  `320546f220da598982ff323da8f3f07e088df7a8`: **PASS**. Der Lock besitzt
  mit `sync/intervals_lock.py` genau einen Backend-Eigentümer; Server und
  Concurrency-Tests verwenden dieselbe Instanz ohne Alias oder zweiten Lock.
- Daily-Marker-Worker `c8c71b70a57243a15857a72ecad6670e78bd7301`,
  integriert als `4273ffc`, Server-/Testmigration `6692f72`: **PASS**.
  `DailySyncMarkerService` besitzt Read/Write-UOW, lokale Datumssemantik,
  Source-Allowlist und Rollback. Die zwei Server-Callback-Wrapper und alle
  alten Patch-Ziele sind entfernt.
- Selected-Batch-Worker `b8727f09fcb0bca4fe8c5b2d8469b60350481453`:
  zunächst **FAIL**. Library-Remoteaufrufe hatten das Intervals-Resync-Gate
  verloren und die Auswahlabfrage wechselte von der serialisierten UOW auf
  einen Reader-Lease. Korrektur desselben Workers
  `6f3458e7bde02abd222298cdc2d5a79a9c52b0e2`, integriert als `bf193ea`,
  Server-/Testmigration `c8c407dfb4f1d8acf2ee97dfde5ead6151d96131`:
  **PASS**. Hash-/Konfliktprüfung, per-Entry-Fehlerisolation, Repair-Batch-
  Verifikation und Antwortprojektion liegen vollständig im Service; jede
  Library-Remoteoperation erhält ihre bisherige konkrete Gate-Grenze, Planned-
  Pfade bleiben unverändert, und der gemeinsame Repair-Lock wird immer gelöst.
- Performance-Refresh-Worker
  `175a1722a8ba89a83d91117223fec7b7f97ab454`, integriert als `f224667`,
  Server-Komposition `15e9ca8296b917dcd6c6129f23d43bfe28f19eee`:
  **PASS** für den inneren Use-Case. Remote-I/O liegt außerhalb der DB-UOW;
  der frische Snapshot-Merge, Save und Erfolgsmarker sind atomar, Fehler sind
  redigiert, und Running-Marker sowie Module-Lock werden auch bei Provider-,
  Storage-, Event- und Cleanup-Fehlern deterministisch bereinigt. Die äußere
  Observability-/Maintenance-/Provider-Gate-Hülle bleibt bewusst offen und
  verhindert einen verfrühten P6-Abschluss.
- Intervals-Snapshot-Worker
  `45dee97af339cb3a30c7d628067a420e63837e78`, integriert als `c9c594e`:
  **PASS** im tatsächlichen Diff-, Code- und Altverhaltensreview. Historische
  und aktuelle Snapshot-Speicherung, initialer Planned-Import samt
  Repair-Deferral, Cursor/Fenster/Pagination sowie Library-Initialisierung
  besitzen `IntervalsSnapshotService`. Reconcile und Initialmarker teilen
  dieselbe UOW und rollen gemeinsam zurück; der Remote-Library-Refresh läuft
  ohne offene DB-UOW, Cancellation und Fehlerredaktion bleiben erhalten.
- Garmin-Data-Prep-Worker
  `3ea650f15252ad38032663bf6cc5dd853ee051fc`, integriert als `134996f`:
  **PASS** im tatsächlichen Diff-, Code- und Altverhaltensreview. Relative und
  absolute Fixture-Pfade, identische Fehlermeldungen, aktuelle Sleep-Daten,
  Source-Freshness, partielle/historische Merges und Completion-Semantik liegen
  in `sync/garmin.py`; Rohdaten und Morning-Body-Battery bleiben unverändert.
- Root-Beobachtungsgrenze `a3879f1` und geprüfte Serverintegration
  `ab2bbdd8413727e93aa4202df205258c6d4f3637`: **PASS**. Maintenance-Gate,
  `ContextVar`, Refresh-Historie, Statusmapping und sichere Lifecycle-Logs
  gehören `SyncOperationObserver`; die doppelte Maintenance-Dekoration ist
  entfernt. Garmin-/Intervals-Patch-Ziele zeigen auf die Eigentümermodule,
  alte Serverdefinitionen sind durch Architekturtests gesperrt. Der
  Morning-Body-Battery-Service erhält den konkreten Fixture-Loader statt
  zweier Server-Callbacks.
- Performance-Follow-up-Worker `b6af5f2`, integriert als `ee0df02`, und
  Job-Outcome-Worker `d056163`, integriert als `04ef000`, gemeinsame
  Serverintegration `390b297`: **PASS** im tatsächlichen Root-Diff- und
  Code-Review. Queueing/Polling des gezielten Performance-Refresh sowie
  Completion, Retry, Requeue und redigierte Fehlerpersistenz beanspruchen
  konkrete Backend-Eigentümer. Die zehn früheren Server-Helper sind entfernt;
  es gibt keine fachlichen Server-Callbacks oder Kompatibilitätswrapper.
- Intervals-Reader-Worker `ad4d434`, integriert als `604f94c`,
  Serverintegration `13f0ec8da538089b0c102ebae3dda379014d6326`:
  **PASS**. Der konkrete `IntervalsApiClient` wird in der Composition Root
  gebaut; `IntervalsSnapshotReader` besitzt aktuelle, historische und
  Performance-Reads einschließlich Cancellation und Fenstersemantik.
  `IntervalsClient.fetch_snapshot` und `fetch_performance_snapshot` sind
  entfernt und durch einen Architekturtest dauerhaft gesperrt.
- Vollständiger Intervals-Gesamtablauf, integrierter Commit
  `3b7dc89549414da7bee86ce7dd8ce07282744b07`: **PASS** im eigenen
  vollständigen Diff- und Code-Review. `IntervalsSyncService` besitzt äußeren
  Observer und Provider-Gate, gemeinsamen Lock, Wait-for-existing,
  Cancellation, Status-/Eventpersistenz, Snapshot-/Fenster-/Marker-Ablauf,
  Library-Initialisierung, Performance-Follow-up, Fehlerredaktion und Cleanup.
  `set_sync_operation_state`, fünf private Ablauf-Helper und
  `sync_intervals` sind aus `server.py` entfernt; alle Aufrufer und Test-
  Patchziele verwenden den konkreten Eigentümer. Autorisierung und sämtliche
  Remote-Schreibpfade blieben unverändert.
- Sync-Worker-Runtime, Luna-Worker-Commit
  `0efa0a2717cc1179b2376971e075cae00b0ff344`, integriert als `cf6f2fe`:
  **PASS** im tatsächlichen Diff- und Code-Review. `SyncJobWorker` besitzt
  Thread, Start-Lock, Wakeup/Stop, Claim, Restore-Generation und den
  dauerhaften Polling-Lebenszyklus; das Modul importiert `server.py` nicht und
  löst den Start-Lock auch bei Thread-Startfehlern. Der konkrete
  Executor-Dispatch bleibt bewusst offen, damit keine fachliche Server-
  Callback-Grenze verfestigt wird.
- Garmin-Payload-Service, Luna-Worker-Erststand
  `c53b34d2e62f3da54273e1c7b73049b382c69f29`, integriert als `c5bb50f`:
  **FAIL** im Root-Code-Review, weil die neue Activity-Match-Projektion Paare
  mit fehlenden IDs ausfilterte und damit das bisherige Verhalten änderte.
  Korrektur desselben Workers
  `818f1c0f6da0c40514bc340cbc2e96cc9f257b13`, integriert als `e63c383`:
  **PASS**. Snapshot-Read, Fixture-/Remote-Aufbereitung, Source-Merge,
  Deduplikation, Max-HR, Activity-Matches und Performance-Historie liegen
  vollständig in `GarminPayloadService`; die exakte Paarsemantik ist durch
  eine Regression mit fehlenden IDs belegt.
- Vollständiger Garmin-Gesamtablauf, integrierter Commit
  `7654aca75a7c721282a035aca2e7da809d1d5f79`: **PASS** im vollständigen
  Root-Diff- und Code-Review. `GarminSyncService` und `GarminRemoteReader`
  besitzen Observer, Provider-Gate, den mit Morning-Body-Battery geteilten
  Module-Lock, Konfigurationsgrenzen, SDK-Login/MFA, Fenster und Collection,
  Wait-for-existing, Cancellation, Status-/Eventpersistenz, Payload-
  Vorbereitung, Fehlerzustand und deterministisches Cleanup. Der optionale
  SDK-Client wird durch `GarminClientFactory` erzeugt. Acht alte Server-
  Ablaufdefinitionen sowie `GARMIN_LOCK` sind entfernt, sämtliche Aufrufer
  und Patchziele zeigen auf konkrete Backend-Eigentümer; Remote-Schreib- und
  Autorisierungsgrenzen blieben unverändert.

### Prüfungen und Inventar

- Planned-Unit-Reconcile: 7 Modul-, 28 Workout-Repair- und 2 Architekturtests,
  PASS; Ruff, Format-Check, Compile und Diff-Check: PASS.
- Queue: 19 Store- und 2 konkrete Request-Connection-Tests nach der letzten
  Korrektur, PASS. Der vorherige Claim-Fix wurde zusätzlich mit 18 Store- und
  dem betroffenen Workout-Repair-Test geprüft.
- Competition-Reconcile: 7 Modul- und 2 Serverregressionen, PASS; Ruff,
  Format-Check, Compile, Diff- und Importgrenzen: PASS.
- Library: 12 Modultests, 55 relevante Integrationsregressionen und 2
  Architekturtests, PASS; Ruff/Format für neue Dateien, Compile und Diff-Check:
  PASS.
- Sync-State: 6 Modul- sowie 47 Provider-/Snapshot-/Aufruferregressionen,
  PASS; erzwungener Snapshot-/KV-Rollback und Connect-Spy enthalten.
- Vollständiger Stand `4640ed6c53dbd949a6f691a36bf3506c9ca80af3`:
  `python -m unittest discover -s tests` — 1.781 Tests, 12 übersprungen,
  **PASS** in 121,809 s. Ein vorheriger Lauf mit 1.781 Tests war wegen genau
  eines alten `server.provider_sync_cursor`-Patch-Ziels **FAIL**; der Lookup-Ort
  ist in `4640ed6` korrigiert und gezielt erneut geprüft.
- Vollständiger Zwischenstand `1d75e8f`: 1.804 Tests, 12 übersprungen,
  **PASS** in 119,639 s. Nach Library-Entry- und Planned-Reconcile-Integration
  wurde der konkrete Stand `a5d6b3153d47711f0ec87a0d85af29a0ebfdb90b`
  erneut vollständig geprüft: 1.829 Tests, 12 übersprungen, **PASS** in
  120,583 s. Die erwarteten synthetischen Fehlerlogs waren Test-Fixtures; die
  finale Unittest-Zusammenfassung ist erfolgreich.
- Nach Gate-, Remote-Library- und Planned-Calendar-Integration wurde der
  konkrete Stand `bd33e83017e2692ed67cd5c098bf97429d393697` vollständig geprüft:
  1.851 Tests, 12 übersprungen, **PASS** in 122,297 s. Zusätzlich bestanden
  32 Library-Modultests und 127 Library-Regressionen sowie 13
  Planned-Calendar-Modultests, 27 Repair- und 18 Kalender-/Push-Regressionen.
- Nach Snapshot-View-, Library-Refresh-, Freshness- und Repair-Integration
  wurde der konkrete Stand `1c455727428e3af987e5992dc3ec3a2601c08065`
  vollständig geprüft: 1.878 Tests, 12 übersprungen, **PASS** in 121,639 s.
  Vorher bestand der Library-Zwischenstand `295f1c3` mit 1.861 Tests, 12
  übersprungen, **PASS** in 121,542 s. Zusätzlich bestanden 41
  Library-Refresh-Modultests, 9 Freshness-Modultests sowie 54 kombinierte
  Calendar-Repair-/Integrationstests; Ruff, Format-Check, `py_compile`,
  Inventar- und Diff-Check sind **PASS**.
- Nach Daily-Marker-, Lock-, Selected-Batch- und innerer Performance-
  Integration wurde der konkrete Stand
  `15e9ca8296b917dcd6c6129f23d43bfe28f19eee` vollständig geprüft:
  `python -m unittest discover -s tests` — 1.903 Tests, 12 übersprungen,
  **PASS** in 122,453 s. Zusätzlich bestanden 10 Selected-Batch-, 9
  Performance-, 7 Daily-Marker-, 39 kombinierte Repair-/Architektur- sowie
  die gezielten Library-, Plan-Push-, Full-Resync- und Performance-
  Regressionen. Ruff/Format auf den neuen Modulen, `py_compile`, Inventar-
  und Diff-Check sind **PASS**.
- Intervals-Snapshot-Worker und Root-Wiederholung: 13 Tests, **PASS**;
  Garmin-Data-Prep-Worker und Root-Wiederholung: 7 Tests, **PASS**. Der neue
  Observer, Refresh-Historie und Maintenance-Gate bestanden 26 Tests; nach
  Serververdrahtung bestanden 45 fokussierte Beobachtungs-, Garmin-, Morning-
  Battery-, Diagnose- und Architekturtests. Ruff/Format für die neuen und
  unmittelbar geänderten Backendmodule, `py_compile` und `git diff --check`:
  **PASS**.
- Vollständiger integrierter Stand
  `ab2bbdd8413727e93aa4202df205258c6d4f3637`:
  `python -m unittest discover -s tests` — 1.931 Tests, 12 übersprungen,
  **PASS** in 123,816 s. Providerzugriffe verwendeten ausschließlich Fakes;
  Datenbanken und Fixtures waren temporär. Erwartete Fehlerlogs stammten aus
  Negativtests.
- Performance-Follow-up und Job-Outcomes: 78 kombinierte Architektur-,
  Audit-, Repair- und Serverregressionen, **PASS**; `tests.test_server` mit
  462 Tests, 3 übersprungen, **PASS**. Intervals-Reader: 6 Modultests sowie
  anschließend 75 fokussierte Tests, 1 übersprungen, **PASS**;
  `tests.test_server` erneut 462 Tests, 3 übersprungen, **PASS**.
- Intervals-Gesamtablauf auf
  `3b7dc89549414da7bee86ce7dd8ce07282744b07`: 7 neue isolierte
  Service-Tests, anschließend 102 Architektur-, Coach-, Repair- und
  Diagnoseregressionen, **PASS**; `tests.test_server` mit 462 Tests, 3
  übersprungen, **PASS** in 81,599 s. Das abschließende vollständige Gate
  `python -m unittest discover -s tests` bestand mit 1.985 Tests, 12
  übersprungen, in 223,245 s. Ruff/Format auf dem neuen Backend-/Testumfang,
  F821 auf allen geänderten Aufrufern, Compileall, Inventar- und Diff-Check:
  **PASS**. Provider und Datenbanken waren ausschließlich gemockt
  beziehungsweise temporär; die Fehlerlogs stammen aus erwarteten
  Negativtests.
- Sync-Worker-Runtime: 6 isolierte Lebenszyklus-, Claim-, Generation- und
  Startfehler-Tests, **PASS**; Ruff, Format, Compile und Diff-Check: **PASS**.
  Garmin-Payload-Korrektur: 29 Payload-, Provider-, Max-HR- und Historien-
  Regressionen, **PASS**. Garmin-Gesamtablauf: 8 isolierte Service-/Reader-
  Tests sowie 49 fokussierte Provider-, Morning-, Diagnose-, Payload- und
  Architekturtests, 1 übersprungen, **PASS**; `tests.test_server` mit 462
  Tests, 3 übersprungen, **PASS** in 83,470 s. Ruff/Format auf dem neuen
  Backend-/Testumfang, F821 auf den geänderten Aufrufern, Compileall und
  Diff-Check: **PASS**.
- Vollständiger integrierter Stand
  `7654aca75a7c721282a035aca2e7da809d1d5f79`:
  `python -m unittest discover -s tests` — 2.003 Tests, 12 übersprungen,
  **PASS** in 195,096 s. Providerzugriffe waren gemockt, Datenbanken und
  Fixtures temporär; sichtbare Fehlerlogs gehörten zu erwarteten
  Negativtests.
- Snapshot-Merge: 7 fokussierte Tests und anschließend 1.786 Gesamttests,
  12 übersprungen, **PASS**. Job-Normalisierung: 27 Modultests; Competition:
  45 Modul-, 74 Competition- und 31 Sync-Job-Regressionen; Library-Entry:
  26 Modul- plus fokussierte Serverregressionen; Planned-Reconcile: 11 Modul-,
  2 Remote-Import-, 1 Import-Orchestrierungs- und 27 Repair-Tests — jeweils
  **PASS**. Ruff/Format für die neuen Eigentümerdateien, Compile und Diff-Check:
  **PASS**.
- Aktualisiertes Inventar auf `15e9ca8`: `server.py` 9.794 physische Zeilen,
  867 Einträge, 464 Funktionen/Klassen. P6 enthält noch 126 fachliche
  Definitionen und 36 globale Bindungen. Die Verringerung ist nur Begleitmetrik; maßgeblich
  sind die oben belegten Eigentümerwechsel. P6 bleibt offen, bis insbesondere
  vollständige Garmin-/Intervals-/Library-/Planned-Unit-/Competition-Abläufe,
  Provider-Resync und Queue-Worker-Lifecycle aus `server.py` entfernt sind.
- Aktualisiertes Inventar auf `ab2bbdd`: `server.py` 9.489 physische Zeilen,
  849 Einträge und 450 Funktionen/Klassen. P6 enthält noch 118 fachliche
  Definitionen und 34 globale Bindungen. Maßgeblich sind die neuen konkreten
  Eigentümer und entfernten Serverdefinitionen, nicht die Zeilenabnahme.
- Aktualisiertes Inventar auf `3b7dc895`: `server.py` 9.039 physische Zeilen,
  817 Einträge und 420 Funktionen/Klassen. P6 enthält noch 88 fachliche
  Definitionen und 32 globale Bindungen. Der Fortschritt ergibt sich aus den
  geschlossenen Backend-Eigentümern und entfernten Ablaufdefinitionen, nicht
  aus der Zeilendifferenz.
- Aktualisiertes Inventar auf `7654aca`: `server.py` 8.909 physische Zeilen,
  807 Einträge und 416 Funktionen/Klassen. P6 enthält noch 84 fachliche
  Definitionen und 30 globale Bindungen. Maßgeblich sind der vollständige
  Garmin-Service, der geteilte Lock-Eigentümer und die entfernten
  Serverabläufe; die Zeilenabnahme ist nur Begleitmetrik.

### Verbleibende Risiken und nächster Schritt

- Garmin- und Intervals-Gesamtabläufe sowie der generische Worker-
  Lebenszyklus sind integriert. P6 bleibt offen, weil Full-Resync und der
  konkrete Queue-Executor-Dispatch noch in `server.py` liegen.
- Als nächste P6-Blöcke bleiben Full-Resync sowie die Kalender-/Wetter-
  Servicegrenzen, die einen Executor ohne fachliche Server-Callbacks
  ermöglichen. Jede Auslagerung muss gemeinsame Locks/Gates, Cancellation,
  Restart/Retry und Autorisierungsgrenzen bewahren und erhält vor der
  Serverintegration ein neues Root-Review.

## P3.1 — Athlet- und Aktivitätsgrundlagen (lokal integriert)

- Basis: lokaler, vollständig geprüfter P2-Gate-Commit
  `314fc9ef03e240b6c7aecf8f9693996df7f2d1a5`. Die Veröffentlichung bleibt von
  PR #692 abhängig; dessen Head `68a317235e94a1d9e5051c4aef0c555c2d882236`
  ist weiterhin offen und ausschließlich durch den fehlenden Codex-Review des
  aktuellen Heads blockiert. Ohne den vorgeschriebenen P1-Befund wurde kein
  zweiter Review-Aufruf erzeugt.
- Profilnormalisierung `5498d446`/`44e57446`, Aktivitätsidentität
  `91fe7197`/`14ed4a87`, Feedbacknormalisierung `a68fc3fc`/`24deeb41` und
  korrigierte Check-in-Normalisierung `82d0214a`/`e6570bf8`: **PASS**. Die
  Module sind rein, importieren `server.py` nicht und besitzen die Validierung;
  persistente Profil-Use-Cases bleiben wegen History- und Wetterabhängigkeit
  ausdrücklich noch offen.
- Aktivitätsfeedback-Service: erster Worker-Diff `37db5ad` **FAIL**, weil der
  Readback in derselben Transaktion wie das Upsert lag und damit die bisherige
  Commit-vor-Read-Grenze änderte. Korrektur `fb477ad`, integriert als
  `eca50762` und komponiert in `fece4ebd`: **PASS**. Write-Fehler rollen zurück;
  ein nachgelagerter Read-Fehler lässt den bereits bestätigten Write bestehen.
- Check-in-Service: erster Worker-Diff `a780b65` **FAIL** wegen unzureichend
  bewiesener Rollback-/Projektionsgrenzen und fremder Formatänderung. Korrektur
  `762fb8b`, integriert als `29e6a034` und komponiert in `a424c5a2`: **PASS**.
  Der erste vollständige Integrationslauf blieb **FAIL** mit fünf veralteten
  Test-Patchzielen; `6b89f788` migrierte sie auf den Service-Lookup. Danach:
  1.081 Tests, 12 übersprungen, PASS.
- Aktivitätsduplikate: Worker-Commit
  `00993b1b355ef01b8249b43cfef5d8d29913565e`, integriert als `ad71d599` und
  `76b86db7`: **PASS**. Erkennung und Projektion sind rein; Wahoo bleibt
  kanonisch. Der ausdrücklich autorisierte Remote-Delete verbleibt als
  separater Use Case und wird nicht vom Erkennungsmodul ausgelöst. Vollständiger
  Lauf: 1.093 Tests, 12 übersprungen, PASS.
- Garmin-Beobachtungsfreshness: Worker-Commit `6b800599` **FAIL**, weil ein
  ungültiges erstes Datumsfeld auf ein späteres Feld fiel und ein vorhandenes
  malformed `observed_at` anders projiziert wurde. Korrektur `162f490a`,
  integriert als `7569d2df`, `2bffb00c` und `b583e1f3`: **PASS**. Der
  Morning-Check-in übergibt nun den Garmin-Snapshot explizit; sein Test patcht
  den tatsächlichen Modul-Lookup.
- Aktivitäts-Leistungsvalidierung: Worker-Commit
  `47055957a59fb46456a13bc9ac42dce79da1fe64`, integriert als `115be615` und
  `d8845534`: **PASS**. Pace, Intensität, Messwertgrenzen, Quellenlabels,
  Beobachtungszeitpunkt, Tie-Break und Interpretationsgrenzen sind vollständig
  im reinen Eigentümermodul. Es gibt keine Server-Callbacks oder mutierten
  Eingaben.

### Prüfungen und Inventar

- Abschließender integrierter Lauf auf `d884553498b8585fa409367767c7e5e20ac8b51d`:
  `python -m unittest discover -s tests` — 1.106 Tests, 12 übersprungen, PASS
  in 177,877 s.
- Fokussierte Modul-, Architektur-, Server-, Coach-Tool-, Transaktions- und
  Patchzielregressionen wurden für jeden Teilschritt erneut ausgeführt. Ruff
  auf allen neuen Modulen und ihren Tests, `py_compile`/`compileall` für die
  geänderten Grenzen und `git diff --check`: PASS. Historische Ruff-Befunde in
  großen bestehenden Testdateien wurden nicht durch eine fachfremde
  Vollformatierung kaschiert.
- Inventar nach expliziter Stabilisierung der durch Zeilenverschiebung wieder
  unklar gewordenen Eigentümer: 1.469 Einträge, 1.027 verbleibende
  Funktionen/Klassen, P0 null Einträge. P3 enthält noch 159 Funktionen/Klassen
  und 23 globale Bindungen. `server.py` umfasst 18.428 physische Zeilen;
  `backend/` 62 Python-Dateien mit 8.966 physischen Zeilen.
- Die Ponytail-Vorgabe führte zu kleinen Eigentümermodulen und direkten
  qualifizierten Aufrufen; es wurden weder Service-Locator noch dauerhafte
  Kompatibilitätswrapper oder ein neues Sammelmodul eingeführt.

### Verbleibende Risiken und nächster Schritt

- P3 ist nicht abgeschlossen: Profilpersistenz hängt noch an der gemeinsamen
  Änderungshistorie und Wetterinvalidierung; Garmin-Metriken, Recovery/Trends,
  Aktivitätsdetailprojektion sowie Kalender- und Wetter-Use-Cases liegen noch
  teilweise in `server.py`.
- Der nächste lokale Schritt ist ein weiterer kleiner Performance-Baustein mit
  expliziten Snapshot-/Datumsparametern. Veröffentlichung und PR-Schnitt folgen
  erst nach bestätigtem Merge von PR #692 und Rebase auf `develop`.

## P3.2 — Performance-Zeitreihen und Aktivitätsgruppierung (lokal integriert)

- Basis: dokumentierter P3.1-Stand `811a63b6cbb0ed659e45f24a10eff1c7c4732dc2`.
- Load-/ATL-Berechnung: Worker-Commit `270b4fb`, integriert als `66938b7`
  und komponiert in `2a24653`: **PASS**. Rollups und die rekonstruierte
  7-Tage-ATL-Rekurrenz besitzen einen verpflichtenden Datumsanker; Decay,
  Rundung, Tageslücken und Summierung mehrerer Loads pro Tag sind unverändert.
- 30-Tage-eFTP: erster Worker-Commit `ac9dbd1` **FAIL**, weil nicht-dict
  Wellness-Zeilen neu still ignoriert wurden. Korrektur `513b9f3`, integriert
  als `4cefcd9`/`7810844` und komponiert in `e103e16`: **PASS**. Schlüssel- und
  Quellenpriorität, Sporterkennung, Leistungsgrenzen und inklusives
  30-Tage-Fenster entsprechen dem Ausgangsverhalten.
- Wellness-Projektionen: erster Worker-Commit `c7f06cec` **FAIL**, weil neue
  Guards die `id`-/`date`-Fallback-, Divisor- und Fehlersignatur verändert
  hatten. Korrektur `c9a61f05`, integriert als `1b44153`/`8c046c5` und
  komponiert in `68d4af4`: **PASS**. Mittelwerte, TSB/Form, rekursive
  Readiness-Auswahl sowie Vergleichsrichtung, Farbe und Label sind
  verhaltensgleich; Zeitfenster sind explizit verankert.
- Gruppierung paralleler Radausfahrten: Worker-Commit `13c9eae`, integriert als
  `8d89717` und komponiert in `4847460`: **PASS**. Halb-offene Zeitintervalle,
  untimed/Mitternacht-Fallback, Mindestdauer, transitive Gruppen und Sortierung
  sind erhalten. Der Eigentümer nutzt `backend.activities.identity` direkt.
- Der tatsächliche Gesamtdiff wurde nach jeder Korrektur erneut geprüft. Es
  bestehen keine Rückimporte auf `server.py`, keine fachlichen Server-Callbacks,
  keine neuen Sammelmodule oder dauerhaften Kompatibilitätswrapper. Die vier
  Bausteine sind rein und besitzen weder Locks noch Cache-, Worker- oder
  Stream-Zustand; Autorisierung, Remote-Schreibgrenzen, Transaktionen,
  Revisionen und Retry-/Cancellation-/SSE-Verhalten werden nicht berührt.

### Prüfungen und Inventar

- Abschließender integrierter Lauf auf `4847460`:
  `python -m unittest discover -s tests` — 1.132 Tests, 12 übersprungen,
  **PASS** in 178,382 s. Modul-, Architektur-, Performance-, Readiness-,
  Coach-Kontext-, eFTP- und Gruppierungsregressionen: **PASS**.
- Ruff für alle neuen Module und Tests, `py_compile`/`compileall`,
  Inventar-Check und `git diff --check`: **PASS**. Ein zwischenzeitlich
  verwendeter, im Repository nicht vorhandener Testmodulname war ein lokaler
  Auswahlfehler und wurde durch die tatsächlich vorhandenen Coach-Tests
  ersetzt; er ist kein Produktbefund.
- Inventar: 1.451 Einträge, 1.005 verbleibende Funktionen/Klassen, P0 null
  Einträge. P3 enthält noch 137 Funktionen/Klassen und 23 globale Bindungen.
  `server.py` umfasst 18.113 physische Zeilen; `backend/` 66 Python-Dateien mit
  9.422 physischen Zeilen.
- Die Ponytail-Vorgabe führte erneut zu kleinen direkten Eigentümermodulen mit
  qualifizierten Aufrufen und verpflichtenden Zeitankern; zusätzliche
  Abstraktionsschichten wurden nicht eingeführt.

### Verbleibende Risiken und nächster Schritt

- P3 bleibt offen: Profilpersistenz/History/Wetterinvalidierung,
  Aktivitätsdetailprojektion, Garmin-Metriken und Recovery-/Trend-Orchestrierung
  sowie Kalender- und Wetterzustand verbleiben teilweise in `server.py`.
- Veröffentlichung bleibt von PR #692 abhängig. Bis dessen aktueller Head den
  vorgeschriebenen Codex-Review erhält und tatsächlich auf `develop` gemergt
  ist, wird dieser lokale Folgestand nicht als veröffentlichter Phasenstand
  ausgewiesen.

## P3.3 — Garmin-Freshness, Projektionen, Gewicht, Recovery und Trends (lokal integriert)

- Basis: geprüfter P3.2-Stand `8ee219a`.
- Garmin-Max-HR: Worker-Commit `0ec3654`, integriert als `d602633` und
  komponiert in `0f22bc5`: **PASS**. Profil-, gespeicherte und
  Aktivitätswerte behalten Grenzen, Sportpriorität und Maximumsbildung.
- Garmin-Freshness: Worker-Commit `7d563086`, integriert als `c801e2b` und
  komponiert in `2039382`: **PASS**. Messalter, `observed_at`,
  Current-/Stale-/Missing-Projektion und Datumsgrenzen sind erhalten.
- Kompakte Garmin-Projektion: Worker-Commit `7c52492`, integriert als
  `7fc83c1` und komponiert in `9537d9d`: **PASS**. Feldallowlist,
  Tiefen-/Listenbegrenzung, jüngste Recovery-Auswahl und Rohdatenbegrenzung
  bleiben unverändert. Vollständiger Zwischenlauf: 1.150 Tests, 12
  übersprungen, PASS in 185,288 s.
- Garmin-Gewicht: Worker-Commit `e12ea52`, integriert als `34d9d2d` und
  komponiert in `04c8efd`: **PASS**. Rekursive Suche, Listenlimit,
  Datumsvererbung, Sekunden-/Millisekundenzeit, kg/lb/Gramm-Normalisierung,
  30–300-kg-Grenze, Ausschlussschlüssel, Deduplizierung, Metric-Shape und
  inklusiver Durchschnitt sind erhalten.
- Trendmittelwerte: Worker-Commit `faa4e726`, integriert als `bb00c64` und
  komponiert in `d921598`: **PASS**. Inklusive Fenster, Garmin-Historie,
  Intervals-Sportaliase, Threshold-/Zone-2-Pace, Readiness, Bounds und
  Rundung entsprechen den entfernten Serverfunktionen.
- Garmin-Recovery-Aggregation: Worker-Commit `0eee7e2`, integriert als
  `aad1cf2` und komponiert in `ac1a1c4`: **PASS**. Feldpriorität,
  DFS/LIFO-Reihenfolge, 2.000-/500-Grenzen, exakte Key-Normalisierung,
  letzter numerischer Wert, Transform-Semantik, neueste Auswahl und das
  inklusive Durchschnittsfenster sind erhalten.
- Root hat jeden tatsächlichen Worker-Diff mit den ursprünglichen
  Funktionskörpern verglichen. Alle Server-Aufrufer verwenden qualifizierte
  Modulaufrufe; es gibt keine Rückimporte, Server-Callbacks,
  Kompatibilitätswrapper oder neuen Sammelmodule. Die Bausteine besitzen keine
  Locks, Caches, Worker oder Streams. Autorisierung, Remote-Schreibgrenzen,
  Transaktionen, Revision-/Hash-Prüfungen, Retry, Cancellation, Restart und
  SSE werden nicht verändert.

### Prüfungen und Inventar

- Abschließender integrierter Lauf auf `ac1a1c485b6240b4bbb69804c8c54e89c8f38dad`:
  `python -m unittest discover -s tests` — 1.169 Tests, 12 übersprungen,
  **PASS** in 178,815 s.
- Trends: 8 Modul-/Architekturtests und 1 Server-Trendtest, **PASS**.
  Recovery: 8 Modul-/Architekturtests, 10 Server-Recoverytests und 1
  Daily-Health-Test, **PASS**. Ruff für sämtliche neuen Module und deren Tests,
  `py_compile`, Inventar-Check und `git diff --check`: **PASS**. Der
  Gesamt-Rufflauf von `server.py` bleibt wegen vorbestehender, außerhalb dieses
  Diffs liegender Befunde rot; es wurde keine fachfremde Großformatierung
  vorgenommen. Ein versuchter Aufruf von
  `tests.test_server_extraction_inventory` war ein lokaler Auswahlfehler, weil
  dieses Testmodul nicht existiert; der tatsächliche Generator-Check und der
  Architekturtest sind grün.
- Inventar nach symbolbasierter Stabilisierung von zehn durch
  Zeilenverschiebung unklar gewordenen Eigentümern: 1.436 Einträge, 986
  verbleibende Funktionen/Klassen, P0 null Einträge. P3 enthält noch 134
  Funktionen/Klassen und 24 globale Bindungen. `server.py` umfasst 17.827
  physische Zeilen; `backend/` 72 Python-Dateien mit 10.096 physischen Zeilen.
- Die Ponytail-Vorgabe hielt die neuen Eigentümermodule klein und direkt;
  zusätzliche Service-Locator oder Abstraktionsschichten wurden nicht
  eingeführt.

### Verbleibende Risiken und nächster Schritt

- P3 bleibt offen: Garmin-Metriknormalisierung, Daily-Health- und
  Performance-/Recovery-Kontextorchestrierung, Profilpersistenz,
  Aktivitätsdetailprojektion sowie Kalender- und Wetterzustand liegen noch
  teilweise in `server.py`.
- Die Veröffentlichung bleibt durch PR #692 blockiert. Dessen aktueller Head
  hat grüne technische Checks, aber noch keinen erfolgreichen vorgeschriebenen
  Codex-Review; die Projektregel erlaubt ohne P1 im letzten abgeschlossenen
  Review keinen weiteren Review-Ping. Der lokale P3-Stand wird deshalb noch
  nicht veröffentlicht oder als Phasenabschluss ausgewiesen.

## P3.4 — Daily Health, aktuelle Leistungswerte und Garmin-Metriken (lokal integriert)

- Basis: geprüfter P3.3-Stand `ac1a1c4`.
- Daily Health: Worker-Commit `1812da8`, integriert als `9207d20` und zunächst
  komponiert in `91567bf`: tatsächliches Diff-Review **PASS** für Feldaliase,
  Tagesaggregation, inklusives Datumsfenster, Einheiten, Rundung und
  Freshness. Das spätere Integrationsreview fand jedoch einen verbliebenen
  Aufruf des entfernten privaten Helpers in `daily_planning_context`:
  Composition zunächst **FAIL**. `c716c67` macht
  `garmin_daily_health_by_date` zur expliziten öffentlichen Fachschnittstelle
  und migriert den Aufrufer; erneutes Review und Regressionen: **PASS**.
- Aktuelle Leistungswerte: Worker-Commit `9caad30`, integriert als `0d38866`
  und komponiert in `6265025`: **PASS**. Intervals-Sportzuordnung, eFTP/FTP-
  Trennung, Max-HR-Priorität, Profil-Fallbacks, Threshold-Pace, Körperwerte,
  Garmin-Priorität und Laufprognosen entsprechen den entfernten
  Funktionskörpern. Profil und Garmin-Metriken werden explizit übergeben; das
  Modul besitzt keinen Laufzeit- oder Persistenzzustand.
- Garmin-Metriknormalisierung: Worker-Commit `41699a9`, integriert als
  `c2476d7` und komponiert in `c716c67`: **PASS**. Dauer-, VO2max-,
  Laufprognose-, Schwellen-, Max-HR-, Gewichts-, Messdatum- und
  Freshness-Semantik ist vollständig verlagert. Alle Produktionsaufrufer
  übergeben `current_date` explizit; Serverkonstanten, Implementierungen und
  Test-Patch-Ziele wurden entfernt beziehungsweise auf das Eigentümermodul
  migriert. Es gibt keine Rückimporte, Servercallbacks oder
  Kompatibilitätswrapper.
- Root hat die tatsächlichen Worker-Diffs gegen die entfernten Serverkörper
  geprüft. Autorisierung, Datenschutz, Remote-Schreibgrenzen, Transaktionen,
  Revision-/Hash-Prüfungen, Rollback, Retry, Cancellation, Restart und SSE
  werden von diesem reinen Berechnungsumfang nicht verändert.

### Prüfungen und Inventar

- Fokussiert nach der Composition-Korrektur: 22 Daily-Health-/Garmin-/Current-
  Metrics-/Architekturtests, 36 Garmin-Serverregressionen, 2 Provider- und 6
  Diagnosefälle: **PASS**. Ruff für die Eigentümermodule und ihre Tests,
  `py_compile` und `git diff --check`: **PASS**.
- Vollständiger integrierter Lauf auf `c716c674dd36e13d8a5ca6843960b549bcf79096`:
  `python -m unittest discover -s tests` — 1.189 Tests, 12 übersprungen,
  **PASS** in 173,603 s. Die ausgegebenen Provider-/Coachfehler stammen aus
  erwarteten Negativtests.
- Nach stabiler symbolischer Nachklassifizierung der durch Zeilenverschiebung
  betroffenen Funktionen: 1.389 Inventareinträge, 940 verbleibende
  Funktionen/Klassen, P0 null Einträge. P3 enthält noch 119
  Funktionen/Klassen und 24 globale Bindungen. `server.py` umfasst 17.202
  physische Zeilen; `backend/` 75 Python-Dateien mit 12.727 physischen Zeilen.
- Die Ponytail-Vorgabe führte zu direkten Fachmodulen und expliziten
  Parametern; zusätzliche Registry-, Locator- oder Sammelschichten wurden
  nicht eingeführt.

### Verbleibende Risiken und nächster Schritt

- P3 bleibt offen: History-Schreibung und Recovery-/Performance-
  Kontextorchestrierung, Profilpersistenz, Aktivitätsdetailprojektion sowie
  Kalender- und Wetterzustand liegen noch teilweise in `server.py`.
- Veröffentlichung bleibt von PR #692 und dessen vorgeschriebenem aktuellen
  Codex-Gate abhängig. Bis zum bestätigten Merge auf `develop` bleibt dieser
  P3-Stand lokal gestapelt.

## P3.5 — Kontext, Aktivitätsdetails, Wetter und Profilpersistenz (lokal integriert)

- Basis: geprüfter P3.4-Stand `c716c67`; aktueller dokumentierter Stand
  `14e3a8e` auf `refactor/server-extraction-p3-domain-foundations`.
- Current-Performance-Kontext: Worker-Commit `d51700d2`, integriert als
  `4b65872`, Composition `cbabe33`: **PASS**. Snapshot, Garmin-Snapshot,
  Profil und lokales Datum sind explizite Eingaben; keine Servercallbacks oder
  Rückimporte. 10 Differentialfälle sowie 18 Server- und 15 Providerfälle
  (1 übersprungen) bestanden.
- Aktivitätskalender und Detailprojektion: Worker-/Integrationsstände
  `d97aeba`/`1ad99c4` sowie `f148e38`/`d07fa17`: **PASS**. Identität,
  Allowlists, Downsampling, Lap-Grenzen und Kalenderpayloads liegen vollständig
  in `backend/activities/`; alte Serverdefinitionen und Patchziele wurden
  entfernt.
- Wetterprojektion, Empfehlungen, adaptive Entscheidung und Forecast-Merge:
  Worker-Commits `5e75d363`, `c880819`, `1d627cbb` und `a0cabe0`, integriert
  beziehungsweise komponiert bis `5894ae0`: jeweils **PASS** nach tatsächlichem
  Diff- und Code-Review. Zusätzlich bestanden 8 Forecast-Projektionsfälle, 45
  Recommendation-Differentialfälle, 4.050 Adaptive-Differentialfälle und 20
  Merge-/Parameter-/Completeness-Differentialfälle. Datum wird explizit
  übergeben; es gibt keine I/O-, Lock- oder Serverabhängigkeit in den reinen
  Modulen.
- Change-History-Writer: Extraktion `46be665`, Composition `209b28f`:
  **PASS**. Projektion, Hash, Diff, Retention, Kapazitätsgrenze, persistenter
  Record und datenschutzbegrenzte öffentliche Sicht besitzen
  `backend/change_history.py`. Sämtliche bisherigen Writer-Aufrufer verwenden
  das Modul direkt; Undo- und jeweilige Domänentransaktionen bleiben erhalten.
- Profilpersistenz: Eigentümercommit `828e3f7`, Composition `09ff68f`:
  **PASS**. `ProfileService` besitzt Laden, Validierung, Normalisierung,
  Transaktion, History-Schreibung und atomare standortabhängige
  Wettercache-Invalidierung. `server.py` enthält weder `get_profile` noch
  `save_profile` oder eine Invalidierungsimplementierung; Produktions- und
  Testaufrufer nutzen den konkreten Service.
- Root-Review bestätigte für alle Umfänge: keine Remote-Schreibänderung, keine
  neuen Kompatibilitätswrapper, keine Rückimporte, unveränderte
  Autorisierungs-/Datenschutzgrenzen und eindeutige Eigentümer für den jeweils
  verschobenen Zustand.

### Prüfungen und Inventar

- Vor der letzten Profilintegration: vollständiger Lauf mit 1.238 Tests, 12
  übersprungen, **PASS** in 236,923 s. Auf dem kombinierten Stand nach
  Profilintegration: `python -m unittest discover -s tests` — 1.260 Tests,
  12 übersprungen, **PASS** in 177,805 s.
- Profil-Composition: 6 Modul-/Architekturtests, 9 Profil-, 14 Wetter- sowie
  112 Dialog-/Tool-/Audit-Regressionen (1 übersprungen), **PASS**. History:
  7 Modul-/Architektur-, 21 History- und 4 Undo-Regressionen, **PASS**.
  Ruff auf allen neuen Eigentümermodulen und Tests, `py_compile`, Inventar-
  Check und `git diff --check`: **PASS**.
- Regeneriertes Inventar auf `14e3a8e`: 1.320 Einträge, 886 verbleibende
  Funktionen/Klassen, P0 null Einträge. P3 enthält noch 76
  Funktionen/Klassen und 13 globale Bindungen. `server.py` umfasst 16.125
  physische Zeilen. Die Abnahme folgt den Eigentums- und Verhaltensverträgen,
  nicht der reinen Zeilenabnahme.

### Verbleibende Risiken und nächster Schritt

- P3 bleibt offen: Performance-Refresh/Morning-Body-Battery und
  Planning-Recovery, Activity-Matching/Listen-/Lösch-Use-Cases, kanonische und
  öffentliche Kalenderorchestrierung sowie Wetter-I/O, Cache-/Retry-Zustand
  und Lock-Eigentum liegen noch in `server.py`.
- PR #692 ist weiterhin `OPEN`, `MERGEABLE`, aber `BLOCKED`; `mergedAt` und
  Merge-Commit fehlen. Alle technischen Checks außer `Codex code review` sind
  grün, Reviews und Review-Threads sind leer. Ohne P1 im letzten
  abgeschlossenen Review erlaubt die Projektregel keinen zweiten Review-Ping;
  daher erfolgt weder ein Umgehungsversuch noch eine Mergebehauptung.
- Nächster integrierbarer Schnitt sind die bereits separat delegierten reinen
  Activity-Matching- und kanonischen Kalenderprojektionen; danach folgen die
  zustandsbehafteten Wetter- und Performance-Use-Cases unter Root-Architektur.

## P3.6 — Aktivitätsabgleich, Kalender-Read-Models und Planungskontext (lokal integriert)

- Basis: dokumentierter P3.5-Stand `14e3a8e`; geprüfter kombinierter Stand
  `6fb68cc` auf `refactor/server-extraction-p3-domain-foundations`.
- API-Deduplizierung `b3e6834`: **PASS**. Der konkrete Eigentümer ist
  `backend/activities/duplicates.py`; 15 fokussierte Fälle sowie Ruff,
  Compile- und Diff-Prüfung bestanden.
- Activity-Matching: Worker-Commit `6138ed7`, integriert als `d793ae1`,
  Composition `4914a32`: erster Integrationsreview **FAIL**, weil zwei
  Listenaufrufer den entfernten Namen `_record_date` weiterhin verwendeten.
  Root-Korrektur `6fb68cc`: **PASS**. Beide Aufrufer verwenden den konkreten
  Backend-Eigentümer; die Pagination-Regression prüft zusätzlich die
  Datumsgrenze. 37 Matching-, Coach-Tool-, Architektur- und Paginationfälle
  bestanden.
- Kanonischer Kalender: Worker-Commit `7b77a6d`, integriert als `87e241a`,
  Composition `d75bea6`: **PASS**. Projektion und Sortierung sind rein,
  erhalten lokale/remote Identität und besitzen weder Servercallbacks noch
  I/O. 13 fokussierte Fälle bestanden.
- Täglicher Planungskontext `f10d4cb`, Composition `d673d41`: **PASS**.
  Datenabruf bleibt in der Composition; Feldprojektion, Datumsfenster und
  Sortierung besitzen `backend/planning/context.py`. Sieben Modulfälle und 19
  Auditfälle (einer übersprungen) bestanden.
- Aktivitätskalender/Compliance `469eab0`, Composition `afda583`: **PASS**.
  Matching-Orchestrierung, Compliance-Basis und Wochenaggregation liegen
  vollständig im Backend; 24 fokussierte Fälle bestanden.
- Planning-Recovery: Worker-Commit `cd914fd`, integriert als `2d9747c`,
  Composition `77a5c90`: **PASS**. Intervals-/Garmin-Priorität,
  Quellenlabels, gespeicherte Body-Battery-Historie und der aktuelle
  Morgenwert werden aus expliziten Eingaben gebaut; 22 fokussierte Fälle
  bestanden.
- Lokaler Kalender: Worker-Commit `8a1e53d`, integriert als `c4595d1`,
  Composition `edfad8d`: **PASS**. Geplante Einheiten, Wettkämpfe und externe
  Termine werden aus expliziten Listen projiziert; 17 fokussierte Fälle
  bestanden. Keine der neuen Backendgrenzen importiert oder erreicht
  `server.py`; dauerhafte Kompatibilitätswrapper wurden nicht eingeführt.

### Prüfungen und Inventar

- Erster vollständiger Lauf auf `edfad8d`: **FAIL**, 1.290 Tests, zwei
  zusammengehörige Fehler im Coach-Read-Pfad `list_recent_activities`.
  Ursache war ein nach der Matching-Composition verbliebener Aufruf des
  entfernten `_record_date` ohne Receipt. Nach `6fb68cc` erneuter vollständiger
  Lauf: 1.290 Tests, 12 übersprungen, **PASS** in 170,552 s.
- `python scripts/server_extraction_inventory.py --check`, `py_compile` für
  Server, Generator und betroffene Tests sowie `git diff --check`: **PASS**.
- Regeneriertes Inventar: 1.273 Einträge, 838 verbleibende
  Funktionen/Klassen, P0 null Einträge. P3 enthält noch 54
  Funktionen/Klassen und 12 globale Bindungen. `server.py` umfasst 15.484
  physische Zeilen. Die Freigabe beruht auf Eigentum und Regressionen, nicht
  auf der Zeilenabnahme.

### Verbleibende Risiken und nächster Schritt

- P3 bleibt offen: Performance-Refresh/Morning-Body-Battery,
  Activity-Listen-/Detail-/Remote-Lösch-Use-Cases, öffentliche und externe
  Kalenderorchestrierung, Wetter-I/O samt Cache/Retry/Lock sowie Teile der
  Athletenpersistenz liegen noch in `server.py`.
- PR #692 bleibt ein externer Veröffentlichungsvorläufer; ohne bestätigtes
  `mergedAt`, Merge-Commit und Erreichbarkeit auf `develop` wird dieser lokal
  gestapelte Stand nicht als veröffentlicht oder gemergt gemeldet.

## P3.7 — Activity-Use-Cases, Wetter- und Kalenderzustand (lokal integriert)

- Basis: geprüfter P3.6-Stand `6fb68cc`; geprüfter integrierter Stand
  `9ddc14e` auf `refactor/server-extraction-p3-domain-foundations`.
- Activity-Use-Cases: Weather-Cache-Worker `a7fa055`, Composition `b20f037`:
  **PASS**. Duplicate-Service `ba1963e`: **FAIL**, weil numerische IDs,
  fehlerhafte Listen und fehlende Zeitstempel vom bisherigen Vertrag
  abwichen. Korrektur `8e404a6`, Integration `887e6b0`/`a8c644d` und
  vollständiger Service-Stand `0be6b92`: **PASS**. Identität,
  Duplikaterkennung, Details und Wettercache-Invalidierung besitzen konkrete
  Backend-Eigentümer; es verbleibt kein fachlicher Server-Callback.
- Öffentlicher Kalender: Worker `9c1d3b4`, Integration `8d005ec`, Composition
  in `6faa94f`: **PASS**. Intervals-State: Worker `a48b8ab`, Integration
  `5fbc657`, Composition `6faa94f`: **PASS**. Projektionen und Persistenzgrenzen
  erhalten Datumsfenster, Sortierung und Quellenfelder.
- Wetterhistorie: Worker `3327835`: **FAIL**, weil die Korrektur das bisherige
  ID-/Datums-/Namens-Matching erweiterte. Worker-Korrektur `eaa102e`, integriert
  als `e8a0f76`, Composition `a2948b0`: **PASS**. Sieben Modulfälle und der
  tatsächliche Body-Battery-Aufrufer bestanden.
- Provider-Refresh-Tracker: Worker `cdd6e63`, integriert als `f690204`,
  Composition `57b2405`: **PASS**. Unit-of-work, Retry, Cleanup und Events
  besitzen `backend/sync/refresh.py`; Fehlercodes werden rein klassifiziert.
- Wetter-Service `486ac75`: **PASS**. Maintenance-Gate, Refresh-Lock,
  Profil-/KV-Lesen, Negativcache, Client-Aufruf und transaktionale
  History-/Cache-/Fehlerpersistenz liegen vollständig im Service. Events
  werden erst nach erfolgreichem Commit publiziert. 23 fokussierte Wetter-,
  Maintenance- und Architekturfälle, 28 Workout-Repair-Fälle sowie alle 463
  Fälle aus `tests.test_server` (drei übersprungen) bestanden.
- Externer Kalender: Worker `0d20f5b`, integriert als `6995b6b`, Reader- und
  Composition-Stand `9ddc14e`: **PASS**. Query, Endgrenze, Relevanzfilter,
  Sortierung, Limit und KV-State liegen ohne Rückimport auf `server.py` im
  Kalenderpaket; der Reader besitzt die Lese-Transaktion. 44 fokussierte
  Kalender-, Repair- und Architekturfälle bestanden.

### Prüfungen und Inventar

- Vollständiger Lauf auf `0be6b92`: 1.336 Tests, 12 übersprungen, **PASS** in
  177,356 s. Erneuter vollständiger Lauf auf `9ddc14e`: 1.373 Tests, 12
  übersprungen, **PASS** in 169,853 s. Alle Providerzugriffe waren Fakes oder
  temporäre Fixtures.
- `python scripts/server_extraction_inventory.py --check`, `py_compile` für den
  Generator und `git diff --check`: **PASS**. Nach expliziter Zuordnung der
  durch Zeilenverschiebungen aus heuristischen Bereichen gefallenen Symbole
  enthält P0 erneut null Einträge.
- Regeneriertes Inventar: 1.231 Einträge, 800 verbleibende
  Funktionen/Klassen, P3 mit acht Funktionen/Klassen und einer globalen
  Bindung. Composition-Root-Fabriken, Planning-Kalender und
  Calendar-Reconciliation sind nun explizit P11, P4 beziehungsweise P6
  zugeordnet, statt durch Namensheuristiken P3 zu verzerren. `server.py`
  umfasst 14.932 physische Zeilen. Die Freigabe beruht auf vollständiger
  Eigentümerschaft und Regressionen, nicht auf der Zeilenabnahme.

### Verbleibende Risiken und nächster Schritt

- Aktivitätsidentität/-details sowie Kalender-/Wetter-Read- und Cache-Grenzen
  erfüllen P3. Die verbleibende P3-Arbeit ist die zustandsbehaftete Garmin-
  Morning-Body-Battery- und Performance-/Recovery-Kontextorchestrierung.
  Externe Kalender-Schreibsynchronisation bleibt planmäßig P6.
- PR #692 bleibt extern blockiert. Ohne `mergedAt`, Merge-Commit und dessen
  Erreichbarkeit auf `develop` wird kein Merge gemeldet; ohne P1 im letzten
  berechtigten Review wird kein weiterer `@codex`-Ping gesendet.

## P3.8 — Athletenkontext und Morning-Recovery (lokal integriert)

- Basis: geprüfter P3.7-Stand `9ddc14e`; letzter geprüfter Code-Stand
  `17cae87` auf `refactor/server-extraction-p3-domain-foundations`.
- Athletenkontext: Worker `d65a4c7`, integriert als `db72d1e`: **PASS**.
  Profil, Wettkampf-Upserts, Tombstones, Löschungen und Änderungshistorie
  laufen in einer vom `DatabaseManager` besessenen Unit-of-Work. Revisionen,
  Providerverknüpfungen und Rollback-Verhalten bleiben erhalten; es gibt
  weder einen Rückimport noch einen fachlichen Server-Callback.
- Morning-Body-Battery: Worker-Erststand `2a4f3c9`: **FAIL**, weil das bisherige
  Exception-Logging den Traceback verlor. Korrektur `b8522c0`, integriert als
  `1edfa41`/`18fd746`: **PASS**. Das anschließende Root-Review korrigierte
  zusätzlich Merge-Reihenfolge, UTC-/Lokalzeit-Trennung, Commit-Failure-
  Regression und die zunächst beim Singleton-Bau eingefrorene
  `OPERATION_CONTEXT`. Der finale Service besitzt Lock, Maintenance-/Provider-
  Gates, Cooldown, Retry-Zähler, Snapshot/History/Error-Persistenz und
  Eventreihenfolge. Die Fehlerbereinigung liest und schreibt atomar in einer
  Unit-of-Work; Remote-I/O liegt in `backend/providers/garmin_morning.py`.
- Wettkampfnormalisierung wurde im Root als vorgezogene P4-Grenze nach
  `backend/planning/competitions.py` verschoben: **PASS**. Alle Produktions-
  aufrufer verwenden das Eigentümermodul; die entfernten Server-Symbole sind
  per Architekturtest verboten.

### Prüfungen und Inventar

- Root-Wiederholung nach der letzten Transaktionskorrektur: 44 fokussierte
  Athlete-, Morning-Recovery-, Provider-, Competition-, Diagnostic- und
  Architekturtests: **PASS**. Ruff-Lint, Formatprüfung der acht neuen bzw.
  fachlich geänderten Module/Modultests, `py_compile`, Inventar-Check und
  `git diff --check`: **PASS**. Der historische Inventargenerator bleibt
  außerhalb dieses Umfangs nicht Ruff-formatiert; sein Lint und Bytecode-
  Check sind grün.
- Vollständiger Lauf auf dem exakten Code-Stand `17cae87`:
  `python -m unittest discover -s tests` — 1.393 Tests, 12 übersprungen,
  **PASS** in 171,436 s. Es wurden ausschließlich temporäre Daten und
  Provider-Fakes verwendet.
- Regeneriertes Inventar: 1.218 Einträge, 782 verbleibende
  Funktionen/Klassen, 216 globale Bindungen und 220 Imports. P0 und P3
  enthalten jeweils null offene Einträge. `first_present` und `as_number`
  bleiben als konkrete P4-Planungsabhängigkeiten offen;
  `ATHLETE_RECORD_HANDLERS` ist P7-Tool-Dispatch. `server.py` umfasst 14.667
  physische Zeilen. Entscheidend ist die vollständige Eigentümerschaft, nicht
  die Zeilenreduktion.

### Verbleibende Risiken und nächster Schritt

- P3 ist nach tatsächlichem Diff-, Aufrufer-, Zustands- und Regressionstest-
  Review **PASS**. P4 bleibt offen; Wettkampf-Sync, Workout-/Library-/Plan-
  Orchestrierung, Revisionen und Rollback müssen weiter migriert werden.
- PR #692 bleibt der externe Veröffentlichungsvorläufer. Ohne bestätigtes
  `mergedAt`, Merge-Commit und Erreichbarkeit auf `develop` wird der lokal
  gestapelte Stand nicht veröffentlicht oder als gemergt gemeldet.

## P4.1 — Saisonprojektion und Workout-Validierung (lokal integriert)

- Basis: P3-Abschluss `9e68ec9`; letzter geprüfter integrierter Code-Stand
  `1db8879` auf `refactor/server-extraction-p3-domain-foundations`.
- Saisonprojektion: Luna-Worker `84f342d`, integriert als `dd9bf59`,
  Composition `4945234`: **PASS**. `season_plan_summary` und
  `planning_state` sind reine Funktionen mit expliziten Wettbewerben, Datum,
  Replan-Vorschau und Adaptive-Status. Phasengrenzen, Sortierung und
  `next_event` entsprechen dem bisherigen Vertrag; es gibt keinen Server-
  Rückimport und keinen Kompatibilitätswrapper.
- Workout-Validierung: Luna-Worker `eb5ba92`, integriert als `da3e27e`,
  Composition `1db8879`: **PASS**. Sportnormalisierung, Step-/Dauerprüfung,
  kanonischer Workout-Text, Provider-Event-Payload und Remote-Readback liegen
  vollständig in `backend/planning/workouts.py`. Das aktuelle lokale Datum
  wird nur an der Composition-Grenze injiziert. Alle Produktions- und
  Testaufrufer verwenden das Eigentümermodul; die entfernten Server-Symbole
  sind per Architekturtest verboten.

### Prüfungen und Inventar

- Root-Wiederholung der Worker-Suites: fünf Season- und zehn Workout-
  Modultests: **PASS**; tatsächliches Diff-, Schnittstellen-, Import- und
  Verhaltensreview beider Worker-Commits: **PASS**.
- Integrierter Stand: 89 fokussierte Planning-/Workout-/Coach-/Architektur-
  Tests: **PASS**; `tests.test_server`: 463 Tests, drei übersprungen,
  **PASS** in 75,529 s. Vollständiger Lauf auf `1db8879`: 1.408 Tests,
  12 übersprungen, **PASS** in 254,456 s. Alle Provider waren Fakes; alle
  Daten temporär.
- Ruff-Lint/Format für die neuen Eigentümermodule und Modultests,
  `py_compile`, Inventar-Check und `git diff --check`: **PASS**.
  Regeneriertes Inventar: P0 und P3 null; P4 noch 248 Definitionen und
  20 globale Bindungen. `server.py` umfasst 14.494 physische Zeilen.

### Verbleibende Risiken und nächster Schritt

- P4 bleibt offen. Library/Templates, geplante Units, Wettkampf-Use-Cases,
  Kalender/Compliance, strukturierte Änderungen und Adaptive Apply besitzen
  noch Server-Orchestrierung. Zwei getrennte Folgepakete für reine
  Wettkampf- und Kontextprojektionen laufen in unabhängigen Worktrees.
- Live-Prüfung von PR #692: weiterhin `OPEN`, `MERGEABLE`, aber `BLOCKED`;
  `mergedAt` und Merge-Commit sind null. Der einzige fehlschlagende Gate-
  Check bleibt `Codex code review`; es liegt weiterhin kein Review/P1 vor,
  daher wurde kein unzulässiger zweiter Review-Ping gesendet.

## P4.2 — Kontext- und Wettkampfprojektionen (lokal integriert)

- Kontextprojektionen: Luna-Erststand `8f85bd1`, Review **FAIL**, weil ein
  dauerhafter Alias `_selected = selected` die alte private Schnittstelle
  erhalten hätte. Korrektur desselben Workers `0c6e27b`, integriert als
  `ec8be33` und `dd7737c`, erneutes tatsächliches Diff- und Code-Review
  **PASS**. Root-Composition `dc75d2b` verlagert Snapshot-, Sport- und lokale
  Kalenderprojektionen vollständig nach `backend/planning/context.py` und
  injiziert Zeit sowie Vollsync-Zustand explizit. Ein zunächst übersehener
  Callback-Verweis `select=selected` ließ `tests.test_server` mit zwölf
  `NameError` fehlschlagen; nach Migration aller Aufrufer liefen 463 Tests,
  drei übersprungen, **PASS** in 77,255 s.
- Wettkampfprojektionen: Luna-Commit
  `62bce4de8b5a6f2db8967300419a2c968e289801`, integriert als `b16a21b`,
  tatsächliches Diff-, Schnittstellen-, Import- und Verhaltensreview
  **PASS**. Root-Composition `b75c341` entfernt Sport-, Payload-, Remote-,
  Konflikt- und Sync-Key-Projektionen aus `server.py`; der Konfliktzeitpunkt
  wird explizit injiziert. Es gibt keinen Server-Rückimport, keinen
  Zustandszugriff und keinen Kompatibilitätswrapper.

### Prüfungen und Inventar

- 13 Modul-/Architekturtests und zehn fokussierte Wettkampf-/Sync-Tests:
  **PASS**. `tests.test_server`: 463 Tests, drei übersprungen, **PASS** in
  85,526 s.
- Der erste vollständige Lauf fand drei veraltete direkte Patch-/Aufrufziele
  in `tests/test_audit_remediation.py` und war deshalb **FAIL**. Nach
  Migration auf das Eigentümermodul: die drei Regressionen **PASS** in
  0,902 s; vollständiger Lauf: 1.424 Tests, 12 übersprungen, **PASS** in
  179,476 s. Alle Provider waren Fakes; alle Daten temporär.
- Inventar-Check: **PASS**. P0 und P3 sind null; P4 enthält noch 231
  Definitionen und 18 globale Bindungen. `server.py` umfasst 14.310
  physische Zeilen.

### Verbleibende Risiken und nächster Schritt

- P4 bleibt offen. Stateful Wettkampf-CRUD/-Sync, Library/Templates,
  geplante Units, Adaptive/Illness und strukturierte Änderungen besitzen
  weiterhin Server-Orchestrierung. Kalenderkonflikt- und Library-Projektionen
  werden als nächste unabhängige, bereits abgegrenzte Pakete geprüft und
  sequenziell integriert.
- PR #692 bleibt extern `OPEN`/`BLOCKED`; ohne P1 gibt es keinen zweiten
  Review-Ping und ohne bestätigtes `mergedAt` keinen Mergebericht.

## P4.3 — Kalenderkonflikt- und Library-Projektionen (lokal integriert)

- Kalenderkonflikte: Luna-Commit
  `915a0e76587e00d7c80955cb72a74d78c51c32d6`, integriert als `d0be3d3`;
  tatsächliches Diff-, Code-, Import- und Verhaltensreview **PASS**.
  `backend/planning/calendar.py` besitzt Datums-/Zeitfenster-, Dauer- und
  Konfliktprojektion. Root-Composition `52a8734` lässt DB, lokale Library und
  externen Kalender als eindeutige Server-Abhängigkeiten und entfernt alle
  fachlichen Kalender-Callbacks aus `server.py`.
- Library-Projektionen: Luna-Commit
  `5f0c34d7dadf75b39f4ca4e65421f88b234721e8`, integriert als `8ebca25`;
  tatsächliches Diff-, Code-, Import- und Verhaltensreview **PASS**. Die
  zusätzliche Regression verhindert, dass eine großgeschriebene lokale UUID
  als externe ID gespeichert wird. Root-Composition `e396c76` migriert
  Identität, Whitelist, Normalisierung, Dauer und konservatives Matching nach
  `backend/planning/library.py`; die Kandidatenliste ist eine verpflichtende
  explizite Abhängigkeit. Es gibt keine Server-Rückimporte, Zustandszugriffe,
  Callbacks oder Kompatibilitätswrapper.

### Prüfungen und Inventar

- Kalender: zehn Modultests plus Architekturtests und vier integrierte
  DB-/Kalenderregressionen: **PASS**. Library: zehn Modultests plus
  Architektur- und Workout-Repair-Suite, insgesamt 40 Tests: **PASS**.
- `tests.test_server`: 463 Tests, drei übersprungen, **PASS** in 78,003 s.
  Vollständiger Lauf: 1.444 Tests, 12 übersprungen, **PASS** in 174,780 s.
  Alle Provider waren Fakes; alle Daten temporär. `py_compile` und
  `git diff --check`: **PASS**.
- Regeneriertes Inventar: P0 und P3 null; P4 enthält noch 215 Definitionen
  und 17 globale Bindungen. `server.py` umfasst 14.068 physische Zeilen.

### Verbleibende Risiken und nächster Schritt

- P4 bleibt offen. Zwei weitere reine Pakete für Planned-Unit- und
  Adaptive-/Illness-Projektionen laufen in separaten Worktrees. Stateful
  Persistenz, Revision/Hash-Transaktionen, Wettkampf- und Library-Sync sowie
  strukturierte Apply-Orchestrierung verbleiben danach als Service-Arbeit.
- PR #692 bleibt der externe Veröffentlichungsvorläufer; ohne bestätigten
  Merge auf `develop` wird dieser gestapelte lokale Stand nicht publiziert.

## P4.4 — Planned-Unit- und Adaptive-Projektionen (lokal integriert)

- Planned Units: Luna-Commit
  `63b478d918e87ac239f24f7c6269beb6ce9b3bf3`, integriert als `70a626c`,
  tatsächliches Diff-, Code-, Import- und Verhaltensreview **PASS**.
  Root-Composition `8882229` migriert Hashing, Normalisierung, Update-
  Projektion, Remote-Importprojektion und Dirty-/Remote-Zustandsklassifikation
  nach `backend/planning/planned_units.py`. Das aktuelle Datum ist explizit;
  DB, Revision, Kalenderkonflikt und Persistenz bleiben außerhalb. Der Worker
  dokumentierte einen bestehenden Restore-Randfall (`local_deleted` wird bei
  der Metadatenübernahme wiederhergestellt); er wurde zur Verhaltenswahrung
  nicht verdeckt in diesem Refactoring geändert.
- Adaptive/Illness: Luna-Commit
  `4cba82fd9b21fe75f329cccf57e34fcca810e578`, integriert als `2f6828e`,
  tatsächliches Diff-, Code-, Import- und Verhaltensreview **PASS**.
  Root-Composition `4d9e1a6` migriert Hard-Workout-Erkennung,
  Recovery-/Kalenderprovenienz, Quick-Action-Blocker, Fingerprint und
  Krankheitsprognose/-ereignisse nach `backend/planning/adaptive.py`.
  Datum, Text-/Tagesgrenzen und Kalenderkennungen werden explizit injiziert;
  die vorhandene transaktionale Apply-Orchestrierung bleibt unverändert.

### Prüfungen und Inventar

- Planned Units: 20 Modultests plus Architektur- und Workout-Repair-Suite,
  insgesamt 50 Tests: **PASS**. Adaptive: neun Modultests plus Architektur-
  und Workout-Repair-Suite, insgesamt 39 Tests: **PASS**.
- `tests.test_server`: 463 Tests, drei übersprungen, **PASS** in 77,612 s.
  `py_compile` und `git diff --check`: **PASS**. Die Formatprüfung des
  Adaptive-Moduls zeigt ausschließlich den schon auf der Basis vorhandenen,
  unveränderten `apply_adaptive_changes`-Altblock; neuer Testcode und neue
  Projektionen sind formatiert.
- Regeneriertes Inventar: P0 und P3 null; P4 enthält noch 195 Definitionen
  und 17 globale Bindungen. `server.py` umfasst 13.777 physische Zeilen.

### Verbleibende Risiken und nächster Schritt

- P4 bleibt offen. Reine Wettkampf-Sync-Planung und Library-Bulk-Auswahl
  laufen als nächste unabhängige Pakete. Danach bleiben stateful Services für
  Persistenz, Locks, Revision/Hash-Transaktionen, Remote-Reconcile und
  strukturierte Apply-Orchestrierung.
- Der vollständige Lauf folgt nach Integration der beiden laufenden reinen
  Pakete; der letzte vollständige PASS bleibt P4.3 mit 1.444 Tests.

## P4.5 — Library-Bulk und lokale Wettkampf-Use-Cases (lokal integriert)

- Library-Bulk-Auswahl: Luna-Erstcommit
  `399de7afda2df6e8280c3f82ce99dcc820ee74f1`, tatsächliches Root-Diff- und
  Verhaltensreview zunächst **FAIL**. Die Datumsprüfung hatte die bisher von
  `date.fromisoformat` akzeptierte ISO-Basisform `JJJJMMTT` zusätzlich
  verboten. Korrektur desselben Workers
  `c2d52d54801c67de1612dae9af6a2c863fd69212`, nach dem Basis-Rebase
  integriert als `50430e3` und `b8597fb`, erneutes Review **PASS**.
  Root-Composition `02c7f90` entfernt
  Auswahl-, UUID-/Datums-/Hash-Helfer und beide Konstantenduplikate aus
  `server.py`; sämtliche Produktions- und Testaufrufer verwenden
  `backend/planning/library.py` direkt.
- Reine Wettkampf-Sync-Planung: Luna-Commit
  `a2f2c0af013daf03dc3003291d8a6e1815997af7`, nach dem Basis-Rebase
  integriert als `9212c88`;
  tatsächliches Diff-, Schnittstellen-, Import- und Verhaltensreview
  **PASS**. Remote-ID-/External-ID-/Identitätspriorität, `local_override`,
  Missing-Remote-Konflikte, Tombstones, Payload-Hashes, deterministische
  Signatur und Summary entsprechen dem entfernten Servercode. Das Modul
  führt keine Provider-Schreiboperation aus und greift nicht auf Serverzustand
  zu.
- Lokale Wettkampf-Use-Cases: nach dem Basis-Rebase Root-Commit `966a5e6`,
  Composition und Aufrufermigration `db233dc`, Review **PASS**.
  `CompetitionService` besitzt
  Lesen, Erstellen, partielles Aktualisieren, Löschen und Konfliktauflösung;
  `DatabaseManager` besitzt Lock und Transaktion, `CompetitionRepository` die
  SQL-Schreiboperationen. Wettbewerb und Audit sowie Wettbewerb, Tombstone
  und Public-Event-Unlink committen oder rollen jeweils gemeinsam zurück.
  Uhr und Repository sind injiziert; es gibt keine Rückimporte, fachlichen
  Server-Callbacks oder Kompatibilitätswrapper. Architekturtests verbieten
  alle entfernten Symbole.

### Prüfungen und Inventar

- Worker Library nach Korrektur: 12 Tests, PASS; Ruff, Format, `py_compile`
  und Diff-Check: PASS. Integrierte Library-/Architektur-/Coach-/Repair-
  Regressionen: 68 Tests, PASS.
- Worker Wettkampf-Sync: fünf Tests, PASS; Ruff, Format, `py_compile` und
  Diff-Check: PASS. Service-/Sync-Plan-/Architekturtests: elf Tests, PASS.
- Integrierte Competition-/Coach-/Server-Regressionssuite: 575 Tests, vier
  übersprungen, **PASS** in 124,463 s. Vollständiger integrierter Lauf:
  `python -m unittest discover -s tests` — 1.494 Tests, 12 übersprungen,
  **PASS** in 182,535 s. Alle Daten waren temporär und alle Provider
  gemockt.
- Ruff auf den neuen Eigentümermodulen und Modultests, Formatprüfung,
  `py_compile`, Inventar-Check und `git diff --check`: **PASS**.
  Regeneriertes Inventar: 1.105 Einträge, 682 verbleibende
  Funktionen/Klassen, P0 und P3 jeweils null; P4 enthält noch 167
  Definitionen und 15 globale Bindungen. `server.py` umfasst 13.393
  physische Zeilen. Maßgeblich ist die eindeutige Eigentümerschaft, nicht die
  Zeilenreduktion.

### Verbleibende Risiken und nächster Schritt

- P4 bleibt offen. Stateful Library-/Template- und Planned-Unit-Persistenz,
  Revision-/Hash-Batches, Planersatz, Adaptive Apply, Trainingskalender und
  Compliance verbleiben in `server.py`. Der Remote-Wettkampf-Sync bleibt bis
  zur P6-Servicegrenze im Server; die jetzt extrahierte reine Planung ist sein
  fachlicher Input.
- Der vorhandene Planned-Unit-Restore-Randfall aus P4.4 bleibt unverändert.
  PR #692 bleibt externe Veröffentlichungsvoraussetzung; ohne bestätigten
  Merge auf `develop` wird der gestapelte Stand nicht publiziert.

## P4.6 — Revisionen, Planmetadaten und Mutationsvorbereitung (lokal integriert)

- Planning-Revision `c1727d3`: Root-Review zunächst **FAIL** wegen eines
  möglichen Lost-Update-Fensters zwischen fehlgeschlagenem Bump und
  Recovery-Lock. Im selben Commit korrigiert und erneut geprüft: **PASS**.
  `PlanningRevisionService` wiederholt den Bump nach Lock-Erwerb und führt
  erforderliche Reset-Initialisierung samt Bump innerhalb derselben
  Transaktion aus; der globale Reset-Merker und Server-Callbacks entfallen.
- Trainingsplan-Service `ccc34ad`: **PASS**. `TrainingPlanService` besitzt
  Listen, CRUD, Statusnormalisierung, Bounds, Constraints, Audit,
  Revision-Bump und Eventpublikation. Der verworfene generische
  Callback-Service wurde gelöscht; es bleibt kein Kompatibilitätswrapper.
- Strukturierte Vorbereitung: Artifact-Limits `0c95d7d`/`7adb9c8`,
  Change-Vorbereitung `a8bc4d7`/`ebd6ecd` und Replacement-Vorbereitung
  `294625d`/`53c9f1b`. Der erste Change-Stand war **FAIL**, weil unhashbare
  Targets statt des bisherigen `TypeError` einen `AppError` geliefert hätten;
  Korrektur `9e7082c`, erneutes Review **PASS**. Datum, Limits, erforderliche
  Felder und Fehlerverträge entsprechen damit dem Altverhalten.
- Planreferenzauflösung `cb56afe`/`2f342cb`: **PASS**. Membership,
  Bounds-Bedarf, autorisierte Planreferenz und Create-Zuordnung liegen in
  `StructuredTrainingPlanResolver`; acht Serverdefinitionen wurden entfernt.
- Planned-Unit-Mutation `3d56422`/`48aaee7` und Library-Mutation
  `5e0daed`/`2a05a7b`: **PASS**. Normalisierung, Konfliktpayload,
  Inhaltsabgleich, Metadatenerhalt und UUID-/Action-Verträge besitzen die
  Fachmodule. Die transaktionalen Persistenz-Use-Cases bleiben bewusst offen.

### Prüfungen und Inventar

- Revision: 120 Tests (einer übersprungen), nach der Lock-Korrektur weitere
  sechs Tests, jeweils PASS. Trainingsplan-Service: elf korrekte Zieltests
  PASS; ein zuvor angegebener nicht existierender Testselektor war ein
  Ausführungsfehler des Review-Kommandos und kein Produktfehler.
- Artifact-/Change-/Replacement-/Resolver-Worker und Root-Wiederholungen:
  acht, elf, 21 beziehungsweise 19 Tests, PASS. Planned-Unit-Integration:
  33 Tests, PASS. Library-Integration: 65 Tests, PASS. Ruff, fokussierte
  Formatprüfung, `py_compile` und `git diff --check`: PASS; der bereits
  unformatierte große Architekturtest wird nicht mechanisch umformatiert.
- Vollständiger integrierter Lauf auf dem inhaltsgleichen Vor-Rebase-Stand
  `70d3b80` (nach Rebase `2f342cb`):
  `python -m unittest discover -s tests` — 1.541 Tests, 12 übersprungen,
  **PASS** in 172,913 s. Sämtliche Daten waren temporär, Provider gemockt.
- Aktuell regeneriertes Inventar nach dem inhaltsgleichen Rebase-Stand
  `2a05a7b`: 1.083 Einträge, 656
  verbleibende Funktionen/Klassen, P0 und P3 jeweils null; P4 enthält noch
  144 Definitionen und 17 globale Bindungen. `server.py` umfasst 13.074
  physische Zeilen; `backend/` umfasst 117 Python-Dateien mit 18.720
  physischen Zeilen. Entscheidend bleibt die Eigentümerschaft, nicht die
  Nettozeilenzahl.

### Externer Stand und verbleibende Risiken

- Die frühere Veröffentlichungsvoraussetzung PR #692 ist bestätigt gemergt:
  `mergedAt=2026-09-20T05:21:32Z`, Merge-Commit
  `5896e7b3ca197b9e8e498a44ac6a853ea52b238f`, erreichbar als aktuelles
  `origin/develop`; dessen Baum ist identisch zum geprüften PR-Head
  `68a317235e94a1d9e5051c4aef0c555c2d882236`.
- P4 bleibt offen: State-Read, Kalenderkonflikt-Service, Library-/Planned-
  Persistenz, Batch-Validierung/-Apply, Planersatz, Adaptive Apply,
  Trainingskalender und Compliance sind noch vollständig zuzuordnen. Nach
  jeder weiteren Integration wird der betroffene Umfang erneut geprüft; ein
  neuer vollständiger Lauf ist vor Veröffentlichung verbindlich.

## P4.7 — Kalender-, State- und Change-Validation-Services (lokal integriert)

- Kalenderkonflikt-Worker `29d40c80dccefca7896537241c515142881dc1db`,
  integriert als `3f57745`, Root-Komposition `e297dac`: **PASS** im
  tatsächlichen Diff- und Code-Review. `CalendarConflictService` besitzt die
  Orchestrierung über lokale, Library- und externe Kalenderquellen; es gibt
  keinen Rückimport und keine fachliche Server-Callback-Implementierung. Ein
  veraltetes Test-Patchziel führte im ersten Volltest zu **FAIL**; Korrektur
  `d278e68` richtet den Patch auf den neuen Eigentümer und bestand sieben
  fokussierte Regressionen.
- Structured-State-Worker-Erststand
  `48b77928` war im Root-Review **FAIL**: `json_valid` hätte das Verhalten bei
  korruptem SQL-Payload verändert, und der Writer-UOW blieb über fremde
  Service-Reads hinweg offen. Korrektur desselben Workers
  `5cb4acc6163eee1de4e2da53e004d739a667c151`, integriert als `8e4367c` und
  `61d17aa`, Root-Komposition `13bd37e`: erneutes Review **PASS**.
  `StructuredTrainingStateService` besitzt State-Projektion und Pagination,
  beendet die DB-Transaktion vor abhängigen Reads und bewahrt das bisherige
  Korruptionsverhalten. Zwei Test-Patchziele für das Page-Limit wurden zum
  Backend-Eigentümer migriert.
- Change-Validator-Worker `8c84a6467f0a904f03c2ae9e038417864b3e7309`,
  integriert als `c1fce69`, Root-Komposition `555e777`: zunächst fand das
  Integrationsreview einen verbliebenen Aufruf des entfernten privaten
  Server-Helpers in `_validate_training_patch_schedule`. Nach der Korrektur
  über die öffentliche `validate_batch`-Schnittstelle: **PASS**. Alle acht
  Datums-, Revision- und Payload-Hash-Helfer liegen im
  `StructuredTrainingChangeValidator`; Validierung bleibt in derselben
  Aufrufertransaktion, und Architekturtests sperren ihre Rückkehr in
  `server.py`.

### Prüfungen und Inventar

- Kalender: 23 Worker-/Root-Tests und nach Komposition 29 Integrationstests,
  PASS; Korrektur des Patchziels: sieben Tests, PASS. Structured State nach
  Korrektur: 41 Worker-/Root-Tests und 45 Integrations-/Architekturtests,
  PASS. Change Validation: 15 isolierte Worker-Tests und 22 Root-
  Integrations-, Rollback- und Architekturtests, PASS.
- Vollständiger integrierter Lauf auf Code-Stand `555e777`:
  `python -m unittest discover -s tests` — 1.589 Tests, 12 übersprungen,
  **PASS** in 180,496 s. Sämtliche Testdaten waren temporär und Provider
  gemockt. Ruff auf den neuen Backend-/Testdateien, `py_compile`, Inventar-
  und `git diff --check`: PASS; bekannte globale Ruff-Befunde und das
  historische Format des großen `server.py`/Architekturtests wurden nicht
  mechanisch verändert.
- Aktuelles Inventar: `server.py` 12.829 physische Zeilen, 1.068 Einträge und
  641 Definitionen. P0 und P3 sind null; P4 enthält noch 133 Definitionen und
  17 globale Bindungen. `backend/` umfasst 120 Python-Dateien mit 21.630
  physischen Zeilen. Eigentümerschaft und entfernte Server-Orchestrierung sind
  maßgeblich, nicht die Zeilenreduktion.

### Verbleibende Risiken und nächster Schritt

- P4 bleibt offen für lokale Planned-Unit-/Library-Persistenz, vollständigen
  Batch-Apply und Planersatz, Adaptive Preview/Apply, Krankheitspausen,
  Trainingskalender und Compliance. Remote-Sync-Orchestrierung bleibt bis P6
  getrennt.
- Die nächsten zwei kleinen, schreibbereichsgetrennten Pakete bauen konkrete
  Services für lokale Planned-Unit- sowie Workout-Library-Erzeugung/-Reads;
  Root integriert ihre Aufrufer anschließend sequenziell und wiederholt das
  Review-Gate nach jeder Änderung.

## P4.8 — Planned-Unit- und Workout-Library-Erzeugung/-Reads (lokal integriert)

- Planned-Unit-Worker `177f37b4a8b21ec74ab296ee5b239907530c0c37`,
  integriert als `85f93db`, Root-Komposition `a8de740`: **PASS** im
  tatsächlichen Diff- und Code-Review. Der Root hat die Schnittstelle um das
  öffentliche, aufrufertransaktionsgebundene `insert` erweitert und die
  bestehende Redaktionsabhängigkeit explizit injiziert. Nach erneutem Review
  besitzt `PlannedUnitService` lokale Erzeugung, generisches Insert und
  Listing; Audit, optionale Planungsrevision, Sync-Metadaten und
  Fehlerredaktion sind erhalten. Die vier bisherigen Server-Funktionen und
  ihre Aufrufer wurden ohne Kompatibilitätswrapper migriert.
- Workout-Library-Worker-Erststand
  `8f029e5169ca9a5270a46ba6975c94982e056067` war im Root-Review **FAIL**:
  `json_valid` hätte das Verhalten bei korruptem JSON geändert, und ein
  Reader statt des bestehenden serialisierten Unit-of-Work hätte den
  Transaktionsvertrag verändert. Korrektur desselben Workers
  `bd86fb00fc02c7308dd817cbc9edd8b6feddb5cc`, integriert als `b09c2bb` und
  `fd4aa39`, Root-Komposition `c13f8ab`: erneutes Review **PASS**.
  `WorkoutLibraryService` besitzt lokale Erzeugung, Template-Validierung und
  Listing mit exakt der bisherigen SQL-/Korruptions- und UOW-Semantik. Die
  vier Server-Funktionen wurden entfernt; Patchziele zeigen auf den neuen
  Eigentümer. Das Insert-SQL gehört nun dem Backend-Service und wird bis zur
  P5-Auslagerung vom bestehenden Undo-Pfad verwendet.

### Prüfungen und Inventar

- Planned Unit: acht isolierte Worker-Tests und 45 kombinierte Service-,
  Integrations- und Architekturtests, **PASS**. Workout Library: neun Tests
  im Erststand, zehn nach der Korrektur und 96 kombinierte Service-,
  Integrations- und Architekturtests, **PASS**.
- Vollständiger integrierter Lauf auf Code-Stand
  `c13f8ab97841ee7f925424fa41af67fa9c8553d7`:
  `python -m unittest discover -s tests` — 1.608 Tests, 12 übersprungen,
  **PASS** in 184,485 s. Sämtliche Testdaten waren temporär und Provider
  gemockt. Ruff auf den neuen Backend-/Testdateien, `py_compile`, Inventar-
  und `git diff --check`: PASS.
- Aktuelles Inventar: `server.py` 12.746 physische Zeilen, 1.061 Einträge und
  635 Definitionen. P0 und P3 sind null; P4 enthält noch 125 Definitionen und
  17 globale Bindungen. `backend/` umfasst 122 Python-Dateien mit 21.884
  physischen Zeilen. Eigentümerschaft, vollständige Orchestrierung und
  Vertragsgleichheit bleiben die Erfolgskriterien.

### Verbleibende Risiken und nächster Schritt

- P4 bleibt offen für Planned-Unit- und Library-Update/Delete/Restore,
  Konfliktauflösung, vollständigen Batch-Apply und Planersatz, Adaptive
  Preview/Apply, Krankheitspausen, Trainingskalender und Compliance.
  Remote-Sync-Orchestrierung bleibt bis P6 getrennt; Undo bleibt P5.
- Als nächste voneinander unabhängige Pakete werden die lokalen
  Planned-Unit- und Library-Mutationspfade in die bestehenden Services
  aufgenommen. Der Root integriert danach sequenziell, migriert sämtliche
  Aufrufer und prüft Transaktion, Revision, Historie und Rollback erneut.

## P4.9 — Lokale Planned-Unit- und Library-Mutationen (lokal integriert)

- Planned-Unit-Worker `9fdc517e7c6eb93dedaca4303e63c0a243411fdc`,
  integriert als `5405b51`, Root-Komposition `6aaba6c`: **PASS** im
  tatsächlichen Diff- und Code-Review. `PlannedUnitService.update` besitzt
  Update, Archive, Restore und auditiertes Tombstone-Delete. Kalenderkonflikt,
  optionale Revisionsanhebung und externe Aufrufertransaktionen sind
  explizite Verträge; ein Event entsteht ausschließlich nach erfolgreichem
  service-eigenem Commit. Fünf alte Server-Funktionen wurden entfernt, alle
  Produktions- und Testaufrufer migriert und ihre Rückkehr architektonisch
  gesperrt. Das gemeinsame Planned-Unit-Update-SQL gehört nun dem Service und
  wird von den noch offenen P5-/P6-Pfaden referenziert.
- Library-Worker `ff839587beea7a6795207a5732b07fee0bb9a386`,
  integriert als `a6d1c87`, Root-Komposition `b3ec33e`: **PASS** im
  tatsächlichen Diff- und Code-Review. `WorkoutLibraryService.update` besitzt
  Update, Archive, Restore und physisches Delete unsynchronisierter Vorlagen;
  synchronisierte Einträge behalten die Archive-statt-Delete-Grenze. History-
  before verwendet den effektiven Sync-Zustand, Mutationen werden atomar auf
  `local`/dirty gesetzt, und das Event folgt erst nach Commit. Drei alte
  Server-Funktionen und sämtliche direkten Aufrufer wurden entfernt und per
  Architekturtest gesperrt.

### Prüfungen und Inventar

- Planned Unit: 18 unabhängige Root-Wiederholungstests des Worker-Patches,
  danach 20 Service-/Architekturtests, 17 geplante Serverpfade und ein
  Repair-Pfad auf dem komponierten Stand, **PASS**. Library: 17 unabhängige
  Root-Wiederholungstests, danach 19 Service-/Architekturtests, 26
  library-bezogene Serverpfade und alle 16 Coach-Review-Tests, **PASS**.
- Vollständiger integrierter Lauf auf Code-Stand
  `b3ec33e5a5fca2b2284ce81a2ac61df174cb8cca`:
  `python -m unittest discover -s tests` — 1.624 Tests, 12 übersprungen,
  **PASS** in 191,312 s. Sämtliche Testdaten waren temporär und Provider
  gemockt. Ruff und Format-Check auf den vier Service-/Testdateien,
  `py_compile`, Inventar- und `git diff --check`: PASS.
- Die Neugenerierung zeigte zunächst zwei bestehende Morning-Check-in-Helfer
  fälschlich als P0, weil ihre zeilenbasierte Fallback-Grenze verschoben war.
  Die symbolbasierte Zuordnung im Generator weist beide wieder P8 zu;
  Generator-Check, Ruff-F-Check und Compile: **PASS**.
- Aktuelles Inventar: `server.py` 12.586 physische Zeilen, 1.052 Einträge und
  627 Definitionen. P0 und P3 sind null; P4 enthält noch 117 Definitionen und
  17 globale Bindungen. `backend/` umfasst 122 Python-Dateien mit 22.123
  physischen Zeilen.

### Verbleibende Risiken und nächster Schritt

- P4 bleibt offen für Planned-Unit-Konfliktauflösung und Sync-State-
  Persistenz, Library-/Planned-Remote-Persistenzgrenzen, vollständigen
  Batch-Apply und Planersatz, Adaptive Preview/Apply, Krankheitspausen,
  Trainingskalender und Compliance. Remote-Orchestrierung bleibt P6, Undo P5.
- Der nächste Schritt zieht die lokale Planned-Unit-Konfliktauflösung in den
  vorhandenen Service. Sie ist von Remote-Provider-Schreiben getrennt, muss
  aber beide Strategien, Audit, Revision, Tombstones und atomaren Rollback
  unverändert bewahren.

## P4.10 — Konfliktauflösung und atomarer Library-Plan-Batch (lokal integriert)

- Planned-Conflict-Worker `300ca232d23b6d62c6966420a2743f17e7900327`,
  integriert als `16483a7`, Root-Komposition `d9d966b`: **PASS** im
  tatsächlichen Diff- und Code-Review. `PlannedUnitService.resolve_conflict`
  besitzt Keep-local, Übernahme eines normalisierten Remote-Zustands und den
  persistenten Remote-Deletion-Tombstone. Hash, Identität, Timestamps und
  Revision bleiben in derselben Transaktion; der Readback folgt erst nach
  Commit. Wie zuvor entstehen weder History-Eintrag noch Event oder
  Provider-Write. Fünf Server-Funktionen und alle direkten Aufrufer wurden
  entfernt und architektonisch gesperrt.
- Library-Plan-Worker `82cd55d4f236519d7ef5ff692ac3582c2f9b94dd`,
  integriert als `ba8365a`, Root-Komposition `3de1ecf`: **PASS** im
  tatsächlichen Diff- und Code-Review. `WorkoutLibraryPlanService.apply`
  besitzt Eingabe-/Templatevalidierung, vollständige Konfliktprüfung und
  lokale Erstellung. Anders als der frühere sequenzielle Serverpfad umfasst
  eine einzige reentrante Unit-of-Work jetzt alle Creates, History-Einträge
  und Revisionsbumps; ein später Fehler rollt den gesamten Batch zurück. Das
  eine State-Event wird erst nach Commit publiziert. Sieben Server-Funktionen
  und direkte Testaufrufe wurden entfernt und gesperrt; Remote Writes bleiben
  ausgeschlossen.

### Prüfungen und Inventar

- Konfliktauflösung: 27 unabhängige Root-Wiederholungstests, danach 29
  Service-/Architekturtests und der reale Serverkonfliktpfad, **PASS**.
  Library-Plan: acht unabhängige Root-Wiederholungstests, danach zehn
  Service-/Architekturtests, vier reale Serverpfade und alle 26
  Coach-Tool-Coverage-Tests, **PASS**.
- Vollständiger integrierter Lauf auf Code-Stand
  `3de1ecf03a0246d02e7dfd0694597c1d050a71e8`:
  `python -m unittest discover -s tests` — 1.641 Tests, 12 übersprungen,
  **PASS** in 172,572 s. Sämtliche Testdaten waren temporär und Provider
  gemockt. Ruff und Format-Checks der neuen/geänderten Service-Tests,
  `py_compile`, Inventar- und `git diff --check`: PASS.
- Aktuelles Inventar: `server.py` 12.427 physische Zeilen, 1.042 Einträge und
  616 Definitionen. P0 und P3 sind null; P4 enthält noch 108 Definitionen und
  17 globale Bindungen. `backend/` umfasst 123 Python-Dateien mit 22.372
  physischen Zeilen.

### Verbleibende Risiken und nächster Schritt

- P4 bleibt offen für den vollständigen strukturierten Batch-Apply und
  Planersatz, Adaptive Preview/Apply, Krankheitspausen, Trainingskalender und
  Compliance. Planned-/Library-Sync-State und Provider-Reconciliation bleiben
  P6; Undo bleibt P5.
- Als nächster Architekturblock wird der transaktionsgebundene strukturierte
  Change-Apply von seinen `PlanningChangeDependencies`-Servercallbacks
  befreit. Revision-/Hash-Prüfung, History und kompletter Rollback sind dabei
  die Freigabekriterien.

## P4.11 — Strukturierter Batch-Apply und atomarer Planersatz (lokal integriert)

- Change-Service-Worker `3185c0c0f43b64d65e66d4dee493c78a0a825046`,
  integriert als `0b686a2`, Root-Komposition `48c79a9`: **PASS** im
  tatsächlichen Diff- und Code-Review. `StructuredTrainingChangeService`
  besitzt Vorbereitung, Datums-/Revisions-/Hashprüfung, Planauflösung,
  Create/Update/Archive/Delete, genau einen Revisionsbump, Bounds-Aktualisierung
  und das Event nach erfolgreichem Commit. `apply_in_db` teilt dieselbe
  Orchestrierung mit dem äußeren Training-Patch, eröffnet dort aber weder eine
  zweite Transaktion noch ein Event. `PlanningChangeDependencies`, freie
  Apply-Funktionen und vier Server-Callbacks wurden vollständig entfernt.
- Replacement-Service-Worker `f918d34913ccd2fae9498944af021cd8955859c8`,
  integriert als `5243cab`, Root-Komposition `a97397e`: **PASS** im
  tatsächlichen Diff- und Code-Review. Der
  `StructuredTrainingPlanReplacementService` besitzt Auswahl der zu
  ersetzenden Units und Metadaten, History-Kapazität, vollständige
  Kalenderprüfung vor Writes, Tombstones/Archivierung, geerbte oder explizite
  Constraints, Plan-/Unit-Neuanlage und genau einen Revisionsbump in einer
  Unit-of-Work. Neun Server-Helfer und alle direkten Testaufrufe wurden
  entfernt und architektonisch gesperrt. Es gibt keine Provider-, Event- oder
  `server.py`-Rückimporte und keine neue Remote-Schreibgrenze.

### Prüfungen und Inventar

- Unabhängige Root-Wiederholung des Change-Worker-Stands: 31
  Change-/Validation-/Resolver-Tests, **PASS**; Ruff, Format, `py_compile` und
  Worker-Diff-Check: PASS. Integriert: 33 Modul-/Architekturtests und 16 reale
  Server-Regressionen, **PASS**.
- Unabhängige Root-Wiederholung des Replacement-Worker-Stands: acht Tests,
  **PASS**; Ruff, Format, `py_compile` und Worker-Diff-Check: PASS. Integriert:
  zehn Service-/Architekturtests, vier Replacement- und zwei Broad-
  Replacement-Serverpfade, **PASS**.
- Vollständiger integrierter Lauf auf Code-Stand
  `a97397ea6c8f1e689b13bb236493f14c52707179`:
  `python -m unittest discover -s tests` — 1.657 Tests, 12 übersprungen,
  **PASS** in 124,724 s. Sämtliche Testdaten waren temporär und Provider
  gemockt. Ruff für neue Module, Service-Tests, Architektur und Generator,
  `py_compile`, Inventar- und `git diff --check`: PASS. Der breite Ruff-Lauf
  auf `server.py`/`tests/test_server.py` bleibt wegen 222 historischen
  Baseline-Befunden ungleich null; die geänderten Eigentümerdateien sind
  sauber.
- Aktuelles Inventar: `server.py` 12.217 physische Zeilen, 1.027 Einträge und
  605 Definitionen. P0 und P3 sind null; P4 enthält noch 95 Definitionen und
  16 globale Bindungen. `backend/` umfasst 124 Python-Dateien mit 22.728
  physischen Zeilen.

### Verbleibende Risiken und nächster Schritt

- P4 bleibt offen für Adaptive Preview/Apply, Krankheitspausen,
  Trainingskalender und Compliance. Planned-/Library-Sync-State,
  Provider-Reconciliation und Remote-Schreiben bleiben P6; Undo bleibt P5.
- Nächster P4-Block ist die Entfernung von `AdaptiveDependencies` und der
  fachlichen Adaptive-/Illness-Callbacks aus `server.py`. Preview und Apply
  müssen dieselbe Autorisierungs-, Kalender-, Revisions-, Hash-, History- und
  Rollback-Semantik behalten; Remote-Sync bleibt ein separater Einstieg.

## P4.12 — Adaptive Preview/Apply und lokale Krankheitspausen (lokal integriert)

- Apply-Service-Worker `4e8476bcbedf3c8de24a7dbb76e9a31c371ff28c`:
  **FAIL** im ersten tatsächlichen Diff- und Code-Review. Ein nicht als Objekt
  dekodierbares Preview-Payload wurde still zu einem leeren Objekt ersetzt und
  hätte dadurch einen beschädigten Preview-Datensatz als angewendet markieren
  können. Korrekturauftrag an denselben Worker; Korrektur-Commit
  `3c9299c3ee2d388796ac502f01d2dadd1e5c1e29`: **PASS**. Integriert als
  `1f89859` und `3c9299c`, Root-Komposition `3386d6e`. Der
  `AdaptiveReplanApplyService` besitzt Preview-Lookup, Eigentümer-/Status-,
  Ablauf-, Revisions- und Payload-Hash-Prüfung, History-Kapazität, Krankheit-
  Check-in, lokale Planänderung, Illness-Pause, Revisionsbump und finalen
  Preview-Status in einer Unit-of-Work. Beschädigte Preview-Payloads schlagen
  wieder geschlossen fehl.
- Preview-Service-Worker `1de255bfebd593281f8fe9e9502bee8c85c5cd5c`,
  integriert als `a0b6f58`, Root-Komposition
  `d57bdaa803cc2bf02d16481f00a8f4ab1ca436c7`: **PASS** im tatsächlichen
  Diff- und Code-Review. `AdaptiveReplanPreviewService` besitzt Status- und
  Latest-Projektion, aktuelle Krankheitspause, Kalender-/Feedback-/Wetter-
  Kontext, bestehende Pause, Ersetzungsentscheidung und persistierte Preview-
  Erzeugung. `AdaptiveDependencies`, die freien Adaptive-Helfer und alle
  fachlichen Preview-Callbacks in `server.py` wurden entfernt; Architekturtests
  sperren ihre Rückkehr. Die Composition Root koordiniert nach erfolgreichem
  lokalen Apply nur noch den separaten optionalen Remote-Sync und die
  Antwortprojektion.

### Prüfungen und Inventar

- Unabhängige Root-Wiederholung des korrigierten Apply-Worker-Stands: 15
  Service-Tests, **PASS**; Ruff, Format, `py_compile` und Diff-Check: PASS.
  Integriert: 17 Modul-/Architekturtests, elf Server-Adaptive-Regressionen,
  je ein Workout-Repair- und Coach-Review-Pfad sowie drei Coach-Tool-Pfade,
  **PASS**.
- Unabhängige Root-Wiederholung des Preview-Worker-Stands: 26 Tests,
  **PASS**; Ruff, Format, `py_compile` und Diff-Check: PASS. Integriert: 34
  Preview-/Apply-/Projektions-/Wetter-/Architekturtests, elf Server-Adaptive-
  Regressionen sowie Workout-Repair-, Coach-Review-, Coach-Tool- und Audit-
  Pfade, **PASS**.
- Vollständiger integrierter Lauf auf Code-Stand
  `d57bdaa803cc2bf02d16481f00a8f4ab1ca436c7`:
  `python -m unittest discover -s tests` — 1.671 Tests, 12 übersprungen,
  **PASS** in 114,697 s. Sämtliche Testdaten waren temporär und Provider
  gemockt. Inventargenerator und dessen `--check`-Modus: PASS.
- Aktuelles Inventar: `server.py` 11.803 physische Zeilen, 1.005 Einträge und
  584 Definitionen. P0 und P3 sind null; P4 enthält noch 72 Definitionen und
  16 globale Bindungen. `backend/` umfasst 125 Python-Dateien mit 23.386
  physischen Zeilen.

### Verbleibende Risiken und nächster Schritt

- P4 bleibt offen für lokale Planerzeugung/Library-Persistenz,
  Tagesplanungskontext, Trainingskalender und Compliance. Planned-/Library-
  Sync-State, Provider-Reconciliation und Remote-Schreiben bleiben P6; Undo
  bleibt P5.
- Als nächste unabhängige P4-Scheiben werden die transaktionsgebundene lokale
  Planerzeugung und der reine Tagesplanungskontext in konkrete Services
  überführt. `server.py` bleibt dabei ausschließlich Composition Root.

## P4.13 — Lokale Planerzeugung und Tagesplanungskontext (lokal integriert)

- Planerzeugungs-Worker `ef291d5bed571bfb1f5c4c196e471fccc6b09e70`,
  integriert als `1814f77bb9dac6d0aec4a93e2a2778865a96a0d9`:
  **PASS** im tatsächlichen Diff- und Code-Review.
  `LocalTrainingPlanCreationService` besitzt Eingabe-/Workout-Normalisierung,
  doppelte und bestehende Kalenderkonflikte, konservative Template-
  Wiederverwendung, optionale Planmetadaten samt History, Planned-Unit-
  Erzeugung und genau einen Revisionsbump. Eigenes und caller-owned
  Transaktionsverhalten bleiben getrennt; mittige Fehler rollen Plan, Units,
  History und Revision vollständig zurück.
- Daily-Context-Worker `0166f9c0784986d3035c9d5ea56cef8d917faa52`,
  integriert als `f3790cdb1fe04d71c3f4a782c678d47f5e497ffb`:
  Modulreview zunächst **PASS**, integriertes Root-Gate danach **FAIL**. Der
  Service öffnete mit `reader()` eine dritte Datenbankverbindung innerhalb des
  bereits aktiven `public_state`-Unit-of-Work-Pfads. Korrekturauftrag an
  denselben Worker; Korrektur `43946259e003bc30c6f0c98354b087e285891f46`,
  integriert als `e3c178113344f5a98b3aa8c7c5c42ce4b35c79ce`:
  **PASS**. KV-Reads nutzen nun die verschachtelte Unit-of-Work und damit die
  aktive Connection. Override-, Korruptions-, Freshness-, Relevant-only- und
  Projektionssemantik bleiben erhalten.
- Root-Komposition `ef11bb178a6ec07b72f6077d9597758b3668f54f`:
  **PASS** nach erneutem tatsächlichem Diff- und Aufruferreview. Sie entfernt
  fünf Planerzeugungshelfer, `_validate_plan_calendar`,
  `save_workout_library_entries` und `daily_planning_context` vollständig aus
  `server.py`. Produktionsaufrufer und Tests verwenden die konkreten Services;
  der mittige Training-Patch-Fehlertest patcht den echten Klassenmethoden-
  Eigentümer. Es gibt keine Kompatibilitätswrapper, Rückimporte oder neue
  Remote-Schreibgrenze.

### Prüfungen und Inventar

- Unabhängige Root-Wiederholung: zehn Planerzeugungs- und acht Daily-Context-
  Tests, jeweils **PASS**; Ruff, Format, `py_compile` und Worker-Diff-Checks:
  PASS. Integrierte Service-/Projektions-/Architektur- und migrierte
  Coach-/Repair-Module: 182 Tests, **PASS**.
- Erster vollständiger `tests.test_server`-Lauf: 463 Tests, drei übersprungen,
  **FAIL** mit einer zusätzlichen DB-Verbindung und einer veralteten
  Server-Konstantenreferenz. Nach Worker-Korrektur und Migration auf
  `backend.performance.morning_battery_service.MORNING_BATTERY_HISTORY_KEY`:
  463 Tests, drei übersprungen, **PASS** in 46,575 s.
- Vollständiger integrierter Lauf auf Code-Stand
  `ef11bb178a6ec07b72f6077d9597758b3668f54f`:
  `python -m unittest discover -s tests` — 1.689 Tests, 12 übersprungen,
  **PASS** in 166,886 s. Sämtliche Testdaten waren temporär und Provider
  gemockt. Ruff für neue Services/Tests, Architektur und Generator,
  `py_compile`, Inventargenerator, dessen `--check`-Modus und
  `git diff --check`: PASS.
- Aktuelles Inventar: `server.py` 11.692 physische Zeilen, 999 Einträge und
  579 Definitionen. P0 und P3 sind null; P4 enthält noch 66 Definitionen und
  16 globale Bindungen. `backend/` umfasst 127 Python-Dateien mit 23.674
  physischen Zeilen.

### Verbleibende Risiken und nächster Schritt

- P4 bleibt für Trainingskalender/Compliance und die noch in `server.py`
  liegende Artifact-Commit-Orchestrierung offen. Wettkampf-, Library- und
  Planned-Unit-Reconciliation sowie Remote-Schreiben gehören weiterhin P6;
  Undo bleibt P5.
- Nächster P4-Block ist die vollständige lokale Artifact-Stage/Commit-
  Orchestrierung einschließlich Eigentümer-, Conversation-, Revisions- und
  Rollback-Verträgen. Danach wird die verbleibende Trainingskalender- und
  Compliance-Orchestrierung abgegrenzt.

## P4.14 — Trainingsplan-Artefakte und Kalender-Read-Modell (lokal integriert)

- Kalender-Worker `54eb75b34d1218c920839f197560c8c3ac8077bf`,
  integriert als `67dc165`: **PASS** im tatsächlichen Diff- und Code-Review.
  `planning/calendar_read_model.py` besitzt die kombinierte Projektion für
  lokale Planung, Trainingskalender, Compliance, Wetter und paralleles
  Radtraining. Das Read-Modell hat genau sechs öffentliche Ergebnisfelder;
  Provider-I/O und kanonische Datenbeschaffung bleiben explizite
  Composition-Aufgaben.
- Artifact-Worker `47ffde30e50cec93c3398a68653a4042496f1a8a`,
  integriert als `2e20cc5`: **PASS** im tatsächlichen Diff- und Code-Review.
  `TrainingPlanArtifactService` besitzt Stage und Commit einschließlich
  Normalisierung, Conversation-Rebind, Baseline-Revision, Kalender-Vorprüfung,
  Limitvalidierung, lokaler Planpersistenz und bedingtem Statusupdate in einer
  Unit-of-Work. Fehler rollen Artifact, Plan, Units, History und Revision
  gemeinsam zurück.
- Root-Komposition `77057e70ec5074e234d5b4f900abbc8b8eedfc71`:
  **PASS** nach erneutem tatsächlichem Diff-, Code- und Aufruferreview. Fünf
  Artifact-Helfer wurden vollständig entfernt. Der verbleibende
  `_structured_coach_plan_artifact_result` ist ausschließlich der
  Autorisierungs-/Intent-Adapter und delegiert Facharbeit an den konkreten
  Service. Öffentliche State-Reads verwenden das neue Kalender-Read-Modell;
  es gibt keine Rückimporte, dauerhaften Kompatibilitätswrapper oder neue
  Remote-Schreibgrenze.

### Prüfungen und Inventar

- Unabhängige Root-Wiederholung: 19 Kalender-Read-Modell- und acht Artifact-
  Service-Tests, jeweils **PASS**; Ruff, Format, `py_compile`, Worker-Diff-
  Checks, Inventargenerator und `git diff --check`: PASS. Der integrierte
  Zielblock mit Service-, Projektions-, Architektur- und migrierten
  Aufrufertests umfasste 95 Tests und war **PASS**.
- Erster vollständiger `tests.test_server`-Lauf: 463 Tests, drei übersprungen,
  **FAIL** wegen eines veralteten Test-Patch-Ziels `server.URLError`. Nach
  Migration auf den tatsächlichen Eigentümer `urllib.error.URLError` war der
  gezielte Netzwerkdiagnostiktest **PASS**; die Wiederholung von
  `tests.test_server` war mit 463 Tests und drei übersprungen **PASS**.
- Vollständiger integrierter Lauf auf Code-Stand
  `77057e70ec5074e234d5b4f900abbc8b8eedfc71`:
  `python -m unittest discover -s tests` — 1.698 Tests, 12 übersprungen,
  **PASS** in 142,360 s. Sämtliche Testdaten waren temporär und Provider
  gemockt.
- Aktuelles Inventar: `server.py` 11.637 physische Zeilen, 990 Einträge und
  576 Definitionen. P0 und P3 sind null; P4 enthält noch 62 Definitionen und
  16 globale Bindungen. `backend/` umfasst 129 Python-Dateien mit 23.896
  physischen Zeilen.

### Verbleibende Risiken und nächster Schritt

- P4 bleibt offen: Drei lokale Planned-Read-Wrapper liegen noch in
  `server.py`; mehrere als P4 inventarisierte Reconciliation- und
  Remote-Schreibabläufe gehören tatsächlich P6, Coach-Autorisierung P7 und
  Pagination P10. Diese Zuordnung wird erst nach Aufruferprüfung im Inventar
  geändert.
- Nächster abgeschlossener P4-Schnitt ist die direkte Verwendung des
  `PlannedUnitService` für lokale, datierte und Coach-Reads einschließlich
  Migration der Test-Patch-Ziele. Adaptive Remote-Orchestrierung bleibt bis
  zur geklärten P6/P7-Grenze unangetastet; Undo folgt in P5.

## P4.15 — Lokale Planning-Read-Oberfläche und Phasenabschluss

- Planned-Read-Worker `3b92c1bbca5f49c1f81147c842e2b4ff1ddc2e93`,
  integriert als `0672e7f`: **PASS** im tatsächlichen Diff- und Code-Review.
  `PlannedUnitService.list_for_coach()` verwendet den bestehenden lokalen
  `list`-Read und den kanonischen Kalenderprojektor; Future-only-Filter,
  Sortierung, Limit und die exakt vier öffentlichen Ergebnisfelder sind durch
  einen fokussierten Regressionstest abgesichert. Der Worker änderte nur die
  zwei freigegebenen Dateien und führte weder Provider-I/O noch Server-
  Rückimporte ein.
- Root-Integration `22c97c0a8401294c60922188b5e8025e1c82c4a4`:
  **PASS** nach tatsächlichem Diff-, Code- und Aufruferreview. Die drei
  `server.py`-Wrapper `list_local_planned_workouts`,
  `list_dated_local_planned_workouts` und `list_coach_planned_workouts` sind
  vollständig entfernt; Produktionsaufrufer und Tests verwenden direkt den
  konkreten Service. Zwei verwaiste Konstanten und drei tote numerische
  Hilfsdefinitionen wurden gelöscht. Adaptive Defaultwerte liegen nun beim
  fachlichen `planning/adaptive.py`-Eigentümer.
- Das Inventar ordnet verbliebene Remote-Reconciliation und Sync-Orchestrierung
  konkret P6, Coach-Kontext/Autorisierung P7 und die Service-Komposition P11
  zu. Diese Funktionen sind weiterhin offen und wurden nicht als extrahiert
  ausgegeben. P4 enthält damit tatsächlich keine verbleibende Definition oder
  globale Bindung; sämtliche P4-Checklistenpunkte sind abgeschlossen.

### Prüfungen und Inventar

- Unabhängige Root-Wiederholung des Worker-Patches: 28
  `PlannedUnitService`-Tests sowie Ruff, Format, `py_compile` und Diff-Check:
  PASS. Nach Integration waren 30 Planned-/Architekturtests und anschließend
  44 Planned-/Adaptive-/Architekturtests **PASS**.
- Erster vollständiger `tests.test_server`-Lauf: **FAIL** mit einem Fehler,
  weil der migrierte Test eine einzelne, vom Factory-Aufrufer nicht
  wiederverwendete Serviceinstanz patchte. Das Patch-Ziel wurde auf
  `PlannedUnitService.list` beim tatsächlichen Eigentümer verschoben; der
  gezielte Test war danach **PASS**. Die vollständige Wiederholung umfasste
  463 Tests, drei übersprungen, und war **PASS** in 46,862 s.
- Vollständiger integrierter Lauf auf Code-Stand
  `22c97c0a8401294c60922188b5e8025e1c82c4a4`:
  `python -m unittest discover -s tests` — 1.699 Tests, 12 übersprungen,
  **PASS** in 115,786 s. Sämtliche Testdaten waren temporär und Provider
  gemockt. Nach der rein statischen Inventar-Deduplizierung liefen die 44
  betroffenen Planned-/Adaptive-/Architekturtests erneut **PASS**;
  Inventargenerator samt `--check`, Ruff-F-Checks, Ruff/Format für die
  betroffenen Backend-Module, `py_compile` und `git diff --check`: PASS.
- Aktuelles Inventar: `server.py` 11.597 physische Zeilen, 979 Einträge und
  570 Definitionen. P0, P3 und P4 sind null. `backend/` umfasst 129
  Python-Dateien mit 23.910 physischen Zeilen.

### Verbleibende Risiken und nächster Schritt

- Adaptive Provider-Synchronisierung, Competition-/Library-/Planned-
  Reconciliation, Remote-Readback und Dirty-State-Verarbeitung bleiben P6;
  Coach-Autorisierung und Kontextkomposition bleiben P7. Diese Grenzen wurden
  nicht verändert und müssen in ihren Phasen weiterhin vollständig aus
  `server.py` entfernt werden.
- Nächster abhängiger Block ist P5: zuerst ein konkreter lokaler
  Change-History-Read/Preview-Service, danach der transaktionale Undo-
  Orchestrator mit fachlichen Domänenoperationen und ohne Rückimport.

## P5 — Änderungshistorie und transaktionales Undo

- History-Read-Worker `b5e1b10bc3ec1c1f764ebcc5c4b9879058a1fa12`,
  integriert als `4e82b35`: **PASS** im tatsächlichen Diff- und Code-Review.
  `ChangeHistoryService` besitzt Cleanup, begrenzte öffentliche Liste, den
  aktuellen Audit-Zustand aller fünf lokalen Entitätstypen und die exakte
  Diff-Zielrekonstruktion. Die Root-Aufrufermigration `a401b81` entfernte
  `list_change_history`, `_history_current`, `_history_current_record` und
  `_history_target`; Produktions- und Testaufrufer verwenden den konkreten
  Service. Keine Rückabhängigkeit auf `server.py`, HTTP oder Coach.
- Profil-Worker `06d5b807b11d628493e2578a2712f2c1679c5db9`,
  integriert als `23f2583`: **PASS**. Wettkampf-Worker
  `56bff44f9d88e14f00786d148ea497b5e82a8859`, integriert als `4b9c4f9`:
  **PASS**. Library-Worker `c04a128bf6c17674f3382bc855d5c20f0bd5fb07`,
  integriert als `49a3781`: **PASS**. Jeder Patch wurde unabhängig anhand
  des tatsächlichen Diffs und Codes geprüft. Die Restore-Operationen verwenden
  die äußere Unit-of-Work, mutieren ihre Eingaben nicht und erzeugen weder
  eigenen Audit, Revision, Event noch Provider-I/O. Remote-Identitäten bleiben
  bei lokalen Updates erhalten; Delete/Recreate folgen exakt dem bisherigen
  lokalen Undo-Vertrag.
- Root-Stände `f12f051` und `a7a19c6`: **PASS**. Planned-Unit-Restore besitzt
  Sichtbarkeits-/Datumsrekonstruktion, Kalenderkonfliktprüfung, Sync-State und
  Remote-ID-Erhalt; Training-Plan-Restore besitzt Update, Recreate und Delete.
  Beide sind rollbackfähig und überlassen Revision und Audit dem
  Orchestrator.
- Undo-Worker `087a0c77f5e8350c568af4b5dfa9689a3e99ab82`,
  integriert als `4a0cd76`: **PASS** im tatsächlichen Diff- und Code-Review.
  `HistoryUndoService.preview` bindet den aktuellen Audit-Hash und liefert ein
  Coach-neutrales Proposal-DTO. `apply` validiert Change-ID, erlaubte Aktion,
  gespeicherten After-Hash und bestätigten Current-Hash in einer Unit-of-Work,
  dispatcht direkt an den fachlichen Eigentümer, bump't Planned-/Training-
  Revision genau einmal und schreibt genau einen `undo`-Eintrag. Domain-,
  Revision- und History-Fehler rollen die gesamte Operation zurück.
- Root-Integration `81c9612e78dfa62e2d55233c2dbddfe4c8cedaba`:
  **PASS** nach vollständigem Diff-, Code- und Aufruferreview. Alle alten
  Undo-Helfer, `UNDO_ENTITY_HANDLERS`, `_history_preview` und
  `_apply_change_undo` sind aus `server.py` entfernt. Tool- und HTTP-Pfade
  komponieren nur den History-Preview mit der bestehenden generischen,
  sessiongebundenen Coach-Proposal-Persistenz; Apply ruft direkt den
  Orchestrator auf. Autorisierung, CSRF-/Tokenbindung, Ablaufzeit,
  Remote-Schreibgrenze und Replay-Schutz bleiben erhalten.

### Prüfungen und Inventar

- Worker-Wiederholungen: History Read 7, Profil 7, Wettkampf 8, Library 23 und
  Undo-Orchestrator 11 Tests; jeweils Ruff, Format, `py_compile` und
  `git diff --check`: **PASS**. Root Planned Unit 32 und Training Plan 8 Tests:
  **PASS**.
- Kombinierter Domänen-/History-/Architekturstand: 87 Tests, **PASS**. Nach
  Server-Integration: 98 Service-/Architekturtests, 42 Coach-Review-/Tool-
  Tests und 6 gezielte serverweite Undo-Regressionsfälle, **PASS**.
- Vollständiges `tests.test_server` auf `81c9612`: 463 Tests, drei
  übersprungen, **PASS** in 45,603 s. Erwartete Fehlerlogs stammen aus
  gemockten Negativpfaden.
- Vollständiger integrierter Discovery-Lauf auf `81c9612`: 1.737 Tests,
  zwölf übersprungen, **PASS** in 116,218 s. Ausschließlich temporäre
  Testdaten und gemockte Provider; die erwarteten Fehlerlogs stammen aus
  expliziten Negativpfaden.
- Aktuelles Inventar: `server.py` 11.351 physische Zeilen, 966 Einträge und
  557 Definitionen. P0, P3, P4 und P5 sind null. `backend/` umfasst 132
  Python-Dateien mit 24.384 physischen Zeilen. Die zwei Service-Factories sind
  ausdrücklich P11-Composition-Root und nicht offene P5-Fachlogik.

### Verbleibende Risiken und nächster Schritt

- Die generische Coach-Proposal-Persistenz bleibt bis P7 in `server.py`; sie
  enthält keine History-Fachlogik. Provider-Synchronisierung, Reconciliation,
  Job-Retry/Restart und Remote-Dirty-State gehören unverändert P6.
- Nächster abhängiger Block ist P6. Er beginnt mit den providerfreien
  Reconciliation-/Persistenzkernen für Competition, Library und Planned Unit;
  Worker-Lebenszyklus und vollständige Sync-Orchestrierung folgen erst nach
  stabilen Modulgrenzen.

## P2.14 — Konkrete OpenAI- und Gemini-JSON-Clients

- Lokale Basis: dokumentierter P2.13-Stand `1a312e8` auf dem korrigierten,
  vom Root geprüften P2.11-Head
  `68a317235e94a1d9e5051c4aef0c555c2d882236`. Der Stand bleibt gestapelt,
  solange PR #692 nicht bestätigt auf `develop` gemergt ist.
- Gemini-Worker-Commit
  `b529154643523f53d5cd1924a244f5a981242cab`, integriert als `15cdada`:
  tatsächliches Diff- und Code-Review **PASS**. `GeminiJsonClient` besitzt
  Modell-/Key-Validierung, JSON-Request, Cancellation-Weitergabe,
  Providerstatus und Usage. Root-Integration `de92310` entfernt
  `gemini_raw_request`; `server.py` verdrahtet nur den konkreten Client.
- OpenAI-Worker-Erststand `fe9c3f5bce62c9d5ef2b48fbea4c0147703c52aa`,
  integriert als `1357bd8`: Review **FAIL**. Ein Abbruch während des
  Conversation-Lock-Backoffs konnte als internes `ProviderRequestCancelled`
  aus dem öffentlichen Client entweichen. Korrektur desselben Workers
  `804b8809c26ec0e801930a0c841761d89307882b`, integriert als `73167cd`:
  erneutes tatsächliches Diff- und Code-Review **PASS**. Die Grenze liefert
  wieder `AppError` 499 mit `chat_cancelled`.
- Root-Integration `6303aec`: Review **PASS**. `OpenAIResponsesClient` besitzt
  Request-Aufbau und -Ausführung, Conversation-Lock-Retry, Background-Create,
  Retrieve/Cancel, Gesamtdeadline, Polling, Cancellation, Response-ID-Prüfung
  und einmalige finale Usage-Erfassung vollständig. `server.py` enthält weder
  `openai_request`, `retrieve_openai_response`, `cancel_openai_response` noch
  `gemini_raw_request`; alle Produktionsaufrufer verwenden die konkreten
  Eigentümer. Es gibt keine Rückimporte, fachlichen Server-Callbacks oder
  Kompatibilitätswrapper; Architekturtests verbieten die entfernten Symbole.
- Erster vollständiger Lauf auf `e462633`: **FAIL** mit zwei veralteten
  Test-Patchzielen in `tests/test_coach_response_failure.py`. Beide Tests
  mockten noch `responses_request`, obwohl der Background-Ablauf jetzt dem
  konkreten OpenAI-Client gehört. Korrektur `a5aceb8` und regeneriertes
  Inventar `8f8eca3`: erneutes Diff- und Aufruferreview **PASS**; Rate-Limit-
  Retry, Partial-Success, genau ein Sync und redigierte Providerfehler bleiben
  unverändert geprüft.
- `server.py` hat 19.379 physische Zeilen und 1.073 Definitionen. Das Inventar
  enthält 1.514 Einträge; P0 bleibt bei null unklaren Zuordnungen, in P2
  verbleiben 54 Definitionen und 8 globale Bindungen. Maßgeblich sind die
  eindeutigen Transport- und Zustandsbesitzer, nicht die Reduktion um 86
  Serverzeilen.

### Prüfungen

- Gemini-Worker und Root-Wiederholung: 30 Tests, PASS; OpenAI-Worker nach
  Korrektur und Root-Wiederholung: 61 Tests, PASS.
- Integrierte Provider- und Architekturregressionen: 93 Tests, PASS;
  zehn gezielte Server-Kompositions-/Aufrufertests sowie drei korrigierte
  Coach-Fehlerregressionen: PASS.
- Erster vollständiger Lauf: 1.006 Tests, 12 übersprungen, **FAIL** mit zwei
  veralteten Mock-Zielen. Vollständiger Wiederholungslauf auf `8f8eca3`:
  `python -m unittest discover -s tests` — 1.006 Tests, 12 übersprungen,
  PASS in 177,698 s.
- Ruff/F-/E9-Prüfung der berührten Provider-, Server-, Test- und
  Inventardateien, `py_compile`, Inventar-Check und `git diff --check`: PASS.

### Verbleibende Risiken und nächster Schritt

- PR #692 bleibt trotz aller übrigen grünen Gates offen: Der Codex-Review-
  Check hat nur den alten Head geprüft. Die einzige bisherige zulässige
  `@codex review`-Anforderung fand kein P1; gemäß Projektregel wurde ohne
  ausdrückliche Freigabe keine zweite Anforderung gesendet. P2.12–P2.14 werden
  vor einem bestätigten Merge dieses Basisstands nicht veröffentlicht.
- P2 bleibt offen: OpenAI-/Gemini-Streamfehler- und Streamorchestrierung,
  Audio-Transkription, die bis P7 verbleibende Gemini-Historie sowie weitere
  Garmin-/Intervals-Adaptergrenzen liegen noch in `server.py`.
- Nach dem bestätigten Merge von PR #692 sind Rebase auf den tatsächlichen
  Squash-Commit und ein erneutes vollständiges Review-/Test-Gate erforderlich.

## P2.15 — Konkrete OpenAI- und Gemini-Stream-Clients

- Lokale Basis: dokumentierter und vollständig geprüfter P2.14-Stand
  `bce75d20a41ad3ecc7e184476f3c9ee5f8992524`; der Stapel bleibt wegen des
  weiterhin offenen Basis-PR #692 unveröffentlicht.
- Gemini-Worker-Erststand
  `e97a0e4439efaf8ba637e4540bd82dc960f4d433`, integriert als `427f6f5`:
  Review **FAIL**. Der generische Fehlerlog hätte private Callback-Gründe
  aufnehmen können, und gleichzeitig gesetzte Cancel-Events veränderten die
  bisherige Timeout-/Netzwerk-/HTTP-Statussemantik. Korrektur desselben Workers
  `ad4ce8743fce91db9116c9315d1ee487e8c0d753`, integriert als `03dcde4`:
  erneutes Diff- und Code-Review **PASS**. `GeminiStreamClient` besitzt
  Requestaufbau, Header-Abbruch, begrenztes SSE-Lesen, Aggregation,
  Fehlerklassifizierung, Status/Usage und Cancellation vollständig; private
  Provider- oder Callbacktexte werden nicht geloggt. Root-Integration
  `fb3fade` reduziert `gemini_stream_request` auf Payload-/Historienadapter
  und Response-Normalisierung.
- OpenAI-Worker-Erststand
  `884068aafc46ee95230c16ec65f218b90e33c7cd`, integriert als `615933c`:
  Review **FAIL**. Der nachgelagerte Cancel-Check lief vor dem Speichern einer
  bereits vollständig gelesenen finalen Response und konnte dadurch eine
  falsche leere Cancelled-Usage erzeugen; die UTC-Zeitquelle war nicht
  verpflichtend. Korrektur desselben Workers
  `d5c998f63d592dc8f3868b478898d69e4be93b1d`, integriert als `b91679f`:
  erneutes Diff- und Code-Review **PASS**. Finale Response, Retry-After,
  Conversation-Lock-Backoff, Response-ID, Status/Rate-Limits, Usage,
  Diagnose-Capture, Disconnect und alle Cancellation-Pfade behalten ihren
  Vertrag; beliebige Callback-Fehler werden vor Logs und Diagnosen statisch
  projiziert.
- Root-Integration `4dbb8aa`: Review **PASS**. `server.py` komponiert die
  beiden konkreten Clients und routet nur noch den Provider. Die vollständige
  OpenAI-Stream-Orchestrierung samt sieben Fehler-/Logging-Callbacks und dem
  früheren `openai_stream_request` wurde entfernt. Es gibt keine Rückimporte,
  fachlichen Server-Callbacks oder Kompatibilitätswrapper; Server-Tests prüfen
  den öffentlichen Router, und Architekturtests sperren alle entfernten
  Symbole sowie beide neuen Clientklassen.
- Inventar-/Planstand `9da9a6f`: Review **PASS**. Eine nach der Zeilenverschiebung
  sichtbar gewordene positionsabhängige Fehlzuordnung von 14 bekannten
  Symbolen wurde durch explizite stabile Eigentümer ersetzt. P0 ist wieder
  vollständig geschlossen.
- `server.py`: 19.068 physische Zeilen und 1.067 verbleibende Definitionen.
  Das Inventar enthält 1.504 Einträge; P0 bleibt bei null unklaren
  Zuordnungen, in P2 bleiben 48 Definitionen und 8 globale Bindungen. Erfolg
  ist die vollständige Stream-Orchestrierung in den konkreten Clients, nicht
  die Reduktion um 311 Serverzeilen.

### Prüfungen

- Gemini-Worker nach Korrektur und Root-Wiederholung: 38 Tests, PASS;
  OpenAI-Worker nach Korrektur und Root-Wiederholung: 71 Tests, PASS.
- Integrierte Provider-, Architektur- und migrierte Server-Regressionen:
  123 Tests, PASS. Vollständige `tests.test_server`-Suite: 463 Tests,
  3 übersprungen, PASS in 77,618 s.
- Vollständiger integrierter Lauf auf `4dbb8aa`:
  `python -m unittest discover -s tests` — 1.023 Tests, 12 übersprungen,
  PASS in 180,449 s.
- Ruff auf den betroffenen Provider-, Provider-Test-, Architektur- und
  Inventargenerator-Dateien, `py_compile`, Inventar-Check und
  `git diff --check`: PASS.

### Verbleibende Risiken und nächster Schritt

- PR #692 bleibt die externe Veröffentlichungsblockade: alle übrigen Checks
  sind grün, aber der vorgeschriebene Codex-Review-Check bezieht sich auf den
  alten Head. Da der einzige abgeschlossene Review kein P1 enthielt, verbietet
  die Projektregel ohne ausdrückliche Freigabe eine zweite Anforderung.
- P2 bleibt offen für Audio-Transkriptionsorchestrierung sowie die vorhandenen
  Garmin-/Intervals-Adaptergrenzen. Die persistierte Gemini-Dialoghistorie
  bleibt gemäß Plan bewusst bis P7 im Composition Root.
- Nach dem bestätigten Merge von PR #692 muss der gesamte gestapelte Stand auf
  den tatsächlichen Squash-Commit rebasiert und erneut vollständig geprüft
  werden; erst danach darf dieses Paket veröffentlicht werden.

## P2.16 — Audio-Transkription und Intervals-API-Adapter

- Lokale Basis: dokumentierter und vollständig geprüfter P2.15-Stand
  `91379f3`; der Stapel bleibt wegen des weiterhin offenen Basis-PR #692
  unveröffentlicht.
- Audio-Worker `b1046e3`, integriert als `6f29f07`: Review **PASS**.
  `AudioTranscriptionClient` besitzt Eingabe-, Größen- und MIME-Validierung,
  Providerwahl, transiente Gemini-Base64- und OpenAI-Multipart-Payloads,
  Transport sowie Response-Prüfung vollständig. Es gibt keinen Rückimport auf
  `server.py`; Audio oder Provider-Payload werden nicht persistiert.
  Root-Integration `7039d22`: Review **PASS**. `transcribe_audio` komponiert nur
  noch den Client und reicht Provider und Modell weiter; das bestehende
  90-Sekunden-Timeout und der konfigurierbare kompatible OpenAI-Endpunkt bleiben
  erhalten.
- Intervals-Worker-Erststand `d0e8bf0`, integriert als `7ffa96f`: Review
  **FAIL**. `pagination` lieferte `MappingProxyType`; dieser Wert wird direkt in
  Provider-Snapshots gespeichert und wäre bei der anschließenden
  JSON-Persistenz nicht serialisierbar gewesen. Korrektur desselben Workers
  `265a50b`, integriert als `2b4fe88`: erneutes Diff- und Code-Review **PASS**.
  `IntervalsApiClient` besitzt Basic Auth, Read-/Write-Transport und begrenzte
  Pagination; der interne Pagination-Zustand hat genau einen Eigentümer und
  wird als defensive, JSON-serialisierbare Kopie exponiert.
- Root-Integration `0513bbe`: erster fokussierter Lauf **FAIL**, weil der
  delegierende Read-Wrapper `cancel_event=None` anders als zuvor explizit an
  den gepatchten Adapter weiterreichte. Nach der Korrektur, das Schlüsselwort
  nur bei einem tatsächlichen Event zu setzen, erneutes Review **PASS**. Die
  vier betroffenen Test-Patch-Ziele zeigen nun auf den API-Client. Die
  `intervals_operation`-Dekoratoren bleiben unverändert vor `post`, `put` und
  `delete`; dadurch wurden weder Autorisierung noch Remote-Schreibgrenze in den
  reinen Provider-Adapter verschoben. Sync-, Snapshot-, Workout- und
  Library-Use-Cases bleiben bewusst für P4/P6 außerhalb des Adapters.
- Die Architekturtests sperren `AudioTranscriptionClient` und
  `IntervalsApiClient` gegen eine erneute Implementierung in `server.py`.
  Es gibt keine Backend-Rückimporte und keine neuen Sammelmodule. Das
  minimalistische Adapter-/Kompositionsdesign folgt dem verwendeten
  Ponytail-YAGNI-Gate: vorhandene Transporte und Pagination werden
  wiederverwendet, ohne eine zweite Abstraktionsschicht einzuführen.
- Inventarstand nach Regeneration und Korrektur der positionsabhängigen
  Zuordnung: `server.py` hat 19.026 physische Zeilen und 1.068 verbleibende
  Definitionen; das Inventar enthält 1.501 Einträge. P0 bleibt bei null
  unklaren Zuordnungen, P2 bei 48 Definitionen und 8 globalen Bindungen. Der
  fachliche Erfolg ist das verlagerte Zustands- und Orchestrierungseigentum,
  nicht die Reduktion um 42 Serverzeilen.

### Prüfungen

- Audio-Worker und Root-Wiederholung: 7 Provider-Tests, PASS; drei direkte
  Server-Regressionen und zwei Architekturtests ebenfalls PASS.
- Intervals-Worker nach Korrektur und Root-Wiederholung: 6 Provider-Tests und
  42 Intervals-Regressionen, PASS. Integrierter fokussierter Lauf: 48 Tests,
  PASS; Audio-/Architekturlauf: 9 Tests, PASS.
- Vollständige `tests.test_server`-Suite auf `0513bbe`: 463 Tests,
  3 übersprungen, PASS in 80,966 s.
- Vollständiger integrierter Lauf:
  `python -m unittest discover -s tests` — 1.034 Tests, 12 übersprungen,
  PASS in 175,609 s.
- Ruff auf den betroffenen Provider-, Provider-Test-, Architektur- und
  Inventargenerator-Dateien, `py_compile`, Inventar-Check und
  `git diff --check`: PASS.

### Verbleibende Risiken und nächster Schritt

- PR #692 bleibt die externe Veröffentlichungsblockade: alle übrigen Checks
  sind grün, aber der vorgeschriebene Codex-Review-Check bezieht sich auf den
  alten Head. Der einzige abgeschlossene Review enthielt kein P1; deshalb wird
  ohne ausdrückliche Freigabe keine zweite Review-Anforderung gesendet.
- Die konkreten OpenAI-/Audio- sowie Garmin-/Intervals-Adapterziele von P2 sind
  erfüllt. Offen bleibt ausschließlich die laut Plan an P7 gebundene
  persistierte Gemini-Dialoghistorie; die nächste unabhängige Arbeit beginnt
  deshalb mit P3.
- Nach dem bestätigten Merge von PR #692 muss der gesamte gestapelte Stand auf
  den tatsächlichen Squash-Commit rebasiert und erneut vollständig geprüft
  werden; erst danach darf dieses Paket veröffentlicht werden.

## P2.9 — Provider-Status, Usage und Rate-Limit-Persistenz

- Basis: bestätigter Merge-Commit
  `da4251a74b4218a962e2285e27542d49e92abf38` von PR #689; `mergedAt`
  `2026-09-19T19:49:22Z`, Erreichbarkeit auf `origin/develop`, grüne Gates
  und null offene Review-Threads bestätigt.
- Luna-Worker, erste geprüfte Commits `7e83e1f` und `7c11d7d`, integriert als
  `5346a8b` und `d56fa07`: erster Review **FAIL**. Die erste Fassung entfernte
  `rate_limits: {}` aus der Gemini-Summary und führte ein neues generisches
  Usage-Log für Gemini ein. Konkreter Korrekturauftrag ging an denselben
  Worker. Erneutes tatsächliches Diff- und Code-Review: **PASS** — die
  bestehenden Summary- und Logging-Verträge sind wieder exakt hergestellt.
- Integrierter Arbeitsstand: **PASS**. `ProviderStateService` besitzt nun
  Status-, Usage- und OpenAI-Rate-Limit-Schlüssel, Normalisierung sowie die
  atomare Read-Modify-Write-Transaktion. Der Composition Root bindet genau
  eine Instanz an aktiven `DatabaseManager`, `KeyValueRepository`, `DB_LOCK`,
  Uhr und Logger und verwirft sie bei Managerwechsel. Backend-Code importiert
  `server.py` nicht; die entfernten Serverimplementierungen sind durch den
  Architekturtest gesperrt. Sämtliche Aufrufer und Test-Patch-Ziele verwenden
  den neuen Eigentümer direkt; dauerhafte Kompatibilitätswrapper gibt es nicht.
- Erster vollständiger Integrationslauf: **FAIL** — nach direktem Zurücksetzen
  des `DATABASE_MANAGER` durch den bestehenden Test-Isolationshelper blieb der
  Service an den geschlossenen Manager gebunden. Root-Korrektur: jede
  Manager-Neuerzeugung invalidiert den Service unabhängig davon, wie der alte
  Manager entfernt wurde. Der neue Lifecycle-Regressionstest und die zuvor
  blockierende Sequenz aus Dialogue-, Recovery- und Providerfehlerfällen
  laufen danach mit 84 Tests in 14,622 s durch: erneutes Review **PASS**.
- `server.py`: 19.868 physische Zeilen und 1.090 verbleibende
  Funktionen/Klassen. Das Inventar enthält 1.536 Einträge; P0 bleibt ohne
  unklare Zuordnung, in P2 bleiben 69 Definitionen und 8 globale Bindungen
  offen. Entscheidend ist der vollständige Eigentümerwechsel; die Zeilenzahl
  allein ist kein Abnahmekriterium.

### Prüfungen

- Worker-Stand: 46 Provider-State-/Usage-/OpenAI-Tests, PASS; Root-Diff-Review,
  Ruff, Bytecode-Compile und `git diff --check`: PASS.
- Architektur-, Provider-State- und Coach-Response-Fehlerregressionen:
  12 Tests, PASS. Gezielte HTTP-, OpenAI-/Gemini-Streaming-, Status-, Usage-
  und Deadlockregressionen: 14 Tests, PASS.
- Vollständiger `tests.test_server`-Lauf: 461 Tests, 3 übersprungen, PASS in
  122,146 s. Vollständiger Repository-Lauf nach der Lifecycle-Korrektur:
  955 Tests, 12 übersprungen, PASS in 122,806 s. Ruff für die neuen
  Provider-State-Dateien und die neu eingeführte Closure-Bindung, Compileall,
  Inventar-Check und `git diff --check`: PASS.
- Externes Codex-Review auf `3ee4e4880a0b3d4f892a98d41d926f9f8e8395ec`:
  **FAIL (P1)** — ohne konfigurierte OpenAI-/Gemini-Credentials liefert die
  Settings-Auswahl absichtlich den leeren String, den der neue Service strikt
  ablehnte. Korrektur: nur die beiden öffentlichen Projektionen verwenden wie
  zuvor OpenAI als leeren Summary-Fallback; die sichtbare Provider-Auswahl
  bleibt leer. Neuer No-Credentials-Test sowie State-, Deadlock-, Service- und
  Architekturregressionen: 11 Tests, PASS. Vollständiger Wiederholungslauf:
  956 Tests, 12 übersprungen, PASS in 135,212 s.
- Korrigierter Head `81e03832e2c7c2c3ffa8e7690f22fcc49677f0be`:
  erneutes Root-Diff-Review **PASS**. Der einmal zulässige Codex-Follow-up-
  Review meldete keine weiteren Befunde; CodeQL, SonarCloud, Unit-Shards,
  Container-, Quality- und Browser-/Accessibility-Gates sind grün. Der einzige
  Review-Thread ist gelöst.
- PR #690 wurde am `2026-09-19T20:29:37Z` als Squash gemergt. Merge-Commit
  `22e4b1b90bdaec7adb5a24010dff4b02f634e83b` ist auf `origin/develop`
  erreichbar.

### Verbleibende Risiken und nächster Schritt

- Request-/Background-Transport und die verbleibende Netzwerk-, Retry- und
  Statusorchestrierung liegen noch in `server.py`; P2 ist daher noch offen.
- Jede weitere Änderung an diesem Stand erfordert ein erneutes Root-Review.
  Vor dem Merge bleiben vollständiger Testlauf und externe PR-Gates
  verbindlich.

## P2.10 — OpenAI-Background-Polling

- Basis: bestätigter Merge-Commit
  `22e4b1b90bdaec7adb5a24010dff4b02f634e83b` von PR #690; `mergedAt`
  `2026-09-19T20:29:37Z`, Erreichbarkeit auf `origin/develop`, grüne finale
  Gates und ein gelöster, veralteter Review-Thread bestätigt.
- Luna-Worker-Commit `b331a712d6348a0b4b867dd4c4069315d1e72638`:
  eigenes tatsächliches Diff- und Code-Review **PASS**. Der OpenAI-Adapter
  besitzt jetzt Response-ID-validiertes Polling, abbrechbares Warten,
  monotone Deadline und Best-effort-Remote-Cancel. Die Funktion importiert
  `server.py` nicht, loggt keine Nutzdaten und besitzt weder Usage-/Status-
  Persistenz noch Serverzustand.
- Integrationsreview **PASS**: `responses_background_request` delegiert die
  Poll-Schleife an den Adapter; Create/Resume, finale Response-Validierung und
  Usage-Erfassung behalten ihre bisherigen Eigentümer. Die an den Adapter
  übergebene Restdeadline zieht Create-/Resume-Zeit ab und erhält damit die
  bisherige Gesamtgrenze. Es gibt keinen Kompatibilitätswrapper und keinen
  neuen Sammelmodul-Einstieg.
- Das Inventar weist `_gemini_request_payload` nun ausdrücklich P7
  `coach/conversation.py` zu, weil die Funktion persistierte Historie und
  Request-Aufbau verbindet. Damit verbleiben null unklare P0-Zuordnungen.
  `server.py` hat 19.869 physische Zeilen und 1.090 Definitionen; im Inventar
  bleiben 69 P2-Definitionen und 8 P2-Bindungen offen.

### Prüfungen

- Worker: `tests.test_provider_openai` — 43 Tests, PASS; Ruff, Bytecode-Compile
  und `git diff --check`: PASS.
- Integrierte Provider-, Background-, Coach-Aufrufer- und Architekturtests:
  137 Tests, PASS in 29,714 s.
- Ruff für Adapter, Adaptertests und Inventargenerator sowie B023 für den
  ergänzten Servertest, Bytecode-Compile, Inventar-Check und
  `git diff --check`: PASS.
- Vollständiger Repository-Lauf: 964 Tests, 12 übersprungen, PASS in
  181,523 s.

### Verbleibende Risiken und nächster Schritt

- Request-, Retrieve-/Cancel- und Stream-Fehler-/Statusorchestrierung liegen
  weiterhin in `server.py`; P2 ist noch nicht abgeschlossen.
- PR #691 wurde mit geprüftem Head
  `c059cfc510469e2c96e977add4db083e10bfde6e` am
  `2026-09-19T20:54:22Z` als Squash-Merge
  `176b897653783e5993efcc0ff39e7a05770ff44e` integriert. Der Merge-Commit
  ist auf `origin/develop` erreichbar; Codex, SonarCloud, CodeQL, Test-Shards,
  Container-, Quality- und Browser-Gates sind grün. Die GraphQL-Abfrage ergab
  null Review-Threads.

## P2.11 — OpenAI-Conversation-Lock-Retry

- Basis: bestätigter Merge-Commit
  `176b897653783e5993efcc0ff39e7a05770ff44e` von PR #691.
- Luna-Worker-Commit `78d99dc2b063ddd6bdaef47880666f222cb0ea33`:
  tatsächliches Diff- und Code-Review **PASS**. Die zustandslose öffentliche
  Adapterfunktion `request_with_conversation_retry` besitzt Lock-Erkennung,
  drei begrenzte Versuche, die Delays 1/2 Sekunden, abbrechbares Event-Warten
  und Retry-Telemetrie-Hook. Nicht-Lock- und letzter Lock-Fehler werden
  unverändert weitergereicht; Cancellation behält den Lock-Fehler als Cause.
  Es gibt keinen `server.py`-Import, keine Provider-/Usage-Persistenz und
  keine Nutzdatenprotokollierung.
- Integrationscommit `6ba525e8929d9f08d15250ac4c7c1f5f554d95cd`:
  eigenes tatsächliches Diff- und Code-Review **PASS**.
  `responses_request` und `responses_stream_request` delegieren die gesamte
  Retry-Entscheidung und Backoff-Reihenfolge an den Adapter. Die verbleibenden
  Callbacks führen nur den konkreten Request beziehungsweise redigierte
  Retry-Telemetrie aus. Promptes Stream-Cancel während des Backoffs wird auf
  den bestehenden 499-Vertrag abgebildet und weiterhin als abgebrochene
  OpenAI-Usage erfasst.
- Externes Sonar-Review auf Head `3dd1cae`: **FAIL** wegen
  `python:S3776` (`AaC7gesGGAbKVok_PxnX`) an
  `request_with_conversation_retry`, Complexity 27 statt maximal 15.
  Korrektur desselben Luna-Workers
  `e9d67013c35d29cc4e84433fca1ecc45b5d0111a`: tatsächliches Diff- und
  Code-Review erneut **PASS**. Drei kleine private, zustandslose Helfer tragen
  Cancellation-Prüfung und Warten; öffentliche Schnittstelle,
  Fehleridentität, Cause und Callback-Reihenfolge bleiben unverändert.
- `server.py` hat 19.869 physische Zeilen und 1.090 Definitionen; im Inventar
  verbleiben 69 P2-Definitionen und 8 P2-Bindungen. Die unveränderte Zahl zeigt,
  dass dieses Paket Orchestrierung statt bloßer Zeilenmenge verlagert.

### Prüfungen

- Worker und Root-Wiederholung: `tests.test_provider_openai` — 50 Tests,
  PASS; Ruff, Bytecode-Compile und `git diff --check`: PASS.
- Integrierter OpenAI-Adapter plus vollständige Servertests: 515 Tests,
  3 übersprungen, PASS in 82,598 s.
- Gezielte Retry-/Cancellation-Regressionsprüfung: 54 Tests, PASS in
  0,388 s. Inventar-Check, relevante Ruff-Regeln, Bytecode-Compile und
  `git diff --check`: PASS.
- Vollständiger Repository-Lauf: 972 Tests, 12 übersprungen, PASS in
  174,490 s.
- Vollständiger Wiederholungslauf nach der Sonar-Korrektur: 972 Tests,
  12 übersprungen, PASS in 181,657 s. Adaptertests, Ruff, Bytecode-Compile
  und `git diff --check` wurden auf dem Korrekturstand ebenfalls erneut mit
  PASS ausgeführt.

### Verbleibende Risiken und nächster Schritt

- Request-, Retrieve-/Cancel-, allgemeine HTTP- sowie Stream-Fehler- und
  Statusorchestrierung liegen noch in `server.py`; P2 ist daher weiter offen.
- Vor dem Merge folgen noch die externen PR-Gates. Jede Änderung nach diesem
  PASS erfordert ein erneutes Review des betroffenen Umfangs.

## P2.12 — Response-Validierung und SDK-Aufrufbeobachtung

- Lokale Basis: korrigierter, vom Root geprüfter P2.11-Head
  `68a317235e94a1d9e5051c4aef0c555c2d882236`. Dieser Commit ist noch nicht
  auf `develop`, weil PR #692 trotz aller übrigen grünen Gates am für den
  aktualisierten Head fehlenden Codex-Review scheitert. Eine zweite Review-
  Anforderung wurde wegen der verbindlichen Ein-Review-Regel nicht ausgelöst.
- OpenAI-Validierungs-Worker-Commit
  `27d77c83465704165769ae9cb8770efe2147cc50`, integriert als `e85423f`:
  tatsächliches Diff- und Code-Review **PASS**. Der reine OpenAI-Adapter besitzt
  jetzt Response-Shape, Status- und Fehlercode-Validierung mit statischen
  Meldungen und expliziter Code-Allowlist. Er importiert `server.py` nicht,
  persistiert keinen Zustand und gibt keine Providerinhalte weiter.
- SDK-Beobachtungs-Worker-Erststand `0babbdb`, integriert als `afc881c`:
  Review **FAIL**. Die Operation-Phase wich vom bisherigen Vertrag ab und für
  bereits klassifizierte `AppError` wurde ein zusätzliches Warning-Log
  eingeführt. Korrektur desselben Workers
  `287fb26bdae8522688530f174e6e2a1699a8bcc8`, integriert als `448e6e0`:
  erneutes tatsächliches Diff- und Code-Review **PASS**. Phase, AppError-
  Weitergabe, Diagnose-Capture, Fehlerübersetzung und Ergebnis-Metadaten
  entsprechen wieder dem Ausgangsvertrag; Request- und Response-Inhalte
  bleiben redigiert.
- Root-Integration `c1f6cb6`, `8a10baa` und Abschlusscommit `116ebe9`:
  Review des tatsächlichen Gesamt-Diffs
  `68a317235e94a1d9e5051c4aef0c555c2d882236..116ebe9` **PASS**.
  `ProviderStateService.validate_openai_response` besitzt die sichere
  Statuspersistenz und AppError-Abbildung; `backend.providers.http.external_call`
  besitzt die SDK-Beobachtung. `server.py` enthält weder
  `_validate_openai_response` noch `external_call`; alle Produktionsaufrufer
  und Test-Patchziele verwenden die konkreten Eigentümer direkt. Die beiden
  Garmin-Einstiege verdrahten ausschließlich Logger, Diagnose-Capture und den
  aktuellen Operation-Kontext. Es gibt keine Rückimporte, fachlichen Server-
  Callbacks oder Kompatibilitätswrapper.
- `server.py` hat 19.778 physische Zeilen und 1.088 Definitionen. Das Inventar
  enthält 1.535 Einträge; P0 bleibt bei null unklaren Zuordnungen, in P2
  verbleiben 67 Definitionen und 8 globale Bindungen. Gegenüber P2.11 wurden
  zwei fachliche Definitionen vollständig verlagert; maßgeblich ist ihr neuer
  eindeutiger Eigentümer, nicht die Reduktion um 91 Zeilen.

### Prüfungen

- OpenAI-Worker und Root-Wiederholung: 53 Provider-Adaptertests, PASS;
  Compile- und Diff-Check: PASS.
- SDK-Beobachtungs-Worker nach Korrektur und Root-Wiederholung: 31 Tests,
  PASS; Compile- und Diff-Check: PASS.
- Integrierte Provider-, State-, Server-, Architektur-, Fehler- und
  Cancellation-Regressionsprüfung: 102 Tests, PASS. Ergänzter Provider-Lauf:
  94 Tests, PASS.
- Ruff auf allen geänderten Provider-Modulen, Provider-Tests und dem
  Inventargenerator, `python -m compileall -q server.py backend tests`,
  `python scripts/server_extraction_inventory.py --check` und
  `git diff --check`: PASS. Der breite Ruff-Lauf auf der vollständigen alten
  `tests/test_server.py` meldet weiterhin ausschließlich vorbestehende
  Monolith-Testbefunde; die zwei neuen Befunde wurden behoben.
- Vollständiger Repository-Lauf:
  `python -m unittest discover -s tests` — 982 Tests, 12 übersprungen, PASS in
  178,197 s.

### Verbleibende Risiken und nächster Schritt

- Der Stand bleibt lokal und wird nicht als gestapelter PR veröffentlicht,
  solange P2.11 nicht bestätigt auf `develop` gemergt ist. Nach dem Merge ist
  ein Rebase auf den tatsächlichen Squash-Commit sowie ein erneuter vollständiger
  Review- und Testlauf erforderlich.
- P2 bleibt offen: allgemeine `http_json`-Netzwerk-/Statusorchestrierung,
  OpenAI-Request-, Retrieve-/Cancel- und Stream-Orchestrierung sowie weitere
  Garmin-/Intervals-Adaptergrenzen liegen noch in `server.py`.

## P2.13 — Beobachteter JSON-HTTP-Client

- Lokale Basis: dokumentierter P2.12-Stand `ce744bd` auf dem korrigierten,
  vom Root geprüften P2.11-Head
  `68a317235e94a1d9e5051c4aef0c555c2d882236`. Der Stand bleibt gestapelt,
  solange PR #692 nicht bestätigt auf `develop` gemergt ist.
- Response-Header-Worker-Commit
  `70332752785208b62465c178e636602d1f260f17`, integriert als `6074de6`:
  tatsächliches Diff- und Code-Review **PASS**. Die allowlist-basierte,
  redigierte und begrenzte Headerprojektion besitzt jetzt
  `backend/observability.py`; Credentials und unbekannte Header werden nicht
  übernommen, ungültige Headerobjekte liefern sicher ein leeres Ergebnis.
- JSON-HTTP-Worker-Erststand `3b5e69be`, integriert als `8a93aa8`: Review
  **FAIL**. Der Operation-Kontext war beim Bau des Clients eingefroren,
  Tracebacks wurden unterdrückt und zwei technische Fehlerlogs enthielten
  nicht die bisherige redigierte Fehlerangabe. Korrektur desselben Workers
  `a346ae1`, integriert als `759c250`: erneutes tatsächliches Diff- und
  Code-Review **PASS**. Der Kontext wird pro Request gelesen, reguläre
  Exceptions behalten ihren Traceback und Fehlertext wird ausschließlich
  redigiert und begrenzt protokolliert.
- Root-Integration `66f06d2`: Code- und Diff-Review zunächst **PASS**, das
  anschließende vollständige Gate jedoch **FAIL**. `IntervalsClient()` band den
  konkreten Client bereits bei der Konstruktion und verlangte dadurch in zwei
  reinen Workout-Tests unnötig SQLCipher; zwei DB-Schema-Tests verwendeten noch
  den veralteten `server`-Lookup-Ort.
- Korrekturcommit
  `bc5d20470055dd16c20e7524150e94f06dd115ce`: erneutes Gesamt-Review
  **PASS**. `JsonHttpClient` besitzt Request-Aufbau und -Ausführung,
  Cancellation, Größenlimit, HTTP-/Netzwerk-/Clientfehler, OpenAI-/Gemini-
  Statuspflege, Logging, Diagnose-Capture und Response-Cleanup vollständig.
  `server.py` konstruiert nur die konkreten Abhängigkeiten und löst sie im
  noch offenen `IntervalsClient` erst beim tatsächlichen Request auf; dieser
  Composition-Thunk enthält keine Fachlogik. Alle Produktionsaufrufer und
  Test-Patchziele verwenden den neuen Eigentümer. Es gibt keine Rückimporte,
  fachlichen Server-Callbacks oder Kompatibilitätswrapper. Architekturtests
  verbieten die entfernten HTTP-Symbole.
- Die Inventarregeneration nach Entfernung von `http_json` machte zwölf zuvor
  nur heuristisch zugeordnete Funktionen wieder P0-unklar. Der korrigierte
  Generator verankert Snapshot-Zugriffe in `sync/snapshots.py` und OpenAI-
  Request-/Stream-Orchestrierung in `providers/openai.py`; P0 ist wieder null.
- `server.py` hat 19.465 physische Zeilen und 1.075 Definitionen. Das Inventar
  enthält 1.516 Einträge; P2 enthält 58 Definitionen und 8 globale Bindungen.
  `backend/` umfasst 52 Python-Dateien mit 8.138 physischen Zeilen. Maßgeblich
  ist der vollständige Eigentümerwechsel des allgemeinen JSON-HTTP-Ablaufs,
  nicht die Reduktion um 313 Serverzeilen.

### Prüfungen

- Response-Header-Worker und Root-Wiederholung: 21 Tests, PASS; HTTP-Client-
  Worker nach Korrektur und Root-Wiederholung: 38 Tests, PASS.
- Integrierte Provider-, Observability- und Architekturregressionen: 61 Tests,
  PASS. Breite Server-, Coach-, Repair- und Tool-Aufruferprüfung: 521 Tests,
  3 übersprungen, PASS in 107,917 s.
- Erster vollständiger Lauf: 992 Tests, 12 übersprungen, **FAIL** mit vier
  Integrationsfehlern. Gezielte Korrekturprüfung: 6 Tests, PASS.
- Vollständiger Wiederholungslauf auf `bc5d204`:
  `python -m unittest discover -s tests` — 992 Tests, 12 übersprungen, PASS in
  186,930 s.
- Ruff auf den geänderten Backend-/Inventar-/Testdateien sowie F-/E9-Prüfung
  der berührten Monolithdateien, `python -m compileall -q server.py backend
  tests scripts/server_extraction_inventory.py`, Inventar-Check,
  `py_compile` und `git diff --check`: PASS.

### Verbleibende Risiken und nächster Schritt

- PR #692 bleibt trotz aller übrigen grünen Gates offen, weil der Codex-
  Review-Check den korrigierten Head nicht geprüft hat. Die letzte zulässige
  Review-Anforderung fand kein P1; deshalb wurde ohne ausdrückliche Freigabe
  keine zweite Anforderung gesendet. P2.12/P2.13 werden nicht gestapelt
  veröffentlicht, bevor dieser Basisstand bestätigt gemergt ist.
- P2 bleibt offen: OpenAI-Request-, Background-Retrieve/Cancel-, Streamfehler-
  und Statusorchestrierung sowie der vollständige Intervals-Adapter liegen noch
  in `server.py`. Der nächste kleine Schritt ist die konkrete OpenAI-Request-
  und Background-Grenze; danach folgen Rebase und vollständige Wiederholungs-
  prüfung auf dem tatsächlichen Merge-Commit der Basis.
- Lokale Docker-/E2E-Ausführung bleibt durch den nicht erreichbaren Docker-
  Desktop-Daemon blockiert; externe PR-Gates dürfen nicht umgangen werden.

## P2.8 — Begrenzte JSON-Ausführung und OpenAI-Streamtransport

- Basis: bestätigter Squash-Merge von PR #688 am `2026-09-19T19:28:37Z`;
  Merge-Commit `1e46e2c17554b879981f7aab033db26990f81acf` ist auf
  `origin/develop` erreichbar. Alle Checks waren grün und die GraphQL-Abfrage
  ergab null Review-Threads.
- HTTP-Worker: geprüfter Commit
  `7ded0bfd90533c21a860bfaa69cc170c17826b62`, integriert als `bc300f2`.
  Review: **PASS** — `request_json` besitzt Öffnen, begrenztes Lesen,
  UTF-8-/JSON-Dekodierung und Cleanup; Status, Header und Bytezahl werden in
  `JsonResponse` zurückgegeben. Transportfehler bleiben unverändert, ungültige
  Antworten erhalten eine statische, geheimnisfreie Fehlermeldung.
- OpenAI-Worker: Erststand
  `3341dc4d745e6e16b17b9adbd4dfb84e295f076c`: **FAIL**, weil Status und
  Rate-Limit-Header nach dem geschlossenen Response nicht verfügbar waren.
  Korrektur `7e0e15c2742f50031262e4f5216f422b0c1a5165`: erneut **FAIL**, weil ein
  dauerhafter zweiter State-Name als Kompatibilitätsalias verblieb. Korrektur
  `399f6a6f187d740eb2eb70e2c27bfdc447e3baa4`: **PASS** — genau ein
  `StreamReadState` besitzt Bytefortschritt, Status und Header; der Adapter
  besitzt Öffnen, Header-Abbruch, Response-Handle und deterministisches Cleanup.
  Integriert als `64b46d9`, `9a5f95d` und `61d6b25`.
- Root-Integration `763e596` und `70e2905`: **PASS** — `server.py` ruft weder
  `provider_http.open_interruptibly` noch `provider_http.read_response` direkt
  auf. Leere JSON-Antworten bleiben `None`, Größenlimits bleiben 502, und
  OpenAI-Rate-Limit-Header sowie Status werden auch bei nachfolgendem
  Streamfehler persistiert. Cancellation, Client-Disconnect, Timeout,
  Response-ID-/Delta-Ausgabe und diagnostische Bytezahlen bleiben erhalten.
  Es gibt keine Rückimporte, Server-Fachcallbacks oder Kompatibilitätswrapper.
- `server.py`: 19.863 physische Zeilen und 1.100 verbleibende
  Funktionen/Klassen. Das Inventar enthält 1.547 Einträge; P0 bleibt ohne
  unklare Zuordnung, in P2 bleiben 81 Definitionen und 10 globale Bindungen
  offen. Dieser Schritt verlagert Transportbesitz und entfernt deshalb keine
  zusätzliche Top-Level-Definition.

### Prüfungen

- HTTP-Worker: 27 fokussierte Tests im Root-Nachlauf, PASS; Ruff, PyCompile und
  `git diff --check`: PASS.
- OpenAI-Worker nach den beiden Korrekturrunden: 36 Tests, PASS; Root-Diff- und
  Code-Review, Ruff, PyCompile und `git diff --check`: PASS.
- Integrierte Provider-, Architektur-, Status-, Cancellation- und
  Streamingregressionen: 76 Tests, PASS.
- Vollständiger integrierter Lauf:
  `python -m unittest discover -s tests` — 947 Tests, 12 übersprungen, PASS in
  293,675 s.
- Ruff auf den geänderten Provider- und Provider-Testdateien, Compileall,
  PyCompile, Inventar-Check und `git diff --check`: PASS. Die nicht geänderten
  Altbefunde in der vollständigen Architekturtestdatei bleiben außerhalb dieses
  Diffs.

### Verbleibende Risiken und nächster Schritt

- `http_json` besitzt noch Beobachtung, Fehlerabbildung und Providerstatus in
  `server.py`; OpenAI Request-/Background-Transport samt Polling liegt ebenfalls
  noch dort. P2 ist daher ausdrücklich nicht abgeschlossen.
- Als nächstes werden Status-/Usage-Persistenz und allgemeine HTTP-
  Fehlerorchestrierung an eine konkrete Backend-Schnittstelle gebunden; danach
  folgen OpenAI Request/Retrieve/Cancel in einem kleinen separaten Paket.
- Jede Änderung nach diesem Stand hebt den PASS für den betroffenen Umfang auf;
  vor Merge bleiben Codex-, Sonar-, CodeQL-, Unit-, Container-, Quality- und
  Browser-Gates verbindlich.

## P2.7 — OpenAI- und Gemini-Stream-Reader

- Basis: bestätigter Merge-Commit
  `ab22eefac32fd1ae8c6c6e1b38f313c6a8817b4e` von PR #687; `mergedAt`
  `2026-09-19T19:07:51Z`, Erreichbarkeit auf `origin/develop` und null offene
  Review-Threads bestätigt.
- OpenAI-Worker: geprüfter Commit
  `6f4a994d9b386a2e87e4e1f72564026df0330172`, integriert als `79a61af`.
  Review: **PASS** — SSE-Zeilengrenzen, trailing flush, Delta-/Response-ID-
  Weitergabe, Abbruch und Bytebegrenzung liegen ohne Netzwerk- oder
  Serverabhängigkeit im OpenAI-Adapter.
- Gemini-Worker: geprüfte Commits
  `ea31ae3479a5b947264f5bea0b8302c91151d637` und
  `95da8dc55a9af0bd8830366ab49dc18d9774c6fd`, integriert als `762533c` und
  `65eb354`. Review: zunächst **FAIL**, weil der Header-Abbruchtest das
  Schließen einer verspäteten Response nicht bewies; nach deterministischer
  Close-Assertion **PASS**. Der Adapter besitzt Öffnen, Header-Abbruch,
  Response-Handle, SSE-Lesen, Größenlimit, Akkumulation und Cleanup.
- Geprüfter Root-Integrationscommit `6adfc31`: **PASS** — beide lokalen
  Leseschleifen sowie `_read_openai_stream_response` wurden aus `server.py`
  entfernt. `ProviderResponseTooLarge` erhält den bestehenden 502-Vertrag;
  `StreamReadState` bewahrt gelesene Bytes auch bei Fehlern für redigierte
  Diagnostik. Status-, Usage- und Rate-Limit-Persistenz bleiben außerhalb des
  reinen Readers; es gibt keine Rückimporte oder Server-Callbacks.
- `server.py`: 19.866 physische Zeilen und 1.100 verbleibende
  Funktionen/Klassen. Das Inventar enthält 1.547 Einträge; P2 enthält 81
  Definitionen und 10 globale Bindungen, P0 bleibt bei null. `backend/`
  umfasst 51 Python-Dateien mit 7.308 physischen Zeilen.

### Prüfungen

- OpenAI-Worker: 28 Tests, PASS; Ruff, Compileall und `git diff --check`:
  PASS.
- Gemini-Worker nach Testkorrektur: 24 Tests, PASS; Ruff, Compileall und
  `git diff --check`: PASS.
- Integrierte Provider-/Architekturregressionen: 74 Tests, PASS; zehn
  Server-Regressionen für Stream, Fehler, Abbruch und aktives Handle: PASS.
- Geänderte Provider- und Provider-Testdateien: Ruff PASS; PyCompile,
  Compileall, Inventar-Check und `git diff --check`: PASS.
- Vollständiger integrierter Lauf: 931 Tests, 12 übersprungen, PASS in
  325,249 s.

### Verbleibende Risiken und nächster Schritt

- OpenAI-Request-, Background- und das verbleibende Stream-Öffnen samt
  Statusorchestrierung liegen noch in `server.py`; diese Transportgrenze wird
  als nächster P2-Schritt geschlossen. Gemini-Dialoghistorie folgt abhängig
  von P7 in `coach/conversation.py`.
- Alle externen PR-Gates sind vor Merge verbindlich. Lokale Docker-/E2E-
  Ausführung bleibt vom nicht erreichbaren Docker-Desktop-Daemon abhängig.

## P2.4 — Provider-HTTP-Wire-Aufbau und Usage-Berechnungen

- Basis: bestätigter Korrektur-Merge-Commit
  `ddbd40f53cbf22090a19edfea4cd2015421db8f6` von PR #683; `mergedAt`
  `2026-09-19T17:34:18Z`, Erreichbarkeit auf `origin/develop`, null offene
  Review-Threads sowie erfolgreiche Codex-, Sonar-, CodeQL-, Unit-, Container-,
  Quality- und Browser-Gates bestätigt.
- HTTP-Wire-Worker: geprüfter Commit
  `b990c41532e3e086b77f139acd79af840be957bc`, nach Rebase integriert als
  `531a29a`. Review: **PASS** — JSON-/Raw-Body-Ausschluss, Request-/Headeraufbau,
  ausschließlich Query-Schlüssel im Diagnosekontext sowie gebundener Read mit
  deterministischem Close liegen in `backend/providers/http.py`. Netzwerk,
  Cancellation, Logging und Fehlerprojektion bleiben außerhalb.
- Usage-Worker: geprüfter Commit
  `b6004d21deed622286d8aaf482b3ebcf0755ece3`, nach Rebase integriert als
  `5ada139`. Review: **PASS** — Tagesnormalisierung, providerabhängige
  Tokenzählung und nicht mutierende Akkumulation sind reine Berechnungen ohne
  DB-, Lock-, Zeit-, Log- oder Serverzugriff.
- Geprüfter Integrationscommit `52aeec9`, nach Rebase `47512ca`:
  **PASS** — die drei HTTP-Helfer wurden aus `server.py` entfernt und alle
  Aufrufer auf das Eigentümermodul umgestellt. Usage-Persistenz, `DB_LOCK` und
  die atomare Read-Modify-Write-Transaktion verbleiben beim Server; der neue
  Usage-Adapter erhält ausschließlich bereits gelesene Werte und liefert
  persistierbare Projektionen zurück. Es bestehen weder Rückimporte noch
  Kompatibilitätswrapper oder fachliche Server-Callbacks.
- Architekturkorrektur `9c719c7`: **PASS** — die bereits im Plan festgelegten
  Gemini-Historien-/Attachment-Eigentümer wurden `coach/conversation.py` (P7)
  und die Commit-Validierung `planning/` (P4) zugeordnet. P0 ist damit wieder
  exakt geschlossen; es wurde keine Laufzeitlogik verändert.
- `server.py`: 19.948 physische Zeilen und 1.101 verbleibende
  Funktionen/Klassen. Das Inventar enthält 1.549 Einträge; P0 ist bei null
  unklaren Zuordnungen, in P2 bleiben 85 Definitionen und 10 globale Bindungen
  offen. Diese Restdefinitionen, nicht die reine Zeilenabnahme, bestimmen die
  nächsten P2-Pakete.

### Prüfungen

- HTTP-Wire-Worker: 10 Tests, PASS; eigenes Diff-Review, Ruff, Compileall und
  `git diff --check`: PASS.
- Usage-Worker: 3 Tests, PASS; eigenes Diff-Review, Ruff, Compileall und
  `git diff --check`: PASS.
- Integrierte Provider- und Architekturregressionen nach Rebase: 15 Tests,
  PASS. Zusätzlich wurden vor dem Rebase 14 Serverregressionen für HTTP,
  Cancellation, Response-Close/Redaktion, Rate-Limits, Retry-After sowie
  atomare Usage-Aktualisierung und Lock-Reihenfolge ausgeführt: PASS.
- Vollständiger integrierter Lauf vor dem Rebase: 897 Tests, 12 übersprungen,
  PASS in 242,292 s. Nach Rebase auf PR #683 und der Eigentümerkorrektur:
  897 Tests, 12 übersprungen, PASS in 181,102 s.
- Ruff auf allen geänderten Provider-, Provider-Test- und Inventardateien,
  Compileall, Inventar-Check und `git diff --check`: PASS.

### PR-#684-Korrekturrunde

- SonarCloud auf `3cf9795c273fd42a8c6fd5a528e0f29e77a88da5`: **FAIL** — nach
  der Request-Delegation verblieb in `http_json` die unbenutzte lokale Bindung
  `body = request.data`.
- Korrekturcommit `b912ab5`, nach Rebase als `a821ae4` integriert: **PASS** im
  erneuten Root-Diff- und Code-Review. Nur die tote Bindung wurde entfernt;
  Requestobjekt, Netzwerk-, Cancellation-, Logging- und Fehlerpfade sowie
  öffentliche Schnittstellen bleiben unverändert.
- Provider- und Architekturregressionen: 15 Tests, PASS. Vollständiger Lauf:
  897 Tests, 12 übersprungen, PASS in 175,628 s. Ruff auf den extrahierten
  Provider-, Provider-Test- und Inventardateien, Compileall, Inventar- und
  Diff-Check: PASS. Nach dem Rebase auf den tatsächlich gemergten Stand von
  PR #684 wurden erneut 897 Tests mit 12 Überspringungen in 268,102 s
  erfolgreich ausgeführt; die 15 fokussierten Regressionen und alle genannten
  statischen Checks blieben ebenfalls grün. Der aktualisierte PR-Head benötigt
  erneut sämtliche externen Gates.
- PR #684 wurde zuvor am `2026-09-19T17:49:28Z` auf dem alten Head gemergt;
  Merge-Commit `b4b4138b08abb636241d63e12709806422d60616` ist auf
  `origin/develop` erreichbar und besitzt keine offenen Review-Threads. Der
  separate Sonar-Analysecheck blieb dort rot. Der Korrektur-PR #685 wurde nach
  Root-Review-PASS und erfolgreichen Codex-, Sonar-, CodeQL-, Unit-, Container-,
  Quality- und Browser-Gates am `2026-09-19T18:07:30Z` als Squash gemergt.
  Merge-Commit `158299ce0b8f96b3ae9a88c0c9bc24a1a8c0cf77` ist auf
  `origin/develop` erreichbar; es bestehen null Review-Threads. P2.4 ist damit
  abgeschlossen.

### Verbleibende Risiken und nächster Schritt

- Die externen PR-Gates dieses Pakets bleiben vor dem Merge verbindlich; jede
  weitere Codeänderung erfordert ein erneutes Review des betroffenen Umfangs.
- `http_json` besitzt weiterhin Netzwerk-, Retry-/Cancellation- und
  Statusorchestrierung in `server.py`; vollständige OpenAI-/Gemini-Requests,
  Background-Retrieve/Cancel und Gemini-Konversationshistorie bleiben ihren
  geplanten P2-/P7-Paketen vorbehalten. P2.4 schließt diese Punkte nicht
  vorzeitig als erledigt.
- Docker-/E2E-Ausführung bleibt lokal durch den nicht erreichbaren
  Docker-Desktop-Daemon blockiert; die externen Container-/Browser-Gates sind
  deshalb verbindlich.

## P2.5 — OpenAI-/Gemini-Payload- und Response-ID-Adapter

- Basis: bestätigter Merge-Commit
  `158299ce0b8f96b3ae9a88c0c9bc24a1a8c0cf77` von PR #685; `mergedAt`
  `2026-09-19T18:07:30Z`, Erreichbarkeit auf `origin/develop`, null offene
  Review-Threads und erfolgreiche Codex-, Sonar-, CodeQL-, Unit-, Container-,
  Quality- und Browser-Gates bestätigt.
- OpenAI-Worker: geprüfter Commit
  `03b03f2d4893e9ca0dae84b97dfdb45e5b7448f6`, integriert als `7d91b00`.
  Review: **PASS** — `response_id` validiert ausschließlich Responses-IDs und
  `responses_payload` erzeugt nicht mutierend die öffentlichen Reasoning-,
  Streaming- und Background-/Store-Wirefelder. Keine I/O-, Status-, Usage- oder
  Serverabhängigkeit wurde eingeführt.
- Gemini-Worker: geprüfter Commit `ca5e601`, integriert als `78eba05`.
  Review: **PASS** — `input_parts` besitzt die Responses-zu-Gemini-Konvertierung
  von Text, Data-URL-Medien und Tool-Ergebnissen; `request_payload` besitzt
  Instruktionen, Tool-Choice, JSON-Schema, Tokenbudget und modellabhängige
  Thinking-Konfiguration. Beide Funktionen sind rein und importieren `server`
  weder direkt noch indirekt.
- Geprüfter Integrationscommit `1b2ec71`: **PASS** — `server.py` delegiert alle
  betroffenen OpenAI-Requestpfade einschließlich Background und Stream sowie die
  Gemini-Payload-/Tool-Konvertierung. `_openai_response_id` wurde vollständig
  entfernt; Architekturtests verhindern eine Wiedereinführung. Retry, Polling,
  Cancellation, Netzwerkzugriff, Status-/Usage-Persistenz und Locks bleiben bei
  ihren bisherigen Eigentümern. Gemini-Historienauswahl und atomare Speicherung
  bleiben bis P7 in der vorhandenen Orchestrierung; es gibt keine Rückimporte,
  Kompatibilitätswrapper oder fachlichen Provider-Callbacks.
- Externes Sonar-Gate auf `46fd2bc`: **FAIL** — neue Cognitive-Complexity-
  Befunde in `_gemini_request_payload`, `gemini.input_parts` und
  `gemini.request_payload`. Der Luna-Korrekturcommit `a007afe`, integriert als
  `c2ecfbb`, zerlegt ausschließlich die beiden reinen Gemini-Adapter; Root-
  Diff-Review: **PASS**. Der Root-Korrekturcommit `729ba23` zerlegt die
  serverseitige Historien-, Last-User- und Call-Name-Vorbereitung, ohne deren
  Persistenz oder Provider-I/O zu verschieben; Integrationsreview: **PASS**.
- `server.py`: 19.917 physische Zeilen und 1.103 verbleibende
  Funktionen/Klassen. Das Inventar enthält 1.551 Einträge; P0 bleibt bei null
  unklaren Zuordnungen, in P2 bleiben 87 Definitionen und 10 globale Bindungen.
  `backend/` umfasst 51 Python-Dateien mit 7.025 physischen Zeilen; die
  Verlagerung wird damit nicht allein über entfernte Serverzeilen bewertet.

### Prüfungen

- OpenAI-Worker: 22 Tests, PASS; Root-Diff-Review, Ruff, Compileall und
  `git diff --check`: PASS.
- Gemini-Worker: 17 Tests, PASS; Root-Diff-Review, Ruff, Compileall und
  `git diff --check`: PASS.
- Sonar-Korrektur: 17 Gemini-Adaptertests beim Worker sowie 41 integrierte
  Gemini-Provider-, Anhang- und Historienregressionen beim Root, PASS. Ruff auf
  `backend/providers/gemini.py`, Compileall und `git diff --check`: PASS.
- Integrierte Provider-, Anhang-, Historien-, Background-, Retry- und
  Architekturregressionen: 65 Tests, PASS in 6,168 s.
- Vollständiger integrierter Lauf: 906 Tests, 12 übersprungen, PASS in
  322,222 s. Ruff auf den geänderten Provider- und Provider-Testdateien,
  Compileall, Inventar-Check und `git diff --check`: PASS. Die fünf bei einem
  zusätzlichen Ruff-Lauf sichtbaren Befunde in `tests/test_server_architecture.py`
  bestanden bereits vor diesem Paket und wurden nicht durch sachfremde
  Formatierungsänderungen vermischt.
- Vollständiger Wiederholungslauf nach der Sonar-Korrektur: 906 Tests, 12
  übersprungen, PASS in 220,295 s; Architekturtest und Inventar-Check ebenfalls
  PASS. Damit ersetzt dieser Lauf den zuvor geprüften Code-Stand als aktuelles
  Root-Review-Gate für P2.5.

### Verbleibende Risiken und nächster Schritt

- P2 ist noch nicht abgeschlossen: `http_json`, OpenAI-Request-/Background- und
  Stream-Transport, Gemini-Stream-Transport sowie die verbleibenden Garmin-/
  Intervals-Adapter besitzen weiterhin fachliche Definitionen in `server.py`.
- Persistierte Gemini-Dialoghistorie bleibt gemäß Plan Eigentum von P7 und wird
  nicht in das Provider-Modul verschoben.
- Lokale Docker-/E2E-Ausführung bleibt durch den nicht erreichbaren
  Docker-Desktop-Daemon blockiert. Vor einem Merge bleiben daher die externen
  Container-, Browser-, Sonar-, CodeQL- und Codex-Gates verbindlich.

### Abschließendes externes Gate und Merge

- Der korrigierte Head `43a6ad1aff241cf271d4eca1e0e85b60a3f4a053`
  bestand Codex, SonarCloud, CodeQL, vier Test-Shards, Container-Unit-Tests,
  Quality-Baseline sowie Browser-/Accessibility-Checks; es bestanden null
  Review-Threads. PR #686 wurde am `2026-09-19T18:39:52Z` gemergt.
- Merge-Commit `a2ba01341a60d7864b7b72d18672c5b51a367e98` ist auf
  `origin/develop` erreichbar. P2.5 ist damit abgeschlossen.

## P2.6 — Abbrechbarer Provider-HTTP-Transport

- Basis: bestätigter Merge-Commit
  `a2ba01341a60d7864b7b72d18672c5b51a367e98` von PR #686.
- Luna-Worker: geprüfter Commit
  `c4e77104052f1edc17bcd25e82b47856da698f47`, integriert als `d3f4a92`.
  Review: **PASS** — `ProviderRequestCancelled`, `open_interruptibly` und
  `read_response` besitzen das abbrechbare Header-Warten, Late-Response-Cleanup,
  begrenzte Reads und den temporären Response-Handle. Das Modul importiert
  `server` nicht, besitzt keinen globalen Laufzeitzustand und verändert weder
  Retry- noch Statuspolitik.
- Geprüfter Root-Integrationscommit `ccf925e`: **PASS** — die Server-Wrapper
  `_urlopen_interruptibly` und `_read_http_response` wurden entfernt. `http_json`
  und Gemini-Streaming delegieren direkt an den Transportadapter; `server.py`
  übersetzt nur das neutrale Abbruchsignal in den bestehenden 499-Vertrag und
  behält Logging, Providerstatus und Fehlerprojektion. Architekturtests sperren
  die entfernten Symbole gegen Wiedereinführung.
- SonarCloud auf `60b577ef7b750ea27bfd2b0e8096c4cdc8d73b74`:
  **FAIL** — Cognitive Complexity 21 in `open_interruptibly` und ein zu breiter
  `BaseException`-Catch. Der Korrekturcommit desselben Luna-Workers
  `748e025ddd63ee7381fcf3c40e1265be03a9ab28`, integriert als `b764afd`,
  kapselt den Thread-Zustand in `_OpenState`, zerlegt Worker und Abbruch-Cleanup
  und fängt nur reguläre `Exception`; erneutes Root-Diff-Review: **PASS**.
- Der Inventargenerator ordnet `_gemini_request_history`,
  `_gemini_last_user_text` und `_gemini_call_names` nun explizit P7
  `coach/conversation.py` zu. Damit bleibt P0 stabil bei null, statt durch
  wechselnde Heuristikkandidaten wieder unklar zu werden.
- `server.py`: 19.895 physische Zeilen und 1.101 verbleibende
  Funktionen/Klassen. Das Inventar enthält 1.548 Einträge; P2 enthält 82
  Definitionen und 10 globale Bindungen. `backend/` umfasst 51 Python-Dateien
  mit 7.186 physischen Zeilen.

### Prüfungen

- Luna-Worker: 20 Tests, PASS; Root-Diff-Review, Ruff, Compileall und
  `git diff --check`: PASS.
- Sonar-Korrektur: 20 Provider-HTTP-Tests beim Worker und beim Root, PASS;
  Ruff, Compileall und `git diff --check`: PASS.
- Integrierte Provider-HTTP-, Cancellation-, Gemini-Stream- und
  Architekturregressionen: 27 Tests, PASS. Ruff auf den geänderten Provider-
  und Provider-Testdateien, Compileall, Inventar-Check und `git diff --check`:
  PASS.
- Vollständiger integrierter Wiederholungslauf nach der Sonar-Korrektur:
  916 Tests, 12 übersprungen, PASS in 215,023 s.

### Verbleibende Risiken und nächster Schritt

- `http_json` besitzt weiterhin Logging, Providerstatus, Retry- und
  Fehlerorchestrierung in `server.py`; OpenAI-Request-, Background- und
  Stream-Transport sowie Gemini-Stream-Transport sind ebenfalls noch offen.
- Der vollständige Testlauf und alle externen PR-Gates sind vor einem Merge
  verbindlich. Lokale Docker-/E2E-Ausführung bleibt vom nicht erreichbaren
  Docker-Desktop-Daemon abhängig.

## P2.3 — OpenAI-SSE und Gemini-Stream-Akkumulation

- Basis: bestätigter Merge-Commit
  `7bbba03232366412a08ef03f095217116f3ffee1` von PR #681; `mergedAt`
  `2026-09-19T17:08:53Z`, Erreichbarkeit auf `origin/develop` und null offene
  Review-Threads bestätigt.
- OpenAI-SSE-Worker: geprüfter Commit
  `61731158dc8ce92d789e4fc95095594e1af3265c`, integriert als `78b7edf`.
  Review: **PASS** — fragmentierte Mehrzeilen-Events, `[DONE]`, Delta- und
  Response-ID-Weitergabe sowie alle finalen Response-Zustände werden im
  OpenAI-Adapter interpretiert; ungültiges JSON und Nicht-Objekte liefern den
  bestehenden redigierten `invalid_response`-Vertrag.
- Gemini-Stream-Worker: geprüfter Commit
  `b7cdbe4c46b4b3ea3919e9f26358c3f1929e3dda`, integriert als `5b68305`.
  Review: **PASS** — der Adapter besitzt den vollständigen Akkumulatorzustand,
  erhält Usage-/Modell-/Safety-/Citation-Metadaten und alle Kandidaten und
  koalesziert Textteile nur bei identischer Part-Metadatenstruktur.
- Geprüfter integrierter Code-Commit nach Rebase: `edf5e53`.
  Integrationsreview: **PASS** — vier OpenAI-SSE-Helfer und die gesamte
  Gemini-Chunk-Merge-Logik wurden aus `server.py` entfernt. Der Server besitzt
  weiter nur I/O, Cancellation, Byte-Limit, Status-/Usage-Persistenz und
  Stream-Lifecycle; Delta-/Response-ID-Callbacks sind reine Ausgabesenken und
  tragen keine ausgelagerte Fachlogik. Es gibt keine Rückimporte oder
  Kompatibilitätswrapper; Architekturtests sperren die neuen Eigentümer.
- `server.py`: 20.037 physische Zeilen und 1.104 verbleibende
  Funktionen/Klassen. Das Inventar enthält 1.551 Einträge; P0 bleibt ohne
  unklare Zuordnung, in P2 bleiben 99 Definitionen und 10 globale Bindungen
  offen.

### Prüfungen

- OpenAI-SSE-Worker: 15 Tests, PASS; eigenes Diff-Review, Ruff, Compileall und
  `git diff --check`: PASS.
- Gemini-Stream-Worker: 13 Tests, PASS; eigenes Diff-Review, Ruff, Compileall
  und `git diff --check`: PASS.
- Integrierte Provider-, Architektur-, Cancellation- und
  Streamingregressionen: 37 Tests, PASS.
- Vollständiger integrierter Lauf vor dem finalen Rebase:
  `python -m unittest discover -s tests` — 888 Tests, 12 übersprungen, PASS in
  194,113 s.
- Vollständiger Lauf nach Rebase auf den bestätigten PR-#681-Mergecommit:
  `python -m unittest discover -s tests` — 888 Tests, 12 übersprungen, PASS in
  257,471 s.
- Ruff auf den betroffenen Provider- und Provider-Testdateien, Compileall,
  Inventar-Check und `git diff --check`: PASS.

### PR-#682-Korrekturrunde

- SonarCloud auf `a8e546c5d3ff1cf593ca9092c7af114d55a78f3c`: **FAIL** —
  `StreamAccumulator._merge_chunk` und `consume_sse_event` überschritten mit
  47 beziehungsweise 17 die erlaubte kognitive Komplexität 15.
- Korrekturcommit `27301f4`, nach Rebase als `ea11c91` integriert: **PASS** im
  erneuten Root-Diff- und Code-Review. Ausschließlich private Parserteilschritte
  wurden getrennt; öffentliche API, Eventreihenfolge, Delta-/Response-ID-Ausgabe,
  Metadatenaggregation und Fehlerverträge bleiben unverändert.
- Provider- und Architekturregressionen: 32 Tests, PASS. Vollständiger Lauf:
  888 Tests, 12 übersprungen, PASS in 183,539 s. Ruff, Compileall und
  `git diff --check`: PASS. Nach Rebase auf den bestätigten Merge-Commit von
  PR #682: erneut 32 gezielte Tests sowie 888 Tests, 12 übersprungen, PASS in
  181,716 s; Ruff, Compileall, Inventar- und Diff-Check: PASS. Der aktualisierte
  PR-Head benötigt erneut alle externen Gates.
- PR #682 wurde zuvor am `2026-09-19T17:22:31Z` auf dem alten Head gemergt;
  Merge-Commit `3e1dd708398a3a5fc8bcd6c1ef16f638fb9aeb8f` ist auf
  `origin/develop` erreichbar und besitzt keine offenen Review-Threads. Der
  separate Sonar-Analysecheck blieb dort rot. Folge-PR #683 wurde am
  `2026-09-19T17:34:18Z` mit Merge-Commit
  `ddbd40f53cbf22090a19edfea4cd2015421db8f6` gemergt und ist auf
  `origin/develop` erreichbar; null Review-Threads sowie erfolgreiche Codex-,
  Sonar-, CodeQL-, Unit-, Container-, Quality- und Browser-Gates sind bestätigt.

### Verbleibende Risiken und nächster Schritt

- Die externen PR-Gates dieses Pakets bleiben vor dem Merge verbindlich. Die
  finalen Gates von PR #681 einschließlich Browser-/Accessibility-Lauf
  `35456920160` sind vollständig grün.
- HTTP-Orchestrierung, vollständige OpenAI-/Gemini-Requests und Background-
  Lifecycle bleiben P2; die separat geprüften HTTP-Wire- und Usage-Bausteine
  werden im nächsten kleinen Paket integriert.
- Nächster Schritt ist ein kleiner, unabhängiger P2-Transportbaustein; danach
  werden dessen Serveraufrufer sequenziell integriert und erneut vollständig
  geprüft.

### PR-#680-Korrekturrunde

- Externe Analyse des geprüften Stands `e9eedded46d9f7626927b286ed7b383281575c6c`:
  **FAIL** — Sonar meldete sechs Cognitive-Complexity-Befunde im neuen
  Kalenderparser und ein vierfaches Eigentümerliteral im Inventargenerator;
  CodeQL meldete einen nicht allowlist-projizierten Stream-Fehlergrund im
  strukturierten Log.
- Kalender-Korrekturcommit des ursprünglichen Workers:
  `35d4e289e1f066aa22ce16b390e09be90959ca20`, integriert als `1a1e2c1`.
  Eigenes Diff-Review: **PASS** — die sechs Funktionen wurden in kleine reine
  Hilfsfunktionen zerlegt. COUNT-/UNTIL-Reihenfolge, Exception-Unterdrückung,
  Recurrence-Grenzen, Zeitzonen, Fehlertexte und öffentliche Schnittstelle
  bleiben unverändert; keine Rückimporte oder Server-Callbacks.
- Integrationskorrektur `e3883d8`: **PASS** — der Loggrund wird unmittelbar
  vor dem strukturierten Log über eine statische Allowlist projiziert;
  bekannte Timeout-/Cancellation-/Response-Gründe bleiben erhalten,
  unbekannter Text wird `http_error`. Der Inventareigentümer
  `sync/reconcile.py` besitzt nun eine einzelne Konstante.
- Geprüfter integrierter Stand: `1a1e2c1`. Vollständiger Lauf
  `python -m unittest discover -s tests` — 871 Tests, 12 übersprungen, PASS
  in 181,550 s. Provider-/Log-Korrekturtests: 25 Tests, PASS. Ruff auf allen
  betroffenen Provider-, Test- und Inventardateien, Compileall,
  Inventar-Check und `git diff --check`: PASS.
- Lokale Sonar-Dateianalyse für `backend/providers/calendar.py`,
  `scripts/server_extraction_inventory.py` und `server.py`: keine Befunde;
  der CLI-Gesamtcode ist ausschließlich wegen nicht verfügbarer optionaler
  Vortex-Analyse ungleich null. Der aktualisierte PR-Head benötigt erneut die
  vollständigen GitHub-, Sonar- und Codex-Gates.
- CodeQL auf `7311ca4`: erneut **FAIL** — die Allowlist gab erlaubte Werte als
  dasselbe Eingabeobjekt zurück, sodass der Taint-Fluss formal bis zum Log
  bestehen blieb. Korrektur: ausschließlich statische Mapping-Werte werden
  zurückgegeben; nicht-stringartige und unbekannte Eingaben werden
  `http_error`. Der betroffene Sicherheitsumfang wird nach dem neuen Commit
  erneut geprüft.
- Codex-Review auf `1cab17f`: **FAIL** — die bereits statisch projizierte
  Kategorie `usage_limit_exceeded` war bei einer zweiten Projektion nicht
  idempotent und fiel auf `http_error` zurück. Korrekturcommit
  `1390aefc50d24e7be26649ab8742c3267f3b5f8a`: **PASS** — ausschließlich der
  statische Kategorienwert wurde ergänzt; unbekannte Werte bleiben redigiert.
  Provider- und Serverregressionen: 11 Tests, PASS; vollständiger Lauf: 871
  Tests, 12 übersprungen, PASS in 180,945 s. Ruff, Compileall und Diff-Check:
  PASS.
- PR #680 wurde am `2026-09-19T16:53:42Z` als Squash gemergt. Merge-Commit
  `de078fa0439af897b3fc25c4f0cdbf926bfa626a` ist auf `origin/develop`
  erreichbar; Review-Threads sind aufgelöst. CodeQL, Codex, Unit-, Shard-,
  Container- und Quality-Gates waren beim Merge grün; der nachgelagerte
  Browser-/Accessibility-Job wurde separat bis zum Abschluss beobachtet.

## P2.2 — Kalendertransport, Provider-HTTP und Audio/OpenAI-Hilfen

- Basis: bestätigter Merge-Commit
  `de078fa0439af897b3fc25c4f0cdbf926bfa626a` von PR #680; `mergedAt`
  `2026-09-19T16:53:42Z`, Erreichbarkeit auf `origin/develop` und aufgelöste
  Review-Threads bestätigt.
- Kalendertransport-Worker: geprüfter Commit
  `9b670cfad5d15c3c8677f79d06d857c45f581cf6`, integriert als `e6fa07e`.
  Review: **PASS** — URL-, DNS-, SSRF- und IP-Revalidierung, gepinntes
  Verbindungsziel mit ursprünglichem TLS-SNI/Host, TLS >= 1.2, Gesamtdeadline,
  5-MB-Grenze, begrenzter Retry, deterministisches Cleanup und redigiertes
  Fehlerlogging liegen vollständig in `backend/providers/calendar.py`.
- OpenAI-/Audio-Worker: geprüfter Commit
  `d154f111d69291db6d104fca6a7f08635e881611`, integriert als `ed23144`.
  Review: **PASS** — Endpoint-Zusammensetzung, Multipart-Encoding sowie
  Audio-MIME-/Suffix-Normalisierung sind reine Provider-Hilfen ohne Zugriff
  auf `server.py`, globale Serverzustände oder externe Provider.
- Geprüfter integrierter Code-Commit nach Rebase: `63283c2`.
  Integrationsreview: **PASS** — die bisherigen Kalendertransport-,
  OpenAI-Endpoint-, Multipart- und Audio-Kompatibilitätswrapper wurden aus
  `server.py` entfernt. Sämtliche Aufrufer verwenden die Eigentümermodule
  direkt; Test-Patch-Ziele wurden auf diese Module migriert. Kalender-Sync
  behält Parse-before-delete, Transaktion und den letzten guten Datenstand.
  Architekturtests verbieten die Rückkehr aller entfernten Symbole.
- `server.py`: 20.129 physische Zeilen und 1.108 verbleibende
  Funktionen/Klassen. Das Inventar enthält 1.555 Einträge; P0 bleibt bei null
  unklaren Zuordnungen, in P2 bleiben 103 Definitionen und 10 globale
  Bindungen offen. Der fachliche Eigentümerwechsel, nicht die Zeilenabnahme,
  ist das Abnahmekriterium.

### Prüfungen

- Worker-Kalendertransport: 20 Tests, PASS; eigenes Diff-Review, Ruff,
  Compileall und `git diff --check`: PASS.
- Worker-OpenAI/Audio: 18 Tests, PASS; eigenes Diff-Review, Ruff, Compileall
  und `git diff --check`: PASS.
- Integrierte Provider-, Aufrufer- und Architekturregressionen: 46 Tests,
  PASS in 1,460 s.
- Vollständiger integrierter Lauf: `python -m unittest discover -s tests` —
  878 Tests, 12 übersprungen, PASS in 174,419 s.
- Nach Rebase auf den bestätigten PR-#680-Mergecommit: vollständiger Lauf —
  878 Tests, 12 übersprungen, PASS in 185,179 s.
- `ruff check` für alle geänderten Provider-, Provider-Test- und
  Inventardateien, Compileall, Inventar-Check und `git diff --check`: PASS.

### Verbleibende Risiken und nächster Schritt

- Die nach dem Rebase erneut ausgeführten Prüfungen und externen PR-Gates sind
  vor dem Merge des Pakets verbindlich; jede weitere Änderung hebt diesen PASS
  für den betroffenen Umfang auf.
- SSE-Verarbeitung und Gemini-Stream-Akkumulation sind separat geprüft, aber
  absichtlich noch nicht integriert; sie folgen als eigenes P2-Paket, damit
  Schreibbereiche und Reviewumfang klein bleiben.
- Docker-/E2E-Ausführung bleibt lokal durch den nicht erreichbaren
  Docker-Desktop-Daemon blockiert; die externen PR-Gates bleiben verbindlich.
## P6.4 — Wetter, vollständiger Provider-Resync und externer Kalender

- Wetter-Service und Komposition: geprüfter Commit `efedc6b03be2e4d0a8a03ecee328888c4863978f`.
  Review: **PASS** — `WeatherSyncService` besitzt den beobachteten Refresh samt
  Adaptive-Preview-Projektion; der frühere Server-Einstieg ist entfernt und
  Architekturtests verhindern seine Rückkehr.
- Full-Resync-Worker: `a9526120a00c3ca53886dce1c8f8c79e310b9d55`,
  integriert als `44d6033`; Server-Komposition `42d6025`. Das erste integrierte
  Review war **FAIL**: `state()` öffnete pro Provider einen separaten Reader
  und verletzte die bestehende Bootstrap-/Public-State-Verbindungsgrenze.
  Korrekturcommit `37b7592`: **PASS** — die Projektion kann die aktive
  caller-owned Unit-of-Work wiederverwenden und verwendet außerhalb davon
  genau einen Reader. Gates, Fehlerredaktion, Cleanup und der letzte gute
  Providerzustand bleiben erhalten.
- External-Calendar-Worker: initial `79ced3dfef0202701e30cae28e0e716e12c3807f`:
  **FAIL** — Observer-/Konfigurationsreihenfolge und Fehler-/Cleanup-Propagation
  wichen vom bestehenden Vertrag ab. Korrektur desselben Workers
  `94e16e8156c5b386bcc601afa5293e45769e5ed9`, integriert als `8eb3c36`:
  **PASS**. Die Root-Komposition `e44a5ff` ist ebenfalls **PASS**; atomarer
  Parse-before-delete-Ersatz, Redaction, Daily-Marker, Adaptive Preview,
  Module-Lock und öffentliche Running-Projektion besitzen nun den konkreten
  Backend-Service. `server.py` enthält weder den Ablauf noch einen Wrapper.

### Prüfungen

- Wetter: 8 neue/Architekturtests, 3 Server-/Auditregressionen und anschließend
  462 Server-Tests, 3 übersprungen, PASS.
- Full Resync nach Korrektur: 11 Service-Tests plus 2
  Verbindungsregressionen, 9 Architektur-/Resync-Vertragstests und 462
  Server-Tests, 3 übersprungen, PASS in 81,048 s. Ruff, Format, Compile und
  `git diff --check`: PASS.
- Externer Kalender: 9 isolierte Worker-Tests; 17 integrierte Kalender-,
  Architektur- und Datenschutzregressionen; 462 Server-Tests, 3 übersprungen,
  PASS in 84,506 s. Ruff, Format, Compile und `git diff --check`: PASS.
- Geprüfter integrierter Stand: `e44a5ffbb268dc413267efe67a9718daef333feb`.
  `server.py`: 8.768 physische Zeilen. Das Inventar wird nach Abschluss des
  noch offenen konkreten Job-Executors erneut erzeugt.

### Verbleibende Risiken und nächster Schritt

- Der konkrete Sync-Job-Dispatch und seine Competition-/Maintenance-
  Verdrahtung liegen noch in `server.py`; `SyncJobWorker` besitzt bereits den
  Thread-Lifecycle. Dieser Rest wird als nächster P6-Baustein ohne
  Server-Callbacks komponiert.
- Die abschließende P6-Prüfung für Konflikte, Remote-Readback, Tombstones und
  lokale Dirty-Zustände bleibt offen.

## P6.5 — Konflikt-, Readback- und Dirty-State-Audit

- Geprüfter Stand: `50e2449dcf7d935cf2df0e2fe177156e31eec89d` plus unveränderte Sync-Implementierungen aus dem
  integrierten P6-Verlauf. Review: **PASS**.
- `RemotePlannedUnitReconciler` verwendet compare-and-swap gegen sämtliche
  gelesenen Zeilenfelder, begrenzt Remote-Missing auf das tatsächlich gelesene
  Kalenderfenster, erhält lokale Dirty-Payloads als Konflikt und bump't die
  Planrevision innerhalb derselben Unit-of-Work.
- Library-Reconciliation überschreibt keine offenen lokalen Zustände; saubere
  fehlende Remoteobjekte werden als `remote_missing` markiert, Dirty-Zeilen
  bleiben retry-/konfliktfähig. Remote-Identitäten werden vor nachgelagerter
  Ergebnisvalidierung gesichert.
- Competition-Read-Sync führt keine Remote-Mutation aus. Tombstones werden nur
  bei explizitem `push_local=True` remote gelöscht und erst nach erfolgreichem
  Delete mit ID plus Erstellzeit lokal entfernt; Dirty-Abweichungen und
  fehlende Remoteobjekte bleiben Konflikte.
- Planned-Calendar-Push und Repair teilen den per-ID-Lock und prüfen lokalen
  Payload-Hash, Remote-Identität, freie zukünftige Planung sowie abschließenden
  Readback. Ein zwischenzeitlicher lokaler Edit gewinnt; fehlerhafte Readbacks
  behalten die bereits erhaltene Remote-ID für einen sicheren Retry.

### Prüfungen

- `python -m unittest tests.test_sync_competitions tests.test_sync_planned_units
  tests.test_sync_library tests.test_sync_selected
  tests.test_sync_planned_calendar` — 107 Tests, PASS in 4,992 s.
- Verbleibendes P6-Risiko ist ausschließlich die noch nicht integrierte
  konkrete Job-Executor-/Worker-Komposition; der geprüfte Konfliktumfang selbst
  hat keine offenen Befunde.

## P6.6 — Konkreter Job-Executor und Worker-Komposition

- Luna-Worker-Commit `36e1bb936396052471c8dc808065b33e69030ed5`,
  integriert als `61e0f1798f021879109e951c26755fb289992512`:
  **PASS** im tatsächlichen Diff- und Code-Review. `SyncJobExecutor` besitzt
  Providerdispatch, normalisierte Persistenz-Envelopes, historische Fenster,
  Competition-Observation/-Gate, Garmin-Fixture-/Morning-Regeln sowie Outcome-
  und Backfill-Folgejob-Orchestrierung. Das Modul importiert `server.py` nicht
  und erhält keine fachlichen Server-Callbacks.
- Root-Komposition und Entfernung der alten Server-Abläufe:
  `6171175f5a1909676fe53b030f8fa8a77c27666b`: **PASS**. `SyncJobWorker`
  besitzt Thread, Start-Lock, Stop und Wakeup; Queue, Outcome und Worker teilen
  genau das modul-eigene Wake-Event. Claim und Ausführung laufen innerhalb
  derselben Maintenance-Operation. Elf frühere Sync-Job-Funktionen, drei
  Server-Events/-Locks und der Competition-Wrapper sind entfernt; alle
  Produktions- und Testaufrufer verwenden die konkreten Eigentümer.
- Das erste integrierte Gesamtgate war **FAIL**: Der Full-Resync-Gate-Test
  verwendete nach Entfernung des Competition-Wrappers den inneren Service und
  erreichte dadurch den gemockten Provider (502 statt erwartetem 409).
  Korrektur im selben Root-Integrationsstand: Der Test ruft den realen
  `SyncJobExecutor` auf und prüft damit wieder die produktive Gate-Grenze.
  Erneutes Review: **PASS**.

### Prüfungen

- Executor, Worker und Architektur: 21 Tests, PASS. Vier migrierte Audit-,
  Diagnose-, Provider- und Repair-Module: 83 Tests, 2 übersprungen, PASS.
- Integrierter Server-/Providerumfang: 477 Tests, 4 übersprungen, PASS in
  96,217 s. Vollständige Suite: 2.040 Tests, 12 übersprungen, PASS in
  228,860 s.
- Ruff und Formatprüfung für die neuen Executor-/Worker-Dateien, Compile für
  `server.py` und `backend/`, Inventargenerator/-Check sowie
  `git diff --check`: **PASS**.

### Verbleibende Risiken und nächster Schritt

- Regeneriertes Inventar auf `6171175`: `server.py` 8.624 physische Zeilen,
  788 Einträge und 398 Funktionen/Klassen. Die heuristische P6-Zuordnung weist
  64 Funktionen/Klassen und 24 globale Bindungen aus; darunter liegen
  Composition-Root-Fabriken und späteren Coach-Phasen zuzuordnende Funktionen,
  die vor dem P6-Abschluss einzeln geprüft und umklassifiziert werden müssen.
- Tatsächlich verbleibende P6-Fachlogik umfasst mindestens Garmin-/Sync-
  Public-State und Garmin-Coach-Projektion, adaptive Krankheitspausen-
  Remote-Synchronisierung sowie strukturierte Refresh-, Plan-Sync-, Retry- und
  Konfliktbefehlsorchestrierung. Diese Pakete werden als kleine, getrennte
  Backend-Eigentümer umgesetzt; P6 bleibt bis dahin offen.

## P6.7 — Manuelle Phasenzuordnung des Restinventars

- Geprüfter Commit `77303bac23b15dd42d09965b17f4f66e6a0d8705`: **PASS**.
  Die tatsächlichen Composition-Root-Fabriken für konkrete Sync-Dienste,
  Repositories, Worker und Clients sind nun P11 zugeordnet. Coach-Job- und
  Tool-Ausführung ist P7/P8, Sync-HTTP-Routen und das Library-Seitenlimit sind
  P10. Die vorherige Namensheuristik hatte diese Einträge fälschlich P6
  zugerechnet; an Produktionscode oder Laufzeitverhalten wurde nichts geändert.
- Das regenerierte Inventar enthält null unklare P0-Zuordnungen. P6 umfasst
  jetzt 24 Funktionen/Klassen und 18 globale Bindungen statt heuristisch 64
  beziehungsweise 24. Diese Reduktion ist ausschließlich eine präzisere
  Eigentumszuordnung und wird nicht als Fachlogik-Auslagerung gewertet.

### Prüfungen

- `python scripts/server_extraction_inventory.py` und
  `python scripts/server_extraction_inventory.py --check` — PASS.
- `python -m py_compile scripts/server_extraction_inventory.py`,
  `ruff check scripts/server_extraction_inventory.py` und
  `git diff --check` — PASS.

### Verbleibende Risiken und nächster Schritt

- P6 bleibt wegen der 24 tatsächlich zu prüfenden Definitionen sowie Garmin-/
  Sync-Projektion, Krankheitspausen-Remote-Sync und strukturierter Sync-
  Orchestrierung offen. Die beiden voneinander unabhängigen Projektionsdienste
  werden als nächste integrierte Stände geprüft.

## P6.8 — Garmin- und Sync-Public-State

- Garmin-Worker `edcdbe5` war im Code-Review zunächst **FAIL**: falscher
  Factory-Typ und Writer-UOW für eine reine Projektion. Korrektur `18ebce2`
  nach erneutem Diff-Review **PASS**; integriert als `5c08f9a`, `2439666`,
  Root-Verdrahtung `e6eac49`. Die beiden Server-Fachfunktionen sind entfernt.
  42 fokussierte Tests (1 übersprungen) **PASS**.
- Sync-Public-State-Worker `01ca17b` war zunächst **FAIL**: inkonsistenter
  Reader/Writer-Snapshot und Rückimport aus `http_api`. Korrektur `b470c7b`
  nach erneutem Review **PASS**; integriert als `5544bc4`, `6794342`,
  Root-Verdrahtung `5a36cbd`. Vier Server-Fachfunktionen sind entfernt.
  Acht Service-, drei Architektur- und zwei Server-Status-Tests **PASS**.
- Integrationsregression in `public_bootstrap`/`public_state` beim späteren
  Server-Testlauf: Reader öffnete innerhalb aktiver UOW bis zu 14 statt 1–2
  Verbindungen. **FAIL** im Stand vor der Korrektur; `DatabaseManager.reader`
  verwendet nun die aktive UOW und sieht denselben Transaktionssnapshot.
  Sieben Manager-/Verbindungs-Regressionstests **PASS**; erneuter kompletter
  `tests.test_server`-Lauf: 462 Tests, drei übersprungen, **PASS**. Gesamtsuite
  steht aus.

## P6.9 — Lokale Planungsautorität vor explizitem Sync

- Worker `ca218e3`, integriert als `ca0a53a`, im tatsächlichen Diff-Review
  zunächst **FAIL**: ungültiges JSON und erneute Autoritätswahl änderten die
  bisherige Schreib-/Revisionssemantik. Root-Integration stellt beide
  Verhaltensverträge wieder her, entfernt fünf Server-Fachdefinitionen und
  migriert Produktions- und Testaufrufer auf `PlanningAuthorityService`.
  Elf fokussierte Dienst-/Architekturtests, 141 Coach-/Repair-Tests und sieben
  DB-/Verbindungstests **PASS**. Der Server-Gesamttest war vor dem Reader-Fix
  wegen zweier Verbindungszählungs-Regressionen **FAIL**; die Wiederholung
  nach dem Reader-Fix mit 462 Tests (drei übersprungen) ist **PASS**.
  Tatsächlicher Code- und Diff-Review dieses integrierten Stands: **PASS**;
  die vollständige Suite steht noch aus.

### Nächster Schritt

Zuerst die Gesamtsuite nach der Reader-Korrektur wiederholen,
anschließend die beiden GPT-6-Luna-P6-Worker-Patches sequenziell integrieren,
den betroffenen Code erneut reviewen und Inventar/Checkliste aktualisieren.

## P6.10 — Krankheitspausen-Sync (GPT-6 Luna)

- Worker `9aa7e08` im tatsächlichen Diff-Review zunächst **FAIL**:
  Whitespace-only-Krankheitsangabe wurde entgegen dem bisherigen Vertrag
  wieder zu `Krankheit` normalisiert. Korrektur `93116d1` geprüft: **PASS**.
  Sequenziell als `4d1a9f8` und `71c7cb2` integriert; Root entfernt die drei
  Server-Fachfunktionen einschließlich Ergebnisorchestrierung und migriert
  den Coach-Aufrufer auf `IllnessPauseSyncService.apply`. Auth bleibt vor dem
  Aufruf, Remote-Write erfordert weiter `sync_illness_to_intervals=True`.
- Der integrierte Diff- und Code-Stand ist **PASS**: keine Server-Rückimporte,
  keine fachlichen Server-Callbacks; lokale Revision/Transaktion/Rollback
  bleiben beim `AdaptiveReplanApplyService`. 82 Dienst-, Coach-, Repair-,
  Architektur- und Server-Regressionstests **PASS**; Compile, Inventar-Check
  und `git diff --check` **PASS**. Die vollständige Suite steht aus.

## P6.11 — Strukturierte Provider-Refresh-Befehle (GPT-6 Luna)

- Worker `7c4557b`, sequenziell integriert als `21cc23c`, im tatsächlichen
  Diff- und Code-Review **PASS**. `ProviderRefreshCommandService` besitzt
  Queue, synchronen Intervals-Read, Wait-for-existing, begrenzten Retry,
  Busy-Fehler und Cancellation-Weitergabe. Vier Server-Fachdefinitionen sind
  entfernt. Die Autorisierungs- und Scope-Prüfung bleibt unmittelbar vor dem
  konkreten Dienstaufruf; nur ein erfolgreich gequeueter Job erhält eine
  turn-lokale `sync_job_id`.
- 28 Dienst-/Coach-/Architekturtests und 27 Coach-Tool-/Server-Tests **PASS**.
  Inventargenerator/-Check und `git diff --check` **PASS**. P0-Zuordnung
  bleibt null; acht P6-Funktionen/Klassen sind noch offen. Vollständige Suite
  und integrierter Server-Test stehen noch aus.

### Gesamtsuite nach P6.11

- `python -m unittest discover -s tests` — 2.076 Tests, 12 übersprungen,
  zunächst **FAIL** mit zwei veralteten Testreferenzen auf die entfernte
  Server-Funktion `apply_adaptive_replan` und die verschobene
  `ILLNESS_CALENDAR_CATEGORY`-Konstante. Patch-Ziele auf
  `IllnessPauseSyncService.apply` und `backend.sync.adaptive` migriert;
  beide betroffenen Tests erneut **PASS**. Gesamtsuite nach der nächsten
  Integration wiederholen.

## P6.12 — Adaptiver Preview-Follow-up (GPT-6 Luna)

- Worker `0cea809`, sequenziell integriert als `d0515a2`, tatsächlicher
  Diff- und Code-Review **PASS**. `AdaptivePreviewFollowupService` besitzt
  Preview-Prüfung, Ergebnisprojektion und unverändertes Warn-Event mit
  Status-Fallback; `server.py` enthält nur die Komposition und konkrete
  Aufrufe nach Wetter-Refresh. Kein Server-Rückimport/-Callback und kein
  Remote-Write. 18 fokussierte Dienst-, Architektur- und Wettertests **PASS**;
  Compile, Inventar-Check und `git diff --check` **PASS**. P6 hat danach
  sieben zu prüfende Definitionen; vollständige Suite noch offen.

## P6.13 — Konfliktentscheidung und Job-Retry (GPT-6 Luna)

- Worker `a1954de`, sequenziell integriert als `d735a44`, im tatsächlichen
  Diff- und Code-Review **PASS**. `SyncConflictCommandService` besitzt die
  lokale Planned-Unit-/Competition-Typentscheidung und den Queue-Retry; die
  bestehende Coach-Operation-, Objekt-Scope-, Provider-Ziel- und Remote-Write-
  Autorisierung findet unverändert vor dem mutierenden Service-Aufruf statt.
  Ein erfolgreicher Retry ergänzt die turn-lokale Job-ID wie zuvor. Keine
  Server-Rückimporte/-Callbacks; die jeweiligen Domänendienste behalten
  Transaktion, Revision und Job-Status.
- 103 integrierte Dienst-, Coach-Tool-, Dialog- und Architekturtests **PASS**;
  Compile, Inventar-Check und `git diff --check` **PASS**. P6 zählt noch sechs
  Definitionen; Gesamtsuite steht aus.

## P6.14 — Plan-Push-Queue (GPT-6 Luna)

- Worker `4637c0b` im tatsächlichen Diff-Review zunächst **FAIL**:
  beim Fehlschlag eines späteren 28er-Chunks ging die ID eines bereits
  eingereihten Jobs aus der turn-lokalen Liste verloren. Korrektur
  `46d6110` mit Partial-Failure-Regressionstest erneut geprüft: **PASS**;
  sequenziell als `760a02c` und `e377851` integriert.
- `PlanPushCommandService` besitzt Chunking, Reason-/Repair-Payload,
  per-Item-Hashes und Queue-Orchestrierung; `server.py` enthält nur die
  Komposition und Aufrufe nach Coach-Autorisierung. 37 integrierte Dienst-,
  Repair-, Architektur- und Server-Tests **PASS**; Compile, Inventar-Check
  und `git diff --check` **PASS**. Fünf P6-Definitionen bleiben offen;
  Gesamtsuite steht aus.

### Integrationscheckpoint

- Letzter integrierter Diff-Stand: `51c72ca` (P6.14), fokussierter Review
  **PASS**. Fünf P6-Definitionen betreffen noch strukturierte Plan-Sync-
  Auswahl, Hash-/Revisionsvalidierung und den Coach-Autorisierungs-Router.
- Nächster Schritt: den zweistufigen `StructuredPlanSyncService` aus dem
  dedizierten GPT-6-Luna-Worktree prüfen und sequenziell integrieren, danach
  `server.py`-Aufrufer sowie Scope-/Hash-/Rollback-Tests erneut prüfen.
  Vollständige Python-Suite auf dem Code-Stand `51c72ca` nach den
  Test-Patch-Korrekturen: 2.092 Tests, 12 übersprungen, **PASS** in 266,135 s.
- `origin/develop` war beim letzten Fetch sieben Commits voraus; es gibt
  aktuell keinen offenen PR. Vor Veröffentlichung erneut fetch/integrate und
  alle betroffenen Tests/Reviews wiederholen.

- Worker-Patch `3a857cb` für die verbleibende Plan-Sync-Auswahl im
  tatsächlichen Diff-Review zunächst **FAIL**: Bei `_sync_all_pending` fehlte
  die zusätzliche Prüfung gebundener Same-Turn-IDs. Korrektur `c233fd8` im
  tatsächlichen Diff- und Code-Review **PASS**, sequenziell als `a46a889`
  und `84f81c4` integriert. `StructuredPlanSyncService` besitzt Auswahl,
  Scope-Gruppen, Hash-/Revisionsprüfung, atomare Autoritätsmarkierung und
  Queue-Aufruf; `server.py` prüft Coach-Operation, Ziel und Objektscopes vor
  der Mutation. Keine Server-Rückimporte/-Callbacks oder dauerhaften Wrapper.
  Regressionen prüfen All-Pending plus Same-Turn-IDs, unveränderten Queue-Hash
  für Changed und Rollback bei Authority-Fehler.

### P6.15 — Strukturierte Plan-Sync-Auswahl

- Geprüfter integrierter Diff-Stand: `84f81c4` plus Root-Adapter in
  `server.py`, Architektur-Guard und Inventar. Review **PASS**. Vier frühere
  Server-Fachfunktionen entfernt; der verbleibende Coach-Autorisierungs-
  Router wird in P7 mit dem Tool-Dispatch verlagert.
- `python -m unittest discover -s tests -q`: **PASS**, 2.099 Tests,
  12 übersprungen, 195,606 s. Sieben fokussierte Plan-Sync- und drei
  Architekturtests **PASS**; `git diff --check` **PASS**. Verbleibendes
  Risiko: Reparatur-Manifest-Orchestrierung liegt noch in `server.py` und
  wird separat vor P6-Abschluss ausgelagert.

## P7.1 — Intervals-Coach-Kontextprojektion (GPT-6 Luna)

- Worker-Patch `59f4597`, sequenziell als `0180b47` integriert;
  tatsächlicher Diff- und Code-Review **PASS**. Der read-only
  `CoachIntervalsContextService` besitzt Aktivitätsauswahl, 7-/30-Tage-
  Summen, Zukunftsfilter und kompakte Planned-Unit-Projektion vollständig.
  `server.py` beschafft nur Snapshot, Planned-Unit-Lesedaten und lokalen Tag;
  frühere Projektionsfunktionen und unbenutzte Wrapper sind entfernt. Kein
  Server-Rückimport/-Callback, keine Provider-Schreiboperation und keine
  gespeicherte Trainingsbeschreibung im kompakten Event.
- Vier neue Projektionstests, drei Architekturtests und 462 Server-Tests
  **PASS** (drei übersprungen); `git diff --check` **PASS**. Vollständige
  Python-Suite und nachfolgendes Review bleiben für den nächsten
  integrierten Stand erforderlich.

## P6.16 — Vollständiges Reparatur-Manifest (GPT-6 Luna)

- Worker-Diff `748c42f` im tatsächlichen Review zunächst **FAIL**: stale
  Revision/Hash wurde vor dem Root-Scope-Gate sichtbar. Korrektur `cd17cbd`
  im selben Worktree erneut geprüft: **PASS**; sequenziell als `b973e99`
  und `167a4c1` integriert. `PlanRepairManifestService` besitzt die
  Zeitraum-/Vollständigkeitsprüfung, erneute Hash-/Revisionsprüfung im
  mutierenden UOW, Beschreibungskontrolle, Autoritätsmarkierung und finalen
  Manifesthash. `server.py` prüft Objekt-Scopes vor `execute`, enthält keine
  Reparatur-Fachcallbacks/-Wrapper; Queue- und Remote-Freigabe bleiben
  explizit beim aufrufenden Coach-Pfad.
- Elf Diensttests, 27 Workout-Repair-Tests und drei Architekturtests
  **PASS**; `git diff --check` **PASS**. Inventar: P6 hat keine offenen
  Fachfunktionen mehr, aber 16 globale Bindungen für den P11-Restcode-Audit.
  P7-Tool-Router und die vollständige Python-Suite bleiben offen.

## P7.2 — Bibliothekskatalog im Coach-Kontext (GPT-6 Luna)

- Worker-Diff `94ecae5`, sequenziell als `51ea667` integriert und im
  tatsächlichen Diff/Code **PASS** geprüft. `backend/coach/context.py`
  besitzt die vollständige typbalancierte, begrenzte Whitelist-Projektion;
  datierte lokale Pläne werden ausgeschlossen und private Felder nicht
  weitergegeben. `server.py` liest nur die Bibliothek und injiziert die
  unveränderten Limits; drei frühere Fachfunktionen sind entfernt, keine
  dauerhaften Server-Wrapper oder Rückimporte.
- Sechs neue Projektortests und die vollständige Python-Suite auf dem
  integrierten Code-Stand: **PASS**, 2.120 Tests, 12 übersprungen,
  227,809 s. `compileall`, Inventar-Check und `git diff --check` **PASS**.
  Weitere P7-Kontext-/Konversations- und Tool-Abläufe bleiben offen.

## P7.3 — Coach-Quick-Actions (GPT-6 Luna)

- Worker `be39754` im tatsächlichen Integrationsreview zunächst **FAIL**
  als vollständige P7-Auslagerung: die reine Projektion ließ vier KV-/Preview-
  Read-Orchestrierungen in `server.py` zurück. Korrektur `9859e65` im selben
  Worktree erneut geprüft: **PASS**; sequenziell als `e0541d0` und `9e6c891`
  integriert. `CoachQuickActionsService` besitzt die konkreten lokalen
  Reads und die unveränderte, datensparsame Projektion; `server.py` komponiert
  den Dienst und ruft `.state()` auf. Keine Server-Rückimporte/-Callbacks,
  kein neuer Cache oder Remote-Write.
- Sechs Dienst-/Projektortests, drei integrierte Morning-/Quick-Action-
  Tests und drei Architekturtests **PASS**; Compile, Inventar-Check und
  `git diff --check` **PASS**. Gesamtsuite nach der nächsten Integration
  erneut ausführen.

## P7.4 — Gemini-Konversationshistorie (GPT-6 Luna)

- Worker-Diff `38b2f63` im tatsächlichen Review zunächst **FAIL**: der
  Inline-Media-Replay-Filter hätte bisher akzeptierte truthy Werte verworfen.
  Korrektur `1569737` im selben Worktree erneut geprüft: **PASS**;
  sequenziell als `abc88b1` und `d5985c3` integriert. Pure Exchange-/Trim-
  und Sanitizing-Logik liegt in `coach/conversation.py` ohne Serverzugriff.
- Folgedienst-Diff `3834326` im tatsächlichen Code-/Diff-Review **PASS**,
  als `40a7ce9` integriert. `GeminiConversationHistoryService` besitzt
  Load, sichere persistierte Save-Projektion und atomare Reparatur eines
  unterbrochenen Tool-Calls; `server.py` komponiert ihn und ruft konkrete
  Methoden. Keine Fachcallbacks, kein veränderter Retention-/Replay-Vertrag.
- Je sechs pure und Persistenztests, 19 Attachment-Tests, fünf betroffene
  Server-Tests und drei Architekturtests **PASS**. Compile, Inventar-Check
  und `git diff --check` **PASS**. Gesamtsuite für den aktualisierten
  integrierten Stand noch offen; P7-Konversations- und Tool-Orchestrierung
  bleibt umfangreich.

## P7.5 — Lokale Chat-Nachrichten (GPT-6 Luna)

- Worker-Diff `fc83a1e`, sequenziell als `579d6ba` integriert;
  tatsächlicher Diff-/Code-Review **PASS**. `CoachMessageService` besitzt
  die einfachen Add-/List-Abläufe mit konkretem `ChatRepository`,
  `DatabaseManager` und Event-Puffer. Die alten Server-Funktionen sind
  entfernt, sämtliche direkten Testaufrufe auf den Dienst migriert;
  andere mehrstufige Coach-Turn-Transaktionen bleiben ausdrücklich in P7/P8.
  Keine Server-Rückimporte/-Callbacks oder neue Sammelmodule.
- Fünf Diensttests, 19 Attachment-, 68 Dialog-, 26 Tool-Coverage- und drei
  Architekturtests **PASS**; Compile, Inventar-Check und `git diff --check`
  **PASS**. Das Coach-State-Event wird im eigenständigen Add-Pfad nach
  Verlassen seiner UOW publiziert; ein hypothetischer Aufruf innerhalb einer
  äußeren UOW hätte wie zuvor keine separate Commit-Garantie. Gesamtsuite
  auf dem nächsten integrierten Stand erneut prüfen.

## P7.6 — Gemini-History-Attachment-Teile (GPT-6 Luna)

- Worker-Diff `89bc6fa`, sequenziell als `b27538b` integriert und im
  tatsächlichen Diff/Code **PASS** geprüft. Die Auswahl des begrenzten
  Inline-Rohdatenbudgets und die datensparsame Part-Projektion liegen in
  `backend/coach/attachments.py`; `server.py` injiziert das bisherige Limit
  und behält nur die noch auszulagernde lokale History-Orchestrierung.
  Keine Server-Rückimporte, Fachcallbacks oder neuen Zustandseigentümer.
- Vier neue Part-Tests, 19 Attachment-Tests, drei Architekturtests und zwei
  betroffene Server-Tests **PASS**. Compile, Inventar-Check und
  `git diff --check` **PASS**. Die vollständige Suite auf diesem integrierten
  Stand steht noch aus; lokale History-Orchestrierung ist der nächste P7-Schritt.

## P7.7 — Lokale Gemini-Chat-History (GPT-6 Luna)

- Worker-Diff `12c81f0`, sequenziell als `348c86a` integriert und im
  tatsächlichen Diff/Code **PASS** geprüft. `GeminiLocalChatHistoryService`
  besitzt den vollständigen read-only Nachrichten-/Attachment-Leseablauf,
  das unveränderte Inline-Budget und die begrenzte History-Projektion.
  `server.py` komponiert ihn nur noch; keine Rückimporte oder Fachcallbacks.
  Beschädigtes altes Attachment-JSON wird ohne Raw-Media-Leck ignoriert.
- Sechs neue Diensttests, 19 Attachment- und drei Architekturtests **PASS**;
  Compile, Inventar-Check und `git diff --check` **PASS**. Die Gesamtsuite
  für den unmittelbar vorherigen Stand `0e5ebfe`: 2.147 Tests, 12
  übersprungen, **PASS**; erneuter Gesamtlauf für diesen Stand offen.

## P10.1 — Aktive Bibliotheks-Pagination (GPT-6 Luna)

- Worker-Diff `9d24999`, sequenziell als `33e8785` integriert und im
  tatsächlichen Diff/Code **PASS** geprüft. `LibraryPageService` besitzt
  den vollständigen read-only SQL-Filter, Keyset-Cursor, Limit und die
  Response-Projektion. Die HTTP-Route ruft den konkreten Dienst auf;
  keine Server-Rückimporte, Fachcallbacks, Remote-Writes oder bleibenden
  Kompatibilitäts-Wrapper. Der neue Composition-Root-Factory-Eintrag ist
  im Inventargenerator als solcher klassifiziert.
- Vier neue Dienst-, vier Pagination-Integrations- und drei Architekturtests
  **PASS**; Compile, Inventar-Check und `git diff --check` **PASS**.
  Gesamtsuite auf diesem integrierten Stand noch offen.

## P7.8 — Sitzungsgebundene Coach-Vorschlags-Reads (GPT-6 Luna)

- Worker-Diff `d5dea7e`, sequenziell als `3b1aef2` integriert und im
  tatsächlichen Diff/Code **PASS** geprüft. `CoachProposalReadService`
  besitzt Prune, sessiongebundenes SELECT und datensparsame View innerhalb
  einer UOW; kanonischer Hash und TTL-Grenzen sind ebenfalls in
  `backend/coach/proposals.py`. `server.py` nutzt den konkreten Dienst,
  kein Rückimport, kein Fachcallback, kein dauerhaftes Wrapper-API.
  Der Worker-Dateikopf wurde bei der Integration an die tatsächlich
  schreibende Expiration-Cleanup-Semantik angepasst und erneut geprüft.
- Sechs neue Dienst-, 16 bestehende Review-/Autorisierungs- und drei
  Architekturtests **PASS**; Compile und `git diff --check` **PASS**.
  Gesamtsuite auf dem unmittelbar vorherigen Stand `3d84990`: 2.157 Tests,
  12 übersprungen, **PASS**; auf diesem integrierten Stand noch offen.

## P7.9 — Eingabevertrag für Coach-Aktionsvorschauen (GPT-6 Luna)

- Worker-Diff `3c9e593` im tatsächlichen Review zunächst **FAIL** wegen
  eines irreführenden Session-Owner-Anspruchs im Docstring der reinen
  Validierung. Korrektur `7197605` vom selben Worker erneut geprüft:
  **PASS**; sequenziell als `ba72296`/`7e5dce2` integriert. Die Funktion
  liegt in `backend/coach/proposals.py`, der Server nutzt sie direkt ohne
  Wrapper. Aktionstypen und verwaiste Server-Zielkonstante sind entfernt;
  Owner-Prüfung verbleibt ausdrücklich im späteren Vorschlags-Use-Case.
- Vier neue Validierungs-, sechs Read-Service-, drei Architektur- und ein
  bestehender Server-Vertragstest **PASS**; Compile, Inventar-Check und
  `git diff --check` **PASS**. Vollständige Suite für den vorigen integrierten
  Stand `9ec752d`: 2.163 Tests, 12 übersprungen, **PASS**; nach diesem
  Schritt erneut auszuführen.

## P7.10 — Strukturierter Athletenkontext (GPT-6 Luna)

- Worker-Diff `4aba0a4`, sequenziell als `b790300` integriert und im
  tatsächlichen Diff/Code **PASS** geprüft. `CoachStructuredContextService`
  besitzt alle lokalen und Provider-Reads, Kontext-/Kalenderprojektion und
  Quellenpolicy; die Composition Root injiziert konkrete Dienste und nur
  einen Uhr-Callable. Keine Fachcallbacks oder Server-Rückimporte. Die
  bisherigen mehrfachen Reads, Datums-/Quellenkennzeichnung und
  Datenschutzprojektion bleiben erhalten.
- Drei neue Dienst-, 19 Kontext-, 15 Provider-Review- (ein Skip), drei
  Response-Failure-, ein gezielter Server- und drei Architekturtests
  **PASS**. Compile, Inventar-Check und `git diff --check` **PASS**.
  Vollständige Python-Suite auf `5c55917`: 2.170 Tests, 12 übersprungen,
  **PASS** in 226,247 s.

## P7.11 — Atomare Bestätigung von Coach-Aktionsvorschauen (GPT-6 Luna)

- Worker-Diff `6ecd0c1`, sequenziell als `a4d7b87` integriert und im
  tatsächlichen Diff/Code **PASS** geprüft. `CoachProposalConfirmationService`
  besitzt UUID-Prüfung, Token-Erzeugung, sessiongebundenen SELECT,
  Status-/TTL-Grenze, SHA-256-Token-Hash, atomisches UPDATE, Rotation und
  datensparsame Antwort. Die Route ruft den konkreten Dienst; keine
  Server-Rückimporte/-Fachcallbacks oder Remote-Writes. Der alte lockere
  Server-UUID-Regex ist entfallen; der unabhängige Wettkampf-Test prüft nun
  eine tatsächlich parsebare UUID.
- Sieben neue Bestätigungs-, vier Validierungs-, sechs Read-, 16
  bestehende Review-/Autorisierungs-, ein Action-Preview-, ein Wettkampf-
  und drei Architekturtests **PASS**. Compile, Inventar-Check und
  `git diff --check` **PASS**. Gesamtsuite auf dem letzten Stand `5c55917`:
  2.170 Tests, 12 übersprungen, **PASS**; auf diesem Stand erneut offen.

## P7.12 — Coach-Prompttext (GPT-6 Luna)

- Worker-Diff `ce98842`, sequenziell als `6ac748f` integriert und im
  tatsächlichen Diff/Code **PASS** geprüft. `COACH_PROMPT` liegt nun in
  `backend/coach/prompt.py`; die Composition Root importiert den Text ohne
  Kopie oder Wrapper. Vor Entfernung der alten Konstante wurden beide
  Python-Stringwerte unabhängig exakt verglichen: 9.398 Zeichen,
  SHA-256 `1e058f6943a0fde9d04dcc04a1d285b8d0bf7f29030cef36379aebf104366545`.
  Sicherheits-, Sprach- und Remote-Schreibvorgaben sind unverändert.
- Zwei Prompt-, drei Architektur- und 19 Kontexttests **PASS**; Compile,
  Inventar-Check und `git diff --check` **PASS**. Gesamtsuite auf `f0467c2`:
  2.179 Tests, 12 übersprungen, **PASS** in 190,418 s.

## P7.13 — Sessiongebundene Coach-Vorschlagserzeugung (GPT-6 Luna)

- Worker-Diff `73a3b4a`, sequenziell als `4ebc33f` integriert; Root-Diff
  `3efcb99` im tatsächlichen Code/Diff **PASS** geprüft. Die vollständige
  Abfolge Validierung → frischer Duplikat-Snapshot → UUID/TTL → atomare
  Persistenz → datensparsame View gehört `CoachProposalCreationService`.
  `server.py` besitzt nur die Konstruktion und direkte Aufrufe. Keine
  Rückimporte, Fachcallbacks, Remote-Writes oder Wrapper.
- Sechs neue Dienst-, 16 Review-/Autorisierungs-, 26 Tool-Coverage-, 13
  Duplikat- und drei Architekturtests **PASS**; Compile, Inventar-Check
  und `git diff --check` **PASS**. Gesamtsuite auf kombiniertem Folgestand
  `3a5c4e0`: 2.188 Tests, 12 übersprungen, **PASS** in 183,816 s.

## P7.14 — Vollständiger Coach-Trainingskontext (GPT-6 Luna)

- Worker-Diff `0df83b1` im Code-Review zunächst **FAIL**: zusätzliche
  Intervals-Kürzung hätte gegenüber dem Original die gelieferte Projektion
  verändert, während Rollups unverändert blieben. Korrektur vom selben
  Worker `13dd7cf` im tatsächlichen Diff **PASS**; sequenziell als
  `4b9abd2`/`6e13bdb` integriert. Root-Diff `3a5c4e0` **PASS** geprüft.
  `CoachTrainingContextService` besitzt Snapshot-Read, strukturierte
  Projektion, Library-Auswahl, Abschnitts-/Gesamtbudget, Prompt-Montage
  und Warning-Event. Die Composition Root injiziert nur konkrete Dienste
  und Werte; Aufrufer und Test-Patch-Ziele wurden migriert.
- Drei neue Dienst-, 68 Dialog-, drei Response-Failure-, 15 Provider-Review-
  (ein Skip), 18 Audit- (ein Skip) und drei Architekturtests **PASS**;
  Compile, Inventar-Check und `git diff --check` **PASS**. Vollständige
  Python-Suite auf `3a5c4e0`: 2.188 Tests, 12 übersprungen, **PASS**
  in 183,816 s. Verbleibendes P7-Risiko: Kontextvorschau und Gemini-
  Request-Historie tragen noch Orchestrierung in `server.py`.

## P7.15 — Bestätigte Coach-Aktionsausführung (Root-Architekturarbeit)

- Integrierter Diff `b03c3d8` im tatsächlichen Code **PASS** geprüft.
  `CoachProposalExecutionService` besitzt Maintenance-Gate, Token-Hash,
  Session-/TTL-/Payload-Hash-Prüfung, atomaren Einmalverbrauch vor
  Dispatch, Undo- und Duplikat-Aktion sowie datensparsame Audit-Metadaten.
  Die Root injiziert konkrete Dienste und den Intervals-Client-Konstruktor;
  keine Fachcallbacks oder Backend-Rückimporte. Remote-Löschung wird nur
  nach gültigem, bestätigtem Token erreicht.
- Vier neue Ausführungs-, 16 Review-/Autorisierungs- und drei Architekturtests
  **PASS**; Compile, Inventar-Check und `git diff --check` **PASS**.
  Vollständige Suite auf kombiniertem Stand `a42bad8`: 2.199 Tests,
  12 übersprungen, **PASS** in 206,913 s.

## P7.16 — Gemini-Request-Historie (GPT-6 Luna)

- Worker-Diff `0ac4394`, sequenziell als `c047809` integriert; Root-Diff
  `a42bad8` im tatsächlichen Code/Diff **PASS** geprüft. Der
  `GeminiRequestPayloadService` besitzt History-Auswahl, lokale
  Textkontinuität, deduplizierte Eingabe, Attachment-Replay,
  Call-Name-Lesen und Tool-Response-Persistenz vor Provider-Request.
  Provider-Argumente bleiben unverändert; Aufrufer und Tests nutzen den
  konkreten Dienst. Kein Server-Rückimport oder Fachcallback.
- Vier neue Dienst-, 19 Attachment- und drei Architekturtests **PASS**;
  Compile, Inventar-Check und `git diff --check` **PASS**. Die
  Gesamtsuite auf `a42bad8`: 2.199 Tests, 12 übersprungen, **PASS**
  in 206,913 s.

## P7.17 — Coach-Kontextvorschau (GPT-6 Luna)

- Worker-Diff `01327b1`, sequenziell als `3570de9` integriert; Root-Diff
  `a42bad8` im tatsächlichen Code/Diff **PASS** geprüft. Der
  `CoachContextPreviewService` besitzt Snapshot-/Nachrichten-Reads,
  strukturierte und Intervals-Projektion, Budgetmetadaten, Library-Read,
  Prompttext-Referenz und Response-Layout. Nach Integration wurden sechs
  inzwischen unbenutzte Server-Kompatibilitäts-Wrapper entfernt. Nur
  konkrete Lesedienste und Uhren werden injiziert, keine Fachcallbacks.
- Drei neue Dienst- und drei Architekturtests **PASS**; Compile,
  Inventar-Check und `git diff --check` **PASS**. Die Gesamtsuite auf
  `a42bad8`: 2.199 Tests, 12 übersprungen, **PASS** in 206,913 s.

## P7.18 — Gemini-Antwortnormalisierung (GPT-6 Luna)

- Worker-Diff `350061f`, sequenziell als `5a6cdd1` integriert; Root-Diff
  `dce0188` im tatsächlichen Code/Diff **PASS** geprüft. Der konkrete
  `GeminiResponseNormalizationService` besitzt 502-/Parallel-Tool-Prüfung,
  dauerhafte Model-History, Text-/Tool-Konvertierung, Call-Name-Persistenz,
  UUID-Reihenfolge und Usage-Projektion. Keine Rückimporte oder
  Fachcallbacks. Beide JSON-/SSE-Aufrufer nutzen denselben Dienst.
- Vier neue Dienst-, vier gezielte Gemini-Integrations- und drei
  Architekturtests **PASS**; Compile, Inventar-Check und `git diff --check`
  **PASS**. Vollständige Suite nach weiterer P7-Integration offen.

## P7.19 — Korrektur-/Fehlschrittprojektion (GPT-6 Luna)

- Worker-Diff `7788c4f` im tatsächlichen Review zunächst **FAIL** wegen
  unbeabsichtigter Änderung von `ok`-Truthiness und JSON-Feldvergleichen.
  Korrektur `3e3adc3` desselben Workers erneut geprüft: **PASS**;
  sequenziell als `3d919d4`/`f77aa2f` integriert, Root-Diff `d0fe2ee`
  **PASS**. `backend/coach/outcomes.py` besitzt nun die vollständige
  Äquivalenz-/Repair-/Unresolved-Projektion; Server-Funktionen und alte
  Testzugriffe wurden entfernt. Keine Zustands- oder Remote-Schreibrechte.
- Acht neue Reparatur-, 68 Dialog- und drei Architekturtests **PASS**;
  Compile, Inventar-Check und `git diff --check` **PASS**. Vollständige
  Suite nach weiterer P7-Integration offen.
- Bekannter Altvertrag: bei einem invaliden Fehlschritt ohne `request`
  kann ein späterer Erfolg desselben Tools den Fehler als repariert
  markieren, ohne Objektäquivalenz zu beweisen. Diese Ausnahme blieb in der
  reinen Migration unverändert und ist mit einem Regressionstest sichtbar;
  eine separate Härtung braucht Dialog-/Outcome-Prüfung.

## P7.20 — Scope- und Ausführungsgrenzen (GPT-6 Luna)

- Worker-Diff `52d8b1a`, sequenziell als `46f9712` integriert; Root-Diff
  `15092be` im tatsächlichen Code/Diff **PASS** geprüft. In
  `backend/coach/authorization.py` liegen jetzt der inklusive
  Planungshorizont und der konkrete Scope-403-Vertrag. Der Server gibt
  den Horizont als Wert weiter; sämtliche alten Scope-Wrapper und
  Testzugriffe wurden entfernt. Keine Remote-Freigabe wird hinzugefügt.
  Bei der Integration wurde `require_coach_scope` auf den bereits
  bestehenden `require_scope`-Eigentümer reduziert und erneut geprüft.
- Vier neue Autorisierungs-, 27 Workout-Repair- und drei Architekturtests
  **PASS**; Compile, Inventar-Check und `git diff --check` **PASS**.
  Vollständige Suite auf `15092be`: 2.215 Tests, 12 übersprungen,
  **PASS** in 176,989 s.

## P7.21 — Dialog-Reparatur- und Effektschlüssel (GPT-6 Luna)

- Worker-Diff `b3541c5`, sequenziell als `d182fb9` integriert; Root-Diff
  der Server- und Testmigration im tatsächlichen Code/Diff **PASS** geprüft.
  Fünf konkrete Schlüsselbildungen liegen in `backend/coach/service.py`;
  die Server-Duplikate und der alte Testzugriff wurden entfernt. Hashing,
  Scope-/Remote-Bindung und die bisherige Fehlersignatur bleiben erhalten.
- Fünf neue Schlüssel-, 68 Dialog- und drei Architekturtests **PASS**;
  Compile, Inventar-Check und `git diff --check` **PASS**. Der spätere
  Gesamtstand `6bfec4b` mit dieser Änderung: 2.228 Tests, 12
  übersprungen, **PASS** in 173,351 s.

## P7.22 — Lokale Dialog-Read-Projektionen (GPT-6 Luna)

- Worker-Diff `edeaa69` zunächst **FAIL**: kaputtes gespeichertes JSON und
  truthy Nicht-Objekte wurden entgegen dem Altvertrag stillschweigend
  übersprungen. Korrektur `b06db39` desselben Workers erneut anhand des
  Codes/Diffs geprüft: **PASS**; sequenziell als `a76249b`/`33a379f`
  integriert. `CoachDialogueReadService` besitzt die vollständige lokale
  Kontext-, Receipt- und Draft-Projektion; Server-Duplikate entfernt. Der
  konkrete Read-Service wird auch an die Plan-Zustandsprojektion gebunden.
- Acht direkte, 68 Dialog-, 462 Server- und drei Architekturtests **PASS**
  (Servertests: drei übersprungen). Compile, Inventar-Check und
  `git diff --check` **PASS**. Vollständige Suite auf `6bfec4b`: 2.228
  Tests, 12 übersprungen, **PASS** in 173,351 s. Uhrzeit-Fixierung im Dialogtest zielt nun auf den
  injizierten Dienst-Clock statt auf eine entfernte Server-Funktion.

## Veröffentlichung gegen `develop` — in Vorbereitung

- Letzter vollständig integrierter und geprüfter Stand: `6bfec4b` auf
  `refactor/server-extraction-p3-domain-foundations` (7.250 Zeilen,
  330 Top-Level-Definitionen in `server.py`). Es wurde noch kein PR
  veröffentlicht und kein Merge behauptet.
- Zielbranch bei letzter Prüfung: `origin/develop` auf `37144d5`; acht
  neuere Commits seit der gemeinsamen Basis. Der dedizierte Worktree
  `ai-coach-server-extraction-foundation-pr` hat einen begonnenen,
  **nicht abgeschlossenen** Merge mit Konflikten in `server.py`,
  `tests/test_server.py`, `tests/test_provider_review.py`,
  `tests/test_audit_remediation.py` und
  `tests/test_diagnostic_followups.py`. Der Konflikt in
  `backend/sync/daily.py` wurde fachlich auf stündliche Erfolgs-/Versuchsmarker
  und den konkreten `DailySyncMarkerService` vereint; acht direkte Tests
  **PASS**, aber noch kein Gesamt-Review/Merge-PASS.
- Nächster Integrationsschritt: neue `develop`-Verträge für begrenztes
  automatisches Garmin-Fenster und manuellen Morgen-Check-in in die
  ausgelagerten Besitzer übernehmen; alle konfliktbehafteten Tests auf
  diese konkreten Besitzer umstellen, dann den Merge vollständig auflösen,
  Gesamtsuite und Review-Gate erneut ausführen. Keine Auto-Merge-Aktivierung
  vor einem PASS des finalen PR-Diffs.

## P7.23 — Attachment-History und lokale Evidenz (GPT-6 Luna)

- Worker-Diff `3a11006`, sequenziell als `af310ba` integriert; Root-Diff
  anhand tatsächlichem Code **PASS** geprüft. Der konkrete
  `CoachAttachmentContextService` besitzt jetzt beide Read-Abfragen,
  OpenAI-Vorverlaufserkennung und die begrenzte Evidenzprojektion.
  Server-Duplikate und SQL-Konstante entfernt; keine Rohdaten gelangen
  in die Dialog-Evidenz und keine Remote-Aktion wurde ergänzt.
- Fünf direkte, 68 Dialog- und drei Architekturtests **PASS**;
  Compile, Inventar-Check und `git diff --check` **PASS**. Der spätere
  integrierte Gesamtstand mit dieser Änderung: 2.237 Tests,
  12 übersprungen, **PASS** in 134,031 s.

## P6/develop-Abgleich — stündlicher Refresh und Garmin-Fenster (Root)

- Der konkrete Backend-/Aufrufer-Diff wurde im Code **PASS** geprüft.
  Die neuen Zielbranch-Verträge aus `origin/develop` (`37144d5`) wurden
  gegen ihre früheren Server-Aufrufer und die ausgelagerten Eigentümer
  geprüft: `DailySyncMarkerService` besitzt Stunden-/Versuchsmarker,
  `SyncJobQueueService` schreibt Versuche für Startup/Scheduler-Refreshes,
  Garmin- und Intervals-Sync setzen Erfolgsmarker nur ohne historisches
  `end_date`, und `SyncJobExecutor` beginnt Garmin-Backfill hinter dem
  zweitägigen automatischen Fenster. Manueller 30-Tage-Abruf bleibt
  separat. Der Intervals-Refresh verändert den Morgen-Fehlerstatus nicht
  mehr. Keine Remote-Schreibfreigabe wurde erweitert.
- 50 direkte Marker-/Queue-/Garmin-/Intervals-/Executor-Tests **PASS**;
  462 Servertests, drei übersprungen, **PASS**; drei Architekturtests,
  Compile, Inventar-Check und `git diff --check` **PASS**. Im ersten
  Gesamtlauf fiel ein alter Kalendertest wegen des entfernten Tagesmarkers
  auf; seine neue ISO-Zeitstempel-Assertion und alle neun Kalendertests
  **PASS**. Gesamtsuite anschließend: 2.237 Tests, 12 übersprungen,
  **PASS** in 134,031 s. Review des finalen `develop`-Merge-Diffs offen.

## P8.1/develop-Abgleich — expliziter Morgen-Check-in (GPT-6 Luna)

- Worker-Diff `b7ea1ce`, sequenziell als `16a3190` integriert; der
  tatsächliche Code/Diff des `ManualMorningCheckinService` und die
  Server-Aufrufer **PASS** geprüft. Er besitzt den Garmin-Refresh,
  aktuellen Schlaf-Frische-Gate und nachgelagerte Body-Battery-Aktualisierung.
  Ein Sync-Fehler lässt alte Schlafdaten nicht zur Coach-Analyse durch.
- Der in `develop` entfernte automatische Morgen-Scheduler samt Lock,
  Retry-Reservierung und HTTP-/Startup-Aufrufen wurde auch hier entfernt.
  Obsolete Tests dieser nicht mehr vorhandenen Automatik wurden durch
  fünf direkte Diensttests und einen Background-Integrationsvertrag
  für das Frische-Gate ersetzt. Die übrigen 14 Diagnose-, 17 Audit-
  (einer übersprungen), 462 Server- (drei übersprungen) und drei
  Architekturtests **PASS**. Compile, Inventar-Check und `git diff --check`
  **PASS**; vollständige Suite auf `ae7db8c`: 2.232 Tests,
  12 übersprungen, **PASS** in 222,488 s.
- P8 bleibt offen: Background-/Stream-Zustand und Scheduler besitzen noch
  Server-Fachlogik; die Morgen-Statusprojektion liegt ebenfalls noch im
  Server. Finaler `develop`-Merge und PR-Review stehen aus.

- Zielbranch erneut abgeglichen: `origin/develop` ist inzwischen
  `232d6cc` (zusätzlicher Release-Versionscommit). Diese Änderung ist
  noch nicht in den Extraktionsbranch integriert; der vorbereitete
  Veröffentlichungs-Worktree bleibt im unaufgelösten Mergezustand.

## P8.2 — Morgen-Statusprojektion (GPT-6 Luna)

- Worker-Diff `947c41b` im tatsächlichen Code/Diff zunächst **FAIL**
  wegen Ruff-I001 im neuen Testimport; derselbe Worker korrigierte mit
  `60e448b`, erneutes Diff-/Lint-Review **PASS**. Sequenziell als
  `aaa8d0a`/`736a22d` integriert. `MorningCheckinStateService` besitzt
  jetzt die read-only Tages-/Statusprojektion; die Server-Funktion wurde
  entfernt und alle drei Aufrufer binden den konkreten Dienst.
- Zehn Direkt-, 14 Diagnose-, fünf gezielte Server- und drei
  Architekturtests **PASS**; Ruff für neue Dateien, Compile,
  Inventar-Check und `git diff --check` **PASS**. Gesamtsuite nach
  dieser Änderung zunächst 2.237 Tests/12 Skips mit einem FAIL: Der
  Prompt-Digest-Test erwartete noch den alten Hash nach Übernahme des
  Garmin-Zwei-/30-Tage-Hinweises aus `develop`; kein P8.2-Funktionsfehler.
  Der Test wurde mit einer expliziten inhaltlichen Assertion für diesen
  Vertrag aktualisiert. Danach fünf Prompt-/Architekturtests **PASS**;
  erneuter Gesamtlauf: 2.237 Tests, 12 Skips, **PASS** in 234,969 s.
  Finaler `develop`-Merge-Review steht aus.

## Develop-Abgleich nach P8.2 — Garmin-Prompt und Release-Version (Root)

- Geprüfter lokaler Diff gegenüber `19588cc`: Der fachliche Hinweis in
  `backend/coach/prompt.py` entspricht dem aktuellen `develop`-Text;
  `server.py` meldet die aktuelle Zielbranch-Version `1.11.11`. Der
  Prompt-Snapshot wurde auf den tatsächlichen Digest aktualisiert und
  prüft zusätzlich beide Garmin-Fenster semantisch. Keine Änderung an
  Autorisierung, Remote-Schreibfreigaben oder Provider-Transport.
- Fünf Prompt-/Architekturtests **PASS**; ein erster Gesamtlauf hatte
  ausschließlich den veralteten Prompt-Digest als FAIL (2.237 Tests,
  12 Skips). Nach der Korrektur vollständige Suite: 2.237 Tests,
  12 Skips, **PASS** in 234,969 s. Veröffentlichung und CI sind offen.

## P9.1 — Datenschutzsichere Coach-Diagnosehistorie (GPT-6 Luna)

- Worker-Commit `8087930`, als `22b1274a` sequenziell integriert.
  Root hat den tatsächlichen Diff des neuen `CoachDiagnosticHistoryService`
  gegen die entfernten Server-Funktionen geprüft: SQL-Read auf 20 Zeilen,
  40 Schritte, acht Frames, Status-/Tool-/Fehler-Whitelists und gehashte
  Turn-ID bleiben erhalten. Malforme Receipt-Felder werden enger begrenzt.
  Kein `server`-Rückimport, kein zusätzlicher Lock/Cache und kein
  Server-Callback mit Diagnose-Fachlogik. **PASS** für den Worker-Patch.
- Root-Integration (noch uncommitteter Diff nach `22b1274a`): alte
  Diagnose-Helfer und Public-Wrapper in `server.py` entfernt, konkrete
  Service-Konstruktion und drei direkte Testaufrufer migriert. Der
  `develop`-Abgleich ergänzt die explizite Garmin-30-Tage-Toolbeschreibung
  und entfernt den obsolete Bootstrap-Reset der abgeschafften automatischen
  Morgenroutine; ein Test bestätigt, dass manueller Status erhalten bleibt.
  Die vier Worker-Direkttests und 96 kombinierte Diagnose-/DB-/Dialogtests,
  ein Tool-Schematest, drei Architekturtests, Ruff auf betroffenen Backend-
  Dateien, Compile, Inventar-Check und `git diff --check` **PASS**.
  Gesamtsuite auf diesem erweiterten Stand: 2.242 Tests, 12 Skips,
  **PASS** in 230,330 s. Root-Diff-/Code-Review nach dem Gesamtlauf:
  **PASS** für die integrierte P9.1-Diagnosehistorie und den `develop`-
  Abgleich. Eine spätere Änderung am betroffenen Umfang erfordert ein
  erneutes Review. Veröffentlichung und finaler Zielbranch-Merge offen.
- Inventar nach Root-Integration: `server.py` 6.975 physische Zeilen,
  315 Definitionen, 715 Einträge. Die fünf neuen/umbenannten
  Kompositionssymbole sind explizit zugeordnet, P0 wieder null. In P9
  verbleiben 21 Definitionen und sechs globale Bindungen; Diagnosebericht,
  Logprojektion, Backup und Privacy sind weiter offen.

## Publikationsabgleich mit `develop` (Root)

- Frischer Publikations-Worktree `refactor/server-extraction-publish-20260923`
  aus geprüftem Commit `f2a9f7f`; Zielbranch beim Merge
  `origin/develop` = `232d6cc` (v1.11.11). Der alte Publikations-Worktree
  mit ungelöstem Merge bleibt unangetastet. `git merge --no-ff --no-commit
  -X ours origin/develop` erzeugte keine unaufgelösten Konflikte; der
  tatsächliche staged Diff wurde mit den Zielbranch-Änderungen verglichen.
- Erstes Root-Diff-Review **FAIL**: Das automatische Zusammenführen ließ
  `GARMIN_AUTOMATIC_SYNC_DAYS` neben dem bereits importierten Backend-
  Eigentümer doppelt stehen und übernahm `mark.assert_not_called()` ohne
  passendes Patch-Ziel. Root entfernte die doppelte Konstante und patcht
  `DailySyncMarkerService.mark` als tatsächlichen Aufrufpfad. Alle übrigen
  Zielbranch-Änderungen an Review-Gate, Abhängigkeiten, Dockerfile,
  README und CI-Vertrag wurden übernommen; die fachlichen Sync-/Morning-
  Änderungen waren bereits in konkreten Backend-Eigentümern integriert.
- 26 gezielte Python-Tests einschließlich historischem Intervals-Sync,
  Bootstrap und CI-Vertrag sowie 45 Node-Vertragsprüfungen **PASS**;
  Inventargenerator/-Check und `git diff --check` **PASS**. Nach Korrektur
  vollständige Suite: 2.242 Tests, 12 Skips, **PASS** in 218,983 s;
  isolierter Docker-Build **PASS** (Image-Digest
  `sha256:87077b71f075a8afb07e9593f68c697b127ba4895fc555aaa397d6ed12058a21`).
  Erneutes Root-Review des tatsächlichen staged+unstaged Merge-Diffs:
  **PASS**; die zwei FAIL-Befunde sind behoben und die Zielbranch-
  Fachverträge erhalten. Merge-Commit, finaler PR-Diff, CI und GitHub-
  Review stehen noch aus; spätere Änderungen benötigen erneute Prüfung.

- Finaler Veröffentlichungsbranch `refactor/server-extraction-foundation-20260923`
  wurde direkt von `origin/develop` `232d6cc` erzeugt. Der gestagte
  Squash-Diff hat denselben vollständigen Quellbaum wie der geprüfte
  Integrationscommit `3797c07` (`git diff --cached --quiet 3797c07`:
  **PASS**); lediglich dieser Review-Log-Nachtrag kommt danach hinzu.
  Damit werden keine historischen Zwischenstände oder veralteten
  Zielbranch-Dateien in den PR getragen. Der endgültige Code-Diff ist
  gegenüber dem getesteten Stand unverändert; `git diff --cached --check`,
  Inventar-Check und Compile **PASS**. PR, CI, Codex-Review und Merge
  sind noch offen.

## PR #706 — CI-Folgeprüfung (Root)

- GitHub-Head `d0ee5f8`: vier Test-Shards, CodeQL, Syntax, SBOM und
  Conventional-Commit-Gate **PASS**. Container-Unit-Tests **FAIL** mit
  genau drei `FileNotFoundError`-Befunden: AST-Architekturtests suchten
  Backend-Quelltext relativ zu `/review/tests`, während das Image die
  importierten Module unter `/app/backend` enthält. Root stellte nur
  die Quellpfad-Auflösung der drei Tests auf `inspect.getfile` der
  tatsächlich importierten Serviceklasse um; AST-Prüfungen und
  Assertions bleiben unverändert. 26 gezielte lokale Tests und die
  exakt nachgestellte read-only Container-Suite (2.242 Tests,
  10 Skips) **PASS**. Code-Diff **PASS**; CI-Neulauf ausstehend.
- SonarCloud Code Analysis **FAIL** mit 46 neuen Code-Smells, darunter
  Komplexität, zu breite Konstruktoren und duplizierte Literale in
  ausgelagerten Modulen und Inventarskript. Keine Regel oder Prüfung
  wird umgangen; Befunde werden fachlich geprüft und in unabhängigen
  Schreibbereichen korrigiert. Auto-Merge bleibt deaktiviert.

## PR #706 — Sonar-Korrekturen und erneutes Root-Gate

- `d99d643` behebt ausschließlich die Container-Quellpfade der drei
  AST-Tests. Der CI-Containerlauf auf diesem Head ist **PASS**; der
  Codex-Bot meldete für den vorherigen Stand `d0ee5f8` keine größeren
  Codeprobleme. Der aktuelle Pflichtcheck ist weiterhin rot, weil die
  abgeschlossene Bot-Reaktion nicht dem neuen Head zugeordnet ist.
- Worker-Diffs `3dcfd33` (Provider), `7603c667` (Inventar), `94dfbab`
  (Sync) und `ccf1193` (SQL-Literale/Coach-Bindung) wurden von Root
  tatsächlich geprüft und sequenziell als `6133b6c`, `e786e8b`,
  `f980be7`, `c4795fa` integriert: **PASS**. Öffentliche Schnittstellen,
  DB-/Hash-Rechecks, Lock- und Fehlerpfade sind unverändert. Der eigene
  Kontext-Diff `6ce1fb5` wurde auf Auswahlreihenfolge und Kürzungsgrenzen
  geprüft: **PASS**. Dies ist noch kein vollständiger P2/P7-Abschluss.
- Nach Integration: 3 Inventar-/Architekturtests, 109 Provider-Tests,
  34 Sync-Tests, 145 Planning-/Kalender-/Coach-Tests und 9
  Coach-Katalog-/Architekturtests **PASS**; Compile, Ruff für geänderte
  Module, Generator-Check und Diff-Check **PASS**. Gesamtsuite auf
  `c4795fa` plus `6ce1fb5` und diesem Log-Nachtrag: 2.242 Tests,
  12 Skips, **PASS** in 211,574 s. Abschließendes Root-Code-Review
  der integrierten Sonar-Patches **PASS**. Neuer Sonar-Lauf steht aus.
  Rest-Risiken:
  komplexe Fachmethoden und Konstruktoren, offener Review-Pflichtcheck.

## PR #706 — zweite Sonar-Runde (integrierter Zwischenstand)

- Auf `b495ffe` sind die vier Test-Shards, Container-Unit-Tests und der
  Codex-Pflichtcheck **PASS**. SonarCloud meldet nun 26 statt 46 neue
  Befunde; Browser-Check und übrige technische Gates waren zuletzt
  grün. Der PR bleibt **OPEN/BLOCKED**, Auto-Merge aus.
- Root-Diff `51d0481`: ungenutzten Parameter aus `SyncStateRepository`
  und allen Aufrufern entfernt; HTTP-Fehlerdetails nach Provider
  abgegrenzt, ohne Status-/Redaktions-/Retry-Vertrag zu ändern.
  7 Sync-State-, 2 Server- und 109 Provider-Tests, Ruff/Compile/Diff:
  **PASS**. Code-Review **PASS**.
- Worker-Diffs `bfcd3bf` (Body-Battery und Planersatz), `a8a2bb1`
  (Plan-Auswahl und Remote-missing-CAS), `bb4cce5` (Restore-Sichtbarkeit)
  und `8574135` (Gemini-Historie/Normalisierung) wurden am tatsächlichen
  Code und Diff von Root geprüft: **PASS**. Sequenziell integriert als
  `8e554b7`, `6e4ad45`, `356bc83`, `cecad30`. Die zugehörigen
  46, 21, 55 und 74 fokussierten Tests sowie Ruff im geänderten Umfang
  **PASS**; bestehende Ruff-Funde in unveränderten Conversation-Zeilen
  sind dokumentiert, nicht unterdrückt oder als behoben ausgegeben.
- Root-Diff `c4611a2`: Sync-Job-Normalisierung, Ergebniszuordnung und
  Hash-Erzeugung innerhalb von `backend/sync/jobs.py` fachlich getrennt;
  dieselbe DB-Transaktion, Redaction, Retry-/Status- und JSON-Fehlerpfade
  bleiben erhalten. 34 Job-/Outcome-Tests, Ruff, Compile und Diff **PASS**;
  Root-Code-Review **PASS**. Die Gesamtsuite und neue Sonar-Analyse
  stehen für diesen erweiterten Stand noch aus.
- Worker-Diff `195eb73` der täglichen Planungskontext-Projektion von Root
  am tatsächlichen Code geprüft und sequenziell als `d5bd759` integriert:
  **PASS**. Öffentliche Signatur, Kalenderfenster, Feldselektion,
  Sortierung und Bereinigung bleiben unverändert; die neue Regression
  erhält instruction-artigen Terminnamen als wörtliche Daten. 21 direkte
  Planungs-/Kalendertests und Diff-Check **PASS**. Ein erster lokaler
  Testaufruf enthielt zwei nicht existierende Modulnamen und wurde mit
  den tatsächlichen Testmodulen erfolgreich wiederholt. Gesamtsuite
  für den integrierten Stand **PASS**: 2.242 Tests, 12 Skips in
  206,184 s. Der Root hat den Gesamt-Diff `b495ffe..d5bd759`
  (14 Code-/Testdateien, 512 Einfügungen, 324 Entfernungen) und dessen
  Konfliktfreiheit erneut geprüft: **PASS**. Sonar-Analyse auf dem
  veröffentlichten Head steht noch aus; dieser Review-PASS allein
  autorisiert bei rotem Pflichtcheck keinen Merge.

## PR #706 — dritte Sonar-Runde (lokal, noch unveröffentlicht)

- Auf Head `e5fa608` sind alle Unit-/Container-/CodeQL-/Codex-Gates
  grün; der neue Sonar-Pflichtcheck bleibt mit 15 New-Code-Befunden
  rot (`new_violations=15`, Grenze null). Browserprüfung lief zuletzt
  noch. Auto-Merge ist deaktiviert; `mergedAt=null`.
- GPT-6-Luna-Diff `d4fd6fe` zu zwei verbliebenen Job-Normalisierungs-
  Komplexitätsbefunden am vollständigen Diff und Code geprüft: **PASS**.
  Die Helfer erhalten Validierungsreihenfolge, Fehlermeldungen,
  Trunkierung, Eindeutigkeit und kanonischen Hash; Transaktion und
  Persistenz bleiben beim `SyncJobStore`. Sequenziell als `0985f4b`
  integriert. 45 Job-/Outcome-/Queue-Tests, Ruff und Diff-Check **PASS**.
  Ein erster Testaufruf verwendete einen nicht existierenden Modulnamen;
  der korrigierte Aufruf ist grün. Gesamtsuite für `0985f4b`
  **PASS**: 2.245 Tests, 12 Skips in 198,199 s. Root-Review des
  aktualisierten Code-Diffs nach Integration erneut **PASS**.
- Offen bleiben neun S107-Konstruktoren sowie vier S3776-Methoden in
  `server.py`. Diese werden nicht per Sonar-Unterdrückung oder
  kosmetischen Callback-Bags behandelt, sondern mit den zuständigen
  P6/P7/P10-Use-Cases zusammengeführt.
- GPT-6-Luna-Diff `4de41d3` (`WeatherService`) von Root am tatsächlichen
  Code und Diff geprüft: **PASS**. `WeatherCacheStore` besitzt den
  Standort-Recheck und atomare Cache-/History-/Failure-Transaktionen;
  `WeatherRefreshJournal` besitzt Operation-Tracking und sichere Logs.
  Wetter-Lock, Maintenance-Gate, Retry und Rückgabeform bleiben beim
  Use-Case. Sequenziell als `9803c30` integriert; 14 direkte Wetter-,
  Server- und Architekturtests sowie Ruff/Diff **PASS**. Ein zunächst
  falsch benannter Testaufruf wurde mit vorhandenen Testnamen wiederholt.
  Gesamtsuite nach Wetterintegration **PASS**: 2.246 Tests,
  12 Skips in 211,745 s; erneuter Root-Code-Gate **PASS**. Neuer
  Sonar-Head steht noch aus. Die vor dem Patch gemeldeten 13 Befunde
  bleiben bis zur neuen Analyse offen.
- Root-Diff `f18217f`, sequenziell als `662615c` integriert:
  `CoachContextPreviewService` verwendet die bereits vom strukturierten
  Kontext erzeugte, begrenzte Intervals-Projektion, statt Snapshot,
  Planungen und Tageszeit nochmals zu lesen. Eine unveränderliche
  Budget-Policy fasst ausschließlich die vorhandenen Grenzen zusammen;
  die Abschnittsgrenzen werden weiter defensiv kopiert. Der Root hat
  Diff und Code auf Daten-/Datenschutzgrenzen, Feldform und fehlende
  Server-Rückimporte geprüft: **PASS**. Vier direkte Preview-/Server-
  Tests, Ruff, Compile und Diff **PASS**. Gesamtsuite für diesen
  erweiterten Stand **PASS**: 2.246 Tests, 12 Skips in 211,726 s.
  Erneuter Root-Diff-/Code-Gate für `9803c30..662615c` **PASS**.
  Sonar und GitHub-Gates müssen auf dem aktualisierten PR-Head neu
  laufen; bis dahin bleibt der PR offen und Auto-Merge aus.
- Sonar auf Head `4b99cde` meldet elf statt 13 New-Code-Befunde;
  Wetter und Kontextvorschau sind nicht mehr betroffen. Sieben
  Konstruktoren und vier Server-Orchestrierungen bleiben offen.
- Root-Diff `4a5f2dd`, sequenziell als `7940314` integriert:
  `CoachPlanningContextReader` besitzt lokale Plan-/Kalenderprojektion,
  `CoachPerformanceContextReader` Profil-/Providerprojektion;
  `CoachStructuredContextService` koordiniert sechs konkrete Quellen.
  Der Root hat die tatsächlichen Aufrufpfade und den Diff auf
  wiederholte autoritative Reads, unveränderte Quellenlabels,
  Datensparsamkeit und fehlende Server-Rückimporte geprüft: **PASS**.
  Sieben gezielte Struktur-/Preview-/Server-Tests, Ruff, Compile und
  Diff-Check **PASS**. Gesamtsuite für `7940314` **PASS**: 2.246 Tests,
  12 Skips in 208,403 s; Root-Code-Gate erneut **PASS**. Der neue
  Sonar-Lauf steht noch aus.

## P7.19 — strukturierte Coach-Sync-Werkzeuge

- Root-Diff `268df22`, sequenziell als `5dcf937` integriert: Der neue
  konkrete `CoachSyncToolService` besitzt Plan-Push, Job-Lookup,
  Wettkampf-Push und Konfliktwiederholung samt Scope-/Target- und
  Remote-Write-Prüfung. `server.py` komponiert die sechs betroffenen
  Dienste und ruft den Besitzer nur für diese vier Toolnamen; die
  bisherige Fachorchestrierung ist entfernt, ohne Server-Callbacks.
  Sync-Use-Cases behalten Transaktion, Revision/Hash und Queue-
  Eigentümerschaft; Sync-Job-IDs bleiben turn-lokal. Root-Diff- und
  Code-Review der Berechtigungs- und Schreibgrenzen **PASS**.
- Vier neue direkte Sicherheitsregressionen und 68 Dialogregressionen
  **PASS** (72 gesamt), Ruff, Compile, Diff- und Inventar-Check
  **PASS**. Die Gesamtsuite dieses erweiterten PR-Stands ebenfalls
  **PASS**: 2.250 Tests, 12 Skips in 207,822 s. Erneuter Root-Code-
  Review des integrierten P7-Diffs **PASS**. Inventar: `server.py`
  6.929 Zeilen; P7 103 Definitionen/31
  globale Bindungen, also weiterhin offen.

## PR #706 — OpenAI-Stream-Telemetry-Gate

- Erstes GPT-6-Luna-Diff `6cab84a` nach tatsächlichem Root-Diff-/Code-
  Review **FAIL**: ein neuer generischer Failure-Dispatcher hatte zu
  viele Parameter und vermischte mehrere Status-/Usage-Pfade. Der
  konkrete Korrekturauftrag ging an denselben Worker; keine Integration
  des unzureichenden Einzelstands.
- Korrektur-Diff `a6a2d67` mit fachlich getrennten HTTP-, Timeout-,
  Netzwerk-, Cancel-, Disconnect- und AppError-Telemetry-Pfaden erneut
  am tatsächlichen Code geprüft: **PASS**. HTTP-Rate-Limits werden vor
  dem Error-Body-Read persistiert; Status, Log und redigierte Diagnose
  bleiben in ihrer Reihenfolge. `OpenAIStreamClient` besitzt weiterhin
  SSE-Transport, Retry, Abbruch, Byte-/Handle-Grenzen und finale
  Response-Validierung; keine Server-Rückimporte oder Callback-Fachlogik.
- Beide Worker-Commits sequenziell als `35a211d` und `25cb5ac`
  integriert. Root hat den einzigen alten Server-Test auf die konkrete
  Telemetry-Eigentümerschaft umgestellt. 76 Provider-, Architektur-
  und Server-Tests, Ruff, Compile, Diff- und Inventar-Check **PASS**.
  Die Gesamtsuite des erweiterten lokalen Stands **PASS**: 2.251 Tests,
  12 Skips in 211,476 s. Erneuter Root-Code-Review des integrierten
  Patches einschließlich Testanpassung **PASS**. Die Sonar-Prüfung des
  veröffentlichten Stands steht noch aus. Inventar aktuell: `server.py` 6.933 Zeilen; P2 elf
  Definitionen/sieben globale Bindungen (P2 weiterhin offen).

## P7.20 — Coach-Provider-Refresh-Werkzeuge

- Root-Diff `2ad652e`, sequenziell als `3dea5f9` integriert und am
  tatsächlichen integrierten Code erneut geprüft: **PASS**. Der
  `CoachSyncToolService` besitzt jetzt auch Autorisierung, Scope-
  Prüfung, Provider-Refresh, Performance-Refresh und turn-lokale
  Job-ID-Buchführung. Der Server komponiert den konkreten Refresh-
  Dienst und reicht das unveränderte Cancel-Event weiter; die beiden
  Fachzweige wurden aus `_structured_coach_tool_result` entfernt.
  Keine Server-Rückimporte oder Callback-Fachlogik; Remote-Write-
  Grenzen und synchrone-vs.-queued Semantik bleiben erhalten.
- Sechs direkte Service- und 68 Dialogtests, Ruff, Compile, Diff- und
  Inventar-Check **PASS**. Gesamtsuite für den integrierten Stand
  `3dea5f9`: **PASS**, 2.253 Tests, 12 Skips in 221,691 s. Inventar:
  `server.py` 6.917 Zeilen, P7 weiterhin 103 Definitionen/31 globale
  Bindungen; P7 ist nicht abgeschlossen. Sonar-Prüfung erst nach Push.

## PR #706 — Morning-Body-Battery-Eigentümer

- Erstes GPT-6-Luna-Diff `bf952c2` am tatsächlichen Code geprüft:
  **FAIL**, weil `exc_info=True` beim Refresh-Fehler ohne fachlichen
  Grund in ein Exception-Tuple geändert und der Test entsprechend
  abgeschwächt war. Konkreter Korrekturauftrag an denselben Worker.
- Korrektur-Diff `a3d5a35` und gesamter Patch erneut geprüft: **PASS**.
  `MorningBatteryStore` besitzt atomare Snapshot-/History-/Fehler-
  Writes; Source besitzt Fixture/Remote und sichere Fehlerprojektion;
  ExecutionGate besitzt Lock-/Maintenance-/Provider-Reihenfolge;
  Events besitzen Veröffentlichung und unverändertes Exception-
  Logging. Der Service besitzt Freshness, Retry und Ablauf. Kein
  Server-Rückimport und keine ausgelagerte Fachlogik im Factory-Callback.
- Sequenziell als `e20dff9` und `8f13be5` integriert. Zehn direkte
  Service-, 14 Diagnose- und einschlägige Server-/Architekturtests,
  Ruff, Compile und Diff-Check **PASS**. Gesamtsuite für `8f13be5`
  **PASS**: 2.253 Tests, 12 Skips in 217,816 s. Root-Review des
  integrierten Stands erneut **PASS**. Inventar: `server.py` 6.926
  Zeilen; P2 weiterhin elf Definitionen/sieben globale Bindungen.
  Sonar-Prüfung nach Veröffentlichung ausstehend.

## P7.21 — adaptive Coach-Freigabe

- Root-Diff `637a909`, als `13a048c` sequenziell integriert und im
  integrierten Code selbst geprüft: **PASS**. Der konkrete
  `CoachAdaptiveApplyService` besitzt Scope-/Target-Autorisierung,
  Preview-Freshness und die spätere, quellgebundene Nutzerfreigabe
  vor dem lokalen Apply und jedem optionalen Intervals-Schreiben.
  `DB_LOCK` und DatabaseManager-Transaktion bleiben dieselben
  Eigentümer; `server.py` komponiert nur die Abhängigkeiten und trägt
  weder die Approval-Abfrage noch einen Fachcallback. Eager erzeugte
  Provider-Objekte führen keine Remote-I/O aus; Schreibgrenzen sind
  weiterhin erst nach der Freigabe erreichbar.
- Drei direkte Approval-Regressionen, 27 Coach-Tool-Coverage- und drei
  Architekturtests, Ruff, Compile und Diff-Check **PASS**. Gesamtsuite
  des integrierten Stands `13a048c` **PASS**: 2.256 Tests, 12 Skips
  in 254,981 s. Erneutes Root-Review **PASS**. Inventar: `server.py`
  6.914 Zeilen, P7 102 Definitionen/31 globale Bindungen; P7 bleibt
  offen. Sonar-Prüfung nach Push ausstehend.

## PR #706 — Sync-Job-Executor-Eigentümer

- GPT-6-Luna-Diff `f485cc9`, sequenziell als `b983c30` integriert.
  Root hat den tatsächlichen Worker-Diff und die integrierte Factory
  einschließlich aller Provider-Routen, Plan-Push-Grenze, historischen
  Backfill-Continuation, Morning-Followup, Outcome und Gate-/Lock-
  Eigentümern geprüft: **PASS**. `HistoricalSyncJobOwner`, konkrete
  Provider-Owner und Dispatcher halten Fachabläufe; `SyncJobExecutor`
  normalisiert den Job und persistiert das Outcome. Keine Server-
  Rückimporte oder fachtragenden Callbacks.
- 31 direkte Sync-/Queue-/Worker-/Architekturtests, 15 Provider-
  Regressionen (ein Skip) und sieben gezielte Server-Jobtests, Ruff,
  Compile und Diff-Check **PASS**. Ein anfänglich falsch benannter
  Testmodulaufruf und ein separater Importversuch ohne den erforderlichen
  Test-Suchpfad waren reine Aufruffehler; die identischen gültigen
  Auswahlen liefen anschließend grün. Gesamtsuite und Sonar-Prüfung
  des erweiterten Stands stehen noch aus.

## PR #706 — Full-Resync-Eigentümer

- Erstes GPT-6-Luna-Diff `cb6ee3d` im tatsächlichen Code **FAIL**:
  die Cleanup-Bedingung war versehentlich an eine wahrheitswertige
  Operations-ID gekoppelt. Korrekturauftrag an denselben Worker;
  Korrektur-Diff `b848fbd` mit Empty-ID-Regression erneut geprüft:
  **PASS**. Beide Commits sequenziell als `7b9682b` und `23d5d79`
  integriert und am integrierten Code erneut geprüft: **PASS**.
  Konkrete Eigentümer besitzen Provider/Gates, dauerhaften KV-/DB-
  Status und Operation-Journal/Redaction. Status-Cleanup, Gate-Release,
  Context-Reset und Ereignisfolge auch bei Fehlern bleiben erhalten;
  keine Server-Rückimporte oder fachtragenden Callbacks.
- Zwölf direkte Full-Resync-, drei Architektur- und sechs gezielte
  Server-Resync-Regressionen, Ruff, Compile und Diff-Check **PASS**.
  Gesamtsuite und Sonar-Prüfung des erweiterten Stands stehen noch aus.

## PR #706 — Garmin-Sync-Lifecycle-Eigentümer

- Erstes GPT-6-Luna-Diff `4a76c7a` im tatsächlichen Code **FAIL**:
  der Fixture-Fallback für das Sync-Enddatum war von der lokalen Uhr
  auf potentiell alte/fehlende Fixture-Metadaten umgestellt worden.
  Korrekturauftrag an denselben Worker; Korrektur-Diff `8ff5932`
  samt Regression für alte und fehlende Datumsfelder erneut geprüft:
  **PASS**. Beide Commits sequenziell als `a645d43` und `28a8834`
  integriert und den integrierten Pfad erneut geprüft: **PASS**.
  Quelle, gemeinsames Garmin/Morning-Lock und Provider-Gate sowie
  Status-/Timestamp-/Log-Besitzer sind fachlich getrennt. Die Fixture-
  Uhr wird wieder nach Payload-Vorbereitung gelesen; Snapshot-/Fehler-
  Persistenz, Cancellation und Redaction bleiben erhalten. Keine
  Server-Rückimporte oder fachtragenden Factory-Callbacks.
- Neun direkte Garmin-, drei Architektur- und vier gezielte Server-
  Regressionen, Ruff, Compile und Diff-Check **PASS**. Gesamtsuite
  und Sonar-Prüfung des erweiterten Stands stehen noch aus.

## PR #706 — kombinierter Integrationsstand nach Garmin

- Integrierter Stand `28a8834` (Executor `b983c30`, Full-Resync
  `7b9682b`/`23d5d79`, Garmin `a645d43`/`28a8834`) im tatsächlichen
  Code erneut auf Provider-Routen, geteilten Lock, Gate-Reihenfolge,
  Backfill, Fixture-Datum, Cleanup, Cancellation, Transaktion und
  Remote-Schreibgrenzen geprüft: **PASS**. Alle betroffenen direkten,
  Architektur- und Server-Regressionen oben **PASS**; kombinierte
  Gesamtsuite **PASS**: 2.259 Tests, 12 Skips in 231,630 s.
  Inventar: `server.py` 6.952 Zeilen; P7 102 Definitionen/31 globale
  Bindungen. Zeilenzunahme durch Composition-Factories zählt nicht
  als Phasenabschluss. Sonar/CI des nächsten veröffentlichten Heads
  noch ausstehend.

## P7.22 — atomare Coach-Profiländerung

- Root-Diff `58051bb`, sequenziell als `46523cb` integriert und am
  integrierten Code erneut geprüft: **PASS**. Der konkrete
  `CoachProfileUpdateService` besitzt Scope-Prüfung, Feld- und
  Duplikatvalidierung, Expected-Value-Konfliktprüfung und atomaren
  Gesamtbatch vor `ProfileService.save`. Bestehende `DB_LOCK`-/UOW-
  Eigentümer und unveränderte ProfileService-Audit-/Cache-Invalidierung
  bleiben erhalten; der Server komponiert nur und trägt weder den
  Business-Loop noch einen Fachcallback.
- Drei direkte Profil-, drei Architektur- und 68 Dialogregressionen,
  Ruff, Compile, Diff- und Inventar-Check **PASS**. Gesamtsuite für
  `46523cb` **PASS**: 2.262 Tests, 12 Skips in 223,005 s. Root-Code-
  Review erneut **PASS**. Inventar: `server.py` 6.932 Zeilen, P7
  101 Definitionen/31 globale Bindungen; P7 ist weiterhin offen.
  Sonar/CI des veröffentlichten Stands noch ausstehend.

## PR #706 — Intervals-Lifecycle, Coach-Aktivitätslesen und HTTP-Sync

- GPT-6-Luna-Intervals-Diff `bbb72f61` zunächst **FAIL**: Der Waiter
  hätte den rohen persistierten `last_sync_error` in eine API-Meldung
  übernommen. Korrektur `0fefd5c7` mit Redaction-Regression erneut
  im tatsächlichen Code geprüft: **PASS**. Sequenziell als `65cdb3c0`
  und `b1a4a403` integriert. Status-/Journal-/Runtime-Eigentümer
  besitzen den äußeren Observer, Lock, Gate, persistierte Fehler und
  Wait-Semantik ohne Server-Rückimport. 13 Flow-/Architektur- und fünf
  Server-Regressionen **PASS**.
- GPT-6-Luna-P7-Aktivitätslese-Diff `fdb5827a` im tatsächlichen Code
  **PASS**, als `27c3ad09` integriert. Vier direkte, drei Architektur-,
  ein Server-Detail- und 27 Coach-Tool-Regressionen **PASS**. Die
  Aktivitätslesefunktionen und zugehörige Auswahl liegen im konkreten
  Coach-Use-Case; übrige P7-Definitionen bleiben offen.
- Root-P10-HTTP-Sync-Diff `9f48ba7` im tatsächlichen Code **PASS**,
  als `2f9be5ef` integriert. `SyncCommandEndpoint` besitzt Perioden-
  validierung, Queue-/Bestätigungsentscheidungen und Full-Resync;
  `_handle_sync_post` beschränkt sich auf Transport/Body/Antwort.
  Fünf direkte und drei Architekturtests **PASS**. Ein anfängliches
  Top-Level-`import server` im neuen Testmodul verletzte die isolierte
  Testinitialisierung: Korrektur `034fb702` als `635cd960` integriert,
  Handler-Regressionsfall nach `test_server.py` verschoben.
- Der erste breite Lauf dieses Stands war **FAIL**: Ein älterer Test
  patchte nach dem Intervals-Umzug weiterhin `service._get_value`,
  brach nach Lock-Erwerb ab und verursachte Folgefehler/Hänger.
  Root-Korrektur `c184b06d` patcht `service._status.get` und erwirbt
  den Lock erst nach Aufbau des Beobachtungspunkts. Einzeltest **PASS**;
  vollständige integrierte Suite auf `c184b06d` **PASS**: 2.274 Tests,
  12 Skips in 221,892 s. Damit sind die korrigierten Pfade am
  integrierten Code erneut geprüft; P7 und P10 bleiben offen.

## PR #706 — P10 lokaler Bootstrap- und Wetter-Vorlauf

- Root-Diff `f3820d2d` nach tatsächlichem Code-/Diff-Review **PASS**,
  als `f7f8d521` integriert. `PublicStateLocalPrelude` hält die
  vorhandene gemeinsame DB-UOW unter `DB_LOCK` für Snapshot,
  Aktivitätsfeedback, geplante Einheiten und Offline-Wetter ein;
  `PublicStateWeatherPrelude` aktualisiert Provider-Wetter und löst
  Adaptive-Follow-up erst außerhalb dieses Locks aus. Kein
  Server-Rückimport, kein fachtragender Server-Callback; `public_state`
  enthält allerdings noch weitere Projektionen und ist nicht fertig
  ausgelagert. Neun gezielte und vier Architekturtests, Compile,
  Ruff für die neuen Module und Diff-Check **PASS**. Vollständige
  integrierte Suite auf `f7f8d521` **PASS**: 2.276 Tests, 12 Skips
  in 225,183 s. Sonar/CI des erweiterten Stands stehen noch aus.
- Inventar nach `f7f8d521`: `server.py` 6.862 Zeilen,
  318 Definitionen; P7 101 Definitionen/31 globale Bindungen,
  P10 25 Definitionen/37 globale Bindungen. Diese Zahlen sind keine
  fachliche Fertigmeldung. Die ältere `test_coach_review.py` hat
  bestehende Ruff-Stilbefunde; die oben betroffenen neuen Module
  bestehen Ruff. Nächster Schritt: aktuellen PR-Head gegen `develop`
  prüfen, veröffentlichen, Sonar/CI auswerten und die verbleibende
  P10-Projektion weiter auslagern.

## PR #706 — CI- und Sonar-Korrektur nach `f249f9a6`

- Veröffentlichter Head `f249f9a6`: lokaler Integrationsreview **PASS**,
  aber CI-Review-Gate **FAIL**. Der Container-Architekturtest suchte den
  Backend-Quellbaum unter `/review/backend`, obwohl CI nur Tests und
  `server.py` nach `/review` mountet und den Backend-Code aus dem Image
  unter `/app/backend` bereitstellt. Damit war zuvor auch der statische
  Backend-Importgraph-Guard im Container leer gelaufen. Root-Korrektur
  wählt den tatsächlich vorhandenen Backend-Quellbaum und fordert
  dessen Existenz ausdrücklich. Tatsächlichen Testdiff geprüft:
  **PASS**; vier lokale Architekturtests, Ruff und exakt nachgebildete
  Read-only-Container-Suite **PASS** (2.276 Tests, 10 Skips in 22,591 s).
- SonarCloud des veröffentlichten Heads meldete fünf neue
  `python:S1192`-Befunde in `backend/http_api/sync_commands.py`, keine
  verbliebenen S107-/S3776-Befunde. Root-Korrektur ersetzt ausschließlich
  die wiederholten fünf Sync-Routenliterale durch benannte Konstanten;
  Route-Menge, Body-Policy und Dispatch bleiben unverändert. Code-/Diff-
  Review **PASS**; fünf direkte/Handler-Regressionen, vier Architektur-
  tests, Ruff und die neu gebaute Container-Suite **PASS**. Sonar/CI
  dieses Korrekturstands müssen nach Veröffentlichung erneut bestehen.

## P10 — Kalender- und Tageskontext-Bootstrap

- Erstes GPT-6-Luna-Diff `cd2b5996` anhand des tatsächlichen Codes
  **FAIL**: Der neue Service berechnete die schon vom lokalen Prelude
  bereitgestellte kanonische Planliste erneut und konnte damit einen
  anderen Snapshot an den Tageskontext übergeben. Konkreter Auftrag an
  denselben Worker; Korrektur `4ea53759` entfernt die zweite Projektion
  und übergibt `prelude.canonical_planned` unverändert. Regression prüft
  die Objektidentität. Beide Diffs erneut geprüft: **PASS**.
- Sequenziell als `00fb89c0`/`3f8b5a9d` auf dem bestätigten PR-#706-
  Merge-Commit `45dd27f2` integriert und die tatsächliche Codegrenze
  erneut geprüft: **PASS**. `PublicStateCalendarProjection` besitzt
  Check-in-/Wettkampf-/externe Kalender-/Tageskontext-Orchestrierung;
  der vorhandene `DB_LOCK` und dieselbe UOW umschließen den Aufruf.
  Keine Server-Rückimporte oder Fachcallbacks, JSON-Felder und Offline-
  Bootstrap-Grenzen unverändert. `public_state` enthält weitere offene
  Projektionen, daher bleibt P10 unvollständig.
- Worker nach Korrektur: direkter Test 1, Server 462/3 Skips,
  Architektur 4, volle Python-Suite 2.277/12 Skips, Ruff der neuen
  Dateien, Compile und Diff-Check **PASS**. Im integrierten Worktree:
  vier fokussierte, vier Architekturtests, Ruff, Compile und Diff-
  Check **PASS**. Neu gebautes Read-only-Container-Image und volle
  Container-Suite **PASS**: 2.277 Tests, 10 Skips in 20,464 s.
  Inventar: `server.py` 6.861 Zeilen; P10 weiterhin 26 Definitionen
  und 37 globale Bindungen. Die neue Factory erhöht die Definitionszahl,
  ohne den ausgelagerten fachlichen Ablauf wieder in den Server zu holen.
  CI/Sonar des veröffentlichten PR-Stands bleiben abzuwarten.
## PR #706 — bestätigter Merge

- Korrektur-Head `af77f5a5`: Root-Code-/Diff-Review **PASS**,
  vollständige Windows-Suite 2.276 Tests/12 Skips **PASS** und
  Read-only-Container-Suite 2.276 Tests/10 Skips **PASS**. Alle GitHub-
  Checks einschließlich Browser/Accessibility und SonarCloud bestanden;
  Quality Gate `OK`, `new_violations=0`, keine ungelösten Review-Threads.
  Squash-Auto-Merge erst danach aktiviert. PR #706 ist laut GitHub
  `MERGED` seit 2026-09-23T12:09:29Z, Merge-Commit
  `45dd27f2848fc046ff8fa426339c222bdf12cc85` ist auf
  `origin/develop` erreichbar. Das schließt nicht die weiterhin offenen
  Planphasen P2/P6/P7/P8/P9/P10/P11.

## P9 — datensparsame Logprojektion

- GPT-6-Luna-Diff `6f4463b6` im tatsächlichen Code geprüft: **PASS**.
  Sequenziell als `2d27cd3b` auf dem bestätigten `develop`-Merge
  integriert und erneut geprüft: **PASS**. `RecentLogEntriesService`
  besitzt Tail, JSON-Fallback, OSError-Projektion und Redaction;
  `server.py` komponiert nur noch den dynamischen Logpfad. Diagnosebericht,
  HTTP-Route und sieben bestehende Server-Tests verwenden den neuen
  Lookup; kein Server-Rückimport, Fachcallback oder Alt-Wrapper.
- Worker: drei direkte und vier Architekturtests, Ruff der neuen Dateien,
  Compile/Diff-Check sowie volle Python-Suite **PASS** (2.279 Tests,
  12 Skips in 312,020 s). Auf integriertem Stand: vier fokussierte
  Service-/Server- und vier Architekturtests, Ruff der neuen Dateien,
  Compile und Diff-Check **PASS**. Dateiweite Legacy-Ruff-Befunde in
  `server.py` (26) und `tests/test_server.py` (182) sind gegenüber der
  Basis unverändert. Neu gebautes Image und exakte Read-only-Container-
  Gesamtsuite auf `2d27cd3b` **PASS**: 2.279 Tests, 10 Skips in
  19,993 s. CI/Sonar dieses PR-Stands stehen noch aus; Diagnosebericht,
  Capture und Privacy-/Backup-Pfade bleiben P9-Risiken.

## P10 — erneuter Integrationsstand nach PR #707

- Vor Veröffentlichung `origin/develop` mit bestätigtem PR-#707-Merge
  `ff0bd755db41c1a58bfce8333e3fbe4f2cc835ac` in den P10-Branch
  übernommen (`c07b6a4c`). Überschneidungen im Review-Protokoll
  wurden unter Erhalt beider Befunde aufgelöst; das Inventar wurde aus
  dem kombinierten Code neu erzeugt. Root-Review von Server-Aufrufern,
  Kalender-UOW, Logprojektion und tatsächlichem Merge-Diff **PASS**.
- Sieben kombinierte fokussierte Tests, vier Architekturtests, Ruff der
  neuen Module/Tests, Compile, Inventar- und Diff-Check **PASS**.
  Neu gebautes Read-only-Container-Image: vollständige Suite **PASS**
  mit 2.280 Tests und 10 Skips in 21,223 s. Inventar:
  `server.py` 6.849 Zeilen, 319 Definitionen; P9 und P10 bleiben
  fachlich offen. Der erste veröffentlichte PR-Head scheiterte nur an
  der Conventional-Commit-Prüfung des technischen Merge-Titels.
  Der Merge wurde mit identischen Eltern und identischem Dateibaum als
  `c07b6a4c` mit gültigem Titel neu erzeugt; der folgende Docs-Commit
  wurde erneut aufgesetzt. Alter und neuer geprüfter Head haben bis
  auf diese Review-Log-ID denselben Dateibaum. CI/Sonar des korrigierten
  PR-Heads stehen noch aus.

## PR #708 — bestätigter Merge und P6-Abschlussprüfung

- PR-Head `051848b7d29ff5ed1d9f909c73b0d4f4cb6d431a` nach dem
  zuvor dokumentierten Root-Code-Review erneut geprüft: alle erforderlichen
  Checks einschließlich Browser, Container, Sonar (`new_violations=0`) und
  Codex-Review-Gate **PASS**; keine offenen Review-Threads. Der vorzeitige
  Review-Gate-Fehler wurde durch erneuten Lauf des unveränderten geschützten
  Workflows behoben, ohne eine zweite Review-Anforderung zu stellen.
  `develop` war Vorfahr des PR-Heads. Squash-Merge am
  `2026-09-23T12:35:42Z`, Commit
  `072162c3e2e4651549455d71f9177b6b75003d3d`, auf `origin/develop`
  erreichbar. Integrierte Read-only-Container-Suite zuvor **PASS**:
  2.280 Tests, 10 Skips; spätere P2-/P8-Diffs benötigen eigene Reviews.
- P6-Abschluss-Audit auf diesem gemergten Stand **PASS**: Im Inventar
  verbleiben unter P6 nur `sync_command_endpoint` und
  `coach_sync_tool_service` als reine Kompositions-Factorys sowie 15
  Konfigurationsbindungen. Die fachlichen Sync-Abläufe, Gates, Queue,
  Reconciliation, Retry und Worker liegen bei konkreten `backend/sync/`-
  Eigentümern; sämtliche P6-Unterpunkte sind bereits abgenommen.
  Die beiden Factorys und ungenutzte/duplizierte Konfiguration bleiben
  für den P11-Composition-Root-/Restcode-Audit sichtbar, nicht als
  ausgelagerte Fachlogik. P6-Hauptpunkt daher geschlossen. Rest-Risiko:
  der finale Importgraph- und Testpatch-Audit bleibt P11.

## P2 — Gemini-Antwort-Orchestrierung

- Explizit als GPT-6 Luna/high delegierter Worker-Commit
  `5a9716c2894cbe32218af71c26ca1d878517b350` im tatsächlichen
  Diff zunächst **FAIL**: Die Factory las die gespeicherte
  Default-Modellauswahl auch bei explizitem Modell und änderte damit
  Fehler-/Lock- und Latenzverhalten. Korrekturauftrag an denselben
  Worker; der finale Commit injiziert den konkreten `SettingsService`
  und liest die Auswahl nur im Fallback. Der Fake-Test belegt JSON-
  und Stream-Pfad. Erneutes Root-Code-Review des committed Diffs
  **PASS**: Payload-/Historien-Persistenz, konkrete Adapter,
  Cancellation, SSE/Usage und Response-Normalisierung bleiben bei
  ihren Eigentümern; kein `server.py`-Rückimport oder Fachcallback.
  Der Worker meldete 2.277 Tests, 12 Skips, fokussierte Tests,
  Architektur/Compile/Diff **PASS**; Ruff der neuen/geänderten
  fokussierten Module nur unter Ausnahme eines bestehenden `UP031`.
- Sequenziell nach PR #708 auf `origin/develop` als `2f285f41`
  integriert. Fünf Payload-/Service-Tests, 44 Provider-/Normalisierungs-
  Tests und vier Architekturtests **PASS**. Neu gebautes Read-only-
  Container-Image mit vollständiger integrierter Suite **PASS**:
  2.281 Tests, 10 Skips in 21,789 s. Inventar neu erzeugt:
  `server.py` 6.826 physische Zeilen; P2 enthält noch neun
  Routing-/Kompositions-Definitionen und sieben Konfigurationsbindungen,
  aber keine Gemini-Transport-/Antwort-Orchestrierung. Die verbliebenen
  Response-Router und Testpatches sind P8/P11-Restaudit, nicht P2-
  Adapterlogik. P2-Hauptpunkt geschlossen; CI/Sonar des
  veröffentlichten PR-Stands bleiben abzuwarten.

## PR #709 — bestätigter Merge; P8 täglicher Scheduler

- PR #709 mit Root-Review-PASS, Sonar (`new_violations=0`), Codex-Review,
  Backend- und Browser-CI **PASS**. Squash-Merge am
  `2026-09-23T12:49:07Z`, Commit
  `b1f1ceb1f8e444182248156e498f35718fe362bd`, auf
  `origin/develop` erreichbar. Der Browserlauf endete kurz nach dem
  Merge mit **SUCCESS**; keine neuen Befunde.
- P8-Worker-Stand `3df4ecf` im tatsächlichen Code **FAIL**: `server.py`
  behielt einen dauerhaften `schedule_daily_sync_jobs`-Wrapper.
  Korrektur `352869b4` entfernt ihn; nur die reine
  `daily_sync_scheduler`-Factory bleibt. Erneutes Root-Review **PASS**
  für Orchestrierung, Maintenance-/Resync-/DB-Locks, Queue-Reihenfolge,
  Marker, Payloads und keine automatischen Morning-Check-ins.
- Erstes integriertes Container-Review **FAIL**: 2.286 Tests,
  10 Skips, genau ein Fehler im migrierten Architekturtest, weil
  dessen Quellpfad fälschlich aus `/review/tests` statt dem geladenen
  `/app/backend`-Modul abgeleitet wurde. Korrektur desselben Workers
  `f3c88b4` wurde als `c81cf54e` sequenziell integriert und im
  tatsächlichen Diff **PASS** geprüft. Das Testziel ist jetzt das
  importierte Scheduler-Modul; Assertions bleiben unverändert.
  Neu gebautes Read-only-Container-Image, erneut vollständige Suite
  **PASS**: 2.286 Tests, 10 Skips in 19,304 s; fünf fokussierte
  Scheduler- und vier Architekturtests, scoped Ruff, Compile,
  Inventar- und Diff-Check **PASS**. Inventar: `server.py` 6.777
  physische Zeilen; P8-Hauptphase bleibt für Startup, Coach-Turn,
  Streaming/Background-Lifecycle offen. CI/Sonar des veröffentlichten
  P8-PR-Stands bleiben abzuwarten.

- Nach Veröffentlichung von PR #710 meldete SonarCloud für Head
  `2368be93` **FAIL**: neues `python:S107` in
  `DailySyncScheduler.__init__` (16 Parameter bei Limit 13).
  Korrekturauftrag an denselben GPT-6-Luna-Worker; Commit `4c8e46a0`
  bündelt ausschließlich die sechs skalaren Konfigurationswerte in
  `DailySyncSchedulerConfig(frozen=True)` und lässt die konkreten
  Zustandseigentümer einzeln injiziert. AST zählt nun 12 Parameter
  einschließlich `self`. Im Root-Diff als `18331ade` **PASS** geprüft:
  Reihenfolge, Marker, Queue-/Reset-/Maintenance-/DB-Gates und Payloads
  unverändert. Worker-Gesamtsuite 2.284 Tests, 12 Skips; fünf
  Scheduler- und vier Architekturtests, scoped Ruff/Compile/Diff
  **PASS**. Neu gebautes Read-only-Container-Image auf dem korrigierten
  Integrationsstand: vollständige Suite **PASS** mit 2.286 Tests und
  10 Skips in 22,182 s. Inventar-Check **PASS**; erneute Sonar/CI-
  Prüfung des veröffentlichten PR-Heads steht noch aus.

## PR #710 — bestätigter Merge; P10 Chat-Pagination

- PR #710 nach der `python:S107`-Korrektur auf Head `8e35ba54`
  erneut im Root-Diff **PASS**; SonarCloud `new_violations=0`,
  Codex-Review-Gate, Python-/Container-CI und Quality Baseline
  **PASS**. Squash-Merge am `2026-09-23T13:14:58Z`, Commit
  `50db694826b3eb410018bbc4129130c5af0de302`, auf
  `origin/develop` erreichbar. Der beim Merge noch laufende
  Browserjob endete anschließend ebenfalls mit **SUCCESS**.
- GPT-6-Luna/high-Worker-Commit `c0538118` verschiebt den vollständigen
  begrenzten Chat-History-Read in `ChatHistoryPageService`; der alte
  Server-Wrapper ist entfernt, der Handler ruft den konkreten Service.
  Ein früher Zwischen-Diff wurde wegen eigener manueller Reader-
  Transaktion **FAIL** bewertet; der Worker stellte vor Commit
  `DB_LOCK` plus `DatabaseManager.unit_of_work()` für Rows und
  Generation wieder her. Root-Review des committed Diffs **PASS**:
  Cursor, LIKE-Escaping, Begrenzung, Attachment-Namen und
  sitzungsgebundene Vorschläge behalten den bisherigen Vertrag.
  Zusätzliche Tests decken `%`, `_`, Backslash, UOW-/Generation-
  Bindung, Cursor und fremde Proposal-Session ab. Worker-Gesamtsuite
  **PASS**: 2.282 Tests, 12 Skips; drei Chat-, ein Reset-, ein
  Session- und vier Architekturtests sowie Compile/Diff/scoped Ruff
  **PASS**.
- Nach PR #710 als `c08bdc7e` auf den P10-Integrationsbranch
  übernommen und `origin/develop` mit `daf17e2e` integriert.
  Root-Diff/Server-Aufrufer **PASS**; drei Chat-, fünf tägliche
  Scheduler- und vier Architekturtests **PASS**. Inventar-Generator
  um die echten Composition-Factorys ergänzt, damit P0/P5 keine
  falschen offenen Fachdefinitionen ausweisen. `server.py` hat
  6.756 physische Zeilen. Neu gebautes Read-only-Container-Image:
  vollständige integrierte Suite **PASS**, 2.288 Tests, 10 Skips
  in 19,666 s. PR #711: SonarCloud `new_violations=0`, alle Python-,
  Container-, Browser- und Review-Gates **PASS**, keine offenen Threads;
  Squash-Merge am `2026-09-23T13:31:14Z`, Commit
  `e66ca4e3184cdff2e525f0eae0d4cb7616e9489a` auf
  `origin/develop` erreichbar.

## P7 Konversations-ID-Bereitstellung — integrierter Prüfstand

- GPT-6-Luna/high-Worker-Commit `0cdbad9b`, nach dem geprüften P10-Stand
  als `71d56c56` integriert. Der frühe Zwischen-Diff hielt den Remote-POST
  unter DB-Lock/Transaktion und wurde mit **FAIL** zurückgegeben. Der
  committed Korrekturstand trennt kurze KV-Lese-/Schreib-UOWs vom OpenAI-
  Request; ein Fake-Test beweist, dass während des Requests weder Lock noch
  UOW gehalten werden. Root-Diffprüfung **PASS**: `ensure_conversation` ist
  entfernt, beide produktiven Aufrufer und sämtliche bekannten Test-/E2E-
  Patch-Ziele nutzen den konkreten Service; keine Backend-Rückimporte oder
  neue dauerhaften Kompatibilitäts-Wrapper. Persistenzschlüssel, OpenAI-
  Metadaten und Fehlermeldung bleiben erhalten.
- Integrierte sieben Service- und vier Architekturtests **PASS**;
  vollständige lokale Suite **PASS**, 2.295 Tests, 12 Skips in 297,618 s.
  Inventar-Check, Diff-Check und scoped Ruff (vorbestehendes `UP031` in
  `conversation.py` ausgeschlossen) **PASS**. CI-/Sonar-Prüfung des noch zu
  veröffentlichenden PR-Stands steht aus. Die weiteren P7-History-, Reset-,
  Vorschlags- und Tool-Use-Cases bleiben offen.
- Nach Squash-Merge von PR #711 `origin/develop` mit `dd83d1f2`
  integriert; nur generiertes Inventar, Script-Owner-Eintrag und Review-
  Log hatten erwartete Textkonflikte. Der finale Tree-Diff gegenüber dem
  bereits getesteten P7-Stand ist leer. Erneute sieben Service- und vier
  Architekturtests sowie Inventar-/Diff-Check **PASS**.
- PR #712 auf Head `d591dbb7`: SonarCloud ohne neue Issues,
  Python-/Container-/Browser-CI und Codex-Review **PASS**, keine offenen
  Threads; Squash-Merge am `2026-09-23T13:41:20Z`, Commit
  `703629685b962279312f3ff891ae1e3698cb0c25` auf
  `origin/develop` erreichbar.

## P8 Startup-Scheduler — integrierter Prüfstand

- GPT-6-Luna/high-Worker-Commit `66c47bcf`, nach dem geprüften P7-/P10-
  Stand als `ea40c78b` integriert. Root-Review des tatsächlichen Diffs
  **PASS**: Calendar → Intervals → Garmin → Weather, Refresh und
  Historical Backfill samt aktiver Jobs, Cursor-/Frühgrenze und Payloads
  liegen vollständig in `StartupSyncScheduler`; die sieben alten
  `server.py`-Fachfunktionen sind entfernt. `main()` ruft den konkreten
  Service auf; `server.py` erstellt lediglich dessen Abhängigkeiten.
  Queue, Sync-State, Garmin-Konfiguration und Profil behalten jeweils
  ihren bestehenden Zustandseigentümer. Keine Backend-Rückimporte oder
  permanenten Wrapper.
- Worker-Host-Suite **PASS**: 2.288 Tests, 12 Skips; neu gebautes
  Read-only-Container-Image **PASS**: 2.288 Tests, 10 Skips. Der erste
  isolierte Containerlauf scheiterte nur am fehlenden read-only Docs-Mount;
  nach korrektem Mount keine Produkt-/Teständerung. Vier neue Startup-,
  ein `main()`-Reihenfolge-, vier Architekturtests, scoped Ruff,
  Compile und Diff-Check **PASS**. Integriert erneut vier Startup- und
  vier Architekturtests, Inventar und scoped Ruff **PASS**. `server.py`
  hat 6.677 physische Zeilen; die Tages-Loop-Lifecycle-Steuerung und
  weitere P8-Use-Cases bleiben offen. Neu gebautes kombiniertes
  Read-only-Container-Image **PASS**: 2.297 Tests, 10 Skips in
  20,563 s. Nach PR #712 `origin/develop` mit `141eb40e` integriert;
  nur Inventar-/Review-Textkonflikte, finaler Tree-Diff gegenüber dem
  bereits vollständig getesteten kombinierten Stand leer. CI/Sonar des
  künftigen P8-PR-Stands stehen noch aus.

- PR #713 auf Head `dd84d828`: SonarCloud `new_violations=0`,
  Python-/Container-/Browser-CI und Codex-Review **PASS**, keine offenen
  Threads; nach einem transienten GitHub-GraphQL-Fehler beim ersten
  Merge-Aufruf Squash-Merge am `2026-09-23T13:50:01Z`, Commit
  `e546089d6744794dc50246620c35f6d5fed8c8ad` auf
  `origin/develop` erreichbar.

## P8 Tages-Loop-Lifecycle — integrierter Prüfstand

- GPT-6-Luna/high-Worker-Commit `befab9e0`, nach dem geprüften
  Startup-/P7-/P10-Stand als `a65bdd35` integriert. Ein früher
  Zwischenstand behielt `daily_sync_loop()` als potenziellen alten
  Wrapper; konkreter Root-Korrekturauftrag, committed Stand nennt die
  reine Factory `daily_sync_loop_service()`. Root-Diffprüfung **PASS**:
  `DailySyncLoop.run()` besitzt den initialen 300-Sekunden-Schlaf,
  Schedule-vor-Morning-Reihenfolge, Maintenance-Fortsetzung,
  unverändertes Fehler-Logging und Propagation sonstiger Fehler.
  `main()` startet die gebundene Methode als Daemon-Thread. Scheduler,
  Morning-Battery und Logger behalten ihre Zustände; keine Backend-
  Rückimporte oder Server-Callbacks für die Loop-Fachlogik.
- Worker-Gesamtsuite **PASS**: 2.301 Tests, 12 Skips; vier Loop-,
  vier Architekturtests und scoped Ruff/Compile/Diff **PASS**.
  Integrierte vier Loop- und vier Architekturtests, Inventar-/Diff-
  Check **PASS**. Neu gebautes kombiniertes Read-only-Container-Image:
  vollständige Suite **PASS**, 2.301 Tests, 10 Skips in 20,366 s.
  `server.py` hat 6.675 physische Zeilen. Die P8-Scheduler-Checkliste
  ist fachlich abgeschlossen; Coach-Turn/Background/Streaming bleiben
  offen. Nach PR #713 `origin/develop` mit `585e1ba7` integriert;
  Produkt-, Test-, Plan- und Inventar-Konflikte aus dem Squash-Branch
  sequenziell geprüft. Finaler Tree-Diff gegenüber dem bereits vollständig
  getesteten kombinierten Stand leer; erneut vier Loop-, vier Startup-,
  vier Architekturtests und Inventar-/Diff-Check **PASS**. CI/Sonar des
  künftigen PR-Stands stehen aus.

- PR #714 auf Head `1594524c`: SonarCloud `new_violations=0`,
  Python-/Container-/Browser-CI und Codex-Review **PASS**, keine offenen
  Threads; Squash-Merge am `2026-09-23T14:00:08Z`, Commit
  `894407586abcd85e52b3791f3c5b275be427a221` auf
  `origin/develop` erreichbar.

## P9 Diagnosebericht — integrierter Prüfstand

- GPT-6-Luna/high-Worker-Commit `f18dc66c`, nach dem geprüften
  P8-/P7-/P10-Stand als `58dae268` integriert. Frühes Root-Diffreview
  stellte einen unnötig vorgezogenen Kalender-Read fest (**FAIL**);
  Korrekturauftrag an denselben Worker, committed Stand erhält beide
  getrennten Event-Reads an ihren ursprünglichen Projektionsstellen.
  Root-Review des tatsächlichen committed Diffs **PASS**:
  `DiagnosticReportService.report()` besitzt den gesamten Report,
  einschließlich fünf DB-Zählern, acht KV-Reads, Provider-Frische,
  redigierten Logs und Capture-Status/Entries. `server.py` enthält nur
  eine Composition-Factory; der Handler ruft den Service. Keine Backend-
  Rückimporte, Server-Callbacks, Remote-Writes oder neuen Rohdatenfelder.
  DB-Lock/UOW, Datenschutz-/Redaktionsgrenzen und API-Shape bleiben
  erhalten. Root-Audit der eigenständigen Capture-Endpunkte: `status()`
  und `set_enabled()` gehören bereits `DiagnosticCapture`; der Handler
  übernimmt nur Auth, Body-Lesen und Transport. Damit ist die P9-
  Diagnose-/Capture-Projektion vollständig zugeordnet.
- Worker-Gesamtsuite **PASS**: 2.297 Tests, 12 Skips; 14 Diagnose-
  Follow-ups, zwei neue Service-, vier Architekturtests, scoped Ruff,
  Compile/Diff **PASS**. Integriert erneut 14 Follow-ups, zwei Service-,
  vier Architekturtests, Inventar/Compile/Ruff/Diff **PASS**.
  `server.py` hat 6.639 physische Zeilen, P9 bleibt für Privacy und
  Backup/Restore offen. Neu gebautes
  kombiniertes Read-only-Container-Image: vollständige Suite **PASS**,
  2.303 Tests, 10 Skips in 19,917 s. CI/Sonar des künftigen PR-Stands
  stehen noch aus. Nach PR #714 `origin/develop` mit `65c74549`
  integriert; nur generiertes Inventar und Review-Text hatten Konflikte.
  Finaler Tree-Diff gegenüber dem vollständig getesteten Stand leer;
  erneut zwei Service-, 14 Follow-up-, vier Architekturtests sowie
  Inventar-/Diff-Check **PASS**.
- PR #715 auf Head `64711d07`: SonarCloud ohne neue Issues,
  Python-/Container-/Browser-CI und explizites Codex-Review **PASS**,
  keine offenen Review-Threads. Ein alter Review-Koordinationslauf wurde
  abgebrochen; der eigentliche Review-Check bestand. Squash-Merge am
  `2026-09-23T14:13:50Z`, Commit
  `fe3a014492d9691d752f4ad6b462bc7037d71aa2` ist auf
  `origin/develop` erreichbar.

## P9 lokaler JSON-Datenexport — integrierter Prüfstand

- GPT-6-Luna/high-Worker-Commit `0cc31cbb`, als `7c7b7e28` auf den
  bestätigten PR-#715-Mergestand integriert. Frühes Diffreview **FAIL**:
  eine Testdatei war außerhalb des anfänglichen Schreibbereichs geändert;
  die notwendige einzelne Aufrufer-Migration in
  `tests/test_coach_attachments.py` wurde danach ausdrücklich begrenzt
  freigegeben. Außerdem war die lokale Uhr zunächst neu berechnet statt
  unverändert injiziert; derselbe Worker korrigierte beides vor Commit.
  Root-Review des tatsächlichen committed Diffs **PASS**: Der konkrete
  `PrivacyDataExportService.export()` besitzt SQL-/KV-Auswahl,
  Laufzeitschlüssel-Filter, JSON-Fallbacks und die vollständige
  Ergebnisprojektion. Die Root erstellt nur Abhängigkeiten; keine
  Server-Rückimporte oder Fach-Callbacks. Drei getrennte DB-Lock/UOW-
  Lesegrenzen und die ursprüngliche Feld-/Zeitreihenfolge bleiben
  erhalten; weder Remote-Schreiben noch zusätzliche sensible Daten.
- Worker-Gesamtsuite **PASS**: 2.305 Tests, 12 Skips; `test_server.py`
  464 Tests, 3 Skips, zwei Fake-UOW-Tests sowie scoped Ruff/Compile/Diff
  **PASS**. Im Integrations-Worktree erneut `test_server.py` **PASS**:
  464 Tests, 3 Skips. Ein anfänglicher Einzeltest-Aufruf scheiterte
  ausschließlich an einem unpassenden `unittest`-Importpfad; die
  Repository-Discovery lief erfolgreich. Kombinierter ZIP-Patch steht
  noch aus; P9 bleibt für Archiv, Backup/Restore und Privacy-Delete offen.

## P9 Privacy-ZIP-Archiv — integrierter Prüfstand

- GPT-6-Luna/high-Worker-Commit `3d5100ef`, nach sequenzieller
  Konfliktauflösung in `server.py` als `7c9257a2` integriert. Frühes
  Root-Diffreview **FAIL**: Konstruktor zunächst zu breit und Lock als
  `Any` annotiert; derselbe Worker korrigierte frozen Config,
  konkrete Dienste/Lock und veraltete Modulbeschreibung vor Commit.
  Root-Review des committed Diffs **PASS**: `PrivacyArchiveExportService`
  besitzt ZIP-Erzeugung, sämtliche SQL-/KV-/JSONL-Auswahlen, Manifest,
  Limits und Temp-Datei-Cleanup. DB-Lock und gemeinsame UOW umfassen
  alle Reads bis zum Abschluss der ZIP-Datei. `server.py` erstellt nur
  den Service und streamt die fertige Datei; keine Server-Rückimporte,
  fachlichen Callbacks, Session-Exportdatei oder Remote-Writes.
- Worker-Gesamtsuite **PASS**: 2.304 Tests, 12 Skips; gezielte ZIP-,
  Manifest-, Datenschutz-, >1.000-Zeilen- und 507/413/408-Cleanup-
  Regressionen sowie scoped Ruff/Compile/Diff **PASS**. Kombinierte
  Integrationstests stehen noch aus. P9 bleibt für Backup/Restore,
  Privacy-Delete und HTTP-Migration offen.
- Kombinierter Read-only-Containerlauf des Stands `7c9257a2` **FAIL**:
  2.308 Tests, 10 Skips, ein Testfehler. Der neue Architekturtest für
  `backend/privacy.py` leitete den Quellpfad fälschlich aus dem
  separaten `/review/tests`-Mount ab statt aus dem importierten Modul
  unter `/app/backend`. Keine Produktcode-Exception. Korrekturauftrag
  an denselben JSON-Worker; nach dessen Follow-up sind Code und Tests
  erneut zu prüfen. Die vier Architekturtests, Inventar-Check, scoped
  Ruff und Diff-Check des integrierten Stands bestanden separat.
- JSON-Worker-Follow-up `735bb1a8`, integriert als `7082a183`, ändert
  ausschließlich die Quellpfadableitung im Test auf das importierte
  `backend.privacy`-Modul. Root-Diffreview **PASS**, kein schwächeres
  Architektur-Assertion. Gezielt Host und Read-only-Container je zwei
  Tests **PASS**; erneut gebautes kombiniertes Image mit den
  vollständigen gemounteten Repository-Tests **PASS**: 2.308 Tests,
  10 Skips in 20,140 s. Damit ist der integrierte JSON-/ZIP-Code nach
  Korrektur erneut freigegeben; CI und Review des PR-Stands stehen aus.
- PR #716 auf Head `24454a02`: SonarCloud, Python-/Container-/Browser-
  CI und explizites Codex-Review **PASS**, keine offenen Threads.
  Squash-Merge am `2026-09-23T14:36:31Z`, Commit
  `a761e2d37bddf4cd60b215d00cd825f3cf529fa2` auf
  `origin/develop` erreichbar.

## P10 HTTP-Serverklasse — integrierter Prüfstand

- GPT-6-Luna/high-Worker-Commit `c7b178d7`, nach #716 als `93074b15`
  integriert. Erstes Root-Diffreview **FAIL**: Tests referenzierten die
  neue HTTP-Modulklasse noch indirekt über `server.http_server`.
  Derselbe Worker migrierte nur die Test-Patch-Ziele direkt auf
  `backend.http_api.server`; Follow-up `b4841333`, integriert als
  `d9734ce1`. Erneutes Root-Review des Produkt- und Testdiffs **PASS**:
  `CoachHTTPServer` liegt ausschließlich in `backend/http_api/server.py`;
  `main()` verwendet den konkreten Modulbesitzer mit identischem Bind-
  Tupel und `RequestHandler`. Threading-Basisklasse,
  `daemon_threads=True` und Queuegröße 32 bleiben erhalten. Kein
  Rückimport, Alias-Wrapper oder veränderter Auth-/SSE-/Routenpfad.
- Worker-Gesamtsuite **PASS**: 2.304 Tests, 12 Skips; gezielte Startup-,
  Klassen- und HTTP-Tests sowie Compile/Diff und scoped Ruff **PASS**.
  Ein versehentlich im Haupt-Checkout begonnener Cherry-pick wurde vor
  der eigentlichen Integration abgebrochen; der Haupt-Checkout behielt
  ausschließlich seine vorhandenen Fremdänderungen. Der korrekt
  benannte PR-Worktree wurde danach konfliktfrei integriert.
  Kombiniertes neu gebautes Read-only-Container-Image: vollständige
  Suite **PASS**, 2.309 Tests, 10 Skips in 20,120 s. Vier
  Architekturtests, Inventar-Check, scoped Ruff und Diff-Check **PASS**;
  `server.py` hat 6.408 physische Zeilen. PR-CI/Review stehen aus.

## P9 Privacy-Löschung — eigenständig geprüfter Arbeitsstand

- Root-Diffstand auf `24454a02` (#716-Head): `PrivacyDeleteService`
  besitzt Preview-Kategorien, Wartungsgate, OpenAI-DELETE-Versuch,
  Zählung und lokale Löschtransaktion. `OpenAIResponsesClient` besitzt
  die einzige konkrete Remote-DELETE-Anforderung mit unveränderter
  URL-Kodierung, 30-s-Timeout und Auth-Header. `server.py` komponiert
  nur die Abhängigkeiten und delegiert beide HTTP-Endpunkte; die
  Reset-Routine nutzt denselben Provider-Adapter statt eines
  servereigenen Remote-Transport-Wrappers. Test-Patch-Ziele wurden
  auf Providerklasse und Privacy-Service umgestellt. Keine neuen
  Rückimporte oder fachlichen Server-Callbacks; Fremdprovider bleiben
  vom Delete unberührt.
- Gezielte Tests **PASS**: OpenAI-Provider 73, `test_server.py` 465
  (3 Skips), Provider-Review 15 (1 Skip), Audit-Remediation 17
  (1 Skip). Ein zusätzlicher synthetischer SQL-Abbruch nach bereits
  gelöschten Nachrichten beweist den Rollback der ganzen lokalen
  Transaktion. Neu gebautes Read-only-Container-Image:
  vollständige Suite **PASS**, 2.310 Tests, 10 Skips in 20,246 s.
  `server.py` hat 6.347 physische Zeilen; Restore und HTTP-Migration
  bleiben P9-offen. PR-CI/Review stehen noch aus.
- Der geprüfte Root-Commit `e5da2548` wurde auf den bestätigten
  #716-Merge-Commit sequenziell als `09b9aa49` übernommen; der
  vollständige Tree-Diff gegenüber dem mit 2.310 Container-Tests
  geprüften Stand ist leer. Inventar-Check und Diff-Check bleiben
  **PASS**; nur diese Review-Dokumentation wurde danach aktualisiert.
- PR #717 auf Head `9546044e`: SonarCloud, Python-/Container-/Browser-
  CI und explizites Codex-Review **PASS**, keine offenen Threads.
  Squash-Merge am `2026-09-23T14:47:17Z`, Commit
  `0fe5c7a05fbe27c67658c6d033918d2d5016e894` auf
  `origin/develop` erreichbar. P10-HTTP-Server-PR-Branch integriert
  diesen Zielstand sequenziell als `5f5e9ffc`; nur Inventar, Review-Text
  und zwei Testimporte hatten Konflikte. Root-Review des endgültigen
  Produkt-/Testdiffs gegen `origin/develop` **PASS**: nur die HTTP-
  Serverklasse und die direkten Patch-Ziele bleiben als Unterschied.
  Neu gebautes kombiniertes Read-only-Container-Image: vollständige
  Suite **PASS**, 2.311 Tests, 10 Skips in 21,301 s. Inventar-
  Check, vier Architekturtests und Diff-Check **PASS**.

## P9 Datenbank-Backup-Read — eigenständig geprüfter Arbeitsstand

- Root-Diffstand auf #717-PR-Head `9546044e`: Der konkrete
  `DatabaseBackupService` besitzt WAL-Checkpoint, Byte-Read,
  Speicher-/Größenprüfung und eine Kontextgrenze, die `DB_LOCK` bis
  nach der vollständigen HTTP-Dateiausgabe hält. `stream_database_backup`
  verbleibt als reiner Datei-Transport im Handlerbereich; Restore
  verwendet denselben Checkpoint-Besitzer, ohne Server-Callback ins
  Backend. Der beschädigte-DB-Fallback, Fehlerstatus 500/503/507/413,
  die ursprüngliche 120-s-Deadline und SQLCipher-Manager-
  Konfiguration bleiben erhalten.
- Drei neue Fake-Tests für Lockdauer, Grenzen und beschädigten
  Checkpoint sowie gezielte Backup-/Restore-Regressionen **PASS**.
  Neu gebautes Read-only-Container-Image: vollständige Suite **PASS**,
  2.313 Tests, 10 Skips in 20,611 s. Vier Architekturtests,
  Inventar-/Diff-Check und scoped Ruff **PASS**; `server.py` hatte
  6.331 physische Zeilen. P8-Job-Wiederaufnahme blockiert weiterhin
  die saubere Restore-Auslagerung ohne Rückimport.
- Der geprüfte Root-Commit `82f71abe` wurde auf den bestätigten
  #717-Merge-Commit als `10180f0c` übernommen. Der vollständige
  Dateibaum gegenüber dem mit 2.313 Container-Tests geprüften Stand
  ist identisch; Inventar- und Diff-Check bleiben **PASS**. Root-Gate
  für diesen integrierten Stand: **PASS**; PR-CI und Review folgen.
- Nach #718-Merge wurde #719 auf `7673a1f8` rebased
  (`36553d7e`, `0aac8a2e`). Root-Review des tatsächlichen Produkt-
  und Testdiffs **PASS**; ausschließlich generiertes Inventar und
  Review-Text hatten Konflikte. Neu gebautes kombiniertes Read-only-
  Container-Image: vollständige Suite **PASS**, 2.314 Tests,
  10 Skips in 21,452 s. Inventar- und Diff-Check **PASS**.

## P10 statische Assets — integrierter Prüfstand

- GPT-6-Luna-Patch `f82ffe4c` hatte im ersten Root-Diffreview **FAIL**:
  Der Handler-Level-Test für 304/ETag/Cache-Control/keinen Body war
  durch eine reine Service-Assertion ersetzt. Korrekturauftrag an
  denselben Worker; Follow-up `0a5d03e2` ergänzt wieder den konkreten
  Handler-Transporttest und die Traversal-Sperre ohne Request-Attribute.
- Root prüfte den tatsächlichen Follow-up- und Gesamtdiff: **PASS**.
  `StaticAssetService` besitzt Allowlist, Dateiauflösung, ETag,
  Cache- und Sicherheitsheader; `server.py` behält nur den
  Antworttransport. Kein Rückimport, Server-Callback oder zusätzlicher
  Zustandseigentümer. Die Integration auf HTTP-Server-Stand `a70be088`
  ergab `62ba899b` und `366b3e69`; der eine Produktkonflikt wurde
  zugunsten von `backend.http_api.server.CoachHTTPServer` mit einem
  komponierten Handler gelöst. Der Startup-Test prüft nun dessen
  konkreten Static-Service statt nur eine unveränderte Klassenidentität.
- Gezielte 11 Handler-/Architekturtests, Inventar- und Diff-Check
  **PASS**. Neu gebautes Read-only-Container-Image: vollständige Suite
  **PASS**, 2.314 Tests, 10 Skips in 20,586 s. `server.py` hatte
  6.299 physische Zeilen. PR-Veröffentlichung und CI stehen noch aus.
- PR #718 (HTTP-Server-Eigentümer) wurde separat nach Root-PASS und
  grünen erforderlichen Checks am `2026-09-23T15:00:24Z` als
  `7673a1f8512c50530d9f83420cee67e4e136931a` gemerged; der
  Commit ist auf `origin/develop` erreichbar und sein Dateibaum
  identisch mit dem integrierten Parent `a70be088`.
- Nach dem bestätigten #719-Merge wurde #720 sequenziell auf
  `0694a844` rebased (`843edb24`, `58de2214`, `ebab8200`). Der
  Produkt- und Testdiff war konfliktfrei; nur Inventar und Review-
  Text wurden neu erzeugt beziehungsweise zusammengeführt. Root-
  Review des kombinierten Stands **PASS**. Neu gebautes Read-only-
  Container-Image: vollständige Suite **PASS**, 2.317 Tests,
  10 Skips in 20,316 s. Inventar- und Diff-Check **PASS**;
  `server.py` hat 6.283 physische Zeilen.

## P10 Rate-Limiter — integrierter Prüfstand

- GPT-6-Luna/high-Worker-Commit `42a78abe`: `RateLimiter` besitzt
  Lock, Buckets, Cleanup-Uhr und die unveränderte Limit-/Retry-
  Entscheidung; `server.py` komponiert eine Instanz für Login und
  API-Auth. Erstes Root-Diffreview **FAIL**, weil drei Tests den
  Owner indirekt über `server.RATE_LIMITER.allow` patchten. Derselbe
  Worker korrigierte nur die Test-Patch-Ziele in `88a979f5` auf die
  direkt importierte Klasse mit `autospec`; Root-Follow-up- und
  Gesamtdiffreview danach **PASS**.
- Sequenzielle Integration auf bestätigtem #719-Merge-Stand
  `0694a844` als `43357d73` und `a6811065`: Konflikte nur in
  Importzeilen, keine Änderung der Entscheidungslogik. Gezielte
  sieben Rate-/Architekturtests, scoped Ruff, Inventar- und
  Diff-Check **PASS**. Neu gebautes Read-only-Container-Image:
  vollständige Suite **PASS**, 2.316 Tests, 10 Skips in 20,496 s.
- Nach #720-Merge auf `2a57b317` rebased. Der einzige Produkt-/
  Testkonflikt war die Registrierung beider neuen Modul-Owner im
  Architekturtest; beide Assertions bleiben erhalten. Inventar und
  Review-Text neu erzeugt. Root-Review des kombinierten Diffs **PASS**.
  Neu gebautes Read-only-Container-Image: vollständige Suite **PASS**,
  2.319 Tests, 10 Skips in 21,453 s; Inventar- und Diff-Check
  **PASS**. #720 wurde am `2026-09-23T15:12:16Z` als
  `2a57b31706fb37f7ea73cfee066c4538427d66ae` gemerged und ist
  auf `origin/develop` erreichbar. PR-CI für den Rate-Limiter folgt.
- PR #721, erster Head `3ba49b34`: Codex-Review fand einen echten
  **P1** — `e2e/fixture_runtime.py` überschrieb noch den entfernten
  `server.allow_rate`-Namen. Root-Gate für den PR-Stand **FAIL**;
  Auto-Merge blieb aus. Derselbe GPT-6-Luna-Worker reparierte nur die
  disposable Fixture (`9fa1c97a`, integriert als `926a8871`): sie
  überschreibt nun die tatsächlich verwendete `RATE_LIMITER.allow`-
  Instanz. Root-Follow-up-Diffreview **PASS**, produktive Limits
  unverändert. Im isolierten Fixture-Container bestanden 10 Login-
  und 200 authentifizierte API-Anfragen ohne 429; vier normale
  Limiter-Tests, Compile, scoped Ruff und Diff-Check **PASS**.
  Das einmalige Codex-Folgereview war ohne größere Befunde; der
  geprüfte Produkt-/Testdiff blieb nach Rebase und Bot-Update
  inhaltlich identisch. Root-Review **PASS**; Read-only-Docker-
  Vollsuite nach Rebase **PASS**, 2.320 Tests, 11 Skips.
  #721 wurde am `2026-09-23T16:17:03Z` als
  `d922e5068ed67565d2d24b59de741d3913d4cd72` gemergt;
  der Commit ist auf `origin/develop` erreichbar. Erforderliche
  Checks und Review-Threads **PASS** (0 offen); der nicht erforderliche
  Browser-Smoke-Test lief zum Zeitpunkt dieses Eintrags noch.

## P8 Chat-Stream-Zustand — integrierter Prüfstand

- GPT-6-Luna/high-Patch `6eb20b8d`: `ChatStreamRegistry` besitzt
  allein Lock, angehängte SSE-Queues und Background-Cancel-Events.
  Erstes Root-Diffreview **FAIL**: Tests referenzierten den Owner
  indirekt über `server.coach_streams`; außerdem erzeugte ein
  Background-Cancel nach Restart neu ein In-Memory-Event statt nur
  das durable Receipt-Flag zu setzen. Derselbe Worker korrigierte
  beides in `e6482200`. Root-Review des tatsächlichen Follow-up-
  und Gesamtdiffs danach **PASS**: Tests importieren das konkrete
  Modul; Reset und Jobstart verwenden weiterhin get-or-create,
  regulärer Cancel ohne Event erzeugt keinen Zustand.
- Worker-Vollsuite nach Korrektur **PASS**: 2.317 Tests, 12 Skips;
  fokussierte SSE-/Cancel-/Restart-/Architekturtests sowie Compile,
  scoped Ruff und Diff-Check **PASS**. Sequenzielle konfliktfreie
  Integration auf #720-Merge `2a57b317` als `6ffd7198` und
  `1f97a3eb`; fünf gezielte Architektur-/Restart-Tests und
  Inventar-/Diff-Check **PASS**. Neu gebautes kombiniertes Read-only-
  Container-Image: vollständige Suite **PASS**, 2.320 Tests,
  10 Skips in 22,403 s. `server.py` hat 6.219 physische Zeilen.
  Nach #721-Merge auf `d922e506` rebased; beide Owner-Assertions
  im Architekturtest erhalten. `git range-diff` zeigte keine Änderung
  an der Fachlogik oder den Regressionstests; Root-Review des
  kombinierten Diffs **PASS**. Neu gebautes Read-only-Container-Image:
  Vollsuite **PASS**, 2.323 Tests, 11 Skips in 19,996 s;
  Inventar- und Diff-Check **PASS**. PR-CI für den rebasierten Stand
  folgte.
  #726 wurde nach frischem Codex-Erstreview am
  `2026-09-23T16:38:31Z` als
  `9c7ae8730adc921e27294493a62165fd62802ee6` gemergt;
  der Commit ist auf `origin/develop` erreichbar, 0 Review-Threads
  offen. P8-Job- und Turn-Eigentümer bleiben offen.

## P10 Readiness — integrierter Prüfstand

- GPT-6-Luna/high-Patch `c075f454`: öffentliche DB-/Schema-/
  Verzeichnis-/Wartungsprojektion als `ReadinessService.state()`.
  Erstes Root-Diffreview **FAIL**: unaufgeforderter Wechsel von
  `DatabaseManager.unit_of_work()` auf eine Reader-Lease und fehlender
  Handler-Level-Vertrag für 200/503. Derselbe Worker korrigierte
  beides in `339b4c6c`; Root-Follow-up- und Gesamtdiffreview
  danach **PASS**. Die DB-Prüfung bleibt unter `DB_LOCK` in der
  ursprünglichen Writer-/UOW-Grenze; der Handler-Test prüft den
  komponierten Service, vollständige JSON-Payloads und Statuscodes.
- Worker-Vollsuite nach Korrektur **PASS**: 2.319 Tests, 12 Skips;
  sechs gezielte Readiness- und vier Architekturtests, Compile,
  scoped Ruff und Diff-Check **PASS**. Konfliktfreie Integration auf
  bestätigtem #720-Merge `2a57b317` als `479c3de3` und
  `2cfd1be1`. Neu gebautes kombiniertes Read-only-Container-Image:
  vollständige Suite **PASS**, 2.319 Tests, 10 Skips in 20,149 s;
  Inventar- und Diff-Check **PASS**. `server.py` hat 6.250
  physische Zeilen. Nach #726-Merge auf `9c7ae873` rebased;
  die Owner-Assertions für Limiter, Stream und Readiness bleiben
  erhalten. Der Importkonflikt enthüllte zwei doppelte bestehende
  Compose-Imports im Worker-Patch; sie wurden bei der Integration
  entfernt. Root-Diffreview des rebasierten Stands zunächst **FAIL**:
  der Handler band einen `ReadinessService` bei Handler-Klassenerzeugung
  dauerhaft und hätte nach einem Backup-Restore den geschlossenen alten
  `DatabaseManager` weiterverwendet. Root-Integrationskorrektur:
  pro Readiness-Anfrage wird der Service aus dem aktuellen Manager
  komponiert; der Handler-Vertragstest wechselt den Manager zwischen
  zwei Requests und prüft die vollständigen 200/503-Payloads.
  Erneutes Root-Diffreview **PASS**. Neu gebautes Read-only-Docker-Image:
  vollständige Suite **PASS**, 2.325 Tests, 11 Skips; Inventar-/Diff-
  Check **PASS**. Ersatz-PR #727 erhielt bei `bfc451d9` einen
  berechtigten Codex-**P2**: `database_manager()` konnte beim
  Verzeichnisfehler schon außerhalb des abgesicherten Probe-Pfads
  werfen, wodurch 500 statt 503 zurückkäme. Root-Gate erneut
  **FAIL**. Korrektur: Der Service erhält eine Manager-Factory und
  löst sie unter `DB_LOCK` innerhalb seines `try` auf. Ein neuer
  Handler-Regressionstest erzwingt einen Fehler bei der Komposition
  und prüft 503 samt datensparsamer `not_ready`-Payload. Gezielte
  Tests **PASS** (3/3); neu gebautes Read-only-Docker-Image:
  vollständige Suite **PASS**, 2.326 Tests, 11 Skips. Root-Review des
  tatsächlichen Korrekturdiffs **PASS**. Der P2-Thread wurde mit Test-
  und Commitnachweis beantwortet und aufgelöst. Die Codex-Gate-Prüfung
  verlangt nach der Head-Änderung eine neue Erstprüfung; gemäß der
  Repository-Regel (kein zusätzliches Review ohne P1) wird #727
  ersetzt, nicht durch einen regelwidrigen Folgereview umgangen.
  Ersatz-PR #728, Head `312faeb7`: Codex meldete einen berechtigten
  **P2** ausschließlich im Inventar — `readiness_service()` war als
  offene P3-Fachlogik statt als reine Composition-Root-Funktion
  klassifiziert. Root-Gate **FAIL**. Der Generator ordnet den Namen
  nun explizit `COMPOSITION_ROOT` zu; das Inventar wurde regeneriert.
  Root-Review des konkreten Diffs **PASS**; Inventar-Check, vier
  Architekturtests, Compile und Diff-Check **PASS**. Laufzeitcode
  und das bereits mit 2.326 Tests geprüfte Verhalten sind unverändert.
  #728 wurde am `2026-09-23T16:59:33Z` als
  `16fb0c6123b0619b747bdec5da05f548e562b0fc` gemergt;
  der Commit ist auf `origin/develop` erreichbar, 0 Review-Threads
  offen. Der nicht erforderliche Browser-Smoke-Test lief bei diesem
  Eintrag noch.

## P8 Coach-Job-Store — integrierter Prüfstand

- GPT-6-Luna/high-Patch `875e32b2`, nach Rebase auf bestätigtem
  #729-Merge `7e064b19` als `a7fc93fa`: `CoachJobStore` besitzt
  durable Claim-, Contention-Requeue- und gespeicherte
  Nutzernachrichten-Leseentscheidungen. Die vorherigen Server-
  Fachfunktionen sind entfernt; die Composition Root injiziert
  Manager, DB-Lock, Wake-Event, Maintenance-Gate und Uhrzeit.
- Root prüfte tatsächlichen Modul-, Aufrufer- und Testdiff:
  **PASS**. Claim bleibt unter Maintenance-Gate und atomarer UOW,
  Statuswechsel verwendet einen bedingten Update; Retry-Backoff,
  20-Kandidaten-Grenze, Worker-Wakeup, Restart und fehlende
  Nachrichten behalten ihre Verträge. Integration bewahrte die
  P7-Reset-Testmigration; Architekturtest verbietet alle drei
  alten Server-Namen, Inventar weist die reine Compose-Funktion
  explizit der Composition Root zu. Worker-Vollsuite auf altem
  Stand **PASS**, 2.326 Tests, 12 Skips; Root-Vollsuite auf
  #726-Stand **PASS**, 2.329 Tests, 11 Skips. Neu gebautes
  kombiniertes Read-only-Docker-Image auf #729-Merge:
  vollständige Suite **PASS**, 2.334 Tests, 11 Skips; Inventar-,
  Architektur-, Compile- und Diff-Check **PASS**. PR-CI folgt.
  Enqueue/Resume/
  Cancel/Turn bleiben P8-offen.
  #730 wurde am `2026-09-23T17:18:52Z` als
  `67b4b377d8a9c7df1efc41abd73917b99307d7a0` gemergt;
  der Commit ist auf `origin/develop` erreichbar, 0 Review-Threads
  offen. Codex und erforderliche Checks **PASS**; der nicht
  erforderliche Browser-Smoke lief bei diesem Eintrag noch.

## P7 Coach-Chat-Reset — lokaler Prüfstand

- Root-Commit `c37eeb87` (Rebase des inhaltlich identischen
  `7237a69a`) verlagert die gesamte Reset-Orchestrierung in
  `CoachConversationResetService`: best-effort OpenAI-DELETE vor der
  lokalen UOW, atomare Nachrichten-/Command-/Entwurfs-/Generation-
  Änderung, Cancellation über den konkreten Stream-Owner und das
  bisherige anschließende Provider-KV-Clearing. Der Handler delegiert
  direkt; die sechs alten Server-Fachfunktionen sind entfernt.
- Root-Diffreview **PASS**: keine Backend-Importe aus `server.py`, keine
  rückrufende Server-Fachlogik, bestehende Remote-Autorisierung durch
  Handler-Auth/CSRF und unveränderte Reset-Reihenfolge. Zwei neue
  Regressionen prüfen Transaktions-Rollback und best-effort Remote-
  Fehler. Read-only-Docker-Vollsuite **PASS**, 2.325 Tests, 11 Skips
  in 21,365 s; 68 Coach-Dialogtests, 4 Architekturtests, Compile,
  Inventar- und Diff-Check **PASS**. Scoped Ruff meldet nur den
  bereits vorhandenen `UP031`-Befund im Conversation-Modul.
- Dieser Stand ist lokal und noch kein gemergter PR. Inventar:
  Nach Rebase auf bestätigtem #728-Merge `16fb0c61` ist die
  Fachlogik des P7-Diffs unverändert. Root prüfte den tatsächlichen
  kombinierten Code und Diff erneut: **PASS**. Neu gebautes Read-only-
  Docker-Image: vollständige Suite **PASS**, 2.328 Tests, 11 Skips;
  Inventar-, Architektur- und Diff-Check **PASS**. `server.py` hat
  6.099 physische Zeilen und 288 Definitionen. P7-Rest bleibt
  umfangreich; PR-CI und externer Review folgen.
  #729 wurde am `2026-09-23T17:09:48Z` als
  `7e064b192e237b707513f5007800c9587025804e` gemergt;
  auf `origin/develop` erreichbar, Codex-/Browser-/CI-Checks
  **PASS**, 0 Review-Threads offen.

## P10 Session-Auth — integrierter Prüfstand

- GPT-6-Luna/high-Patch `c61205de`, Testmigration `f90129ea`:
  `SessionAuthService` besitzt Cookie-/CSRF-/Login-/Logout-/
  Session-Touch-/Cleanup- und Coach-Session-Binding-Fachlogik;
  `server.py` komponiert nur den konkreten Eigentümer und die
  Handler delegieren an ihn. Erstes Root-Diffreview **FAIL**:
  Handler-Klassenbindung hätte nach DB-Restore einen geschlossenen
  Manager behalten. Derselbe Worker korrigierte auf Handler-Instanz
  (`78c3ed38`); Root-Review des erneuten Integrationsdiffs
  **FAIL**, weil eine HTTP/1.1-Keep-Alive-Verbindung dieselbe
  Instanz für mehrere Requests verwendet. Derselbe Worker korrigierte
  mit dynamischer Compose-Property (`a3a2c0d9`); ein echter
  Zwei-Request-Test auf derselben TCP-Verbindung wechselt den
  Datenbankmanager und prüft 200 sowie Socket-Identität.
- Root prüfte den tatsächlichen Follow-up- und Gesamtdiff auf
  #730-Merge `67b4b377`: **PASS**. Session-Lock und DB-Lock,
  konstante Token-/CSRF-Hashprüfung, feste Expiry, begrenztes
  Cleanup, 429-Retry und Cookie-Flags bleiben erhalten; keine
  Backend-Rückimporte oder Kompatibilitätswrapper. Worker-Vollsuite
  **PASS**, 2.329 Tests, 12 Skips; neu gebautes kombiniertes
  Read-only-Docker-Image **PASS**, 2.335 Tests, 11 Skips.
  Architektur-, Inventar-, Compile- und Diff-Check **PASS**;
  `server.py` hat 5.912 physische Zeilen und 275 Definitionen.
  PR-CI und externer Review folgen.
- #731, Head `5f94d99d`: Codex-Code- und Security-Review ohne
  Befund; Python-/Container-/Sonar-Checks **PASS**. Browser-Smoke
  **FAIL**: ausschließlich die HTTP-Plan-Fixture schloss nach
  `GET /api/fixture/plan` die Verbindung ohne Antwort. Root-Befund:
  die Fixture rief den entfernten `server.require_auth`-Wrapper auf.
  Derselbe GPT-6-Luna-Worker migrierte den Testaufrufer in `3b3659ed`
  auf `self.auth_service.require_auth(self)`. Root prüfte den
  tatsächlichen Ein-Zeilen-Diff und alle Auth-Lookups der Fixture:
  **PASS**. Gezielter Browser-Test **PASS** (1/1), vollständiges
  `mobile-small`-Profil **PASS** (51/51) mit frischer temporärer
  Fixture-Datenbank und gemockten Providern; Compile, scoped Ruff
  und Diff-Check **PASS**. Nach dem Push bestand auch die vollständige
  GitHub-Browser-Suite; der Codex-Check verlangte bei neuer Head-SHA
  dennoch eine zweite explizite Erstanforderung. Da ohne P1 kein
  zweiter `@codex review` zulässig ist, wird #731 durch einen neuen
  PR auf dem bestätigten #732-Merge ersetzt; keine Prüfung wird umgangen.

## P9 Restore-Validierung — integrierter lokaler Prüfstand

- GPT-6-Luna/high-Patch `91bf1d1e`, nach Rebase auf dem bestätigten
  #730-Merge `67b4b377` als `1605961e`: `DatabaseRestoreValidationService`
  besitzt Payload-Grenze und exklusives temporäres Staging, SQLCipher-/
  Schema-/Integritäts-/Fremdschlüsselprüfung sowie das Entfernen der
  Backup-Sessions. Der Server komponiert den Service und behält bis zum
  folgenden Restore-Schritt Austausch und Worker-Wiederaufnahme.
- Root prüfte tatsächlichen Diff und Code einschließlich Fehler-Cleanup,
  Maintenance-Gate, bestehender DB-Lock-/Drain-Grenze und Rollback vor
  Datenbankaustausch: **PASS**. Keine Backend-Rückimporte oder Server-
  Callbacks; der einzige neue Servername ist eine Compose-Funktion.
  Rebase-Konflikt im Architekturtest wurde unter Erhalt beider
  Verbotslisten gelöst. Neu gebautes Read-only-Docker-Image:
  vollständige Suite **PASS**, 2.340 Tests, 11 Skips; fokussierte
  Validierungs-/Architekturtests **PASS**, 10/10; Inventar-, Compile-
  und Diff-Check **PASS**. `server.py` umfasst 6.023 physische Zeilen
  und 284 Definitionen. #732 wurde am `2026-09-23T17:40:25Z`
  als `3c9a5fe5ff561f479f2eb462fa39ee2fbfa5ae6e` gemergt,
  auf `origin/develop` erreichbar; alle CI-/Browser-/Codex-Checks
  **PASS**, 0 Review-Threads offen. Offen bleiben Restore-Austausch
  und atomare Ressourcen-/Worker-Wiederaufnahme.
## P8 Coach-Job-Submission — lokaler Prüfstand

- GPT-6-Luna/high-Patches `cb0e70bc`, `d3b32172`, `1bfb2cee`
  verlagern Background-Enqueue, Session-Active-Lookup, Replay,
  Attachment-Validierung und -Quote sowie atomare Message-/Command-
  Persistenz in `CoachJobSubmissionService`. Die Handler delegieren
  direkt; der Service besitzt keine Server-Rückimporte oder globale
  Worker-/Stream-Zustände. Der konkrete `ChatStreamRegistry` bleibt
  Eigentümer der Cancel-Events; Wake und State-Event erfolgen erst
  nach erfolgreichem Commit.
- Root-Diffreview des Erststands **FAIL**: zwei konkurrierende Turns
  konnten zwischen Active-Read und Insert durchlaufen. Derselbe
  Worker verlagerte die Prüfung in die DB-Lock-/UOW-Grenze und
  ergänzte einen deterministischen Race-Test. Zweites Review
  **FAIL**: ein vor dem Lock gebundener Datenbankmanager konnte nach
  Restore geschlossen sein. Der Worker injiziert nun eine Fabrik
  und löst sie unter dem Lock auf; ein Managerwechseltest belegt
  Active-Lookup und Replay. Worker-Vollsuite auf seinem Stand
  **PASS**, 2.332 Tests, 12 Skips. Root führte zusätzlich den
  Session-Bindungs-Hash in `coach/authorization.py` zusammen,
  migrierte die Test-Lookups und verbot den alten Servernamen.
  Fokussierte Coach-/Architekturtests, Compile, Inventar- und
  Diff-Check **PASS**. Rebase, kombinierte Vollsuite und PR-Gate
  stehen noch aus; P8-Worker/Turn/Resume/Cancel bleiben offen.
- Nach bestätigtem #733-Merge `eb69cffd` sequenziell auf
  `develop` rebased: finaler Root-Code-/Diffstand `d6682506`.
  Der Konflikt mit der Auth-Auslagerung wurde ohne Wiedereinführung
  der entfernten Session-Recovery-Serverfunktion gelöst; alle
  Architekturverbote und beide Checklistenpunkte blieben erhalten.
  Root-Gate für den tatsächlich integrierten Stand **PASS**:
  neu gebautes Read-only-Docker-Image mit vollständiger Suite
  **PASS**, 2.344 Tests, 11 Skips; Coach-Review 16/16,
  Architektur 4/4, gezielte Submissiontests, Inventar-, Compile-
  und Diff-Check **PASS**. `server.py` umfasst 5.744 physische
  Zeilen und 267 Definitionen. Externe PR-/CI-Prüfung steht aus.
- #734 auf Head `e1c9ae35`: SonarCloud-Gate **FAIL** mit genau einem
  neuen `python:S3776`-Befund in `enqueue` (kognitive Komplexität
  20 statt höchstens 15). Derselbe GPT-6-Luna-Worker zerlegte
  Validierung und Provider-Limits ohne Schnittstellen- oder
  Reihenfolgeänderung in `69b221e8`. Root prüfte den tatsächlichen
  Ein-Modul-Diff: **PASS**; atomare Session-/Replay-UOW, Manager-
  Auflösung unter Lock und Post-Commit-Side-Effects bleiben gleich.
  23 fokussierte Tests, Ruff einschließlich `C901`, Compile und
  Diff-Check **PASS**. Ein neu gebautes Read-only-Docker-Image auf
  `69b221e8` bestand die vollständige kombinierte Suite erneut:
  **PASS**, 2.344 Tests, 11 Skips. Root-Gate des korrigierten Diffs
  **PASS**; die erneute Sonar-/Browser-/Codex-Prüfung steht noch aus.

## P8 Coach-Job-Submission — bestätigter Merge

- #734 nach SonarCloud-FAIL und bestandenen übrigen Prüfungen ohne Merge
  geschlossen. Der korrigierte Head `e0b59d0d` wurde als #735 gegen
  `develop` geprüft: SonarCloud, Browser, Container-Tests und Codex-Code-
  sowie Security-Review **PASS**, 0 offene Review-Threads. Squash-Merge
  `f6f310ec1a3784dbde4250fbb31753c0cec30125` am
  `2026-09-23T18:10:14Z` bestätigt und auf `origin/develop` erreichbar.

## P10 Performance-/Feedback-Projektionen — Integrationsreview

- GPT-6-Luna/high-Patch `aa00a316`, auf bestätigtem #733-Merge
  `eb69cffd` als `2aefe68b` mit Inventar-/Architekturstand
  `b0e71b3a` integriert. Root prüfte den tatsächlichen Diff und
  Code: **PASS**. Die zwei konkreten Services in
  `backend/http_api/public_performance.py` besitzen die vollständige
  Performance-/Garmin- bzw. Feedback-Projektion; `server.py` enthält
  nur ihre Komposition und direkte Handler-Delegation. Auth-Grenze,
  lokale Datumsauflösung, Lese-Reihenfolge und Check-in-Limit 30
  bleiben erhalten. Keine Server-Rückimporte oder Alt-Wrapper.
- Rebase-Konflikte betrafen #733-Authentifizierung sowie das generierte
  Inventar; die dynamische Handler-Auth wurde beibehalten und das
  Inventar aus dem kombinierten Quellstand neu erzeugt. Fokussierte
  Tests und Architekturtest **PASS** (6/6), Inventar-/Diff-Check
  **PASS**. Neu gebautes Read-only-Docker-Image: vollständige Suite
  **PASS**, 2.343 Tests, 11 Skips. `server.py` umfasst 5.888
  physische Zeilen; übrige P10-Projektionen und vollständiger
  HTTP-Transport bleiben offen. #736 wurde nach bestandenem Browser-
  und Codex-Review ohne Merge geschlossen, weil #735 inzwischen die
  Zielbasis änderte und das generierte Inventar konfliktierte. Auf
  `f6f310ec` rebased und tatsächlichen Gesamtdiff erneut geprüft:
  **PASS**; fokussierte Architektur-/Service-Tests 6/6, Inventar- und
  Diff-Check **PASS**, neues Read-only-Docker-Image mit vollständiger
  Suite **PASS**, 2.346 Tests, 11 Skips. `server.py` hat 5.743
  physische Zeilen. #737-Container-, Sonar- und Browser-Checks
  **PASS**; Codex-Check scheiterte geschlossen mit externem
  `Unexpected error`, und das abgeschlossene Review meldete einen
  P2-Befund: `public_state()` dupliziert die Performance-/Feedback-
  Projektionen noch in `server.py`. Die behauptete produktive
  `/api/bootstrap`-Verknüpfung existiert zwar nicht, die doppelte
  Eigentümerschaft aber schon. Review-Gate deshalb **FAIL**;
  #737 ohne Merge geschlossen. Nächster Schritt: denselben
  `public_state`-Eigentümer auf die konkreten Performance-/Feedback-
  Services verdrahten, integrierten Diff und Vollsuite neu prüfen und
  erst dann einen Ersatz-PR gegen aktuelles `develop` eröffnen.

## P10 Öffentliche Projektionen — kombiniertes Sol-Review

- GPT-6-Luna/high-Patch `e0ac064a` verschob die komplette historische
  `public_state`-Orchestrierung in `PublicStateService`. Root-Diffreview
  **FAIL**: ein vor dem Wetter-Follow-up gebundener Datenbankmanager
  konnte nach Restore veraltet sein. Derselbe Worker korrigierte mit
  Factory-Auflösung unter `DB_LOCK` in `7419a980` und einem
  deterministischen Managerwechseltest. Ein zunächst außerhalb des
  erlaubten Schreibbereichs angelegter Test wurde auf Root-Hinweis
  nach `tests/test_server.py` verlegt; Endpatch nur in den freigegebenen
  Dateien. Worker-Vollsuite **PASS**, 2.343 Tests, 12 Skips.
- Root integrierte die Worker-Patches sequenziell als `197426a1` und
  `ffa6e079` mit den Performance-/Feedback-Services und beseitigte
  den P2-Duplikationsbefund in `230ecb96`: `PublicStateService` nutzt
  dieselben konkreten Services mit bereits gelesenem Snapshot und
  Check-ins. Die ursprüngliche Response-Reihenfolge, lokale-only-
  Grenze und Lock-/UOW-Nutzung bleiben erhalten. Keine Backend-
  Rückimporte, Server-Fachcallbacks oder Kompatibilitätswrapper.
  Root prüfte den tatsächlichen integrierten Diff und Code: **PASS**.
  Neu gebautes Read-only-Docker-Image mit vollständiger Suite
  **PASS**, 2.350 Tests, 11 Skips; fokussierte Projektionstests,
  Architekturtests, Compile, Inventar- und Diff-Check **PASS**.
  `server.py` umfasst 5.656 physische Zeilen. Die frühere
  `public_state()`-Funktion hatte nur Testaufrufer; produktives
  `/api/bootstrap` bleibt ein separater begrenzter Local-Only-Read.
  #738 auf Head `c0e6eaaa`: Sonar-, Container-, Browser- und Codex-
  Checks **PASS**, 0 offene Review-Threads. Root fand danach im
  zusätzlichen Ruff-Lauf einen reinen Import-Sortierbefund im neuen
  Modul; der Ein-Modul-Diff `ac4eab44` ist erneut geprüft, Ruff,
  Compile und Diff-Check **PASS**. Wegen der Einmal-Review-Regel
  wird #738 ohne Merge durch einen neuen PR mit dem korrigierten
  Head ersetzt; kein alter PASS wird auf eine neue Head-SHA übertragen.

## P10 öffentliche Planprojektion — integrierter lokaler Prüfstand

- GPT-6-Luna/high-Patch `f8f77ddd` mit Korrektur `b83ac404`, nach
  Rebase auf bestätigtem #730-Merge `67b4b377` als `09579637` und
  `7c602be1`: `PublicPlanStateService` besitzt den vollständigen
  `/api/plan`-Leseablauf einschließlich Bounded Reads, Wetter-Follow-up,
  geschütztem History-Read, Kalender- und Tageskontextprojektion.
  `server.py` komponiert nur und der Handler delegiert direkt.
- Root-Diffreview des Erststands **FAIL**, da History ohne `DB_LOCK`
  gelesen und der Manager zu früh gebunden wurde. Derselbe Worker
  korrigierte beides. Root prüfte den tatsächlichen korrigierten und
  rebasierten Gesamtdiff: **PASS**. Managerauflösung erfolgt innerhalb
  des Locks; keine Backend-Rückimporte oder fachlichen Server-
  Callbacks. Neu gebautes Read-only-Docker-Image: vollständige Suite
  **PASS**, 2.338 Tests, 11 Skips; fokussierte Plan-/Architekturtests
  **PASS**, 7/7; Inventar- und Diff-Check **PASS**. `server.py` hat
  6.010 physische Zeilen und 286 Definitionen. Andere P10-Projektionen,
  PR-CI und externer Review bleiben offen.

## P10 Bootstrap-/Plan-/Wetterprojektionen — kombinierter lokaler Prüfstand

- GPT-6-Luna/high-Bootstrap-Patch `d80149a9` auf bestätigtem
  #735-Merge `f6f310ec` als `dcf0ecc4`, Plan-Patches
  `09579637`/`7c602be1` als `949a2fbc`/`118b3f17` und
  Wetter-Patch `32567c8c` als `2c0e16b6` sequenziell integriert.
  Root prüfte die tatsächlichen Code-/Konfliktdiffs: **PASS**.
  `PublicBootstrapService` besitzt die komplette bounded Local-Only-
  Antwort unter einer DB-Lock-/UOW-Grenze; `PublicPlanStateService`
  hält den geschützten History-Read nach Wetter-Follow-up, und
  `PublicWeatherStateService` besitzt die Refresh-/Marker-Regel.
  Handler authentifizieren dynamisch und delegieren unmittelbar;
  keine Server-Rückimporte oder Kompatibilitätswrapper.
- Drei veraltete Testaufrufer/Patchziele wurden auf konkrete Services
  beziehungsweise `session_auth_service` migriert. Gezielte Handler-/
  Privacy-Tests **PASS** (3/3), Architekturtests **PASS** (4/4),
  Ruff, Compile, Inventar- und Diff-Check **PASS**. Neu gebautes
  Read-only-Docker-Image auf dem kombinierten #735-Basisstand:
  vollständige Suite **PASS**, 2.351 Tests, 11 Skips.
  `server.py` umfasst 5.605 physische Zeilen. Dieser Stand wird
  nach dem #739-Merge gegen aktuelles `develop` neu integriert und
  erneut geprüft, bevor ein PR veröffentlicht wird.

## P10 öffentliche Projektionen — bestätigter #739-Merge und Rebase-Gate

- #739 auf Head `ee1fd8da`: Container-, Sonar-, Browser- und Codex-Code-/
  Security-Checks **PASS**, 0 offene Review-Threads. Squash-Merge
  `62f77b11ee543511a9c56849521562b2c70bc785` am
  `2026-09-23T18:54:39Z` bestätigt und auf `origin/develop` erreichbar.
- Bootstrap-/Plan-/Wetterstand auf diesen Merge rebased: `738fa014`.
  Konflikte in Testaufrufen, Architekturliste, Importen und dem generierten
  Inventar wurden anhand der kombinierten konkreten Service-Eigentümer
  aufgelöst. Root prüfte den tatsächlichen neuen Gesamtdiff samt
  Handler-Delegation, Lock-/Manager-Auflösung, Local-Only- und
  Wetter-Follow-up-Grenze erneut: **PASS**. Neu gebautes Read-only-
  Docker-Image: vollständige Suite **PASS**, 2.357 Tests, 11 Skips;
  Ruff für neue Module, Compile, Inventar- und Diff-Check **PASS**.
  `server.py`: 5.517 physische Zeilen, 266 Definitionen. PR-CI,
  externer Review und Merge dieses neuen Stands stehen noch aus.

## P10 Planprojektion — #740 Quality-Gate-Korrektur

- #740 auf Head `4d8eaa93`: Container-, CodeQL- und Codex-Checks
  **PASS**, 0 offene Review-Threads; SonarCloud Code Analysis **FAIL**
  wegen 20 Parametern in `PublicPlanStateService.__init__`
  (`backend/http_api/public_plan.py:21`). Kein Merge und kein
  Übertrag des vorherigen PASS auf einen geänderten Stand.
- Root führte die konkrete Abhängigkeitsstruktur `PublicPlanDependencies`
  im selben Fachmodul ein, ohne UOW-, Lock-, Auth- oder Response-Ablauf
  zu ändern. Fokussierte Projektionstests 3/3, Ruff, Compile und
  Inventar-Check **PASS**. Root prüfte den tatsächlichen Korrektur-Diff
  erneut: **PASS**. Neu gebautes Read-only-Docker-Image: vollständige
  Suite **PASS**, 2.357 Tests, 11 Skips; Architekturtests 4/4 und
  Diff-Check **PASS**. #740 ohne Merge geschlossen; ein Ersatz-PR mit
  neuem Head braucht eigene CI- und Review-Freigabe.

## P10 öffentliche Projektionen — bestätigter #741-Merge

- #741 auf Head `1ba976fc`: Sonar-, Container-, Browser- und Codex-
  Checks **PASS**, 0 offene Review-Threads. Squash-Merge
  `5c3f8f49d13127f15ffbe704342199713aa4d003` am
  `2026-09-23T19:16:11Z` bestätigt und auf `origin/develop` erreichbar.

## P7 lokale Athletenakten und Trainingsvorlagen — Integrationsreview

- GPT-6-Luna/high-Athletenakten-Patch `acce8573` auf #741-Basis
  rebased; Root prüfte den tatsächlichen Diff und Code: **PASS**.
  `CoachAthleteRecordToolService` besitzt die fünf lokalen
  Operationen samt Operation-/Scope-Prüfung; keine Remote-Schreibwege
  oder Server-Fachcallbacks.
- GPT-6-Luna/high-Vorlagenpatch `909f1911`: Root-Review **FAIL**
  wegen redundanter Backend-Factory und unwirksamem unerwartetem
  Testpfad (`self.fail` auf Library). Derselbe Worker korrigierte
  in `ef0a8a96`; Worker-Vollsuite erneut **PASS**, 2.352 Tests,
  12 Skips. Root integrierte sequenziell als `20ed1aae` und
  `32f6f223`. Ein Cherry-Pick-Konflikt ließ zunächst die alte
  `server.py`-Vorlagenfunktion stehen; Root entfernte sie als
  Integrationskorrektur. Die konkrete Klasse besitzt nun Batch-UOW,
  1–28-Eintragsgrenze, Objekt-Scope und Rollback.
- Root prüfte den kombinierten Code-/Diffstand inklusive der
  Konfliktkorrektur: fokussierte Service-Tests 5/5,
  Architekturtests 4/4, Ruff, Compile, Inventar- und Diff-Check
  **PASS**. Neu gebautes Read-only-Docker-Image mit vollständiger
  Suite **PASS**, 2.362 Tests, 11 Skips. Root-Gate des kombinierten
  lokalen Stands **PASS**. `server.py`: 5.439 physische Zeilen,
  258 Definitionen. PR-CI, externer Review und Merge stehen aus.

## P7 Athletenakten/Vorlagen — bestätigter #742-Merge

- #742 auf unverändertem Head `2676929c`: CodeQL, SonarCloud,
  Container-/Browser- und Codex-Code-/Security-Prüfung **PASS**;
  0 offene Review-Threads. Der abgebrochene Review-Koordinationsjob
  wurde über ein reguläres PR-Reopen-Ereignis mit aktuellen Daten neu
  bewertet, ohne zweiten Review-Auftrag. Squash-Merge
  `8343ae13fea2a1621e928f9d68714045e4ee91ef` am
  `2026-09-23T19:37:12Z` bestätigt und auf `origin/develop` erreichbar.

## P7 lokaler Bibliotheksplan — Integrationsreview

- GPT-6-Luna/high-Patch `2ec3cb26` sequenziell auf den #742-Merge
  rebased als `87be8cbc`. Root prüfte den tatsächlichen Diff samt
  Konfliktauflösung: **PASS**. Der alte Server-Use-Case wurde entfernt;
  `CoachLibraryPlanToolService` besitzt Operation-/Objekt-Scope und
  Eingabeprüfung und ruft den bestehenden atomaren, rein lokalen
  `WorkoutLibraryPlanService` ohne Server-Fachcallback auf.
- Fokustests 5/5 und Architektur 4/4, Ruff, Compile und Diff-Check
  **PASS**. Die Testanzahl ist für diese Grenze angemessen: fünf neue
  Fälle decken Autorisierung und Eingabegrenzen ab; acht vorhandene
  Domain-Tests decken Batch-UOW, Konflikte, Rollback, Grenzen und
  Remote-Freiheit ab. Native Gesamtsuite **PASS**, 2.367 Tests,
  12 Skips; Python-3.14-Docker-Build und vollständige Read-only-
  Docker-Suite **PASS**, 2.367 Tests, 11 Skips. Inventar- und
  Diff-Check **PASS**. Root-Gate des integrierten lokalen Stands
  `87be8cbc` plus Dokumentations-/Inventardiff **PASS**; PR-CI und
  externer Review stehen noch aus. `server.py`: 5.428 physische Zeilen.

## P7 lokaler Bibliotheksplan — bestätigter #743-Merge

- #743 auf Head `c6dd94db`: CodeQL, SonarCloud, Container-/Browser-
  und Codex-Code-/Security-Prüfung **PASS**, 0 offene Review-Threads.
  Ein transienter GitHub-API-500 ließ die erste Review-Gate-Abfrage
  fail-closed; derselbe Workflow wurde ohne weiteren Review-Auftrag
  erfolgreich wiederholt. Squash-Merge
  `211b4bd47f16d4bf69057cd6262bbd494550a961` am
  `2026-09-23T19:54:27Z` bestätigt und auf `origin/develop` erreichbar.

## P7 sitzungsgebundene Coach-Receipts — Integrationsreview

- GPT-6-Luna/high-Patch `fb97ce47`: Root-Diffreview zunächst **FAIL**
  wegen redundant injiziertem `proposal_view`-Callback. Derselbe Worker
  entfernte ihn in `6259b01d`; fokussierte und Architekturtests 8/8,
  volle Suite 2.361 Tests/12 Skips, Ruff, Compile und Diff-Check **PASS**.
- Sequenziell auf #743 rebased als `dbce4d16` und `0719c080` ohne
  Konflikt. Root prüfte den gesamten neuen Diff und Code erneut:
  **PASS**. Der Service besitzt DB-Read-UOW, Session-Owner-Prüfung,
  aktuelle Proposal-/TTL-Projektion und entfernt den Session-Schlüssel;
  Planning-/Chat-/HTTP-/SSE-Aufrufer delegieren ohne Server-Wrapper.
  Die vier neuen Tests prüfen 400/403/404, Fremdsitzung, abgelaufene
  und konsumierte Vorschläge sowie Restore-Drain-Kompatibilität;
  bestehende Dialog-/HTTP-Tests ergänzen die Integration. Post-Rebase-
  native Vollsuite **PASS**, 2.371 Tests/12 Skips; Python-3.14-
  Docker-Build und vollständige Read-only-Docker-Suite **PASS**,
  2.371 Tests/11 Skips. Ruff, Compile, Inventar- und Diff-Check
  **PASS**. Root-Gate des integrierten lokalen Stands `0719c080`
  plus Dokumentations-/Inventardiff **PASS**; PR-CI und externer
  Review stehen aus. `server.py`: 5.404 Zeilen, 257 Definitionen.

## P10 Export-HTTP-Streaming — Integrationsreview

- GPT-6-Luna/high-Patch `0185e0b8`: Root-Diffreview zunächst **FAIL**,
  weil beide Exportdienste für jede Route eager konstruiert wurden.
  Derselbe Worker korrigierte dies in `efb232c0`; die Route löst nun
  ausschließlich ihren eigenen Dienst auf. Worker-Fokustests und
  Architektur 7/7, Vollsuite 2.360 Tests/12 Skips, Ruff, Compile und
  Diff-Check **PASS**.
- Sequenziell auf den bestätigten #744-Merge rebased als `c82f5100`
  und `48b86928`, ohne Konflikt. Root prüfte den gesamten Code und Diff
  erneut: **PASS**. Der HTTP-Transport besitzt Backup-/Privacy-
  Download-Orchestrierung; Lock bis zum Ende des Sendens, Deadlines,
  Cleanup und Auth-Reihenfolge bleiben erhalten. Der Server enthält
  nur Service-Composition und Route-Delegation, keine Fach-Callbacks.
  Root ergänzte je Route einen positiven und verweigerten Auth-Pfad
  und entfernte die verwaiste MIME-Konstante.
- Die Testzahl ist für diese Grenze angemessen: drei neue Transporttests
  decken Lock/Fehler, Cleanup/Deadline und Lazy-Construction ab; der
  neue parametrische Routentest prüft beide Auth-Grenzen vor dem
  Factory-Aufruf. Bestehende Backup-/Privacy-Tests prüfen Archivinhalt,
  Limits und temporäre Dateien. Integrierte Fokustests und Architektur
  8/8; native Gesamtsuite **PASS**, 2.375 Tests/12 Skips;
  Python-3.14-Docker-Build und vollständige Read-only-Docker-Suite
  **PASS**, 2.375 Tests/11 Skips. Ruff für neue Module, Compile,
  Inventar- und Diff-Check **PASS**. Root-Gate für `48b86928` plus
  Integrationsdiff **PASS**; PR-CI und externer Review stehen aus.
  `server.py`: 5.393 physische Zeilen, 256 Definitionen;
  `backend/`: 39.191 Zeilen, zusammen 44.584 Zeilen.
## P8 Cancellation und dauerhafte Receipt-Merges — lokaler Prüfstand

- Root-Implementierungsdiff auf #735-Basis `f6f310ec`: **PASS** nach
  tatsächlichem Code-/Diffreview. `CoachCancellationService` besitzt
  Attached-/Background-Cancel samt Session-Bindung, persistierter
  Markierung vor dem Event-Signal, Provider-Response-Close und
  fehlendem In-Memory-Event nach Restart. `CoachJobStore` besitzt den
  atomaren Receipt-Merge und löst den aktuellen Manager erst unter
  `DB_LOCK` auf; `server.py` komponiert und delegiert ohne frühere
  Receipt-/Cancel-Wrapper. Der HTTP-Cancel-Pfad bleibt nach Auth/CSRF
  außerhalb des Maintenance-Gates erreichbar.
- Fokussierte Cancellation-/Job-Store-Tests 10/10,
  Architekturtests 4/4, Ruff, Compile, Inventar- und Diff-Check
  **PASS**. Vollsuite lokal **PASS**, 2.348 Tests, 12 Skips;
  neu gebautes Read-only-Docker-Image **PASS**, 2.348 Tests,
  11 Skips. `server.py` umfasst 5.705 physische Zeilen und
  263 Definitionen auf dieser älteren Basis. Rebase auf aktuelles
  `develop`, erneutes Integrationsreview, PR-CI und Merge stehen aus.
## P8 terminale Coach-Fehler — lokaler Zwischenstand

- Root-Worktree `refactor/p8-failure-state-20260923` auf #741-Basis:
  `CoachTurnFailureService` übernimmt vollständige Fehlerprojektion,
  Pending-Request und atomare Receipt-/Nachrichtenpersistenz. Die
  technischen Diagnosemetadaten liegen ebenfalls im Backend; `server.py`
  komponiert nur Ressourcen und delegiert alle bisherigen Aufrufer.
- Root-Code-/Diffreview **PASS** auf diesem lokalen Stand: keine
  `server.py`-Rückimporte oder fachlichen Server-Callbacks; DB-Lock und
  Manager-Auflösung liegen in derselben UOW, Rollback bei Schreibfehler,
  Event erst nach Commit. Neue Tests decken partielle Effekte, sensible
  Checkpoint-Bereinigung, Cancellation/Replay und Rollback ab. Die drei
  bestehenden Antworttexttests und der Privacy-Worker-Patch wurden auf den
  neuen Eigentümer umgestellt.
- Native vollständige Suite **PASS**, 2.360 Tests, 12 Skips; fokussierte
  Failure-Tests 3/3, bestehende Response-/Privacy-Tests 18/18 (1 Skip),
  Architektur 4/4, Ruff, Compile und Diff-Check **PASS**. Der Stand ist
  noch nicht auf das aktuelle `develop` rebased oder als PR veröffentlicht;
  danach sind erneutes Review und vollständige Integrationstests nötig.

## P10 Export-HTTP-Streaming — bestätigter #745-Merge

- #745 auf Head `28781021`: CodeQL, SonarCloud, Container-, Browser-
  und Codex-Code-/Security-Prüfung **PASS**, 0 offene Review-Threads.
  Der formale Titel-Check schlug zunächst wegen fehlendem
  Conventional-Commit-Präfix fehl; nach Titelkorrektur **PASS**.
  Squash-Merge `30689b85b3ff3fcb5e72f8e2671467a7da33238e` am
  `2026-09-23T20:16:10Z` bestätigt und auf `origin/develop` erreichbar.

## P8 Cancellation und terminale Fehler — Integrationsreview

- Root integrierte die beiden lokalen P8-Patches sequenziell auf den
  bestätigten #745-Merge als `d0e17271` und `7ee41786`. Beim ersten
  Rebase wurden die #744-Receipt-Owner-Prüfungen bewahrt; beim
  Cherry-Pick wurde die ältere `coach_command_receipt`-Funktion nicht
  in `server.py` zurückgebracht. Das generierte Inventar wurde nach
  jedem Konflikt neu erzeugt. Root prüfte den vollständigen Diff und
  den Code der beiden konkreten Services erneut: **PASS**.
- `CoachCancellationService` koordiniert Session-gebundenes Attached-
  und Background-Cancel, persistiert vor dem Event-Signal und schließt
  Provider-Responses; Stream-Register und Job-Store behalten ihre
  eigenen Zustände. `CoachJobStore` besitzt den atomaren Receipt-Merge
  und löst den aktuellen DB-Manager unter Lock auf. `CoachTurnFailureService`
  besitzt partielle Fehlerprojektion, Pending-Request, atomare
  Nachricht/Receipt-UOW, Checkpoint-Cleanup und Post-Commit-Event.
  Keine Server-Rückimporte oder Fach-Callbacks; Auth/CSRF und
  Maintenance-Grenzen bleiben unverändert.
- Sieben neue Fälle prüfen falsche Operation/Session, Cancel-Reihenfolge,
  Restart ohne In-Memory-Event, aktiven Status/Managerwechsel, partielle
  Effekte mit sensiblen Checkpoints, Cancellation/Replay und Rollback.
  Vorhandene Dialog-, Background- und HTTP-Tests decken Retry,
  Wiederaufnahme und Antwortformate ergänzend ab. Testzahl für diese
  Teilgrenzen angemessen; der gesamte Turn und Worker-Resume sind noch
  offen und benötigen eigene weitere Tests.
- Integrierte Fokustests und Architektur **PASS**, 17/17; nach direkter
  Migration zweier Test-Patch-Ziele die betroffenen Tests 2/2 erneut
  **PASS**. Native Vollsuite **PASS**, 2.382 Tests/12 Skips;
  Python-3.14-Docker-Build und vollständige Read-only-Docker-Suite
  **PASS**, 2.382 Tests/11 Skips. Ruff für neue Module, Compile,
  Inventar- und Diff-Check **PASS**. Root-Gate für `d0e17271` und
  `7ee41786` plus Test-/Dokumentationsdiff **PASS**; PR-CI und
  externer Review stehen aus. `server.py`: 5.240 Zeilen,
  246 Definitionen; `backend/`: 39.537 Zeilen, zusammen 44.777.

## P8 Cancellation und terminale Fehler — bestätigter #746-Merge

- #746 auf Head `df655ef4`: CodeQL, SonarCloud, Container-, Browser-
  und Codex-Code-/Security-Prüfung **PASS**, 0 offene Review-Threads.
  Squash-Merge `25d00641d928f176d1f12882ff20e1510c848108` am
  `2026-09-23T20:30:01Z` bestätigt und auf `origin/develop` erreichbar.

## P8 Restart-Recovery — integrierter lokaler Prüfstand

- Root-Commit `c2b6a37a` liegt als einzelner Recovery-Commit auf dem
  bestätigten #746-Merge; der vorherige, auf Squash-Commits zeigende
  Rebase-Versuch wurde abgebrochen und mit `rebase --onto` ohne Übernahme
  älterer PR-Commits wiederholt. Root prüfte den tatsächlichen Diff und
  den Code nach der Integration erneut: **PASS**.
- `CoachJobStore.resume_interrupted` besitzt die Restart-Entscheidung
  einschließlich persistierter Intents, OpenAI-Response-Fortsetzung,
  Nicht-Wiederholung unterbrochener Gemini-Turns, Queue-Phase und
  Worker-Wake. `server.py` ruft den konkreten Eigentümer nur bei Start
  und nach Restore auf. Die frühere Abfrage las das Gemini-Intent nicht;
  die neue Abfrage schließt diese Lücke. Keine Server-Rückimporte,
  Fach-Callbacks oder Änderung an Autorisierungsgrenzen.
- Neue Unit-Tests prüfen Attached-/Gemini-Fehler samt Intent und
  `process_interrupted`, OpenAI-/Queued-Requeue, Managerwechsel und
  ausbleibenden Wake ohne Jobs. Bestehende Start-/Restore-/Gemini-
  Integrationstests wurden auf den Eigentümer umgestellt und bleiben
  wirksam. Testumfang für diese Teilgrenze angemessen; Worker-Turn-
  Orchestrierung und gesamter Restore sind noch offen.
- Fokussierte Unit-/Architekturtests **PASS**, 13/13; Ruff, Compile,
  Inventar- und Diff-Check **PASS**. Native Vollsuite **PASS**,
  2.384 Tests/12 Skips; frisch gebautes Python-3.14-Image und
  vollständige Read-only-Docker-Suite **PASS**, 2.384 Tests/11 Skips.
  Das Root-Gate für `c2b6a37a` samt Integrations- und Dokumentationsdiff
  ist **PASS**; PR-CI und externer Review stehen noch aus.
  `server.py`: 5.200 Zeilen, 245 Definitionen.

## P8 Restart-Recovery — bestätigter #747-Merge

- #747 auf Head `b828ca9a`: Container-, Browser-, CodeQL-, SonarCloud-
  und übrige CI-Prüfungen **PASS**, 0 offene Review-Threads. Der erste
  Codex-Gate-Lauf schlug trotz befundfreiem Review mit einem unerwarteten
  Koordinatorfehler fail-closed fehl; ein regulärer Wiederholungslauf
  desselben geschützten Workflows erzeugte für denselben Head den grünen
  Gate-Check, ohne einen zweiten Review anzufordern. Squash-Merge
  `41675599ed8d9e863036c3620beec5b2f3cafbdd` am
  `2026-09-23T20:46:46Z` bestätigt und auf `origin/develop` erreichbar.

## P8 strukturierter Provider-Request — integrierter lokaler Prüfstand

- Luna-Commit `2d6b670f` wurde als einzelner Patch auf den bestätigten
  #747-Merge rebasiert (`f235ab84`). Root prüfte den tatsächlichen Code
  und Diff erneut: **PASS**. `CoachRequestPayloadService` besitzt die
  komplette Request-Projektion inklusive Dialog-/Attachment-Kontext,
  Modell-/Thinking-Auswahl, OpenAI-Kontinuität und Gemini-Medien. Der
  Server konstruiert den konkreten Service und delegiert; es gibt keine
  Server-Rückimporte oder fachlichen Server-Callbacks.
- Vier neue Unit-Tests decken OpenAI-Kontinuität und lokale Zusammenfassung,
  Advisory-Grenze, Gemini-Bild und untrusted-evidence-Anweisung sowie
  Modell-/Thinking-/Token-Fallback ab. Vorhandene Attachment-Tests bleiben
  wirksam. Testumfang für diesen Payload-Baustein angemessen; die
  Response-/Tool-Rundenschleife benötigt später eigene Regressionen.
- Fokussierte Tests einschließlich Attachment-/Architektur-Checks
  **PASS**, 27/27; Ruff, Compile, Inventar- und Diff-Check **PASS**.
  Native Vollsuite **PASS**, 2.388 Tests/12 Skips; frisch gebautes
  Python-3.14-Image und vollständige Read-only-Docker-Suite **PASS**,
  2.388 Tests/11 Skips. Root-Gate für `f235ab84` samt
  Integrations-/Dokumentationsdiff **PASS**; PR-CI und externer Review
  stehen aus. `server.py`: 5.150 Zeilen, 245 Definitionen.

## P8 strukturierter Provider-Request — bestätigter #748-Merge

- #748 auf Head `658aa643`: alle Container-, Browser-, CodeQL-,
  SonarCloud-, Codex-Code-/Security- und weiteren CI-Prüfungen **PASS**,
  0 offene Review-Threads. Squash-Merge
  `ac91b7e9a8be637d2c5256a5a5a419a19fe9c09d` am
  `2026-09-23T21:00:35Z` bestätigt und auf `origin/develop` erreichbar.

## P10 öffentliches State-SSE — integrierter lokaler Prüfstand

- Luna-Ausgangscommit `797a13e8`: Root-Diffreview zunächst **FAIL**,
  weil ein migrierter Test den neuen Eigentümer über `server.py` ansprach
  und ein enger Architektur-Guard für die alten Handler-Methoden fehlte.
  Der gleiche Worker korrigierte beide Befunde, ergänzte einen expliziten
  401-Routentest und regenerierte nach Testzeilenänderungen das Inventar.
  Endcommit `0caa3182` wurde als einzelner Patch auf #748 rebasiert
  (`122dc349`); Root prüfte den vollständigen Code/Diff erneut:
  **PASS**.
- `StateEventTransport` besitzt Cursor-Validierung, Initial-/Ready-Events,
  Gap-Reset, 15-Sekunden-Heartbeat und Disconnect-Schleife. Der Puffer
  bleibt bei `runtime_events`, Socket- und Schreibzustand beim Handler;
  dieser authentifiziert vor Konstruktion und delegiert nur. Keine
  Server-Rückimporte, Fach-Callbacks oder zurückgebliebene SSE-Orchestrierung.
- Vier neue Transportfälle und der Route-/Auth-Test prüfen Cursor, Event-
  Reihenfolge, Gap/Heartbeat, Disconnect und 401 vor Streamstart. Der
  ergänzte AST-Guard verbietet beide entfernten Handler-Methoden. Testzahl
  für diese SSE-Teilgrenze angemessen; Coach-Chat-Stream bleibt separat
  offen. Fokussierte Transport-/Architekturtests **PASS**, 9/9;
  Inventar- und Diff-Check **PASS**. Frisch gebautes Python-3.14-Image
  und vollständige Read-only-Docker-Suite **PASS**, 2.394 Tests/11 Skips.
  Native Vollsuite **PASS**, 2.394 Tests/12 Skips; Ruff und Compile
  **PASS**. Root-Gate für `122dc349` samt vollständigem Integrations-
  und Dokumentationsdiff **PASS**; PR-CI und externer Review stehen
  noch aus. `server.py`: 5.122 Zeilen, 245 Definitionen.

## P10 öffentliches State-SSE — bestätigter #749-Merge

- #749 auf Head `2f1f10be`: alle Container-, Browser-, CodeQL-,
  SonarCloud-, Codex-Code-/Security- und weiteren CI-Prüfungen **PASS**,
  0 offene Review-Threads. Squash-Merge
  `6cca5c8a5aa60cc32da09b9e516db963e6e0938e` am
  `2026-09-23T21:14:11Z` bestätigt und auf `origin/develop` erreichbar.

## P9 vollständiger Datenbank-Restore — integriertes Root-Review

- Root-Ausgangscommit `dd899678` auf dem bestätigten #747-Merge,
  auf den #749-Merge rebasiert als `fff95a16`. Root hat den tatsächlichen
  integrierten Code und Diff einschließlich aller Aufrufer geprüft:
  **PASS**. Keine Server-Rückimporte oder fachlichen Server-Callbacks;
  Lock, Maintenance-Gate, Backup, Swap und Worker-Wiederaufnahme haben
  einen konkreten Eigentümer.
  `DatabaseRestoreService` besitzt das
  Wartungsgate, Staging/Validierung über den bestehenden konkreten
  Validierungsservice, Checkpoint und DB-Drain unter `DB_LOCK`, eindeutige
  vorherige Sicherung, atomaren Dateiaustausch, Temp-Cleanup sowie die
  Sync-/Coach-Job-Wiederaufnahme und Wake-Events. `server.py` konstruiert
  nur den Eigentümer; der HTTP-Handler behält Auth/CSRF und Body-Limit.
- Fünf neue temporäre, providerfreie Tests prüfen Reihenfolge und Gate,
  unveränderte Live-DB bei ungültigem Backup, redigierte Fehler,
  fehlgeschlagenen Austausch und zwei eindeutige Sicherungen innerhalb
  kurzer Zeit. Die vorhandenen SQLCipher-Integrationstests prüfen exaktes
  Schema, Session-Bereinigung und Sync-Job-Recovery im Container.
- Die erste Codefassung bestand native Vollsuite **PASS**,
  2.388 Tests/12 Skips, und Read-only-Docker **PASS**,
  2.388 Tests/11 Skips. Danach wurde die Sicherungsnamen-Kollision
  behoben und ein fünfter Test ergänzt: fokussiert 9/9, Ruff,
  Compile, Inventar- und Diff-Check **PASS**. Die Vollsuiten des
  endgültigen Codes bestanden nativ mit 2.389 Tests/12 Skips und im
  frisch gebauten Read-only-Docker mit 2.389 Tests/11 Skips. Integration
  auf aktuelles `develop`: fokussierte Restore-/Architekturtests 10/10,
  Ruff der neuen Dateien, Compile, Inventar- und Diff-Check **PASS**;
  native Vollsuite **PASS**, 2.399 Tests/12 Skips, und frisch gebautes
  Read-only-Docker **PASS**, 2.399 Tests/11 Skips. Die Testzahl ist für
  diese Grenze angemessen: fünf neue Fehler-/Reihenfolge-/Sicherungsfälle
  plus vorhandene echte SQLCipher-/HTTP-Integrationsfälle. PR-CI und Merge
  stehen noch aus. `server.py`: 5.089 Zeilen, 242 Definitionen.
  Der existierende Vertrag rollt
  Validierungs-/Swap-Fehler vor erfolgreichem Austausch zurück;
  ein Fehler während der nachgelagerten Worker-Wiederaufnahme löst
  weiterhin keinen zweiten Datenbanktausch aus.

## P9-Review-Nacharbeit — Inventarzuordnung

- Der externe Review von PR #750 auf Head `2ff23152` meldete einen
  berechtigten P2-Befund: `database_restore_service` war im Generator
  noch nicht als Composition-Root-Factory erfasst. Root-Gate für diesen
  PR-Stand deshalb **FAIL**, trotz grüner Code- und Laufzeittests.
- Root prüfte alle elf entsprechenden offenen P0-Funktionen im
  tatsächlichen `server.py`: sie sind reine Factory-/Transport-
  Komposition, keine ausgelagerte Fachlogik. Alle explizit dem
  Composition Root zugeordnet; das generierte Inventar weist nun
  **0 offene P0-Symbole** aus. Ein Architekturtest schützt diese
  Invariante, damit ein konsistentes, aber falsch klassifiziertes
  Inventar künftig nicht als abgeschlossen gilt.
- Korrigierter Code/Diff erneut **PASS** geprüft. Architekturtests 6/6,
  Generator-`--check`, Ruff, Compile und Diff-Check **PASS**. Native
  Vollsuite **PASS**, 2.400 Tests/12 Skips; frisch gebautes Read-only-
  Docker-Image **PASS**, 2.400 Tests/11 Skips. Review-Thread-Auflösung,
  aktualisierte PR-CI und Merge stehen noch aus.

## P9 Restore — bestätigter #750-Merge

- #750 auf korrigiertem Head `7dd86a33`: Root-Gate **PASS**;
  P2-Review-Thread beantwortet und gelöst, geschützter Codex-Gate-
  Workflow regulär erneut ausgewertet und **PASS**. Alle erforderlichen
  Checks **PASS**. Squash-Merge
  `7ab9b982de26ddf04c92f40215cab5b488186100` am
  `2026-09-23T21:33:08Z` bestätigt und auf `origin/develop` erreichbar.
  Der nicht erforderliche Browser-Smoke-Check war beim Merge noch
  unterwegs und wurde danach **PASS** (5m29s) nachkontrolliert.

## P7 Read-only Coach-Tools — erster integrierter Patch

- Luna-Ausgangscommit `bca00d69` wurde als einzelner Patch auf #750
  integriert (`7b1d1c24`). Root prüfte den tatsächlichen integrierten
  Diff und Code erneut: **PASS**. Auswahl, Limits und Antwortprojektion
  aller Read-Tools liegen im konkreten Backend-Eigentümer; die
  Domänendienste behalten Zustand, und `server.py` delegiert ohne Rückimport.
  Neue Factory im Inventargenerator als Composition-Root-Verdrahtung
  erfasst, P0 bleibt 0.
- Vier neue direkte Unit-Tests decken alle Toolnamen, Filter und Cursor,
  obere/untere Grenzwerte, fehlerhafte Limits und unbekannte Namen ab.
  Für diese lokale Leseschnittstelle angemessen. Nach Integration:
  fokussierte Service-/Architekturtests 10/10, Ruff, Compile,
  Inventar- und Diff-Check **PASS**. Der zweite P7-Patch und die
  gemeinsame Vollregression stehen noch aus.

## P7 Planartefakt-Werkzeug — zweiter integrierter Patch

- Luna-Ausgangscommit `caf05e09` wurde nach dem Read-Tool-Stand
  sequenziell integriert (`ee5760d2`). Der Konflikt mit dem älteren
  Server-Read-Dispatcher wurde durch Entfernung beider bereits
  ausgelagerter Funktionsblöcke gelöst; das Inventar wurde auf dem
  kombinierten Code erneut generiert. Root prüfte den tatsächlichen
  Code/Diff beider P7-Bausteine: **PASS**.
- `CoachPlanArtifactToolService` besitzt Operation-, Scope- und
  Artifact-ID-Prüfung vor jedem Planning-Service-Aufruf. Der konkrete
  `TrainingPlanArtifactService` behält Speicherung, Revisionprüfung und
  atomaren Commit; `server.py` injiziert nur seine Factory. Keine
  Rückimporte, keine neuen Remote-Schreibrechte oder dauerhaften
  Kompatibilitätsfunktionen.
- Acht direkte Tests prüfen Stage/Commit samt Autorisierung, fehlender
  und fremder Artifact-ID, explizitem Flag und unbekanntem Tool. Zusammen
  mit bestehenden Planning-Integrationen für diese Grenze angemessen.
  Nach Integration: fokussierte Service-/Architekturtests 18/18, Ruff,
  Compile, Inventar- und Diff-Check **PASS**. Gemeinsame native
  Vollsuite **PASS**, 2.412 Tests/12 Skips; frisch gebautes Read-only-
  Docker-Image **PASS**, 2.412 Tests/11 Skips. Root-Gate für den
  kombinierten Stand `ee5760d2` samt Integrations-/Dokumentationsdiff
  **PASS**; PR-CI und externer Review stehen noch aus. `server.py`:
  5.023 Zeilen, 240 Definitionen; P0-Inventar 0.

## P7 Read-/Planartefakt-Werkzeuge — bestätigter #751-Merge

- #751 auf Head `c50e1854` bestand Root-Gate und alle CI-/Review-Prüfungen
  einschließlich Browser, Qualität und Security; keine offenen Review-Threads.
  Squash-Merge `a8cad23b5f74b6704b1efbc5eec892f5612ce3e5` am
  `2026-09-23T21:47:52Z` bestätigt und als Vorfahr von `origin/develop`
  geprüft.

## P7 strukturierte Planmutationen — integrierter Patch

- Luna-Ausgangscommit `f611bf0b` wurde auf dem bestätigten #751-Stand ohne
  Konflikt als `d4de9e68` integriert. Root prüfte den tatsächlichen Diff und
  Code: **PASS** für Operation-/Objekt-Scope, unveränderte
  Perioden-/Constraint-Projektion und Revision-Flag. Die atomaren
  Replacement-/Change-Services bleiben Eigentümer von Revision, Hash und
  Rollback; keine Backend-Rückimporte, Server-Fachcallbacks, neuen Remote-
  Schreibrechte oder Kompatibilitäts-Wrapper.
- 13 neue direkte Tests prüfen erlaubte und abgelehnte Operationen,
  Mehrfach-/Fremdplan- und Unit-Scopes, Argumentprojektion und unbekannte
  Werkzeuge. Die vorhandenen DB-Integrationstests prüfen Revision,
  Payload-Hash und Rollback. Diese Kombination ist für die ausgelagerte
  Autorisierungsgrenze angemessen; die gesamte P7-Orchestrierung bleibt
  ausdrücklich offen.
- Integrierte fokussierte Service-/Architekturtests **PASS** (19/19),
  Inventargenerator `--check`, Ruff der geänderten Backend-/Testdateien,
  Compile und Diff-Check **PASS**. Frisch gebautes Read-only-Docker-Image:
  Vollsuite **PASS**, 2.425 Tests/11 Skips. Native Vollsuite **PASS**,
  2.425 Tests/12 Skips. Finaler integrierter Code/Diff **PASS**.
  `server.py`: 4.964 physische Zeilen, 237 Definitionen; P0-Inventar 0.
  Nächster Schritt: PR gegen `develop` veröffentlichen und
  CI/Review/Merge verifizieren.

## P7 strukturierte Planmutationen — bestätigter #752-Merge

- #752 auf Head `f396cf3c` bestand Root-Gate, native und Read-only-Docker-
  Vollsuite, CodeQL/Sonar, Qualitäts- und Containerchecks. Der einmalig
  angeforderte Codex-Code- und Security-Review war auf diesem Head ohne
  Befund; keine offenen Review-Threads. Ein früher Koordinationsjob wurde
  beim manuellen Review-Wechsel abgebrochen und war nicht mergeblockierend.
- Squash-Merge `ba61818a4365be2abf2544c8cc711ce94f972302` am
  `2026-09-23T22:04:32Z` bestätigt und als Vorfahr von `origin/develop`
  geprüft. Der zum Mergezeitpunkt noch laufende optionale Browser-Smoke-
  und Accessibility-Check wurde nachträglich **PASS** (5m42s).

## P7 Planungshandlungs-Werkzeuge — integrierter Patch

- Der erste Worker-Diff scheiterte am Root-Gate (**FAIL**): ein alter
  Server-Wrapper blieb bestehen. Der zweite Zwischenstand führte die
  fachlich verschiedenen Werkzeuge unter `misc_tools` als neuem Sammelmodul;
  ebenfalls **FAIL**. Derselbe GPT-6-Luna-Worker entfernte den Wrapper und
  benannte die fachlich zusammengehörigen Planungshandlungen samt Tests und
  Architektur-Guard um.
- Finaler Worker-Commit `43c37418` wurde ohne Konflikt auf dem bestätigten
  #752-Merge als `e9036256` integriert. Root prüfte den tatsächlichen Code
  und Diff erneut: **PASS**. Operation-/Objekt-Scope, Action-Payload,
  späterer Adaptive-Apply-Turn und sitzungsgebundene Undo-Proposal-Erzeugung
  bleiben erhalten. Die vorhandenen Preview-, Apply-, Plan-, History- und
  Proposal-Services besitzen weiterhin ihren Zustand. Keine Backend-
  Rückimporte, Server-Fachcallbacks, Remote-Schreibausweitung oder
  Kompatibilitätsfunktion.
- Zwölf neue direkte Positiv-/Negativtests decken alle vier Toolnamen,
  abgelehnte Operationen und Objektscopes, unbekannte Namen, Proposal-
  Sitzungsbindung und Fehlerweitergabe ab. Die vorhandene Integration
  prüft Commit, Rollback, Replay und Sync-Scope. Für diese Grenze
  angemessen; vollständiger Coach-Tool- und Turn-Dispatch bleibt offen.
  Integriert: fokussierte Service-/Architekturtests **PASS** (20/20),
  Inventar-`--check`, Ruff, Compile und Diff-Check **PASS**. Native
  Vollsuite **PASS** (2.439 Tests/12 Skips), frisch gebautes Read-only-
  Docker-Image **PASS** (2.439 Tests/11 Skips). `server.py`: 4.932
  physische Zeilen, 236 Definitionen; P0-Inventar 0.
- Nächster Schritt: übergreifenden Coach-Tool-Dispatch als eigenen
  Backend-Use-Case auslagern und alle direkten Server-Testaufrufer sowie
  zwei Test-Patchziele auf die neue Schnittstelle migrieren; danach
  den kombinierten Stand erneut reviewen und veröffentlichen.

## P7 gesamtes strukturiertes Werkzeug-Routing — Root-Integration

- Auf dem geprüften Stand `e9036256` verlagerte Root die bisherige
  `_structured_coach_plan_tool_result`- und
  `_structured_coach_tool_result`-Orchestrierung vollständig in
  `CoachToolDispatchService`. Die einzige neue Server-Factory verdrahtet
  konkrete Eigentümer verzögert; ihre Callables konstruieren Services und
  enthalten keine Werkzeug-Fachlogik. Unbekanntes Werkzeug bleibt 400/
  `unknown_coach_tool`, Sync-Job-Liste und Cancellation-Event behalten
  dieselbe Instanz, und Conversation-/Turn-/Session-Bindungen gehen
  unverändert an Planartefakt und Planungshandlungen.
- 44 direkte Testaufrufe wechseln zur tatsächlichen Dispatcher-
  Schnittstelle. Zwei Replay-Tests patchen nun deren Klassenmethode am
  neuen Lookup-Ort statt eine gelöschte Server-Funktion. Acht direkte
  Dispatcher-Tests decken Lesepriorität, lokale Mutationen, Plan- und
  Sync-Routing, Weitergabe der Sicherheitskontexte und den Unknown-Fehler
  ab. Zusammen mit den bestehenden 84 gezielten Dialog-/Review-Tests
  und der vollen Regression ist diese Testmenge für das reine Routing
  angemessen; fachliche Scope-/Transaktionsfehler bleiben zusätzlich bei
  ihren konkreten Service-Tests. Spezialwerkzeuge und Turn-Fehlerprojektion
  verbleiben ausdrücklich in der offenen P7/P8-Arbeit.
- Root prüfte Code und tatsächlichen kombinierten Diff nach den
  Testmigrationen: **PASS**. Fokussierte Dialog-/Review-/Dispatcher-/
  Architekturtests **PASS** (68+16+14), Ruff ohne neue Server- oder
  Legacy-Test-Findings, neue Dateien/Architektur/Generator Ruff **PASS**,
  Compile, Inventar-`--check` und Diff-Check **PASS**. Native Vollsuite
  **PASS** (2.447 Tests/12 Skips); frisch gebautes Read-only-Docker-Image
  **PASS** (2.447 Tests/11 Skips). `server.py`: 4.890 physische Zeilen,
  235 Definitionen; P0-Inventar 0. PR-CI, externer Review und Merge
  stehen noch aus.

## P7 Tool-Routing und Planungshandlungen — bestätigter #753-Merge

- #753 auf Head `2b2105cf` bestand Root-Gate, native und Read-only-Docker-
  Vollsuite, CI-Testshards, Container, Qualität, Sonar und CodeQL. Der
  einmalig angeforderte Codex-Code-/Security-Review fand keine Probleme;
  keine offenen Review-Threads.
- Squash-Merge `e79b89375f7cb08e7b1967b426fb97e508d5a3e1` am
  `2026-09-23T22:33:50Z` bestätigt und als Vorfahr von `origin/develop`
  geprüft. Der zum Mergezeitpunkt noch laufende optionale Browser-Smoke-/
  Accessibility-Check wurde nachträglich **PASS** (6m8s).

## P7 Dialog-Plan-/Artefakt-Scopes — integrierter Patch

- GPT-6-Luna-Ausgangscommit `ce1b6d77` wurde auf den bestätigten #753-
  Merge als `e60cd348` ohne Konflikt integriert. Root prüfte den
  tatsächlichen Code/Diff: **PASS**. Vier Datums-/Planned-Unit-/Draft-
  Prüffunktionen samt ihrer Prüf-Orchestrierung gehören nun einem
  konkreten `CoachDialoguePlanScopeService`; der Server ruft ihn direkt
  auf und behält keinen Wrapper. Kein Backend-Rückimport oder
  Server-Fachcallback. Die bestehende DatabaseManager-UOW wird unter
  demselben `DB_LOCK` geöffnet; Artifact-Herkunft muss vor dem expliziten
  Flag erfolgreich geprüft werden.
- Neun direkte Tests mit temporärer SQLite-DB prüfen gültige und
  unzulässige Daten, Unit-Scope, fehlende Einheit, fremdes Draft,
  Artefakt-Flag und ausschließlich lesende SQL-Prüfung. Für diese
  lokale Prüfgrenze angemessen, zusammen mit bestehenden Dialog-
  Integrationen. Worker-Vollsuite **PASS** (2.456 Tests/12 Skips),
  betroffene Integrationen **PASS** (492/3 Skips). Nach Integration:
  direkte/Architekturtests **PASS** (15/15), Dialog-Harness **PASS**
  (68/68), Ruff, Compile, Inventar-`--check` und Diff-Check **PASS**.
  Vollständige Root-Regression des kombinierten Folgestands und PR-CI
  stehen noch aus.

## P7 Dialog-Autorisierung — Root-Integrationsreview

- Integrierter Ausgangsstand `e60cd348` auf #753-Squash `e79b8937`;
  Root-Diff dieses Worktrees (noch nicht committet) manuell geprüft:
  **PASS** für Request-Provenienz, Remote-Schreib-/Refresh-Ziel,
  Retry-Provider, lebende Objekt- und Plan-Scopes, Reparaturzeitraum
  und die unveränderte Lock/UOW-Eigentümerschaft. Sechs vormals
  servereigene Funktionen sind vollständig in
  `CoachDialogueActionService.classify` verlagert; der Server komponiert
  nur konkrete Backend-Dienste und ruft die Methode direkt auf.
  Kein Rückimport, Fachcallback oder Kompatibilitätswrapper.
- Sieben neue direkte Sicherheitsfälle (Advice-only, fremde Nachricht,
  Remote-Freigabe, Providerziel, fehlendes Objekt, Reparaturumfang,
  erlaubter lokaler Scope) ergänzen die bestehenden Dialog-Integrationen
  für Retry, archivierte Pläne und mehrstufige Korrekturen. Diese
  Abdeckung ist für die ausgelagerte Autorisierungsgrenze angemessen;
  P7-Turn-Orchestrierung wird separat weiter geprüft.
- Betroffene Dialog-/Architekturtests 74/74 **PASS** vor dem neuen
  Sicherheitsfall; neuer Fall separat **PASS**. Frisch gebautes
  Read-only-Docker-Image: 2.457 Tests/11 Skips **PASS**. Native
  Vollsuite: 2.457 Tests/12 Skips **PASS** (214,605 s). PR-CI noch
  ausstehend. Inventar `--check`, Compile,
  Ruff für das neue Backend-Modul und Diff-Check **PASS**.
  `server.py`: 4.746 physische Zeilen, 225 Definitionen;
  P7 verbleiben 52 Definitionen/28 globale Bindungen. Nächster
  Schritt: Root-Gate auf finalem Diff, dann PR gegen aktuellen
  `develop` veröffentlichen.

## P7 Dialog-Scopes und Autorisierung — bestätigter #754-Merge

- Root-Gate **PASS** auf Commit `a63a28c7`; native und frisch
  gebaute Read-only-Docker-Vollsuiten **PASS** (je 2.457 Tests,
  12/11 Skips). CI-Testshards, Container, Quality, Sonar, CodeQL und
  der einmalig angeforderte Codex-Code-/Security-Review **PASS**;
  null offene Review-Threads. Der zum Mergezeitpunkt noch laufende
  optionale Browser-Smoke-/Accessibility-Check wurde anschließend
  **PASS** (5m46s).
- Squash-Merge `df885603c3162f57e88979ce5768d835dba25fd0` am
  `2026-09-23T22:57:03Z` mit `state=MERGED`, `mergedAt` und
  Erreichbarkeit auf `origin/develop` bestätigt.
- P7 bleibt offen: Rückfrage-Persistenz, atomare Trainings-Patches,
  strukturierte Coach-Turn-Orchestrierung und weitere Eigentümer.

## P7 Rückfrage-Persistenz — integrierter Prüfstand

- GPT-6-Luna/high-Worker `6f2cd806` wurde auf bestätigtem #754-Stand
  `df885603` als `0c1169f7` integriert. Root prüfte den tatsächlichen
  Worker-Code/Diff und die Konfliktauflösung selbst: **PASS**.
  `CoachClarificationService.save_question` übernimmt vollständig
  Userturn-Provenienz, Textgrenzen und dauerhafte KV-Persistenz unter
  demselben `DB_LOCK` und `DatabaseManager`-UOW. Der Server komponiert
  nur den konkreten Service und ruft ihn direkt auf; kein Rückimport,
  Fachcallback oder Kompatibilitätswrapper.
- Drei direkte Testmethoden mit Grenzwert und Negativ-Matrix prüfen
  24 Message-IDs, Unicode-Persistenz, fremde/Assistant-/Bool-IDs,
  aktuellen Userturn, Leer-/Überlängen und unveränderten KV-Zustand bei
  Ablehnung. Zusammen mit dem Dialog-Harness für Rückfrage-Fortsetzung
  ist die Abdeckung dieser kleinen Grenze angemessen. Worker-Vollsuite
  **PASS** (2.450 Tests/12 Skips), Dialog-Harness 71/71,
  Architektur 6/6, Ruff/Compile/Diff-Check **PASS**. Integrierte
  Vollsuite, Inventar und PR-CI stehen noch aus. Nächster Schritt:
  integrierten Stand vollständig prüfen und als eigenen PR
  veröffentlichen; danach atomaren Trainings-Patch sequenziell
  integrieren.
- Erstes integriertes Architektur-Gate: **FAIL**, da die neue reine
  `coach_clarification_service`-Factory im Inventargenerator noch
  nicht als Composition Root erfasst war (P0=1). Root ergänzte die
  konkrete Zuordnung und regenerierte das Inventar. Danach
  Dialog-/Architekturtests 79/79, Inventar-`--check`, Ruff/Compile
  **PASS**; Read-only-Docker-Vollsuite 2.460 Tests/11 Skips **PASS**;
  native Vollsuite 2.460 Tests/12 Skips **PASS** (232,168 s).
  Root prüfte den korrigierten integrierten Code/Diff erneut:
  **PASS**. Keine verbleibende P0-Zuordnung; `server.py` 4.741
  physische Zeilen, 225 Definitionen. PR-CI und Merge stehen aus.

## P7 Rückfrage-Persistenz — bestätigter #755-Merge

- #755 auf Head `6b32e9c3` bestand Root-Gate, native und
  Read-only-Docker-Vollsuite, CI-Testshards, Container, Qualität,
  Sonar und CodeQL. Einmalig angeforderter Codex-Code-/Security-
  Review **PASS**; null offene Review-Threads. Der zum Mergezeitpunkt
  noch laufende optionale Browser-Smoke-/Accessibility-Check wurde
  anschließend **PASS** (5m41s).
- Squash-Merge `255c21e12e0831d4b09c96418c0df743efc36a79` am
  `2026-09-23T23:13:36Z` mit `state=MERGED`, `mergedAt` und
  Erreichbarkeit auf `origin/develop` bestätigt.

## P7 atomarer Trainings-Patch — integrierter Prüfstand

- Root-Ausgangscommit `06431c23` wurde auf den bestätigten #755-
  Merge als `de3915b0` integriert. Root prüfte tatsächlichen Code,
  Diff und Konfliktauflösung: **PASS** für vollständige Verlagerung
  der Schedule-/Revisions-/Constraint-Orchestrierung nach
  `CoachTrainingPatchService`, direkte Delegation aus `server.py`,
  gemeinsame `DatabaseManager`-UOW und `DB_LOCK`, unveränderten
  Planning-Revision/Hash-Vertrag, atomaren Rollback und Event-Ausgabe.
  Keine Backend-Server-Rückimporte oder Fachcallbacks. Der
  bestehende lokale Planungsdienst bleibt Eigentümer seiner Daten.
- Sechs direkte Tests prüfen Erfolg/Revision, stale Revision ohne
  Schreibzugriff, fehlenden Scope, Batch-Limit, Kalenderkonflikt mit
  Rollback sowie Plan-Constraints. Bestehende Regressionen decken
  zusätzlich gescheiterte Creation nach Änderungen und Retry/Replay
  ohne doppelte Effekte ab; Test-Patchziel und direkter Testaufruf
  wurden migriert. Für diese risikoreiche Transaktionsgrenze
  angemessen. Auf dem Root-Ausgangsstand: native Vollsuite 2.463
  Tests/12 Skips **PASS**, frisches Read-only-Docker-Image 2.463
  Tests/11 Skips **PASS**, fokussierte 37 + 7 Tests **PASS**.
  Integrierte Vollsuite, Inventar und PR-CI stehen noch aus.
- Nach Integration: 40 fokussierte Tool-/Transaktions-/Architekturtests
  **PASS**; Inventar-`--check`, Ruff für neue Dateien und Generator,
  Compile und Diff-Check **PASS**. Native Vollsuite 2.466 Tests/
  12 Skips **PASS** (224,129 s), frisch gebautes Read-only-Docker-
  Image 2.466 Tests/11 Skips **PASS** (23,009 s). Root prüfte den
  integrierten Code/Diff nach der Konfliktauflösung erneut: **PASS**.
  `server.py` 4.691 physische Zeilen, 223 Definitionen; P7
  verbleiben 48 Definitionen/28 globale Bindungen, P0=0. PR-CI und
  Merge stehen aus.

## P7 atomarer Trainings-Patch — bestätigter #756-Merge

- #756 auf Head `c1bb12d5` bestand Root-Gate, native und frische
  Read-only-Docker-Vollsuite, CI-Testshards, Container, Qualität,
  Sonar und CodeQL. Einmalig angeforderter Codex-Code-/Security-
  Review **PASS**, null offene Threads. Der zum Mergezeitpunkt noch
  laufende optionale Browser-Smoke-/Accessibility-Check wurde
  anschließend **PASS** (5m46s).
- Squash-Merge `77551f689c2deec9b980f48f40e0ad8223217336` am
  `2026-09-23T23:25:21Z` mit `state=MERGED`, `mergedAt` und
  Erreichbarkeit auf `origin/develop` bestätigt.
- Nächster Schritt: P7-Planungskommando-Claim/Ausführung/Receipt als
  zusammenhängenden Use Case verlagern; ein einzelner GPT-6-Luna-
  Worker übernimmt unabhängig davon nur die stateless
  Tool-Call-Metadaten. Deren Patches werden sequenziell integriert.

## P7 strukturierte Planungskommandos — Root-Ausgangsstand

- Auf bestätigtem #756-Merge `77551f68` hat Root die acht zusammen-
  hängenden Planungsbefehl-Funktionen einschließlich Scope-
  Vorbereitung, Artifact-/Revisionsprüfung, sessiongebundenem
  Claim/Replay, atomarer Tool-Ausführung und finalem Receipt
  vollständig in `CoachPlanningCommandService.execute` verlagert.
  Der HTTP-Handler delegiert direkt; kein Server-Wrapper oder
  Backend-Rückimport. `DatabaseManager` und `DB_LOCK` bleiben
  Transaktionseigentümer; Tool-Dispatcher, Receipt- und
  Fehlerdienste sind konkrete injizierte Backend-Eigentümer.
- Sechs neue direkte Tests prüfen HTTP-Delegation, Replay und
  Session-/Conversation-Isolation ohne doppelte Wirkung,
  einen laufenden Claim ohne Doppeleffekt, unzulässige Kommandos
  ohne Claim, stale Revision vor Claim und
  Rollback mit dauerhaftem Fehler-Receipt. Dies deckt die neuen
  risikoreichen Grenzen gezielt ab, ergänzt durch bestehende
  Coach-Tool-/Dialog-Integrationen; Testanzahl allein ist nicht
  das Abnahmekriterium. Fokussiert 111 Tests **PASS**;
  native Vollsuite 2.472 Tests/12 Skips **PASS** und finales
  frisches Read-only-Docker-Image 2.472 Tests/11 Skips **PASS**;
  Ruff/Compile, Inventar-`--check` und Diff-Check **PASS**.
  Root prüfte das tatsächliche Diff samt Transaktions-, Autorisierungs-
  und Fehlergrenzen: **PASS**; PR-CI und Review stehen noch aus.
  `server.py` 4.579 physische Zeilen nach letzter Leerzeilenkorrektur;
  P7-Rest 40 Definitionen. P7 bleibt offen.

## P7 Planungskommandos — bestätigter #757-Merge

- Geprüfter Root-Dateibaum `9cb02ed8`, nach reinem Conventional-Commit-
  Betreff-Amend auf Head `7c438953` per leerem `git diff` unverändert.
  Root-Gate **PASS**: 111 fokussierte, 2.472 native (12 Skips) und
  2.472 Read-only-Docker-Tests (11 Skips), Ruff/Compile/Inventar.
- PR #757: CI-Testshards, Container, Qualitätsbaseline, Sonar,
  CodeQL, Browser (5m36s), einmalig angeforderte Codex-Code-/Security-
  Review **PASS**, null offene Threads. Der nach dem Commit-Amend
  zunächst fehlgeschlagene Codex-Check wurde durch erneute Auswertung
  des unveränderten Diffs im geschützten Workflow grün, ohne zweite
  Review-Anfrage oder Branch-Schutz-Umgehung.
- Squash-Merge `dfb2f45772ef9fda873206dea111eefe0ca06002` am
  `2026-09-23T23:48:49Z` mit `state=MERGED`, `mergedAt` und
  Erreichbarkeit auf `origin/develop` bestätigt.

## P7 Tool-Call-Metadaten — sequenzielle Worker-Integration

- Ein einzelner explizit als GPT-6-Luna/high gestarteter Worker lieferte
  Commit `65125aca`. Auf dem bestätigten #757-Merge wurde er ohne
  Konflikt als `2500ef5d` integriert. Root prüfte tatsächlichen
  Worker- und Integrationsdiff: exakt die unveränderte reine
  Projektion mit Call-ID-/40-Schritt-/Allowlist-/JSON-Grenzen und
  stabilen Effekt-/Reparatur-/Bindungs-Schlüsseln, direkte
  Server-Delegation ohne Wrapper oder Rückimport. Die sechs neuen
  direkten Tests decken gültige Projektion, 200/201-Zeichen-Grenze,
  Replay trotz Schrittlimit, Tool-Scope und Argumentfehler ab.
- Integriertes Root-Gate **PASS** für den Code: 111 kombinierte
  Coach-/Architekturtests und frisches Read-only-Docker-Image mit
  2.478 Tests/11 Skips **PASS**; Ruff/Compile/Inventar-/Diff-Check
  **PASS**. Native Vollsuite 2.478 Tests/12 Skips ebenfalls
  **PASS**; PR-CI steht noch aus.
  `server.py` 4.540 physische Zeilen, P7-Rest 39 Definitionen/
  28 globale Bindungen, P0=0. P7 bleibt offen;
  nächster fachlicher Schritt ist die zustandsbehaftete strukturierte
  Tool-Ausführungs- und Replay-Orchestrierung.

## P7 Tool-Call-Metadaten — bestätigter #758-Merge

- Der integrierte Worker-Dateibaum `d91ff6f2` bestand das Root-Diff-
  Review **PASS**; 111 kombinierte, 2.478 native/12 Skips und 2.478
  Read-only-Docker-Tests/11 Skips sowie Ruff/Compile/Inventar **PASS**.
  Die einmalig angeforderte Codex-Code-/Security-Review, CI-Testshards,
  Container, Qualität, Sonar, CodeQL und optionaler Browser-/Accessibility-
  Check (5m55s) waren **PASS**, null offene Review-Threads.
- Squash-Merge `9d84c8cb3d3129155e1cfc7c9c2f16b842259a60` am
  `2026-09-23T23:58:27Z` mit `state=MERGED`, `mergedAt` und
  Erreichbarkeit auf `origin/develop` bestätigt.

## P7 strukturiertes Tool-Replay — sequenzielle Worker-Integration

- Ein einzelner explizit als GPT-6-Luna/high gestarteter Worker lieferte
  Commit `1cf811e0`, auf #758 konfliktfrei als `bc80e577` integriert.
  Root prüfte den tatsächlichen Worker- und Integrationsdiff:
  vollständige Verlagerung der Replay-Entscheidung, direkte Server-
  Delegation ohne Wrapper/Rückimport, keine neue Cache-Eigentümerschaft,
  aktuelle Draft-Revision unter injiziertem DB-Lock und Manager-UOW.
  Implementierungsreview **PASS**.
- Acht neue direkte Tests prüfen exaktes Call-ID-Replay/409-Konflikt,
  mutierendes Effekt-Replay, Read-only-Ausnahme, fehlgeschlagene Effekte,
  fehlendes/veraltetes Draft-Artefakt, gültige Draft-Revision und
  bereits gespeichertes Artefakt trotz alter Basisrevision.
  Worker: 14 fokussierte Tests **PASS**, native Vollsuite 2.486/
  12 Skips **PASS**, Ruff/Compile/Diff-Check **PASS**. Nach Integration
  sind 113 kombinierte Coach-/Architekturtests und die frische
  Read-only-Docker-Vollsuite 2.486/11 Skips **PASS**; Inventar-`--check`
  und Diff-Check **PASS**, `server.py` 4.521 physische Zeilen,
  P7-Rest 38 Definitionen/28 globale Bindungen, P0=0. Native
  Integrations-Vollsuite 2.486/12 Skips **PASS** (342,167 s).
  Root prüfte den integrierten Code und alle betroffenen Aufrufer
  erneut: **PASS**. CI-Testshards, Container, Qualität, Sonar, CodeQL und Codex-Code-/Security-Review **PASS**, null offene Threads. P7 bleibt offen.

## P7 strukturiertes Tool-Replay — bestätigter #759-Merge

- Squash-Merge `52acbe45e51ed8599e2145daa690cc3d116f0804` am
  `2026-09-24T00:23:16Z` mit `state=MERGED`, `mergedAt` und
  Erreichbarkeit auf `origin/develop` bestätigt. Optionaler
  Browser-Smoke-/Accessibility-Check anschließend **PASS** (5m37s).
- Nächster Schritt: Ein einzelner GPT-6-Luna-Worker besitzt separat
  nur die strukturierte Replay-Entscheidung; Root bearbeitet im
  unabhängigen Worktree die Turn-Ergebnisprojektion. Beide
  `server.py`-Patches werden sequenziell integriert und erneut geprüft.

## P7 strukturierte Turn-Ergebnisse — Root-Ausgangsstand

- Auf bestätigtem #758-Merge `9d84c8cb` hat Root die komplette
  Ergebnisprojektion einschließlich reparierter Fehler, Effekte,
  Text-/Status-Fallback und Pending-Request-KV-Persistenz in
  `CoachStructuredOutcomeService.finalize` verlagert. Der Turn-Aufrufer
  delegiert direkt; `DatabaseManager`/`DB_LOCK` und
  `KeyValueRepository` sind die injizierten Zustandseigentümer.
  Auch der reine `output_text`-Kompatibilitäts-Wrapper ist entfernt;
  drei Provider-Tests zielen direkt auf die Backend-Funktion.
- Sieben neue direkte Tests prüfen Erfolg/Clearing, partielle Fehler
  mit Provenienz und bestätigten Schritten, Rückfrage ohne KV-Effekt,
  unvollständige Antwort, Read-only-Grenze, reparierte Fehler und
  fehlende Antwort. Direkte Tests plus Architekturtest 13 **PASS**;
  Der erste Read-only-Docker-Gesamtlauf **FAIL** (2.485 Tests,
  1 Importziel-Fehler): Ein bestehender Sprach-Recovery-Test rief
  `server.coach_failure_lines` statt des Backend-Eigentümers auf.
  Root migrierte den Test auf `backend.coach.outcomes.coach_failure_lines`;
  25 betroffene direkte/Architektur-/Recovery-Tests **PASS**. Die
  finale native Vollsuite 2.485/12 Skips und erneute frische
  Read-only-Docker-Vollsuite 2.485/11 Skips **PASS**; kombinierte
  85 Coach-/Architekturtests **PASS**, Ruff/Compile/Inventar **PASS**.
  Root prüfte den korrigierten Stand erneut: **PASS** für den
  isolierten Ausgangsstand. `server.py` 4.460 physische Zeilen,
  P7-Rest 33 Definitionen/28 globale Bindungen, P0=0. Die
  sequenzielle Integration nach dem Tool-Replay-Merge und deren
  erneute Tests/Review stehen noch aus.

## P7 strukturierte Turn-Ergebnisse — integrierter Diff-Stand

- Ausgangscommit `183544c0` wurde auf bestätigtem #759-Merge
  `52acbe45` sequenziell integriert. Die Konflikte betrafen
  benachbarte, aber unabhängige Server-Funktionen sowie gemeinsam
  generierte Inventar-/Plan-/Review-Dateien; Root behielt beide
  konkreten Services und die beiden Architekturverbote, entfernte
  beide alten Fachfunktionen und generierte das Inventar neu.
- Code-/Integrationsreview vorläufig **PASS**: direkte Aufrufer für
  Tool-Replay und Ergebnisfinalisierung, kein Server-Callback oder
  Backend-Rückimport, KV-Transaktion und Replay-Revision bleiben bei
  ihren Besitzern. `server.py` 4.441 physische Zeilen; P7-Rest 32
  Definitionen/28 globale Bindungen, P0=0. Nach der Konfliktauflösung
  132 kombinierte Coach-/Architekturtests, native Vollsuite 2.493/
  12 Skips (239,210 s) und frisches Read-only-Docker-Image 2.493/
  11 Skips (23,106 s) **PASS**; Ruff/Compile/Inventar/Diff-Check
  **PASS**. Root prüfte den tatsächlichen integrierten Diff und die
  beiden Aufrufer erneut: **PASS**. PR-CI steht noch aus.

## P7 strukturierte Werkzeugvorbereitung — integrierter Diff-Stand

- #760 ist am 24.09.2026 um 00:35:59 UTC mit Merge-Commit
  `efbd51c305e1cfe57abe386889b26f1bfe6e8e1e` gemergt; der Commit
  ist auf `origin/develop` erreichbar, alle Checks einschließlich Codex-
  Review und Browser sind grün, und die PR hat null Review-Threads.
- GPT-6-Luna-Worker-Commit `3d794cd87501a8d4c09ee940395a47924d72fc02`
  wurde auf diesem bestätigten Stand sequenziell als `fe512aa6` integriert.
  Ein `server.py`-Konflikt mit #760 betraf benachbarte Funktionen; Root
  behielt die Outcome-Factory, ergänzte die Preparation-Factory und
  entfernte ausschließlich die beiden alten Preparation-Funktionen.
- Root-Diff-Review: zunächst **FAIL** für den integrierten Stand
  `fe512aa6`: Die native Vollsuite hatte 2.506 Tests/12 Skips und
  genau einen Fehler im P0-Architekturvertrag, weil die neue Factory
  im Inventargenerator nicht als Composition Root eingetragen war.
  Root ergänzte diese Zuordnung, entfernte zudem einen nach der
  Verlagerung ungenutzten Server-Import und generierte das Inventar
  erneut; 34 fokussierte Tests sowie `--check` sind danach **PASS**.
  Die korrigierte Read-only-Docker-Vollsuite ist mit 2.506 Tests/
  11 Skips **PASS**; die native Vollsuite mit 2.506 Tests/12 Skips
  ebenfalls **PASS**. Ruff für die neuen/geänderten Nicht-Serverdateien,
  Compileall, Inventar-Check und Diff-Check sind **PASS**; `server.py`
  behält nur die 23 Ruff-Baseline-Befunde. Der erneut geprüfte
  integrierte Stand erhält **PASS**. PR-CI war anschließend grün.
- Code-Review des korrigierten Diffs: fachlich **PASS** für die Verlagerung einschließlich
  Pause/Cancel, Dialogautorisierung, Remote-Write-Abhängigkeit, Sync-Scopes
  und Planungskonflikt. Das Backend importiert `server.py` nicht und erhält
  keinen Server-Callback. Der integrierte Stand hat 4.390 physische
  `server.py`-Zeilen, P7-Rest 30 Definitionen/28 globale Bindungen,
  P0=0. 34 fokussierte Tests **PASS**. Der Worker prüfte zuvor
  19 fokussierte und 2.499 native Tests/12 Skips erfolgreich.
- Testangemessenheit: Die 13 direkten Preparation-Verträge decken die
  sechs sicherheitsrelevanten Zweige samt positiven und negativen Sync-
  Varianten ab; Architekturtests verhindern die Rückverlagerung. Die
  integrierten Tool-/Turn-/Replay-Regressionen und die Docker-Vollsuite
  sind zusätzlich erforderlich, bevor dieser Stand veröffentlicht wird.

## P7 nächster Integrationsstand — Werkzeugausführung

- #761 ist am 24.09.2026 um 00:55:18 UTC mit Merge-Commit
  `c591d38718577c9034d44ce31494a9d8a528f22d` gemergt. Der Commit
  ist auf `origin/develop` erreichbar; alle Checks einschließlich
  Browser und Codex sind grün, die PR hat null Review-Threads.
- Nächster Schritt: Den eng begrenzten GPT-6-Luna-Worker-Patch für
  `CoachStructuredToolExecutionService` aus dem separaten Worktree
  sequenziell auf `c591d387` integrieren; dabei innere und äußere
  Transaktionsgrenze, Rollback, Session-gebundene Duplikatvorschläge
  und migrierten Backend-Test-Patch selbst am Diff prüfen. Danach
  fokussierte, native und Read-only-Docker-Regressionen sowie das
  Inventar ausführen. Bis dahin ist dieser Teil ausdrücklich **offen**.

## P7 strukturierte Spezialwerkzeug-Ausführung — integrierter Diff-Stand

- GPT-6-Luna-Worker-Commit `bec16e299f983bd8e524f984382b9d4ef4cd528a`
  wurde auf bestätigtem #761-Merge `c591d387` konfliktfrei als
  `d27ddf93` integriert. Der Worker änderte ausschließlich das neue
  `CoachStructuredToolExecutionService`-Modul, `server.py`, direkte
  Tests, Architekturtest und den migrierten Tool-Coverage-Patch.
- Root-Diff-Review des integrierten Codes: **PASS**. Die
  innere bedingte DB-UOW/Lock-Grenze liegt im konkreten Service,
  während der äußere Turn-UOW weiterhin Ausführung, Receipt-Anhang
  und JobStore-Merge atomar hält. Cancel schreibt `null` über den
  gemeinsamen KV-Eigentümer; Duplikatvorschläge benötigen weiterhin
  die Session-CSRF-Bindung. Kein Backend-Rückimport, Server-Callback
  oder permanenter Kompatibilitäts-Wrapper. Der Testpatch für den
  Trainings-Patch zielt nun auf `CoachTrainingPatchService.apply`.
- 39 kombinierte direkte/Tool-Coverage/Architekturtests **PASS**;
  der Worker meldete 12 direkte/Architektur-, 27 Tool-Coverage- und
  2.512 native Tests/12 Skips **PASS**. Root ergänzte die neue Factory
  im Inventargenerator und erzeugte das Inventar neu: `server.py`
  4.356 physische Zeilen, P7-Rest 29 Definitionen/28 globale
  Bindungen, P0=0. Ruff der betroffenen Nicht-Serverdateien **PASS**;
  die 23 bestehenden Server-Ruff-Befunde sind unverändert. Die native
  Vollsuite mit 2.512 Tests/12 Skips und das frische Read-only-Docker-
  Image mit 2.512 Tests/11 Skips sind **PASS**; Compileall,
  Inventar-Check und Diff-Check sind **PASS**. PR-CI steht noch aus.
- Testangemessenheit: Die direkten Tests verwenden temporäre SQLite-
  Daten und gemockte Fach-Services. Sie prüfen nicht nur Rückgaben,
  sondern Lock-Reihenfolge, innere UOW, Rollback, CSRF-Grenze und beide
  transaktionsfreien Remote-Zweige; die bestehende Dialogfolge prüft
  zusätzlich Replay ohne zweite Patch-Mutation.

## P7 strukturierte Werkzeugfehler — integrierter Diff-Stand

- #762 ist am 24.09.2026 um 01:14:08 UTC mit Merge-Commit
  `75c2222f82aba335c6fbac6cde6434c91368438c` gemergt; Commit
  auf `origin/develop` erreichbar, alle Checks einschließlich Codex
  und Browser grün, null Review-Threads.
- GPT-6-Luna-Worker-Commit `fa91fc2fc3e46e11edb29c5455ae7571505415d3`
  wurde auf diesem Stand konfliktfrei als `8de7dce5` integriert.
  Root prüfte tatsächliches Modul, Callsite, Architekturverbot und
  direkte Tests erneut: **PASS**. Fehlerergebnis, sichere Diagnose,
  kompletter Receipt-Eintrag und Log-Reihenfolge sind im konkreten
  `CoachStructuredToolFailureService`; keine Server-Callbacks oder
  Backend-Rückimporte. Unbekannte Toolnamen werden im Log zu `unknown`,
  Nicht-AppError-Texte bleiben generisch und `validation_reason` wird
  nur mit begrenzter `request_`-Form übernommen.
- 84 direkte/Architektur/Dialogtests **PASS**; Worker meldete 12
  direkte/Architektur-, 72 Dialog- und 2.518 native Tests/12 Skips
  **PASS**. Inventargenerator um Composition-Factory ergänzt;
  `server.py` 4.337 physische Zeilen, P7-Rest 28 Definitionen/
  28 globale Bindungen, P0=0. Ruff der betroffenen Nicht-Serverdateien
  **PASS**, bestehende 23 Server-Ruff-Befunde unverändert. Integrierte
  native Vollsuite 2.518 Tests/12 Skips und frisches Read-only-Docker-
  Image 2.518 Tests/11 Skips **PASS**; Compileall, Inventar- und
  Diff-Check **PASS**. PR-CI steht noch aus.
- Testangemessenheit: Die sechs direkten Fälle prüfen AppError- und
  Nicht-AppError-Texte, beide Reason-Fallbacks, begrenzte Validation-
  Daten, unbekannte Toolnamen sowie Append-vor-Log. Die bestehende
  Dialogsuite prüft zusätzlich Recovery, Receipt und Reparaturfolgen.

## P8 strukturiertes Tool-Round-Journal — integrierter Diff-Stand

- #763 ist am 24.09.2026 um 01:23:56 UTC mit Merge-Commit
  `3c2bf7a175233febee114911202dd851c2b21c48` gemergt; Commit
  auf `origin/develop` erreichbar, alle erforderlichen Checks und
  Codex-Reviews grün, null Review-Threads.
- GPT-6-Luna-Worker-Commit `d9e4aad4bff6360c12159994a368e00be3a6bec7`
  wurde auf diesem Stand konfliktfrei als `e3c85acc` integriert.
  Root prüfte Modul und tatsächlichen Server-Diff erneut: **PASS**
  für die vollständige Verlagerung der durable Round-Journalübergänge.
  `CoachJobStore` ist alleiniger persistenter Zustandseigentümer;
  Tool-Loop, Cancellation und Provider-Follow-up bleiben ausdrücklich
  bis zum zusammenhängenden P8-Turn-Use-Case offen. Kein Backend-Import
  oder Callback zu `server.py` und kein Kompatibilitäts-Wrapper.
- Direkte Journal-Tests prüfen Filterung, fehlende IDs/Namen,
  zweistufige Pending-/Output-Phase, Unicode-JSON, Clarify/Cancel nur
  bei Erfolg und Finish/Clear-Reihenfolge. Worker meldete 11 direkte/
  Architektur-, 81 Dialog/JobStore- und 2.523 native Tests/12 Skips
  **PASS**. Die integrierte Suite hat 92 fokussierte und 2.523 native
  Tests/12 Skips **PASS**; frisches Read-only-Docker-Image 2.523 Tests/
  11 Skips **PASS**. Ruff der betroffenen Nicht-Serverdateien,
  Compileall, Inventar- und Diff-Check **PASS**; die 23 bestehenden
  Server-Ruff-Befunde sind unverändert. `server.py` hat 4.324
  physische Zeilen, P7-Rest 26 Definitionen/28 globale Bindungen,
  P8-Rest 13 Definitionen/8 Bindungen, P0=0. PR-CI steht noch aus.

## P8 begrenzte Response-Retry-Policy — integrierter Diff-Stand

- #764 ist am 24.09.2026 um 01:34:00 UTC mit Merge-Commit
  `b041142b09fe875aec5c1a8ef109d0d59beae1a1` gemergt; Commit auf
  `origin/develop` erreichbar, null Review-Threads und alle Checks,
  einschließlich des nach dem Merge abgeschlossenen Browser-Checks, grün.
- GPT-6-Luna-Worker-Commit `bb7ac8a4e51c5155ec717b1443e639b0ad3450ae`
  wurde auf diesem Stand konfliktfrei als `42de0414` integriert. Root-Diff-
  Review: zunächst **FAIL**, weil `server.py` nach der Verlagerung einen
  ungenutzten `secrets`-Import behielt (Ruff 24 statt 23 bestehende Befunde).
  Der Import wurde im integrierten Worktree entfernt; erneutes Code-/Diff-
  Review: **PASS**. `CoachResponseRetryPolicy` besitzt Rate-Limit-Entscheidung,
  begrenztes Retry-After/Jitter und abbrechbares Warten; Provider- und Turn-
  Loop bleiben offen. Kein Backend-Rückimport, Callback oder Wrapper.
- Die sechs direkten Tests decken Provider/Reason-Grenze, Retry-Erschöpfung,
  Streaming-Deltas, Retry-After-Budget, Jitter und Cancellation-Wait ab.
  Bestehende Language-Recovery-Tests patchen nun das Backend-Ziel. 24
  fokussierte Tests, Architektur-, Compileall-, Ruff-Nicht-Server- und
  Inventarprüfungen **PASS**. Integrierte native Vollsuite 2.529 Tests/
  12 Skips, frisches Read-only-Docker-Image 2.529 Tests/11 Skips **PASS**;
  bestehende 23 Server-Ruff-Befunde unverändert, Diff-Check **PASS**.
  `server.py`: 4.302 physische Zeilen; P7-Rest 25 Definitionen,
  P8-Rest 13, P0=0. PR-CI steht noch aus.

## P8 Remote-Konversations-Recovery — integrierter Diff-Stand

- #765 ist am 24.09.2026 um 01:46:56 UTC mit Merge-Commit
  `b9852960f7ad4828b48ffefeda7e96962e6d69de` gemergt; auf
  `origin/develop` erreichbar, null Review-Threads und alle Checks,
  einschließlich Browser, grün. Die Recovery-Änderung wurde zunächst in einem separaten
  Worktree auf dem geprüften #765-Quellstand vorbereitet.
- Root-Code-/Diff-Review: **PASS** für die vollständige Verlagerung der
  einmaligen `conversation_state_invalid`-Recovery in
  `CoachConversationRecoveryService`. Der Service besitzt Entscheidung,
  lokale Dialog-/Attachment-Evidenz, KV-Reset mit DB-Lock, JobStore-
  Checkpoint und redigiertes Ereignis. Kein Rückimport, Server-Callback
  oder dauerhafter Wrapper. Der Provider-/Turn-Loop bleibt offen.
- Vier direkte Tests prüfen durable Checkpoints, nur bedingten KV-Reset,
  einmalige OpenAI-Grenze vor Textdelta und Retry-Budget sowie unveränderte
  Attachment-Evidenz. 101 kombinierte direkte/Architektur/Dialog-/Attachment-
  Tests, Ruff, Compileall, Inventar-Check und Diff-Check **PASS**. Frisches
  Read-only-Docker-Image: 2.533 Tests/11 Skips **PASS**. Die native
  Vollsuite mit 2.533 Tests/12 Skips ist ebenfalls **PASS**. Quellcommit
  `8b6aca37` wurde auf dem bestätigten #765-Merge konfliktfrei als
  `a4ca1c70` integriert; 101 betroffene Tests sowie Ruff, Compileall,
  Inventar- und Diff-Check sind auf diesem Stand erneut **PASS**.
  `server.py` 4.259
  physische Zeilen; P7-Rest 23 Definitionen, P0=0.

## P7 Chat-Serialisierung — integrierter Diff-Stand

- #766 ist am 24.09.2026 um 01:56:48 UTC mit Merge-Commit
  `5d6999890196f2f0a926975652bc71af1c982c7a` gemergt; Commit
  auf `origin/develop` erreichbar, alle Checks einschließlich Browser
  grün, null Review-Threads.
- GPT-6-Luna-Worker-Commit `a24994f4923242e9be20df4184b3a7ace5307edc`
  wurde auf diesem Stand mit ausschließlich additiver Architekturtest-
  Konfliktauflösung als `e5ad0f70` integriert. Root prüfte Code und Diff:
  **PASS**. `CoachConversationGate` besitzt die eine prozessweite Queue und
  RLock; Reset und Chat-Turn teilen genau dieselbe Lock-Instanz. 429 bei
  voller Queue, 409 beim Lock-Timeout, Wartelimit 30 Sekunden, Queuegröße
  3 und Freigabe im Fehlerpfad sind erhalten. Keine Rückimporte, Server-
  Callbacks oder Kompatibilitäts-Wrapper.
- Fünf direkte Gate-Tests prüfen Limit, Timeout, Exception-Freigabe und
  Reset-Lock-Kohärenz. Worker: 11 direkte/Architektur-, ein migrierter
  Server-Queue-Test und native Vollsuite 2.528/12 **PASS**; Root zusätzlich
  12 fokussierte und Read-only-Docker 2.528/11 am Quellstand **PASS**.
  Integriert: 96 betroffene Tests, Ruff, Compileall, Inventar- und
  Diff-Check **PASS**. Frisches Read-only-Docker-Image: 2.538 Tests/
  11 Skips und native Vollsuite 2.538 Tests/12 Skips **PASS**;
  bestehende 23 Server-Ruff-Befunde unverändert. PR-CI steht noch aus.
  `server.py`: 4.240 physische Zeilen;
  P7-Rest 22 Definitionen/24 globale Bindungen, P0=0.

## P8 Turn-Eröffnung und finales Receipt — integrierter Diff-Stand

- #767 ist am 24.09.2026 um 02:11:40 UTC mit Merge-Commit
  `da0216ce5695f78ddf594b8a34625c8d10720b4c` gemergt;
  Commit auf `origin/develop` erreichbar, alle Checks einschließlich
  Browser grün und null Review-Threads.
- GPT-6-Luna-Worker-Commit `7b0c09d984d6e065f8faec795b98ed28dfa1d0b0`
  wurde auf diesem Stand mit ausschließlich additiver Architekturtest-
  Konfliktauflösung als `c5c74eab` integriert. Root prüfte Code und Diff:
  **PASS** für atomare User-Nachricht/Command-Erstellung, Session-Owner-
  Prüfung, idempotente bestehende Receipts und Rollback. Vier direkte
  Tests verwenden temporäres SQLite und prüfen gerade die 403-Grenze
  ohne Mutation sowie den Trigger-induzierten Insertfehler mit Rollback.
  Worker: 10 direkte/Architektur-, 81 Dialog/JobStore- und 2.533 native
  Tests/12 Skips **PASS**; Root: 91 betroffene und Read-only-Docker
  2.533 Tests/11 Skips am Quellstand **PASS**.
- Root hat auf dem geprüften #766-Quellstand den konkreten
  `CoachFinalReceiptService` implementiert und am tatsächlichen Code/Diff
  geprüft: **PASS** für finale Projektion, atomare Assistant-Nachricht,
  Preview-Publikationsbindung, Provider-Marker, bereinigtes Receipt und
  Event erst nach Commit. Der alte Server-Code und die verwaiste SQL-
  Konstante sind entfernt; kein Rückimport, Server-Callback oder Wrapper.
- Fünf direkte Fälle decken Status-/Checkpoint-Projektion,
  Idempotenz, Preview-/Event-Reihenfolge und Fehler ab. Ein Test verwendet
  eine temporäre echte SQLite-UOW und beweist, dass ein KV-Fehler die bereits
  eingefügte Assistant-Nachricht zurückrollt und kein Event veröffentlicht.
  Betroffene Dialog-/Fehler-/Architekturtests, Ruff, Compileall, Inventar-
  und Diff-Check **PASS**. Native Vollsuite vor dem zusätzlichen SQLite-
  Test: 2.537 Tests/12 Skips **PASS**; danach direkter SQLite-Test **PASS**
  und Read-only-Docker-Vollsuite 2.538 Tests/11 Skips **PASS**. Quellcommit
  `ea42932c` wurde mit additiver Inventarzuordnung und zusammengeführtem
  Reviewlog nach Turn-Eröffnung als `203472d5` integriert. Beiderseits keine Backend-
  Rückimporte, Server-Callbacks oder dauerhaften Wrapper.
- Der kombinierte integrierte Stand hat `server.py` mit 4.186 physischen
  Zeilen, P7-Rest 19 Definitionen/24 globale Bindungen und P0=0.
  99 betroffene Tests, Ruff der Nicht-Serverdateien, Compileall,
  Inventar- und Diff-Check **PASS**. Frisches Read-only-Docker-Image:
  2.547 Tests/11 Skips und native Vollsuite 2.547 Tests/12 Skips
  **PASS**. Die 23 bestehenden Server-Ruff-Befunde sind unverändert.
  Root-Review des integrierten Stands: **PASS**; PR-CI steht noch aus.

## P7 Coach-Kontextbudgets — integrierter Diff-Stand

- #768 wurde am 24.09.2026 um 02:27:40 UTC mit Merge-Commit
  `6ef739b3f2f87842f8e0176de68e916235cd65a2` gemergt;
  der Commit ist auf `origin/develop` erreichbar und Review-Threads: 0.
  Der optionale Browser-Check war beim Merge noch offen und ist
  inzwischen ebenfalls **PASS**.
- GPT-6-Luna-Quellcommit `3efe9922b544593811cba16e2bbcd49edaef14d0`
  wurde konfliktfrei als `019fddab` auf diesen Stand integriert.
  Root prüfte den tatsächlichen Code/Diff: **PASS**. Die sieben
  Kontextbudgets besitzen mit `backend/coach/context.py` genau einen
  Eigentümer; beide Composition-Root-Factories lesen dieselben Werte.
  Keine geänderten Limits, Rückimporte, Server-Callbacks oder Wrapper.
- Zwei neue Grenz-/Factory-Tests und sechs Architekturtests: **PASS**.
  Frisches Read-only-Docker-Image: 2.549 Tests/11 Skips **PASS**;
  Ruff der geänderten Nicht-Server-Dateien, Compileall, Inventar- und
  Diff-Check **PASS**. `server.py`: 4.168 physische Zeilen; P0=0.
  Veröffentlichung und PR-CI stehen noch aus.

## P8 Coach-Response-Transport — integrierter Diff-Stand

- #769 wurde am 24.09.2026 um 02:35:50 UTC mit Merge-Commit
  `fbbf0ef5a760fa7f28cfcdbb6c11f2daf419c6b8` gemergt;
  Commit auf `origin/develop` erreichbar, null Review-Threads.
  Der optionale Browser-Check war beim Merge noch offen und ist
  inzwischen ebenfalls **PASS**.
- Root-Produktpatch und GPT-6-Luna-Testmigration wurden als Quellcommit
  `9eaa2757` geprüft: **PASS**. Eine zusätzliche volle Suite fand einen
  alten Patch auf `server.responses_background_request`; derselbe Worker
  korrigierte ausschließlich dieses freigegebene Testziel. Root prüfte
  danach erneut Code und vollständigen Test-Diff. `CoachResponseTransport`
  besitzt Providerwahl sowie OpenAI-/Gemini-Request-, Background- und
  Stream-Dispatch. Nur der gewählte Adapter wird konstruiert; die
  Gemini-Cancel-Grenze wird vor und nach dem Aufruf geprüft. Kein
  Rückimport, Server-Callback oder dauerhafter Kompatibilitäts-Wrapper.
- Quellstand: 15 direkte/Architektur-/Review-Tests, 600 betroffene
  Integrationstests/4 Skips, native Vollsuite 2.555 Tests/12 Skips
  und frisches Read-only-Docker-Image 2.555 Tests/11 Skips **PASS**.
  Ruff des neuen Moduls, direkten Tests und Architekturtests, Compileall,
  Diff-Check **PASS**; 194 bestehende Legacy-Test-Ruff-Befunde blieben
  außerhalb des Umfangs.
- Quellcommit wurde auf dem #769-Merge als `6ea7dec3` integriert;
  einzig kollidierende Importzeilen im Test wurden additiv zusammengeführt.
  Root-Review des integrierten Codes/Diffs: **PASS**. 15 fokussierte
  Tests, Ruff, Compileall, Inventar- und Diff-Check **PASS**;
  frisches Read-only-Docker-Image: 2.557 Tests/11 Skips **PASS**.
  `server.py`: 4.119 physische Zeilen, P0=0. Veröffentlichung und
  PR-CI stehen noch aus; die Gesamt-Response-/Tool-Schleife bleibt P8-offen.

### #770 Browser-Fixture-Korrektur — erneutes Review-Gate

- PR-Stand `c200da12`: **FAIL**. Codex-Review meldete P1 im offenen
  Thread `PRRT_kwDOUHv92c6laUxA`: `e2e/fixture_runtime.py` patchte noch
  drei entfernte `server.responses_*`-Symbole. Browser-CI reproduzierte
  den Fehler im natürlichen Rückfrage-/Reload-/Follow-up-Fall; die
  synthetische Antwort wurde umgangen und der Provider bewusst blockiert.
- Derselbe GPT-6-Luna-Worker änderte ausschließlich die freigegebene
  Fixture-Datei: ein providerfreier Adapter an der aktiven
  `server.coach_response_transport`-Lookup-Stelle delegiert alle drei
  Methoden weiter an dieselbe synthetische Antwortfunktion. Root ergänzte
  einen Architekturtest, der alte Fixture-Patchziele verbietet und das
  aktive Transport-Patchziel fordert. Root prüfte beide tatsächlichen
  Diffs/Code erneut: **PASS**; keine Aufweichung der Browsererwartung.
- Worker: alter Patch-Ziel-Scan, Compileall, Diff-Check und lokaler
  `mobile-small`-Playwright-Einzelfall (1/1) **PASS**. Root:
  Architekturtests 7/7, statische Prüfungen und frisches Read-only-
  Docker-Image mit 2.558 Tests/11 Skips **PASS**. Keine echten Provider-
  oder Athletendaten. Aktualisierter PR-Check und Review-Thread-
  Auflösung stehen noch aus.
- Nach `9f46a301` meldete SonarCloud sechs neue `python:S1172`-Befunde
  für ungenutzte Fixture-Transportargumente: erneutes Gate **FAIL**.
  Derselbe Worker leitete die sechs Argumente an die unveränderte
  synthetische Antwortfunktion weiter; kein Provideraufruf, keine
  Delta-Emission und keine Regel-/Testabschwächung. Root prüfte den
  konkreten Diff erneut: **PASS**. Ruff, Compileall, Diff-Check und
  lokaler `mobile-small`-Rückfragefall (1/1) **PASS**. Finale PR-CI
  auf dem erneut aktualisierten Stand bleibt abzuwarten.

## P8 Strukturierter Provider-Response-Use-Case — integrierter Diff-Stand

- #770 wurde am 24.09.2026 um 03:03:13 UTC mit Merge-Commit
  `a84b693a337407f1f384dd713954b9ac68c6e4e0` gemergt;
  der Commit ist auf `origin/develop` erreichbar. Alle Checks
  einschließlich vollständiger Browser-Matrix und SonarCloud **PASS**;
  finaler Codex-Code-Review für `4309574` ohne neue Befunde und
  der ursprüngliche P1-Thread gelöst (0 offen).
- Root-Quellcommit `cbfd49ec` verlagerte den gesamten einzelnen
  strukturierten Response-Versuch mit Background-Checkpoint,
  OpenAI-Resume, einmaliger Recovery, begrenztem Retry sowie Delta-
  und Cancel-Grenze nach `CoachStructuredResponseService`. Die
  Provider- und Durable-Dienste sind konkret injiziert; kein
  Rückimport, Server-Callback mit Fachlogik oder Kompatibilitäts-
  Wrapper. Die übergreifende Tool-Rundenschleife bleibt P8-offen.
- Acht direkte Tests prüfen normalen Request, Checkpoint, Resume,
  Retry, Stream-Delta, Recovery und Cancel vor bzw. während Warten.
  Quellstand: 101 betroffene, 14 direkte/Architektur-, native
  Vollsuite 2.565 Tests/12 Skips sowie frisches Read-only-Docker-
  Image 2.565 Tests/11 Skips **PASS**. Root-Code-/Diff-Review:
  **PASS**.
- Der Quellcommit wurde konfliktfrei als `d1363233` auf dem #770-
  Merge integriert. 33 fokussierte Tests, Ruff der neuen und
  Architekturdateien, Compileall, Inventar- und Diff-Check **PASS**;
  frisches Read-only-Docker-Image: 2.566 Tests/11 Skips **PASS**.
  Root-Review des integrierten Stands: **PASS**. `server.py`:
  3.959 physische Zeilen, P0=0. Veröffentlichung/PR-CI offen.
- PR #771 auf Head `f1c3e906`: **FAIL** im SonarCloud-Code-Analysis-Gate
  wegen genau eines `python:S3776`-Befunds in `respond()` (16 statt
  erlaubter 15); übrige abgeschlossene Unit-/Container-/CodeQL-Checks
  waren grün. Root verschob die Delta-Markierung und -Weiterleitung in
  den zuständigen `_ResponseState`, ohne Streaming- oder Retry-Semantik
  zu ändern. Tatsächlicher Korrektur-Diff/Code erneut geprüft: **PASS**.
  Direkte/Architekturtests 15/15, frisches Read-only-Docker-Image
  2.566 Tests/11 Skips, Compileall, Inventar- und Diff-Check **PASS**.
  Erneute externe Sonar-/Browser-/Codex-Prüfung des korrigierten Heads
  steht vor Merge aus.

## P8 Chat-Statusprojektion — sequenziell integrierter Stand

- PR #771 wurde am 24.09.2026 um 03:16:42 UTC als Squash-Commit
  `d912ca1059fd80d531af85d5d8f050d2d803cb61` gemergt;
  `origin/develop` enthält ihn. SonarCloud, CodeQL, alle Test-/Container-,
  Browser- und Codex-Checks **PASS**, null offene Review-Threads.
- GPT-6-Luna-Commit `514ca611f6896481f846c4d88e7068f67df792f4`
  wurde auf diesem Merge konfliktfrei als `be267d97` integriert. Root
  prüfte den tatsächlichen Quell- und Integrationsdiff samt
  `CoachJobSubmissionService.active()`-Sessiongrenze: **PASS**. Der
  Service besitzt Attached-Priorität und Background-/Idle-Projektion;
  `server.py` enthält keinen `chat_stream_status`-Wrapper mehr.
- Fünf direkte Statusfälle prüfen Priorität, exakte Antwortformen und
  fremde Sessions. Zwei migrierte Server-Aufrufer und ein Architekturtest
  sichern die neue Lookup-Stelle. Integriert: 14 fokussierte Tests,
  Ruff, Compileall, Inventar-/Diff-Check und frisches Read-only-Docker-
  Image mit 2.571 Tests/11 Skips **PASS**. Keine echten Provider- oder
  Athletendaten. `server.py`: 3.941 physische Zeilen, P0=0.
  PR-CI und externe Reviews für diesen Stand stehen noch aus;
  Gesamt-Turn-/Worker-Orchestrierung bleibt P8-offen.

## P8 Strukturierte Tool-Rundenschleife — Quellstand

- #772 wurde am 24.09.2026 um 03:22:33 UTC mit Squash-Commit
  `0a733724ae8aa1c097607be124cd36ffeefb3bf8` gemergt;
  der Commit ist auf `origin/develop` erreichbar. Alle Checks
  einschließlich Browser und Codex **PASS**, null offene Threads.
- Root verlagerte `StructuredCoachRoundState`, Tool-Call-Ausführung,
  Replay-/Transaktions-/Receipt-Reihenfolge, Round-Journal und
  Provider-Follow-up vollständig nach `CoachStructuredToolRoundService`.
  `server.py` komponiert konkrete Dienste und ruft `.run()` auf;
  kein Backend-Rückimport oder Server-Callback mit Tool-Fachlogik.
  `DatabaseManager.unit_of_work()` und derselbe DB-Lock erhalten die
  bisherige lokale Transaktion; `CoachJobStore` bleibt Receipt-Eigentümer.
- Fünf neue direkte Tests prüfen Transaktion/Receipt, Replay ohne zweite
  Ausführung, Rollback vor Fehlerprojektion, Round-Limit/Follow-up und
  Cancellation vor Tool-Ausführung. 92 Dialog-/Journal-/Response-/
  Architekturtests, Ruff, Compileall und Diff-Check **PASS**.
  Erster Read-only-Docker-Lauf: **FAIL** nur wegen der neu zuzuordnenden
  Composition-Root-Factory im P0-Inventar. Nach expliziter P8-Zuordnung
  und Neugenerierung: 2.576 Tests/11 Skips, Inventar-Check **PASS**.
  `server.py`: 3.826 physische Zeilen, P0=0. Externe PR-Gates offen;
  finaler Turn und Background-Worker bleiben P8-offen.
- Quellcommit `d08bf729` wurde auf dem bestätigten #772-Merge
  konfliktfrei als `42c98d07` integriert. Root prüfte den tatsächlichen
  Integrationsdiff samt Aufrufern und Transaktions-/Rollback-Grenze
  erneut: **PASS**. 97 fokussierte Tests, Ruff, Compileall,
  Inventar-/Diff-Check und frisches Read-only-Docker-Image mit
  2.576 Tests/11 Skips **PASS**. PR-CI/Sonar/Codex stehen aus.
- PR #773 auf Head `20123e64`: SonarCloud-Code-Analysis **FAIL** wegen
  genau eines `python:S107`-Befunds (14 statt erlaubter 13 Parameter im
  `CoachStructuredToolRoundService`-Konstruktor). Root bündelte die
  vier unveränderten Grenzwerte in `CoachStructuredToolRoundLimits`;
  kein Budget oder Rundencap wurde verändert. Der tatsächliche
  Korrektur-Diff/Code, die 84 gezielten Tests, Ruff, Compileall,
  Inventar-/Diff-Check und ein frisch gebautes Read-only-Docker-Image
  mit 2.576 Tests/11 Skips: **PASS**. Erneute externe Sonar-/Codex-/
  Browser-Prüfung des neuen Heads vor Merge ausstehend.

## P8 Vollständiger strukturierter Coach-Turn — Quellstand

- PR #773 wurde am 24.09.2026 um 03:40:02 UTC mit Squash-Commit
  `d85f9d1195b90a6a626183d4f82150325045f51c` gemergt;
  der Commit ist auf `origin/develop` erreichbar, null offene Threads.
  SonarCloud, CodeQL, Browser, Codex und übrige Pflichtchecks **PASS**.
- Root verlagerte Eröffnung, Attachment-/Dialogkontext, Restart-
  Checkpoint-Replay, Provider-Response, Tool-Runden, Outcome,
  finalen Receipt-Commit und sichere Fehlerbehandlung in
  `CoachStructuredTurnService`. `server.py` komponiert die konkreten
  Zustandseigentümer und ruft `.run()` auf; keine Rückimporte oder
  fachlichen Server-Callbacks. `chat_with_coach`-Vorprüfung und
  Background-Worker-Lifecycle bleiben P8-offen.
- Direkte Tests prüfen Read-only-Toolfilter, privaten Session-Key,
  OpenAI-Checkpoint, Pending-Outputs nach Restart, sicheres
  Fehler-Receipt und Scope-Denial. Der erste Read-only-Docker-Lauf:
  **FAIL** wegen eines alten Testaufrufs auf den entfernten Server-
  Helper und fehlender Diagnose-Frames bei getrennten `/review`-
  Server- und `/app`-Backend-Quellpfaden. Root migrierte den Test auf
  den Backend-Service und begrenzte `coach_error_metadata` auf die
  installierten Backend-Dateien oder die explizite `server.py`;
  fremde Pfade/Inhalte bleiben ausgeschlossen. Ein zusätzlicher
  direkter Split-Root-/Privacy-Test sichert diese Grenze.
- Nach Korrektur: 84 fokussierte Tests und frisches Read-only-Docker-
  Image mit 2.582 Tests/11 Skips **PASS**; Ruff neuer/geänderter
  Backenddateien und neuer Tests, Compileall, Inventar-/Diff-Check
  **PASS**. `server.py`: 3.699 physische Zeilen, P0=0.
  Root prüfte den tatsächlichen Code-/Diff-Stand einschließlich
  Transaktionseigentümer, Restart-Replay, Session-/Scope-Grenze,
  Diagnosedaten und aller Aufrufer: **PASS**. PR-CI folgt.
- Quellcommit `aeeabaa9` wurde auf dem #773-Merge konfliktfrei als
  `f2075f4f` integriert. Root prüfte den tatsächlichen Integrationsdiff
  und die geänderten Aufrufer nochmals: **PASS**. 87 fokussierte Tests,
  Ruff, Compileall, Inventar-/Diff-Check und frisches Read-only-Docker-
  Image mit 2.582 Tests/11 Skips **PASS**. PR-CI/Sonar/Codex stehen aus.

## P8 Sessiongebundene Chat-Turn-Vorprüfung — Quellstand

- PR #774 wurde am 24.09.2026 um 03:57:52 UTC mit Squash-Commit
  `fb413ae79961b37aecd5153941ebda00544d82dd` gemergt;
  der Commit ist auf `origin/develop` erreichbar, null offene Threads.
  SonarCloud, CodeQL, Unit-/Container-, Qualitäts-, Browser- und
  Codex-Checks **PASS**.
- Root verlagerte Nachricht-/Turn-ID-Grenzen, frühe Cancellation,
  Session-Owner-Prüfung, idempotentes Completed-Read,
  15-Minuten-Stale-Recovery, gespeicherte Provider-/Modellwahl,
  Conversation-ID und Background-Resume nach `CoachChatTurnService`.
  DB-UOW, Lock und `CoachCommandReceiptService` bleiben die
  konkreten Zustandseigentümer; `server.py` enthält nur noch einen
  dekorierten Aufrufer, der nach direkter HTTP-/Worker-Migration
  entfernt werden muss. Keine fachlichen Server-Callbacks.
- Sieben direkte Tests prüfen Validation/Cancel vor DB-Zugriff,
  Session-Weitergabe, idempotentes Read ohne zweite Ausführung,
  fremde Sitzung vor Providerzugriff, persistierte Background-Wahl,
  Stale-Freigabe nach 901 Sekunden und In-Progress nach 899 Sekunden.
  Quellstand: 109 bestehende betroffene Tests, Ruff, Compileall,
  Inventar-/Diff-Check sowie frisches Read-only-Docker-Image mit
  2.589 Tests/11 Skips **PASS**. `server.py`: 3.614 physische
  Zeilen, P0=0. Root prüfte den tatsächlichen Quell-Diff samt
  Session-/DB-Grenze, Providerwahl, Stale-Cutoff und allen Aufrufern:
  **PASS**. Integrationsreview und PR-Gates ausstehend.
- Quellcommit `d5ffe493` wurde auf dem #774-Merge konfliktfrei als
  `3b526915` integriert. Root prüfte den konkreten Integrationsdiff,
  Session-/Owner-/Stale-/Provider-Aufrufer und den vorläufigen
  Server-Adapter erneut: **PASS**. Ruff, Compileall, Inventar-/Diff-
  Check und frisches Read-only-Docker-Image mit 2.589 Tests/11 Skips
  **PASS**. PR-CI/Sonar/Codex stehen aus.
- PR #775 auf `3f4d363c`: Codex-Code-Review **FAIL** mit P2 im Thread
  `PRRT_kwDOUHv92c6lbvJ7`. Die eager Server-Composition baute den
  vollständigen Turn-Graphen vor Validation, Cancellation, Session-
  Owner-Check oder idempotentem Read und konnte dadurch DB-Lesezugriffe
  zu früh auslösen. Root injizierte nur noch reine Composition-Factories
  für Conversation-Provision und Structured-Turn; beide werden erst
  nach erfolgreicher Vorprüfung bzw. bei fehlender Conversation-ID
  aufgelöst. Keine Server-Callbacks mit Fachlogik. Direkte Tests
  assertieren nun, dass beide Factories bei ungültiger, abgebrochener,
  fremder, abgeschlossener und jüngst laufender Anfrage unberührt
  bleiben. Root prüfte den konkreten Korrektur-Diff erneut: **PASS**;
  7 direkte Tests, Ruff, Compileall, Inventar-/Diff-Check und frisches
  Read-only-Docker-Image mit 2.589 Tests/11 Skips **PASS**. Erneute
  Externe CI-/Sonar-/Codex-Prüfung und Thread-Auflösung wurden vor
  dem Merge erneut bestätigt.
- PR #775 wurde nach Korrektur auf `2bdcfd61` mit grünen Checks und
  aufgelöstem Review-Thread gemergt (`mergedAt` 2026-09-24T04:17:26Z,
  Merge-Commit `92670bf62663d3769b0fd2f62285cc50929e2cf0`).
  Der Merge-Commit ist auf `origin/develop` erreichbar: **PASS**.

## P8 Chat-Gate-Grenze — isolierter Quellstand

- Root verlagerte die bisherige äußere Maintenance- und innere
  Conversation-Gate-Reihenfolge vom dekorierten `server.chat_with_coach`
  in `CoachChatTurnService.run()`. `CoachConversationGate.operation()`
  besitzt weiterhin Queue-Slot und denselben Reset-geteilten Lock;
  `wrap()` delegiert auf dieselbe Grenze. Damit kann der Background-
  Worker später den konkreten Turn-Service direkt aufrufen.
- Zwei neue direkte Tests sichern Wartungs-Frühabbruch vor DB/Queue und
  Freigabe der äußeren Wartungsoperation bei voller Chat-Queue.
  Neun direkte Tests, Ruff, Compileall, Inventar-/Diff-Check sowie
  frisches Read-only-Docker-Image mit 2.591 Tests/11 Skips **PASS**.
  `server.py`: 3.613 physische Zeilen, P0=0.
- Der isolierte Quellstand `ec6cfdb7` basiert noch auf dem ersten
  #775-Head. Die Gate-Änderung wird nach dem bestätigten Merge des
  korrigierten Heads sequenziell integriert und erneut geprüft.
- Integrationscommit `afee359b` auf dem bestätigten #775-Merge
  `92670bf6`: Root prüfte den tatsächlichen Diff und die Aufrufer.
  Die Lazy-Factories des #775-Review-Fixes bleiben erhalten; die
  Maintenance-Operation umfasst weiterhin den äußeren Queue-Zugriff,
  der Conversation-Lock bleibt mit Reset geteilt, und Fehler geben
  beide Ressourcen frei. Kein Rückimport aus `backend` nach `server.py`,
  keine veränderte Autorisierung oder Remote-Schreibgrenze: **PASS**.
  88 fokussierte Tests, Ruff, Inventar-/Diff-Check und vollständiges
  frisches Read-only-Docker-Image mit 2.591 Tests/11 Skips **PASS**.
  Verbleibend: Der dünne Server-Aufrufer und die Background-Worker-
  Orchestrierung müssen in den nächsten P8-Schritten entfernt werden;
  externe PR-Gates stehen für diesen Stand noch aus.

- PR #776 wurde mit vollständig grünen CI-/Browser-/Sonar-/Codex-Gates,
  null offenen Review-Threads und null offenen Sonar-Issues gemergt
  (`mergedAt` 2026-09-24T04:27:59Z, Merge-Commit
  `5d977a82a24a9a1cede063ce172e856f0cafe252`). Der Commit ist
  auf `origin/develop` erreichbar: **PASS**.

# P8 Morning Coach job completion receipt — isolierter Quellstand

- Auf Basis des isolierten Branches `refactor/p8-morning-completion-source-20260924`
  (`5863e91c`, vor dem Merge von PR #776) besitzt
  `MorningCoachJobCompletionService.complete()` die persistierten lokalen
  Morning-Status-/Datumsmarker und die atomare Receipt-Projektion. Der Service
  bekommt DatabaseManager/Lock, KeyValueRepository, QuickActions-Servicefactory
  sowie lokale/UTC-Uhr injiziert. `server.py` verdrahtet diese Abhängigkeiten
  am dünnen `_persist_completed_morning_coach_job`-Adapter; dieser bleibt bis
  zur folgenden Worker-Migration temporär. Backend-Code importiert kein
  `server.py`.
- Die zwei getrennten UOWs, QuickActions-Read dazwischen, Datum des lokalen
  Tages, Completed-Statusfilter, `updated_at`, `client_turn_id`-Filter,
  Unicode-/kompaktes JSON und bisherige Rückgabe auch für fehlende oder nicht
  abgeschlossene Commands bleiben erhalten. Direkte Tests prüfen Erfolg,
  fehlende/nicht abgeschlossene Zeile, beide Transaktionsgrenzen und die
  Reihenfolge von QuickActions nach dem Commit des `ready`-Markers. Eine
  Worker-Regression prüft weiterhin das zurückgegebene Receipt. Ein Fehler
  der QuickActions-Projektion propagiert nach der ersten UOW; der bereits
  committed Marker bleibt erhalten und Receipt samt `updated_at` unberührt.
- Vier direkte Service-Tests, Worker-/Morning-/Background-Regressionen,
  Architekturtests, Ruff für das neue Backendmodul und direkte Tests,
  `compileall`, Inventar-`--check` und `git diff --check`: **PASS**.
  Frischer Python-3.14-Docker-Build: **PASS**. Vollständige Suite im frischen
  read-only Container mit Worktree als read-only Quelle: 2.596 Tests,
  11 Skips, **PASS**. Es wurden nur temporäre Testdaten und gemockte Aufrufe
  verwendet.
- Root prüfte den tatsächlichen Worker-Commit `a8015024` samt Service,
  Server-Caller, DB-/Statusfiltern, JSON-Vertrag und Tests. Ein zunächst
  fehlender Failure-Boundary-Test wurde an denselben Worker zurückgegeben
  und vor Integration ergänzt. Die sequenzielle Integration auf dem
  bestätigten #776-Merge ist `e35ed7a8`; 21 fokussierte Tests, Ruff,
  Compileall, Inventar-/Diff-Check und ein frisch gebautes Read-only-
  Docker-Image mit 2.596 Tests/11 Skips **PASS**. Externe PR-Gates
  werden für den integrierten Stand gesondert bestätigt. Der vorläufige
  Server-Adapter bleibt ein P8-Risiko bis zur Worker-Auslagerung.

- PR #777 wurde mit grünen CI-/Browser-/Sonar-/Codex-Gates, null offenen
  Review-Threads und null offenen Sonar-Issues gemergt (`mergedAt`
  2026-09-24T04:43:26Z, Merge-Commit
  `032c4a9f6439c7d7ad4a45be724f7cef03a689b5`). Der Commit ist
  auf `origin/develop` erreichbar: **PASS**.

## P8 Background-Job-Runner — isolierter Quellstand

- Root verlagert aus `server.py` die komplette Ausführung eines geclaimten
  Coach-Jobs einschließlich Session-Binding, persistiertem Cancel-Read,
  Turn-Aufruf, Morning-Abschluss, Contention-Requeue, Fehlerprojektion,
  SSE-Delta-/Receipt-/Error-Publikation und Event-Cleanup nach
  `CoachBackgroundJobRunner`. `CoachJobStore` besitzt weiter den durable
  Claim und das neue Cancel-Read; `ChatStreamRegistry` behält Queue und
  process-lokale Cancel-Events. Kein Backend-Rückimport aus `server.py`.
- Initialer Root-Diff-Review fand ein **FAIL**: Der Runner-Composer
  konstruierte den Chat-Service vor Generation-/Session-Prüfung und hätte
  den in #775 korrigierten Lazy-Composition-Vertrag erneut verletzt.
  Die konkreten Service-Factories werden jetzt ausschließlich an ihrem
  fachlichen Einsatzpunkt aufgelöst. Direkter Regressionstest prüft, dass
  invalidierte Claims weder Factories noch Session-/Failure-Pfade berühren.
- Der vorläufige `_run_background_coach_job`-Caller und die processweite
  Worker-Loop verbleiben nur bis zum unmittelbar folgenden Lifecycle-Umzug;
  dauerhafte Kompatibilitäts-Wrapper sind nicht zulässig. Die bisherigen
  Worker-Test-Patchziele wurden auf `CoachChatTurnService.run` und den
  Morning-Completion-Service verlegt, sodass Tests keine ungemockten
  Provideraufrufe auslösen. Der Session-Binding-Vertrag ist als enger
  Coach-Protocol typisiert; es entsteht keine Coach→HTTP-Importkante.
  Vier direkte Runner-Tests sichern Claim-Invalidation, persistiertes Cancel,
  Contention-Requeue/SSE und Morning-Abschluss. 72 Dialog-Tests, 32 Audit-/
  Provider-Tests (2 Skips), 495 Server-Tests (3 Skips), Architektur-, Ruff-,
  Compileall-, Inventar- und Diff-Checks **PASS**. Ein erster vollständiger
  Docker-Lauf meldete **FAIL**, weil zwei neue Composition-Factories noch
  nicht dem Inventar zugeordnet waren; der Generator wurde konkret ergänzt.
  Danach: frisches Read-only-Docker-Image mit 2.600 Tests/11 Skips **PASS**.
  Der Root-Review des Quell-Diffs ist nach Lazy- und Importkorrektur **PASS**;
  sequenzielle Integration und externe PR-Gates stehen noch aus.
- Quellcommit `66e0dc37` wurde auf dem bestätigten #777-Merge
  `032c4a9f` konfliktfrei als `e038483f` integriert. Root prüfte den
  tatsächlichen Integrationsdiff, die migrierten Patch-Ziele, Claim-
  Generation, Cancel-Read, Transaktions-/Morning-Grenzen, Datenschutz-
  Redaction und SSE-/Retry-/Cleanup-Pfade erneut: **PASS**. 23 fokussierte
  Tests, Ruff, Compileall, Inventar-/Diff-Check und frisches Read-only-
  Docker-Image mit 2.600 Tests/11 Skips **PASS**. Verbleibendes Risiko:
  temporärer Server-Caller und Worker-Loop; externe PR-Gates stehen aus.
- PR #778 auf `47e179ba`: Sonar **FAIL** mit `python:S1192` wegen
  dreifacher identischer Receipt-SELECT-Konstante im `CoachJobStore`.
  Root ersetzte nur die drei identischen Literale durch `SELECT_RECEIPT_SQL`;
  SQL, Filter, UOWs und Rückgaben bleiben unverändert. Korrektur-Diff
  erneut geprüft: **PASS**; 20 direkte/Architekturtests, Ruff,
  Diff-Check und frisches Read-only-Docker-Image mit 2.600 Tests/
  11 Skips **PASS**. Externe Gates folgen erneut.
- PR #778 wurde nach erneutem Codex-Review und grünen CI-/Sonar-Gates
  gemergt (`mergedAt` 2026-09-24T05:07:32Z, Merge-Commit
  `208565fac1bd4547deca590a89b3097026a06c83`). Review-Threads:
  null; Merge-Commit auf `origin/develop` erreichbar: **PASS**.

## P8 Coach-Worker-Lifecycle — isolierter Quellstand

- Root verlagerte die processweite Thread-/Wake-/Stop-/Lock-
  Eigentümerschaft und die Maintenance-Claim-Pollschleife nach
  `CoachJobWorker`. `server.py` importiert nur die konkrete Backend-
  Instanz, verdrahtet ihre Wake-Event-Referenz für Store, Enqueue und
  Restore und startet sie erst nach Schema und Job-Recovery. Der
  temporäre `_run_background_coach_job`-Adapter, Server-Worker-Globals
  und beide Server-Lifecycle-Funktionen sind entfernt. Runner und
  Job-Store tragen weiterhin die fachliche Ausführung und durable Daten.
- Direkte Tests prüfen idempotenten Daemon-Start, äußere Maintenance-
  Operation um Claim und Ausführung, Wartungsablehnung ohne Claim,
  Stop-Wakeup sowie Propagation unerwarteter Claim-Fehler. Startup-
  Reihenfolge und acht Worker-Testaufrufer wurden auf konkrete Backend-
  Eigentümer migriert. 13 fokussierte und 108 betroffene Regressionen
  (2 Skips), Ruff, Compileall, Inventar-/Diff-Check und frisches
  Read-only-Docker-Image mit 2.604 Tests/11 Skips **PASS**. Root prüfte
  den tatsächlichen Quell-Diff einschließlich Queue-/Stop-Eigentum,
  unveränderter fünfsekündiger Poll-/Wake-Semantik, Startreihenfolge,
  Restore-Gate und Test-Patchzielen: **PASS**. Integration auf dem
  bestätigten #778-Merge und externe PR-Gates stehen noch aus.
- Quellcommit `092ff440` wurde nach dem bestätigten #778-Merge
  `208565fa` als `4259d303` integriert; der Dokumentkonflikt bewahrte
  sowohl den #778-Sonar-Fix als auch den Lifecycle-Befund. Root prüfte
  den tatsächlichen Integrationsdiff, Wake-Referenzen aller drei
  Verbraucher, Startup-/Restart-Reihenfolge und Patch-Ziele erneut:
  **PASS**. 26 fokussierte Tests, Ruff, Compileall, Inventar-/Diff-
  Check und frisch gebautes Read-only-Docker-Image mit 2.604 Tests/
  11 Skips **PASS**. Externe PR-Gates und die reine Test-Adapter-
  Bereinigung `server.chat_with_coach` blieb als reine Testmigration offen.

## P8 `server.chat_with_coach`-Testadapter — isolierter Quellstand

- Vor jeder Löschung wurde `rg` über Produktiv-Python-Code ausgeführt:
  außer der Adapterdefinition gab es keinen Produktiven Aufrufer; die
  Tests nutzten noch elf direkte Aufrufstellen. `CoachBackgroundJobRunner`
  konsumiert bereits `CoachChatTurnService.run`.
- Der Adapter wurde entfernt. Tests rufen über die Composition-Factory
  `server.coach_chat_turn_service().run` auf; bestehende Assertions und
  `CoachChatTurnService.run`-Patchziele bleiben auf dem konsumierten Backend-
  Use-Case. Ein Architekturtest verhindert eine erneute Server-Definition.
- Die elf migrierten Testaufrufe decken Kontextaktualisierung, Attachments,
  synchrone und persistente Hintergrundausführung, Sessionbindung,
  Providerstreaming, Retry, Receipt-Replay und Review-Regressionspfade ab.
  Zusammen mit dem Architekturguard ist diese direkte Testfläche für die
  Entfernung eines reinen Einzeilen-Weiterleiters angemessen; die Service-
  Verträge selbst bleiben durch die vorhandenen Coach-Use-Case-Tests geprüft.
- Sieben betroffene Module einschließlich Architekturtest: 630 Tests,
  4 erwartete SQLCipher-Skips **PASS**. Compileall, Inventar-`--check`
  und `git diff --check` **PASS**. Ruff fand im vollständigen Umfang der
  großen bestehenden Server-/Testmodule 223 bestehende Befunde; keiner liegt
  auf den geänderten Testaufrufen oder dem neuen Architekturguard.
- Frisches Docker-Image `sha256:c59271324b09d723580b05e83400f2beb8ed9f54d085d067cfddbfbc83a0cd05`;
  read-only Container-Suite: 2.605 Tests, 11 Skips **PASS**. Das kanonische
  Skript mountet `docs/` nicht und hatte daher zunächst zwei Dokumentlese-
  fehler; derselbe Containerlauf bestand mit zusätzlichem read-only-
  Docs-Mount. Tests nutzten temporäre Daten und abgefangene Provideraufrufe.
- Quellstand: Branch `refactor/p8-chat-adapter-cleanup-source-20260924`,
  Basis `e5d85bb593d36bed3873628673e725b990bf2e49`. Kein Rebase.

## P8 Testadapter — Sol-Integrationsreview

- Vorgänger-PR #779 wurde am 24.09.2026 um 05:15:00 UTC mit
  `002dea5a2c1607273568de562485e542283a7733` gemergt; der Commit ist
  Vorfahr von `origin/develop`. Container-, Sonar-, Codex- und nachlaufender
  Browser-Check waren erfolgreich; keine offenen Review-Threads.
- Quellcommit `af7fd92a78f14a004276c17c9ae547b18f341f1a` wurde als
  `bfbb8305c240d691dd4c8a3cf99f065b33dadd15` auf genau diesen
  `develop`-Stand übernommen. Geprüft wurden der tatsächliche Quell-Diff,
  alle elf migrierten Aufrufer, die konsumierte Backend-Schnittstelle und
  der integrierte Diff.
- **PASS**: Nur der ungenutzte Server-Weiterleiter entfiel. Der HTTP-Handler
  und der Background-Runner konsumieren bereits `CoachChatTurnService.run`;
  die Tests rufen dieselbe Use-Case-Grenze direkt auf. Kein neuer Callback,
  Rückimport, Zustandsbesitzer oder gelockerter Sicherheitsvertrag.
- Integrationstests: 520 Coach-Tests **PASS**; frisch gebautes Read-only-
  SQLCipher-Image mit vollständiger Suite 2.605 Tests/11 Skips **PASS**;
  Compileall, Inventar-`--check`, `git diff --check` und Definitionen-Suche
  **PASS**. Die elf ersetzten Testaufrufe behalten ihre Assertions; ein
  Architekturtest schützt gegen erneute Einführung des Adapters. Diese
  Testzahl ist für die reine Weiterleiter-Entfernung angemessen.
- Restrisiko: Die umfangreichen noch vorhandenen `server.*`-Testpatches
  müssen in P11 anhand der tatsächlichen Lookup-Orte migriert werden;
  dieser Patch erweitert ihre Zahl nicht. P7/P8-Elternpunkte und P10/P11
  bleiben offen.

## P10 Coach-GET-Routen — isolierter Quellstand

- Die drei GET-Routen `/api/chat/history`, `/api/chat/receipt` und
  `/api/chat/status` liegen in `backend/http_api/coach_get.py` unter einem
  zustandslosen `CoachGetRoutes`. `server.py` komponiert die Route explizit
  aus `SessionAuthService`, `ChatHistoryPageService`,
  `CoachCommandReceiptService` und `CoachJobSubmissionService`.
- Authentifizierung bleibt vor Query-/Servicezugriff; der Handler verwendet
  pro Request die Auth-Factory. Der Route-Dienst enthält weder Lock noch Cache.
  CSRF-Hash, Query-Defaults und URL-Decodierung, Status 200/JSON sowie
  Fehlerpropagation bleiben erhalten. Unbekannte Pfade lösen keine Factory
  auf. Andere GET-, POST- und SSE-Pfade wurden nicht geändert.
- Vor Änderungen wurden alle drei Service-Factorys, `_handle_coach_get` und
  vorhandene Testaufrufer/Patchstellen durchsucht. Es gab keine bestehenden
  Tests, die diese Handler-Methode oder deren Route-Factory patchten.
  Acht direkte Fake-Handler-/Fake-Service-Tests prüfen alle drei Routen,
  Defaults und dekodierte History-Querywerte, Auth-Scope, Auth-Fehler,
  dynamische Auth-Auflösung auf dem zweiten Request und den unbekannten Pfad.
- **PASS**: 17 fokussierte Routen-/Architekturtests; vollständige
  Read-only-Docker-Suite im frisch gebauten SQLCipher-Image
  `ai-coach:p10-coach-get-routes-source-20260924`: 2.614 Tests, 11 Skips.
  Ruff für Route, direkte Tests und Architekturtest, Compileall,
  Inventar-`--check` und `git diff --check` bestanden. Ruff auf `server.py`
  meldet dieselben 22 bestehenden Befunde wie `HEAD`; kein neuer Befund.
- Quellbasis: `4d2409ad2f1e96be4d260f4c77d231485843cfdf`, Branch
  `refactor/p10-coach-get-routes-source-20260924`. Kein Rebase, Push,
  Pull Request oder Merge.

## P10 Coach-GET-Routen — Sol-Integrationsreview

- Vorgänger-PR #780 wurde am 24.09.2026 um 05:27:51 UTC mit
  `a98092dc1611a5fd22f485fc6a928c5d254039ae` gemergt; der Commit
  ist Vorfahr von `origin/develop`. Alle Checks einschließlich Browser,
  Container, Sonar und Codex waren erfolgreich, ohne offene Review-Threads
  oder Sonar-Issues.
- Der Quellcommit `b37f03c98a5d36a5730bec963a3b7bf924c26bc3`
  wurde als `f4b9e4a04339400c123a1cbba80d71be4d2ae3bb` integriert.
  Geprüft wurden tatsächlicher Diff, Route, Server-Call-Site, alle acht
  direkten Tests und die Architekturprüfung; keine fremden Änderungen.
- **PASS**: Auth wird vor Datendienst und bei jedem Request neu aufgelöst;
  unbekannte Pfade berühren keine Factory. Die bisherigen Zustandseigentümer
  bleiben für Session, Pagination, Receipt und Jobstatus zuständig. Die
  Route enthält keine Fachmutation, keinen Server-Rückimport und keinen
  neuen Lock/Cache. Andere GET-, POST- und SSE-Verträge blieben unberührt.
- Integrierte Prüfung: acht direkte Routen- plus neun Architekturtests
  **PASS**; frisch gebautes Read-only-SQLCipher-Image mit 2.614 Tests/
  11 Skips **PASS**; Ruff für neue/geänderte Module, Compileall,
  Inventar-`--check` und `git diff --check` **PASS**. Die acht direkten
  Tests sind für die drei schmalen GET-Routen angemessen, weil sie alle
  Verzweigungen sowie Auth-, Query- und Keep-Alive-Grenzen ausführen.
- Restrisiko: Die übrigen Handler-Routen, Body-/SSE-Transport und der
  komplette P11-Architektur-/Testpatch-Audit sind noch offen.

## P10 öffentliche GET-Routen — isolierter Quellstand

- `/api/health`, `/api/readiness`, `/api/auth/status` und `/api/bootstrap`
  liegen in `backend/http_api/public_get.py` unter einem zustandslosen
  `PublicGetRoutes`. `server.py` verdrahtet explizit
  `runtime_maintenance.MAINTENANCE_GATE`, `readiness_service`,
  `session_auth_service` und `public_bootstrap_service`.
- Maintenance-Gate, Readiness-, Session-Auth- und Bootstrap-Service bleiben
  die Zustandseigentümer. Unbekannte Pfade lösen keine Factory oder Gate-Abfrage
  aus; Auth wird für jeden Request neu aufgelöst. `/api/auth/status` nutzt
  ausschließlich `authenticated_session`; Bootstrap authentifiziert vor dem
  Read. Status, JSON, Fehlerpropagation und bestehende Servicegrenzen bleiben
  erhalten.
- Vor der Änderung wurden `_handle_public_get`, alle vier Pfade, Route-Dispatch,
  Service-Factorys und Test-Patchstellen gesucht. Die zwei bestehenden
  Readiness-Handler-Vertragstests bleiben erhalten und rufen nun
  `server.PUBLIC_GET_ROUTES.handle(handler, "/api/readiness")` auf. Ihre
  Assertions zu dynamischem DatabaseManager auf Folgeanfragen sowie 503 und
  redigiertem JSON bei Kompositionsfehlern sind unverändert.
- **Review-Fix:** Die erste Sol-Vorabprüfung meldete **FAIL**, weil dieser
  Zwischenstand beide bestehenden Readiness-Handler-Vertragstests entfernt
  hatte; die neuen Fake-Route-Tests deckten ihre Risiken nicht gleichwertig ab.
  Beide Testfälle wurden wiederhergestellt und auf den neuen Call-Site-Lookup
  migriert, ohne Assertions zu entfernen oder abzuschwächen. Beide Tests liefen
  danach gezielt erfolgreich.
- Sieben direkte Fake-Handler-/Service-Tests prüfen alle vier Routen,
  Readiness true/false, Authstatus false/true, Bootstrap-Auth-Reihenfolge und
  Fehlerpropagation, dynamische Auth-Auflösung bei Keep-Alive sowie unbekannte
  Pfade ohne Abhängigkeitsaufrufe. Ein zusätzlicher Architekturtest prüft
  Route-Dispatch, konkrete Composition-Factories und die Entfernung des alten
  Handler-Dispatchers.
- **PASS:** Frisch gebautes SQLCipher-Image
  `ai-coach:p10-public-get-routes-source-20260924`, read-only mit ausschließlich
  read-only Test-/Dokumentations-/Workflow-/Fixture-/Playwright-Mounts und
  flüchtigen `/tmp`-/`/data`-tmpfs: vollständige Python-Suite mit 2.622 Tests,
  11 Skips. Die ersten zwei Containeraufrufe zeigten fehlende Test-Source-
  Mounts im Image; nach Ergänzung des fehlenden `/app/playwright.config.cjs`
  bestand der vollständige Lauf. Es wurden keine Testdateien geändert, um
  Mountfehler zu umgehen.
- Ruff für `public_get.py`, die direkten Routentests und den Architekturtest,
  Compileall, Inventar-`--check` und `git diff --check` bestanden.
  Die Readiness-Vertragstests liefen zusätzlich gezielt unter der lokalen
  Python-Umgebung erfolgreich.
- Kein Rebase, Push, Pull Request oder Merge.

## P10 öffentliche GET-Routen — Sol-Integrationsreview

- Vorgänger-PR #781 wurde am 24.09.2026 um 05:40:26 UTC mit
  `08c81c11f868b8b287e93e6caa09b875ea31bff6` gemergt; der Commit
  ist Vorfahr von `origin/develop`. Auch der nachlaufende Browser-Check
  endete erfolgreich. Keine offenen Review-Threads oder Sonar-Issues.
- Quellcommit `22b2e478` wurde als `d728619c70fa619713fe9bd9deb1d7bf5a72aaa9`
  auf den bestätigten `develop`-Stand übernommen. Tatsächlicher Quell-
  und Integrations-Diff, alle vier Handler-Pfade, die Factory-Lookups,
  bestehenden Readiness-Verträge und die neuen Tests wurden geprüft.
- **FAIL → Korrektur → PASS**: Im ersten Worker-Diff fehlten zwei alte
  Readiness-Handler-Tests. Nach konkretem Korrekturauftrag wurden beide
  mit sämtlichen Assertions auf `PUBLIC_GET_ROUTES.handle` migriert;
  dynamische DB-Manager-Bindung, redigierter 503-Fehler und JSON-Vertrag
  sind weiterhin getestet. Der korrigierte Diff enthält keine
  Testabschächung.
- Route und Zusammensetzung sind zustandslos. Maintenance-, Readiness-,
  Session- und Bootstrap-Eigentümer bleiben unverändert; unbekannte
  Pfade lösen nichts auf, Authstatus bleibt optional, Bootstrap verlangt
  Auth vor dem Read. Kein Backend-Rückimport oder Fachlogik-Callback.
- Integrierte Abnahme: sieben direkte Routen- und zehn Architekturtests
  **PASS**; beide migrierten Readiness-Verträge **PASS**; frisch gebautes
  Read-only-SQLCipher-Image mit vollständiger Suite 2.622 Tests/11 Skips
  **PASS**; Ruff für neue Route/Tests, Compileall, Inventar-`--check`
  und `git diff --check` **PASS**. Die sieben direkten Tests plus die
  erhaltenen Fehlerverträge decken die vier Routen angemessen ab.
- Restrisiko: Die übrigen Handler-, SSE- und P11-Audit-Arbeiten bleiben
  offen; `server.py` hat auf diesem Stand 3.438 physische Zeilen.

## P10 öffentliche GET-Routen — CI-Nachreview

- PR #782 meldete bei SonarCloud zunächst **FAIL**, ausschließlich wegen
  `new_duplicated_lines_density=8.4%` (Grenze 3%): 22 neue Duplikatzeilen
  lagen im Architekturtest zwischen Coach- und Public-GET-Routenprüfungen.
  Die Sonar-Issuesuche selbst ergab null offene Issues.
- Die gemeinsame AST-Prüfung für Handler-Methode und genau einen
  `do_GET`-Delegationsaufruf wurde in einen Testhelfer extrahiert. Beide
  bisherigen Tests prüfen dieselben entfernten Methoden und Routenamen
  weiter; der Public-Test prüft zusätzlich weiterhin alle vier konkret
  verdrahteten Factories. Kein Produktionscode wurde geändert.
- Aktualisierter Integrationsstand: zehn Architektur- und sieben direkte
  Routentests **PASS**; vollständige Read-only-SQLCipher-Suite erneut
  2.622 Tests/11 Skips **PASS**; Ruff, Compileall, Inventar-`--check`
  und Diff-Check **PASS**. Root-Review des geänderten Testumfangs erneut
  **PASS**. Das externe Sonar-Gate muss auf dem neuen Commit neu laufen;
  bis zu dessen Erfolg bleibt der PR unfreigegeben.

## P10 Plan-/Wetter-/Library-GET-Routen — isolierter Quellstand

- `/api/plan`, `/api/weather` und `/api/library` liegen in
  `backend/http_api/planning_get.py` unter `PlanningGetRoutes`. `server.py`
  verdrahtet ausschließlich die konkreten Session-Auth-, Plan-State-,
  Wetter-State- und Library-Page-Factories. Die Route besitzt keinen Lock
  oder Cache und greift pro Request dynamisch auf Auth zu.
- Die drei bisherigen Zweige wurden aus `_handle_training_get` entfernt;
  Performance, Profile, Feedback und Context-Preview verbleiben unverändert.
  Auth wird vor jedem Datendienst aufgerufen. `local` nutzt ausschließlich
  den ersten Querywert `1`; Library reicht jeweils den ersten `cursor`- und
  `limit`-Wert beziehungsweise `None` weiter. Status und JSON bleiben 200.
- Die beiden bestehenden Wetter-/Plan-Handler-Vertragstests wurden auf
  `PLANNING_GET_ROUTES.handle` migriert; ihre Auth-, Factory-, Query- und
  JSON-Assertions sind erhalten. Sie patchen nun die tatsächlich von der
  Route injizierten Factory-Callables. Sieben direkte Fake-Handler-/Service-
  Tests decken alle drei Routen, erste Querywerte und Defaults, Authfehler,
  unbekannte Pfade ohne Factory-Aufruf sowie erneute Auth-Auflösung bei
  Folgeanfragen ab. Der Architekturtest nutzt die gemeinsame AST-Prüfung
  für Dispatch und Composition-Factories.
- **PASS:** Frisch gebautes SQLCipher-Image
  `ai-coach:p10-planning-get-routes`, Read-only und netzwerkisoliert, mit
  schreibgeschützten Test-/Dokumentations-/Public-/Server-/E2E-/Workflow- und
  Playwright-Konfigurations-Mounts sowie flüchtigem `/tmp`: vollständige
  Python-Suite mit 2.630 Tests und 11 Skips.
- Sieben Routentests, elf Architekturtests, beide migrierten Handler-Verträge,
  Compileall, Inventar-`--check` und `git diff --check` bestanden. Ruff für
  neue Route, direkte Routentests und Architekturtests bestanden. Der breitere
  Ruff-Lauf meldet weiter Altverstöße in `server.py`/`tests/test_server.py`;
  die `F`-Befunde sind gegenüber HEAD unverändert (11 im Server, 2 im alten
  Server-Testmodul).
- Kein Rebase, Push, Pull Request oder Merge.

## P10 Plan-/Wetter-/Library-GET-Routen — Sol-Integrationsreview

- Vorgänger-PR #782 wurde am 24.09.2026 um 06:03:31 UTC mit
  `df1a69365ec00d7982e0cbfad5e0255bc016c4af` gemergt; der Commit
  ist Vorfahr von `origin/develop`. Sonar-Gate, Codex-Review und der
  nachlaufende Browser-Check waren erfolgreich, ohne offene Review-Threads.
- Quellcommit `7f8725e95c884d5c5004093c9406916220b3028a` wurde als
  `8fe87c0ebe6048ac5074a4db2c0c010f3881a01d` übernommen.
  Tatsächlicher Diff, alle drei Routen, beide migrierten Handler-Verträge,
  Factory-Lookup, Architekturguard und unbekannter Pfad wurden geprüft.
- **PASS**: `PlanningGetRoutes` ruft Auth vor Datendiensten und bei jedem
  Request neu auf; Query-Defaults und erste `local`-/`cursor`-/`limit`-
  Werte bleiben unverändert. Plan-, Wetter- und Library-Services behalten
  ihre Zustandseigentümerschaft. Keine Rückimporte, Fachlogik-Callbacks,
  neuen Locks/Caches oder Änderungen an den anderen GET-/SSE-Pfaden.
- Integrierte Abnahme: sieben direkte Routen- und elf Architekturtests
  **PASS**, beide alten Plan-/Wetter-Handler-Verträge samt Assertions
  **PASS**; frisch gebautes, netzwerkisoliertes Read-only-SQLCipher-Image
  mit 2.630 Tests/11 Skips **PASS**; Ruff für Route/direkte Tests/
  Architektur, Compileall, Inventar-`--check` und Diff-Check **PASS**.
  Diese Testzahl deckt alle drei Zweige und Auth-/Query-/Folgeanfragen
  angemessen ab.
- Die Architekturtests verwenden den gemeinsamen Factory-AST-Helfer,
  damit der zuvor bei #782 aufgetretene Sonar-Duplikationsfehler nicht
  wieder eingeführt wird. Externe Gates dieses neuen PR stehen noch aus.
  `server.py` hat hier 3.432 physische Zeilen; weitere Handler-Routen,
  SSE und P11 bleiben offen.

## SQLCipher-Testskript — isolierter Integrationsreview

- Vorgänger-PR #783 wurde am 24.09.2026 um 06:22:51 UTC mit
  `bc4367b3bc2a9f35ed7e484cbbd93a62d4687283` gemergt; der Commit
  ist Vorfahr von `origin/develop`, ohne offene Review-Threads.
- Quellcommit `3d212c40` wurde als `25dd8afe` auf diesen Stand übernommen.
  Der tatsächliche Diff in `tests/run_sqlcipher_tests.ps1` ergänzt nur
  den schreibgeschützten `docs/`-Mount, den schreibgeschützten
  Playwright-Konfigurationspfad unter `/app`, flüchtiges `/data` und
  deaktiviertes Containernetzwerk. `.env`, Datenbank und Athletendaten
  werden weiterhin nicht gemountet.
- **PASS**: Das kanonische Skript selbst baute auf dem integrierten Stand
  ein frisches SQLCipher-Image und führte die vollständige Suite mit
  2.630 Tests/11 Skips erfolgreich aus; `git diff --check` ist sauber.
  Dadurch sind die zuvor wiederholt nötigen manuellen Test-Mounts
  reproduzierbar im Skript enthalten, ohne einen Testfall abzuschwächen.
- P10-Handler- und P11-Restaudit bleiben offen; die Skriptänderung
  verändert keinen Produktivcode und keine Checklistenbewertung.

## P10 Athlete-GET-Routen — Integrationsreview

- Vorgänger-PR #784 wurde am 24.09.2026 um 06:28:32 UTC mit
  `7eb7ae6fb5930a9fa949788fd83d89bc05cbcab6` gemergt; der Commit ist
  Vorfahr von `origin/develop`. Erforderliche CI-/Browser-/Codex-/Sonar-
  Checks bestanden, das Sonar-Gate ist OK und es gibt keine offenen
  Review-Threads. Der abgebrochene, nicht erforderliche Review-Koordinator-
  Nebenjob änderte diese Gates nicht.
- Quellcommit `7e8253927a395b497d92bc04beb90ec51a97ee97` wurde als
  `d099fd7e` integriert. **FAIL** beim ersten Root-Review: Ruff I001 in
  `backend/http_api/athlete_get.py`. Derselbe GPT-6-Luna-Worker korrigierte
  ausschließlich die Importfolge in `9b328fba5e91cc41a0d2e2ced913097da0100e48`,
  integriert als `730a2065`; Ruff und fokussierte Tests wurden erneut grün.
- Der tatsächliche Diff und die Aufrufer sind geprüft: Alle vier GET-Pfade
  `/api/performance`, `/api/profile`, `/api/feedback` und
  `/api/context-preview` gehören nun `AthleteGetRoutes`; `_handle_training_get`
  entfällt vollständig. Auth wird nach Pfadmatch vor Datendiensten pro
  Request neu aufgelöst. Profil und Wettkämpfe bleiben beim jeweiligen
  Service, das Wettkampflimit bleibt 100. Die Preview liest die Providerwahl
  bei jedem Request aus derselben Settings-Instanz. Keine Rückimporte,
  Server-Fachcallbacks, neuen Caches/Locks oder Remote-Schreibpfade.
- Der erste integrierte Volltest ergab **FAIL** (1/2.636): Das generierte
  Inventar ordnete die neue `ATHLETE_GET_ROUTES`-Bindung mangels expliziter
  Regel fälschlich P0 zu. Root ergänzte die Zuordnung im Inventargenerator
  und regenerierte das Inventar; P0 zählt wieder 0 offene Einträge.
- **PASS** auf dem korrigierten integrierten Stand: 5 direkte Routentests,
  12 Architekturtests, 495 bestehende `test_server.py`-Tests (3 Skips),
  vollständige frisch gebaute Read-only-/netzwerkisolierte SQLCipher-Suite
  mit **2.636 Tests/11 Skips**, Ruff für neue Route/Tests/Inventarskript,
  Compileall, Inventar-`--check` und Diff-Check. Die fünf direkten Tests
  decken vier Payloads, Authfehler, unbekannte Pfade, neue Auth-Instanz auf
  Folgeanfragen und dynamische Providerwahl angemessen ab.
- `server.py` hat 3.425 physische Zeilen. P10-Sync-/Diagnostik-/POST-/SSE-
  Transport sowie P7/P8-Restzuordnungen und P11 bleiben offen. Nächster
  kleiner Auftrag: die authentifizierten Sync-GET-Routen außer SSE.
