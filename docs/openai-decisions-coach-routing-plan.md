# Umsetzungsplan: OpenAI Decisions für die Coach-Kontextauswahl

Stand: 18. Oktober 2026. Grundlage: [Ideendokument](openai-decisions-coach-routing-idea.md).
Status: Plan, nicht implementiert.

## Entscheidungen

- **Nur Kontextauswahl, keine Modellauswahl.** Automatische Modellwahl kollidiert
  mit „Preserve explicit model selection“ (AGENTS.md) und ist ausgeschlossen.
  Eine spätere Neubewertung braucht eine eigene Entscheidung der Nutzerin bzw.
  des Nutzers.
- **Output-Token-Limits sind nicht Teil dieses Vorhabens.** Weder Decisions noch
  dieser Plan ändern `max_output_tokens`.
- **Der Router darf nur ergänzen.** Er fügt Abschnitte hinzu oder verlängert
  Horizont und Aktivitätslimit. Er entfernt nie etwas, das die deterministische
  Auswahl gewählt hat.
- **Gate, Outcome und Recovery bleiben deterministisch.** `turn_write_gate.py`,
  `turn_outcome.py` und `conversation_recovery.py` rufen weiterhin
  ausschließlich `select_coach_context` auf. Schreibrechte und
  `retain_pending_request` hängen damit nie von einer Remote-Klassifikation ab.
- **Phasen mit Gates.** Jede Phase ist ein eigener PR. Die nächste Phase beginnt
  erst, wenn das Gate der vorherigen erfüllt ist.

## Evidenz zum Planungszeitpunkt

| Prüfung | Ergebnis |
| --- | --- |
| `python -m unittest discover -s tests -p "test_coach_context_[sr]e*.py"` | 42 Tests OK |
| Vollständige Unit-Suite `python -m unittest discover -s tests` | 6266 Tests OK (19 übersprungen), 715 s |
| Lokaler CLIProxyAPI, `GET /v1/models` | OK, `gpt-6-luna` gelistet |
| Lokaler CLIProxyAPI, synthetisches `POST /v1/decisions` | **HTTP 404** nach 106 ms |
| Offline-Baseline der heutigen Regeln, 37 synthetische Szenarien | 7 Szenarien (19 %) mit fehlendem Bedarf |

Die Baseline wurde mit einem temporären Skript außerhalb des Repositorys
erstellt. Es ruft `select_coach_context` direkt auf und prüft für jedes
Szenario, ob die benötigten Abschnitte, Horizonttage, Aktivitätsanzahlen und die
`retain_pending_request`-Erwartung erfüllt sind.

Ergebnisse der Baseline:

- **Gemischte Anliegen:** 0 Fehlschläge, auch für das Beispiel aus der Idee
  („Woche an Schlaf und Dienstreise anpassen“).
- **Offene Anforderungen:** 0 falsche `retain_pending_request`-Entscheidungen.
- **Alle 7 Fehlschläge fallen in drei regelbehebbare Muster:**
  1. Wetter mehr als 3 Tage voraus („am Samstag“, „Donnerstag“, „Friday“): der
     Horizont bleibt bei 3 Tagen.
  2. Verlauf und Vergleiche („letzte zwei Monate“, „letzter Monat“,
     „Vergleich zu letzter Woche“): `activity_limit` bleibt 1. Die
     Vergleichsfrage wird zusätzlich als `weekly_planning` eingestuft.
  3. Kompletter externer Kalender: `daily_planning_context` enthält nur
     trainingsrelevante Termine.

Einschränkungen: Der Satz ist klein, synthetisch und selbst beschriftet. Ein
Fehlschlag kostet heute eine zusätzliche `read_coach_context`-Runde, keine
falsche Antwort. Live-Aufrufe der offiziellen Decisions-API fanden nicht statt.
Die Nachladerate im echten Betrieb ist unbekannt.

**Folgerung:** Der Nutzen des Routers ist bisher nicht belegt. Die gefundenen
Lücken lassen sich günstiger mit Regeln schließen. Deshalb beginnt der Plan mit
Messung und Regelverbesserung. Decisions folgt nur, wenn danach ein relevanter
Rest bleibt.

## Phase 0: Messen und Regeln verbessern (ohne Decisions)

### PR 0a: Nachlade-Ereignis protokollieren

- Ort: Aufrufer in `structured_tool_round.py` (nur nicht wiederholte,
  erfolgreiche Aufrufe). Das Profil wird in `structured_turn.py` mit denselben
  Argumenten wie in `request_payload.py` bestimmt.
