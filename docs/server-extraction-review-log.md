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
