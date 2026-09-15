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
- Integrierter Diff-Stand vor Commit: SHA-256
  `d19977a28fa2e4af254e2c391293a83ab1811b75edde5c91eaacca002e1762d2`.
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