- `JsonLogFormatter` schreibt nur `event`, `message` und das Extra `context`.
  Flache Extras gehen verloren. Deshalb stehen die Felder unter `context`.
  0a verschiebt auch die Felder von `coach_request_sizes` (Nenner der
  Nachladequote) dorthin. `coach_context_projection` und
  `coach_context_budget_applied` in `backend/coach/context.py` haben denselben
  Mangel und bleiben ein eigener Folge-PR.
- Neues strukturiertes Log-Ereignis `coach_context_reload`. Felder:
  - `context_profile` der deterministischen Auswahl
  - angeforderte Abschnittsnamen
  - Tool-Runde
  - Größe des Ergebnisses in Zeichen
  - Kürzungsstatus
- Keine Inhalte, keine Nachrichtentexte, keine Athletenwerte.
- Tests:
  - Das Ereignis wird einmal pro erfolgreichem Aufruf geschrieben.
  - Ungültige Abschnitte erzeugen kein Erfolgsereignis.
  - Das Log enthält keine Kontextinhalte. Prüfung per `assertLogs` und Suche
    nach einem synthetischen Marker.
- Abnahme: Ein Coach-Turn mit gemocktem `read_coach_context` schreibt genau ein
  Ereignis mit den erwarteten Feldern.

### PR 0b: Szenariensatz und Regelkorrekturen

- Neue Fixture `tests/fixtures/coach_context_scenarios.json` mit den
  37 synthetischen Szenarien. Jedes Szenario enthält Kategorie, Nachricht,
  optionalen Dialog, Anhangsflag und Bedarf: Abschnitts-Alternativen,
  Mindesthorizont, Mindestaktivitäten und `retain_pending_request`.
- Neuer Test `tests/test_coach_context_scenarios.py`:
  - Bewertet alle Szenarien gegen `select_coach_context`.
  - Gibt Fehlschläge mit Szenario-ID aus.
  - Kennzeichnet bekannte, akzeptierte Lücken explizit mit `expected_gap`, damit
    neue Regressionen auffallen.
- Regeländerungen in `backend/coach/context_selection.py`:
  1. Wochentage und „Wochenende“ in Verbindung mit Wetter oder Planung setzen
     den Horizont auf mindestens 7 Tage.
  2. Verlaufs- und Vergleichsformulierungen („letzte(n)/vergangene(n) N
     Tage(n)/Wochen/Monate(n)“, „letzter Monat“, „Vergleich“, „compared to“)
     wählen den vollständigen Zeitkontext wie lange Planungszeiträume. Nur so
     bleiben ältere Aktivitäten und `comparisons` erhalten; ein höheres
     `activity_limit` allein reicht nicht. Einzeltage wie „vergangene Nacht“
     bleiben beim Standardprofil. „letzter Woche“ ohne Planungsverb darf nicht
     mehr `weekly_planning` auslösen.
  3. Explizite Kalenderanfragen („Termine“, „mein Kalender“) laden den
     Abschnitt `external_calendar` (iCalendar-Termine) zusätzlich zu
     `daily_planning_context`.
- Bestehende Tests in `test_coach_context_selection.py` bleiben unverändert grün.
  Neue Einzeltests decken die drei Muster und den Fall „letzter Woche“ ab.
- Abnahme: Alle 37 Szenarien erfüllt bzw. mit begründetem `expected_gap`. Die
  bestehenden 42 Kontexttests sind grün. Die Kontextgröße im
  Standardprofil steigt nicht: ein Test misst Standardnachrichten gegen den
  bisherigen Umfang.

### Gate 0 → 1

Etwa zwei Wochen nach Deployment von 0a und 0b die Ereignisse
`coach_context_reload` und `coach_request_sizes` lokal auswerten. Die Auswertung
erfordert die Zustimmung der Athletin bzw. des Athleten und nutzt nur Zähler,
keine Inhalte.

Phase 1 nur beginnen, wenn mindestens eine Bedingung zutrifft:

- Nachladerunden in mehr als etwa 10 % der Turns.
- Nachladen dominiert die Latenz oder die Tokenkosten messbar.

Andernfalls endet das Vorhaben nach Phase 0. Das Ideendokument erhält den
Messbefund.

Zusätzlich vor Phase 1 klären:

- **ZDR und Speicherung:** Wird für `/v1/decisions` gespeichert? Gilt ZDR für
  dieses Konto?
- **Rate- und Größenlimits** der Beta.
- **Endpunkt-Unterstützung:** Unterstützt der konfigurierte `OPENAI_BASE_URL`
  den Endpunkt? Der lokale Proxy antwortet heute mit 404.

## Phase 1: Schattenmodus

Ziel: Router-Ergebnisse protokollieren und vergleichen, ohne Coach-Verhalten zu
ändern.

