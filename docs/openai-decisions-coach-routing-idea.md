# Idee: OpenAI Decisions für Coach-Kontext und Modellauswahl

Stand: 18. Oktober 2026. Status: bewertet, nicht implementiert.

## Empfehlung

Die OpenAI Decisions API zunächst für die Auswahl des Coach-Kontextes evaluieren.
Automatische Modellauswahl erst danach als getrennten Schritt untersuchen.
Produktionsverhalten und Standardmodell bleiben bis zu einem belegten Vorteil
unverändert.

Decisions liefert Klassifikationen, Wahrscheinlichkeiten und Bewertungen. Laut
offizieller Dokumentation ist die API zum Bewertungszeitpunkt in öffentlicher
Beta, unterstützt `gpt-6-luna` und verwendet `POST /v1/decisions`. Der Preis liegt
bei 0,10 US-Dollar je Million Eingabetokens, ohne Ausgabetokenkosten; regionale
Aufschläge und Langkontextregeln können hinzukommen. Verfügbarkeit, Preise und
Kompatibilität vor einer Umsetzung erneut prüfen.

Quelle: [OpenAI Decisions Guide](https://developers.openai.com/api/docs/guides/decisions).

## Ausgangslage im Repository

- `backend/coach/context_selection.py` wählt Kontext anhand von Schlüsselwörtern
  und Regeln für Rückfragen, Wiederholungen, Zeiträume und Anhänge aus.
- `backend/coach/request_payload.py` verbindet Kontextauswahl und Responses-Payload.
- `backend/coach/context.py` begrenzt Kontext und erhält Quelleninformationen.
  Fehlende Bereiche können über `read_coach_context` nachgeladen werden.
- `backend/settings.py` bietet Luna als feste Modelloption an; ein zusätzliches
  konfiguriertes Modell wird ebenfalls angeboten. Modell und Thinking Level
  sind explizite Einstellungen.
- `backend/coach/chat_turn.py` berücksichtigt gespeicherte Turn-Einstellungen.
  `backend/coach/structured_tool_round.py` berechnet Kontext nach Tool-Aktionen
  erneut. Eine Integration muss beide Pfade konsistent behandeln.

## Nutzen für die Kontextauswahl

Decisions könnte freie Formulierungen und mehrere gleichzeitige Anliegen besser
erkennen als Schlüsselwortregeln. Beispiel: „Passe meine Woche an den schlechten
Schlaf und meine Dienstreise an“ benötigt mehrere Kontextbereiche.

Mehrere unabhängige `predicate`-Fragen eignen sich für diesen Bedarf, etwa nach
Erholungsdaten, Kalender, Trainingsplanung und Aktivitätsdetails. Eine einzelne
exklusive Kategorie würde gemischte Anliegen unnötig einschränken. Die Antworten
werden lokal auf erlaubte Kontextbereiche und begrenzte Profile abgebildet.

Der Router erhält nur die Nachricht, den nötigen Dialogausschnitt und bei Bedarf
Anhang-Metadaten. Den vollständigen Athletenkontext vorher zu übertragen würde
den Einsparzweck unterlaufen. Relevante Einschränkungen und offene Anforderungen
müssen trotzdem zuverlässig erhalten bleiben.

## Nutzen und Grenzen der Modellauswahl

Ein Router könnte später zwischen explizit zugelassenen Modellen unterscheiden.
Mit Luna als bereits günstigem Standardmodell ist eine Kostenersparnis jedoch
nicht selbstverständlich. Eine Einschätzung der Aufgabenschwierigkeit beweist
auch nicht, welches Modell die bessere Coach-Antwort liefert.

Ein möglicher Auto-Modus erfordert deshalb separate Qualitätsvergleiche,
eine begrenzte Modellauswahl und ein Kostenlimit. Manuelle Modell- und
Thinking-Level-Einstellungen behalten Vorrang. Die Wahl bleibt innerhalb eines
Turns einschließlich Toolrunden und Wiederaufnahme stabil und nachvollziehbar.

## Integrationsgrenzen

- Decisions bewertet Bedarf; lokale Regeln bestimmen den tatsächlich erlaubten
  Kontext. Pflichtinformationen, Quellen, Aktualität und lokale Datenautorität
  bleiben erhalten.
- Kontextauswahl autorisiert niemals Schreibaktionen. Bestehende Regeln für
  gespeicherte Athletennachrichten, Änderungen, Receipts, Undo und ausdrücklich
  benannte Intervals-Synchronisierung bleiben unabhängig davon bestehen.
- Bei Unsicherheit, Verweigerung, ungültigen Antworten oder Ausfall wird ein
  konservativer lokaler Kontext gewählt. Fehlendes bleibt nachladbar.
- Schwellenwerte anhand beschrifteter Beispiele bestimmen. Falsches Weglassen
  wichtiger Daten wiegt schwerer als zusätzlicher Kontext; Modellkonfidenz ist
  kein Qualitätsnachweis.
- Externe Texte und Anhänge bleiben untrusted data. Keine Credentials,
  Token-Stores oder vollständigen Athletenpayloads in Router-Diagnosen aufnehmen.
- `/v1/decisions` erweitert den bisherigen Responses-Vertrag ausdrücklich.
  Unterstützung durch konfigurierte `OPENAI_BASE_URL`-Endpunkte separat prüfen;
  keine automatische Umleitung zu einem anderen Anbieter einführen.
- Provider-Transport gehört nach `backend/providers/`, Kontext- und Routingpolicy
  nach `backend/coach/`; `server.py` bleibt Composition Root. Vorhandenen
  HTTP-Transport und sichere Nutzungsmetrik-Erfassung möglichst wiederverwenden.

## Vorgeschlagene Evaluation

1. Einen kleinen, beschrifteten synthetischen Szenariensatz erstellen:
   direkte Fragen, freie Formulierungen, gemischte Anliegen, kurze Rückfragen,
   Themenwechsel, Wiederholungen, Anhänge sowie explizite und lange Zeiträume.
   Auch untrusted Anweisungen in externen Daten berücksichtigen.
2. Decisions zunächst parallel zur bestehenden Auswahl bewerten, ohne deren
   Ergebnis produktiv anzuwenden. Schwellenwerte mit getrennten Kalibrierungs-
   und Bewertungsbeispielen prüfen.
3. Benötigte und tatsächlich ausgewählte Kontextbereiche vergleichen. Besonders
   kritische Auslassungen, Quellenverlust, verlorene Einschränkungen und falsch
   reaktivierte offene Anforderungen untersuchen.
4. Coach-Antwortqualität, zusätzliche Nachlade-Toolrunden, gesamte Tokenkosten und
   Ende-zu-Ende-Latenz einschließlich Router messen. Kontextauswahl und Modellwahl
   getrennt variieren, damit ihre Effekte erkennbar bleiben.
5. Verweigerung, Timeout, inkompatiblen Endpoint und ungültige Antworten testen.
   Ein Ausfall des optionalen Routers darf den Coach nicht blockieren.

Aktivierung erst bei nachgewiesenem Vorteil ohne kritische Regressionen im
Bewertungssatz. Die beworbene Beschleunigung der Klassifikation belegt keine
schnellere gesamte Coach-Antwort. Für die einzelne Athleteninstanz muss der
Nutzen den zusätzlichen Netzwerkaufruf und Wartungsaufwand rechtfertigen.

## Bisherige Evidenz

Bei der Bewertung wurden die genannten Codepfade und die aktuelle offizielle
Dokumentation geprüft. Die vorhandenen Tests für Kontextauswahl und
Kontextbegrenzung bestanden: 29 Tests aus `test_coach_context_selection.py` und
10 Tests aus `test_coach_context_reduction.py`.

Es wurden keine Live-Decisions-Aufrufe oder vergleichenden Coach-Benchmarks
durchgeführt. Verbesserungen bei Qualität, Kosten und Latenz sind Hypothesen.
Die Testergebnisse bestätigen ausschließlich das bestehende Verhalten zum
Bewertungszeitpunkt.
