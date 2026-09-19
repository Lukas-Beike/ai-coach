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
- Korrekturcommit `27301f4`: **PASS** im erneuten Root-Diff- und Code-Review.
  Ausschließlich private Parserteilschritte wurden getrennt; öffentliche API,
  Eventreihenfolge, Delta-/Response-ID-Ausgabe, Metadatenaggregation und
  Fehlerverträge bleiben unverändert.
- Provider- und Architekturregressionen: 32 Tests, PASS. Vollständiger Lauf:
  888 Tests, 12 übersprungen, PASS in 183,539 s. Ruff, Compileall und
  `git diff --check`: PASS. Der aktualisierte PR-Head benötigt erneut alle
  externen Gates.

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