### Transport: `backend/providers/`

- Neue Methode, etwa `OpenAIResponsesClient.decide(payload, *, timeout)`, oder
  ein kleiner eigener Client, der Basis-URL, Header und HTTP-Transport
  wiederverwendet. Sie unterscheidet sich von `request`:
  - **Kurzer Timeout**, Standard etwa 2 s, statt `response_timeout_seconds`.
  - **Kein `validate_openai_response`**, das `record_status("openai",
    state="error")` auslöst. Ein Router-Fehler darf den OpenAI-Status in der
    PWA nicht auf Fehler setzen.
  - **Eigenes Usage-Label**, etwa die Operation `decisions`, über
    `recorded_usage`. `usage_counts` liest bereits `usage.input_tokens`.
  - **404, 405 oder 501 gelten als „nicht unterstützt“.** Der Router deaktiviert
    sich für die Prozesslaufzeit und schreibt ein Warnereignis
    `coach_router_unsupported`.
  - Fehlertexte von OpenAI werden nicht protokolliert, nur Statuscode und
    Fehlerkategorie.

### Policy: `backend/coach/context_router.py` (neu)

- Ein Aufruf mit mehreren `predicate`-Fragen. Jede Frage entspricht einem
  Bedarf und ist lokal fest auf erlaubte Abschnitte abgebildet. Beispiele:
  - `needs_recovery` → `recovery`, `health`
  - `needs_calendar` → `calendar`
  - `needs_history` → Aktivitäten, mit erhöhtem Limit
  - `needs_long_horizon` → Horizont 14 Tage
  - `needs_library` → Workout-Bibliothek

  Die genauen Namen werden gegen `CONTEXT_SECTIONS` festgelegt.
- Eingabe:
  - aktuelle Nachricht
  - kompakter Dialogausschnitt aus `compact_coach_dialogue`
  - Anhangsflag

  Nicht übertragen werden Athletenwerte, Profil, Provider-Snapshots und
  Anhangsinhalte. Externe Texte sind nicht enthalten.
- Schwellenwerte kommen aus der Konfiguration, kalibriert an einem getrennten
  Teil des Szenariensatzes. Werte unter dem Schwellenwert, `refusal`,
  ungültige Antworten und Fehler ergeben „keine Ergänzung“.
- Ergebnisobjekt: Ergänzungen, Rohwahrscheinlichkeiten auf 2 Stellen
  gerundet, Latenz und Status (`ok`, `refusal`, `timeout`, `unsupported`,
  `invalid`, `error`).

### Integration

- Aufruf genau einmal pro Turn in `structured_turn.py` vor dem Payload-Build
  (aktuell Zeile 118).
- Das Ergebnis wird über `CoachJobStore.merge_receipt(client_turn_id,
  {"context_router": …})` im Turn-Receipt gespeichert. Tool-Runden und
  Wiederaufnahme nach Neustart lesen es von dort und rufen den Router nicht
  erneut auf. Das Receipt ist JSON in `coach_commands.receipt`, daher ist
  **keine Schemaänderung** nötig.
- Übersprungen werden:
  - Turns mit `allow_mutations=False` (Hintergrund und Advisory)
  - Turns ohne gespeicherte Athletennachricht
  - Wiederholungen und Fortsetzungen, bei denen die deterministische Auswahl
    bereits volle Zeitkontexte liefert
- Schattenvergleich: Ereignis `coach_context_router_shadow` mit
  - deterministischem Profil
  - Abschnitten, die der Router ergänzen würde
  - Status und Latenz
  - danach in diesem Turn tatsächlich nachgeladenen Abschnitten (aus
    `coach_context_reload`)

  Keine Inhalte.
- Konfiguration: `COACH_CONTEXT_ROUTER=off|shadow|additive`, Standard `off`.
  Ergänzungen im README-Konfigurationsabschnitt. Eine PWA-Einstellung folgt
  erst, wenn Phase 2 sich lohnt.
- Verdrahtung in `server.py`: nur Konstruktion und Übergabe, keine Logik.

### Tests (Phase 1)

Transport, mit gemocktem HTTP:

- Erfolgreiche Antwort
- `refusal`
- Timeout
- 404 mit Selbstdeaktivierung
- 429 und 5xx
- ungültiges JSON
- falsche Antwortanzahl

Für alle Fälle gilt: Der OpenAI-Providerstatus bleibt unverändert, und Usage
wird unter dem eigenen Label erfasst.

Policy:

- Abbildung von Wahrscheinlichkeiten auf Ergänzungen
- Schwellenwerte
- unbekannte Fragenamen werden ignoriert
- das Ergebnis enthält nie Abschnitte außerhalb von `CONTEXT_SECTIONS`

