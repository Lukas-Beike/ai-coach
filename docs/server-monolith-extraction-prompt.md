# Orchestrator-Prompt für die server.py-Auslagerung

Diesen Prompt im Haupt-Task mit **GPT-5.6 Sol** und Reasoning `high` verwenden.
Die delegierten Worker sollen ausdrücklich mit **GPT-5.6 Luna** und Reasoning
`high` gestartet werden.

```text
Setze den Plan in docs/server-monolith-extraction-plan.md vollständig um.

Rollen und Modelle
- Du bist der Orchestrator, Integrator und das abschließende Review-Gate.
  Verwende dafür GPT-5.6 Sol mit Reasoning high.
- Spawne echte Subagents mit explizitem Modell gpt-5.6-luna und
  Reasoning high für klar abgegrenzte Implementierungsaufgaben.
- Prüfe vor der Delegation, ob diese Modellzuweisung unterstützt wird.
  Behaupte keinen Luna-Einsatz, wenn das Modell nicht tatsächlich
  entsprechend ausgewählt wurde.
- Nutze maximal zwei Luna-Worker gleichzeitig.
- Architekturentscheidungen, schwierige Abhängigkeiten und unmittelbar
  blockierende Integrationsarbeit übernimmst du selbst.
- Luna darf keine weiteren Subagents starten.

Vorbereitung und Aufgabenzerlegung
- Lies die geltenden AGENTS.md-Dateien und den vollständigen Plan.
- Prüfe den aktuellen Repository- und PR-Stand; bereits abgeschlossene
  Arbeit nicht wiederholen.
- Arbeite in dedizierten Worktrees und Task-Branches.
- Beginne mit P0 und arbeite anschließend entlang der Abhängigkeiten.
- Zerlege jede Phase in kleine, vollständig abschließbare fachliche
  Auslagerungen. Delegiere keine ganze Großphase pauschal an Luna.
- Lege vor jeder Delegation Zielmodul, öffentliche Schnittstelle,
  Abhängigkeiten, Zustandseigentümer und Abnahmekriterien fest.

Auftrag an jeden Luna-Worker
Übergebe ausdrücklich:
1. Die konkrete Verantwortung und die betroffenen Funktionen.
2. Den Ausgangsstand und den zu verwendenden Arbeitsbereich.
3. Die Dateien, die der Worker bearbeiten darf.
4. Die verbindlichen Schnittstellen und Architekturentscheidungen.
5. Die zu erhaltenden Verhaltens- und Sicherheitsverträge.
6. Die auszuführenden Tests.
7. Das erwartete Ergebnis: implementierter Patch, geänderte Dateien,
   tatsächliche Testergebnisse und offene Unsicherheiten.

Worker dürfen keine fremden Änderungen überschreiben, Testanforderungen
abschwächen oder ihren Schreibbereich eigenmächtig erweitern.
Bei einer notwendigen Schnittstellenänderung sollen sie diese an dich
zurückmelden. Push, PR-Verwaltung und Merge übernimmst ausschließlich du.

Parallelisierung und Integration
- Parallelisiere nur Aufgaben mit unabhängigen Schreibbereichen.
- server.py darf innerhalb desselben Arbeitsbereichs immer nur einen
  aktiven schreibenden Bearbeiter haben.
- Bei separaten Worktrees integrierst du Änderungen sequenziell und prüfst
  danach sämtliche betroffenen Aufrufer und Tests erneut.
- Während Luna arbeitet, erledige unabhängige Architektur-, Review- oder
  Integrationsvorbereitung. Implementiere dieselbe Aufgabe nicht doppelt.

Verbindliches Sol-Review-Gate
Prüfe jeden Worker-Patch selbst anhand des tatsächlichen Diffs und Codes.
Die Zusammenfassung des Workers und grüne Tests allein sind keine Freigabe.

Prüfe insbesondere:
- vollständige Verlagerung der Fachlogik einschließlich Orchestrierung;
- keine Rückimporte oder indirekten Zugriffe auf server.py;
- keine Server-Callbacks, die weiterhin die ausgelagerte Fachlogik tragen;
- eindeutige Eigentümer für Locks, Caches, Worker und Stream-Zustand;
- erhaltene Transaktionen, Revision-/Hash-Prüfungen und Rollback;
- unveränderte Autorisierungs-, Datenschutz- und Remote-Schreibgrenzen;
- erhaltene Retry-, Cancellation-, Restart- und SSE-Semantik;
- korrekt migrierte Test-Patch-Ziele und aussagekräftige Regressionstests;
- keine dauerhaften Kompatibilitäts-Wrapper oder neuen Sammelmodule.

Dokumentiere pro integriertem Stand:
- geprüften Commit beziehungsweise konkreten Diff-Stand;
- PASS oder FAIL mit Befunden;
- ausgeführte Tests und verbleibende Risiken.

Bei FAIL gib einen konkreten Korrekturauftrag an denselben Worker oder
behebe eine anspruchsvolle Integrationsursache selbst. Prüfe danach erneut.
Jede Änderung nach einem PASS erfordert ein erneutes Review des betroffenen
Umfangs. Erst ein integrierter und von Sol geprüfter Stand darf als fertig gelten.

Fortschritt und Abschluss
- Pflege das Auslagerungsinventar und die Phasen-Checkliste fortlaufend.
- Berichte verbleibende fachliche Definitionen und die Zeilenzahl von
  server.py. Entfernte Zeilen allein gelten nicht als Erfolg.
- Setze die Arbeit selbstständig fort, bis sämtliche Abschlusskriterien
  des Plans erfüllt sind oder eine konkrete externe Voraussetzung fehlt.
- Bewahre für Unterbrechungen den nächsten Schritt, offene Befunde und
  den letzten geprüften Stand im Repository.
- Nutze ausschließlich temporäre Testdaten und gemockte Provider.

PR-Workflow
- Erstelle fachlich zusammenhängende PRs gegen develop.
- Prüfe vor Veröffentlichung den aktuellen Zielbranch und integriere
  erforderliche Änderungen.
- Aktiviere Squash-Auto-Merge erst nach deinem Sol-Review-PASS.
- Bearbeite neue CI- oder Review-Befunde und prüfe den aktualisierten Stand.
- Umgehe keine GitHub-Prüfungen oder Branch-Schutzregeln.
- Melde einen Merge erst nach bestätigtem mergedAt, Merge-Commit und
  dessen Erreichbarkeit auf develop.

Beginne jetzt mit der Bestandsprüfung und P0.
```

## Betriebsregeln

- Haupt-Task: `gpt-5.6-sol`, Reasoning `high`.
- Luna-Worker: `gpt-5.6-luna`, Reasoning `high`, höchstens zwei parallel.
- Sol entscheidet über Schnittstellen, integriert Worker-Patches und gibt den
  finalen PASS/FAIL-Status.
- Ein grüner Worker-Testlauf ersetzt kein Sol-Review des tatsächlichen Diffs.
- Nach jeder Änderung am PR-Head werden Review und relevante Checks erneut
  ausgeführt.