Integration:

- Ein Turn im Schattenmodus erzeugt einen Payload, der byte-identisch zum
  Modus `off` ist.
- Der Router wird pro Turn genau einmal aufgerufen, auch bei mehreren
  Tool-Runden und nach simulierter Wiederaufnahme.
- Advisory- und Hintergrund-Turns rufen den Router nicht auf.
- Router-Ausfall blockiert den Turn nicht und erzeugt keinen Fehler in der PWA.

Datenschutz:

- Der Router-Payload enthält keine Profil- oder Providerdaten. Prüfung mit
  synthetischen Markern im Kontext.
- Logs enthalten keine Nachrichtentexte.

Architektur:

- Bestehende Architekturtests bleiben grün.
- `backend/` importiert `server.py` nicht.

### Gate 1 → 2

Nach einem Schattenzeitraum mit genehmigtem Live-Zugang:

- Der Router hätte einen großen Teil der tatsächlichen Nachladungen vorweggenommen.
- Er ergänzt selten Unnötiges, gemessen an zusätzlichen Zeichen pro Turn.
- Die p95-Latenz des Routers liegt deutlich unter der Dauer einer eingesparten
  Tool-Runde.
- Der Szenariensatz zeigt keine Verschlechterung. Bewertet wird ein getrennter
  Teil, der nicht zur Kalibrierung verwendet wurde.

Ohne diesen Nachweis bleibt der Modus `shadow` bzw. `off`, und die Phase endet.

## Phase 2: Additive Aktivierung

- `request_payload.py`: Im Modus `additive` werden die Router-Ergänzungen aus dem
  Receipt mit der deterministischen `CoachContextSelection` vereinigt. Die
  Vereinigung ergänzt Abschnitte, nimmt beim Horizont und beim
  Aktivitätslimit jeweils das Maximum und setzt `include_library` per ODER.
  Name und `retain_*`-Felder bleiben deterministisch.
- `structured_tool_round._refreshed_instructions`: dieselbe Vereinigung, ebenfalls
  aus dem gespeicherten Receipt, ohne erneuten Aufruf.
- Unverändert bleiben `turn_write_gate.py`, `turn_outcome.py` (beide Aufrufe)
  und `conversation_recovery.py`.
- Die bestehenden Grenzen bleiben wirksam: Kontextbudget in `context.py`,
  Quellenlabels und das 40.000-Zeichen-Limit beim Nachladen.

### Tests (Phase 2)

- Vereinigung:
  - Die deterministische Auswahl ist immer eine Teilmenge des Ergebnisses.
  - Horizont und Limit sinken nie.
  - `retain_pending_request` ist unverändert.
- Invarianz des Write-Gates: Für alle Szenarien ist die Gate-Entscheidung mit
  und ohne Router identisch. Das gilt auch, wenn der Router alle Fragen mit
  Wahrscheinlichkeit 1 beantwortet.
- Stabilität: Tool-Runde und Wiederaufnahme nutzen dieselben Ergänzungen wie der
  erste Payload.
- Budget: Mit allen Ergänzungen bleiben die Kontextgrenzen eingehalten. Fehlende
  Abschnitte bleiben über `read_coach_context` nachladbar.

## Validierung pro PR

```powershell
python -m unittest discover -s tests -v
python -m compileall -q server.py backend tests
```

Zusätzlich:

- Ruff und mypy gemäß CI-Konfiguration
- Architekturtests
- README-Konfigurationsabschnitt in Phase 1

Es gibt keine Frontend-Änderung, daher sind keine Asset-Versionen und kein
Playwright-Lauf nötig. Es gibt keine Docker- oder Abhängigkeitsänderung. Ein
Docker-Build ist nur nötig, wenn Startup-Verdrahtung in `server.py`
hinzukommt; in Phase 1 ist das der Fall.

## Offene Prüfungen und Risiken

- **Keine Live-Decisions-Aufrufe:** Für die offizielle API fehlt ein
  autorisierter Zugang. Antwortformat, Latenz und `refusal`-Häufigkeit sind nur
  aus der Dokumentation bekannt.
- **Reale Nachladerate unbekannt:** Sie ist erst nach PR 0a messbar.
- **Beta-Risiko:** API-Form, Modell und Preise können sich ändern. Der Router
  muss jederzeit per `off` vollständig abschaltbar bleiben.
- **Kompatible Endpunkte:** Der lokale Proxy unterstützt `/v1/decisions` nicht.
  Der Router darf deshalb nie Voraussetzung für den Coach werden.
